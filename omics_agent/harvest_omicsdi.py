import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import store

WS = "https://www.omicsdi.org/ws/dataset/search"
PAGE_SIZE = 1000
PAGES = Path(__file__).resolve().parent.parent / "data" / "omicsdi_pages"

REPOS = (
    "MassIVE", "iProX", "jPOST", "PeptideAtlas", "PanoramaPublic", "MetaboLights",
    "GNPS", "EGA", "dbGaP", "NODE", "ExpressionAtlas", "EVA", "LINCS",
)


def _get(client: httpx.Client, params: dict) -> dict:
    for attempt in range(6):
        try:
            response = client.get(WS, params=params, timeout=60)
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{params} failed after retries")


def _upsert(db: sqlite3.Connection, rows: list[dict]) -> None:
    """Upsert, retrying while another harvester holds the write lock.
    A dataset already stored under another repository keeps it: OmicsDI lists some datasets under several."""
    for _ in range(20):
        owned = dict(db.execute(f"SELECT accession, source FROM datasets WHERE accession IN ({','.join('?' * len(rows))})", [r["accession"] for r in rows]))
        rows = [r for r in rows if owned.get(r["accession"], r["source"]) == r["source"]]
        try:
            return store.upsert(db, rows)
        except sqlite3.OperationalError:
            db.rollback()
    raise RuntimeError("database stayed locked")


def _published(raw: str | None) -> str | None:
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if raw and len(raw) == 8 else None


def _row(repo: str, d: dict) -> dict:
    organisms = "; ".join(dict.fromkeys(o["name"].strip() for o in d.get("organisms") or [] if o.get("name")))
    return {
        "accession": d["id"],
        # GNPS datasets are MassIVE submissions under their MSV accessions.
        "source": "MassIVE" if d["id"].startswith("MSV") else repo,
        "title": d.get("title") or "",
        "summary": re.sub(r"<[^>]+>", "", d.get("description") or ""),
        "organism": organisms,
        "modality": "; ".join(d.get("omicsType") or []) or "Unknown",
        "samples": None,
        "published": _published(d.get("publicationDate")),
        "papers": [],
        "url": f"https://www.omicsdi.org/dataset/{d['source']}/{d['id']}",
    }


def harvest_repo(client: httpx.Client, repo: str) -> list[dict]:
    """Every dataset for one OmicsDI repository. Resumable: each page is cached under data/omicsdi_pages."""
    query = f'repository:"{repo}"'
    count = _get(client, {"query": query, "start": 0, "size": 1, "faceCount": 0})["count"]
    pages = -(-count // PAGE_SIZE)

    def page(n: int) -> list[dict]:
        path = PAGES / f"{repo}_{n:04d}.json"
        if not path.exists():
            data = _get(client, {"query": query, "start": n * PAGE_SIZE, "size": PAGE_SIZE, "faceCount": 0})
            path.write_text(json.dumps(data["datasets"]))
        return json.loads(path.read_text())

    with ThreadPoolExecutor(max_workers=6) as pool:
        datasets = {d["id"]: d for batch in pool.map(page, range(pages)) for d in batch}
    print(f"{repo}: {count} listed, {len(datasets)} fetched", flush=True)
    # E-GEOD-N is a copy of GEO series GSEN, which the GEO harvest already holds.
    return [_row(repo, d) for d in datasets.values() if not d["id"].startswith("E-GEOD-")]


def harvest_workbench(client: httpx.Client) -> list[dict]:
    """Metabolomics Workbench lists twice as many studies natively as OmicsDI does, with species and sample counts."""
    base = "https://www.metabolomicsworkbench.org/rest/study/study_id/ST"
    studies = client.get(f"{base}/summary", timeout=300).json().values()
    disease = {d["Study ID"]: d["Disease"] for d in client.get(f"{base}/disease", timeout=300).json().values()}
    return [
        {
            "accession": s["study_id"],
            "source": "MetabolomicsWorkbench",
            "title": s["study_title"],
            "summary": f"{s['analysis_type']} metabolomics study of {s['species']} from {s['institute']}."
            + (f" Disease: {disease[s['study_id']]}." if s["study_id"] in disease else ""),
            "organism": s["species"],
            "modality": f"Metabolomics; {s['analysis_type']}",
            "samples": int(s["number_of_samples"]) if s["number_of_samples"].isdigit() else None,
            "published": s["release_date"] or None,
            "papers": [],
            "url": f"https://www.metabolomicsworkbench.org/data/DRCCMetadata.php?StudyID={s['study_id']}",
        }
        for s in studies
    ]


def harvest_omicsdi() -> int:
    PAGES.mkdir(parents=True, exist_ok=True)
    db = store.connect()
    total = 0
    with httpx.Client() as client:
        for repo in REPOS:
            rows = harvest_repo(client, repo)
            _upsert(db, rows)
            total += len(rows)
        rows = harvest_workbench(client)
        _upsert(db, rows)
    return total + len(rows)


if __name__ == "__main__":
    started = time.time()
    n = harvest_omicsdi()
    print(f"done: {n} datasets across {len(REPOS)} repositories in {time.time() - started:.0f}s", flush=True)
