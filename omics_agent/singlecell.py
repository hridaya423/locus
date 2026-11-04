"""One GEO single-cell or single-nucleus RNA-seq series, in the three tiers the Process panel shows.

Here, now: the authors' per-sample processed matrices from GEO (10x triplets, .h5 or dense tables) go through
`singlecell_analyse.py` in the omics-sc environment (scanpy QC, Leiden clusters, UMAP, Wilcoxon markers) and the raw
counts summed per cluster and sample go through `pseudobulk_deseq2.R` in the omics-rnaseq environment. On your laptop:
a kit that counts subsampled ENA reads with kb-python and then runs the same analysis script. On a cluster: an
nf-core/scrnaseq 4.0.0 kit (samplesheet, Slurm script, Nextflow config). Conventions follow process.py; the contract is
docs/data-processing-contract.md.
"""

import csv
import io
import json
import os
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import process, samples, samplesheet, store

ENV = "omics-sc"
R_ENV = "omics-rnaseq"
TIER = "here"
DATA_TYPE = "scrnaseq"
STAGES = ["plan", "fetch", "qc", "cluster", "markers", "pseudobulk", "done"]
MIN_PER_CONDITION = 2
MAX_PER_CONDITION = 4
MAX_HERE_BYTES = 400_000_000
LAPTOP_READS = 20_000_000
NFCORE = "nf-core/scrnaseq 4.0.0"
GEO_FTP = "https://ftp.ncbi.nlm.nih.gov/geo"
FILELIST_CACHE = Path.home() / ".cache" / "omics-agent" / "geo-filelist"
ANALYSE = Path(__file__).with_name("singlecell_analyse.py")
R_SCRIPT = Path(__file__).with_name("pseudobulk_deseq2.R")
NESTED = "Samples are nested in people: cells from the same donor are not independent; pseudobulk per sample avoids that, but n is the number of samples, not cells."
MITO_MAX = {"cells": 0.20, "nuclei": 0.10}
SINGLE_CELL = re.compile(r"single[ -]?cell|single[ -]?nucle|\bsnRNA|\bscRNA|\b10x\b|chromium|drop-?seq|in-?drops?|smart-?seq|cel-?seq|mars-?seq|\bsci-RNA", re.I)
NUCLEI = re.compile(r"single[ -]?nucle|\bsnRNA|\bnuclei\b|\bnucleus\b", re.I)
DETECT_FIELDS = ("sequencing type", "library strategy", "molecule", "source name", "title pattern", "library_source", "cell type", "assay")
CELLS_FIELD = re.compile(r"cells?\b", re.I)
# GENCODE genome + annotation of the same releases process.GENCODE pins for transcripts, so every tier shares one annotation.
GENOME = {
    "Homo sapiens": {"release": "human-46", "genome": "GRCh38",
                     "fasta": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/GRCh38.primary_assembly.genome.fa.gz",
                     "gtf": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/gencode.v46.primary_assembly.annotation.gtf.gz"},
    "Mus musculus": {"release": "mouse-M35", "genome": "GRCm39",
                     "fasta": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M35/GRCm39.primary_assembly.genome.fa.gz",
                     "gtf": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M35/gencode.vM35.primary_assembly.annotation.gtf.gz"},
}
TECHNOLOGY = {28: "10XV3", 26: "10XV2"}


# ---------------------------------------------------------------- detect

def _text_of(record: dict) -> str:
    fields = record.get("fields", {})
    return " ".join([record.get("title", ""), record.get("library_source", ""), *(fields.get(f, "") for f in DETECT_FIELDS)])


def detect(records: list[dict], labels: dict | None = None) -> bool:
    """True when the series is single-cell or single-nucleus RNA-seq: GEO's own fields (library source 'transcriptomic
    single cell', a 'sequencing type' or title naming single cells, nuclei, 10x, Chromium, Drop-seq) or labelled assays."""
    if any(SINGLE_CELL.search(_text_of(r)) for r in records):
        return True
    return any(SINGLE_CELL.search(a) for a in (labels or {}).get("assays", []))


def nuclei(records: list[dict]) -> bool:
    """Single-nucleus rather than single-cell, from the records' wording; sets the mitochondrial threshold."""
    return sum(bool(NUCLEI.search(_text_of(r))) for r in records) * 2 > len(records)


# ---------------------------------------------------------------- processed files

def _filelist_url(accession: str) -> str:
    return f"{GEO_FTP}/series/{accession[:-3]}nnn/{accession}/suppl/filelist.txt"


def _sample_url(gsm: str, name: str) -> str:
    return f"{GEO_FTP}/samples/{gsm[:-3]}nnn/{gsm}/suppl/{name}"


def parse_filelist(text: str) -> list[dict]:
    """The per-sample files of a GEO series filelist (columns Archive/File, Name, Time, Size, Type): every `File` row
    whose name starts with a GSM, as {gsm, name, bytes, url, kind}; kind is matrix, barcodes, features, h5, dense or other."""
    out = []
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) < 4 or row[0] != "File":
            continue
        name, size = row[1], row[3]
        gsm = re.match(r"(GSM\d+)", name)
        if not gsm:
            continue
        out.append({"gsm": gsm.group(1), "name": name, "bytes": int(size) if size.isdigit() else 0, "url": _sample_url(gsm.group(1), name), "kind": _kind(name)})
    return out


def _kind(name: str) -> str:
    low = name.lower()
    if re.search(r"\.mtx(\.gz)?$", low):
        return "matrix"
    if re.search(r"barcodes\.(tsv|txt)(\.gz)?$", low):
        return "barcodes"
    if re.search(r"(features|genes)\.(tsv|txt)(\.gz)?$", low):
        return "features"
    if re.search(r"\.(h5|hdf5)$", low):
        return "h5"
    if re.search(r"\.(csv|tsv|txt)(\.gz)?$", low) and re.search(r"count|matrix|expr|umi|dge", low):
        return "dense"
    return "other"


def processed_files(accession: str) -> list[dict]:
    """The per-sample processed files GEO holds for a series, from its suppl/filelist.txt (cached); [] when there is none."""
    path = FILELIST_CACHE / f"{accession}.txt"
    if not path.exists():
        response = httpx.get(_filelist_url(accession), timeout=60, follow_redirects=True)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text)
    return parse_filelist(path.read_text())


