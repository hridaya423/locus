import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import anthropic
import httpx

from . import answer, assay, compare, index, methods, samples, samplesheet, sdrf, store
from .sources import Dataset, cellxgene_diseases, download_plan, search_cellxgene, search_geo, search_pride

# OMICS_PLANNER_MODEL swaps the planner, for example to claude-haiku-5-5 so a whole search runs on Haiku.
PLANNER = os.environ.get("OMICS_PLANNER_MODEL") or "claude-sonnet-5-5"
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


def _sized(schema: dict, size: int) -> dict:
    """A numbered schema whose answers list must hold exactly `size` answers, one per candidate in the batch. Without
    it, the local model closed the list early in about one batch in ten when its answer could not be pretty-printed."""
    answers = schema["properties"]["answers"] | {"minItems": size, "maxItems": size}
    return schema | {"properties": schema["properties"] | {"answers": answers}}


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
# LOCAL_LLM_COMPACT_JSON=1 sends the server a grammar that allows no newlines or indentation between JSON tokens
# instead of the schema, so an answer is not pretty-printed: the same fields and values in about a third fewer output
# tokens, which is what sets a stage's wall time. The grammars are built from the schemas by scripts/build_grammars.py
# (xgrammar, any_whitespace=False) into grammars.json; a schema without one falls back to the schema. The plan schema has
# none on purpose: it is one call per question, and the constrained plans repeated or lost search terms. The same effect
# server-wide, without this flag, is vLLM's --structured-outputs-config disable_any_whitespace=true (then also for plans).
LOCAL_LLM_COMPACT_JSON = os.environ.get("LOCAL_LLM_COMPACT_JSON") == "1"
GRAMMARS_FILE = Path(__file__).with_name("grammars.json")
GRAMMARS: dict[str, str] = json.loads(GRAMMARS_FILE.read_text()) if LOCAL_LLM_COMPACT_JSON and GRAMMARS_FILE.exists() else {}
# PLAN_LLM_URL, PLAN_LLM_MODEL and PLAN_LLM_KEY send only the planning call to another OpenAI-compatible service, for
# example Gemini's (https://generativelanguage.googleapis.com/v1beta/openai), while every other call stays local.
# Planning is one call per question and sets the search terms, so it is where a stronger model helps most.
PLAN_LLM_URL = os.environ.get("PLAN_LLM_URL", "").rstrip("/")
PLAN_LLM_MODEL = os.environ.get("PLAN_LLM_MODEL", "")
PLAN_LLM_KEY = os.environ.get("PLAN_LLM_KEY", "")
# ANSWER_LLM_URL, ANSWER_LLM_MODEL and ANSWER_LLM_KEY send the batched triage and screening calls to an OpenAI-compatible
# service the same way. Any batch it refuses (busy, rate-limited) is asked of the default model instead.
ANSWER_LLM_URL = os.environ.get("ANSWER_LLM_URL", "").rstrip("/")
ANSWER_LLM_MODEL = os.environ.get("ANSWER_LLM_MODEL", "")
ANSWER_LLM_KEY = os.environ.get("ANSWER_LLM_KEY", "")
# OMICS_FRESH_ANSWERS=1 ignores remembered triage and screen answers, so a timing run measures real model calls.
FRESH_ANSWERS = os.environ.get("OMICS_FRESH_ANSWERS") == "1"
# Every model call, local, planning service or Claude, is recorded here (stage, seconds, model, tokens in and out;
# for Claude also the cached tokens read and written) so a run can be profiled; `run` resets it.
TRACE: list[dict] = []
STAGE = ["start"]


def schema_key(schema: dict) -> str:
    return hashlib.sha1(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:16]


