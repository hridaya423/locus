"""Where one dataset's processing can run: three rows for every data type, with what each costs for this dataset.

Rows: "here" (small analyses of files that are already processed: the authors' tables, or a run computed earlier; instant
and safe on the public server), "laptop" (a kit a 16 GB laptop runs; on a machine that runs locus live, the laptop is this
machine) and "cluster" (a Slurm / nf-core kit, with the reason a laptop cannot do it). A row that cannot work for this
dataset is shown with its reason, never hidden. Requirements are estimated from ENA's read counts and file sizes and
calibrated against measured runs; the constants below say which.
"""

import csv
import io
import math
import re
import time
from collections import Counter

from . import assay, process, samples, samplesheet, store

ROWS = ("here", "laptop", "cluster")
ROW_LABELS = {"here": "Here, now", "laptop": "On your laptop", "cluster": "On a cluster"}
DATA_TYPES = {"bulk_rnaseq": "Bulk RNA-seq", "scrnaseq": "Single-cell RNA-seq", "riboseq": "Ribo-seq"}
SINGLE_CELL = re.compile(r"single[- ]?(?:cell|nucle(?:us|i))|\bsc\s*RNA|\bsn\s*RNA|10x|chromium|drop-?seq|smart-?seq|cel-?seq|inDrops?|seq-?well", re.I)

# Bulk RNA-seq, laptop tier (2,000,000 reads per FASTQ, salmon on 8 threads), measured on this ARM machine:
# GSE273888 6 samples 172 s, GSE344137 6 samples 291 s, GSE295999 8 samples 519 s; so about 55 s per sample plus the
# reference, which took 7 min and 3.3 GB the first time for human.
LAPTOP_SECONDS_PER_SAMPLE = 55
LAPTOP_REFERENCE_SECONDS = 420
LAPTOP_MEMORY_GB = 4
LAPTOP_REFERENCE_GB = 1.5
LAPTOP_DISK_PER_SAMPLE_GB = 0.3
# Bulk RNA-seq, cluster tier (nf-core/rnaseq, STAR + salmon): a human STAR index needs about 32 GB of memory, which is
# why a 16 GB laptop cannot run it. STAR aligns on the order of 150 million reads an hour on 12 cores; nf-core runs
# samples as separate jobs, so the walltime is set by the largest sample, with a margin.
STAR_MEMORY_GB = 32
STAR_READS_PER_HOUR = 150e6
CLUSTER_DISK_FACTOR = 3


_STATS: dict[tuple, tuple[float, dict]] = {}
STATS_TTL = 3600


def ena_stats(experiments: list[str]) -> dict[str, dict]:
    """Per SRA experiment: its runs with FASTQ URLs, read counts, bytes and layout, from one ENA query per 100.
    Remembered for an hour, because the panel, the run and the kit all ask for the same series."""
    key = tuple(experiments)
    if key in _STATS and time.monotonic() - _STATS[key][0] < STATS_TTL:
        return _STATS[key][1]
    out = _ena_stats(experiments)
    _STATS[key] = (time.monotonic(), out)
    return out


