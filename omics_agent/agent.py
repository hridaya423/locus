import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import anthropic
import httpx

from . import index, samples, store
from .sources import Dataset, cellxgene_diseases, search_cellxgene, search_geo, search_pride

PLANNER = "claude-sonnet-5-5"
WORKER = "claude-haiku-5-5"
MAX_FACTS = 40
POOL = {"GEO": 300, "PRIDE": 50, "CELLxGENE": 50}
INDEX_POOL = 300
REPOSITORIES = {"GEO": search_geo, "PRIDE": search_pride, "CELLxGENE": search_cellxgene}
# Every repository in the local index, with what it holds; only the first three have a live fallback.
ARCHIVES = {
    "GEO": "sequencing and microarray studies of every kind",
    "ArrayExpress": "sequencing and microarray studies, many from European labs and not in GEO",
    "ENA": "raw sequencing studies deposited only in ENA/SRA, without a GEO series",
    "ExpressionAtlas": "curated, reanalysed expression experiments",
    "CELLxGENE": "curated single-cell atlases",
    "PRIDE": "mass-spectrometry proteomics",
    "MassIVE": "mass-spectrometry proteomics and metabolomics, including GNPS natural-product and metabolomics datasets",
    "iProX": "mass-spectrometry proteomics, mostly from Chinese labs",
    "jPOST": "mass-spectrometry proteomics, mostly from Japanese labs",
    "PeptideAtlas": "peptide identifications from proteomics experiments",
    "PanoramaPublic": "targeted proteomics (SRM, PRM, DIA) with Skyline documents",
    "MetaboLights": "metabolomics",
    "MetabolomicsWorkbench": "metabolomics",
    "EGA": "controlled-access human sequencing and genotype data",
    "dbGaP": "controlled-access human genotype and phenotype studies",
    "NODE": "sequencing studies from the Chinese National Omics Data Encyclopedia",
    "EVA": "genetic variation studies",
    "LINCS": "cellular responses to drugs and genetic perturbations",
}
PLANS = Path.home() / ".cache" / "omics-agent" / "plans.json"

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Search terms: the disease or topic plus its synonyms, abbreviations, and closely related names",
        },
        "organism": {
            "type": "string",
            "description": "Latin species name such as 'Homo sapiens', or empty if the question does not restrict species",
        },
        "assays": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Assays that can answer the question, by their common names",
        },
        "repositories": {
            "type": "array",
            "items": {"type": "string", "enum": list(ARCHIVES)},
        },
        "ideal_summary": {
            "type": "string",
            "description": "The summary the ideal dataset for this question would have, written like a GEO series summary",
        },
        "method_notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "At most 3 short notes on what the relevant methods can and cannot measure for this question",
        },
        "matched_assays": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Assays that must come from the same samples to answer the question, by standard name (for example RNA-seq and Ribo-seq for translation efficiency), or empty if the question does not need matched assays",
        },
        "wants_controls": {
            "type": "boolean",
            "description": "True only if the question asks to compare against healthy, untreated, wild-type, or baseline samples. Atlases, discovery, and characterisation questions do not need controls",
        },
        "needs_patient_samples": {
            "type": "boolean",
            "description": "True if the question is about patients, donors, or human or animal tissue, so cell lines and model systems do not answer it",
        },
        "geo_query": {"type": "string", "description": "NCBI GEO DataSets boolean query for the topic only"},
        "pride_keywords": {"type": "array", "items": {"type": "string"}},
        "cellxgene_diseases": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["terms", "organism", "assays", "repositories", "ideal_summary", "method_notes", "matched_assays", "wants_controls", "needs_patient_samples", "geo_query", "pride_keywords", "cellxgene_diseases"],
    "additionalProperties": False,
}

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "hits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "accession": {"type": "string"},
                    "topic": {
                        "type": "string",
                        "enum": ["same", "other"],
                        "description": "'same' if the dataset studies what the question is about: the disease, treatment, genotype, organism, or condition itself; 'other' for different topics, even related ones",
                    },
                    "patient_material": {
                        "type": "string",
                        "enum": ["yes", "no", "unclear"],
                        "description": "Samples come from people (tissue, fluid, or cells taken from donors), not cell lines or animal models",
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["yes", "no"],
                        "description": "The dataset measures one of the data types the question asks for. If the question names a specific technology (for example RNA-seq, single-cell, DIA proteomics), a different technology (for example microarray instead of RNA-seq) is 'no'",
                    },
                    "controls": {
                        "type": "string",
                        "enum": ["yes", "no", "unclear"],
                        "description": "The samples include healthy or non-diseased comparison samples",
                    },
                    "reason": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["accession", "topic", "patient_material", "data_type", "controls", "reason", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hits"],
    "additionalProperties": False,
}

