import csv
import re
import sqlite3
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

from . import store

API = "https://www.ebi.ac.uk/ena/portal/api/search"
CACHE = Path(__file__).resolve().parent.parent / "data" / "ena"
STUDY_FIELDS = "study_accession,secondary_study_accession,study_title,study_description,scientific_name,first_public,center_name,geo_accession"
RUN_FIELDS = "study_accession,library_strategy,instrument_model"
YEARS = range(2008, date.today().year + 2)  # ENA/SRA predates 2008 only for a handful of legacy records; +2 covers clock skew

csv.field_size_limit(10_000_000)  # a few study_description values exceed the 128k default


def _quarters(year: int) -> list[tuple[str, str]]:
    return [(f"{year}-{a}", f"{year}-{b}" if b != "01-01" else f"{year + 1}-01-01") for a, b in (("01-01", "04-01"), ("04-01", "07-01"), ("07-01", "10-01"), ("10-01", "01-01"))]


def _download(path: Path, result: str, fields: str, query: str) -> None:
    """Fetch one date-bounded chunk to disk, skipping if already cached. Chunked by quarter/year
    because the portal API drops connections on single requests that run past ~2 minutes."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(6):
        response = httpx.get(API, params={"result": result, "fields": fields, "query": query, "limit": 0, "format": "tsv"}, timeout=300)
        if response.status_code == 200 and not response.text.lstrip().startswith("<"):
            path.write_text(response.text)
            return
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{result} {query} failed after retries")


def _chunks() -> list[tuple[Path, str, str, str]]:
    chunks = [(CACHE / "studies" / f"{y}.tsv", "study", STUDY_FIELDS, f"first_public>={y}-01-01 AND first_public<{y + 1}-01-01") for y in YEARS]
    chunks += [(CACHE / "read_run" / f"{y}q{i}.tsv", "read_run", RUN_FIELDS, f"first_public>={s} AND first_public<{e}") for y in YEARS for i, (s, e) in enumerate(_quarters(y), 1)]
    return chunks


def fetch_studies() -> dict[str, dict]:
    studies = {}
    for year in YEARS:
        with (CACHE / "studies" / f"{year}.tsv").open(newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            header = next(reader)
            for row in reader:
                d = dict(zip(header, row))
                studies[d["study_accession"]] = d
    return studies


def fetch_read_stats() -> tuple[Counter, dict[str, set], dict[str, set]]:
    """Per-study run count, library strategies and instrument models, aggregated from the
    run-level TSVs (there is no study-level "has reads" field, so this is the only way to know)."""
    run_count, strategies, models = Counter(), defaultdict(set), defaultdict(set)
    for year in YEARS:
        for i in range(1, 5):
            with (CACHE / "read_run" / f"{year}q{i}.tsv").open(newline="") as fh:
                reader = csv.reader(fh, delimiter="\t")
                next(reader)
                for _run, study_acc, strategy, model in reader:
                    if not study_acc:
                        continue
                    run_count[study_acc] += 1
                    if strategy:
                        strategies[study_acc].add(strategy)
                    if model:
                        models[study_acc].add(model)
    return run_count, strategies, models


def _fetch_missing(accessions: set[str]) -> dict[str, dict]:
    """A study can fall outside every yearly bucket when its first read run and its own
    first_public date straddle a year boundary; pull those few stragglers directly by accession."""
    studies = {}
    accs = sorted(accessions)
    with httpx.Client() as client:
        for i in range(0, len(accs), 200):
            query = " OR ".join(f'study_accession="{a}"' for a in accs[i:i + 200])
            response = client.get(API, params={"result": "study", "fields": STUDY_FIELDS, "query": query, "limit": 0, "format": "tsv"}, timeout=120)
            lines = response.text.splitlines()
            if response.status_code != 200 or len(lines) < 2:
                continue
            header = lines[0].split("\t")
            for line in lines[1:]:
                d = dict(zip(header, line.split("\t")))
                studies[d["study_accession"]] = d
    return studies


_DIGITS = re.compile(r"\d+")


def _template_title(study: dict) -> str:
    return re.sub(r"\s+", " ", _DIGITS.sub("#", study.get("study_title", ""))).strip().lower()


def _noisy(studies: dict, run_count: Counter, candidates: list[str]) -> set[str]:
    """Mass single-isolate submissions (pathogen surveillance panels, per-accession resequencing
    of one plant/strain collection) share one templated title across hundreds-to-thousands of
    near-empty studies. Evidence: on the full non-GEO/has-reads set, grouping by title with digits
    stripped and keeping groups of 15+ members that are *all* 5 runs or fewer isolates exactly the
    "mrsa surveillance ii" / "zea mays exome capture - w#_#" pattern while leaving real studies
    (varying run counts, e.g. "homo sapiens raw sequence reads") alone."""
    groups = defaultdict(list)
    for acc in candidates:
        groups[_template_title(studies[acc])].append(acc)
    return {acc for accs in groups.values() if len(accs) >= 15 and all(run_count[a] <= 5 for a in accs) for acc in accs}


def _row(acc: str, study: dict, runs: int, strategies: set, models: set) -> dict:
    parts = [study.get("study_description") or ""]
    if secondary := study.get("secondary_study_accession"):
        parts.append(f"ENA/SRA accession: {secondary}")
    if center := study.get("center_name"):
        parts.append(f"Submitted by: {center}")
    return {
        "accession": acc,
        "source": "ENA",
        "title": study.get("study_title") or study.get("secondary_study_accession") or acc,
        "summary": "\n".join(p for p in parts if p),
        "organism": study.get("scientific_name") or "",
        "modality": "; ".join(sorted(strategies) + sorted(models)),
        "samples": runs,
        "published": study.get("first_public") or None,
        "papers": [],
        "url": f"https://www.ebi.ac.uk/ena/browser/view/{acc}",
    }


def _upsert(db: sqlite3.Connection, rows: list[dict]) -> None:
    """Upsert, retrying while another harvester holds the write lock."""
    for _ in range(20):
        try:
            return store.upsert(db, rows)
        except sqlite3.OperationalError:
            db.rollback()
    raise RuntimeError("database stayed locked")


def harvest_ena() -> int:
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda c: _download(*c), _chunks()))

    studies = fetch_studies()
    print(f"studies: {len(studies)}", flush=True)

    run_count, strategies, models = fetch_read_stats()
    print(f"studies with read runs: {len(run_count)}", flush=True)

    if missing := set(run_count) - set(studies):
        studies.update(_fetch_missing(missing))
        print(f"fetched {len(missing)} studies the yearly buckets missed (year-boundary stragglers)", flush=True)

    with_reads = [a for a in run_count if a in studies]
    non_geo = [a for a in with_reads if not studies[a].get("geo_accession")]
    print(f"not a GEO mirror: {len(non_geo)}", flush=True)

    noisy = _noisy(studies, run_count, non_geo)
    surveillance = {a for a in non_geo if a not in noisy and "surveillance" in (studies[a].get("study_title", "") + studies[a].get("study_description", "")).lower()}
    keep = [a for a in non_geo if a not in noisy and a not in surveillance]
    print(f"dropped {len(noisy)} templated single-isolate dumps, {len(surveillance)} surveillance studies: {len(keep)} remain", flush=True)

    db = store.connect()
    rows = [_row(a, studies[a], run_count[a], strategies[a], models[a]) for a in keep]
    for i in range(0, len(rows), 5000):
        _upsert(db, rows[i:i + 5000])
        print(f"wrote {min(i + 5000, len(rows))}/{len(rows)}", flush=True)
    return len(rows)


if __name__ == "__main__":
    started = time.time()
    n = harvest_ena()
    print(f"done: ENA {n} studies in {time.time() - started:.0f}s", flush=True)