def _ask_openai(url: str, model: str, prompt: str, schema: dict, cached: str, max_tokens: int, key: str = "",
                extra: dict | None = None) -> dict:
    """One call to an OpenAI-compatible chat endpoint that constrains its answer to the JSON schema, or to a grammar
    when `extra` carries one (vLLM's `structured_outputs`)."""
    started = time.monotonic()
    response = httpx.post(
        f"{url}/chat/completions",
        headers={"Authorization": f"Bearer {key}"} if key else {},
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": "\n\n".join(filter(None, (cached, prompt)))}],
            **({} if "structured_outputs" in (extra or {}) else
               {"response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}}),
            **(extra or {}),
        },
        timeout=1800,
    )
    response.raise_for_status()
    body = response.json()
    usage = body.get("usage") or {}
    TRACE.append({"stage": STAGE[0], "seconds": round(time.monotonic() - started, 2), "model": body.get("model") or model,
                  "tokens_in": usage.get("prompt_tokens", 0), "tokens_out": usage.get("completion_tokens", 0), "max_tokens": max_tokens})
    choice = body["choices"][0]
    if choice["finish_reason"] == "length":
        raise RuntimeError("The model ran out of tokens before finishing its answer.")
    return json.loads(choice["message"]["content"])


def _ask_local(prompt: str, schema: dict, cached: str, think: bool, max_tokens: int) -> dict:
    """The same contract as `_ask`, on a local vLLM server; `chat_template_kwargs` is a vLLM extension."""
    grammar = GRAMMARS.get(schema_key(schema))
    return _ask_openai(LOCAL_LLM_URL, LOCAL_LLM_MODEL, prompt, schema, cached, max_tokens,
                       extra={"chat_template_kwargs": {"enable_thinking": think and LOCAL_LLM_THINK},
                              **({"structured_outputs": {"grammar": grammar}} if grammar else {})})


def _ask(prompt: str, schema: dict, effort: str, model: str = WORKER, cached: str = "", think: bool = True, max_tokens: int = 16000) -> dict:
    """`cached` is a fixed prompt prefix, cached across calls so only the varying part is billed in full.
    `think=False` skips the thinking pass, for coarse scoring where speed matters more than reasoning.
    `max_tokens` bounds the answer; a short paragraph needs far fewer than the default.
    Haiku 5.5 rejects sampling settings such as temperature 0, so repeatability comes from remembering answers."""
    if LOCAL_LLM_URL:
        return _ask_local(prompt, schema, cached, think, max_tokens)
    # Sonnet can route a safety decline to a fallback model; Haiku has no server-side fallback.
    fallback = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model.startswith("claude-sonnet") else {}
    started = time.monotonic()
    response = client.beta.messages.create(
        model=model,
        max_tokens=max_tokens,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": [
            *([{"type": "text", "text": cached, "cache_control": {"type": "ephemeral"}}] if cached else []),
            {"type": "text", "text": prompt},
        ]}],
        **fallback,
        **({} if think else {"thinking": {"type": "disabled"}}),
    )
    usage = response.usage
    TRACE.append({"stage": STAGE[0], "seconds": round(time.monotonic() - started, 2), "model": response.model,
                  "tokens_in": usage.input_tokens, "tokens_out": usage.output_tokens,
                  "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                  "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0, "max_tokens": max_tokens})
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
    if PLAN_LLM_URL:
        try:
            return _ask_openai(PLAN_LLM_URL, PLAN_LLM_MODEL, f"Research question:\n{question}", PLAN_SCHEMA,
                               PLAN_PROMPT.format(vocabulary="; ".join(cellxgene_diseases())), 16000, key=PLAN_LLM_KEY)
        except (httpx.HTTPError, ValueError, KeyError) as error:
            # A free hosted tier can be busy (503) or rate-limited (429); the search still runs, planned locally.
            print(f"planning service failed ({error}); planning on the default model", file=sys.stderr)
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


HEALTHY = re.compile(r"control|healt?h?y|normal|non-?diabet|donor|tolerant|\bNGT\b|\bNC\b", re.I)


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
    cols, rows = rec["samples"]["columns"], rec["samples"]["rows"]
    i, who = cols.index(pick["factor"]), next((n for n, c in enumerate(cols) if samples.DONOR.match(c)), 0)
    case, control = (len({r[who] for r in rows if r[i] in pick[g]}) for g in ("case", "control"))
    dataset.facts = {"case": case, "control": control, "mixed": 0, "has_control": control > 0, "sample_type": "unknown", "tissue": "", "assays": [],
                     "library": {}, "libraries": {}, "source": f"{len(rows)} {'Metabolomics Workbench' if dataset.source == 'MetabolomicsWorkbench' else 'MetaboLights'} sample records ({pick['factor']}{', one per subject' if who else ''})"}


def _fetch_samples(dataset: Dataset) -> None:
    """Warm the on-disk sample cache: Gemma's curated groups if they exist, else the GEO sample records.
    A fetch that still fails after the retries leaves that dataset without sample counts; it does not end the search."""
    try:
        if dataset.source == "GEO" and not samples.gemma_fields(dataset.accession):
            samples.geo_fields(dataset.accession)
    except httpx.HTTPError as e:
        print(f"samples for {dataset.accession} not fetched: {e}", flush=True)


def prefetch(pool: list[Dataset]) -> None:
    """Start fetching sample records for the likeliest GEO candidates while the screen runs; NCBI allows 10 requests a second."""
    workers = ThreadPoolExecutor(max_workers=10)
    for d in [d for d in pool if d.source == "GEO"][:MAX_FACTS]:
        workers.submit(_fetch_samples, d)
    workers.shutdown(wait=False)