client = anthropic.Anthropic()


def _ask(prompt: str, schema: dict, effort: str, model: str = WORKER, cached: str = "") -> dict:
    """`cached` is a fixed prompt prefix, cached across calls so only the varying part is billed in full."""
    # Sonnet can route a safety decline to a fallback model; Haiku has no server-side fallback.
    fallback = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model == PLANNER else {}
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": [
            *([{"type": "text", "text": cached, "cache_control": {"type": "ephemeral"}}] if cached else []),
            {"type": "text", "text": prompt},
        ]}],
        **fallback,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined the request.")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def plan(question: str) -> dict:
    """The same question always gets the same search plan, so repeated runs are comparable."""
    plans = json.loads(PLANS.read_text()) if PLANS.exists() else {}
    # A changed prompt or schema makes a new key, so stale plans are never reused.
    version = hashlib.sha1((PLAN_PROMPT + json.dumps(PLAN_SCHEMA)).encode()).hexdigest()[:8]
    key = f"{version} {' '.join(question.lower().split())}"
    if key not in plans:
        plans[key] = _plan(question)
        PLANS.parent.mkdir(parents=True, exist_ok=True)
        PLANS.write_text(json.dumps(plans, indent=1))
    return plans[key]


PLAN_PROMPT = """A scientist wants public datasets for a research question, given at the end.

Write the search plan a data curator would write. Each repository has its own query language, so write a separate query for each.

terms: 2-6 names that titles and summaries use for the disease or topic: the standard name, synonyms, and abbreviations. Do not widen to broader parent categories.

geo_query: a boolean query for NCBI GEO DataSets (E-utilities syntax) that finds series about the topic and the study design the question needs. Useful fields: [Title], [Description] (summary and design text), [MeSH Terms], [Attribute] (sample characteristics). Put the disease synonyms on [Title] or [Description], joined with OR. If the question needs a comparison (for example tumour vs normal, or patients vs healthy controls), add the comparison words on [Description]. Do not add organism, entry type, or data type; the code adds those. Keep the query broad enough to return dozens of series, not a handful.
Example for "breast cancer tumour vs normal tissue": ("breast cancer"[Title] OR "breast carcinoma"[Title] OR "breast tumor"[Title]) AND (normal[Description] OR adjacent[Description] OR healthy[Description] OR control[Description])

pride_keywords: 1-4 short keyword phrases for the PRIDE proteomics archive, which matches plain words in project text.

cellxgene_diseases: the labels from this exact CELLxGENE vocabulary that match the disease of the question. Copy them exactly. Return an empty list if none match.
{vocabulary}

assays: the assays that can answer the question, by common name (for example RNA-seq, scRNA-seq, ATAC-seq, ChIP-seq, Ribo-seq, DIA proteomics, bisulfite sequencing). Use the ones the scientist asked for; if they did not say, the ones that fit.

repositories: every repository where those assays could be deposited. Include all that fit; the same kind of data is often spread over several. They hold:
""" + "\n".join(f"- {name}: {holds}" for name, holds in ARCHIVES.items()) + """

ideal_summary: 3-4 sentences describing the ideal dataset for this question, written the way a submitter writes a GEO series summary: what was studied, in which organism and material, with which assay, and the comparison. It is used to find studies whose own summaries say the same thing in other words.

method_notes: at most 3 short notes, written for the scientist, on what the relevant methods can and cannot measure for this question, and which alternative methods would fill a gap. Include a note only when it changes which data fit the question; otherwise return an empty list.

matched_assays: when the question needs several assays from the same samples (for example RNA-seq and Ribo-seq for translation efficiency, or RNA-seq and ATAC-seq from the same cells), list them by standard name; otherwise return an empty list."""


