import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import store

API = "https://www.ebi.ac.uk/biostudies/api/v1"
PAGE_SIZE = 100
PAGES = Path(__file__).resolve().parent.parent / "data" / "arrayexpress_pages"
# BioStudies search caps at ~20000 results (offset cap), so each prefix query must stay under that.
# These are every nonzero, non-GEOD first letter after "E-" (checked against the EBI API); GEOD
# (the GEO mirror, ~59k studies) is deliberately excluded, and its one native sibling (GEUV) is
# listed by exact prefix instead of by its "G" letter.
LETTERS = "ABCDEFHIJLMNPRSTUW"
EXTRA_QUERIES = ["accession:E-GEUV-*"]


def _get(client: httpx.Client, path: str, params: dict | None = None) -> httpx.Response:
    for attempt in range(6):
        try:
            response = client.get(f"{API}/{path}", params=params, timeout=60)
            if response.status_code in (200, 404):
                return response
        except httpx.HTTPError:
            pass
        time.sleep(2**attempt)
    raise RuntimeError(f"{path} {params} failed after retries")


def _upsert(db: sqlite3.Connection, rows: list[dict]) -> None:
    """Upsert, retrying while another harvester holds the SQLite write lock."""
    for _ in range(20):
        try:
            return store.upsert(db, rows)
        except sqlite3.OperationalError:
            db.rollback()
    raise RuntimeError("database stayed locked")


def list_accessions(client: httpx.Client) -> list[str]:
    """Every native ArrayExpress study accession, i.e. every public BioStudies/ArrayExpress study except E-GEOD-* (GEO mirrors, already in our store from GEO)."""
    accessions: set[str] = set()
    for query in [f"accession:E-{letter}*" for letter in LETTERS] + EXTRA_QUERIES:
        page = 1
        while True:
            data = _get(client, "ArrayExpress/search", {"query": query, "pageSize": PAGE_SIZE, "page": page}).json()
            hits = [h["accession"] for h in data["hits"] if h["type"] == "study"]
            if not hits:
                break
            accessions.update(hits)
            if page * PAGE_SIZE >= data["totalHits"]:
                break
            page += 1
    return sorted(accessions)


def _values(attrs: list[dict], name: str) -> list[str]:
    return list(dict.fromkeys(a["value"] for a in attrs if a.get("name") == name and a.get("value")))


def fetch_full(client: httpx.Client, accession: str) -> dict | None:
    """The full BioStudies record for one study, cached on disk so a rerun skips it."""
    path = PAGES / f"{accession}.json"
    if not path.exists():
        response = _get(client, f"studies/{accession}")
        if response.status_code != 200:
            return None
        path.write_text(response.text)
    return json.loads(path.read_text())


def _row(full: dict) -> dict:
    accession = full["accno"]
    top = {a["name"]: a["value"] for a in full.get("attributes", [])}
    section = full.get("section", {})
    attrs = section.get("attributes", [])
    samples, papers = None, []
    for group in section.get("subsections", []):
        for item in group if isinstance(group, list) else [group]:
            if item.get("type") == "Samples":
                counts = _values(item.get("attributes", []), "Sample count")
                samples = int(counts[0]) if counts else samples
            elif item.get("type") == "Publication":
                pmid = item.get("accno", "")
                if pmid.isdigit():
                    papers.append(f"pmid:{pmid}")
                for doi in _values(item.get("attributes", []), "DOI"):
                    papers.append(f"doi:{doi.strip().rstrip('.').lower()}")
    return {
        "accession": accession,
        "source": "ArrayExpress",
        "title": (_values(attrs, "Title") or [top.get("Title", "")])[0],
        "summary": "\n".join(_values(attrs, "Description")),
        "organism": "; ".join(_values(attrs, "Organism")),
        "modality": "; ".join(_values(attrs, "Study type")),
        "samples": samples,
        "published": top.get("ReleaseDate") or None,
        "papers": list(dict.fromkeys(papers)),
        "url": f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{accession}",
    }


def harvest_arrayexpress() -> int:
    """Every native ArrayExpress study (not E-GEOD-*). Resumable: full records are cached under data/arrayexpress_pages."""
    PAGES.mkdir(parents=True, exist_ok=True)
    db = store.connect()
    with httpx.Client() as client:
        accessions = list_accessions(client)
        print(f"ArrayExpress native accessions: {len(accessions)}", flush=True)

        done, batch = 0, []
        with ThreadPoolExecutor(max_workers=12) as pool:
            for accession, full in zip(accessions, pool.map(lambda a: fetch_full(client, a), accessions)):
                if full is None:
                    print(f"skipped {accession}: fetch failed", flush=True)
                    continue
                batch.append(_row(full))
                if len(batch) >= 200:
                    _upsert(db, batch)
                    done += len(batch)
                    batch = []
                    print(f"ArrayExpress {done}/{len(accessions)}", flush=True)
        if batch:
            _upsert(db, batch)
            done += len(batch)
    return done


if __name__ == "__main__":
    started = time.time()
    count = harvest_arrayexpress()
    print(f"done: ArrayExpress {count} studies in {time.time() - started:.0f}s", flush=True)
