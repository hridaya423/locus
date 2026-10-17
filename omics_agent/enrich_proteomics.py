import json
import random
import re
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest
from pathlib import Path

import httpx

from . import store
from .harvest_pride import PAGES, PRIDE, _names

DATA = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA / "proxi"
CHANGED = DATA / "enriched_proteomics.txt"
MASSIVE = "https://massive.ucsd.edu/ProteoSAFe/proxi/v0.1/datasets"
PROXI = "https://proteomecentral.proteomexchange.org/api/proxi/v0.1/datasets"
OMICSDI = "https://www.omicsdi.org/ws/dataset/get"
SOURCES = ("PRIDE", "MassIVE", "iProX", "jPOST", "PanoramaPublic", "PeptideAtlas")
WORKERS = 24
BATCH = 500
JUNK = re.compile(r"unknown|no ptms|not (available|applicable)|instrument model", re.I)
PTMS = {"phosphorylation": "phospho", "ubiquitination": "glygly|ubiquit", "glycosylation": "glyco"}


def _flat(items: list | None):
    """CV params from PROXI lists, which nest them as plain lists (MassIVE) or {"terms": [...]} groups (ProteomeCentral)."""
    for i in items or []:
        yield from i["terms"] if "terms" in i else i if isinstance(i, list) else [i]


def _clean(names: list[str]) -> list[str]:
    return [n for n in names if not JUNK.match(n)]


def _pride(p: dict) -> tuple[dict, str]:
    keys = {"instruments": "instruments", "tissues": "organismParts", "diseases": "diseases", "keywords": "keywords",
            "modifications": "identifiedPTMStrings", "quantification": "quantificationMethods", "experiment_types": "experimentTypes"}
    meta = {k: _clean(_names(p.get(v))) for k, v in keys.items()} | {"source": ["PRIDE API"]}
    return meta, ", ".join(_names(p.get("organisms")))


def _proxi(d: dict, source: str) -> tuple[dict, str]:
    terms = lambda key: list(_flat(d.get(key)))
    species = [t["value"].strip() for t in terms("species") if t.get("accession") == "MS:1001469" and t.get("value")]
    keywords = [k.strip() for t in terms("keywords") for k in re.split(r"[,;]", t.get("value") or "")]
    meta = {
        "instruments": _clean(_names(terms("instruments"))),
        "keywords": list(dict.fromkeys(k for k in keywords if k)),
        "modifications": _clean(_names(terms("modifications"))),
        "source": [source],
    }
    return meta, "; ".join(dict.fromkeys(species))


def _omicsdi(d: dict) -> tuple[dict, str]:
    meta = {k: _clean(_names(d.get(k))) for k in ("instruments", "tissues", "diseases", "keywords")}
    meta["source"] = ["OmicsDI"]
    return meta, "; ".join(dict.fromkeys(_names(d.get("organisms"))))


def _request(accession: str, source: str) -> tuple[str, dict]:
    if accession.startswith("MSV"):
        return f"{MASSIVE}/{accession}", {}
    if accession.startswith("PAe"):
        return OMICSDI, {"accession": accession, "database": "peptide_atlas"}
    return (f"{PRIDE}/projects/{accession}" if source == "PRIDE" else f"{PROXI}/{accession}"), {}


def _fetch(client: httpx.Client, accession: str, source: str) -> dict | None:
    """Raw API response, cached under data/proxi (a 404 is cached as {"_status": 404}). None after repeated 429/5xx;
    that failure is cached too, so a rerun does not spend minutes retrying it. Delete those files to retry them."""
    path = CACHE / f"{accession}.json"
    if path.exists():
        raw = json.loads(path.read_text())
        return None if raw.get("_status") == "failed" else raw
    url, params = _request(accession, source)
    for attempt in range(3):
        try:
            response = client.get(url, params=params, timeout=20)
            if response.status_code in (200, 404):
                raw = response.json() if response.status_code == 200 else {"_status": 404}
                path.write_text(json.dumps(raw))
                return raw
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2 ** attempt)
    path.write_text(json.dumps({"_status": "failed"}))
    return None


def _extract(accession: str, source: str, raw: dict) -> tuple[dict, str]:
    if raw.get("_status") == 404:
        return {}, ""
    if source == "PRIDE":
        return _pride(raw)
    if accession.startswith("PAe"):
        return _omicsdi(raw)
    return _proxi(raw, "MassIVE PROXI" if accession.startswith("MSV") else "ProteomeCentral PROXI")


def _modality(meta: dict) -> str:
    ptms = [name for name, pattern in PTMS.items() if re.search(pattern, " ".join(meta.get("modifications", [])), re.I)]
    return "; ".join(["Proteomics", *meta.get("instruments", [])[:2], *meta.get("quantification", [])[:2], *ptms])