def _plan(question: str) -> dict:
    return _ask(
        f"Research question:\n{question}",
        PLAN_SCHEMA,
        effort="medium",
        model=PLANNER,
        cached=PLAN_PROMPT.format(vocabulary="; ".join(cellxgene_diseases())),
    )


def gather(search_plan: dict, question: str) -> list[Dataset]:
    """Hybrid search over the whole local index; falls back to live repository search if no index exists."""
    repositories = search_plan["repositories"]
    if store.DB.exists():
        terms = search_plan["terms"] + search_plan.get("pride_keywords", [])
        # Embedding search matches study summaries best against summary-like text, so it uses the plan's ideal summary.
        meaning = search_plan.get("ideal_summary") or question
        return index.load(index.search(meaning, terms, repositories, search_plan["organism"], INDEX_POOL))
    with ThreadPoolExecutor() as pool:
        results = pool.map(lambda r: REPOSITORIES[r](search_plan, POOL[r]), [r for r in repositories if r in REPOSITORIES])
    seen: dict[str, Dataset] = {}
    for batch in results:
        for d in batch:
            seen.setdefault(d.accession, d)
    return list(seen.values())


def _geo_facts(topic: str, dataset: Dataset) -> None:
    """Prefer Gemma's expert-curated sample groups; fall back to the raw GEO sample records.
    Counted groups are cached per dataset and topic, so a repeated topic skips the labelling call."""
    # A changed labelling prompt or schema makes a new key, so stale facts are never reused.
    key = f"{topic} #{hashlib.sha1((samples.label_prompt('', '', {}) + json.dumps(samples.LABEL_SCHEMA)).encode()).hexdigest()[:8]}"
    if cached := store.cached_facts(dataset.accession, key):
        dataset.facts = cached
        return
    fields, source, records = samples.gemma_fields(dataset.accession), "samples, groups curated by Gemma", None
    if not fields:
        records = samples.geo_samples(dataset.accession)
        fields, source = samples.geo_fields(dataset.accession), "GEO sample records"
    if not fields:
        return
    labels = _ask(samples.label_prompt(topic, dataset.accession, fields, dataset.text[:2000]), samples.LABEL_SCHEMA, effort="low")
    dataset.facts = samples.count(fields, labels, source, records)
    store.cache_facts(dataset.accession, key, dataset.facts)


def add_facts(search_plan: dict, candidates: list[Dataset]) -> None:
    topic = ", ".join(search_plan["terms"])
    geo = [d for d in candidates if d.source == "GEO"][:MAX_FACTS]
    # NCBI allows 10 requests a second with an API key; each study needs one request.
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda d: _geo_facts(topic, d), geo))


TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"accession": {"type": "string"}, "score": {"type": "integer", "enum": [0, 1, 2, 3]}},
                "required": ["accession", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["scores"],
    "additionalProperties": False,
}

TRIAGE_PROMPT = """Research question:
{question}

Score every dataset below for how likely it answers the question, from its title and the start of its summary:
3 = the disease, the kind of samples, and the study design all match
2 = the disease matches, the samples or design partly match
1 = related topic only, or a cell line or model system when the question is about patients
0 = off topic

{listing}"""


