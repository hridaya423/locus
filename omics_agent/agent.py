import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import anthropic
import httpx

from . import answer, assay, compare, index, methods, samples, samplesheet, store
from .sources import Dataset, cellxgene_diseases, download_plan, search_cellxgene, search_geo, search_pride

PLANNER = "claude-sonnet-5-5"
WORKER = "claude-haiku-5-5"
# How many triaged candidates are screened, and how many GEO datasets get their samples counted. In tests on five
# questions, ranks 41-60 still passed the screen at close to the rate of ranks 1-40 on rich topics (IPF: 12 of 20,
# including classic datasets), and added little but cost nothing in time on sparse ones.
KEEP = 60
MAX_FACTS = 60
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
            "description": "One Latin species name such as 'Homo sapiens', or empty if the question does not restrict species or accepts more than one",
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

CHECKS = {
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
}


def _numbered(properties: dict) -> dict:
    """A list of answers keyed by each candidate's number, so the model never has to copy accessions back."""
    item = {"n": {"type": "integer", "description": "The candidate's number in the list"}} | properties
    return {
        "type": "object",
        "properties": {"answers": {"type": "array", "items": {"type": "object", "properties": item, "required": list(item), "additionalProperties": False}}},
        "required": ["answers"],
        "additionalProperties": False,
    }


TRIAGE_SCHEMA = _numbered({"score": {"type": "integer", "enum": [0, 1, 2, 3]}})
# The written reason comes first so the checks follow from it; answers without it were inconsistent.
SCREEN_SCHEMA = _numbered({"reason": {"type": "string"}} | CHECKS | {"evidence": {"type": "string"}})

client = anthropic.Anthropic()

# Set LOCAL_LLM_URL (an OpenAI-compatible base URL such as a vLLM server's http://localhost:8000/v1) to run every
# search call on a local model instead of Claude. LOCAL_LLM_MODEL names the served model. Thinking is off unless
# LOCAL_LLM_THINK=1, because a local model is far slower than the API and the calls run in parallel batches.
LOCAL_LLM_URL = os.environ.get("LOCAL_LLM_URL", "").rstrip("/")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "")
LOCAL_LLM_THINK = os.environ.get("LOCAL_LLM_THINK") == "1"


def _ask_local(prompt: str, schema: dict, cached: str, think: bool) -> dict:
    """The same contract as `_ask`, on a local model; the server constrains decoding to the JSON schema."""
    response = httpx.post(
        f"{LOCAL_LLM_URL}/chat/completions",
        json={
            "model": LOCAL_LLM_MODEL,
            "max_tokens": 16000,
            "temperature": 0,
            "messages": [{"role": "user", "content": "\n\n".join(filter(None, (cached, prompt)))}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}},
            "chat_template_kwargs": {"enable_thinking": think and LOCAL_LLM_THINK},
        },
        timeout=1800,
    )
    response.raise_for_status()
    choice = response.json()["choices"][0]
    if choice["finish_reason"] == "length":
        raise RuntimeError("The local model ran out of tokens before finishing its answer.")
    return json.loads(choice["message"]["content"])


def _ask(prompt: str, schema: dict, effort: str, model: str = WORKER, cached: str = "", think: bool = True) -> dict:
    """`cached` is a fixed prompt prefix, cached across calls so only the varying part is billed in full.
    `think=False` skips the thinking pass, for coarse scoring where speed matters more than reasoning.
    Haiku 5.5 rejects sampling settings such as temperature 0, so repeatability comes from remembering answers."""
    if LOCAL_LLM_URL:
        return _ask_local(prompt, schema, cached, think)
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
        **({} if think else {"thinking": {"type": "disabled"}}),
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
        # Every search filters on one species; a list such as 'Homo sapiens, Mus musculus' would match nothing.
        if re.search(r",|;|/|\band\b|\bor\b", plans[key]["organism"]):
            plans[key]["organism"] = ""
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
    if store.has_index():
        terms = search_plan["terms"] + search_plan.get("pride_keywords", [])
        # Embedding search matches study summaries best against summary-like text, so it uses the plan's ideal summary.
        meaning = search_plan.get("ideal_summary") or question
        return index.load(index.search(meaning, terms, repositories, search_plan["organism"], INDEX_POOL, asked=question))
    with ThreadPoolExecutor() as pool:
        results = pool.map(lambda r: REPOSITORIES[r](search_plan, POOL[r]), [r for r in repositories if r in REPOSITORIES])
    seen: dict[str, Dataset] = {}
    for batch in results:
        for d in batch:
            seen.setdefault(d.accession, d)
    return list(seen.values())


