"""The finished table for a dataset, fetched, never reprocessed (docs/data-processing-contract.md, "Fetch, don't reprocess").

Source today: NCBI-generated RNA-seq raw counts for GEO series (one pipeline, HISAT2 + featureCounts on GRCh38.p13 or
GRCm39), with gene symbols from NCBI Gene. Output is the contract's common shape: sample x feature counts, sample
metadata from the record, feature annotation, and a manifest naming every source URL and checksum."""

import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from . import record

DATA = Path.home() / "omics-data" / "ncbi-counts"
MAX_BYTES = 200 * 1024**2
LISTING = "https://www.ncbi.nlm.nih.gov/geo/download/?acc={}"
FILE = "https://www.ncbi.nlm.nih.gov/geo/download/?type=rnaseq_counts&acc={}&format=file&file={}"
GENE_INFO = {"Homo sapiens": "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz",
             "Mus musculus": "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Mus_musculus.gene_info.gz"}
PIPELINE = "NCBI GEO RNA-seq counts pipeline (HISAT2 alignment, featureCounts on NCBI annotation)"


@lru_cache(maxsize=256)
def available(accession: str) -> dict | None:
    """The NCBI-generated raw counts file GEO offers for a series, or None."""
    if not re.fullmatch(r"GSE\d+", accession):
        return None
    page = httpx.get(LISTING.format(accession), timeout=30, follow_redirects=True).raise_for_status().text
    if "Download data" not in page:
        raise ValueError(f"GEO did not send the download page for {accession}")
    if not (m := re.search(rf"{accession}_raw_counts_([^\"&]+?)_NCBI\.tsv\.gz", page)):
        return None
    name = m.group(0)
    return {"file": name, "build": m.group(1), "url": FILE.format(accession, name)}


