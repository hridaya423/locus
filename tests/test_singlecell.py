"""Offline tests for the single-cell module: detection, sample choice, GEO filelist parsing and the two kits. No network."""

from pathlib import Path

import pytest

from omics_agent import samples, singlecell, store

FIXTURES = Path(__file__).parent / "fixtures" / "geo"
LABELS = {"group_field": "tissue", "case_values": ["Tumor"], "control_values": ["Lung adjacent normal"], "sample_type": "patient_tissue", "tissue": "lung", "assays": ["snRNA-seq"]}


def record(n: int, tissue: str, sequencing: str = "Single nuclei", srx: bool = True, cells: str = "3000"):
    assay = "snRNA-seq" if sequencing == "Single nuclei" else "scRNA-seq"
    return {"gsm": f"GSM{7157644 + n}", "title": f"NYU{n}-{tissue[0]} ({assay})", "organism": "Homo sapiens", "srx": f"SRX{n}" if srx else "",
            "library_source": "transcriptomic single cell",
            "fields": {"tissue": tissue, "sequencing type": sequencing, "library strategy": "RNA-Seq", "# _of_cells": cells, "title pattern": f"NYU#-T ({assay})"}}


# ---------------------------------------------------------------- detect

def test_detects_single_cell_from_fields_titles_or_labels():
    assert singlecell.detect([record(0, "Tumor")])
    bulk = {"gsm": "GSM1", "title": "liver rep1", "organism": "Mus musculus", "srx": "SRX1", "library_source": "transcriptomic", "fields": {"library strategy": "RNA-Seq", "molecule": "polyA RNA"}}
    assert not singlecell.detect([bulk])
    assert singlecell.detect([bulk], {"assays": ["scRNA-seq"]})
    assert singlecell.detect([{**bulk, "title": "PBMC 10x Chromium run 2"}])
    assert singlecell.detect([{**bulk, "fields": {"library strategy": "RNA-Seq", "source name": "Drop-seq of cortex"}}])


def test_nuclei_wording_sets_the_stricter_mitochondrial_cutoff():
    assert singlecell.nuclei([record(0, "Tumor"), record(1, "Tumor")])
    assert not singlecell.nuclei([record(0, "Tumor", sequencing="Single cell"), record(1, "Tumor", sequencing="Single cell")])


# ---------------------------------------------------------------- filelist

def test_filelist_parsing_finds_one_matrix_triplet_per_sample():
    files = singlecell.parse_filelist((FIXTURES / "GSE229253_filelist.txt").read_text())
    assert len(files) == 99 and {f["kind"] for f in files} == {"matrix", "barcodes", "features"}
    first = files[0]
    assert first == {"gsm": "GSM7157644", "name": "GSM7157644_CID005975-1.counts_barcodes.tsv.gz", "bytes": 16347,
                     "url": "https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM7157nnn/GSM7157644/suppl/GSM7157644_CID005975-1.counts_barcodes.tsv.gz", "kind": "barcodes"}
    matrices = singlecell.matrices_of(files)
    assert len(matrices) == 33 and matrices["GSM7157644"]["layout"] == "mtx" and matrices["GSM7157644"]["bytes"] == 14107247 + 16347 + 272786
    assert [f["kind"] for f in matrices["GSM7157644"]["files"]] == ["matrix", "barcodes", "features"]


def test_processed_files_reads_the_cached_filelist(tmp_path, monkeypatch):
    monkeypatch.setattr(singlecell, "FILELIST_CACHE", tmp_path)
    (tmp_path / "GSE229253.txt").write_text((FIXTURES / "GSE229253_filelist.txt").read_text())
    assert len(singlecell.processed_files("GSE229253")) == 99


def test_matrices_prefer_triplets_then_h5_then_dense_and_ignore_incomplete():
    files = [{"gsm": "GSM1", "name": "GSM1_matrix.mtx.gz", "bytes": 5, "url": "", "kind": "matrix"},
             {"gsm": "GSM1", "name": "GSM1_barcodes.tsv.gz", "bytes": 1, "url": "", "kind": "barcodes"},
             {"gsm": "GSM2", "name": "GSM2_filtered_feature_bc_matrix.h5", "bytes": 7, "url": "", "kind": singlecell._kind("GSM2_filtered_feature_bc_matrix.h5")},
             {"gsm": "GSM3", "name": "GSM3_counts.csv.gz", "bytes": 9, "url": "", "kind": singlecell._kind("GSM3_counts.csv.gz")},
             {"gsm": "GSM4", "name": "GSM4_metadata.txt.gz", "bytes": 9, "url": "", "kind": singlecell._kind("GSM4_metadata.txt.gz")}]
    matrices = singlecell.matrices_of(files)
    assert set(matrices) == {"GSM2", "GSM3"} and matrices["GSM2"]["layout"] == "h5" and matrices["GSM3"]["layout"] == "dense"


