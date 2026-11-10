"""Offline tests for the three-row options: data type detection, requirement estimates and the bulk kits."""

import csv
import io
import zipfile

from omics_agent import kits, options


def record(gsm, title, strategy="RNA-Seq", **fields):
    return {"gsm": gsm, "title": title, "organism": "Homo sapiens", "srx": f"SRX{gsm[3:]}", "fields": {"library strategy": strategy, **fields}}


def stats_for(records, reads=30_000_000, layout="PAIRED"):
    return {r["srx"]: {"runs": [{"run": "SRR" + r["gsm"][3:], "fastq": [f"https://x/{r['gsm']}_1.fastq.gz", f"https://x/{r['gsm']}_2.fastq.gz"], "reads": reads, "bytes": reads * 60}],
                       "reads": reads, "bytes": reads * 60, "layout": layout, "read_length": 100} for r in records}


LABELS = {"group_field": "treatment", "case_values": ["drug"], "control_values": ["vehicle"], "assays": ["RNA-seq"]}


def test_data_type_tells_the_three_types_apart():
    bulk = [record("GSM1", "liver RNA-seq rep1", treatment="drug")]
    assert options.data_type(bulk, LABELS) == "bulk_rnaseq"
    footprints = [record("GSM1", "hek293_dmso_RPF_rep1", strategy="OTHER"), record("GSM2", "hek293_dmso_RNA_rep1")]
    assert options.data_type(footprints, LABELS) == "riboseq"
    nuclei = [record("GSM1", "NYU1057-T (snRNA-seq)", **{"sequencing type": "Single nuclei"})]
    assert options.data_type(nuclei, LABELS) == "scrnaseq"
    assert options.data_type([record("GSM1", "chip", strategy="ChIP-Seq")], {"assays": ["ChIP-seq"]}) is None


def test_bulk_requirements_scale_with_samples_and_reads():
    chosen = [{"srx": f"SRX{i}"} for i in range(6)]
    stats = {f"SRX{i}": {"reads": 40_000_000, "bytes": 2_400_000_000} for i in range(6)}
    need = options.bulk_requirements(chosen, stats)
    assert need["laptop"]["time"].startswith("about 6 min for 6 samples")
    assert need["laptop"]["memory"] == "about 4 GB"
    assert need["cluster"]["memory"] == "32 GB per alignment job"
    assert "6 samples as parallel jobs" in need["cluster"]["time"] and "40 M reads" in need["cluster"]["time"]
    assert need["cluster"]["disk"] == "about 43 GB"
    assert need["here"] == {"time": "instant", "memory": "none", "disk": "none"}


def test_bulk_cluster_kit_has_one_samplesheet_row_per_run_and_states_memory():
    records = [record(f"GSM{i}", f"cells {'vehicle' if i <= 3 else 'drug'} {i}", treatment="vehicle" if i <= 3 else "drug") for i in range(1, 7)]
    files = kits.bulk_cluster_kit("GSE1", "a drug", records, LABELS, stats_for(records))
    assert set(files) == {"samplesheet.csv", "run.sbatch", "nextflow.config", "README.md"}
    rows = list(csv.DictReader(io.StringIO(files["samplesheet.csv"])))
    assert [r["sample"] for r in rows] == ["vehicle_GSM1", "vehicle_GSM2", "vehicle_GSM3", "drug_GSM4", "drug_GSM5", "drug_GSM6"]
    assert rows[0]["fastq_2"].endswith("GSM1_2.fastq.gz") and rows[0]["strandedness"] == "auto"
    assert f"nf-core/rnaseq -r {kits.RNASEQ_VERSION}" in files["run.sbatch"] and "#SBATCH --time=" in files["run.sbatch"]
    assert "gencode.v46" in files["run.sbatch"] and "GENCODE human-46" in files["README.md"]
    assert "32 GB" in files["README.md"] and "not run on a cluster" in files["README.md"]
    assert "36.GB" in files["nextflow.config"]


def test_bulk_laptop_kit_carries_the_command_and_samples():
    records = [record(f"GSM{i}", f"cells {'vehicle' if i <= 2 else 'drug'} {i}", treatment="vehicle" if i <= 2 else "drug") for i in range(1, 5)]
    files = kits.bulk_laptop_kit("GSE1", "it's a drug", records, LABELS, stats_for(records))
    assert "uv run omics process GSE1 --topic 'it'\\''s a drug'" in files["run.sh"]
    assert files["samples.tsv"].count("\n") == 5


def test_zip_puts_files_in_one_folder():
    data = kits.zipped("GSE1-bulk_rnaseq-cluster", {"README.md": "hi"})
    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == ["GSE1-bulk_rnaseq-cluster/README.md"]
