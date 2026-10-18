"""Quality from the records: sequencing depth per sample from the run table, low or high depth flagged within a real
library type, re-sequencing top-ups shown beside their parent, and the authors' own QC criteria quoted from their
processing text and their paper's methods."""

import re
from statistics import median

from . import assay, record

LOW, HIGH = 0.25, 4.0
FLAGGED_GROUP = range(3, 151)
TOP_UP = re.compile(r"[_\s.-]*(?:re-?seq(?:uenc\w*)?|top-?up|re-?run|resequenc\w*)\b", re.I)
SEQUENCING = {"GEO", "ENA", "ArrayExpress"}

QC_WORD = re.compile(r"\b(?:trimm|adapter|filter|discard|exclud|retain|length|quality|phred|periodicity|in-?frame|frame|threshold|cut-?off|"
                     r"minimum|at least|only reads|uniquely|multi-?mapp|P-site|offset|duplicat|mapq|mapping rate|reads? (?:shorter|longer)|RPKM|TPM|CPM)", re.I)
CRITERION = re.compile(r"(?:≥|>=|<=|≤|>|<|at least|more than|fewer than|less than|minimum|maximum|cut-?off|threshold|only)\s*(?:of\s*)?\S{0,12}\s*\d"
                       r"|\d+\s*(?:-|–|to)\s*\d+\s*(?:nt|bp|nucleotides)\b|\d+\s*(?:nt|bp|nucleotides|reads|%)(?!\w)", re.I)
QC_CHECK = re.compile(r"\bFastQC\b|\bMultiQC\b|\bfastp\b|\bTrimmomatic\b|\bcutadapt\b|periodicity|quality control|\bQC\b", re.I)
# The checks a translation scientist looks for in a Ribo-seq study (jurilw: footprint length, periodicity, reads in CDS).
RIBO_CHECKS = [
    ("Footprint length", re.compile(r"\b\d{2}\s*(?:-|–|to)\s*\d{2}\s*(?:nt|nucleotides?|bp)\b|footprint (?:length|size)|read lengths? (?:of|between|from)", re.I)),
    ("Three-nucleotide periodicity", re.compile(r"periodicit|in-?frame|reading frame|P-site|\bframe\b", re.I)),
    ("Reads in coding sequences", re.compile(r"\bCDS\b|coding (?:sequence|region)s?|\bORFs?\b", re.I)),
    ("rRNA removal", re.compile(r"\brRNA\b|ribosomal RNA", re.I)),
    ("Replicate agreement", re.compile(r"replicates?.{0,60}(?:correlat|agree|reproducib)|(?:correlat|reproducib).{0,60}replicates?", re.I)),
    ("PCR duplicates (UMI)", re.compile(r"\bUMIs?\b|unique molecular identifier|de-?duplicat|PCR duplicates?", re.I)),
]
ANALYSIS = re.compile(r"sequenc|analys|profil|librar|bioinformat|process|read|align|mapp|footprint|quantif|statistic|quality", re.I)


def _project(rec: dict) -> str | None:
    if rec["source"] == "ENA":
        return rec["accession"]
    return next((m.group(0) for _, url in rec["links"] if (m := re.search(r"PRJ[A-Z]{2}\d+", url))), None)


