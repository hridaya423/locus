"""One GEO bulk RNA-seq series, from subsampled ENA reads to DESeq2 results and plots, on a laptop budget.

Stages: plan (sample records, labels and ENA runs become one two-level contrast), reference (GENCODE transcripts and a
salmon index, cached under ~/omics-ref), fetch (the first N reads of each FASTQ, streamed from ENA), quantify (salmon),
count (tximport gene counts, `counts.tsv` and one `<sample>.count` per sample) and test (DESeq2 with apeglm shrinkage,
PCA, volcano and MA plots). `manifest.json` records every tool version, the reference release, the read cap and the
samples that were left out. The HPC-tier equivalent is nf-core/rnaseq; see docs/data-processing-contract.md.
"""

import csv
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import explain, samples, samplesheet, store

ENV = "omics-rnaseq"
TIER = "laptop"
READS = 2_000_000
THREADS = 8
MIN_PER_CONDITION = 2
MAX_PER_CONDITION = 4
DOWNLOADS = 4
RNASEQ = {"rnaseq", "mrnaseq", "totalrnaseq", "bulkrnaseq", "polyarnaseq"}
GENCODE = {
    "Homo sapiens": ("human-46", "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/gencode.v46.transcripts.fa.gz"),
    "Mus musculus": ("mouse-M35", "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M35/gencode.vM35.transcripts.fa.gz"),
}
STAGES = ["plan", "reference", "fetch", "quantify", "count", "test", "explain", "done"]
R_SCRIPT = Path(__file__).with_name("deseq2.R")
SMALL_FILES = ["counts.tsv", "deseq2_results.tsv", "normalized_counts.tsv", "top_genes.tsv", "pca.json", "volcano.json", "ma.json",
               "pca.png", "volcano.png", "ma.png", "deseq2_summary.json", "manifest.json", "result.json", "samples.tsv", "explanation.md"]


def ref_dir() -> Path:
    return Path(os.environ.get("OMICS_REF_DIR") or Path.home() / "omics-ref")


def out_dir(accession: str) -> Path:
    return Path(os.environ.get("OMICS_PROCESS_DIR") or "data/process") / accession


def micromamba() -> str:
    """The micromamba binary: $MICROMAMBA, then PATH, then ~/bin."""
    return os.environ.get("MICROMAMBA") or shutil.which("micromamba") or str(Path.home() / "bin" / "micromamba")


def _tool(*args: str) -> list[str]:
    return [micromamba(), "run", "-n", ENV, *args]