def _label_key(topic: str) -> str:
    """A changed labelling prompt or schema makes a new key, so stale facts and labels are never reused."""
    return f"{topic} #{hashlib.sha1((samples.label_prompt('', '', {}) + json.dumps(samples.LABEL_SCHEMA)).encode()).hexdigest()[:8]}"


def geo_labels(topic: str, accession: str, summary: str) -> dict:
    """Haiku's reading of which GEO sample fields mark case, control and assay; cached so the search and the samplesheet export agree."""
    key = f"labels {_label_key(topic)}"
    fields = samples.geo_fields(accession)
    if not (labels := store.cached_facts(accession, key)):
        labels = _ask(samples.label_prompt(topic, accession, fields, summary[:2000]), samples.LABEL_SCHEMA, effort="low")
        store.cache_facts(accession, key, labels)
    return samples.resolve_labels(labels, fields)


def samplesheet_files(accession: str, topic: str) -> dict[str, str]:
    """The nf-core/riboseq samplesheet, contrasts and README for one GEO series, by file name."""
    records = samples.geo_records(accession)
    labels = geo_labels(topic, accession, store.summary(accession))
    runs = samplesheet.ena_runs(sorted({r["srx"] for r in records if r["srx"]}))
    return samplesheet.build(accession, records, labels, runs, assay.library_types(accession))


def export_samplesheet(accession: str, topic: str) -> bytes:
    """A zip of samplesheet_files, for download."""
    return samplesheet.zipped(accession, samplesheet_files(accession, topic))


CONTRAST_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "quote_1": {"type": "string"},
        "quote_2": {"type": "string"},
        "name_1": {"type": "string"},
        "name_2": {"type": "string"},
        "status": {"type": "string", "enum": ["same", "related", "differs", "unknown"]},
    },
    "required": ["reason", "quote_1", "quote_2", "name_1", "name_2", "status"],
    "additionalProperties": False,
}

CONTRAST_PROMPT = """Research topic: {topic}

Two datasets were labelled with the samples that count as cases and the samples that count as controls. Each contrast is written "case labels vs control labels", copied from the sample records; # stands for any number in a title.

Dataset 1: {title_1}
Contrast: {contrast_1}

Dataset 2: {title_2}
Contrast: {contrast_2}

Do the two datasets test the same contrast? Ignore species, cell type and technology; compare only the perturbation or condition and the baseline it is compared with.
same: the same perturbation or condition against the same kind of baseline.
related: different perturbations of the same kind, expected to act on the same pathway in the same direction (for example two inhibitors of one target).
differs: different conditions, or a different baseline.
unknown: the labels do not say enough.

reason: one sentence for a scientist saying what the two contrasts have in common or how they differ, for example "Both compare an mTOR inhibitor with vehicle." Name the conditions, never the datasets: no numbers, no accessions.
quote_1 and quote_2: one short phrase copied exactly from that dataset's contrast, the part you compared.
name_1 and name_2: that dataset's contrast in plain words, "condition vs baseline", using its title where the labels are generic (for example "lung fibrosis vs no lung fibrosis" for the labels "Disease vs Normal")."""


def _profile(accession: str, topic: str) -> compare.Profile:
    dataset = next(iter(index.load([accession])), None)
    if not dataset:
        raise LookupError(f"{accession} is not in the locus index")
    records, labels, facts, files = [], None, dataset.facts, None
    if dataset.source == "GEO" and (records := samples.geo_records(accession)):
        labels = geo_labels(topic, accession, dataset.text)
        facts = samples.count(samples.geo_fields(accession), labels, "GEO sample records", [r["fields"] for r in records])
        files = samples.geo_files(accession)
    return compare.build_profile(asdict(dataset), records, labels, facts, files, store.metadata([accession]).get(accession))