def triage(question: str, candidates: list[Dataset], keep: int) -> list[Dataset]:
    """A cheap first ranking over the whole pool: Haiku scores titles and summary openings in parallel batches."""
    batches = [candidates[i:i + 25] for i in range(0, len(candidates), 25)]

    def score(batch: list[Dataset]) -> list[dict]:
        listing = "\n".join(f"{d.accession} | {d.source} | {d.title} | {d.text[len(d.title):][:250].strip()}" for d in batch)
        return _ask(TRIAGE_PROMPT.format(question=question, listing=listing), TRIAGE_SCHEMA, effort="low")["scores"]

    with ThreadPoolExecutor() as pool:
        scores = {s["accession"]: s["score"] for batch in pool.map(score, batches) for s in batch}
    ranked = sorted(candidates, key=lambda d: scores.get(d.accession, 0), reverse=True)
    return [d for d in ranked if scores.get(d.accession, 0) > 0][:keep]


JUDGE_PROMPT = """Research question:
{question}

Candidate datasets:
{listing}

Answer the four checks for every candidate from its text. Answer 'unclear' when the text does not say.
Give a one-sentence reason a non-expert can follow. For evidence, copy one short exact phrase from that candidate's text that supports the checks."""


def screen(question: str, candidates: list[Dataset]) -> dict[str, dict]:
    """Haiku answers the four checks for every candidate, in parallel batches."""
    batches = [candidates[i:i + 8] for i in range(0, len(candidates), 8)]

    def check(batch: list[Dataset]) -> list[dict]:
        listing = [{"accession": d.accession, "source": d.source, "modality": d.modality, "organism": d.organism, "text": d.text[:1500]} for d in batch]
        return _ask(JUDGE_PROMPT.format(question=question, listing=json.dumps(listing, indent=1)), JUDGE_SCHEMA, effort="medium")["hits"]

    with ThreadPoolExecutor() as pool:
        verdicts = [v for batch in pool.map(check, batches) for v in batch]
    known = {d.accession for d in candidates}
    return {v["accession"]: v for v in verdicts if v["accession"] in known}


def relevant(candidates: list[Dataset], verdicts: dict[str, dict]) -> list[Dataset]:
    """Candidates about the same disease, the most promising first."""
    keep = [d for d in candidates if verdicts.get(d.accession, {}).get("topic") == "same"]
    passed = lambda d: sum(verdicts[d.accession][k] == "yes" for k in ("patient_material", "data_type", "controls"))
    return sorted(keep, key=passed, reverse=True)


def grade(search_plan: dict, datasets: list[Dataset], verdicts: dict[str, dict]) -> list[dict]:
    rank = {"strong": 0, "partial": 1}
    hits = []
    for dataset in datasets:
        v = verdicts[dataset.accession]
        checks = _relevant_checks(_apply_facts(v, dataset.facts, search_plan), search_plan)
        fit = _grade(checks)
        if fit == "none":
            continue
        quote_found = v["evidence"].lower() in dataset.text.lower()
        hits.append(asdict(dataset) | {
            "fit": fit,
            "checks": {k: checks[k] for k in ("topic", "patient_material", "data_type", "controls")},
            "reason": v["reason"],
            "evidence": v["evidence"] if quote_found else "",
        })
    return sorted(hits, key=lambda h: rank[h["fit"]])


def _apply_facts(checks: dict, facts: dict | None, search_plan: dict) -> dict:
    """Counted sample facts replace the model's reading of the summary."""
    checks = dict(checks)
    norm = lambda name: re.sub(r"[^a-z0-9]", "", name.lower())
    counted = {norm(a) for a in (facts or {}).get("libraries") or (facts or {}).get("assays", [])}
    if counted and any(norm(a) not in counted for a in search_plan.get("matched_assays", [])):
        checks["data_type"] = "no"
    if facts and facts["has_control"] is not None:
        checks["controls"] = "yes" if facts["has_control"] else "no"
    if facts and facts["sample_type"] != "unknown":
        patient = facts["sample_type"] in ("patient_tissue", "patient_biofluid", "primary_cells")
        checks["patient_material"] = "yes" if patient else "no"
    return checks


def _relevant_checks(checks: dict, search_plan: dict) -> dict:
    """Checks the question does not ask for are marked n/a, so they neither count nor show as warnings."""
    checks = dict(checks)
    if not search_plan.get("needs_patient_samples"):
        checks["patient_material"] = "n/a"
    if not search_plan["wants_controls"]:
        checks["controls"] = "n/a"
    return checks


