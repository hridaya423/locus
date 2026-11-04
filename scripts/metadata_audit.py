"""Audit how much sample metadata each repository gives a reader, on a stratified random sample of locus's index.

For each drawn dataset this reads the live record the way the locus study page does (omics_agent.record), plus the raw
sample attributes ENA and PRIDE SDRF files carry, and records the evidence: every sample attribute with the share of
samples that state it, and every study-level fact. `fields()` then asks one question per field researchers filter on: is
it stated, machine-readably, for at least half of the samples (or for the whole study)? Free text in a summary does not
count; that is the dark data this audit measures. Rules live in `fields()`, so changing one needs no re-audit.

    uv run python scripts/metadata_audit.py draw  --out runs/metadata-audit       # the stratified sample (seeded)
    uv run python scripts/metadata_audit.py audit --out runs/metadata-audit -j 8  # resumable; one JSON line per dataset
"""

import argparse
import csv
import io
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from omics_agent import record, store

DB = Path(os.environ.get("OMICS_DB") or Path.home() / "fast/locus/data/omics.db")
SEED = 20261020

# Datasets drawn per repository: enough for a rate within about ±5 points on the big ones, at least 25 everywhere.
DRAW = {"ENA": 360, "GEO": 360, "PRIDE": 200, "ArrayExpress": 120, "EGA": 60, "MassIVE": 80, "iProX": 50, "NODE": 50,
        "MetabolomicsWorkbench": 40, "MetaboLights": 40, "jPOST": 40, "PeptideAtlas": 25, "CELLxGENE": 30, "dbGaP": 25,
        "EVA": 25, "PanoramaPublic": 25, "LINCS": 25, "ExpressionAtlas": 25}

# The fields a researcher filters on before downloading, matched against attribute / column / study-fact names.
FIELDS = {
    "organism": r"organism|species|scientific.name|taxon",
    "tissue_cell": r"tissue|organ\b|organism.?part|cell.?type|cell.?line|body.?site|source.?name|^cell$|anatomic|sample.?source|isolation.?source",
    "disease_condition": r"disease|condition|phenotype|diagnos|health|clinical|tumou?r|cancer|patholog|grade|case.?control|\bgroup\b|sample.?group|cohort|\barm\b",
    "intervention": r"treat|genotype|strain|knock|agent|compound|drug|dose|infect|stimul|perturb|variation|transfect|mutation|exposure|diet|"
                    r"temperature|stress|cultivar|ecotype|variety|line\b|serovar|serotype|genetic",
    "sex": r"\bsex\b|gender",
    "age_stage": r"\bage\b|stage|develop|time.?point|\btime\b|passage|days|weeks|month|year",
    # Where a microbial or environmental sample came from (MIxS): the host, the environment, the place and the date.
    "environment_host": r"^env_|environment|biome|\bhost\b|host_|host |geo_loc|geographic|location|country|collection.?date|depth|latitude|lat_lon|"
                        r"\bph\b|salinity|isolation.?source|habitat",
}
JUNK = re.compile(r"^(?:n/?a|na|none|null|nan|-+|\.|\?|not ?applicable|not ?available|not ?provided|not ?collected|missing|unknown|"
                  r"unspecified|not ?specified|not ?determined|restricted access|not reported|undefined|other)$", re.I)
# Study-level facts that describe the submission, not the samples (ENA's "Status" is not a disease status).
ADMIN = re.compile(r"status|submission|project|sequencing|bases|updated|submitted|released|published|license|downloads|country|center|refseq|"
                   r"secondary|platform|instrument|software|quantification|modification|keyword|experiment type|^samples$|first public|"
                   r"citation|assay|minseqe|miame|technology|study type|data type|sample count|tags", re.I)