def _contrast(a: compare.Profile, b: compare.Profile, topic: str) -> dict:
    """Haiku classifies the two contrasts and quotes what it compared; the quotes are kept only if the labels contain them.
    The pair is judged in accession order and cached under both accessions, so A-B and B-A share one answer."""
    if not (a.contrast and b.contrast):
        return {"status": "unknown", "note": f"No case and control labels for {' and '.join(p.accession for p in (a, b) if not p.contrast)}."}
    one, two = sorted((a, b), key=lambda p: p.accession)
    prompt = CONTRAST_PROMPT.format(topic=topic, title_1=one.title, contrast_1=one.contrast, title_2=two.title, contrast_2=two.contrast)
    key = f"contrast {topic} #{hashlib.sha1((prompt + json.dumps(CONTRAST_SCHEMA)).encode()).hexdigest()[:8]}"
    if not (judged := store.cached_facts(f"{one.accession}+{two.accession}", key)):
        judged = _ask(prompt, CONTRAST_SCHEMA, effort="low")
        store.cache_facts(f"{one.accession}+{two.accession}", key, judged)
    quoted = {one.accession: judged["quote_1"], two.accession: judged["quote_2"]}
    names = {one.accession: judged["name_1"], two.accession: judged["name_2"]}
    quotes = [f'"{quoted[p.accession]}"' for p in (a, b) if quoted[p.accession] and quoted[p.accession].casefold() in p.contrast.casefold()]
    # Pairs are judged in accession order, so a reason that says "dataset 1" points at the wrong side in the dialog.
    if re.search(r"\bdataset\b|\b[A-Z]{2,4}\d{3,}\b", judged["reason"], re.I):
        # The two contrasts are already named in the row, so the note only says how they relate.
        note = {"same": "The same condition against the same baseline.", "related": "Similar conditions that differ in detail; see the two contrasts.",
                "differs": "Different conditions or baselines; see the two contrasts."}.get(judged["status"], "The records do not say enough to judge.")
        return {"status": judged["status"], "note": note, "names": names}
    return {"status": judged["status"], "note": f"{judged['reason']} ({'; '.join(quotes)})" if quotes else judged["reason"], "names": names}


def compare_datasets(a: str, b: str, topic: str) -> compare.Comparison:
    """Whether two datasets can be pooled, compared as effects, or not combined. Code computes the verdict from the
    records; the model only judges whether the two contrasts match."""
    found = {d.accession: d for d in index.load([a, b])}
    if missing := [accession for accession in (a, b) if accession not in found]:
        raise LookupError(f"{' and '.join(missing)} not in the locus index")
    if shared := set(found[a].papers) & set(found[b].papers):
        raise ValueError(f"{a} and {b} come from the same paper ({sorted(shared)[0]}), so they are parts of one study.")
    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = workers.map(lambda accession: _profile(accession, topic), (a, b))
    contrast = _contrast(first, second, topic)
    # The names are only displayed; the raw labels in `contrast` stay the evidence the quotes were checked against.
    # GEO samples have stable GSM accessions, so a sample in both series is the same sample.
    shared = len({r["gsm"] for r in samples.geo_records(a)} & {r["gsm"] for r in samples.geo_records(b)}) if found[a].source == found[b].source == "GEO" else None
    first, second = (replace(p, contrast_name=contrast.get("names", {}).get(p.accession), shared=shared) for p in (first, second))
    return compare.compare(first, second, contrast)


def _geo_facts(topic: str, dataset: Dataset) -> None:
    """Prefer Gemma's expert-curated sample groups; fall back to the raw GEO sample records.
    Only the labelling call is cached; counts are recomputed, so a counting fix applies to every past search."""
    if fields := samples.gemma_fields(dataset.accession):
        key = f"gemma labels {_label_key(topic)}"
        labels = store.cached_facts(dataset.accession, key)
        if not labels:
            labels = _ask(samples.label_prompt(topic, dataset.accession, fields, dataset.text[:2000]), samples.LABEL_SCHEMA, effort="low")
            store.cache_facts(dataset.accession, key, labels)
        dataset.facts = samples.count(fields, labels, "samples, groups curated by Gemma")
    elif fields := samples.geo_fields(dataset.accession):
        labels = geo_labels(topic, dataset.accession, dataset.text)
        dataset.facts = samples.count(fields, labels, "GEO sample records", samples.geo_samples(dataset.accession))


HEALTHY = re.compile(r"control|healthy|normal|non-?diabet|donor|tolerant|\bNGT\b|\bNC\b", re.I)


def _workbench_facts(dataset: Dataset) -> None:
    """Cases and controls counted from a Metabolomics Workbench or MetaboLights study's sample table: the factor with a
    control-like level, as its dataset page marks them."""
    from . import record, volcano

    try:
        rec, pick = record.record(dataset.accession), volcano.groups(dataset.accession)["default"]
    except (httpx.HTTPError, ValueError, KeyError):
        return
    # Patients against controls only: a time course (Baseline against Follow-Up) is not a case-control count.
    if not rec or not rec["samples"] or not pick or not any(HEALTHY.search(lv) for lv in pick["control"]):
        return
    i, rows = rec["samples"]["columns"].index(pick["factor"]), rec["samples"]["rows"]
    case, control = sum(r[i] in pick["case"] for r in rows), sum(r[i] in pick["control"] for r in rows)
    dataset.facts = {"case": case, "control": control, "mixed": 0, "has_control": control > 0, "sample_type": "unknown", "tissue": "", "assays": [],
                     "library": {}, "libraries": {}, "source": f"{len(rows)} {'Metabolomics Workbench' if dataset.source == 'MetabolomicsWorkbench' else 'MetaboLights'} sample records ({pick['factor']})"}