def depth(accession: str) -> dict:
    rec = record.record(accession)
    if not rec:
        return {"available": False, "reason": "not in the index"}
    if rec["source"] not in SEQUENCING:
        return {"available": False, "reason": "not a sequencing dataset", "sequencing": False}
    project = _project(rec)
    runs = record._runs(project) if project else []
    if not runs:
        return {"available": False, "reason": "the repository lists no sequencing runs with read counts"}
    titles = {r[0]: r[1] for r in (rec["samples"] or {}).get("rows", [])} if rec["source"] == "GEO" else {}
    types = assay.library_types(accession)[0] if rec["source"] == "GEO" else {}
    by_sample: dict[str, dict] = {}
    for run in runs:
        if not run.get("read_count", "").isdigit():
            continue
        gsm = re.search(r"GSM\d+", run.get("experiment_title", ""))
        sample = gsm.group(0) if gsm and rec["source"] == "GEO" else run["run_accession"]
        strategy = run.get("library_strategy") or "not stated"
        row = by_sample.setdefault(sample, {"sample": sample, "title": titles.get(sample, run.get("sample_title", "")), "runs": [], "reads": 0, "bases": 0,
                                            "library": types.get(sample) or (strategy if strategy.upper() not in ("OTHER", "NOT STATED") else "library type not stated"),
                                            "paired": run.get("library_layout") == "PAIRED", "top_up_of": None, "outlier": None})
        row["runs"].append(run["run_accession"])
        row["reads"] += int(run["read_count"])
        row["bases"] += int(run["base_count"]) if run.get("base_count", "").isdigit() else 0
    rows = sorted(by_sample.values(), key=lambda r: (r["library"], -r["reads"]))
    parents = [r for r in rows if r["title"] and not TOP_UP.search(r["title"])]
    for r in rows:
        r["read_length"] = round(r["bases"] / r["reads"] / (2 if r["paired"] else 1)) if r["reads"] else None
        if r["title"] and TOP_UP.search(r["title"]):
            stem = TOP_UP.sub("", r["title"]).lower().split(":")[-1].strip()
            r["top_up_of"] = next((p["sample"] for p in parents if p["title"].lower().split(":")[-1].strip() == stem), "a sample not in this series")
    groups = {}
    for lib in dict.fromkeys(r["library"] for r in rows):
        members = [r for r in rows if r["library"] == lib and not r["top_up_of"]]
        if not members:
            continue
        mid = median(r["reads"] for r in members)
        flagged = len(members) in FLAGGED_GROUP and lib != "library type not stated"
        groups[lib] = {"samples": len(members), "median_reads": int(mid), "min_reads": min(r["reads"] for r in members),
                       "max_reads": max(r["reads"] for r in members), "flagged": flagged}
        for r in members:
            ratio = r["reads"] / mid if mid else 1
            if flagged and (ratio < LOW or ratio > HIGH):
                r["outlier"] = f"{ratio:.3g}× the median"
    return {"available": True, "project": project, "rows": rows, "groups": groups, "outliers": sum(bool(r["outlier"]) for r in rows),
            "top_ups": sum(bool(r["top_up_of"]) for r in rows),
            "rule": f"below {LOW}× or above {HIGH}× the median reads of the same library type; top-ups, unstated library types and groups over {FLAGGED_GROUP.stop - 1} samples are not flagged",
            "source": f"ENA read_run table for {project}"}


def _key(sentence: str) -> str:
    return re.sub(r"[^a-z]+", "", sentence.lower())


def criteria(accession: str) -> dict:
    rec = record.record(accession)
    if not rec:
        return {"quotes": [], "read": []}
    texts = [(field, text) for field, _, text in assay._texts(rec) if re.search(r"data processing|extraction|library|processing protocol", field, re.I)]
    read = sorted({f for f, _ in texts})
    paper = next((p["id"] for p in rec["papers"] if p.get("id") and p["id"] != "pmid:1"), None)
    if paper:
        methods = assay._methods(paper)
        texts += [(f"Paper methods: {p['section']}", p["text"]) for p in methods.get("paragraphs", []) if ANALYSIS.search(p["section"] or "")]
        read.append("paper methods (Europe PMC open-access text)" if methods.get("available") else f"paper methods not readable: {methods.get('reason', 'not stated')}")
    checklist = None
    if assay.RIBOSOME_PROFILING.search(" ".join(t for _, _, t in assay._texts(rec))):
        sentences = [(field, s) for field, text in texts for s in assay._sentences(text) if len(s) <= 600]
        checklist = [next(({"check": name, "stated": True, "text": s, "field": f} for f, s in sentences if rx.search(s)), {"check": name, "stated": False})
                     for name, rx in RIBO_CHECKS]
    quotes: list[dict] = []
    for field, text in texts:
        for sentence in assay._sentences(text):
            if len(sentence) > 400 or not (QC_CHECK.search(sentence) or (QC_WORD.search(sentence) and CRITERION.search(sentence))):
                continue
            key = _key(sentence)
            if any(key in q["key"] or q["key"] in key for q in quotes):
                continue
            quotes.append({"text": sentence, "field": field, "key": key})
    return {"quotes": [{k: q[k] for k in ("text", "field")} for q in quotes[:40]], "read": read, "checklist": checklist}


def sample_qc(accession: str) -> dict:
    return {"accession": accession, "depth": depth(accession), "criteria": criteria(accession)}


if __name__ == "__main__":
    ribo = depth("GSE132703")
    assert ribo["available"] and {"Ribo-seq (elongating ribosomes)", "RNA-seq"} <= set(ribo["groups"]), ribo["groups"]
    top_ups = {r["sample"]: r["top_up_of"] for r in ribo["rows"] if r["top_up_of"]}
    assert len(top_ups) >= 3 and all(p.startswith("GSM") for p in top_ups.values()) and not any(r["outlier"] for r in ribo["rows"] if r["top_up_of"]), top_ups
    paired = depth("GSE263646")
    assert all(r["read_length"] <= 151 for r in paired["rows"] if r["paired"]), "read length is per read, not per spot"
    assert not any(r["outlier"] for r in depth("GSE215147")["rows"]), "large single-cell series are not flagged"
    noise = [q["text"] for q in criteria("GSE263646")["quotes"]]
    assert not any("centrifug" in q.lower() for q in noise), noise
    assert any("FastQC" in q["text"] for q in criteria("GSE112295")["quotes"])
    assert depth("PXD010450").get("sequencing") is False
    print("qc self-check passed:", ribo["groups"], len(top_ups), "top-ups")
