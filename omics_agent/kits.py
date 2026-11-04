"""Kits: the files a user takes away to run a dataset's processing elsewhere, as one zip per row.

Bulk RNA-seq, cluster row: an nf-core/rnaseq samplesheet built from the same GEO records and ENA runs as the laptop
path, a Slurm submission script with stated memory and walltime, a minimal Nextflow config with an Apptainer profile, and
a README naming the GENCODE release so results match the laptop tier's annotation. Bulk RNA-seq, laptop row: the one
command, the samples it will use and a README. Single-cell and Ribo-seq kits come from their own modules.
"""

import io
import zipfile
from collections import Counter

from . import options, process, samples, store

RNASEQ_PIPELINE = "nf-core/rnaseq"
RNASEQ_VERSION = "3.27.0"
GENCODE_GENOME = {
    "Homo sapiens": ("https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/GRCh38.primary_assembly.genome.fa.gz",
                     "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/gencode.v46.primary_assembly.annotation.gtf.gz"),
    "Mus musculus": ("https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M35/GRCm39.primary_assembly.genome.fa.gz",
                     "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M35/gencode.vM35.primary_assembly.annotation.gtf.gz"),
}


def zipped(folder: str, files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(f"{folder}/{name}", text)
    return out.getvalue()


def kit(accession: str, topic: str, row: str, labels_for=None) -> tuple[str, bytes]:
    """The zip for one row of one dataset, with its file name. Raises ValueError when the row has no kit."""
    from . import agent

    labels_for = labels_for or agent.geo_labels
    records = samples.geo_records(accession)
    labels = labels_for(topic, accession, store.summary(accession))
    kind = options.data_type(records, labels)
    if kind == "bulk_rnaseq" and row in ("laptop", "cluster"):
        stats = options.ena_stats(sorted({r["srx"] for r in records if r["srx"]}))
        files = (bulk_laptop_kit if row == "laptop" else bulk_cluster_kit)(accession, topic, records, labels, stats)
    elif kind == "scrnaseq" and row in ("laptop", "cluster"):
        from . import singlecell
        files = (singlecell.laptop_kit if row == "laptop" else singlecell.cluster_kit)(accession, topic, labels_for)
    elif kind == "riboseq" and row == "cluster":
        from . import riboseq
        files = riboseq.cluster_kit(accession, topic, labels_for)
    else:
        raise ValueError(f"{accession} ({options.DATA_TYPES.get(kind or '', 'not a supported data type')}) has no {row} kit")
    folder = f"{accession}-{kind}-{row}"
    return f"{folder}.zip", zipped(folder, files)


# ---------------------------------------------------------------- bulk RNA-seq

def bulk_cluster_kit(accession: str, topic: str, records: list[dict], labels: dict, stats: dict) -> dict[str, str]:
    """nf-core/rnaseq samplesheet, Slurm script, Nextflow config and README for the contrast the laptop path would run,
    on the full reads of every run of each chosen sample."""
    contrast = process.choose_contrast(records, labels, options.runs_of(stats))
    organism = Counter(r["organism"] for r in records).most_common(1)[0][0]
    need = options.bulk_requirements(contrast["samples"], stats)
    fasta, gtf = GENCODE_GENOME[organism]
    release = process.GENCODE[organism][0]
    rows = ["sample,fastq_1,fastq_2,strandedness"]
    for s in contrast["samples"]:
        for run in stats[s["srx"]]["runs"]:
            fastq = run["fastq"] + [""]
            rows.append(f"{s['condition']}_{s['gsm']},{fastq[0]},{fastq[1]},auto")
    hours = int(need["cluster"]["time"].split("walltime ")[1].split(" h")[0])
    sbatch = f"""#!/bin/bash
#SBATCH --job-name=locus-{accession}
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time={hours:02d}:00:00
#SBATCH --output=locus-{accession}-%j.log
# The head job is small: Nextflow submits one Slurm job per task, and the STAR jobs ask for {options.STAR_MEMORY_GB} GB each (nextflow.config).
# Load your site's modules here, for example:  module load nextflow apptainer
set -euo pipefail
export NXF_SINGULARITY_CACHEDIR="${{NXF_SINGULARITY_CACHEDIR:-$PWD/apptainer-cache}}"
nextflow run {RNASEQ_PIPELINE} -r {RNASEQ_VERSION} -profile apptainer,slurm -c nextflow.config \\
  --input samplesheet.csv --outdir results \\
  --fasta {fasta} \\
  --gtf {gtf} \\
  --aligner star_salmon --pseudo_aligner salmon \\
  -resume
"""
    config = f"""// Minimal site config for {RNASEQ_PIPELINE} {RNASEQ_VERSION} on a Slurm cluster with Apptainer. Edit the queue name.
apptainer {{
    enabled    = true
    autoMounts = true
}}
profiles {{
    slurm {{
        process.executor = 'slurm'
        process.queue    = 'batch'          // your partition
        executor.queueSize = 50
    }}
}}
process {{
    resourceLimits = [ cpus: 32, memory: 240.GB, time: 48.h ]
    withName: 'STAR_ALIGN|STAR_ALIGN_IGENOMES|STAR_GENOMEGENERATE' {{
        memory = '{options.STAR_MEMORY_GB + 4}.GB'
        cpus   = 12
    }}
}}
"""
    conditions = Counter(s["condition"] for s in contrast["samples"])
    readme = f"""# {accession}: {RNASEQ_PIPELINE} {RNASEQ_VERSION} on a cluster

Written by locus from the GEO sample records and ENA's run table, for the same contrast as the laptop path:
{contrast['target']} ({conditions[contrast['target']]}) vs {contrast['reference']} ({conditions[contrast['reference']]}) from the field '{contrast['field']}'.
Question the labels answer: {topic}

## Files
- samplesheet.csv: one row per sequencing run of each chosen sample (full FASTQ URLs from ENA; the pipeline downloads them). Strandedness is 'auto'.
- run.sbatch: the Slurm submission. Edit the module lines for your site, then `sbatch run.sbatch`.
- nextflow.config: Apptainer on, a 'slurm' profile (set your partition), and {options.STAR_MEMORY_GB + 4} GB for the STAR jobs.

## Reference
GENCODE {release}: primary assembly genome and annotation, the same release the laptop tier quantifies against with salmon,
so gene identifiers and names match between the two tiers.
- {fasta}
- {gtf}

## Requirements for this dataset
- Memory: {need['cluster']['memory']}. This is why a 16 GB laptop cannot run it: a human STAR index needs about {options.STAR_MEMORY_GB} GB.
- Time: {need['cluster']['time']}.
- Disk: {need['cluster']['disk']} (reads, BAMs and the work directory; `nextflow clean -f` afterwards).

## Samples
""" + "\n".join(f"- {s['gsm']} {s['condition']}: {s['title']} ({stats[s['srx']]['reads'] / 1e6:,.1f} M reads, {len(stats[s['srx']]['runs'])} run(s))" for s in contrast["samples"]) + """

## Left out
""" + ("\n".join(f"- {s['gsm']}: {s['reason']}" for s in contrast["skipped"]) or "- none") + f"""

## Honest notes
- This kit was written on {accession}'s records; it was not run on a cluster. The samplesheet follows the pipeline's
  documented columns (sample, fastq_1, fastq_2, strandedness).
- The result is a full reanalysis (all reads, genome alignment with STAR, salmon quantification, QC in MultiQC), unlike the
  laptop path, which uses the first {process.READS:,} reads of each FASTQ and no genome alignment.
- Differential expression is not part of {RNASEQ_PIPELINE}; run DESeq2 on results/star_salmon/salmon.merged.gene_counts.tsv
  with the conditions in the sample names, or use nf-core/differentialabundance.
"""
    return {"samplesheet.csv": "\n".join(rows) + "\n", "run.sbatch": sbatch, "nextflow.config": config, "README.md": readme}


def bulk_laptop_kit(accession: str, topic: str, records: list[dict], labels: dict, stats: dict) -> dict[str, str]:
    """The laptop row as files: the command, the samples it will use and what it needs."""
    contrast = process.choose_contrast(records, labels, options.runs_of(stats))
    need = options.bulk_requirements(contrast["samples"], stats)
    samples_tsv = "gsm\tcondition\ttitle\trun\treads\tfastq\n" + "".join(
        f"{s['gsm']}\t{s['condition']}\t{s['title']}\t{s['run']}\t{stats[s['srx']]['reads']}\t{';'.join(s['fastq'])}\n" for s in contrast["samples"])
    command = f"uv run omics process {accession} --topic {options._quote(topic)}"
    run_sh = f"""#!/bin/sh
# {accession} on a laptop: the first {process.READS:,} reads of each FASTQ -> salmon -> counts -> DESeq2 -> five figures.
# Needs locus (https://github.com/UoSDDNB/omics-agent) and micromamba; the first run builds the reference (once per organism).
set -e
micromamba create -y -n {process.ENV} -c conda-forge -c bioconda salmon bioconductor-deseq2 bioconductor-tximport bioconductor-apeglm r-ggplot2 r-jsonlite || true
{command}
"""
    readme = f"""# {accession} on your laptop

{contrast['target']} vs {contrast['reference']} from '{contrast['field']}', {len(contrast['samples'])} samples (samples.tsv).
Question the labels answer: {topic}

Command: `{command}`

Needs: {need['laptop']['time']}; memory {need['laptop']['memory']}; disk {need['laptop']['disk']}.
Reads are subsampled, so the result is a preview of the study, not a reanalysis; the manifest says so.
Outputs land in data/process/{accession}/ (counts, DESeq2 results, five figures, manifest.json, explanation.md).
"""
    return {"README.md": readme, "run.sh": run_sh, "samples.tsv": samples_tsv}
