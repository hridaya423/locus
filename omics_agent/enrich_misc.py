import ast
import gzip
import json
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import store

CACHE = store.DB.parent / "enrich_misc"
CHANGED = store.DB.parent / "enriched_misc.txt"
GENERIC = {"Metabolomics", "Genomics", "Transcriptomics", "Proteomics", "Multiomics", "Microarray", "Other", "Unknown"}
NA = {"", "not applicable", "not available", "na", "n/a", "none", "-"}
TECH = {"Liquid Chromatography MS": "LC-MS", "Gas Chromatography MS": "GC-MS", "Nuclear Magnetic Resonance (NMR)": "NMR",
        "Capillary Electrophoresis MS": "CE-MS", "Direct Infusion MS": "DI-MS", "Flow Infusion MS": "FI-MS"}
ATLAS_MODALITY = {"proteomics": "Proteomics", "rnaseq": "Transcriptomics", "microarray": "Transcriptomics"}
URL = {
    "MetaboLights": "https://www.ebi.ac.uk/metabolights/ws/studies/public/study/{}",
    "NODE": "https://www.omicsdi.org/ws/dataset/node/{}",
    "LINCS": "https://lincsportal.ccs.miami.edu/dcic/api/fetchdata?searchTerm=datasetid:{}&limit=1",
    "EVA": "https://www.ebi.ac.uk/eva/webservices/rest/v1/studies/{}/summary",
    "ExpressionAtlas": "https://www.ebi.ac.uk/gxa/json/experiments/{}",
}
WORKERS = {"MetaboLights": 8, "NODE": 8, "LINCS": 4, "EVA": 6, "ExpressionAtlas": 4}


def _uniq(values) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip().lower() not in NA))


def _table(table: dict, header: str) -> list[int]:
    return [f["index"] for f in table["fields"].values() if f["header"].lower() == header]


def _metabolights(d: dict) -> tuple[str, dict]:
    d = d["content"]
    t = d["sampleTable"]
    taxon = (_table(t, "organism") or [None])[0]
    # Sample rows also describe blanks and QC material; only rows whose organism is an NCBITaxon term are samples of a species.
    rows = [r for r in t["data"] if taxon is not None and r[taxon + 1].upper() == "NCBITAXON"]
    column = lambda h: _uniq(r[i] for i in _table(t, h) for r in rows)
    assays = [(a, a["assayTable"]) for a in d["assays"] if a["assayTable"]]
    return "; ".join(column("organism")), {
        "tissues": column("organism part"),
        "cell_types": column("cell type"),
        "diseases": column("disease"),
        "instruments": _uniq(r[i] for _, at in assays for h in {f["header"] for f in at["fields"].values() if f["header"].lower().endswith("instrument")}
                             if not h.lower().startswith(("chromatography", "autosampler")) for i in _table(at, h.lower()) for r in at["data"]),
        "technologies": _uniq(TECH.get(h, h) for a, _ in assays for h in [a["platform"].split(" - ")[0]]),
        "experiment_types": _uniq(a["measurement"] for a, _ in assays),
        "keywords": _uniq(x["description"].split(":", 1)[-1] for x in d["descriptors"]),
        "sample_count": len(t["data"]) or None,
    }


def _node(d: dict) -> tuple[str, dict]:
    a = {k: [v for v in vs if v] for k, vs in d["additional"].items()}
    taxonomy = a.get("taxonomy", [""])[0]
    try:
        organism = "; ".join(ast.literal_eval(taxonomy)) if taxonomy else ""
    except (ValueError, SyntaxError):
        organism = taxonomy
    count = a.get("sample_count", [""])[0]
    return organism, {
        "experiment_types": _uniq(a.get("technology_type", [])),
        "instruments": _uniq(a.get("experiment_platform", [])),
        "sample_count": int(count) if count.isdigit() else None,
    }


def _lincs(d: dict) -> tuple[str, dict]:
    if not d["results"]["documents"]:
        return "", {}
    d = d["results"]["documents"][0]
    return "", {
        "cell_types": _uniq(d.get("cellline", [])),
        "technologies": _uniq([d.get("technologies", ""), d.get("physicaldetection", "")]),
        "experiment_types": _uniq(d.get("assayname", [])),
        "keywords": _uniq(d.get("biologicalprocess", [])),
    }


def _eva(d: dict) -> tuple[str, dict]:
    s = (d["response"][0].get("result") or [{}])[0]
    return s.get("speciesScientificName") or "", {
        "experiment_types": _uniq([s.get("experimentType", "")]),
        "instruments": _uniq([s.get("platform", "")]),
        "sample_count": s.get("numSamples") or None,
    }


def _atlas(d: dict) -> tuple[str, dict]:
    kind = d["experiment"]["type"]
    groups = [g["assayGroupSummary"] for g in d["columnHeaders"] if "assayGroupSummary" in g]
    prop = lambda *names: _uniq(v for g in groups for p in g["properties"] if p["propertyName"] in names for v in p["testValue"].split(","))
    # Differential experiments list contrasts rather than assay groups, so only baseline replicates add up to samples.
    return d["experiment"].get("species") or "", {
        "tissues": prop("organism part"),
        "cell_types": prop("cell type", "cell line"),
        "diseases": prop("disease"),
        "experiment_types": [kind.replace("_", " ")],
        "sample_count": sum(g["replicates"] for g in groups) if kind.endswith("baseline") and groups else None,
    }


