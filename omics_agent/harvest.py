import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from dotenv import load_dotenv

from . import store

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PAGE = 200


class TooLarge(Exception):
    """NCBI refuses to render more than 10 MB as JSON; the batch must be split."""


def _get(client: httpx.Client, endpoint: str, params: dict) -> dict:
    for attempt in range(6):
        try:
            response = client.post(f"{EUTILS}/{endpoint}", data=params, timeout=120)
            if response.status_code == 200:
                body = response.json()
                if "result" in body or "esearchresult" in body or "linksets" in body:
                    return body
                if "cannot be transformed to JSON" in response.text:
                    raise TooLarge
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{endpoint} failed after retries: {params.get('retstart')}")


def _row(r: dict) -> dict:
    return {
        "accession": r["accession"],
        "source": "GEO",
        "title": r["title"],
        "summary": r["summary"],
        "organism": r["taxon"],
        "modality": r["gdstype"],
        "samples": int(r["n_samples"]) if r.get("n_samples") else None,
        "published": r.get("pdat", "").replace("/", "-") or None,
        "papers": [f"pmid:{p}" for p in r.get("pubmedids") or []],
        "url": f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={r['accession']}",
    }


def _all_ids(client: httpx.Client, key: dict) -> list[str]:
    ids, start = [], 0
    while True:
        found = _get(client, "esearch.fcgi", {"db": "gds", "term": "gse[ETYP]", "retstart": start, "retmax": 10000, "retmode": "json", **key})["esearchresult"]
        ids += found["idlist"]
        start += 10000
        if start >= int(found["count"]):
            return ids


def harvest_geo() -> int:
    """Every GEO series. Resumable: lists all series IDs, then fetches only the ones not yet stored."""
    key = {"api_key": os.environ["NCBI_API_KEY"]}
    db = store.connect()
    have = {row[0] for row in db.execute("SELECT accession FROM datasets WHERE source = 'GEO'")}
    with httpx.Client() as client:
        ids = _all_ids(client, key)
        # A GEO series UID is 200000000 plus the GSE number.
        todo = [i for i in ids if f"GSE{int(i) - 200000000}" not in have]
        print(f"GEO series: {len(ids)}, stored: {len(have)}, to fetch: {len(todo)}", flush=True)

        def page(batch: list[str]) -> list[dict]:
            """Fetch a batch; if NCBI keeps failing it, split it so one bad ID cannot sink the rest."""
            try:
                result = _get(client, "esummary.fcgi", {"db": "gds", "id": ",".join(batch), "retmode": "json", **key})["result"]
            except (RuntimeError, TooLarge):
                if len(batch) == 1:
                    print(f"skipped UID {batch[0]}", flush=True)
                    return []
                return page(batch[: len(batch) // 2]) + page(batch[len(batch) // 2 :])
            return [_row(result[uid]) for uid in result.get("uids", []) if result[uid].get("entrytype") == "GSE"]

        done = 0
        # 10 workers stay under NCBI's 10 requests/second limit for keyed clients, because each request takes about 4 seconds.
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(page, todo[i:i + PAGE]) for i in range(0, len(todo), PAGE)]
            for future in as_completed(futures):
                rows = future.result()
                store.upsert(db, rows)
                done += len(rows)
                print(f"GEO {done}/{len(todo)}", flush=True)
    return done


if __name__ == "__main__":
    load_dotenv()
    started = time.time()
    count = harvest_geo()
    print(f"GEO done: {count} series in {time.time() - started:.0f}s", file=sys.stderr)