def _sdrf_facts(topic: str, dataset: Dataset) -> None:
    """Sample-level counts for a proteomics project from its curated SDRF, when the corpus has one. The model only
    labels which field marks case and control (cached per topic); the counts, grains and pooled exclusions are code."""
    table = sdrf.sdrf_for(dataset.accession)
    if not table or not (fields := sdrf.sdrf_fields(table)):
        return
    key = f"sdrf labels {_label_key(topic)}"
    if not (labels := store.cached_facts(dataset.accession, key)):
        labels = _ask(samples.label_prompt(topic, dataset.accession, fields, dataset.text[:2000]), samples.LABEL_SCHEMA, effort="low")
        store.cache_facts(dataset.accession, key, labels)
    dataset.facts = sdrf.count(table, samples.resolve_labels(labels, fields), "SDRF samples (bigbio/sdrf-annotated-datasets)")


def add_facts(search_plan: dict, candidates: list[Dataset]) -> None:
    topic = ", ".join(search_plan["terms"])
    geo = [d for d in candidates if d.source == "GEO"][:MAX_FACTS]
    pride = [d for d in candidates if d.source == "PRIDE"][:MAX_FACTS]
    with ThreadPoolExecutor(max_workers=10) as workers:
        list(workers.map(_fetch_samples, geo))
    # Fetching is rate-limited; labelling is not, so every labelling call runs at once.
    def geo_facts(d: Dataset) -> None:
        try:
            _geo_facts(topic, d)
        except httpx.HTTPError as e:
            print(f"facts for {d.accession} skipped: {e}", flush=True)

    with ThreadPoolExecutor(max_workers=len(geo) + len(pride) or 1) as workers:
        list(workers.map(geo_facts, geo))
        list(workers.map(lambda d: _sdrf_facts(topic, d), pride))
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

# Batch sizes and listing lengths; the environment can override them for timing experiments (docs/evidence/qwen/).
TRIAGE_BATCH = int(os.environ.get("OMICS_TRIAGE_BATCH") or 25)
SCREEN_BATCH = int(os.environ.get("OMICS_SCREEN_BATCH") or 4)
SCREEN_CHARS = int(os.environ.get("OMICS_SCREEN_CHARS") or 1500)
TRIAGE_CHARS = int(os.environ.get("OMICS_TRIAGE_CHARS") or 250)
# Compact triage answers: one list of scores in listing order instead of {n, score} objects, a sixth of the output
# tokens (about 87 against 554 for 25 candidates). Without a length constraint the model dropped one score in most
# batches (docs/evidence/qwen/README.md), so the schema fixes the list's length to the batch's; a list of the wrong
# length still falls back to the numbered form for that batch.
TRIAGE_COMPACT = os.environ.get("OMICS_TRIAGE_COMPACT") == "1"
TRIAGE_COMPACT_SCHEMA = {"type": "object", "properties": {"scores": {"type": "array", "items": {"type": "integer", "enum": [0, 1, 2, 3]}}},
                         "required": ["scores"], "additionalProperties": False}


def _compact_schema(size: int) -> dict:
    """The compact triage schema with exactly `size` scores."""
    scores = TRIAGE_COMPACT_SCHEMA["properties"]["scores"] | {"minItems": size, "maxItems": size}
    return TRIAGE_COMPACT_SCHEMA | {"properties": {"scores": scores}}
TRIAGE_COMPACT_NOTE = "\n\nReturn one list of scores, in the same order as the numbered datasets, one score per dataset."
# Shorter screening answers: the reason capped at 15 words and the evidence at 10, which halves the output tokens
# that set the screening stage's wall time on the local model. Changes the prompt, so it starts its own answer cache.
SCREEN_SHORT = os.environ.get("OMICS_SCREEN_SHORT") == "1"
SCREEN_SHORT_NOTE = " Keep each reason under 15 words and each evidence phrase under 10 words."


# Keyed triage answers: one object with a score under each candidate's number, every key required, so the answer
# cannot misalign or stop short; about 200 output tokens for 25 candidates against 322 for the numbered objects.
TRIAGE_KEYED = os.environ.get("OMICS_TRIAGE_KEYED") == "1"
TRIAGE_KEYED_NOTE = "\n\nReturn an object with one score per dataset, keyed by the dataset's number."


def _keyed_schema(size: int) -> dict:
    return {"type": "object", "properties": {str(i): {"type": "integer", "enum": [0, 1, 2, 3]} for i in range(size)},
            "required": [str(i) for i in range(size)], "additionalProperties": False}