# Study-level facts whose values, not names, list the variables (ArrayExpress: Experimental Factors = "disease, sex").
NAMED_IN_VALUES = re.compile(r"experimental (?:factors|designs)", re.I)
# Sample attributes that are bookkeeping, not biology (ENA adds several to every sample).
BOOKKEEPING = re.compile(r"^ENA-|INSDC|NCBI submission|BioSampleModel|submitted_to|secondary.accession|^description$|^title$|alias|sample.?name|"
                         r"anonymized_name|qiita|^organism$|scientific.?name|taxid|^sample.?title$|identified.by|biomaterial.provider", re.I)
# Columns that identify a run or file rather than describe a sample.
TECHNICAL = re.compile(r"^(?:accession|title|run|sample|experiment|instrument|strategy|source|layout|reads|bases|platform|raw file|named group|"
                       r"molecule|library.*|label|no\. of samples|sample_id|comment\[.*\]|assay name|technology type)$", re.I)


def valid(value) -> bool:
    return bool(str(value or "").strip()) and not JUNK.match(str(value).strip())


def draw(out: Path) -> None:
    db = sqlite3.connect(DB)
    rnd = random.Random(SEED)
    rows = []
    for source, n in DRAW.items():
        ids = [a for (a,) in db.execute("select accession from datasets where source=?", (source,))]
        rows += [(source, a) for a in rnd.sample(ids, min(n, len(ids)))]
    out.mkdir(parents=True, exist_ok=True)
    totals = dict(db.execute("select source, count(*) from datasets group by source"))
    (out / "draw.json").write_text(json.dumps({"seed": SEED, "totals": totals, "draw": rows}))
    print(f"drew {len(rows)} datasets from {len(DRAW)} repositories")


def _sdrf(rec: dict) -> list[dict[str, str]]:
    """The SDRF a PRIDE submitter or ArrayExpress attached, as rows keyed by its characteristics / factor value columns."""
    found = next((f for f in rec["files"] if re.search(r"sdrf", f["name"], re.I) and (f.get("bytes") or 0) < 20_000_000), None)
    if not found:
        return []
    text = httpx.get(found["url"], timeout=60, follow_redirects=True).raise_for_status().text
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = next(reader, [])
    keep = [(i, re.sub(r"^(?:characteristics|factor ?value) ?\[(.*)\]$", r"\1", h.strip(), flags=re.I)) for i, h in enumerate(header)
            if re.match(r"^(?:characteristics|factor ?value) ?\[", h.strip(), re.I)]
    return [{name: row[i] for i, name in keep if i < len(row)} for row in reader if row]


def _ena_attributes(rec: dict) -> list[dict[str, str]]:
    """Every BioSample attribute of an ENA study's samples (the study page keeps only the varying ones), up to 300 samples."""
    rows = (rec.get("samples") or {}).get("rows") or []
    columns = (rec.get("samples") or {}).get("columns") or []
    if "Sample" not in columns:
        return []
    ids = list(dict.fromkeys(r[columns.index("Sample")] for r in rows if r[columns.index("Sample")]))[:300]
    return list(record._sample_attributes(ids).values()) if ids else []


def fields(a: dict) -> dict[str, str]:
    """Per field: "samples" (stated for at least half the samples), "study" (stated for the study only) or "missing"."""
    out = {}
    # "OrganismPart", "organism_part" and "organism part" are one name.
    spaced = lambda k: re.sub(r"(?<=[a-z])(?=[A-Z])", " ", k).replace("_", " ")
    filled = {spaced(k): v for k, v in a.get("filled", {}).items()}
    facts = {spaced(k): v for k, v in a.get("facts", {}).items()}
    for field, pattern in FIELDS.items():
        rx = re.compile(pattern, re.I)
        per_sample = any(rx.search(k) and v >= 0.5 and (field == "organism" or not BOOKKEEPING.search(k)) for k, v in filled.items())
        study = any((rx.search(label) and any(valid(v) for v in values)) or (NAMED_IN_VALUES.search(label) and any(rx.search(spaced(v)) for v in values))
                    for label, values in facts.items() if not ADMIN.search(label) or NAMED_IN_VALUES.search(label))
        if field == "organism":
            study = study or valid(a.get("organism"))
        out[field] = "samples" if per_sample else "study" if study else "missing"
    out["sample_table"] = "samples" if any(v >= 0.5 and not BOOKKEEPING.search(k) for k, v in filled.items()) else "missing"
    out["paper"] = "study" if a.get("papers") else "missing"
    out["raw_files"] = "study" if a.get("raw_files") else "missing"
    return out


