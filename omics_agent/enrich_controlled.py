import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from dotenv import load_dotenv

from . import store
from .sources import EUTILS, ncbi_get

EGA = "https://metadata.ega-archive.org"
OMICSDI = "https://www.omicsdi.org/ws/dataset"
GAP = "https://www.ncbi.nlm.nih.gov/gap/sstr/api/v1/study"
CACHE = store.DB.parent / "enrich_controlled"
CHANGED = store.DB.parent / "enriched_controlled.txt"
GENERIC = ("Genomics", "Genomic", "Unknown", "")
TAXA = {"9606": "Homo sapiens"}
BATCH = 500
WORKERS = 8


def _json(client: httpx.Client, url: str) -> dict | list | None:
    """JSON body, or None for a 404. Backs off on 429/5xx and network errors; raises when they persist."""
    for attempt in range(6):
        try:
            response = client.get(url, timeout=60)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                return None
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(url)


def _ncbi(url: str, params: dict, tries: int = 4) -> dict | None:
    for attempt in range(tries):
        try:
            return ncbi_get(url, params).json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(url)


def _taxonomy(client: httpx.Client, key: str, accession: str) -> list[str]:
    record = _json(client, f"{OMICSDI}/{key}/{accession}") or {}
    return (record.get("cross_references") or {}).get("TAXONOMY", [])


def _studies(accessions: list[str]) -> dict[str, dict]:
    """dbGaP study accession -> its esummary `d_study_results`, for up to ~100 studies per call."""
    term = " OR ".join(f"{a}[Study Accession]" for a in accessions)
    ids = _ncbi(f"{EUTILS}/esearch.fcgi", {"db": "gap", "term": f"({term}) AND study[Object Type]", "retmax": 1000, "retmode": "json"})["esearchresult"]["idlist"]
    if not ids:
        return {}
    result = _ncbi(f"{EUTILS}/esummary.fcgi", {"db": "gap", "id": ",".join(ids), "retmode": "json"})["result"]
    return {result[u]["d_study_results"]["d_study_id"].split(".")[0]: result[u]["d_study_results"] for u in result["uids"]}


def _done(accession: str) -> bool:
    """Cached, except dbGaP studies whose sstr summary failed or timed out: those are retried."""
    path = CACHE / f"{accession}.json"
    return path.exists() and not (accession.startswith("phs") and json.loads(path.read_text())["sstr"] is None)


def _fetch(client: httpx.Client, accession: str, url: str, studies: dict[str, dict]) -> None:
    """Cache every raw response needed for one accession. Failures stay uncached and are retried on the next run."""
    path = CACHE / f"{accession}.json"
    key = url.split("/")[-2]
    try:
        if accession.startswith("phs"):
            base = accession.split(".")[0]
            try:
                sstr = _ncbi(f"{GAP}/{base}/summary", {}, tries=2)
            except RuntimeError:
                sstr = None  # large studies time out (502) on every attempt; they keep their esummary fields but no sample count
            raw = {"gap": studies.get(base), "sstr": sstr}
        elif accession.startswith("EGAD"):
            raw = {"ega": _json(client, f"{EGA}/datasets/{accession}")}
        else:
            raw = {"ega": _json(client, f"{EGA}/studies/{accession}"), "datasets": _json(client, f"{EGA}/studies/{accession}/datasets")}
        raw["taxonomy"] = _taxonomy(client, key, accession)
    except RuntimeError as e:
        print(f"skipped {accession}: {e}", flush=True)
        return
    path.write_text(json.dumps(raw))


def _date(raw: str | None) -> str | None:
    return raw.strip()[:10] if raw and re.match(r"\s*\d{4}-\d{2}-\d{2}", raw) else None


def _uniq(values) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def _parse(raw: dict) -> dict:
    """Metadata plus the dataset columns this source states; keys it does not state are left out."""
    out = {"organism": next((TAXA[t] for t in raw["taxonomy"] if t in TAXA), "")}
    if gap := raw.get("gap"):
        names = [d["d_disease_name"] for d in sorted(gap["d_study_disease_list"], key=lambda d: d["d_disease_importance"] != "primary")]
        meta = {
            "instruments": _uniq(p["d_genotype_platform"] if p["d_genotype_platform"].startswith(p["d_genotype_vendor"]) else f"{p['d_genotype_vendor']} {p['d_genotype_platform']}" for p in gap["d_study_genotype_platform_list"] if "Version" not in p["d_genotype_platform"]),
            "experiment_types": _uniq(m["d_molecular_data_type_name"] for m in gap["d_study_molecular_data_type_list"]),
            "diseases": _uniq(names),
            "keywords": _uniq([gap["d_study_design"]]),
        }
        out["published"] = _date(gap["d_study_release_date"])
        out["source"] = ["NCBI dbGaP"]
        if sstr := raw.get("sstr"):
            if count := sum(c.get("sample_count") or 0 for c in sstr["study"].get("consent_groups", [])):
                out["samples"] = meta["sample_count"] = count
            out["source"].append("dbGaP SSTR")
    elif ega := raw.get("ega"):
        datasets = raw.get("datasets") or [ega]
        study_type = ega.get("study_type")
        meta = {
            "instruments": _uniq(t for d in datasets for t in d.get("technologies") or []),
            "experiment_types": _uniq([t for d in datasets for t in d.get("dataset_types") or []] or ([study_type] if study_type not in (None, "Other", "Not Specified") else [])),
        }
        out["published"] = _date(ega.get("released_date"))
        out["source"] = ["EGA metadata API"]
        if ega.get("num_samples") is not None:
            out["samples"] = meta["sample_count"] = ega["num_samples"]
    else:
        return out
    out["meta"] = {k: v for k, v in meta.items() if v} | {"source": out["source"] + (["OmicsDI"] if raw["taxonomy"] else [])}
    return out