# ---------------------------------------------------------------- choose

def test_choose_caps_each_side_in_gsm_order_and_explains_every_skip():
    records = [record(i, "Tumor" if i % 2 == 0 else "Lung adjacent normal") for i in range(12)] + [record(12, "Metastasis"), record(13, "Tumor")]
    blocked = {"GSM7157657": "no per-sample processed matrix in GEO"}
    plan = singlecell.choose(records, LABELS, lambda r: blocked.get(r["gsm"], ""), cap=3)
    assert (plan["reference"], plan["target"]) == ("lung_adjacent_normal", "tumor")
    assert [(s["gsm"], s["condition"]) for s in plan["samples"]] == [
        ("GSM7157645", "lung_adjacent_normal"), ("GSM7157647", "lung_adjacent_normal"), ("GSM7157649", "lung_adjacent_normal"),
        ("GSM7157644", "tumor"), ("GSM7157646", "tumor"), ("GSM7157648", "tumor")]
    reasons = {s["gsm"]: s["reason"] for s in plan["skipped"]}
    assert reasons["GSM7157656"] == "'tissue' is 'Metastasis', neither case nor control"
    assert reasons["GSM7157657"] == "no per-sample processed matrix in GEO"
    assert sum("beyond the cap" in r for r in reasons.values()) == 6


def test_choose_refuses_fewer_than_two_per_side():
    records = [record(0, "Tumor"), record(1, "Tumor"), record(2, "Lung adjacent normal")]
    with pytest.raises(ValueError, match="only 1 control sample"):
        singlecell.choose(records, LABELS, lambda r: "")
    with pytest.raises(ValueError, match="no usable case sample"):
        singlecell.choose(records, LABELS, lambda r: "no matrix" if r["fields"]["tissue"] == "Tumor" else "")


def test_here_fits_needs_four_matrices_without_labels_and_a_size_under_the_limit(monkeypatch):
    files = singlecell.parse_filelist((FIXTURES / "GSE229253_filelist.txt").read_text())
    monkeypatch.setattr(singlecell, "processed_files", lambda accession: files)
    records = [record(i, "Tumor" if i % 2 == 0 else "Lung adjacent normal") for i in range(8)]
    ok, reason = singlecell.here_fits("GSE229253", records)
    assert ok and "8 would be used" in reason
    ok, reason = singlecell.here_fits("GSE229253", records, max_bytes=10_000_000)
    assert not ok and "above the 10 MB limit" in reason
    ok, reason = singlecell.here_fits("GSE229253", records[:3])
    assert not ok and "3 of 3 samples" in reason
    ok, reason = singlecell.here_fits("GSE229253", records, labels={**LABELS, "case_values": ["Metastasis"]})
    assert not ok and reason.startswith("GEO's per-sample matrices do not cover the contrast")


# ---------------------------------------------------------------- kits

def fake_runs(experiments):
    runs = {}
    for x in experiments:
        n = int(x[3:])
        runs[x] = [{"run": f"SRR{n}a", "fastq": [f"https://ena/SRR{n}a_1.fastq.gz", f"https://ena/SRR{n}a_2.fastq.gz"], "reads": 50_000_000, "bytes": 3_000_000_000}]
        if n % 2:
            runs[x].append({"run": f"SRR{n}b", "fastq": [f"https://ena/SRR{n}b_1.fastq.gz", f"https://ena/SRR{n}b_2.fastq.gz"], "reads": 40_000_000, "bytes": 2_500_000_000})
    return runs


@pytest.fixture
def offline(monkeypatch):
    records = [record(i, "Tumor" if i % 2 == 0 else "Lung adjacent normal") for i in range(10)] + [record(10, "Tumor", srx=False)]
    monkeypatch.setattr(samples, "geo_records", lambda accession: records)
    monkeypatch.setattr(store, "summary", lambda accession: "A study.")
    monkeypatch.setattr(singlecell, "ena_runs", fake_runs)
    monkeypatch.setattr(singlecell, "read_length", lambda url, timeout=20: 28)
    return records


