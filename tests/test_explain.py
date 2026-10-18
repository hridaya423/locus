"""The explanation's number guard: every number the model writes must be one the pipeline computed."""

from omics_agent import explain

RESULT = {
    "accession": "GSE1", "reads_per_fastq": 2000000, "genes": 62646, "genes_tested": 6471, "significant": 84, "up": 44, "down": 40,
    "contrast": {"field": "treatment", "reference": "no_treatment", "target": "100_nm_rapamycin"},
    "samples": [{"condition": c} for c in ["no_treatment"] * 3 + ["100_nm_rapamycin"] * 3],
    "pca": {"variance": [25, 20.3], "means": {"no_treatment": {"PC1": -2.85, "PC2": -0.46}, "100_nm_rapamycin": {"PC1": 2.85, "PC2": 0.46}}},
    "top_genes": [{"gene_id": "ENSG1", "gene_name": "CCN2", "base_mean": 414.6, "log2fc": 1.219, "padj": 1.39e-12},
                  {"gene_id": "ENSG2", "gene_name": "DDIT4", "base_mean": 702.8, "log2fc": -0.718, "padj": 9.14e-08}],
}


def test_numbers_ignore_gene_names_and_axis_labels():
    assert explain.numbers("KRT7 and log2 fold change on PC1 and 4EBP1; 6,471 genes, 25% variance, padj 1.39e-12, -0.718") == {"6471", "25", "1.39e-12", "0.718"}


def test_a_paragraph_with_only_computed_numbers_is_kept():
    text = explain.prompt(RESULT, "HeLa rapamycin", "cells treated with 100 nM rapamycin")
    paragraph = "100_nm_rapamycin was compared with no_treatment, 3 samples each. 84 of 6,471 tested genes changed (44 up, 40 down); PC1 explains 25% of the variance. CCN2 rose (+1.219) and DDIT4 fell (-0.718); DDIT4 is known to be an mTORC1-dependent transcript. With 2,000,000 reads per FASTQ the counts are subsampled."
    out = explain.explain(RESULT, "HeLa rapamycin", "cells treated with 100 nM rapamycin", lambda p, s: {"answer_to_biologist": paragraph})
    assert out["explanation"] == paragraph and "checked" in out["note"]
    assert explain.invented(paragraph, text) == []


def test_a_paragraph_with_an_invented_number_is_dropped():
    paragraph = "About 12,000 genes were tested and 84 changed; roughly 30% of the variance is on PC1."
    out = explain.explain(RESULT, "t", "s", lambda p, s: {"answer_to_biologist": paragraph})
    assert out["explanation"] is None and "12,000" in out["note"] and "30" in out["note"] and "84" not in out["note"]


def test_a_failed_model_call_leaves_a_note_not_an_error():
    def ask(p, s):
        raise RuntimeError("server down")
    out = explain.explain(RESULT, "t", "s", ask)
    assert out["explanation"] is None and "server down" in out["note"]


def test_sentences_about_the_instructions_are_cut():
    paragraph = "We compared treated with untreated cells, three replicates each. 84 genes changed. All numbers are copied exactly from the prompt, and small counts are written in words."
    out = explain.explain(RESULT, "t", "s", lambda p, s: {"answer_to_biologist": paragraph})
    assert out["explanation"] == "We compared treated with untreated cells, three replicates each. 84 genes changed."
    assert "1 sentence about the instructions was cut" in out["note"]