def _keyed_scores(question: str, candidates: list[Dataset]) -> dict[str, dict]:
    """Triage scores keyed by candidate number, one call per batch; remembered like the numbered answers."""
    version = hashlib.sha1((TRIAGE_PROMPT + TRIAGE_KEYED_NOTE + json.dumps(_keyed_schema(TRIAGE_BATCH))).encode()).hexdigest()[:8]
    slot = "question " + hashlib.sha1(" ".join(question.lower().split()).encode()).hexdigest()[:16]
    kind = f"triage answers #{version}"
    known = {} if FRESH_ANSWERS else store.cached_facts(slot, kind) or {}
    missing = [d for d in candidates if d.accession not in known]
    batches = [missing[i:i + TRIAGE_BATCH] for i in range(0, len(missing), TRIAGE_BATCH)]

    def ask(batch: list[Dataset]) -> dict[str, dict]:
        prompt = TRIAGE_PROMPT.replace("{question}", question).replace("{listing}", _listing(batch, TRIAGE_CHARS)) + TRIAGE_KEYED_NOTE
        scores = _ask(prompt, _keyed_schema(len(batch)), effort="low", think=False)
        return {d.accession: {"n": i, "score": scores[str(i)]} for i, d in enumerate(batch)}

    with ThreadPoolExecutor(max_workers=len(batches) or 1) as workers:
        known |= {k: v for part in workers.map(ask, batches) for k, v in part.items()}
    if missing:
        store.cache_facts(slot, kind, known)
    return {d.accession: known[d.accession] for d in candidates if d.accession in known}


def _listing(batch: list[Dataset], chars: int) -> str:
    return "\n\n".join(f"{n}. {d.accession} | {d.source} | {d.modality} | {d.organism}\n{d.text[:chars]}" for n, d in enumerate(batch))


def _answers(name: str, template: str, question: str, schema: dict, candidates: list[Dataset], size: int, chars: int, effort: str, think: bool = True) -> dict[str, dict]:
    """Each batch in its own parallel call; answers are matched back to datasets by their number in the batch.
    Answers are remembered per question, so a repeated search reuses them and only new candidates are asked about;
    a changed prompt or schema starts afresh."""
    version = hashlib.sha1((template + json.dumps(schema)).encode()).hexdigest()[:8]
    slot = "question " + hashlib.sha1(" ".join(question.lower().split()).encode()).hexdigest()[:16]
    kind = f"{name} answers #{version}"
    known = {} if FRESH_ANSWERS else store.cached_facts(slot, kind) or {}
    missing = [d for d in candidates if d.accession not in known]
    batches = [missing[i:i + size] for i in range(0, len(missing), size)]

    def ask(batch: list[Dataset]) -> dict[str, dict]:
        prompt = template.replace("{question}", question).replace("{listing}", _listing(batch, chars))
        sized = _sized(schema, len(batch))
        reply = None
        if ANSWER_LLM_URL:
            try:
                reply = _ask_openai(ANSWER_LLM_URL, ANSWER_LLM_MODEL, prompt, sized, "", 16000, key=ANSWER_LLM_KEY)
            except (httpx.HTTPError, ValueError, KeyError) as error:
                print(f"{name} service failed ({str(error)[:120]}); asking the default model", file=sys.stderr)
        reply = reply or _ask(prompt, sized, effort=effort, think=think)
        return {batch[a["n"]].accession: a for a in reply["answers"] if 0 <= a["n"] < len(batch)}

    with ThreadPoolExecutor(max_workers=len(batches) or 1) as workers:
        known |= {k: v for part in workers.map(ask, batches) for k, v in part.items()}
    if missing:
        store.cache_facts(slot, kind, known)
    return {d.accession: known[d.accession] for d in candidates if d.accession in known}


