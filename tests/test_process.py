"""Offline tests for the processing pipeline's pure parts: contrast selection and .count writing."""

from pathlib import Path

import pytest

from omics_agent import process


def record(gsm, treatment, strategy="RNA-Seq", srx=True, organism="Homo sapiens"):
    return {"gsm": gsm, "title": f"cells {treatment} {gsm}", "organism": organism, "srx": f"SRX{gsm[3:]}" if srx else "",
            "fields": {"treatment": treatment, "library strategy": strategy}}


def runs_for(records):
    return {r["srx"]: [{"run": "SRR" + r["gsm"][3:], "fastq": [f"https://x/{r['gsm']}_1.fastq.gz", f"https://x/{r['gsm']}_2.fastq.gz"]}] for r in records if r["srx"]}


LABELS = {"group_field": "treatment", "case_values": ["drug", "other drug"], "control_values": ["vehicle"], "assays": ["RNA-seq"]}


def test_contrast_picks_the_most_frequent_case_and_control_values_and_explains_every_skip():
    records = [record("GSM1", "vehicle"), record("GSM2", "vehicle"), record("GSM3", "vehicle"), record("GSM4", "drug"), record("GSM5", "drug"),
               record("GSM6", "drug", srx=False), record("GSM7", "other drug"), record("GSM8", "vehicle", strategy="ChIP-Seq")]
    contrast = process.choose_contrast(records, LABELS, runs_for(records))
    assert (contrast["reference"], contrast["target"]) == ("vehicle", "drug")
    assert contrast["levels"] == {"control": "vehicle", "case": "drug"}
    assert [(s["gsm"], s["condition"]) for s in contrast["samples"]] == [("GSM1", "vehicle"), ("GSM2", "vehicle"), ("GSM3", "vehicle"), ("GSM4", "drug"), ("GSM5", "drug")]
    assert contrast["samples"][0]["run"] == "SRR1" and len(contrast["samples"][0]["fastq"]) == 2
    assert {s["gsm"]: s["reason"] for s in contrast["skipped"]} == {
        "GSM6": "no SRA experiment in the GEO record",
        "GSM7": "'treatment' is 'other drug'; the contrast uses 'drug'",
        "GSM8": "assay 'ChIP-Seq' is not bulk RNA-seq",
    }


def test_contrast_caps_each_condition_in_gsm_order():
    records = [record(f"GSM{i}", "vehicle" if i <= 6 else "drug") for i in range(1, 13)]
    contrast = process.choose_contrast(records, LABELS, runs_for(records), cap=3)
    assert [s["gsm"] for s in contrast["samples"]] == ["GSM1", "GSM2", "GSM3", "GSM7", "GSM8", "GSM9"]
    assert sum("beyond the cap" in s["reason"] for s in contrast["skipped"]) == 6


def test_contrast_refuses_a_single_replicate():
    records = [record("GSM1", "vehicle"), record("GSM2", "vehicle"), record("GSM3", "drug")]
    with pytest.raises(ValueError, match="only 1 case sample"):
        process.choose_contrast(records, LABELS, runs_for(records))


def test_contrast_refuses_a_missing_side():
    records = [record("GSM1", "vehicle"), record("GSM2", "vehicle")]
    with pytest.raises(ValueError, match="no case RNA-seq sample"):
        process.choose_contrast(records, LABELS, runs_for(records))


def test_contrast_names_conditions_from_the_values():
    records = [record(f"GSM{i}", "4EBP1/2 -/- + Torin1" if i > 2 else "Vehicle (DMSO)") for i in range(1, 5)]
    labels = {**LABELS, "case_values": ["4EBP1/2 -/- + Torin1"], "control_values": ["Vehicle (DMSO)"]}
    contrast = process.choose_contrast(records, labels, runs_for(records))
    assert (contrast["reference"], contrast["target"]) == ("vehicle_dmso", "4ebp1_2_torin1")


def test_count_files_are_htseq_style_integers(tmp_path: Path):
    counts = tmp_path / "counts.tsv"
    counts.write_text("gene_id\tGSM1\tGSM2\nENSG1\t10\t0\nENSG2\t3\t7\nENSG3\t2.6\t1.4\n")
    paths = process.write_count_files(counts, tmp_path)
    assert [p.name for p in paths] == ["GSM1.count", "GSM2.count"]
    assert paths[0].read_text() == "ENSG1\t10\nENSG2\t3\nENSG3\t3\n"
    assert paths[1].read_text() == "ENSG1\t0\nENSG2\t7\nENSG3\t1\n"


def test_tx2gene_comes_from_gencode_headers(tmp_path: Path):
    import gzip

    fasta = tmp_path / "t.fa.gz"
    with gzip.open(fasta, "wt") as f:
        f.write(">ENST1.1|ENSG1.2|OTTHUMG|OTTHUMT|ACTB-201|ACTB|1812|protein_coding|\nACGT\n>ENST2.1|ENSG2.1|-|-|X-201|X|10|lncRNA|\nACGT\n")
    assert process.write_tx2gene(fasta, tmp_path / "tx2gene.tsv") == 2
    assert (tmp_path / "tx2gene.tsv").read_text() == "transcript_id\tgene_id\tgene_name\nENST1.1\tENSG1.2\tACTB\nENST2.1\tENSG2.1\tX\n"


def test_top_genes_sorts_by_padj_and_skips_untested(tmp_path: Path):
    results = tmp_path / "deseq2_results.tsv"
    results.write_text("gene_id\tgene_name\tbaseMean\tlog2FoldChange\tlfcSE\tpvalue\tpadj\n"
                       "G1\tA\t100.26\t1.5\t0.1\t0.001\t0.01\nG2\tB\t5\t-2\t0.2\t0.0001\t0.002\nG3\tC\t1\t0\t0.5\tNA\tNA\n")
    top = process.top_genes(results, n=5)
    assert [g["gene_name"] for g in top] == ["B", "A"] and top[1]["base_mean"] == 100.3 and top[0]["padj"] == 0.002
