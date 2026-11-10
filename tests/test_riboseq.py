"""Offline tests for the Ribo-seq module's pure parts: detection, pairing and selection, GEO filelist parsing, the ΔTE
class rule, the P-site offset rule, one-transcript-per-gene selection and the cluster kit's files. No network."""

import gzip
from pathlib import Path

import pytest

from omics_agent import riboseq

FIXTURES = Path(__file__).parent / "fixtures"


def record(gsm, kind, treatment, genotype="wild-type", strategy=None, title=None, rep=1):
    """A GSE132703-style sample: '35YW: hek293_dmso_RPF_rep1' with library strategy OTHER for footprints."""
    title = title or f"35YW: hek293_{treatment.split()[0].lower()}_{kind}_rep{rep}"
    strategy = strategy or ("OTHER" if kind == "RPF" else "RNA-Seq")
    return {"gsm": gsm, "title": title, "organism": "Homo sapiens", "srx": f"SRX{gsm[3:]}",
            "fields": {"title pattern": title.replace(str(rep), "#"), "treatment": treatment, "genotype/variation": genotype, "library strategy": strategy, "molecule": "total RNA"}}


LABELS = {"group_field": "treatment", "case_values": ["Torin 1"], "control_values": ["DMSO"], "assays": ["Ribo-seq", "RNA-seq"],
          "assay_field": "library strategy", "assay_values": [{"assay": "Ribo-seq", "values": ["OTHER"]}, {"assay": "RNA-seq", "values": ["RNA-Seq"]}]}


def study(n_per_side=2):
    """n DMSO and n Torin 1 pairs: GSM1..: RPF then RNA for each treatment, the way GEO numbers them."""
    records, i = [], 0
    for treatment in ("DMSO", "Torin 1"):
        for kind in ("RPF", "RNA"):
            for rep in range(1, n_per_side + 1):
                i += 1
                records.append(record(f"GSM{i:03d}", kind, treatment, rep=rep))
    return records


# ---------------------------------------------------------------- detect and library kinds

def test_detect_from_footprint_titles_with_strategy_other():
    assert riboseq.detect(study())
    assert riboseq.detect([record("GSM001", "RPF", "DMSO", strategy="RNA-Seq")]), "a footprint title overrides a wrong strategy"
    assert not riboseq.detect([record("GSM001", "RNA", "DMSO")])


def test_detect_from_labels_when_titles_say_nothing():
    plain = [{"gsm": "GSM1", "title": "sample 1", "organism": "Homo sapiens", "srx": "", "fields": {"library strategy": "OTHER"}}]
    assert not riboseq.detect(plain)
    assert riboseq.detect(plain, {"assays": ["Ribosome profiling"]})
    assert riboseq.detect(plain, {"assays": [], "assay_values": [{"assay": "Ribo-seq", "values": ["x"]}]})
    assert not riboseq.detect(plain, {"assays": ["RNA-seq"]})


def test_library_kind_title_first_then_labels_then_strategy():
    assert riboseq.library_kind(record("GSM001", "RPF", "DMSO")) == "riboseq"
    assert riboseq.library_kind(record("GSM001", "RNA", "DMSO")) == "rnaseq"
    assert riboseq.library_kind({"title": "harringtonine footprints 1", "fields": {}}) == "", "TIS-seq is not Ribo-seq"
    assert riboseq.library_kind({"title": "sample 1", "fields": {"library strategy": "OTHER"}}, LABELS) == "riboseq"
    assert riboseq.library_kind({"title": "sample 1", "fields": {"library strategy": "RNA-Seq"}}) == "rnaseq"
    assert riboseq.library_kind({"title": "sample 1", "fields": {"library strategy": "ChIP-Seq"}}) == ""


# ---------------------------------------------------------------- pairing and selection