def _compact_scores(question: str, candidates: list[Dataset]) -> dict[str, dict]:
    """Triage scores as one list per batch; a batch whose list has the wrong length is asked again in the numbered form."""
    version = hashlib.sha1((TRIAGE_PROMPT + TRIAGE_COMPACT_NOTE + json.dumps(TRIAGE_COMPACT_SCHEMA) + " fixed length").encode()).hexdigest()[:8]
    slot = "question " + hashlib.sha1(" ".join(question.lower().split()).encode()).hexdigest()[:16]
    kind = f"triage answers #{version}"
    known = {} if FRESH_ANSWERS else store.cached_facts(slot, kind) or {}
    missing = [d for d in candidates if d.accession not in known]
    batches = [missing[i:i + TRIAGE_BATCH] for i in range(0, len(missing), TRIAGE_BATCH)]

    def ask(batch: list[Dataset]) -> dict[str, dict]:
        prompt = TRIAGE_PROMPT.replace("{question}", question).replace("{listing}", _listing(batch, TRIAGE_CHARS)) + TRIAGE_COMPACT_NOTE
        scores = _ask(prompt, _compact_schema(len(batch)), effort="low", think=False)["scores"]
        if len(scores) != len(batch):
            return _answers("triage", TRIAGE_PROMPT, question, TRIAGE_SCHEMA, batch, TRIAGE_BATCH, TRIAGE_CHARS, "low", think=False)
        return {d.accession: {"n": i, "score": s} for i, (d, s) in enumerate(zip(batch, scores))}

    with ThreadPoolExecutor(max_workers=len(batches) or 1) as workers:
        known |= {k: v for part in workers.map(ask, batches) for k, v in part.items()}
    if missing:
        store.cache_facts(slot, kind, known)
    return {d.accession: known[d.accession] for d in candidates if d.accession in known}


def triage(question: str, candidates: list[Dataset], keep: int) -> list[Dataset]:
    """A cheap first ranking over the whole pool: Haiku scores titles and summary openings in parallel batches."""
    # Thinking off: in tests it changed the top 40 about as much as two thinking runs differ, at a third of the time.
    answers = (_keyed_scores(question, candidates) if TRIAGE_KEYED else _compact_scores(question, candidates) if TRIAGE_COMPACT
               else _answers("triage", TRIAGE_PROMPT, question, TRIAGE_SCHEMA, candidates, TRIAGE_BATCH, TRIAGE_CHARS, "low", think=False))
    scores = {k: v["score"] for k, v in answers.items()}
    ranked = sorted(candidates, key=lambda d: scores.get(d.accession, 0), reverse=True)
    return [d for d in ranked if scores.get(d.accession, 0) > 0][:keep]


def screen(question: str, candidates: list[Dataset]) -> dict[str, dict]:
    """Haiku answers the four checks for every candidate, with a reason and a quoted phrase, in small parallel batches."""
    template = SCREEN_PROMPT + SCREEN_SHORT_NOTE if SCREEN_SHORT else SCREEN_PROMPT
    return _answers("screen", template, question, SCREEN_SCHEMA, candidates, SCREEN_BATCH, SCREEN_CHARS, "medium")


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


PAPER_LAG = 3


def add_papers(hits: list[dict]) -> None:
    """Attach the dataset's own paper (title, journal, year) to each hit: of its linked papers, the newest that is not
    years older than the dataset. An older paper is a method it cites (PRJEB44790, 2021, links a 1993 J Nutr paper)."""
    linked = {h["accession"]: [p for p in h["papers"] if p != "pmid:1"][:4] for h in hits}
    found = paper_details(list({p for ps in linked.values() for p in ps}))
    for h in hits:
        year = int((h.get("published") or "0")[:4] or 0)
        own = [found[p] for p in linked[h["accession"]] if p in found and int(found[p].get("year") or 0) >= year - PAPER_LAG]
        h["paper"] = max(own, key=lambda x: int(x.get("year") or 0), default=None)


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
    Shared by the CLI, API, and MCP server. The result's `timings` gives the seconds each stage took."""
    TRACE.clear()
    timings: dict[str, float] = {}
    clock = [time.monotonic()]

    def stage(name: str) -> None:
        now = time.monotonic()
        timings[STAGE[0]] = round(timings.get(STAGE[0], 0) + now - clock[0], 1)
        STAGE[0], clock[0] = name, now

    stage("plan")
    search_plan = plan(question)
    progress("plan", search_plan)
    stage("gather")
    pool = gather(search_plan, question)
    progress("candidates", {"count": len(pool)})
    stage("triage")
    candidates = triage(question, pool, limit)
    stage("prefetch")
    prefetch(candidates)
    stage("screen")
    verdicts = screen(question, candidates)
    keep = relevant(candidates, verdicts)
    progress("screened", {"count": len(keep)})
    stage("facts")
    add_facts(search_plan, keep)
    progress("facts", {"count": sum(1 for d in keep if d.facts)})
    stage("grade")
    hits = grade(search_plan, keep, verdicts)
    add_papers(hits)
    for h in hits:
        h["download_plan"] = download_plan(h["accession"], h["source"], h["url"])
    groups = bundles(hits)
    stage("done")
    timings.pop("start", None)
    return {
        "answer": answer.pick(search_plan, hits),
        "question": question,
        "plan": search_plan,
        "candidates": len(pool),
        "datasets": [{k: v for k, v in h.items() if k != "text"} for h in hits],
        "same_paper": [[h["accession"] for h in g] for g in groups],
        "timings": timings,
    }