def _fetch(url: str, path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                raise ValueError(f"{url} is larger than {MAX_BYTES >> 20} MB")
            body = b"".join(r.iter_bytes())
        if not body.startswith(b"\x1f\x8b"):
            raise ValueError(f"{url} did not return a gzip file")
        path.write_bytes(body)
    return path


@lru_cache(maxsize=4)
def _genes(organism: str) -> dict[str, tuple[str, str, str]]:
    """NCBI Gene ID, and Ensembl gene ID, to (symbol, description, type)."""
    path = _fetch(GENE_INFO[organism], DATA / Path(GENE_INFO[organism]).name)
    genes = {}
    with gzip.open(path, "rt") as f:
        for row in csv.reader(f, delimiter="\t"):
            if not row[0].startswith("#"):
                genes[row[1]] = (row[2], row[8], row[9])
                for ensembl in re.findall(r"Ensembl:(ENS\w+)", row[5]):
                    genes.setdefault(ensembl, (row[2], row[8], row[9]))
    return genes


SUPPLEMENTARY = DATA.parent / "geo-supplementary"
MATRIX = re.compile(r"count|expr|matrix|tpm|fpkm|rpkm|cpm|abundance", re.I)
RAW_FIRST = re.compile(r"raw[_ .-]?count|counts?\b|read[_ .-]?count", re.I)


def _authors_matrix(accession: str) -> dict | None:
    """The authors' own gene x sample table from the series' supplementary files, when its columns are the samples."""
    rec = record.record(accession)
    if not rec or not rec["samples"]:
        return None
    rows = rec["samples"]["rows"]
    by_name = {}
    for r in rows:
        for key in (r[0], r[1]):
            by_name.setdefault(re.sub(r"\W", "", key).lower(), r[0])
    organism = next((v[0] for label, v in rec["facts"] if label == "Organism"), "")
    candidates = [f for f in rec["files"] if f["group"] == "Supplementary files" and MATRIX.search(f["name"]) and re.search(r"\.(csv|tsv|txt)(\.gz)?$", f["name"])
                  and (f["bytes"] or 0) <= MAX_BYTES and not re.search(r"design|annotation|metadata|sample", f["name"], re.I)]
    for f in sorted(candidates, key=lambda f: (not RAW_FIRST.search(f["name"]), f["bytes"] or 0)):
        path = _fetch(f["url"], SUPPLEMENTARY / accession / f["name"]) if f["name"].endswith(".gz") else None
        if path is None:
            continue
        with gzip.open(path, "rt", errors="replace") as fh:
            text = fh.read()
        lines = [l for l in text.splitlines() if l and not l.startswith("#")]
        delimiter = "\t" if lines[0].count("\t") >= lines[0].count(",") else ","
        table_rows = list(csv.reader(lines, delimiter=delimiter))
        header = table_rows[0]
        mapped = {i: by_name.get(re.sub(r"\W", "", h).lower()) for i, h in enumerate(header)}
        columns = [i for i, g in mapped.items() if g]
        if len(columns) < max(4, 0.8 * len(rows)):
            continue
        body = [r for r in table_rows[1:] if len(r) == len(header)]
        if not body:
            continue
        try:
            matrix = np.array([[float(r[i] or "nan") for i in columns] for r in body])
        except ValueError:
            continue
        ids = [r[0] for r in body]
        genes = _genes(organism) if organism in GENE_INFO else {}
        integer = bool(np.all(np.nan_to_num(matrix) == np.round(np.nan_to_num(matrix))))
        kind = "raw counts" if integer and np.nanmin(matrix) >= 0 else "log scale" if np.nanmin(matrix) < 0 or np.nanmax(matrix) < 30 else "normalised, linear"
        return {
            "accession": accession, "samples": [mapped[i] for i in columns], "gene_ids": ids, "matrix": np.nan_to_num(matrix), "kind": kind,
            "symbols": [genes.get(g.split(".")[0], (g,))[0] for g in ids], "genes": genes, "organism": organism or "not stated",
            "source": {"url": f["url"], "file": f["name"], "build": "as the authors processed it", "pipeline": f"the authors' supplementary file ({kind})",
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size, "genes_url": GENE_INFO.get(organism, "")},
        }
    return None


@lru_cache(maxsize=8)
def counts(accession: str) -> dict | None:
    """A genes x samples matrix with gene symbols and where it came from: NCBI's raw counts, else the authors' own table."""
    if not (found := available(accession)):
        return _authors_matrix(accession)
    path = _fetch(found["url"], DATA / found["file"])
    with gzip.open(path, "rt") as f:
        header = f.readline().rstrip("\n").split("\t")[1:]
        ids, rows = [], []
        for line in f:
            gene, _, rest = line.rstrip("\n").partition("\t")
            ids.append(gene)
            rows.append(np.array(rest.split("\t"), dtype=np.int64))
    organism = "Mus musculus" if "GRCm" in found["build"] else "Homo sapiens"
    genes = _genes(organism)
    return {
        "accession": accession, "samples": header, "gene_ids": ids, "matrix": np.vstack(rows), "kind": "raw counts",
        "symbols": [genes.get(g, (g,))[0] for g in ids], "genes": genes, "organism": organism,
        "source": {"url": found["url"], "file": found["file"], "build": found["build"], "pipeline": PIPELINE,
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
                   "genes_url": GENE_INFO[organism]},
    }


def summary(accession: str) -> dict:
    """What table locus can hand over for a dataset, without the matrix itself."""
    try:
        data = counts(accession)
    except (httpx.HTTPError, ValueError) as error:
        return {"accession": accession, "available": False, "reason": str(error)}
    if not data:
        return {"accession": accession, "available": False, "reason": "neither NCBI nor the authors' supplementary files give a gene by sample table"}
    m = data["matrix"]
    return {"accession": accession, "available": True, "genes": int(m.shape[0]), "samples": len(data["samples"]), "kind": data["kind"],
            "reads": int(m.sum()) if data["kind"] == "raw counts" else None, "source": data["source"], "organism": data["organism"]}


def bundle(accession: str) -> bytes:
    """counts.tsv (genes x samples), samples.tsv (record characteristics), features.tsv, manifest.json and README.txt in a zip."""
    data = counts(accession)
    rec = record.record(accession)
    table = rec["samples"] or {"columns": ["Accession"], "rows": [[s] for s in data["samples"]]}
    by_gsm = {r[0]: r for r in table["rows"]}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        lines = ["gene_id\tsymbol\t" + "\t".join(data["samples"])]
        lines += [f"{g}\t{s}\t" + "\t".join(f"{v:g}" for v in row) for g, s, row in zip(data["gene_ids"], data["symbols"], data["matrix"].tolist())]
        z.writestr("counts.tsv", "\n".join(lines) + "\n")
        sample_lines = ["\t".join(c.replace("\t", " ") for c in table["columns"])]
        sample_lines += ["\t".join(v.replace("\t", " ") for v in by_gsm.get(s, [s] + [""] * (len(table["columns"]) - 1))) for s in data["samples"]]
        z.writestr("samples.tsv", "\n".join(sample_lines) + "\n")
        feature_lines = ["gene_id\tsymbol\tdescription\ttype"] + [f"{g}\t" + "\t".join(data["genes"].get(g, (g, "", ""))) for g in data["gene_ids"]]
        z.writestr("features.tsv", "\n".join(feature_lines) + "\n")
        z.writestr("manifest.json", json.dumps({"accession": accession, "retrieved": date.today().isoformat(), "tier": "fetched, not reprocessed",
                                                "counts": data["source"], "samples_from": rec["url"], "organism": data["organism"]}, indent=1))
        z.writestr("README.txt", f"""{accession}: {data['kind']} from {data['source']['pipeline']}, genome {data['source']['build']}.
counts.tsv  {len(data['gene_ids'])} genes x {len(data['samples'])} samples (columns are GEO sample accessions)
samples.tsv one row per sample, the characteristics from the GEO record
features.tsv NCBI Gene symbol, description and type per gene_id

Python: import pandas as pd; counts = pd.read_csv("counts.tsv", sep="\\t", index_col=0).drop(columns="symbol"); samples = pd.read_csv("samples.tsv", sep="\\t", index_col=0)
R:      counts <- read.delim("counts.tsv", row.names = 1)[, -1]; samples <- read.delim("samples.tsv", row.names = 1)
""")
    return out.getvalue()


if __name__ == "__main__":
    s = summary("GSE124685")
    assert s["available"] and s["samples"] == 84 and s["genes"] > 30000, s
    data = counts("GSE124685")
    assert "SPP1" in data["symbols"] and data["samples"][0] == "GSM3541118"
    assert not summary("GSE36892")["available"]
    authors = summary("GSE213001")
    assert authors["available"] and authors["kind"] == "raw counts" and authors["samples"] == 139 and "authors" in authors["source"]["pipeline"], authors
    assert not summary("GSE134692")["available"]
    names = zipfile.ZipFile(io.BytesIO(bundle("GSE124685"))).namelist()
    assert names == ["counts.tsv", "samples.tsv", "features.tsv", "manifest.json", "README.txt"], names
    print("table self-check passed", s["genes"], "genes", s["samples"], "samples")
