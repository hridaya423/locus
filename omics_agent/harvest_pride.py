import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import store

PRIDE = "https://www.ebi.ac.uk/pride/ws/archive/v3"
PAGE_SIZE = 100
PAGES = Path(__file__).resolve().parent.parent / "data" / "pride_pages"
CELLXGENE = "https://api.cellxgene.cziscience.com/curation/v1/datasets"
CELLXGENE_CACHE = Path.home() / ".cache" / "omics-agent" / "cellxgene.json"


def _get(client: httpx.Client, path: str, params: dict | None = None) -> httpx.Response:
    for attempt in range(5):
        try:
            response = client.get(f"{PRIDE}/{path}", params=params, timeout=60)
            if response.status_code == 200:
                return response
        except httpx.HTTPError:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{path} {params} failed after retries")


def _upsert(db: sqlite3.Connection, rows: list[dict]) -> None:
    """Upsert, retrying while the GEO harvester holds the write lock."""
    for _ in range(20):
        try:
            return store.upsert(db, rows)
        except sqlite3.OperationalError:
            db.rollback()
    raise RuntimeError("database stayed locked")


def _names(items: list | None) -> list[str]:
    names = [i if isinstance(i, str) else i.get("name") or i.get("value") or i.get("label") or "" for i in items or []]
    return list(dict.fromkeys(n.strip() for n in names if n.strip()))


def _papers(references: list) -> list[str]:
    papers = []
    for ref in references or []:
        if isinstance(ref, str):
            pmids = re.findall(r"pubmed:\s*(\d+)", ref, re.I)
            dois = re.findall(r"doi:\s*(\S+)", ref, re.I)
        else:
            pmids = [str(ref.get("pubmedID") or ref.get("pubmedId") or 0)]
            dois = [ref.get("doi") or ""]
        papers += [f"pmid:{p}" for p in pmids if int(p)]
        papers += [f"doi:{d.strip().rstrip('.').lower()}" for d in dois if d.strip().rstrip(".")]
    return list(dict.fromkeys(papers))


def _pride_row(p: dict) -> dict:
    parts = [p.get("projectDescription") or ""]
    if p.get("sampleProcessingProtocol"):
        parts.append("Sample processing: " + p["sampleProcessingProtocol"][:1500])
    for label, keys in (("Diseases", ("diseases",)), ("Tissues", ("organismParts", "organismsPart")), ("Instruments", ("instruments",))):
        if names := _names(next((p[k] for k in keys if p.get(k)), None)):
            parts.append(f"{label}: {', '.join(names)}")
    return {
        "accession": p["accession"],
        "source": "PRIDE",
        "title": p.get("title") or "",
        "summary": "\n".join(parts),
        "organism": ", ".join(_names(p.get("organisms"))),
        "modality": "Proteomics: " + ", ".join(_names(p.get("experimentTypes"))),
        "samples": None,
        "published": p.get("publicationDate") or None,
        "papers": _papers(p.get("references")),
        "url": f"https://www.ebi.ac.uk/pride/archive/projects/{p['accession']}",
    }


def _cellxgene_row(d: dict) -> dict:
    donors = len(d.get("donor_id") or [])
    parts = [
        f"Collection: {d.get('collection_name')}",
        f"Diseases: {', '.join(_names(d.get('disease')))}",
        f"Tissues: {', '.join(_names(d.get('tissue')))}",
        f"Cells: {d.get('cell_count')}, donors: {donors}",
    ]
    return {
        "accession": d["dataset_id"],
        "source": "CELLxGENE",
        "title": d.get("title") or "",
        "summary": "\n".join(parts),
        "organism": ", ".join(_names(d.get("organism"))),
        "modality": "Single-cell: " + ", ".join(_names(d.get("assay"))),
        "samples": donors or None,
        "published": (d.get("published_at") or "")[:10] or None,
        "papers": [f"doi:{d['collection_doi'].lower()}"] if d.get("collection_doi") else [],
        "url": f"https://cellxgene.cziscience.com/collections/{d['collection_id']}",
    }


def harvest_pride() -> int:
    """Every PRIDE project. Resumable: each page is saved under data/pride_pages and fetched only if missing."""
    PAGES.mkdir(parents=True, exist_ok=True)
    db = store.connect()
    with httpx.Client() as client:
        total = int(_get(client, "projects/count").text)
        pages = -(-total // PAGE_SIZE)
        print(f"PRIDE projects: {total}, pages: {pages}", flush=True)

        def page(n: int) -> list[dict]:
            path = PAGES / f"page_{n:04d}.json"
            if not path.exists():
                projects = _get(client, "projects", {"page": n, "pageSize": PAGE_SIZE}).json()
                path.write_text(json.dumps(projects))
                time.sleep(0.2)
            return [_pride_row(p) for p in json.loads(path.read_text())]

        done = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for n, rows in enumerate(pool.map(page, range(pages))):
                _upsert(db, rows)
                done += len(rows)
                print(f"PRIDE page {n + 1}/{pages}, rows {done}", flush=True)
    return done


def top_up_from_search() -> int:
    """Add projects the /projects listing never returns (PRD and PAD accession series, and very recent ones) via the search endpoint."""
    db = store.connect()
    have = {row[0] for row in db.execute("SELECT accession FROM datasets WHERE source = 'PRIDE'")}
    with httpx.Client() as client:
        pages = -(-int(_get(client, "projects/count").text) // PAGE_SIZE) + 1

        def page(n: int) -> list[dict]:
            response = _get(client, "search/projects", {"page": n, "pageSize": PAGE_SIZE, "sortDirection": "DESC", "sortFields": "submissionDate"})
            return response.json() if response.content.strip() else []

        with ThreadPoolExecutor(max_workers=4) as pool:
            found = {p["accession"]: p for batch in pool.map(page, range(pages)) for p in batch}
    rows = [_pride_row(p) for a, p in found.items() if a not in have]
    _upsert(db, rows)
    return len(rows)


def harvest_cellxgene() -> int:
    """Every CELLxGENE dataset, from the cached list or a fresh download."""
    if not CELLXGENE_CACHE.exists():
        CELLXGENE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CELLXGENE_CACHE.write_text(httpx.get(CELLXGENE, timeout=120).text)
    rows = [_cellxgene_row(d) for d in json.loads(CELLXGENE_CACHE.read_text())]
    _upsert(store.connect(), rows)
    return len(rows)


if __name__ == "__main__":
    started = time.time()
    cellxgene = harvest_cellxgene()
    print(f"CELLxGENE: {cellxgene} datasets", flush=True)
    pride = harvest_pride()
    added = top_up_from_search()
    print(f"PRIDE search top-up: {added} projects the listing missed", flush=True)
    pride += added
    print(f"done: PRIDE {pride} projects, CELLxGENE {cellxgene} datasets in {time.time() - started:.0f}s", flush=True)
