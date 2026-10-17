"""SDRF sample-level counts on three real tables vendored from bigbio/sdrf-annotated-datasets (Apache-2.0, commit b7d0b73)."""

from collections import Counter
from pathlib import Path

from omics_agent import sdrf, samples

FIXTURES = Path(__file__).parent / "fixtures" / "sdrf"


def table(accession: str) -> dict:
    return sdrf.parse(FIXTURES / f"{accession}.sdrf.tsv")


def labels(field: str, case: list[str], control: list[str]) -> dict:
    return {"group_field": field, "case_values": case, "control_values": control, "sample_type": "patient_tissue", "tissue": "t", "assays": ["proteomics"]}


def test_label_free_with_individuals_counts_samples_and_individuals_separately():
    t = table("PXD027637")
    fields = sdrf.sdrf_fields(t)
    assert fields["disease"] == Counter({"non-syndromic male infertility due to sperm motility disorder": 3, "normal": 3})
    assert fields["label"] == Counter({"label free sample": 6})
    facts = sdrf.count(t, labels("disease", ["non-syndromic male infertility due to sperm motility disorder"], ["normal"]), "SDRF samples")
    assert (facts["case"], facts["control"], facts["has_control"]) == (3, 3, True)
    assert facts["individuals"] == 6 and facts["individuals_by_group"] == {"case": 3, "control": 3}
    assert facts["runs"] == 6 and facts["excluded_pooled"] == 0 and facts["grain"] == "samples"
    assert facts["labels"] == {"label free sample": {"case": 3, "control": 3}}
    assert facts["libraries"] == {} and facts["assays"] == []
    # Semen is a biofluid by the table's organism part; the model's 'patient_tissue' label is overridden.
    assert facts["sample_type"] == "patient_biofluid"


def test_tmt_pooled_reference_is_left_out_and_runs_are_counted_per_channel():
    t = table("PXD042101")
    facts = sdrf.count(t, labels("disease", ["endometriosis"], ["normal"]), "SDRF samples")
    assert facts["runs"] == 120 and facts["excluded_pooled"] == 1
    assert (facts["case"], facts["control"]) == (3, 6)
    assert facts["individuals"] == 9 and facts["individuals_by_group"] == {"case": 3, "control": 6}
    assert facts["labels"] == {"TMT": {"case": 36, "control": 72}}
    # The pooled sample never reaches the label prompt's field summary.
    assert sum(sdrf.sdrf_fields(t)["disease"].values()) == 9


def test_a_table_without_an_individual_column_reports_unknown_individuals():
    t = table("PXD028392")
    facts = sdrf.count(t, labels("disease", ["Alzheimer disease"], ["normal"]), "SDRF samples")
    assert (facts["case"], facts["control"]) == (3, 3)
    assert facts["individuals"] is None and facts["individuals_by_group"] == {}


def test_labels_that_name_no_value_give_unknown_not_zero():
    t = table("PXD028392")
    facts = sdrf.count(t, labels("disease", ["Parkinson disease"], ["healthy"]), "SDRF samples")
    assert facts["case"] is None and facts["control"] is None and facts["has_control"] is None


def test_fields_feed_the_shared_label_prompt_and_resolution():
    fields = sdrf.sdrf_fields(table("PXD027637"))
    prompt = samples.label_prompt("male infertility", "PXD027637", fields)
    assert "disease:" in prompt and "'normal'" in prompt
    # The model sometimes renames a field; resolution finds the column holding the labelled values.
    resolved = samples.resolve_labels({"group_field": "condition", "case_values": ["normal"], "control_values": [], "assay_field": "", "assay_values": []}, fields)
    assert resolved["group_field"] == "disease"


def test_ontology_cells_and_missing_markers_are_reduced(tmp_path: Path):
    path = tmp_path / "x.sdrf.tsv"
    path.write_text("source name\tcharacteristics[disease]\tcharacteristics[individual]\tcomment[instrument]\n"
                    "A\tNT=lung cancer;AC=DOID:1\tnot available\tNT=Q Exactive;AC=MS:1\n"
                    "B\tnormal\tP2\tNT=Q Exactive;AC=MS:1\n")
    t = sdrf.parse(path)
    assert sdrf.column(t, "characteristics[disease]") == ["lung cancer", "normal"]
    assert sdrf.column(t, "characteristics[individual]") == ["", "P2"]
    assert sdrf.column(t, "factor value[x]") is None
    facts = sdrf.count(t, labels("disease", ["lung cancer"], ["normal"]), "SDRF samples")
    assert facts["individuals"] == 1 and facts["individuals_by_group"] == {"control": 1}


def test_the_table_decides_the_sample_type_when_it_can():
    assert sdrf.material_of({"cell line": Counter({"HeLa": 3})}, "Homo sapiens") == "cell_line"
    assert sdrf.material_of({"organism part": Counter({"liver": 3})}, "Mus musculus") == "animal_or_organoid_model"
    assert sdrf.material_of({"material type": Counter({"biofluid": 3}), "organism part": Counter({"blood serum": 3})}, "Homo sapiens") == "patient_biofluid"
    assert sdrf.material_of({"organism part": Counter({"colon": 3}), "material type": Counter({"tissue": 3})}, "Homo sapiens") == "patient_tissue"
    assert sdrf.material_of({}, "Homo sapiens") is None
    facts = sdrf.count(table("PXD042101"), labels("disease", ["endometriosis"], ["normal"]), "SDRF samples")
    assert facts["sample_type"] == "patient_biofluid"