def audit_one(source: str, accession: str) -> dict:
    t0 = time.time()
    out = {"accession": accession, "source": source, "notes": []}
    try:
        rec = record.record(accession)
    except Exception as error:  # a broken record is a finding, not a crash
        out.update(error=f"{type(error).__name__}: {error}"[:300], seconds=round(time.time() - t0, 1))
        return out
    if rec is None:
        out.update(error="not in index")
        return out
    live = not any(u.startswith("live record unavailable") for u in rec["unmapped"]) and source in record.ADAPTERS
    out["level"] = "live record" if live else "index only"
    # Sample rows: the study page's table, or richer raw attributes where the page trims them.
    table = rec.get("samples") or {}
    columns, rows = table.get("columns") or [], table.get("rows") or []
    sample_rows = [dict(zip(columns, r)) for r in rows]
    try:
        if source == "ENA":
            sample_rows = _ena_attributes(rec) or sample_rows
        elif source in ("PRIDE", "ArrayExpress") and not (source == "ArrayExpress" and sample_rows) and (sdrf := _sdrf(rec)):
            sample_rows, out["sdrf"] = sdrf, True
    except (httpx.HTTPError, Exception) as error:
        out["notes"].append(f"sample attributes unavailable: {type(error).__name__}")
    out["sdrf"] = out.get("sdrf", False)
    names = [n for n in dict.fromkeys(k for r in sample_rows for k in r) if not TECHNICAL.match(n.strip())]
    n = len(sample_rows)
    filled = {name: sum(valid(r.get(name)) for r in sample_rows) / n for name in names} if n else {}
    out["sample_rows"] = n
    out["filled"] = {k: round(v, 2) for k, v in list(filled.items())[:80]}
    out["facts"] = {label: [str(v)[:120] for v in values[:6]] for label, values in rec["facts"]}
    out["organism"] = rec.get("organism") or ""
    out["papers"] = len(rec.get("papers") or [])
    out["raw_files"] = any(not f["processed"] for f in rec["files"])
    out["files"] = len(rec["files"])
    out["seconds"] = round(time.time() - t0, 1)
    return out


def audit(out: Path, jobs: int, limit: int | None) -> None:
    store.DB = DB
    plan = json.loads((out / "draw.json").read_text())["draw"]
    done_path = out / "audit.jsonl"
    done = {json.loads(line)["accession"] for line in done_path.open()} if done_path.exists() else set()
    todo = [(s, a) for s, a in plan if a not in done]
    # Interleave repositories so one slow API does not hold every worker.
    random.Random(1).shuffle(todo)
    todo = todo[:limit]
    print(f"{len(done)} done, {len(todo)} to go", flush=True)
    lock = threading.Lock()
    with ThreadPoolExecutor(jobs) as pool, done_path.open("a") as sink:
        futures = {pool.submit(audit_one, s, a): a for s, a in todo}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            with lock:
                sink.write(json.dumps(result) + "\n")
                sink.flush()
            if i % 25 == 0:
                print(f"{i}/{len(todo)} {time.strftime('%H:%M:%S')}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["draw", "audit"])
    parser.add_argument("--out", type=Path, default=Path("runs/metadata-audit"))
    parser.add_argument("-j", "--jobs", type=int, default=8)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    draw(args.out) if args.step == "draw" else audit(args.out, args.jobs, args.limit)
    sys.exit(0)
