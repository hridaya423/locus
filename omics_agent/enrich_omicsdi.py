import itertools
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import store

WS = "https://www.omicsdi.org/ws/dataset"
DATA = Path(__file__).resolve().parent.parent / "data"
PAGES = DATA / "omicsdi_pages"
DETAILS = DATA / "omicsdi_details"
WORKERS = 8
BATCH = 500

SOURCES = (
    "MassIVE", "iProX", "jPOST", "PeptideAtlas", "PanoramaPublic", "MetaboLights",
    "EGA", "dbGaP", "NODE", "ExpressionAtlas", "EVA", "LINCS",
)


def _keys() -> dict[str, str]:
    """OmicsDI source key per accession, from the cached search pages."""
    return {d["id"]: d["source"] for f in PAGES.glob("*.json") for d in json.loads(f.read_text())}


def _links(d: dict) -> list[str]:
    """Links from the cross references and the free-text `publication` field. Repositories put PMIDs, DOIs and junk such as 'submitted' under pubmed, so each value is classified."""
    refs = [p for k, v in (d.get("cross_references") or {}).items() if k.lower() in ("pubmed", "pmid") for p in v]
    text = " ".join((d.get("additional") or {}).get("publication") or [])
    refs += re.findall(r"PMID:\s*(\d+)", text) + re.findall(r"\b10\.\d{4,9}/\S+", text)
    links = [f"pmid:{r}" if r.isdigit() else f"doi:{r.rstrip('.,;)').lower()}" for r in map(str.strip, refs) if r.isdigit() or re.match(r"10\.\d{4,9}/\S+$", r)]
    return list(dict.fromkeys(sorted(links, key=lambda x: x[0] != "p")))


def _fetch(client: httpx.Client, key: str, accession: str) -> list[str] | None:
    """Links for one dataset, cached under data/omicsdi_details (empty results too). None after repeated 429/5xx."""
    path = DETAILS / f"{accession}.json"
    if path.exists():
        return json.loads(path.read_text())
    for attempt in range(6):
        try:
            response = client.get(f"{WS}/{key}/{accession}", timeout=60)
            if response.status_code in (200, 404):
                links = _links(response.json()) if response.status_code == 200 else []
                path.write_text(json.dumps(links))
                return links
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2 ** attempt)
    return None


def _write(db: sqlite3.Connection, updates: list[tuple[str, str]]) -> None:
    """Fill empty `papers` only, retrying while another process holds the write lock."""
    for attempt in range(20):
        try:
            db.executemany("UPDATE datasets SET papers=? WHERE accession=? AND papers='[]'", updates)
            return db.commit()
        except sqlite3.OperationalError:
            db.rollback()
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError("database stayed locked")


def _spread(todo: list[tuple[str, str, str]], n: int) -> list[tuple[str, str, str]]:
    """n accessions taken round-robin across sources."""
    by = defaultdict(list)
    for t in todo:
        by[t[0]].append(t)
    return list(itertools.islice((t for group in itertools.zip_longest(*by.values()) for t in group if t), n))


def enrich(sample: int | None = None) -> None:
    DETAILS.mkdir(parents=True, exist_ok=True)
    db = store.connect()
    keys = _keys()
    marks = ",".join("?" * len(SOURCES))
    rows = db.execute(f"SELECT source, accession FROM datasets WHERE papers='[]' AND source IN ({marks})", SOURCES).fetchall()
    todo = [(s, a, keys[a]) for s, a in rows if a in keys]
    print(f"{len(rows)} rows need links, {len(todo)} have an OmicsDI key", flush=True)
    if sample:
        todo = _spread(todo, sample)

    hit, seen, failed, pending = Counter(), Counter(), Counter(), []
    started = time.time()
    with httpx.Client(limits=httpx.Limits(max_connections=WORKERS)) as client, ThreadPoolExecutor(WORKERS) as pool:
        for n, ((source, accession, _), links) in enumerate(zip(todo, pool.map(lambda t: _fetch(client, t[2], t[1]), todo)), 1):
            seen[source] += 1
            if links is None:
                failed[source] += 1
            elif links:
                hit[source] += 1
                pending.append((json.dumps(links), accession))
            if len(pending) >= BATCH and not sample:
                _write(db, pending)
                pending = []
            if n % 2000 == 0:
                print(f"{n}/{len(todo)} {n / (time.time() - started):.1f}/s", flush=True)
    if pending and not sample:
        _write(db, pending)

    elapsed = time.time() - started
    for source in SOURCES:
        print(f"{source}: {hit[source]}/{seen[source]} linked, {failed[source]} failed")
    print(f"done: {len(todo)} accessions in {elapsed:.0f}s ({len(todo) / max(elapsed, 1):.1f}/s){' [sample, DB untouched]' if sample else ''}", flush=True)


if __name__ == "__main__":
    enrich(int(sys.argv[2]) if sys.argv[1:2] == ["--sample"] else None)