def matrices_of(files: list[dict]) -> dict[str, dict]:
    """One readable matrix per GSM: a complete 10x triplet first, else a .h5, else one dense table; with its total bytes."""
    by_gsm: dict[str, list[dict]] = {}
    for f in files:
        by_gsm.setdefault(f["gsm"], []).append(f)
    out = {}
    for gsm, fs in by_gsm.items():
        kinds = {f["kind"]: f for f in fs}
        if {"matrix", "barcodes", "features"} <= set(kinds):
            chosen = [kinds["matrix"], kinds["barcodes"], kinds["features"]]
            layout = "mtx"
        elif "h5" in kinds:
            chosen, layout = [kinds["h5"]], "h5"
        elif "dense" in kinds:
            chosen, layout = [kinds["dense"]], "dense"
        else:
            continue
        out[gsm] = {"layout": layout, "files": chosen, "bytes": sum(f["bytes"] for f in chosen)}
    return out


# ---------------------------------------------------------------- plan

def _gsm_number(record: dict) -> int:
    return int(re.sub(r"\D", "", record["gsm"]) or 0)


def choose(records: list[dict], labels: dict, blocker, cap: int = MAX_PER_CONDITION, floor: int = MIN_PER_CONDITION) -> dict:
    """The contrast that will run, as process.choose_contrast builds it: the most frequent control value against the
    most frequent case value of the labelled field, up to `cap` samples each in GSM order. `blocker(record)` returns the
    reason a sample cannot be used (no matrix, no reads) or "". Raises ValueError when a side has fewer than `floor`."""
    field = labels["group_field"]
    usable, skipped = [], []
    for r in sorted(records, key=_gsm_number):
        value = r["fields"].get(field, "")
        group = samples.group_of(r["fields"], labels)
        reason = (
            "not a single-cell RNA-seq sample" if not detect([r], labels)
            else blocker(r) or (f"'{field}' is '{value}', neither case nor control" if group not in ("case", "control") else "")
        )
        if reason:
            skipped.append({"gsm": r["gsm"], "title": r["title"], "reason": reason})
        else:
            usable.append({**r, "group": group, "value": value})

    levels = {}
    for group in ("control", "case"):
        values = Counter(s["value"] for s in usable if s["group"] == group)
        if not values:
            raise ValueError(f"no usable {group} sample; the labels mark {labels[group + '_values']} as {group}")
        levels[group] = values.most_common(1)[0][0]
    names = {g: samplesheet._slug(v) or g for g, v in levels.items()}
    if names["control"] == names["case"]:
        names = {"control": "control", "case": "case"}

    chosen = []
    for group in ("control", "case"):
        on_level = [s for s in usable if s["group"] == group and s["value"] == levels[group]]
        for s in usable:
            if s["group"] == group and s["value"] != levels[group]:
                skipped.append({"gsm": s["gsm"], "title": s["title"], "reason": f"'{field}' is '{s['value']}'; the contrast uses '{levels[group]}'"})
        if len(on_level) < floor:
            raise ValueError(f"only {len(on_level)} {group} sample(s) with '{field}' = '{levels[group]}'; pseudobulk DESeq2 needs at least {floor} per condition")
        for s in on_level[cap:]:
            skipped.append({"gsm": s["gsm"], "title": s["title"], "reason": f"beyond the cap of {cap} samples per condition"})
        for s in on_level[:cap]:
            chosen.append({"gsm": s["gsm"], "title": s["title"], "srx": s["srx"], "fields": s["fields"], "group": group, "value": s["value"], "condition": names[group]})
    return {"field": field, "reference": names["control"], "target": names["case"], "levels": levels, "samples": chosen, "skipped": skipped}


def _labels(accession: str, topic: str, labels_for) -> dict:
    if labels_for is None:
        from . import agent

        labels_for = agent.geo_labels
    return labels_for(topic, accession, store.summary(accession))


def here_fits(accession: str, records: list[dict], max_bytes: int = MAX_HERE_BYTES, labels: dict | None = None) -> tuple[bool, str]:
    """Whether "Here, now" can run: GEO holds a per-sample processed matrix for at least two case and two control samples
    (without labels: for at least four samples) and the files that would be downloaded stay under `max_bytes`."""
    if not detect(records, labels):
        return False, "the GEO records do not describe single-cell or single-nucleus RNA-seq"
    matrices = matrices_of(processed_files(accession))
    if labels and labels.get("group_field"):
        try:
            plan = choose(records, labels, lambda r: "" if r["gsm"] in matrices else "no processed matrix")
        except ValueError as e:
            return False, f"GEO's per-sample matrices do not cover the contrast: {e}"
        chosen = [s["gsm"] for s in plan["samples"]]
    else:
        chosen = [r["gsm"] for r in sorted(records, key=_gsm_number) if r["gsm"] in matrices][:2 * MAX_PER_CONDITION]
        if len(chosen) < 2 * MIN_PER_CONDITION:
            return False, f"GEO holds per-sample processed matrices for {len(chosen)} of {len(records)} samples; at least {2 * MIN_PER_CONDITION} are needed (2 per condition)"
    total = sum(matrices[g]["bytes"] for g in chosen)
    if total > max_bytes:
        return False, f"the {len(chosen)} matrices to download total {total / 1e6:,.0f} MB, above the {max_bytes / 1e6:,.0f} MB limit for a run here"
    return True, f"GEO holds per-sample matrices for {len(matrices)} of {len(records)} samples; {len(chosen)} would be used, {total / 1e6:,.0f} MB to download"


# ---------------------------------------------------------------- run here

def fetch(sample: dict, out: Path, log) -> list[Path]:
    """One sample's matrix files from GEO into out/<GSM>/, skipped when already there."""
    folder = out / sample["gsm"]
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in sample["files"]:
        path = folder / f["name"]
        if not path.exists():
            log(f"  {sample['gsm']}: {f['name']} ({f['bytes'] / 1e6:.1f} MB)")
            process._run(["curl", "-sSL", "--retry", "3", "-o", f"{path}.part", f["url"]], log)
            os.replace(f"{path}.part", path)
        paths.append(path)
    return paths