def test_pairs_match_ribo_and_rna_by_title_and_characteristics_and_cap_per_condition():
    records = study(6)
    plan = riboseq.choose_pairs(records, LABELS, cap=4)
    assert (plan["reference"], plan["target"]) == ("dmso", "torin_1")
    assert plan["levels"] == {"control": "DMSO", "case": "Torin 1"}
    ribo = [s for s in plan["samples"] if s["assay"] == "riboseq"]
    assert [s["condition"] for s in ribo] == ["dmso"] * 4 + ["torin_1"] * 4
    # Each pair holds one Ribo-seq and one RNA-seq library of the same treatment and replicate.
    for n in range(1, 9):
        pair = [s for s in plan["samples"] if s["pair"] == n]
        assert sorted(s["assay"] for s in pair) == ["riboseq", "rnaseq"]
        assert len({s["condition"] for s in pair}) == 1
    assert sum("beyond the cap of 4 pairs" in s["reason"] for s in plan["skipped"]) == 8


def test_unpaired_and_unlabelled_libraries_are_skipped_with_a_reason():
    records = study(2)
    records.append(record("GSM101", "RPF", "DMSO", title="35YW: hek293_dmso_RPF_rep9_reseq"))   # a footprint library without an RNA-seq twin
    records.append(record("GSM102", "RPF", "rapamycin", title="35YW: hek293_rapa_RPF_rep1"))
    records.append(record("GSM103", "RNA", "rapamycin", title="35YW: hek293_rapa_RNA_rep1"))
    plan = riboseq.choose_pairs(records, LABELS)
    reasons = {s["gsm"]: s["reason"] for s in plan["skipped"]}
    assert "no RNA-seq library shares its title" in reasons["GSM101"]
    assert reasons["GSM102"] == "'treatment' is 'rapamycin', neither case nor control"
    assert len(plan["samples"]) == 8


def test_libraries_without_files_are_skipped_and_too_few_pairs_raise():
    records = study(2)
    available = {r["gsm"]: "x" for r in records if r["gsm"] != "GSM001"}
    with pytest.raises(ValueError, match="only 1 control Ribo-seq/RNA-seq pair"):
        riboseq.choose_pairs(records, LABELS, available)
    with pytest.raises(ValueError, match="no paired case"):
        riboseq.choose_pairs(study(2)[:4], LABELS)


def test_pooled_factors_warn_when_another_field_varies():
    records = study(2) + [record(f"GSM1{i}", k, t, genotype="sgLARP1", title=f"93C: larp1sko_{t.split()[0].lower()}_{k}_rep{r}")
                          for i, (t, k, r) in enumerate((t, k, r) for t in ("DMSO", "Torin 1") for k in ("RPF", "RNA") for r in (1, 2))]
    plan = riboseq.choose_pairs(records, LABELS, cap=4)
    warnings = riboseq.pooled_factors(plan["samples"], "treatment")
    assert warnings == ["'genotype/variation' takes 2 values among the chosen libraries (sgLARP1, wild-type); the contrast pools them."]


# ---------------------------------------------------------------- GEO count tables

def test_filelist_parsing_gives_per_sample_files_with_assay_and_url():
    files = riboseq.parse_filelist((FIXTURES / "GSE132703_filelist.txt").read_text())
    assert len(files) == 24 and all(f["name"] != "GSE132703_RAW.tar" for f in files)
    first = files[0]
    assert first == {"gsm": "GSM3889077", "name": "GSM3889077_35YW_d1_RPF.htseqcounts.txt.gz", "bytes": 79794,
                     "url": "https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM3889nnn/GSM3889077/suppl/GSM3889077_35YW_d1_RPF.htseqcounts.txt.gz", "assay": "riboseq"}
    assert {f["assay"] for f in files} == {"riboseq", "rnaseq"}
    assert sum(f["assay"] == "riboseq" for f in files) == 12
    assert riboseq.file_assay("GSM1_DKO_DMSOa_RPF_unique.htseqcounts.txt.gz") == "riboseq"
    assert riboseq.file_assay("GSM1_DKO_DMSOa_RNA.htseqcounts_cds.txt.gz") == "rnaseq"
    assert riboseq.file_assay("GSM1_counts.txt.gz") == ""


def test_read_counts_sums_columns_and_drops_htseq_summary_rows(tmp_path: Path):
    path = tmp_path / "x.txt.gz"
    with gzip.open(path, "wt") as f:
        f.write("A1BG\t0\t9\nA2M\t1\t1\n__no_feature\t149382\t658574\n__alignment_not_unique\t1\t2\n")
    assert riboseq.read_counts(path) == {"A1BG": 9, "A2M": 2}