def _run(cmd: list[str], log, cwd: Path | None = None, shell: bool = False) -> None:
    """Run a tool, echoing its output to the log, and fail with the last lines if it fails."""
    proc = subprocess.Popen(cmd, cwd=cwd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    tail: list[str] = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.strip():
            log(f"    {line[:300]}")
            tail = (tail + [line])[-10:]
    if proc.wait() != 0:
        raise RuntimeError(f"{cmd[0] if not shell else 'pipeline'} failed ({proc.returncode}): " + " | ".join(tail[-3:]))


# ---------------------------------------------------------------- plan

def _assay(fields: dict[str, str], labels: dict) -> str:
    if labels.get("assay_field"):
        return next((a["assay"] for a in labels.get("assay_values", []) if fields.get(labels["assay_field"], "") in a["values"]), "")
    return labels["assays"][0] if len(labels.get("assays", [])) == 1 else fields.get("library strategy", "")


def _is_rnaseq(fields: dict[str, str], labels: dict) -> bool:
    """Bulk RNA-seq by the GEO library strategy when the record has one (array samples have none), else by the labels."""
    if "library strategy" in fields:
        return samplesheet._norm(fields["library strategy"]) == "rnaseq"
    return samplesheet._norm(_assay(fields, labels)) in RNASEQ


def choose_contrast(records: list[dict], labels: dict, runs: dict[str, list[dict]], cap: int = MAX_PER_CONDITION, floor: int = MIN_PER_CONDITION) -> dict:
    """One two-level contrast from the labelled group field: the most frequent control value against the most frequent
    case value, up to `cap` RNA-seq samples each in GSM order, one sequencing run per sample. Samples of any other value,
    other assays, or without FASTQs are listed under `skipped` with the reason. Raises ValueError when a side has fewer
    than `floor` samples, because DESeq2 cannot estimate dispersion from one replicate."""
    field = labels["group_field"]
    usable, skipped = [], []
    for r in sorted(records, key=lambda r: int(re.sub(r"\D", "", r["gsm"]) or 0)):
        value = r["fields"].get(field, "")
        group = samples.group_of(r["fields"], labels)
        reason = (
            f"assay '{r['fields'].get('library strategy') or _assay(r['fields'], labels) or 'unknown'}' is not bulk RNA-seq" if not _is_rnaseq(r["fields"], labels)
            else "no SRA experiment in the GEO record" if not r["srx"]
            else f"no FASTQ in ENA for {r['srx']}" if not runs.get(r["srx"])
            else f"'{field}' is '{value}', neither case nor control" if group not in ("case", "control")
            else ""
        )
        if reason:
            skipped.append({"gsm": r["gsm"], "title": r["title"], "reason": reason})
        else:
            usable.append({**r, "group": group, "value": value})

    levels = {}
    for group in ("control", "case"):
        values = Counter(s["value"] for s in usable if s["group"] == group)
        if not values:
            raise ValueError(f"no {group} RNA-seq sample with FASTQs; the labels mark {labels[group + '_values']} as {group}")
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
            raise ValueError(f"only {len(on_level)} {group} sample(s) with '{field}' = '{levels[group]}'; DESeq2 needs at least {floor} per condition")
        for s in on_level[cap:]:
            skipped.append({"gsm": s["gsm"], "title": s["title"], "reason": f"beyond the cap of {cap} samples per condition"})
        for s in on_level[:cap]:
            run = runs[s["srx"]][0]
            chosen.append({"gsm": s["gsm"], "title": s["title"], "srx": s["srx"], "run": run["run"], "fastq": run["fastq"],
                           "group": group, "value": s["value"], "condition": names[group]})
    return {"field": field, "reference": names["control"], "target": names["case"], "levels": levels, "samples": chosen, "skipped": skipped}


def plan(accession: str, topic: str, labels_for) -> dict:
    """Records, labels and ENA runs for one series, reduced to the contrast that will run."""
    records = samples.geo_records(accession)
    if not records:
        raise LookupError(f"{accession}: no sample records in GEO")
    organisms = Counter(r["organism"] for r in records)
    organism = organisms.most_common(1)[0][0]
    if organism not in GENCODE:
        raise ValueError(f"{accession} is {organism}; only {' and '.join(GENCODE)} have a pinned reference")
    labels = labels_for(topic, accession, store.summary(accession))
    runs = samplesheet.ena_runs(sorted({r["srx"] for r in records if r["srx"]}))
    contrast = choose_contrast(records, labels, runs)
    return {"accession": accession, "organism": organism, "topic": topic, "labels": labels, **contrast}


# ---------------------------------------------------------------- reference

def reference(organism: str, threads: int, log) -> dict:
    """GENCODE transcripts, a salmon index and tx2gene.tsv for the organism, built once under the reference directory.
    tx2gene comes from the GENCODE FASTA headers (transcript|gene|...|gene name|...), so no GTF download is needed."""
    tag, url = GENCODE[organism]
    base = ref_dir() / "gencode" / tag
    base.mkdir(parents=True, exist_ok=True)
    fasta, index, tx2gene = base / "transcripts.fa.gz", base / "salmon-index", base / "tx2gene.tsv"
    if not fasta.exists():
        log(f"  downloading {url}")
        _run(["curl", "-sSL", "--retry", "3", "-o", f"{fasta}.part", url], log)
        os.replace(f"{fasta}.part", fasta)
    if not tx2gene.exists():
        write_tx2gene(fasta, tx2gene)
    if not (index / "info.json").exists():
        log(f"  building the salmon index in {index} (once per reference; takes a while)")
        building = base / "salmon-index.building"
        shutil.rmtree(building, ignore_errors=True)
        _run(_tool("salmon", "index", "-t", str(fasta), "-i", str(building), "-k", "31", "-p", str(threads), "--gencode"), log)
        os.replace(building, index)
    return {"release": tag, "url": url, "fasta": str(fasta), "index": str(index), "tx2gene": str(tx2gene)}


def write_tx2gene(fasta: Path, path: Path) -> int:
    """transcript_id, gene_id and gene_name for every transcript in a GENCODE FASTA; returns the count."""
    import gzip

    n = 0
    with gzip.open(fasta, "rt") as reads, open(f"{path}.part", "w") as out:
        out.write("transcript_id\tgene_id\tgene_name\n")
        for line in reads:
            if line.startswith(">"):
                parts = line[1:].strip().split("|")
                out.write(f"{parts[0]}\t{parts[1]}\t{parts[5] if len(parts) > 5 else ''}\n")
                n += 1
    os.replace(f"{path}.part", path)
    return n


# ---------------------------------------------------------------- fetch

def fetch(sample: dict, reads: int, out: Path, log) -> list[Path]:
    """The first `reads` reads of each FASTQ of one run, streamed from ENA and recompressed. Mates stay in sync because
    ENA lists them in the same order. Skipped when the files already exist."""
    paths = []
    for i, url in enumerate(sample["fastq"], 1):
        path = out / f"{sample['gsm']}_{i}.fastq.gz"
        if path.exists():
            paths.append(path)
            continue
        log(f"  {sample['gsm']}: first {reads:,} reads of {url.rsplit('/', 1)[-1]}")
        # curl gets SIGPIPE when head closes the pipe, which is expected; gzip's exit status is the pipeline's.
        _run(f"curl -sL --retry 3 {url!r} | gzip -dc | head -n {4 * reads} | gzip -1 > {str(path) + '.part'!r}", log, shell=True)
        os.replace(f"{path}.part", path)
        paths.append(path)
    return paths


# ---------------------------------------------------------------- quantify

def quantify(sample: dict, fastqs: list[Path], index: str, threads: int, out: Path, log) -> dict:
    """salmon quant for one sample; returns the read and mapping numbers from its meta_info.json."""
    quant = out / sample["gsm"]
    if not (quant / "quant.sf").exists():
        reads = ["-1", str(fastqs[0]), "-2", str(fastqs[1])] if len(fastqs) == 2 else ["-r", str(fastqs[0])]
        _run(_tool("salmon", "quant", "-i", index, "-l", "A", *reads, "-p", str(threads), "-o", str(quant)), log)
    meta = json.loads((quant / "aux_info" / "meta_info.json").read_text())
    return {"quant": str(quant), "reads": meta.get("num_processed"), "mapped": meta.get("num_mapped"), "mapping_rate": meta.get("percent_mapped"),
            "library_type": meta.get("library_types", [""])[0]}


# ---------------------------------------------------------------- count

def write_count_files(counts_tsv: Path, out: Path) -> list[Path]:
    """One HTSeq-style `<sample>.count` file per column of counts.tsv: gene_id<TAB>integer count, genes in file order."""
    with open(counts_tsv, newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    header, body = rows[0], rows[1:]
    paths = []
    for column, sample in enumerate(header[1:], 1):
        path = out / f"{sample}.count"
        with open(path, "w") as handle:
            for row in body:
                handle.write(f"{row[0]}\t{int(round(float(row[column])))}\n")
        paths.append(path)
    return paths


def top_genes(results_tsv: Path, n: int = 20) -> list[dict]:
    """The `n` genes with the smallest adjusted p-value, as the results panel and the evidence folder show them."""
    with open(results_tsv, newline="") as handle:
        rows = [r for r in csv.DictReader(handle, delimiter="\t") if r["padj"] not in ("NA", "")]
    rows.sort(key=lambda r: (float(r["padj"]), float(r["pvalue"])))
    return [{"gene_id": r["gene_id"], "gene_name": r["gene_name"], "base_mean": round(float(r["baseMean"]), 1),
             "log2fc": round(float(r["log2FoldChange"]), 3), "padj": float(f"{float(r['padj']):.3g}")} for r in rows[:n]]


# ---------------------------------------------------------------- run

def run(accession: str, topic: str = "", reads: int = READS, threads: int = THREADS, labels_for=None, ask=None, progress=lambda stage, data: None) -> dict:
    """The whole pipeline for one series. `labels_for(topic, accession, summary)` supplies the case/control labels and
    `ask(prompt, schema)` the model's explanation (agent.geo_labels and agent._ask in the app). Calls `progress(stage,
    data)` at each stage and returns the result summary, which is also written to result.json next to the outputs."""
    from . import agent

    labels_for = labels_for or agent.geo_labels
    ask = ask or (lambda prompt, schema: agent._ask(prompt, schema, effort="low", max_tokens=1500))
    started = datetime.now(timezone.utc)
    out = out_dir(accession)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "process.log"
    log_file = open(log_path, "a")

    def log(message: str) -> None:
        log_file.write(message + "\n")
        log_file.flush()
        progress("log", message)

    def stage(name: str, data: dict | None = None) -> None:
        log(f"[{name}]")
        progress(name, data or {})

    try:
        stage("plan")
        p = plan(accession, topic or store.summary(accession).split(". ")[0] or accession, labels_for)
        conditions = Counter(s["condition"] for s in p["samples"])
        log(f"  {p['organism']}; '{p['field']}': {p['target']} ({conditions[p['target']]}) vs {p['reference']} ({conditions[p['reference']]}); {len(p['skipped'])} samples left out")
        progress("plan", {"organism": p["organism"], "reference": p["reference"], "target": p["target"], "samples": p["samples"], "skipped": p["skipped"]})

        stage("reference")
        ref = reference(p["organism"], threads, log)

        stage("fetch", {"count": len(p["samples"])})
        raw = out / "reads"
        raw.mkdir(exist_ok=True)
        with ThreadPoolExecutor(DOWNLOADS) as pool:
            fastqs = list(pool.map(lambda s: fetch(s, reads, raw, log), p["samples"]))

        stage("quantify", {"count": len(p["samples"])})
        quants = out / "salmon"
        quants.mkdir(exist_ok=True)
        for i, (s, files) in enumerate(zip(p["samples"], fastqs), 1):
            log(f"  {s['gsm']} ({i}/{len(p['samples'])})")
            s.update(quantify(s, files, ref["index"], threads, quants, log))
            progress("quantify", {"count": len(p["samples"]), "done": i})

        stage("count")
        with open(out / "samples.tsv", "w") as handle:
            handle.write("sample\tcondition\tquant\n")
            for s in p["samples"]:
                handle.write(f"{s['gsm']}\t{s['condition']}\t{s['quant']}\n")
        _run(_tool("Rscript", str(R_SCRIPT), str(out / "samples.tsv"), ref["tx2gene"], str(out), p["reference"], p["target"]), log)
        counts = write_count_files(out / "counts.tsv", out)
        log(f"  {len(counts)} .count files")

        stage("test")
        summary = json.loads((out / "deseq2_summary.json").read_text())
        top = top_genes(out / "deseq2_results.tsv")
        with open(out / "top_genes.tsv", "w") as handle:
            handle.write("gene_id\tgene_name\tbase_mean\tlog2fc\tpadj\n")
            for g in top:
                handle.write("\t".join(str(g[k]) for k in ("gene_id", "gene_name", "base_mean", "log2fc", "padj")) + "\n")

        finished = datetime.now(timezone.utc)
        manifest = {
            "accession": accession, "tier": TIER, "pipeline": "locus process", "organism": p["organism"], "topic": p["topic"],
            "tools": {"salmon": _version(["salmon", "--version"]), **summary["versions"]},
            "reference": {"source": "GENCODE", "release": ref["release"], "url": ref["url"], "index": "salmon k=31, transcriptome only, no decoys"},
            "reads_per_fastq": reads, "subsampled": True, "contrast": {"field": p["field"], "reference": p["reference"], "target": p["target"], "levels": p["levels"]},
            "samples": [{k: s[k] for k in ("gsm", "title", "srx", "run", "fastq", "condition", "reads", "mapped", "mapping_rate", "library_type")} for s in p["samples"]],
            "skipped": p["skipped"], "started": started.isoformat(timespec="seconds"), "finished": finished.isoformat(timespec="seconds"),
            "seconds": round((finished - started).total_seconds()),
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        result = {
            "accession": accession, "organism": p["organism"], "contrast": manifest["contrast"], "samples": manifest["samples"], "skipped": p["skipped"],
            "genes": summary["genes"], "genes_tested": summary["genes_with_padj"], "significant": summary["significant"], "up": summary["up"], "down": summary["down"],
            "pca": summary["pca"], "top_genes": top, "files": files_of(out), "seconds": manifest["seconds"], "reads_per_fastq": reads,
            "reference": manifest["reference"], "tools": manifest["tools"],
        }
        stage("explain")
        series = samples.geo_series(accession)
        result.update(explain.explain(result, series["title"], " ".join(filter(None, (series["summary"], series["design"]))), ask))
        log(f"  {result['note']}")
        if result.get("rejected"):
            log(f"  rejected paragraph: {result['rejected']}")
        (out / "explanation.md").write_text(f"# {accession}: {series['title']}\n\n{result['explanation'] or '(no explanation)'}\n\n*{result['note']}*\n")
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        stage("done", result)
        return result
    finally:
        log_file.close()


def _version(cmd: list[str]) -> str:
    text = subprocess.run(_tool(*cmd), capture_output=True, text=True).stdout
    return text.strip().split()[-1] if text.strip() else "unknown"


def files_of(out: Path) -> list[dict]:
    """The downloadable outputs with sizes: the small tables, plots and manifest, plus every .count file."""
    names = [n for n in SMALL_FILES if (out / n).exists()] + sorted(p.name for p in out.glob("*.count"))
    return [{"name": n, "bytes": (out / n).stat().st_size} for n in names]


def cached(accession: str) -> dict | None:
    """The result of an earlier complete run, if its result.json is still there."""
    path = out_dir(accession) / "result.json"
    return json.loads(path.read_text()) if path.exists() else None


def summary_lines(result: dict) -> list[str]:
    """What the CLI prints when a run finishes."""
    c = result["contrast"]
    lines = [
        f"{result['accession']} ({result['organism']}): {c['target']} vs {c['reference']} from '{c['field']}', {len(result['samples'])} samples, "
        f"{result['reads_per_fastq']:,} reads per FASTQ, {result['seconds']} s",
        f"genes: {result['genes']} counted, {result['genes_tested']} tested, {result['significant']} with padj < 0.05 ({result['up']} up, {result['down']} down)",
        "PCA means: " + "; ".join(f"{k} PC1 {v['PC1']} PC2 {v['PC2']}" for k, v in result["pca"]["means"].items()) + f"  (variance {result['pca']['variance'][0]}% / {result['pca']['variance'][1]}%)",
        "top genes: " + ", ".join(f"{g['gene_name'] or g['gene_id']} ({g['log2fc']:+.2f})" for g in result["top_genes"][:10]),
        *(["explanation (written by the model from the numbers above, every number checked): " + result["explanation"]] if result.get("explanation") else [f"no explanation: {result.get('note', '')}"]),
        "files:",
        *(f"  {f['bytes']:>12,}  {f['name']}" for f in result["files"]),
    ]
    if result["skipped"]:
        lines += ["left out:", *(f"  {s['gsm']}: {s['reason']}" for s in result["skipped"])]
    return lines


if __name__ == "__main__":
    import sys
    import tempfile

    # A two-condition study with one odd value, one array sample and one sample without reads.
    def record(gsm, treatment, strategy="RNA-Seq", srx=True):
        return {"gsm": gsm, "title": f"cells {treatment} {gsm}", "organism": "Homo sapiens", "srx": f"SRX{gsm[3:]}" if srx else "",
                "fields": {"treatment": treatment, "library strategy": strategy}}

    records = [record("GSM1", "vehicle"), record("GSM2", "vehicle"), record("GSM3", "vehicle"), record("GSM4", "drug"), record("GSM5", "drug"),
               record("GSM6", "drug", srx=False), record("GSM7", "other drug"), record("GSM8", "vehicle", strategy="OTHER")]
    labels = {"group_field": "treatment", "case_values": ["drug", "other drug"], "control_values": ["vehicle"], "assays": ["RNA-seq"]}
    runs = {r["srx"]: [{"run": "SRR" + r["gsm"][3:], "fastq": [f"https://x/{r['gsm']}_1.fastq.gz", f"https://x/{r['gsm']}_2.fastq.gz"]}] for r in records if r["srx"]}
    contrast = choose_contrast(records, labels, runs)
    assert (contrast["reference"], contrast["target"]) == ("vehicle", "drug")
    assert [s["gsm"] for s in contrast["samples"]] == ["GSM1", "GSM2", "GSM3", "GSM4", "GSM5"]
    assert {s["gsm"]: s["reason"] for s in contrast["skipped"]} == {
        "GSM6": "no SRA experiment in the GEO record", "GSM7": "'treatment' is 'other drug'; the contrast uses 'drug'", "GSM8": "assay 'OTHER' is not bulk RNA-seq"}

    with tempfile.TemporaryDirectory() as tmp:
        counts = Path(tmp) / "counts.tsv"
        counts.write_text("gene_id\tGSM1\tGSM2\nENSG1\t10\t0\nENSG2\t3\t7\n")
        paths = write_count_files(counts, Path(tmp))
        assert [p.name for p in paths] == ["GSM1.count", "GSM2.count"] and paths[1].read_text() == "ENSG1\t0\nENSG2\t7\n"
    print("ok")
    sys.exit(0)