def _grade(checks: dict) -> str:
    """Only a confirmed failure downgrades a dataset; 'unclear' means the records did not say, not that the study fails."""
    if checks["topic"] != "same" or checks["patient_material"] == "no":
        return "none"
    if checks["data_type"] == "no" or checks["controls"] == "no":
        return "partial"
    return "strong"


def add_papers(hits: list[dict]) -> None:
    """Attach the linked paper (title, journal, year) to each hit, from one Europe PMC query per 25 IDs."""
    first = {h["accession"]: next(iter(h["papers"]), None) for h in hits}
    ids = sorted({p for p in first.values() if p})
    found: dict[str, dict] = {}
    for start in range(0, len(ids), 25):
        chunk = ids[start:start + 25]
        query = " OR ".join(f"(EXT_ID:{p[5:]} AND SRC:MED)" if p.startswith("pmid:") else f'DOI:"{p[4:]}"' for p in chunk)
        try:
            results = httpx.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={"query": query, "format": "json", "resultType": "lite", "pageSize": 100},
                timeout=30,
            ).json()["resultList"]["result"]
        except (httpx.HTTPError, ValueError, KeyError):
            continue
        for r in results:
            paper = {
                "title": r.get("title", "").rstrip("."),
                "journal": r.get("journalTitle") or r.get("bookOrReportDetails", {}).get("publisher", ""),
                "year": r.get("pubYear", ""),
                "url": f"https://europepmc.org/article/MED/{r['pmid']}" if r.get("pmid") else f"https://doi.org/{r.get('doi', '')}",
            }
            if r.get("pmid"):
                found[f"pmid:{r['pmid']}"] = paper
            if r.get("doi"):
                found[f"doi:{r['doi'].lower()}"] = paper
    for h in hits:
        h["paper"] = found.get(first[h["accession"]])


def _pmid_for_doi(doi: str) -> str | None:
    results = httpx.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": f'DOI:"{doi}"', "format": "json", "resultType": "lite"},
        timeout=30,
    ).json()["resultList"]["result"]
    return results[0].get("pmid") if results else None


def bundles(hits: list[dict]) -> list[list[dict]]:
    """Group hits that come from the same paper, across repositories."""
    dois = {p[4:] for h in hits for p in h["papers"] if p.startswith("doi:")}
    with ThreadPoolExecutor() as pool:
        doi_to_pmid = dict(zip(dois, pool.map(_pmid_for_doi, dois)))
    by_paper: dict[str, list[dict]] = {}
    for h in hits:
        keys = {f"pmid:{doi_to_pmid[p[4:]]}" if doi_to_pmid.get(p[4:]) else p for p in h["papers"]}
        for key in keys:
            by_paper.setdefault(key, []).append(h)
    groups = [g for g in by_paper.values() if len({h["source"] for h in g}) > 1]
    return [g for i, g in enumerate(groups) if g not in groups[:i]]


def run(question: str, limit: int = 40, progress=lambda stage, data: None) -> dict:
    """The whole search: plan, gather wide, screen, count samples for survivors, grade, bundle.
    Shared by the CLI, API, and MCP server."""
    search_plan = plan(question)
    progress("plan", search_plan)
    pool = gather(search_plan, question)
    progress("candidates", {"count": len(pool)})
    candidates = triage(question, pool, limit)
    verdicts = screen(question, candidates)
    keep = relevant(candidates, verdicts)
    progress("screened", {"count": len(keep)})
    add_facts(search_plan, keep)
    progress("facts", {"count": sum(1 for d in keep if d.facts)})
    hits = grade(search_plan, keep, verdicts)
    add_papers(hits)
    groups = bundles(hits)
    return {
        "question": question,
        "plan": search_plan,
        "candidates": len(pool),
        "datasets": [{k: v for k, v in h.items() if k != "text"} for h in hits],
        "same_paper": [[h["accession"] for h in g] for g in groups],
    }