def _sc(threads: int, *args: str) -> list[str]:
    # The thread caps go in before the interpreter starts, so BLAS, numba and UMAP all see them.
    caps = [f"{v}={threads}" for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS", "NUMEXPR_NUM_THREADS")]
    return ["env", *caps, process.micromamba(), "run", "-n", ENV, *args]


def _r(*args: str) -> list[str]:
    return [process.micromamba(), "run", "-n", R_ENV, *args]


def run_here(accession: str, topic: str, out: Path, labels_for=None, progress=lambda stage, data: None, threads: int = 4, max_per_condition: int = MAX_PER_CONDITION) -> dict:
    """The whole "Here, now" tier for one series: plan, fetch the matrices, QC/cluster/markers in scanpy, pseudobulk
    DESeq2 per cluster, then manifest.json and result.json in `out`. Calls progress(stage, data) per stage and
    progress("log", line) per log line; the log also goes to out/process.log."""
    started = datetime.now(timezone.utc)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    log_file = open(out / "process.log", "a")

    def log(message: str) -> None:
        log_file.write(message + "\n")
        log_file.flush()
        progress("log", message)

    def stage(name: str, data: dict | None = None) -> None:
        log(f"[{name}]")
        progress(name, data or {})

    try:
        stage("plan")
        records = samples.geo_records(accession)
        if not records:
            raise LookupError(f"{accession}: no sample records in GEO")
        if not detect(records):
            raise ValueError(f"{accession}: the GEO records do not describe single-cell RNA-seq")
        labels = _labels(accession, topic, labels_for)
        matrices = matrices_of(processed_files(accession))
        p = choose(records, labels, lambda r: "" if r["gsm"] in matrices else "no per-sample processed matrix in GEO", cap=max_per_condition)
        for s in p["samples"]:
            s.update(matrices[s["gsm"]])
        is_nuclei = nuclei(records)
        mito_max = MITO_MAX["nuclei" if is_nuclei else "cells"]
        conditions = Counter(s["condition"] for s in p["samples"])
        log(f"  '{p['field']}': {p['target']} ({conditions[p['target']]}) vs {p['reference']} ({conditions[p['reference']]}); {len(p['skipped'])} samples left out; "
            f"{'nuclei' if is_nuclei else 'cells'}, mitochondrial cut-off {mito_max:.0%}")
        progress("plan", {"reference": p["reference"], "target": p["target"], "samples": p["samples"], "skipped": p["skipped"]})

        stage("fetch", {"count": len(p["samples"])})
        for i, s in enumerate(p["samples"], 1):
            fetch(s, out / "matrices", log)
            progress("fetch", {"count": len(p["samples"]), "done": i})

        with open(out / "samples.tsv", "w") as handle:
            handle.write("gsm\tcondition\tpath\n")
            for s in p["samples"]:
                handle.write(f"{s['gsm']}\t{s['condition']}\t{out / 'matrices' / s['gsm']}\n")
        stage("qc")

        def analysis_log(line: str) -> None:
            log(line)
            if "genes after QC" in line:
                stage("cluster")
            elif "Leiden clusters at" in line:
                stage("markers")

        process._run(_sc(threads, "python", str(ANALYSE), "--samples", str(out / "samples.tsv"), "--out", str(out), "--mito-max", str(mito_max), "--threads", str(threads),
                         "--unit", "nuclei" if is_nuclei else "cells", "--reference", p["reference"], "--target", p["target"]), analysis_log)
        summary = json.loads((out / "summary.json").read_text())

        stage("pseudobulk", {"clusters": len(summary["pseudobulk_clusters"])})
        process._run(_r("Rscript", str(R_SCRIPT), str(out / "pseudobulk"), p["reference"], p["target"], str(out)), log)
        de = json.loads((out / "pseudobulk_summary.json").read_text())

        finished = datetime.now(timezone.utc)
        seconds = round((finished - started).total_seconds())
        tools = {**{k: summary["versions"][k] for k in ("scanpy", "anndata", "leidenalg", "igraph", "python") if k in summary["versions"]}, **de["versions"]}
        manifest = {
            "accession": accession, "tier": TIER, "pipeline": "locus singlecell", "data_type": DATA_TYPE, "topic": topic, "tools": tools,
            "source": "authors' processed per-sample matrices from GEO; reads were not recounted",
            "files_used": [{"gsm": s["gsm"], "name": f["name"], "bytes": f["bytes"], "url": f["url"]} for s in p["samples"] for f in s["files"]],
            "qc": {**summary["thresholds"], "nuclei": is_nuclei, "leiden_flavor": "igraph, 2 iterations", "markers": "wilcoxon, one cluster against the rest",
                   "pseudobulk": "raw counts summed per cluster and sample; DESeq2 ~ condition; apeglm shrinkage when it converges"},
            "contrast": {"field": p["field"], "reference": p["reference"], "target": p["target"], "levels": p["levels"]},
            "samples": [{"gsm": s["gsm"], "title": s["title"], "condition": s["condition"], "layout": s["layout"], **_cells(summary, s["gsm"])} for s in p["samples"]],
            "skipped": p["skipped"], "started": started.isoformat(timespec="seconds"), "finished": finished.isoformat(timespec="seconds"), "seconds": seconds,
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        result = _result(accession, p, summary, de, manifest, is_nuclei, mito_max, out)
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        log(f"  {result['title']}")
        stage("done", result)
        return result
    finally:
        log_file.close()


def _cells(summary: dict, gsm: str) -> dict:
    row = next((r for r in summary["samples"] if r["sample"] == gsm), {})
    return {"cells_before": row.get("cells_before"), "cells_after": row.get("cells_after")}


def _result(accession: str, p: dict, summary: dict, de: dict, manifest: dict, is_nuclei: bool, mito_max: float, out: Path) -> dict:
    """result.json: title, plain sentences, figure captions, tables and warnings, every number from the run."""
    conditions = Counter(s["condition"] for s in p["samples"])
    n_clusters, cells_after, cells_before = summary["clusters"], summary["cells_after"], summary["cells_before"]
    sizes = summary["cluster_sizes"]
    tested = [c for c in de["clusters"] if "genes_tested" in c]
    significant = sum(c["significant"] for c in tested)
    top = max(tested, key=lambda c: c["significant"], default=None)
    kind = "nuclei" if is_nuclei else "cells"
    title = (f"{p['target']} vs {p['reference']} from '{p['field']}', {len(p['samples'])} samples, {cells_after:,} {kind} after QC, {n_clusters} clusters")
    text = [
        f"{conditions[p['target']]} {p['target']} and {conditions[p['reference']]} {p['reference']} samples from the authors' processed matrices in GEO: "
        f"{cells_before:,} {kind} before QC, {cells_after:,} after removing {kind} with fewer than {summary['thresholds']['min_genes']} genes or more than "
        f"{mito_max:.0%} mitochondrial counts (the {'single-nucleus' if is_nuclei else 'single-cell'} cut-off), and genes seen in fewer than {summary['thresholds']['min_cells']} {kind}.",
        f"{n_clusters} Leiden clusters at resolution {summary['thresholds']['resolution']}: the largest has {max(sizes.values()):,} {kind}, the smallest {min(sizes.values()):,}.",
    ]
    if tested:
        text.append(f"Pseudobulk DESeq2 ({p['target']} vs {p['reference']}) ran in {len(tested)} of {n_clusters} clusters that had at least 2 samples per condition "
                    f"with {summary['thresholds']['min_cells_per_sample_for_pseudobulk']} or more {kind}: {significant:,} gene tests at padj < 0.05 in total"
                    + (f", most in cluster {top['cluster']} ({top['significant']:,} of {top['genes_tested']:,} tested)." if top and top["significant"] else "."))
    else:
        text.append(f"No cluster had at least 2 samples per condition with {summary['thresholds']['min_cells_per_sample_for_pseudobulk']} or more {kind}, so no pseudobulk test ran.")
    dominated = summary.get("sample_dominated", {})
    if dominated:
        by_sample = Counter(dominated.values())
        text.append(f"{len(dominated)} of the {n_clusters} clusters are more than 90% one sample ({', '.join(f'{n} from {s}' for s, n in by_sample.most_common())}): "
                    f"donor or batch structure rather than shared cell types, since no integration is run here; the pseudobulk test skips them.")
    if p["skipped"]:
        reasons = Counter(re.sub(r"'.*", "", s["reason"]).strip() or s["reason"] for s in p["skipped"])
        text.append(f"{len(p['skipped'])} of {len(p['samples']) + len(p['skipped'])} samples were left out: " + "; ".join(f"{n} {r}" for r, n in reasons.most_common()) + ".")
    warnings = [NESTED, "Clusters are Leiden communities, not annotated cell types; read the marker genes before naming them.",
                "The matrices are the authors' processed output (their cell calling, reference and filtering); locus did not recount the reads."]
    if dominated:
        warnings.append(f"{len(dominated)} clusters are more than 90% one sample; no batch integration (Harmony, scVI) is run here, so cluster membership partly reflects the donor.")
    if not summary["mito_symbols_found"]:
        warnings.append("No gene names starting with MT- were found, so the mitochondrial filter removed nothing.")
    if not summary["h5ad"]["kept"]:
        warnings.append(f"The analysed .h5ad was {summary['h5ad']['bytes'] / 1e6:,.0f} MB, above the {summary['h5ad']['limit_mb']} MB kept here; the tables and figures are complete without it.")
    n_marker_genes = len({g for genes in summary["top_markers"].values() for g in genes})
    figures = [
        {"file": "umap.png", "title": "UMAP",
         "caption": f"Left: UMAP of {cells_after:,} {kind} in {n_clusters} Leiden clusters, numbered on the plot; right: the same {kind} coloured by condition "
                    f"({p['target']} orange, {p['reference']} blue)."},
        {"file": "markers_dotplot.png", "title": "Marker genes",
         "caption": f"The top 3 Wilcoxon marker genes of each of the {n_clusters} clusters ({n_marker_genes} genes): dot size is the fraction of {kind} in the cluster "
                    f"expressing the gene, colour its mean expression scaled from 0 to 1 per gene."},
    ]
    tables = [{"file": "pseudobulk_de.tsv", "title": "Pseudobulk differential expression per cluster"}, {"file": "markers.tsv", "title": "Top markers per cluster"},
              {"file": "cells_per_cluster.tsv", "title": "Cells per cluster and sample"}, {"file": "qc.tsv", "title": "QC per sample"}]
    return {
        "accession": accession, "data_type": DATA_TYPE, "tier": TIER, "title": title, "summary": text, "figures": figures, "tables": tables, "warnings": warnings,
        "contrast": {"field": p["field"], "reference": p["reference"], "target": p["target"]}, "samples": manifest["samples"], "skipped": p["skipped"],
        "cells": {"before": cells_before, "after": cells_after}, "genes": summary["genes"], "clusters": n_clusters,
        "pseudobulk": [{k: c[k] for k in ("cluster", "samples", "genes_tested", "significant", "up", "down", "shrinkage")} for c in tested],
        "files": files_of(out), "seconds": manifest["seconds"], "tools": manifest["tools"],
    }


OUTPUTS = ["result.json", "manifest.json", "qc.tsv", "cells_per_cluster.tsv", "markers.tsv", "pseudobulk_de.tsv", "pseudobulk_summary.json", "samples.tsv",
           "umap.png", "umap.pdf", "markers_dotplot.png", "markers_dotplot.pdf", "analysed.h5ad", "process.log"]


def files_of(out: Path) -> list[dict]:
    """Every output a user may download, with sizes: tables, figures, manifest, the pseudobulk count matrices and the .h5ad when kept."""
    names = [n for n in OUTPUTS if (out / n).exists()] + sorted(f"pseudobulk/{p.name}" for p in out.glob("pseudobulk/*.tsv"))
    return [{"name": n, "bytes": (out / n).stat().st_size} for n in names]


def cached(out: Path) -> dict | None:
    path = Path(out) / "result.json"
    return json.loads(path.read_text()) if path.exists() else None


# ---------------------------------------------------------------- reads (laptop and cluster kits)

def ena_runs(experiments: list[str]) -> dict[str, list[dict]]:
    """Like samplesheet.ena_runs, with read counts and FASTQ sizes: {srx: [{run, fastq, reads, bytes}]}."""
    runs: dict[str, list[dict]] = {}
    for start in range(0, len(experiments), 100):
        query = " OR ".join(f'experiment_accession="{x}"' for x in experiments[start:start + 100])
        response = samplesheet._ena_post({"result": "read_run", "query": query, "fields": "experiment_accession,fastq_ftp,read_count,fastq_bytes", "format": "tsv", "limit": 0})
        for row in csv.DictReader(io.StringIO(response.text), delimiter="\t"):
            if row["fastq_ftp"]:
                fastq = samplesheet._reads(row["fastq_ftp"].split(";"))
                sizes = [int(b) for b in row["fastq_bytes"].split(";") if b.isdigit()]
                runs.setdefault(row["experiment_accession"], []).append({"run": row["run_accession"], "fastq": fastq, "reads": int(row["read_count"] or 0),
                                                                           "bytes": sum(sizes[-len(fastq):]) if sizes else 0})
    return runs


def read_length(url: str, timeout: int = 20) -> int | None:
    """The length of the first read of a gzipped FASTQ, from its first few KB; None when that cannot be read."""
    try:
        head = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-r", "0-16383", url], capture_output=True, timeout=timeout + 5).stdout
        text = subprocess.run(["gzip", "-dc"], input=head, capture_output=True).stdout.decode(errors="replace")
        lines = text.split("\n")
        return len(lines[1].strip()) if len(lines) > 1 and lines[0].startswith("@") else None
    except (subprocess.SubprocessError, OSError):
        return None


def technology(run: dict, records_text: str = "") -> tuple[str, str]:
    """The kb-python technology string for a run and how it was decided: 10XV3 when read 1 is 28 nt, 10XV2 when 26 nt;
    a placeholder with the reason when ENA holds one file per run (the barcode read is missing) or the length is odd."""
    if len(run["fastq"]) < 2:
        return "", "ENA holds one FASTQ per run, so the barcode/UMI read is not there; recover both reads from SRA with fasterq-dump --include-technical --split-files, then set TECH"
    length = read_length(run["fastq"][0])
    if length in TECHNOLOGY:
        return TECHNOLOGY[length], f"read 1 is {length} nt"
    if re.search(r"\bv3\b|v3\.1|next gem", records_text, re.I):
        return "10XV3", "the GEO records name 10x v3 chemistry"
    if re.search(r"\bv2\b", records_text, re.I):
        return "10XV2", "the GEO records name 10x v2 chemistry"
    return "", f"read 1 is {length} nt, which is neither 28 (10x v3) nor 26 (10x v2); see `kb --list`" if length else "the first read could not be fetched to measure it"


def _reads_plan(accession: str, topic: str, labels_for, cap: int) -> dict:
    records = samples.geo_records(accession)
    if not records:
        raise LookupError(f"{accession}: no sample records in GEO")
    labels = _labels(accession, topic, labels_for)
    runs = ena_runs(sorted({r["srx"] for r in records if r["srx"]}))
    p = choose(records, labels, lambda r: "no SRA experiment in the GEO record" if not r["srx"] else "" if runs.get(r["srx"]) else f"no FASTQ in ENA for {r['srx']}", cap=cap)
    for s in p["samples"]:
        s["runs"] = runs[s["srx"]]
    organism = Counter(r["organism"] for r in records).most_common(1)[0][0]
    cells_field = next((f for f in records[0]["fields"] if CELLS_FIELD.search(f) and any(r["fields"].get(f, "").strip().isdigit() for r in records)), "")
    return {"accession": accession, "organism": organism, "records": records, "labels": labels, "nuclei": nuclei(records), "cells_field": cells_field,
            "records_text": " ".join(_text_of(r) for r in records), **p}


def _expected_cells(sample: dict, field: str) -> str:
    value = sample["fields"].get(field, "").strip() if field else ""
    return value if value.isdigit() else ""


# ---------------------------------------------------------------- laptop kit

def laptop_kit(accession: str, topic: str, labels_for=None, reads: int = LAPTOP_READS, cap: int = MAX_PER_CONDITION) -> dict[str, str]:
    """The files of the laptop kit zip: README.md, run.sh (kb ref once, then per sample the first `reads` reads of each
    FASTQ streamed from ENA into kb count, then singlecell_analyse.py and pseudobulk_deseq2.R), samples.tsv, and both scripts."""
    p = _reads_plan(accession, topic, labels_for, cap)
    genome = GENOME.get(p["organism"])
    if not genome:
        raise ValueError(f"{accession} is {p['organism']}; only {' and '.join(GENOME)} have a pinned reference")
    techs = {s["gsm"]: technology(s["runs"][0], p["records_text"]) for s in p["samples"]}
    guessed = {t for t, _ in techs.values() if t}
    tech = guessed.pop() if len(guessed) == 1 else ""
    reads_total = sum(r["reads"] for s in p["samples"] for r in s["runs"])
    bytes_total = sum(r["bytes"] for s in p["samples"] for r in s["runs"])
    req = requirements(reads_total, bytes_total, len(p["samples"]), None, reads_per_file=reads)["laptop"]
    mito = MITO_MAX["nuclei" if p["nuclei"] else "cells"]

    rows = ["gsm\tcondition\trun\tfastq_1\tfastq_2\treads\tbytes\ttechnology\ttechnology_reason"]
    for s in p["samples"]:
        for r in s["runs"]:
            rows.append("\t".join([s["gsm"], s["condition"], r["run"], r["fastq"][0], r["fastq"][1] if len(r["fastq"]) > 1 else "", str(r["reads"]), str(r["bytes"]), techs[s["gsm"]][0] or "?", techs[s["gsm"]][1]]))
    samples_tsv = "\n".join(rows) + "\n"

    sh = [
        "#!/usr/bin/env bash",
        f"# locus laptop kit for {accession}: kb-python counts from the first $READS reads of each ENA FASTQ, then the same scanpy analysis locus runs.",
        "# Environment (once):  micromamba create -n locus-sc -c conda-forge -c bioconda kb-python scanpy leidenalg python-igraph bioconductor-deseq2 bioconductor-apeglm r-jsonlite",
        "# Then:                micromamba run -n locus-sc bash run.sh",
        "set -euo pipefail",
        f"READS=${{READS:-{reads}}}          # reads kept per FASTQ; single-cell needs more than bulk, and this is still a preview",
        "THREADS=${THREADS:-4}",
        f"TECH=${{TECH:-{tech or 'FILL_IN'}}}" + (f"   # {next(iter(techs.values()))[1]}" if tech else "   # <- could not be guessed: " + "; ".join(sorted({r for _, r in techs.values()})) + ". See `kb --list`."),
        'if [ "$TECH" = FILL_IN ]; then echo "set TECH (for example 10XV3) at the top of run.sh first"; exit 1; fi',
        "",
        f"# 1. Reference: GENCODE {genome['release']} ({genome['genome']}), the same release every locus tier uses. Standard (spliced) index, about 4 GB of memory.",
        "mkdir -p ref",
        f"[ -f ref/genome.fa.gz ] || curl -sSL --retry 3 -o ref/genome.fa.gz {genome['fasta']}",
        f"[ -f ref/genes.gtf.gz ] || curl -sSL --retry 3 -o ref/genes.gtf.gz {genome['gtf']}",
        "[ -f ref/index.idx ] || kb ref -i ref/index.idx -g ref/t2g.txt -f1 ref/cdna.fa ref/genome.fa.gz ref/genes.gtf.gz",
    ]
    if p["nuclei"]:
        sh.append("# These are nuclei: an intron-inclusive index counts the pre-mRNA most nuclear reads come from (kb-python >= 0.28: kb ref --workflow nac, then kb count --workflow nac). The standard index above counts exons only.")
    sh += ["", "# 2. Reads and counts per sample (curl | head keeps the first reads of both mates in step; curl's SIGPIPE is expected)", "mkdir -p reads counts"]
    for s in p["samples"]:
        gsm = s["gsm"]
        files = []
        for r in s["runs"]:
            if len(r["fastq"]) < 2:
                sh.append(f"# {gsm} {r['run']}: ENA has one file ({r['fastq'][0].rsplit('/', 1)[-1]}); fetch both reads with: fasterq-dump --include-technical --split-files {r['run']}, then subsample and name them reads/{gsm}/{r['run']}_1.fastq.gz and _2.fastq.gz")
                files += [f"reads/{gsm}/{r['run']}_1.fastq.gz", f"reads/{gsm}/{r['run']}_2.fastq.gz"]
                continue
            for i, url in enumerate(r["fastq"], 1):
                path = f"reads/{gsm}/{r['run']}_{i}.fastq.gz"
                sh.append(f"mkdir -p reads/{gsm}; [ -f {path} ] || (curl -sL --retry 3 '{url}' | gzip -dc | head -n $((4 * READS)) | gzip -1 > {path}.part && mv {path}.part {path})")
                files.append(path)
        sh.append(f"[ -f counts/{gsm}/counts_filtered/cells_x_genes.mtx ] || kb count -i ref/index.idx -g ref/t2g.txt -x $TECH -t $THREADS --filter bustools -o counts/{gsm} {' '.join(files)}")
    sh += ["", "# 3. QC, clusters, markers and pseudobulk, as locus runs them", "printf 'gsm\\tcondition\\tpath\\n' > analysis_samples.tsv"]
    for s in p["samples"]:
        sh.append(f"printf '{s['gsm']}\\t{s['condition']}\\tcounts/{s['gsm']}/counts_filtered\\n' >> analysis_samples.tsv")
    sh += [f"python singlecell_analyse.py --samples analysis_samples.tsv --out results --mito-max {mito} --threads $THREADS --reference {p['reference']} --target {p['target']}",
           f"Rscript pseudobulk_deseq2.R results/pseudobulk {p['reference']} {p['target']} results",
           'echo "done: results/umap.png, results/markers_dotplot.png, results/markers.tsv, results/pseudobulk_de.tsv"']

    readme = [
        f"# {accession}: single-cell kit for a laptop",
        "",
        f"Written by locus from the GEO sample records and ENA run reports. Topic: {topic}.",
        f"Contrast: {p['target']} vs {p['reference']} from the field '{p['field']}' ({Counter(s['condition'] for s in p['samples'])[p['target']]} and "
        f"{Counter(s['condition'] for s in p['samples'])[p['reference']]} samples, up to {cap} per condition in GSM order). Check these labels before you run anything; a model read them from the GEO records.",
        "",
        "## What it does",
        "",
        f"1. `kb ref` builds a kallisto index from GENCODE {genome['release']} ({genome['genome']}), once.",
        f"2. For each sample, the first {reads:,} reads of each FASTQ are streamed from ENA (`curl | head`, no full download) and counted with `kb count` (`--filter bustools` keeps the cells).",
        "3. `singlecell_analyse.py` (the same script locus runs) does QC, normalisation, PCA, Leiden clusters, UMAP and Wilcoxon markers, and sums raw counts per cluster and sample.",
        "4. `pseudobulk_deseq2.R` tests each cluster with at least 2 samples per condition (DESeq2, design ~ condition).",
        "",
        "## Requirements",
        "",
        f"- Time: about {req['time']}.",
        f"- Memory: {req['memory']}.",
        f"- Disk: about {req['disk']}.",
        f"- Software: micromamba (or conda) and the one-line environment at the top of run.sh. kb-python, kallisto and bustools have conda builds for x86_64 and arm64 Linux and macOS.",
        "",
        "## Read this before trusting the result",
        "",
        f"- This is a preview: {reads:,} reads per file is a fraction of the sequencing (ENA reports {reads_total:,} reads over the {len(p['samples'])} samples), so counts per cell are shallow and small cell types may not separate. The cluster kit uses every read.",
        f"- 10x chemistry: {('`' + tech + '` (' + next(iter(techs.values()))[1] + ')') if tech else 'not guessed; set TECH in run.sh (' + '; '.join(sorted({r for _, r in techs.values()})) + ')'}.",
        *([f"- The library is single-nucleus: the standard index counts exonic reads only; kb-python >= 0.28 offers `--workflow nac` for an intron-inclusive index. The mitochondrial cut-off is {mito:.0%}."] if p["nuclei"] else [f"- The mitochondrial cut-off is {mito:.0%}."]),
        f"- {NESTED}",
        "- Clusters are Leiden communities, not cell types; read markers.tsv before naming them.",
        "",
        "## Files",
        "",
        "- `run.sh`: the whole run; `samples.tsv`: GSM, condition, run, FASTQ URLs, read counts, sizes and the guessed technology.",
        "- `singlecell_analyse.py`, `pseudobulk_deseq2.R`: the analysis, unchanged from locus.",
    ]
    if p["skipped"]:
        readme += ["", "## Left out", ""] + [f"- {s['gsm']} ({s['title']}): {s['reason']}" for s in p["skipped"]]
    return {"README.md": "\n".join(readme) + "\n", "run.sh": "\n".join(sh) + "\n", "samples.tsv": samples_tsv,
            "singlecell_analyse.py": ANALYSE.read_text(), "pseudobulk_deseq2.R": R_SCRIPT.read_text()}


# ---------------------------------------------------------------- cluster kit

def cluster_kit(accession: str, topic: str, labels_for=None, cap: int = MAX_PER_CONDITION) -> dict[str, str]:
    """The files of the cluster kit zip for nf-core/scrnaseq 4.0.0: samplesheet.csv (one row per sequencing run, full
    FASTQ URLs), run.sbatch, nextflow.config and README.md. Not run on a cluster by locus; the README says so."""
    p = _reads_plan(accession, topic, labels_for, cap)
    genome = GENOME.get(p["organism"])
    if not genome:
        raise ValueError(f"{accession} is {p['organism']}; only {' and '.join(GENOME)} have a pinned reference")
    reads_total = sum(r["reads"] for s in p["samples"] for r in s["runs"])
    bytes_total = sum(r["bytes"] for s in p["samples"] for r in s["runs"])
    req = requirements(reads_total, bytes_total, len(p["samples"]), None)["cluster"]
    hours = _cluster_hours(reads_total)
    tech, reason = technology(p["samples"][0]["runs"][0], p["records_text"]) if p["samples"] else ("", "")
    single_file = [r["run"] for s in p["samples"] for r in s["runs"] if len(r["fastq"]) < 2]

    rows = ["sample,fastq_1,fastq_2,expected_cells"]
    for s in p["samples"]:
        for r in s["runs"]:
            # One file per run is the cDNA read alone (fastq_2); the barcode read (fastq_1) stays empty until the user recovers it (README).
            mates = r["fastq"] if len(r["fastq"]) > 1 else ["", r["fastq"][0]]
            rows.append(",".join([f"{s['gsm']}_{s['condition']}", mates[0], mates[1], _expected_cells(s, p["cells_field"])]))
    samplesheet_csv = "\n".join(rows) + "\n"
    conditions_csv = "sample,condition\n" + "".join(f"{s['gsm']}_{s['condition']},{s['condition']}\n" for s in p["samples"])

    sbatch = [
        "#!/bin/bash",
        f"#SBATCH --job-name=scrnaseq-{accession}",
        "#SBATCH --cpus-per-task=4         # the Nextflow head job; each task asks Slurm for its own cores (nextflow.config)",
        "#SBATCH --mem=8G",
        f"#SBATCH --time={hours + 4:02d}:00:00     # head job: about {hours} h of STARsolo plus queue time; raise it if the queue is slow",
        "#SBATCH --output=scrnaseq-%j.log",
        "set -euo pipefail",
        "# Modules differ per site: on Iridis try `module avail nextflow apptainer`; placeholders below.",
        "module load nextflow || true",
        "module load apptainer || true",
        "export NXF_APPTAINER_CACHEDIR=${NXF_APPTAINER_CACHEDIR:-$PWD/apptainer-cache}",
        "export NXF_OPTS='-Xms1g -Xmx4g'",
        "",
        f"# GENCODE {genome['release']} ({genome['genome']}) FASTA and GTF are given explicitly rather than --genome {genome['genome']} (iGenomes), so the annotation",
        "# matches the laptop tier's kb index and locus's bulk RNA-seq tier. Protocol: " + (f"{tech} ({reason})." if tech else f"FILL IN --protocol: {reason}."),
        "nextflow run nf-core/scrnaseq -r 4.0.0 \\",
        "  -profile apptainer,slurm -c nextflow.config -resume \\",
        "  --input samplesheet.csv \\",
        f"  --protocol {tech or '10XV3'} \\" + ("" if tech else "   # <- check"),
        "  --aligner star \\",
        f"  --fasta {genome['fasta']} \\",
        f"  --gtf {genome['gtf']} \\",
        "  --outdir results",
        "",
        "# Afterwards, the same analysis locus runs, on STARsolo's filtered matrices (one folder per sample under results/star/mtx_conversions or results/star/<sample>/):",
        f"#   python singlecell_analyse.py --samples analysis_samples.tsv --out analysis --mito-max {MITO_MAX['nuclei' if p['nuclei'] else 'cells']} --reference {p['reference']} --target {p['target']}",
        f"#   Rscript pseudobulk_deseq2.R analysis/pseudobulk {p['reference']} {p['target']} analysis",
    ]

    config = "\n".join([
        f"// nf-core/scrnaseq 4.0.0 on a Slurm cluster with Apptainer, written by locus for {accession}.",
        "apptainer {",
        "    enabled    = true",
        "    autoMounts = true",
        "}",
        "profiles {",
        "    slurm {",
        "        process.executor = 'slurm'",
        "        process.queue    = 'batch'            // <- your partition (sinfo lists them)",
        "        executor.queueSize = 20",
        "        executor.submitRateLimit = '10/1min'",
        "    }",
        "}",
        "process {",
        "    // Caps on what any task may ask for; STARsolo's human index needs about 32 GB, so the memory cap must stay above that.",
        "    resourceLimits = [ cpus: 16, memory: 64.GB, time: 24.h ]",
        "    withName: 'STARSOLO|STAR_GENOMEGENERATE' {",
        "        cpus   = 16",
        "        memory = 48.GB",
        f"        time   = {max(4, hours)}.h",
        "    }",
        "}",
        "",
    ])

    readme = [
        f"# {accession}: nf-core/scrnaseq 4.0.0 kit for a Slurm cluster",
        "",
        f"Written by locus from the GEO sample records and ENA run reports. Topic: {topic}. Contrast: {p['target']} vs {p['reference']} from '{p['field']}'.",
        "**locus did not run this kit on a cluster**; the samplesheet and scripts are built from the records, and the resource numbers are estimates.",
        "",
        "## Why a cluster",
        "",
        "STARsolo's human genome index takes about 32 GB of memory, more than a laptop has; the pipeline also keeps every read, where the laptop kit keeps a preview.",
        "",
        "## Requirements (estimates)",
        "",
        f"- Reads: {reads_total:,} over {len(p['samples'])} samples ({bytes_total / 1e9:,.1f} GB of FASTQ).",
        f"- Walltime: about {req['time']} (STARsolo at roughly 100 million reads per hour on 16 cores, samples in parallel as the queue allows).",
        f"- Memory: {req['memory']}.",
        f"- Disk: about {req['disk']} (FASTQs, the index, work/ and results/).",
        "",
        "## Run",
        "",
        "1. Edit `nextflow.config`: the Slurm partition, and the resource caps if your nodes are smaller.",
        "2. Edit `run.sbatch`: the module names for Nextflow and Apptainer at your site" + ("" if tech else ", and the 10x protocol") + ".",
        "3. `sbatch run.sbatch`. Nextflow pulls the containers and the GENCODE reference on first use.",
        "",
        "## Files",
        "",
        f"- `samplesheet.csv`: {len(rows) - 1} rows, one per sequencing run (columns sample, fastq_1, fastq_2, expected_cells; runs of one sample share its name, as the pipeline expects)."
        + (f" expected_cells comes from the GEO field '{p['cells_field']}'." if p["cells_field"] else " expected_cells is empty: the records give no cell count."),
        "- `conditions.csv`: sample to condition, for the analysis after the pipeline.",
        f"- `run.sbatch`, `nextflow.config`: GENCODE {genome['release']} ({genome['genome']}) FASTA and GTF given explicitly, `--aligner star`, Apptainer.",
        "- `singlecell_analyse.py`, `pseudobulk_deseq2.R`: the analysis locus runs, for the filtered matrices the pipeline writes.",
        "",
        "## Read this before trusting the result",
        "",
        f"- Protocol: {('`' + tech + '` (' + reason + ')') if tech else 'not guessed (' + reason + '); set --protocol in run.sbatch'}.",
        f"- {NESTED}",
        "- Clusters are Leiden communities, not cell types.",
    ]
    if single_file:
        readme += ["", "## The barcode read is missing from ENA", "",
                   f"ENA holds one FASTQ per run for {len(single_file)} run(s) ({', '.join(single_file[:6])}{'...' if len(single_file) > 6 else ''}): the cDNA read only. nf-core/scrnaseq needs "
                   "both reads (fastq_1 = barcode + UMI, fastq_2 = cDNA). Recover them from SRA on the cluster first, for example "
                   "`fasterq-dump --include-technical --split-files SRRxxxx`, then put the two file paths in samplesheet.csv; the fastq_1 column is empty for those rows until you do."]
    if p["skipped"]:
        readme += ["", "## Left out", ""] + [f"- {s['gsm']} ({s['title']}): {s['reason']}" for s in p["skipped"]]
    return {"README.md": "\n".join(readme) + "\n", "samplesheet.csv": samplesheet_csv, "conditions.csv": conditions_csv, "run.sbatch": "\n".join(sbatch) + "\n",
            "nextflow.config": config, "singlecell_analyse.py": ANALYSE.read_text(), "pseudobulk_deseq2.R": R_SCRIPT.read_text()}


# ---------------------------------------------------------------- requirements

# Calibration: GSE229253 "Here, now" on pgx (ARM64, 4 threads, GPU unused) on 18 October 2026: 8 samples, 37,575 nuclei before QC, 214 MB of matrices,
# 1,151 s wall (plan 19 s, download 19 s, reading + QC 328 s, HVG/PCA/neighbours/Leiden/UMAP 693 s, markers 44 s, pseudobulk DESeq2 67 s),
# peak RSS 3.06 GB (/usr/bin/time -v over the whole run; the scanpy step is the peak). Those seconds are an upper bound: pgx was at 97% RAM
# with 12 GB in swap from other jobs, and a repeat run spent 94% of its time in kernel memory compaction (133 s user vs 1,992 s system CPU
# up to the markers step), so an idle machine with 4 GB free should finish the same data in a few minutes.
CELLS_CALIBRATED = 37_575
HERE_SECONDS_CALIBRATED = 1_151
HERE_RSS_CALIBRATED = 4.04  # the repeat run's peak (3.06 GB the first time); the higher one, so the estimate errs on the safe side


def _cluster_hours(reads_total: int) -> int:
    # STARsolo at about 100 million reads per hour on 16 cores, plus an hour for the index and the rest of the pipeline.
    return max(2, 1 + round(reads_total / 100_000_000))


def _human_time(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def requirements(reads_total: int, bytes_total: int, samples: int, cells: int | None, reads_per_file: int = LAPTOP_READS) -> dict:
    """Time, memory and disk for each tier as short strings. `reads_total` and `bytes_total` are the ENA read count and
    FASTQ bytes of the samples that would run; `cells` the cells they hold when known (GEO's cell counts, else the
    calibration default). Formulas:
      here:    time = 60 s + HERE_SECONDS_CALIBRATED * cells / CELLS_CALIBRATED (scanpy and DESeq2 scale about linearly in cells here);
               memory = 1 GB + HERE_RSS_CALIBRATED * cells / CELLS_CALIBRATED; disk = 3 x the matrices, taken as 1 KB per cell.
      laptop:  time = kb ref 30 min + per sample (download at 20 MB/s + kb count at 1 M reads per 20 s on 4 threads) + the here time;
               memory = 4 GB (kb ref/count on the standard human index) ; disk = index 4 GB + subsampled FASTQs at 50 bytes per read.
      cluster: time = _cluster_hours; memory = 48 GB per STARsolo task (the human index is about 32 GB); disk = FASTQ bytes x 3 + 40 GB.
    """
    cells = cells or CELLS_CALIBRATED * max(samples, 1) / 8
    here_seconds = 60 + HERE_SECONDS_CALIBRATED * cells / CELLS_CALIBRATED
    here_gb = 1 + HERE_RSS_CALIBRATED * cells / CELLS_CALIBRATED
    sub_reads = min(reads_total, reads_per_file * 2 * max(samples, 1))
    laptop_seconds = 30 * 60 + sub_reads * 50 / 20e6 + sub_reads / 1e6 * 20 + here_seconds
    return {
        "here": {"time": _human_time(here_seconds), "memory": f"{here_gb:.1f} GB", "disk": f"{max(0.1, 3 * cells * 1000 / 1e9):.1f} GB"},
        "laptop": {"time": _human_time(laptop_seconds), "memory": "about 4 GB (kb ref and kb count on the standard human index)", "disk": f"{4 + sub_reads * 50 / 1e9:.0f} GB"},
        "cluster": {"time": f"{_cluster_hours(reads_total)} h", "memory": "48 GB per STARsolo task (the human index alone is about 32 GB)", "disk": f"{(3 * bytes_total + 40e9) / 1e9:.0f} GB"},
    }