def _fetch_samples(dataset: Dataset) -> None:
    """Warm the on-disk sample cache: Gemma's curated groups if they exist, else the GEO sample records."""
    if dataset.source == "GEO" and not samples.gemma_fields(dataset.accession):
        samples.geo_fields(dataset.accession)


def prefetch(pool: list[Dataset]) -> None:
    """Start fetching sample records for the likeliest GEO candidates while the screen runs; NCBI allows 10 requests a second."""
    workers = ThreadPoolExecutor(max_workers=10)
    for d in [d for d in pool if d.source == "GEO"][:MAX_FACTS]:
        workers.submit(_fetch_samples, d)
    workers.shutdown(wait=False)


def add_facts(search_plan: dict, candidates: list[Dataset]) -> None:
    topic = ", ".join(search_plan["terms"])
    geo = [d for d in candidates if d.source == "GEO"][:MAX_FACTS]
    with ThreadPoolExecutor(max_workers=10) as workers:
        list(workers.map(_fetch_samples, geo))
    # Fetching is rate-limited; labelling is not, so every labelling call runs at once.
    with ThreadPoolExecutor(max_workers=len(geo) or 1) as workers:
        list(workers.map(lambda d: _geo_facts(topic, d), geo))
    workbench = [d for d in candidates if d.source in ("MetabolomicsWorkbench", "MetaboLights")][:MAX_FACTS]
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(_workbench_facts, workbench))


TRIAGE_PROMPT = """Research question:
{question}

Score every numbered dataset below for how likely it answers the question, from its title and the start of its summary:
3 = the disease, the kind of samples, and the study design all match
2 = the disease matches, the samples or design partly match
1 = related topic only, or a cell line or model system when the question is about patients
0 = off topic

{listing}"""

SCREEN_PROMPT = """Research question:
{question}

Candidate datasets:
{listing}

For every numbered candidate, give a one-sentence reason a non-expert can follow, then answer the four checks from its text. Answer 'unclear' when the text does not say. For evidence, copy one short exact phrase from that candidate's text that supports the checks."""

TRIAGE_BATCH = 25
SCREEN_BATCH = 4


def _listing(batch: list[Dataset], chars: int) -> str:
    return "\n\n".join(f"{n}. {d.accession} | {d.source} | {d.modality} | {d.organism}\n{d.text[:chars]}" for n, d in enumerate(batch))


def _answers(name: str, template: str, question: str, schema: dict, candidates: list[Dataset], size: int, chars: int, effort: str, think: bool = True) -> dict[str, dict]:
    """Each batch in its own parallel call; answers are matched back to datasets by their number in the batch.
    Answers are remembered per question, so a repeated search reuses them and only new candidates are asked about;
    a changed prompt or schema starts afresh."""
    version = hashlib.sha1((template + json.dumps(schema)).encode()).hexdigest()[:8]
    slot = "question " + hashlib.sha1(" ".join(question.lower().split()).encode()).hexdigest()[:16]
    kind = f"{name} answers #{version}"
    known = store.cached_facts(slot, kind) or {}
    missing = [d for d in candidates if d.accession not in known]
    batches = [missing[i:i + size] for i in range(0, len(missing), size)]

    def ask(batch: list[Dataset]) -> dict[str, dict]:
        prompt = template.replace("{question}", question).replace("{listing}", _listing(batch, chars))
        return {batch[a["n"]].accession: a for a in _ask(prompt, schema, effort=effort, think=think)["answers"] if 0 <= a["n"] < len(batch)}

    with ThreadPoolExecutor(max_workers=len(batches) or 1) as workers:
        known |= {k: v for part in workers.map(ask, batches) for k, v in part.items()}
    if missing:
        store.cache_facts(slot, kind, known)
    return {d.accession: known[d.accession] for d in candidates if d.accession in known}


def triage(question: str, candidates: list[Dataset], keep: int) -> list[Dataset]:
    """A cheap first ranking over the whole pool: Haiku scores titles and summary openings in parallel batches."""
    # Thinking off: in tests it changed the top 40 about as much as two thinking runs differ, at a third of the time.
    scores = {k: v["score"] for k, v in _answers("triage", TRIAGE_PROMPT, question, TRIAGE_SCHEMA, candidates, TRIAGE_BATCH, 250, "low", think=False).items()}
    ranked = sorted(candidates, key=lambda d: scores.get(d.accession, 0), reverse=True)
    return [d for d in ranked if scores.get(d.accession, 0) > 0][:keep]


