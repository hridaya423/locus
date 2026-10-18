"""How each PRIDE dataset was run, from PRIDE Map's method tags (github.com/FlynnLachendro/pridemap, MIT).

Most tags were written by a small model, so a tag counts as a fact only when it came from the PRIDE metadata or the
paper with confidence of at least MIN_CONFIDENCE. Other tags are shown as "probably" and never decide anything.
"""

import gzip
import json
import re
from pathlib import Path

import httpx

from . import store

SHARDS = [f"tags.0{n}.jsonl.gz" for n in (1, 2, 3)]
SHARD_URL = "https://raw.githubusercontent.com/FlynnLachendro/pridemap/main/data/demo/{}"
CACHE = store.DB.parent / "pridemap"
TRUSTED = {"metadata", "paper"}
MIN_CONFIDENCE = 0.5
FACETS = ("acquisition", "labelling", "enrichment", "instrument_family", "search_engine", "fractionation", "sample_type", "tissue", "cell_line", "disease", "depth_proteins")
SEPARATOR = " | "

# A method a question asks for, and the tag value that shows a dataset used it.
NEEDS = (
    (r"phospho", "enrichment", "phospho"),
    (r"ubiquitin|ubiquityl", "enrichment", "ubiquitin"),
    (r"glyco", "enrichment", "glyco"),
    (r"acetylom|acetylation", "enrichment", "acetyl"),
    (r"\bap-?ms\b|interactom|affinity purification|pull-?down", "enrichment", "ap_ms"),
    (r"proximity|bioid|turboid|\bapex", "enrichment", "proximity_labelling"),
    (r"secretom", "enrichment", "secretome"),
    (r"\bdia\b|data.independent|swath", "acquisition", "DIA"),
    (r"\bprm\b|\bsrm\b|\bmrm\b|targeted proteom", "acquisition", "PRM_SRM"),
    (r"top-?down", "acquisition", "top_down"),
    (r"\btmt\b|tandem mass tag", "labelling", "TMT"),
    (r"silac", "labelling", "SILAC"),
    (r"itraq", "labelling", "iTRAQ"),
)
LAYER = {"phospho": "phosphoproteome", "ubiquitin": "ubiquitinome", "glyco": "glycoproteome", "acetyl": "acetylome", "ap_ms": "interactome", "proximity_labelling": "interactome", "secretome": "secretome"}
WORDS = {
    "acquisition": {"DIA": "DIA", "DDA": "DDA", "PRM_SRM": "targeted PRM/SRM", "top_down": "top-down", "MALDI": "MALDI"},
    "labelling": {"TMT": "TMT", "SILAC": "SILAC", "iTRAQ": "iTRAQ", "dimethyl": "dimethyl labelling", "label_free": "label-free"},
    "instrument_family": {"orbitrap": "Orbitrap", "timstof": "timsTOF", "qtof": "Q-TOF", "triple_quad": "triple quadrupole"},
    "search_engine": {"maxquant": "MaxQuant", "diann": "DIA-NN", "fragpipe": "FragPipe", "spectronaut": "Spectronaut", "proteome_discoverer": "Proteome Discoverer", "mascot": "Mascot"},
    "fractionation": {"high_ph_rp": "high-pH fractionation", "scx": "SCX fractionation", "gel": "gel fractionation"},
    "enrichment": {"phospho": "phospho enrichment", "ubiquitin": "ubiquitin enrichment", "glyco": "glyco enrichment", "acetyl": "acetyl enrichment", "ap_ms": "affinity purification", "proximity_labelling": "proximity labelling", "secretome": "secretome", "none": "no enrichment"},
}


def parse(row: dict) -> dict:
    """One PRIDE Map row as {facet: {value, confidence, source, evidence}} plus its one-line summary."""
    raw = json.loads(row["raw_json"])
    tags = {f: raw[f] for f in FACETS if isinstance(raw.get(f), dict) and raw[f].get("value") not in (None, "", "other")}
    return {"tags": tags, "summary": row.get("summary_one_line") or "", "model": row.get("model") or ""}


def trusted(tag: dict | None) -> bool:
    return bool(tag) and tag.get("source") in TRUSTED and (tag.get("confidence") or 0) >= MIN_CONFIDENCE


def value(data: dict, facet: str) -> str | None:
    tag = data["tags"].get(facet)
    return str(tag["value"]) if trusted(tag) else None


def words(data: dict) -> list[str]:
    """Trusted method, tissue and disease words, for the search text."""
    out = [WORDS[f].get(v, "") for f in WORDS if (v := value(data, f)) and v != "none"]
    if (enrichment := value(data, "enrichment")) in LAYER:
        out.append(LAYER[enrichment])
    out += [v for f in ("tissue", "cell_line", "disease") if (v := value(data, f))]
    return [w for w in out if w]


HLA = re.compile(r"immunopeptid|ligandom|\b(?:HLA|MHC)\b.{0,40}(?:peptid|ligand|present)", re.I)
ORGANELLE = re.compile(r"\bmito-?IP\b|\bmito-?tag\b|\blyso-?IP\b|organelle (?:immuno)?(?:precipitation|IP|capture)|\bHA-?OMP25\b|\bTMEM192\b", re.I)


def assay(data: dict, text: str = "") -> str | None:
    """One readable assay name, for example "phosphoproteome (DIA, TMT)". An affinity purification of HLA or MHC ligands
    (W6/32) is an immunopeptidome, not an interactome."""
    layer = LAYER.get(value(data, "enrichment") or "", "proteome")
    if value(data, "enrichment") == "ap_ms" and HLA.search(text):
        layer = "immunopeptidome"
    elif value(data, "enrichment") == "ap_ms" and ORGANELLE.search(text):
        layer = "organelle IP proteome"
    qualifiers = [WORDS[f].get(v, "") for f in ("acquisition", "labelling") if (v := value(data, f)) and v != "label_free"]
    return f"{layer} ({', '.join(q for q in qualifiers if q)})" if any(qualifiers) else layer