def _modality(current: str, parsed: dict) -> str:
    meta = parsed.get("meta", {})
    parts = [", ".join(meta.get("experiment_types", [])[:3]), ", ".join([i for i in meta.get("instruments", []) if len(i) <= 40][:3])]
    return "; ".join([current, *filter(None, parts)]) if current in GENERIC else current


def _write(db: sqlite3.Connection, metadata: dict, rows: list[tuple]) -> None:
    for attempt in range(8):
        try:
            store.put_metadata(db, metadata)
            db.executemany(
                f"UPDATE datasets SET organism = CASE WHEN organism = '' THEN ? ELSE organism END, samples = COALESCE(samples, ?),"
                f" published = COALESCE(NULLIF(published, ''), ?), modality = CASE WHEN modality IN {GENERIC} THEN ? ELSE modality END WHERE accession = ?", rows)
            db.commit()
            return
        except sqlite3.OperationalError:
            db.rollback()
            time.sleep(2 ** attempt)
    raise RuntimeError("database stayed locked")


def enrich_controlled(dry: int = 0) -> int:
    """Metadata for EGA and dbGaP records from their own public APIs, plus organism from OmicsDI. Resumable: raw responses are cached in data/enrich_controlled/."""
    db = store.connect()
    CACHE.mkdir(exist_ok=True)
    rows = {r[0]: r[1:] for r in db.execute("SELECT accession, url, organism, modality, samples, published FROM datasets WHERE source IN ('EGA', 'dbGaP') ORDER BY accession")}
    accessions = list(rows)
    if dry:
        groups = [[a for a in accessions if a.startswith(p)] for p in ("EGAD", "EGAS", "phs")]
        accessions = [a for g in groups for a in g[:: max(1, len(g) // (dry // 3))][: dry // 3]]
    changed = set(CHANGED.read_text().split()) if CHANGED.exists() else set()
    print(f"{len(accessions)} accessions ({sum(map(_done, accessions))} cached)", flush=True)
    started, fetched, stats = time.time(), 0, {}

    with httpx.Client(limits=httpx.Limits(max_connections=WORKERS)) as client, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i in range(0, len(accessions), BATCH):
            chunk = accessions[i:i + BATCH]
            todo = [a for a in chunk if not _done(a)]
            phs = [a for a in todo if a.startswith("phs")]
            studies = {}
            for j in range(0, len(phs), 100):
                studies |= _studies([a.split(".")[0] for a in phs[j:j + 100]])
            list(pool.map(lambda a: _fetch(client, a, rows[a][0], studies), todo))
            fetched += len(todo)

            metadata, updates = {}, []
            for a in chunk:
                if not (CACHE / f"{a}.json").exists():
                    continue
                parsed = _parse(json.loads((CACHE / f"{a}.json").read_text()))
                _, organism, modality, samples, published = rows[a]
                new_modality = _modality(modality, parsed)
                kind = "phs" if a.startswith("phs") else a[:4]
                s = stats.setdefault(kind, {"n": 0})
                s["n"] += 1
                for field, ok in (("organism", parsed["organism"]), ("modality", new_modality != modality), ("samples", "samples" in parsed), ("published", parsed.get("published")),
                                  *((k, parsed.get("meta", {}).get(k)) for k in ("instruments", "experiment_types", "diseases", "keywords", "sample_count"))):
                    s[field] = s.get(field, 0) + bool(ok)
                if "meta" in parsed:
                    metadata[a] = parsed["meta"]
                if (not organism and parsed["organism"]) or new_modality != modality:
                    changed.add(a)
                updates.append((parsed["organism"], parsed.get("samples"), parsed.get("published"), new_modality, a))
                if dry and (len(updates) % 15 == 1):
                    print(a, json.dumps(parsed)[:400], new_modality, flush=True)
            if not dry:
                _write(db, metadata, updates)
                CHANGED.write_text("\n".join(sorted(changed)) + "\n")
            print(f"{min(i + BATCH, len(accessions))}/{len(accessions)}: {fetched} fetched, {len(changed)} changed, {time.time() - started:.0f}s", flush=True)
    print(json.dumps(stats, indent=1))
    if dry:
        print(f"throughput: {fetched / (time.time() - started):.1f} accessions/s")
    return len(changed)


if __name__ == "__main__":
    load_dotenv()
    enrich_controlled(int(sys.argv[2]) if sys.argv[1:2] == ["--dry"] else 0)