def test_write_counts_joins_libraries_and_reports_missing_genes(tmp_path: Path):
    tables = {"GSM1": {"A": 1, "B": 2}, "GSM2": {"A": 3}}
    genes, warnings = riboseq.write_counts(tables, ["GSM1", "GSM2"], tmp_path / "counts.tsv")
    assert genes == 2 and warnings == ["GSM2 lists 1 fewer genes than the others; they count 0 there"]
    assert (tmp_path / "counts.tsv").read_text() == "gene\tGSM1\tGSM2\nA\t1\t3\nB\t2\t0\n"


# ---------------------------------------------------------------- the class rule and the offset rule

@pytest.mark.parametrize("args, expected", [
    ((0.5, 0.1, 0.01, 1.0, 0.01, 0.9), "translationally regulated"),
    ((None, 0.0, 0.2, 0.3, 0.001, -1.2), "translationally regulated"),   # NA ΔRNA counts as not significant
    ((0.01, 1.0, 0.6, 0.1, 0.01, -0.9), "buffered"),                     # mRNA up, ribosomes flat: TE down
    ((0.01, 1.0, 0.01, 2.2, 0.01, 1.2), "intensified"),                  # all up, ribosomes more than mRNA
    ((0.01, 1.0, 0.01, 1.1, 0.4, 0.1), "transcriptional"),               # ribosomes follow the mRNA
    ((0.01, 1.0, 0.3, 0.4, 0.3, -0.6), "unchanged"),                     # only the mRNA moved
    ((0.9, 0.0, 0.9, 0.0, float("nan"), 0.0), "unchanged"),
])
def test_classify(args, expected):
    assert riboseq.classify(*args) == expected


def test_psite_offset_is_the_mode_within_30_nt_or_falls_back():
    distances = [12] * 300 + [13] * 120 + [11] * 80 + [40] * 500 + [0] * 50
    assert riboseq.psite_offset(distances) == (12, 500, False), "distances beyond 30 nt or at 0 do not count"
    assert riboseq.psite_offset([12] * 150 + [13] * 40) == (12, 190, True)
    assert riboseq.psite_offset([]) == (12, 0, True)
    assert riboseq.psite_offset([15] * 100 + [14] * 100 + [16] * 50)[0] == 14, "a tie goes to the shorter offset"


def test_corrected_offset_moves_the_dominant_frame_to_frame_0():
    assert riboseq.corrected_offset(12, (100, 100, 400)) == (13, True), "5′ ends in frame 2 need an offset ≡ 1 mod 3; 13 is nearest to 12"
    assert riboseq.corrected_offset(13, (100, 100, 400)) == (13, False)
    assert riboseq.corrected_offset(12, (400, 100, 100)) == (12, False)
    assert riboseq.corrected_offset(12, (100, 400, 100)) == (11, True)
    assert riboseq.corrected_offset(12, (340, 330, 330)) == (12, False), "no dominant frame: keep the start-codon mode"
    assert riboseq.corrected_offset(12, (0, 0, 0)) == (12, False)