def _ena_stats(experiments: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for start in range(0, len(experiments), 100):
        query = " OR ".join(f'experiment_accession="{x}"' for x in experiments[start:start + 100])
        response = samplesheet._ena_post({"result": "read_run", "query": query, "format": "tsv", "limit": 0,
                                          "fields": "experiment_accession,run_accession,read_count,base_count,fastq_bytes,library_layout,fastq_ftp"})
        for row in csv.DictReader(io.StringIO(response.text), delimiter="\t"):
            if not row["fastq_ftp"]:
                continue
            reads = int(row["read_count"]) if row["read_count"].isdigit() else 0
            bases = int(row["base_count"]) if row["base_count"].isdigit() else 0
            nbytes = sum(int(b) for b in row["fastq_bytes"].split(";") if b.isdigit())
            entry = out.setdefault(row["experiment_accession"], {"runs": [], "reads": 0, "bytes": 0, "layout": row["library_layout"], "read_length": 0})
            entry["runs"].append({"run": row["run_accession"], "fastq": samplesheet._reads(row["fastq_ftp"].split(";")), "reads": reads, "bytes": nbytes})
            entry["reads"] += reads
            entry["bytes"] += nbytes
            if reads and bases:
                entry["read_length"] = round(bases / reads / (2 if row["library_layout"] == "PAIRED" else 1))
    return out


def runs_of(stats: dict[str, dict]) -> dict[str, list[dict]]:
    """The shape samplesheet.ena_runs returns, from ena_stats, so the same contrast code runs on both."""
    return {srx: [{"run": r["run"], "fastq": r["fastq"]} for r in s["runs"]] for srx, s in stats.items()}


# ---------------------------------------------------------------- data type

def _footprint(record: dict) -> bool:
    word = assay._library_word(record["title"])
    return bool(word) and word[0] in (assay.RIBO, assay.TIS)


def data_type(records: list[dict], labels: dict | None = None) -> str | None:
    """Which of tonight's data types a GEO series is: Ribo-seq when any library is a footprint library, single-cell when
    the records say so, bulk RNA-seq when the library strategy is RNA-Seq; otherwise None."""
    try:
        from . import riboseq
        if riboseq.detect(records, labels):
            return "riboseq"
    except ImportError:
        if any(_footprint(r) for r in records):
            return "riboseq"
    try:
        from . import singlecell
        if singlecell.detect(records, labels):
            return "scrnaseq"
    except ImportError:
        if any(SINGLE_CELL.search(" ".join([r["title"], *r["fields"].values()])) for r in records):
            return "scrnaseq"
    if any(samplesheet._norm(r["fields"].get("library strategy", "")) == "rnaseq" for r in records):
        return "bulk_rnaseq"
    assays = {samplesheet._norm(a) for a in (labels or {}).get("assays", [])}
    return "bulk_rnaseq" if assays & process.RNASEQ else None


# ---------------------------------------------------------------- requirements

def _hours(seconds: float) -> str:
    if seconds < 90:
        return f"about {round(seconds)} s"
    if seconds < 5400:
        return f"about {max(2, round(seconds / 60))} min"
    return f"about {max(2, round(seconds / 3600))} h"


def _gb(value: float) -> str:
    return f"about {round(value)} GB" if value >= 10 or value == round(value) else f"about {value:.1f} GB"


def bulk_requirements(chosen: list[dict], stats: dict[str, dict]) -> dict[str, dict[str, str]]:
    """Time, memory and disk for the three rows, for the samples the run would use."""
    n = len(chosen)
    reads = [stats.get(s["srx"], {}).get("reads", 0) for s in chosen]
    nbytes = sum(stats.get(s["srx"], {}).get("bytes", 0) for s in chosen)
    biggest = max(reads, default=0)
    laptop_seconds = LAPTOP_SECONDS_PER_SAMPLE * n
    cluster_hours = min(48, math.ceil(1 + 2 * (0.5 + biggest / STAR_READS_PER_HOUR)))
    return {
        "here": {"time": "instant", "memory": "none", "disk": "none"},
        "laptop": {"time": f"{_hours(laptop_seconds)} for {n} samples, plus {_hours(LAPTOP_REFERENCE_SECONDS)} once for the reference",
                   "memory": _gb(LAPTOP_MEMORY_GB), "disk": _gb(LAPTOP_REFERENCE_GB + LAPTOP_DISK_PER_SAMPLE_GB * n)},
        "cluster": {"time": f"walltime {cluster_hours} h ({n} samples as parallel jobs; the largest has {biggest / 1e6:,.0f} M reads)",
                    "memory": f"{STAR_MEMORY_GB} GB per alignment job", "disk": _gb(max(1, CLUSTER_DISK_FACTOR * nbytes / 1e9))},
    }


# ---------------------------------------------------------------- rows

def _row(row: str, available: bool, reason: str = "", **extra) -> dict:
    return {"id": row, "label": ROW_LABELS[row], "available": available, "reason": reason, **extra}


def options(accession: str, topic: str, live: bool, labels_for=None) -> dict:
    """The three rows for one GEO series: which apply, what each costs here, and why one does not."""
    from . import agent

    labels_for = labels_for or agent.geo_labels
    records = samples.geo_records(accession)
    if not records:
        raise LookupError(f"{accession}: no sample records in GEO")
    series_summary = store.summary(accession)
    topic = topic or series_summary.split(". ")[0] or accession
    labels = labels_for(topic, accession, series_summary)
    kind = data_type(records, labels)
    organism = Counter(r["organism"] for r in records).most_common(1)[0][0]
    out = {"accession": accession, "topic": topic, "data_type": kind, "data_type_label": DATA_TYPES.get(kind or "", ""), "organism": organism,
           "samples": len(records), "live": live, "rows": []}
    if kind is None:
        out["reason"] = ("locus processes bulk RNA-seq, single-cell RNA-seq and Ribo-seq from GEO; this series' records show "
                         f"'{records[0]['fields'].get('library strategy') or 'no library strategy'}'")
        return out
    if organism not in process.GENCODE:
        out["reason"] = f"{accession} is {organism}; only {' and '.join(process.GENCODE)} have a pinned reference"
        return out
    stats = ena_stats(sorted({r["srx"] for r in records if r["srx"]}))
    builder = {"bulk_rnaseq": _bulk_rows, "scrnaseq": _singlecell_rows, "riboseq": _riboseq_rows}[kind]
    out["rows"] = builder(accession, topic, records, labels, stats, live)
    return out


def _bulk_rows(accession: str, topic: str, records: list[dict], labels: dict, stats: dict, live: bool) -> list[dict]:
    from . import table

    try:
        contrast = process.choose_contrast(records, labels, runs_of(stats))
        chosen, blocked = contrast["samples"], ""
    except ValueError as error:
        chosen, blocked = [], str(error)
    need = bulk_requirements(chosen, stats)
    what = {"here": "The authors' processed table, as the First look on the dataset page", "laptop": "Subsampled reads → salmon → counts → DESeq2, five figures",
            "cluster": "nf-core/rnaseq (STAR + salmon) on the full reads, as a Slurm kit"}
    rows = []
    cached = process.cached(accession)
    authors = table.summary(accession)
    if cached:
        rows.append(_row("here", True, what="A run computed earlier on this dataset, with its figures", action="cached", requirements=need["here"]))
    elif authors.get("available"):
        rows.append(_row("here", True, what=what["here"], action="link", href=f"/d/{accession}", requirements=need["here"],
                         detail=f"{authors['genes']:,} genes × {authors['samples']} samples, {authors['kind']}, from {authors['source']}"))
    else:
        rows.append(_row("here", False, authors.get("reason", "no processed table"), what=what["here"], requirements=need["here"]))
    command = f"uv run omics process {accession} --topic {_quote(topic)}"
    if blocked:
        rows.append(_row("laptop", False, blocked, what=what["laptop"], requirements=need["laptop"]))
        rows.append(_row("cluster", False, blocked, what=what["cluster"], requirements=need["cluster"]))
        return rows
    contrast_text = f"{contrast['target']} vs {contrast['reference']} from '{contrast['field']}', {len(chosen)} samples"
    rows.append(_row("laptop", True, what=what["laptop"], action="run" if live else "command", command=command, kit=f"laptop", requirements=need["laptop"],
                     detail=contrast_text + (" (this machine runs it)" if live else "")))
    rows.append(_row("cluster", True, what=what["cluster"], action="kit", kit="cluster", requirements=need["cluster"],
                     detail=contrast_text, why_not_laptop=f"a human STAR index needs about {STAR_MEMORY_GB} GB of memory"))
    return rows


def _chosen_by_group(records: list[dict], labels: dict, keep, cap: int = process.MAX_PER_CONDITION) -> list[dict]:
    """Up to `cap` case and control samples that `keep` accepts, in GSM order, for requirement estimates."""
    chosen = []
    for group in ("control", "case"):
        on_side = [r for r in records if keep(r) and samples.group_of(r["fields"], labels) == group]
        chosen += sorted(on_side, key=lambda r: int(re.sub(r"\D", "", r["gsm"]) or 0))[:cap]
    return chosen


def _singlecell_rows(accession: str, topic: str, records: list[dict], labels: dict, stats: dict, live: bool) -> list[dict]:
    try:
        from . import singlecell
    except ImportError:
        return [_row(r, False, "single-cell processing is not built yet") for r in ROWS]
    chosen = _chosen_by_group(records, labels, lambda r: bool(r["srx"]))
    reads = sum(stats.get(r["srx"], {}).get("reads", 0) for r in chosen)
    nbytes = sum(stats.get(r["srx"], {}).get("bytes", 0) for r in chosen)
    cells = sum(int(c) for r in chosen if (c := re.sub(r"\D", "", r["fields"].get("# _of_cells", r["fields"].get("number of cells", "")))))
    need = singlecell.requirements(reads, nbytes, len(chosen), cells or None)
    ok, reason = singlecell.here_fits(accession, records, labels=labels)
    what = {"here": "QC, clustering, UMAP, marker genes and pseudobulk differential expression from the authors' matrices",
            "laptop": "kb-python counts from subsampled reads, then the same scanpy analysis", "cluster": "nf-core/scrnaseq (STARsolo) on the full reads, as a Slurm kit"}
    rows = [_row("here", ok, "" if ok else reason, what=what["here"], action="run", requirements=need["here"], detail=reason if ok else "")]
    enough = len([r for r in chosen if samples.group_of(r["fields"], labels) == "case"]) >= 2 and len([r for r in chosen if samples.group_of(r["fields"], labels) == "control"]) >= 2
    blocked = "" if enough else f"fewer than 2 case or 2 control samples with reads in ENA under '{labels.get('group_field')}'"
    rows.append(_row("laptop", enough, blocked, what=what["laptop"], action="kit", kit="laptop", requirements=need["laptop"], detail=f"{len(chosen)} samples"))
    rows.append(_row("cluster", enough, blocked, what=what["cluster"], action="kit", kit="cluster", requirements=need["cluster"], detail=f"{len(chosen)} samples",
                     why_not_laptop=f"a human STARsolo index needs about {STAR_MEMORY_GB} GB of memory"))
    return rows


def _riboseq_rows(accession: str, topic: str, records: list[dict], labels: dict, stats: dict, live: bool) -> list[dict]:
    try:
        from . import riboseq
    except ImportError:
        return [_row(r, False, "Ribo-seq processing is not built yet") for r in ROWS]
    chosen = _chosen_by_group(records, labels, lambda r: bool(r["srx"]))
    reads = sum(stats.get(r["srx"], {}).get("reads", 0) for r in chosen)
    nbytes = sum(stats.get(r["srx"], {}).get("bytes", 0) for r in chosen)
    need = riboseq.requirements(reads, nbytes, len(chosen))
    ok, reason = riboseq.here_fits(accession, records, labels)
    footprints = sum(1 for r in records if _footprint(r))
    what = {"here": "ΔTE from the authors' CDS counts: DESeq2 with an interaction term, classes and a Δ RNA vs Δ Ribo scatter",
            "laptop": "Subsampled reads → rRNA removal → transcriptome alignment → P-sites, metagene, footprint lengths, CDS counts → ΔTE",
            "cluster": "nf-core/riboseq on the full reads, as a Slurm kit"}
    rows = [_row("here", ok, "" if ok else reason, what=what["here"], action="run", requirements=need["here"], detail=reason if ok else "")]
    enough = footprints >= 4
    blocked = "" if enough else f"only {footprints} footprint libraries"
    rows.append(_row("laptop", enough, blocked, what=what["laptop"], action="run" if live else "command", requirements=need["laptop"],
                     command=f"uv run omics process {accession} --topic {_quote(topic)} --tier riboseq-laptop", detail=f"{len(chosen)} libraries" + (" (this machine runs it)" if live else ""),
                     fidelity="a lower-fidelity approximation of the cluster pipeline: transcriptome alignment, subsampled reads"))
    rows.append(_row("cluster", enough, blocked, what=what["cluster"], action="kit", kit="cluster", requirements=need["cluster"], detail=f"{len(chosen)} libraries",
                     why_not_laptop=f"STAR against the human genome needs about {STAR_MEMORY_GB} GB of memory"))
    return rows


def _quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"