def material(data: dict, organism: str) -> str:
    human = "sapiens" in organism.lower()
    return {
        "cell_line": "cell_line", "primary_cells": "primary_cells",
        "tissue": "patient_tissue" if human else "animal_or_organoid_model",
        "biofluid": "patient_biofluid" if human else "animal_or_organoid_model",
        "organism_whole": "animal_or_organoid_model",
    }.get(value(data, "sample_type") or "", "unknown")


def facts(data: dict, organism: str, text: str = "") -> dict:
    """The facts a PRIDE row shows and grading reads. PRIDE has no counted case/control groups, so those stay unknown."""
    return {
        "case": None, "control": None, "mixed": 0, "has_control": None,
        "sample_type": material(data, organism),
        "tissue": value(data, "tissue") or value(data, "cell_line") or "",
        "assays": [assay(data, text)],
        "library": {}, "libraries": {},
        "source": "PRIDE Map method tags, from PRIDE metadata and papers",
        "methods": {
            f: {"value": str(t["value"]), "label": WORDS.get(f, {}).get(str(t["value"]), str(t["value"])), "evidence": t.get("evidence") or "", "trusted": trusted(t)}
            for f, t in data["tags"].items()
        },
    }


def meets(wanted: list[str], methods: dict) -> str | None:
    """Each name in `wanted` is one alternative that would answer the question (the plan lists alternatives, not
    requirements). 'yes' when trusted tags prove every method of some alternative, 'no' when trusted tags contradict
    every alternative that names a checkable method, else None."""
    results = []
    for name in wanted:
        checks = [(facet, needed) for pattern, facet, needed in NEEDS if re.search(pattern, name, re.I)]
        if not checks:
            continue
        stated = [methods[f]["value"] == needed for f, needed in checks if methods.get(f, {}).get("trusted")]
        results.append(False if not all(stated) else True if len(stated) == len(checks) else None)
    if any(r is True for r in results):
        return "yes"
    return "no" if results and all(r is False for r in results) else None


def _download() -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = []
    for shard in SHARDS:
        path = CACHE / shard
        if not path.exists():
            response = httpx.get(SHARD_URL.format(shard), timeout=300, follow_redirects=True)
            response.raise_for_status()
            path.write_bytes(response.content)
        rows += [json.loads(line) for line in gzip.open(path, "rt")]
    return rows


def import_tags() -> dict[str, int]:
    """Store every tag set and add the trusted words to each PRIDE row's data type, so search can find methods.
    Rerunning replaces the earlier words instead of appending them again."""
    db = store.connect()
    rows = {r["accession"]: parse(r) for r in _download()}
    db.executemany("INSERT OR REPLACE INTO methods (accession, data) VALUES (?, ?)", [(a, json.dumps(d)) for a, d in rows.items()])
    updates = []
    for accession, modality in db.execute("SELECT accession, modality FROM datasets WHERE source = 'PRIDE'"):
        base = modality.split(SEPARATOR)[0]
        found = words(rows[accession]) if accession in rows else []
        updates.append((base + SEPARATOR + ", ".join(found) if found else base, accession))
    db.executemany("UPDATE datasets SET modality = ? WHERE accession = ?", updates)
    db.commit()
    store.rebuild_fts(db)
    return {"tag sets": len(rows), "PRIDE rows": len(updates), "rows with method words": sum(SEPARATOR in m for m, _ in updates)}


if __name__ == "__main__":
    data = {"tags": {
        "enrichment": {"value": "phospho", "confidence": 0.9, "source": "paper", "evidence": "TiO2 enrichment"},
        "acquisition": {"value": "DIA", "confidence": 0.95, "source": "metadata", "evidence": "DIA"},
        "labelling": {"value": "TMT", "confidence": 0.3, "source": "inferred", "evidence": ""},
        "sample_type": {"value": "tissue", "confidence": 0.9, "source": "metadata", "evidence": "liver"},
    }}
    assert assay(data) == "phosphoproteome (DIA)", "an untrusted label is left out"
    f = facts(data, "Homo sapiens (human)")
    assert f["sample_type"] == "patient_tissue" and f["methods"]["labelling"]["trusted"] is False
    assert meets(["phosphoproteomics"], f["methods"]) == "yes"
    assert meets(["glycoproteomics"], f["methods"]) == "no", "a trusted phospho enrichment is not a glyco enrichment"
    assert meets(["RNA-seq"], f["methods"]) is None, "a question about another assay is not checked here"
    assert meets(["DIA phosphoproteomics", "TMT phosphoproteomics"], f["methods"]) == "yes", "one alternative is enough"
    tmt = {"enrichment": {"value": "phospho", "trusted": True}, "acquisition": {"value": "DDA", "trusted": True}, "labelling": {"value": "TMT", "trusted": True}}
    assert meets(["phosphoproteomics", "DIA phosphoproteomics", "TMT phosphoproteomics"], tmt) == "yes", "a TMT phospho study answers a question that lists DIA as one option"
    assert meets(["DIA phosphoproteomics"], tmt) == "no"
    unenriched = {"enrichment": {"value": "none", "evidence": "", "trusted": True}}
    assert meets(["phosphoproteomics"], unenriched) == "no", "a trusted 'no enrichment' rules out phospho"
    print("ok")