PARSE = {"MetaboLights": _metabolights, "NODE": _node, "LINCS": _lincs, "EVA": _eva, "ExpressionAtlas": _atlas}


def _fetch(client: httpx.Client, source: str, accession: str) -> dict | None:
    """Raw response for one dataset, cached gzipped under data/enrich_misc. Unavailable datasets (401/403/404) are cached as {}; None after repeated 429/5xx."""
    path = CACHE / f"{accession}.json.gz"
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    for attempt in range(6):
        try:
            response = client.get(URL[source].format(accession), timeout=60)
            if response.status_code in (200, 401, 403, 404):
                raw = json.loads(response.content.decode("utf-8", "replace")) if response.status_code == 200 else {}
                path.write_bytes(gzip.compress(json.dumps(raw).encode()))
                return raw
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2 ** attempt)
    return None


def _modality(source: str, current: str, raw: dict, meta: dict) -> str:
    """Replace a bare generic modality with 'Generic; technology; instrument'."""
    base = [m for m in current.split("; ") if m != "Unknown"]
    if source == "ExpressionAtlas":
        base = [ATLAS_MODALITY.get(raw["experiment"]["type"].split("_")[0], m) for m in base]
    detail = (meta.get("technologies") or meta.get("experiment_types", []))[:2] + meta.get("instruments", [])[:1]
    return "; ".join(dict.fromkeys(base + detail))


def _write(db: sqlite3.Connection, found: list[tuple[str, str, dict, dict]]) -> list[str]:
    """Store metadata and fill organism, samples and generic modality in one transaction, retrying while another process holds the write lock. Returns accessions whose organism or modality changed."""
    for attempt in range(20):
        changed = []
        try:
            store.put_metadata(db, {a: m for a, _, _, m in found if m})
            for accession, organism, modality, meta in found:
                moved = db.execute("UPDATE datasets SET organism=? WHERE accession=? AND organism='' AND ?!=''", (organism, accession, organism)).rowcount
                if modality:
                    moved += db.execute("UPDATE datasets SET modality=? WHERE accession=? AND modality!=?", (modality, accession, modality)).rowcount
                if meta.get("sample_count"):
                    db.execute("UPDATE datasets SET samples=? WHERE accession=? AND samples IS NULL", (meta["sample_count"], accession))
                if moved:
                    changed.append(accession)
            db.commit()
            return changed
        except sqlite3.OperationalError:
            db.rollback()
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError("database stayed locked")


def enrich(dry: int = 0) -> None:
    """Structured metadata for MetaboLights, NODE, LINCS, EVA and ExpressionAtlas from their own APIs (NODE has none; OmicsDI's
    record stands in). Resumable: raw responses are cached in data/enrich_misc. With dry=N, N accessions are sampled across sources and nothing is written."""
    db = store.connect()
    CACHE.mkdir(exist_ok=True)
    total = 0
    for source in URL:
        rows = db.execute("SELECT accession, modality FROM datasets WHERE source=? ORDER BY " + ("random() LIMIT ?" if dry else "accession"),
                          (source, dry // len(URL)) if dry else (source,)).fetchall()
        started, found, failed, missing, coverage = time.time(), [], Counter(), 0, Counter()
        with httpx.Client(verify=source != "LINCS", headers={"Accept": "application/json"}, follow_redirects=True) as client, ThreadPoolExecutor(WORKERS[source]) as pool:
            for (accession, current), raw in zip(rows, pool.map(lambda r: _fetch(client, source, r[0]), rows)):
                if raw is None:
                    failed["fetch"] += 1
                    continue
                if not raw:
                    missing += 1
                    continue
                try:
                    organism, meta = PARSE[source](raw)
                except (KeyError, IndexError, TypeError) as e:
                    failed[f"{accession}: parse {e!r}"] += 1
                    continue
                meta = {k: v for k, v in meta.items() if v}
                if meta:
                    meta["source"] = [{"NODE": "OmicsDI"}.get(source, source)]
                modality = _modality(source, current, raw, meta) if set(current.split("; ")) <= GENERIC else ""
                coverage.update(["organism"] * bool(organism) + [k for k in meta if k != "source"] + ["modality"] * (modality not in ("", current)))
                found.append((accession, organism, modality, meta))
        if dry:
            print(f"{source}: {len(rows)} sampled, {len(found)} parsed, {missing} unavailable, {len(failed)} failed in {time.time() - started:.0f}s ({len(rows) / (time.time() - started):.1f}/s)\n  {dict(coverage)}", flush=True)
        else:
            changed = [a for i in range(0, len(found), 500) for a in _write(db, found[i:i + 500])]
            with CHANGED.open("a") as f:
                f.writelines(f"{a}\n" for a in changed)
            total += len(changed)
            print(f"{source}: {len(rows)} listed, {len(found)} parsed, {missing} unavailable, {sum(failed.values())} failed, {len(changed)} changed in {time.time() - started:.0f}s\n  {dict(coverage)}", flush=True)
        for reason in list(failed)[:3]:
            print(f"  {reason}", flush=True)
    print(f"done: {total} accessions changed organism or modality", flush=True)


if __name__ == "__main__":
    enrich(int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--dry" else 0)
