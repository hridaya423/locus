import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from dotenv import load_dotenv

from . import store
from .harvest import _get

BATCH = 500
CACHE = store.DB.parent / "ena_papers"


def _papers(client: httpx.Client, accessions: list[str], key: dict) -> dict[str, list[str]]:
    """BioProject accession -> PubMed IDs. The Filter keeps only projects with PubMed links (about 10%), so elink stays small; it returns one linkset per `id`, so the mapping stays per project."""
    term = " OR ".join(f"{a}[Project Accession]" for a in accessions)
    uids = _get(client, "esearch.fcgi", {"db": "bioproject", "term": f"({term}) AND bioproject_pubmed[Filter]", "retmax": 10000, "retmode": "json", **key})["esearchresult"]["idlist"]
    if not uids:
        return {}
    linked = {}
    for s in _get(client, "elink.fcgi", {"dbfrom": "bioproject", "db": "pubmed", "cmd": "neighbor", "id": uids, "retmode": "json", **key})["linksets"]:
        if pmids := [p for d in s.get("linksetdbs", []) for p in d["links"]]:
            linked[s["ids"][0]] = pmids
    if not linked:
        return {}
    summary = _get(client, "esummary.fcgi", {"db": "bioproject", "id": ",".join(linked), "retmode": "json", **key})["result"]
    return {summary[u]["project_acc"]: p for u, p in linked.items()}


def _write(db: sqlite3.Connection, found: dict[str, list[str]]) -> None:
    # Projects linked to more than 3 papers are umbrella projects; their links are mostly reuse papers and would
    # merge unrelated datasets into one study, so they get none.
    rows = [(json.dumps([f"pmid:{p}" for p in pmids]), acc) for acc, pmids in found.items() if len(pmids) <= 3]
    for attempt in range(8):
        try:
            db.executemany("UPDATE datasets SET papers = ? WHERE accession = ? AND papers = '[]'", rows)
            db.commit()
            return
        except sqlite3.OperationalError:
            db.rollback()
            time.sleep(2 ** attempt)
    raise RuntimeError("database stayed locked")


def enrich_ena(dry: int = 0) -> int:
    """PubMed links for ENA studies via NCBI BioProject. Resumable: each finished batch is cached in data/ena_papers/."""
    from os import environ
    key = {"api_key": environ["NCBI_API_KEY"]}
    db = store.connect()
    CACHE.mkdir(exist_ok=True)
    todo = [r[0] for r in db.execute("SELECT accession FROM datasets WHERE source = 'ENA' AND papers = '[]' ORDER BY accession")]
    done = set()
    for f in sorted(CACHE.glob("*.json")):
        batch = json.loads(f.read_text())
        _write(db, batch["found"])
        done.update(batch["tried"])
    todo = [a for a in todo if a not in done]
    if dry:
        todo = todo[:: max(1, len(todo) // dry)][:dry]
    print(f"ENA studies without papers: {len(todo)} ({len(done)} already tried)", flush=True)

    with httpx.Client() as client:
        def run(batch: list[str]) -> tuple[list[str], dict]:
            """If NCBI keeps failing a batch, split it so one bad project cannot sink the rest."""
            try:
                return batch, _papers(client, batch, key)
            except RuntimeError:
                if len(batch) == 1:
                    print(f"skipped {batch[0]}", flush=True)
                    return batch, {}
                mid = len(batch) // 2
                (_, a), (_, b) = run(batch[:mid]), run(batch[mid:])
                return batch, a | b

        found_total = 0
        started = time.time()
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(run, todo[i:i + BATCH]) for i in range(0, len(todo), BATCH)]
            for n, future in enumerate(as_completed(futures), 1):
                batch, found = future.result()
                found_total += len(found)
                if dry:
                    print(found)
                else:
                    (CACHE / f"{batch[0]}.json").write_text(json.dumps({"tried": batch, "found": found}))
                    _write(db, found)
                print(f"batch {n}/{len(futures)}: {found_total} studies linked, {time.time() - started:.0f}s", flush=True)
    return found_total


if __name__ == "__main__":
    load_dotenv()
    enrich_ena(int(sys.argv[2]) if sys.argv[1:2] == ["--dry"] else 0)