def test_psite_script_rule_matches_the_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("riboseq_psite", riboseq.PSITE_SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    for distances in ([12] * 300 + [13] * 100, [9] * 250, [10] * 10):
        assert script.psite_offset(distances) == riboseq.psite_offset(distances)
    for args in ((12, (100, 100, 400)), (12, (340, 330, 330)), (13, (100, 400, 100))):
        assert script.corrected_offset(*args) == riboseq.corrected_offset(*args)


# ---------------------------------------------------------------- reference selection

def test_one_transcript_per_gene_keeps_the_longest_atg_cds(tmp_path: Path):
    counts = riboseq.select_transcripts(FIXTURES / "pc_transcripts_small.fa.gz", tmp_path / "transcripts.fa", tmp_path / "cds.tsv")
    assert counts == {"genes": 2, "transcripts": 2}
    rows = [line.split("\t") for line in (tmp_path / "cds.tsv").read_text().splitlines()]
    assert rows[0] == ["transcript", "gene_id", "gene_name", "gene", "cds_start", "cds_end", "length"]
    assert rows[1] == ["ENST2.1", "ENSG1.1", "GENEA", "GENEA", "13", "138", "143"], "the longer CDS wins; the PAR_Y copy is dropped"
    assert rows[2][0] == "ENST4.1", "a CDS that does not start with ATG is not used"
    headers = [l for l in (tmp_path / "transcripts.fa").read_text().splitlines() if l.startswith(">")]
    assert headers == [">ENST2.1", ">ENST4.1"]


# ---------------------------------------------------------------- the cluster kit

def test_kit_files_add_slurm_nextflow_and_readme_to_the_samplesheet():
    sheets = {"samplesheet.csv": "sample,fastq_1\nGSM1,x\n", "contrasts.csv": "id\n", "README.txt": "labels\n"}
    files = riboseq.kit_files("GSE132703", "Homo sapiens", 400_000_000, 28, sheets)
    assert sorted(files) == ["README.md", "README.txt", "contrasts.csv", "nextflow.config", "run.sbatch", "samplesheet.csv"]
    assert "#SBATCH --mem=64G" in files["run.sbatch"] and "#SBATCH --cpus-per-task=16" in files["run.sbatch"] and "#SBATCH --time=10:00:00" in files["run.sbatch"]
    assert "nextflow run nf-core/riboseq -r 1.2.0 -profile apptainer,slurm" in files["run.sbatch"] and "--contrasts contrasts.csv" in files["run.sbatch"]
    assert "release_46/GRCh38.primary_assembly.genome.fa.gz" in files["run.sbatch"] and "gencode.v46.primary_assembly.annotation.gtf.gz" in files["run.sbatch"]
    assert "resourceLimits" in files["nextflow.config"] and "executor = 'slurm'" in files["nextflow.config"]
    assert "32 GB" in files["README.md"] and "NOT run on a cluster" in files["README.md"]
    assert "--contrasts" not in riboseq.kit_files("GSE1", "Mus musculus", 1, 1, {"samplesheet.csv": ""})["run.sbatch"]


def test_requirements_scale_with_reads_and_libraries():
    small = riboseq.requirements(16 * 2_000_000, 2e9, 16)
    big = riboseq.requirements(2_000_000_000, 150e9, 28)
    assert set(small) == {"here", "laptop", "cluster"} and set(small["laptop"]) == {"time", "memory", "disk"}
    assert small["here"]["time"] == "under a minute"
    assert small["laptop"]["time"] == "about 10 min" and big["laptop"]["time"] == "about 15 min", "the laptop caps reads at 2 M per library"
    assert small["laptop"]["disk"] == "4 GB"
    assert big["cluster"]["time"] == "about 42 h" and "32 GB" in big["cluster"]["memory"]


# ---------------------------------------------------------------- read structure and alignment mode

def test_read_structure_picks_the_innermost_linker_and_counts_5prime_g_runs(tmp_path: Path):
    linker, truseq = "CTGTAGGCACCATCAAT", "AGATCGGAAGAGCACACGTCT"
    reads = [("N" + "GGGG" if i % 4 == 0 else "A") + "ACGTACGTACGTACGTACGTACGTACG" + linker + truseq + "ACGT" for i in range(100)]
    fastq = tmp_path / "x.fastq.gz"
    with gzip.open(fastq, "wt") as f:
        for i, seq in enumerate(reads):
            f.write(f"@r{i}\n{seq}\n+\n{'I' * len(seq)}\n")
    structure = riboseq.read_structure(fastq)
    assert structure["adapter"] == linker and structure["adapter_share"] == 1.0, "both adapters are present; the upstream linker is the one to trim"
    assert structure["five_prime_g"] == 0.25 and structure["reads_scanned"] == 100
    with gzip.open(fastq, "wt") as f:
        f.write("@r\nACGTACGTACGTACGTACGTACGTACGTACGT\n+\n" + "I" * 32 + "\n")
    assert riboseq.read_structure(fastq)["adapter"] == "", "no known linker: fastp detects it instead"


def test_alignment_mode_is_end_to_end_unless_untrimmed_or_g_capped():
    assert riboseq.alignment_mode(True, 0.01)[0] == "--very-sensitive"
    assert riboseq.alignment_mode(True, 0.12)[0] == "--very-sensitive-local"
    assert riboseq.alignment_mode(False, 0.0)[0] == "--very-sensitive-local"