def _stored(meta: dict) -> dict:
    """Metadata with empty keys dropped; {} when nothing but the source is left."""
    meta = {k: v for k, v in meta.items() if v}
    return meta if meta.keys() - {"source"} else {}


def _write(db: sqlite3.Connection, rows: list[tuple], results: list[tuple[dict, str] | None]) -> list[str]:
    """Store metadata and fill organism and modality only where they are empty or generic. Returns accessions whose organism or modality changed."""
    meta, organism, modality = {}, [], []
    for (accession, _, old_organism, old_modality), result in zip(rows, results):
        if result is None or not (m := _stored(result[0])):
            continue
        meta[accession] = m
        if not old_organism.strip() and result[1]:
            organism.append((result[1], accession))
        if old_modality in ("Proteomics", "Unknown") and (new := _modality(m)) != old_modality:
            modality.append((new, accession))
    for attempt in range(20):
        try:
            db.executemany("UPDATE datasets SET organism = ? WHERE accession = ? AND trim(organism) = ''", organism)
            db.executemany("UPDATE datasets SET modality = ? WHERE accession = ? AND modality IN ('Proteomics', 'Unknown')", modality)
            store.put_metadata(db, meta)
            break
        except sqlite3.OperationalError:
            db.rollback()
            time.sleep(min(2 ** attempt, 30))
    else:
        raise RuntimeError("database stayed locked")
    return sorted({a for _, a in organism + modality})


def _pride_cache() -> dict[str, tuple[dict, str]]:
    return {p["accession"]: _pride(p) for f in PAGES.glob("*.json") for p in json.loads(f.read_text())}


def _report(rows: list[tuple], results: list, seconds: float) -> None:
    by = defaultdict(lambda: defaultdict(int))
    for (_, source, _, _), result in zip(rows, results):
        by[source]["n"] += 1
        by[source]["failed"] += result is None
        for k, v in (result[0] if result else {}).items():
            if k != "source":
                by[source][k] += bool(v)
    for source, counts in by.items():
        print(source, counts["n"], "failed", counts["failed"], {k: f"{100 * v // counts['n']}%" for k, v in counts.items() if k not in ("n", "failed")})
    print(f"{len(rows)} accessions in {seconds:.1f}s, {len(rows) / seconds:.1f}/s")


def enrich(sample: int | None = None) -> None:
    """Structured proteomics metadata for PRIDE, MassIVE, iProX, jPOST, PanoramaPublic and PeptideAtlas. Resumable: raw responses are cached in data/proxi.
    With `sample`, fetch that many accessions spread across sources and print field coverage without writing the database."""
    CACHE.mkdir(exist_ok=True)
    db = store.connect()
    todo = db.execute(f"SELECT accession, source, organism, modality FROM datasets WHERE source IN ({','.join('?' * len(SOURCES))}) AND accession NOT LIKE 'RPXD%' ORDER BY accession", SOURCES).fetchall()
    pride = _pride_cache()
    start, failures, changed = time.time(), 0, set()
    by = defaultdict(list)
    for row in todo:
        by[row[1]].append(row)
    random.seed(0)
    if sample:
        by = {s: random.sample(rows, sample // len(by)) for s, rows in by.items()}
    todo = [r for group in zip_longest(*by.values()) for r in group if r]

    with httpx.Client(headers={"User-Agent": "locus-enrich"}) as client, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def job(row: tuple) -> tuple[dict, str] | None:
            if row[1] == "PRIDE" and row[0] in pride:
                return pride[row[0]]
            raw = _fetch(client, row[0], row[1])
            return None if raw is None else _extract(row[0], row[1], raw)

        for i in range(0, len(todo), BATCH):
            rows = todo[i:i + BATCH]
            results = list(pool.map(job, rows))
            failures += results.count(None)
            if sample:
                _report(rows, results, time.time() - start)
                continue
            if new := _write(db, rows, results):
                changed.update(new)
                with CHANGED.open("a") as f:
                    f.write("\n".join(new) + "\n")
            print(f"{i + len(rows)}/{len(todo)} accessions, {failures} failed, {len(changed)} changed, {time.time() - start:.0f}s", flush=True)


def forget_failures() -> int:
    """Clear cached failures, for example after a network outage, so the next run asks for them again."""
    failed = [f for f in CACHE.glob("*.json") if f.stat().st_size < 40 and json.loads(f.read_text()).get("_status") == "failed"]
    for f in failed:
        f.unlink()
    return len(failed)


if __name__ == "__main__":
    if "--retry-failed" in sys.argv:
        print(f"cleared {forget_failures()} cached failures", flush=True)
    enrich(int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else None)