def test_laptop_kit_files_and_commands(offline):
    kit = singlecell.laptop_kit("GSE229253", "lung cancer", labels_for=lambda topic, accession, summary: LABELS)
    assert set(kit) == {"README.md", "run.sh", "samples.tsv", "singlecell_analyse.py", "pseudobulk_deseq2.R"}
    rows = kit["samples.tsv"].splitlines()
    assert rows[0].startswith("gsm\tcondition\trun\tfastq_1\tfastq_2\treads") and len(rows) == 1 + 4 + 4 + 4  # 8 samples, odd ones have two runs
    assert "TECH=${TECH:-10XV3}" in kit["run.sh"] and "read 1 is 28 nt" in kit["run.sh"]
    assert kit["run.sh"].count("kb count -i") == 8 and "head -n $((4 * READS))" in kit["run.sh"] and "READS=${READS:-20000000}" in kit["run.sh"]
    assert "release_46" in kit["run.sh"] and "--mito-max 0.1" in kit["run.sh"]
    assert "preview" in kit["README.md"] and "4 GB" in kit["README.md"] and "GSM7157654" in kit["README.md"]  # the sample without SRX is listed as left out
    assert kit["singlecell_analyse.py"] == singlecell.ANALYSE.read_text()


def test_laptop_kit_leaves_a_placeholder_when_the_technology_is_unknown(offline, monkeypatch):
    monkeypatch.setattr(singlecell, "read_length", lambda url, timeout=20: None)
    kit = singlecell.laptop_kit("GSE229253", "lung cancer", labels_for=lambda topic, accession, summary: LABELS)
    assert "TECH=${TECH:-FILL_IN}" in kit["run.sh"] and "could not be guessed" in kit["run.sh"]


def test_cluster_kit_samplesheet_has_one_row_per_run(offline):
    kit = singlecell.cluster_kit("GSE229253", "lung cancer", labels_for=lambda topic, accession, summary: LABELS)
    assert set(kit) == {"README.md", "samplesheet.csv", "conditions.csv", "run.sbatch", "nextflow.config", "singlecell_analyse.py", "pseudobulk_deseq2.R"}
    rows = kit["samplesheet.csv"].splitlines()
    assert rows[0] == "sample,fastq_1,fastq_2,expected_cells" and len(rows) == 1 + 12
    assert rows[1] == "GSM7157645_lung_adjacent_normal,https://ena/SRR1a_1.fastq.gz,https://ena/SRR1a_2.fastq.gz,3000"
    assert rows[2].startswith("GSM7157645_lung_adjacent_normal,https://ena/SRR1b_1.fastq.gz")
    assert "nextflow run nf-core/scrnaseq -r 4.0.0" in kit["run.sbatch"] and "--aligner star" in kit["run.sbatch"] and "--protocol 10XV3" in kit["run.sbatch"]
    assert "#SBATCH --mem=" in kit["run.sbatch"] and "#SBATCH --time=" in kit["run.sbatch"] and "--cpus-per-task" in kit["run.sbatch"]
    assert "GRCh38.primary_assembly.genome.fa.gz" in kit["run.sbatch"]
    assert "apptainer" in kit["nextflow.config"] and "resourceLimits" in kit["nextflow.config"] and "process.executor = 'slurm'" in kit["nextflow.config"]
    assert "32 GB" in kit["README.md"] and "did not run this kit" in kit["README.md"]


def test_cluster_kit_flags_runs_whose_barcode_read_is_missing(offline, monkeypatch):
    monkeypatch.setattr(singlecell, "ena_runs", lambda xs: {x: [{"run": f"SRR{x[3:]}", "fastq": [f"https://ena/SRR{x[3:]}.fastq.gz"], "reads": 80_000_000, "bytes": 2_000_000_000}] for x in xs})
    kit = singlecell.cluster_kit("GSE229253", "lung cancer", labels_for=lambda topic, accession, summary: LABELS)
    assert "barcode read is missing" in kit["README.md"] and "fasterq-dump --include-technical" in kit["README.md"]
    assert kit["samplesheet.csv"].splitlines()[1] == "GSM7157645_lung_adjacent_normal,,https://ena/SRR1.fastq.gz,3000"


def test_requirements_grow_with_cells_and_reads():
    small = singlecell.requirements(100_000_000, 5e9, 4, 5_000)
    large = singlecell.requirements(2_000_000_000, 100e9, 8, 80_000)
    assert set(small) == {"here", "laptop", "cluster"} and set(small["here"]) == {"time", "memory", "disk"}
    assert float(small["here"]["memory"].split()[0]) < float(large["here"]["memory"].split()[0])
    assert int(small["cluster"]["time"].split()[0]) < int(large["cluster"]["time"].split()[0])