def screen(question: str, candidates: list[Dataset]) -> dict[str, dict]:
    """Haiku answers the four checks for every candidate, with a reason and a quoted phrase, in small parallel batches."""
    return _answers("screen", SCREEN_PROMPT, question, SCREEN_SCHEMA, candidates, SCREEN_BATCH, 1500, "medium")


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
        checks = _relevant_checks(_apply_facts(v, dataset.facts, search_plan, dataset.text), search_plan)
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


def _apply_facts(checks: dict, facts: dict | None, search_plan: dict, text: str = "") -> dict:
    """Counted sample facts replace the model's reading of the summary. Missing one of the matched assays fails the data
    type unless the study's own text names another assay the plan accepts (TrIP-seq's polysome fractions, GSE69352)."""
    checks = dict(checks)
    norm = lambda name: re.sub(r"[^a-z0-9]", "", name.lower())
    counted = {norm(a) for a in (facts or {}).get("libraries") or (facts or {}).get("assays", [])}
    matched = {norm(a) for a in search_plan.get("matched_assays", [])}
    alternatives = {norm(a) for a in search_plan.get("assays", [])} - matched - {"rnaseq"}
    named = {norm(found[0]) for sentence in assay._sentences(text) for found in assay._match(sentence, text)}
    if counted and not matched <= counted and not alternatives & named:
        checks["data_type"] = "no"
    if facts and facts["has_control"] is not None:
        checks["controls"] = "yes" if facts["has_control"] else "no"
    if facts and facts.get("methods") and (used := methods.meets(search_plan.get("assays", []), facts["methods"])):
        checks["data_type"] = used
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


def paper_details(ids: list[str]) -> dict[str, dict]:
    """Title, journal, year and link for each `pmid:` or `doi:` ID that Europe PMC knows, from one query per 25 IDs."""
    ids = sorted(set(ids))
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
    return found


def add_papers(hits: list[dict]) -> None:
    """Attach the linked paper (title, journal, year) to each hit."""
    first = {h["accession"]: next(iter(h["papers"]), None) for h in hits}
    found = paper_details([p for p in first.values() if p])
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
    """Group hits that are one study in several repositories: the same paper, or the same title (ArrayExpress and ENA
    list one submission under two accessions, often with no paper)."""
    dois = {p[4:] for h in hits for p in h["papers"] if p.startswith("doi:")}
    with ThreadPoolExecutor() as pool:
        doi_to_pmid = dict(zip(dois, pool.map(_pmid_for_doi, dois)))
    by_key: dict[str, list[dict]] = {}
    for h in hits:
        keys = {f"pmid:{doi_to_pmid[p[4:]]}" if doi_to_pmid.get(p[4:]) else p for p in h["papers"] if p != "pmid:1"}
        if len(title := re.sub(r"[^a-z0-9]", "", h["title"].lower())) >= 25:
            keys.add(f"title:{title}")
        for key in keys:
            by_key.setdefault(key, []).append(h)
    groups: list[list[dict]] = []
    for g in (g for g in by_key.values() if len({h["source"] for h in g}) > 1):
        touching = [o for o in groups if any(h in o for h in g)]
        merged = [h for o in touching for h in o] + [h for h in g if not any(h in o for o in touching)]
        groups = [o for o in groups if o not in touching] + [merged]
    return groups


def run(question: str, limit: int = KEEP, progress=lambda stage, data: None) -> dict:
    """The whole search: plan, gather wide, screen, count samples for survivors, grade, bundle.
    Shared by the CLI, API, and MCP server."""
    search_plan = plan(question)
    progress("plan", search_plan)
    pool = gather(search_plan, question)
    progress("candidates", {"count": len(pool)})
    candidates = triage(question, pool, limit)
    prefetch(candidates)
    verdicts = screen(question, candidates)
    keep = relevant(candidates, verdicts)
    progress("screened", {"count": len(keep)})
    add_facts(search_plan, keep)
    progress("facts", {"count": sum(1 for d in keep if d.facts)})
    hits = grade(search_plan, keep, verdicts)
    add_papers(hits)
    for h in hits:
        h["download_plan"] = download_plan(h["accession"], h["source"], h["url"])
    groups = bundles(hits)
    return {
        "answer": answer.pick(search_plan, hits),
        "question": question,
        "plan": search_plan,
        "candidates": len(pool),
        "datasets": [{k: v for k, v in h.items() if k != "text"} for h in hits],
        "same_paper": [[h["accession"] for h in g] for g in groups],
    }
