"""Quality from the records: sequencing depth per sample from the run table, outliers within each library type, and the
authors' own QC criteria quoted from their processing text and their paper's methods."""

import re
from statistics import median

from . import assay, record, sources

LOW, HIGH = 0.25, 4.0
# A QC criterion is a sentence that names a filter or threshold and gives a number.
QC = re.compile(r"\b(?:trimm|adapter|filter|discard|remov|exclud|retain|length|quality|phred|periodicity|frame|threshold|cut-?off|minimum|"
                r"at least|only reads|uniquely|multi-?mapp|rRNA|P-site|offset|duplicat)", re.I)
NUMBER = re.compile(r"\d")
ANALYSIS = re.compile(r"sequenc|analys|profil|librar|bioinformat|process|read|align|mapp|footprint|quantif|statistic", re.I)


def _project(rec: dict) -> str | None:
    if rec["source"] == "ENA":
        return rec["accession"]
    return next((m.group(0) for _, url in rec["links"] if (m := re.search(r"PRJ[A-Z]{2}\d+", url))), None)


def depth(accession: str) -> dict:
    """Reads and bases per sample, grouped by library type, with samples far from their group's median flagged."""
    rec = record.record(accession)
    if not rec:
        return {"available": False, "reason": "not in the index"}
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
        row = by_sample.setdefault(sample, {"sample": sample, "title": titles.get(sample, run.get("sample_title", "")), "runs": [], "reads": 0, "bases": 0,
                                            "library": types.get(sample) or run.get("library_strategy") or "not stated"})
        row["runs"].append(run["run_accession"])
        row["reads"] += int(run["read_count"])
        row["bases"] += int(run["base_count"]) if run.get("base_count", "").isdigit() else 0
    rows = sorted(by_sample.values(), key=lambda r: (r["library"], -r["reads"]))
    groups = {}
    for lib in dict.fromkeys(r["library"] for r in rows):
        members = [r for r in rows if r["library"] == lib]
        mid = median(r["reads"] for r in members)
        groups[lib] = {"samples": len(members), "median_reads": int(mid)}
        for r in members:
            r["read_length"] = round(r["bases"] / r["reads"]) if r["reads"] else None
            ratio = r["reads"] / mid if mid else 1
            r["outlier"] = (f"{ratio:.2f}× the median" if ratio < LOW or ratio > HIGH else None) if len(members) >= 3 else None
    return {"available": True, "project": project, "rows": rows, "groups": groups, "outliers": sum(bool(r["outlier"]) for r in rows),
            "rule": f"flagged when below {LOW}× or above {HIGH}× the median reads of its library type (groups of 3 or more)",
            "source": f"ENA read_run table for {project}"}


def criteria(accession: str) -> dict:
    """The authors' QC criteria: sentences from the record's processing text and the paper's methods that state a filter
    or threshold with a number."""
    rec = record.record(accession)
    if not rec:
        return {"quotes": [], "read": []}
    texts = [(field, text) for field, _, text in assay._texts(rec) if re.search(r"data processing|extraction|library|processing protocol", field, re.I)]
    read = sorted({f for f, _ in texts})
    paper = next((p["id"] for p in rec["papers"] if p.get("id") and p["id"] != "pmid:1"), None)
    if paper:
        methods = sources.paper_methods(paper)
        texts += [(f"Paper methods: {p['section']}", p["text"]) for p in methods.get("paragraphs", []) if ANALYSIS.search(p["section"] or "")]
        read.append("paper methods (Europe PMC open-access text)" if methods.get("available") else f"paper methods not readable: {methods.get('reason', 'not stated')}")
    quotes, seen = [], set()
    for field, text in texts:
        for sentence in assay._sentences(text):
            if QC.search(sentence) and NUMBER.search(sentence) and sentence not in seen and len(sentence) < 400:
                seen.add(sentence)
                quotes.append({"text": sentence, "field": field})
    return {"quotes": quotes[:12], "more": max(0, len(quotes) - 12), "read": read}


def sample_qc(accession: str) -> dict:
    return {"accession": accession, "depth": depth(accession), "criteria": criteria(accession)}


if __name__ == "__main__":
    ribo = depth("GSE132703")
    assert ribo["available"] and set(ribo["groups"]) == {"Ribo-seq (elongating ribosomes)", "RNA-seq"}, ribo["groups"]
    assert all(r["sample"].startswith("GSM") for r in ribo["rows"])
    crit = criteria("GSE36892")
    assert any("Paper methods" in q["field"] for q in crit["quotes"]), crit
    ena = depth("PRJEB39707")
    assert ena["available"] and ena["rows"], ena.get("reason")
    print("qc self-check passed:", ribo["groups"], ribo["outliers"], "outliers;", len(crit["quotes"]), "QC sentences for GSE36892")
