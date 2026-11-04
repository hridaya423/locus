"""SDRF-to-mqpar mapping on three real PRIDE SDRFs vendored from bigbio/sdrf-annotated-datasets (Apache-2.0): a label-free
Orbitrap study (PXD000159), the TMT6plex example dataset (PXD000001) and a fractionated label-free study (PXD001345); plus
the refusal when a project has no SDRF, and the contract checks that catch MaxQuant's late failures."""

import re
import shutil
import subprocess
import zipfile
import io
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from omics_agent import maxquant

FIXTURES = Path(__file__).parent / "fixtures" / "sdrf"


def design(accession: str) -> maxquant.Design:
    return maxquant.design_of(accession, maxquant.read_sdrf(FIXTURES / f"{accession}.sdrf.tsv"))


def group(xml: str) -> ET.Element:
    return ET.fromstring(xml).find("parameterGroups/parameterGroup")


def test_label_free_runs_experiments_and_defaults():
    d = design("PXD000159")
    assert len(d.runs) == 12 and d.labelling == "label free" and not d.fractionated
    assert d.runs[0].file == "SIRT6_negative_120125175013.raw" and d.runs[0].experiment == "SIRT6_negative_120125175013"
    assert d.instrument == "LTQ Orbitrap" and d.ms_instrument == 0 and d.organism == "Homo sapiens"
    assert d.enzymes == ["Trypsin/P"] and not d.unspecific
    # This SDRF states no modification parameters: MaxQuant's usual defaults, and the README tells the user to check them.
    assert d.fixed == ["Carbamidomethyl (C)"] and d.variable == ["Oxidation (M)", "Acetyl (Protein N-term)"]
    assert any("modification parameters" in c for c in d.checks)
    xml = maxquant.mqpar_xml(d)
    g = group(xml)
    assert (g.findtext("lfqMode"), g.findtext("matchBetweenRuns"), g.findtext("lcmsRunType")) == ("1", "True", "Standard")
    assert g.findtext("multiplicity") == "1" and [e.text for e in g.find("labelMods")] == [None]
    assert [e.text for e in ET.fromstring(xml).find("fractions")] == ["32767"] * 12
    assert maxquant.validate_mqpar(xml) == []


def test_tmt_channels_become_isobaric_labels():
    d = design("PXD000001")
    assert len(d.runs) == 1 and d.labelling == "TMT6plex" and d.channels == ["126", "127", "128", "129", "130", "131"]
    assert d.runs[0].experiment == "TMT_Erwinia_spike_culture" and d.runs[0].channels == d.channels
    xml = maxquant.mqpar_xml(d)
    g = group(xml)
    assert (g.findtext("lcmsRunType"), g.findtext("lfqMode"), g.findtext("matchBetweenRuns")) == ("Reporter ion MS2", "0", "False")
    labels = [(i.findtext("internalLabel"), i.findtext("terminalLabel"), i.findtext("tmtLike")) for i in g.find("isobaricLabels")]
    assert len(labels) == 6 and labels[0] == ("TMT6plex-Lys126", "TMT6plex-Nter126", "True")
    assert g.findtext("multiplicity") == "1" and len(g.find("labelMods")) == 1
    assert g.findtext("reporterMassTolerance") == "0.003"
    assert maxquant.validate_mqpar(xml) == []


def test_fractions_and_modifications_follow_the_sdrf():
    d = design("PXD001345")
    assert len(d.runs) == 24 and d.fractionated and len({r.experiment for r in d.runs}) == 8
    fractions: dict[str, list[int]] = {}
    for r in d.runs:
        fractions.setdefault(r.experiment, []).append(r.fraction)
    assert all(sorted(f) == [1, 2, 3] for f in fractions.values())
    assert d.fixed == ["Carbamidomethyl (C)"]
    assert d.variable == ["Oxidation (M)", "Acetyl (Protein N-term)", "Deamidation (NQ)", "Gln->pyro-Glu"]
    assert d.instrument == "Q Exactive" and d.organism == "Enterococcus faecalis" and d.enzymes == ["Trypsin/P"]
    xml = maxquant.mqpar_xml(d)
    root = ET.fromstring(xml)
    assert [e.text for e in root.find("fractions")][:3] == ["1", "2", "3"]
    assert [e.text for e in root.find("experiments")][:3] == ["Efaecalis_V583_urine_BR2_intracellular"] * 3
    assert maxquant.validate_mqpar(xml) == []


def test_no_sdrf_is_refused_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(maxquant.sdrf, "sdrf_path", lambda accession: None)
    monkeypatch.setattr(maxquant.sdrf, "pride_sdrf", lambda accession: None)
    with pytest.raises(LookupError, match=r"PXD999999 has no SDRF: none in the curated corpus and none listed in PRIDE"):
        maxquant.kit_files("PXD999999")


def test_mixed_or_unknown_labelling_is_refused():
    with pytest.raises(ValueError, match="disagree on labelling"):
        maxquant._labelling(["label free sample", "TMT126"])
    with pytest.raises(ValueError, match="not one the kit can map"):
        maxquant._labelling(["dimethyl light", "dimethyl heavy"])
    with pytest.raises(ValueError, match="comment\\[label\\] is empty"):
        maxquant._labelling(["", ""])


def test_reagents_are_inferred_from_channels_or_named_outright():
    assert maxquant._labelling(["TMT126C", "TMT127N", "TMT131N"]) == ("TMT10plex", ["126C", "127N", "131N"], [])
    assert maxquant._labelling(["TMT131C", "TMT126C"])[0] == "TMT11plex"
    assert maxquant._labelling(["iTRAQ114", "iTRAQ117"]) == ("iTRAQ4plex", ["114", "117"], [])
    plex, channels, checks = maxquant._labelling(["TMT11plex"])
    assert plex == "TMT11plex" and len(channels) == 11 and "not the channels" in checks[0]
    labelling, states, checks = maxquant._labelling(["SILAC light", "SILAC heavy"])
    assert (labelling, states) == ("SILAC", ["light", "heavy"]) and checks


def test_silac_sets_multiplicity_and_label_mods_together():
    d = design("PXD000159")
    d.labelling, d.channels = "SILAC", ["light", "heavy"]
    g = group(maxquant.mqpar_xml(d))
    assert g.findtext("multiplicity") == "2" and [e.text for e in g.find("labelMods")] == [None, "Arg10;Lys8"]
    assert maxquant.validate_mqpar(maxquant.mqpar_xml(d)) == []


def test_modification_names():
    assert maxquant.modification_name("NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed") == "Carbamidomethyl (C)"
    assert maxquant.modification_name("NT=Acetyl;AC=UNIMOD:1;PP=Protein N-term;MT=Variable") == "Acetyl (Protein N-term)"
    assert maxquant.modification_name("NT=Phospho;AC=UNIMOD:21;TA=S,T,Y;MT=Variable") == "Phospho (STY)"
    assert maxquant.modification_name("NT=GG;AC=UNIMOD:121;TA=K;MT=Variable") == "GlyGly (K)"
    assert maxquant.modification_name("NT=Gln->pyro-Glu;AC=UNIMOD:28;TA=Q;PP=Any N-term;MT=Variable") == "Gln->pyro-Glu"
    assert maxquant.modification_name("not available") is None


def test_contract_catches_the_known_late_failures():
    xml = maxquant.mqpar_xml(design("PXD000159"))
    assert maxquant.validate_mqpar(xml) == []
    cases = {
        "referenceChannel": xml.replace("<massDifferenceMods />", "<massDifferenceMods /><referenceChannel />"),
        "labelMods has 0 entries": re.sub(r"<labelMods>.*?</labelMods>", "<labelMods />", xml, flags=re.S),
        "msmsParamsArray must list": re.sub(r"<msmsParamsArray>.*?</msmsParamsArray>", "<msmsParamsArray />", xml, flags=re.S),
        "restrictMods must be": re.sub(r"<restrictMods>.*?</restrictMods>", "<restrictMods />", xml, flags=re.S),
        "not kit-relative": xml.replace("__KIT_DIR__/fasta", "/home/someone/fasta"),
        "not parallel": re.sub(r"<ptms>.*?</ptms>", "<ptms />", xml, flags=re.S),
        "not well-formed": xml[:-30],
    }
    for expected, broken in cases.items():
        assert any(expected in p for p in maxquant.validate_mqpar(broken)), expected


def test_kit_files_scripts_and_notices(monkeypatch):
    monkeypatch.setattr(maxquant.sdrf, "sdrf_path", lambda accession: FIXTURES / f"{accession}.sdrf.tsv")
    monkeypatch.setattr(maxquant, "raw_files", lambda accession: [
        {"name": "SIRT6_negative_120125175013.raw", "bytes": 526593382, "url": "https://ftp.pride.ebi.ac.uk/x/SIRT6_negative_120125175013.raw", "checksum": "abc"}])
    files = maxquant.kit_files("PXD000159")
    assert set(files) == {"mqpar.xml", "preflight.sh", "download_raw.sh", "download_fasta.sh", "run_maxquant.sh", "run_all.sh", "submit_slurm.sh", "README.txt", "LICENSE.pridemap"}
    # The caveat is in the README and in the preflight the user runs first; the credit carries the MIT notice.
    assert maxquant.README_CAVEAT in files["README.txt"] and maxquant.README_CAVEAT in files["preflight.sh"]
    assert "MIT License" in files["LICENSE.pridemap"] and "pridemap" in files["README.txt"]
    assert "11 file(s) named in the SDRF are not in PRIDE's RAW listing" in files["README.txt"]
    assert 'fetch "SIRT6_negative_120125175013.raw" "526593382" "abc"' in files["download_raw.sh"]
    assert "--mem=32G" in files["submit_slurm.sh"] and "--cpus-per-task=8" in files["submit_slurm.sh"] and "--time=0-18:00:00" in files["submit_slurm.sh"]
    assert 'UP="UP000005640"' in files["download_fasta.sh"]
    if shutil.which("bash"):
        for name, text in files.items():
            if name.endswith(".sh"):
                assert subprocess.run(["bash", "-n"], input=text, text=True, capture_output=True).returncode == 0, name
    archive = zipfile.ZipFile(io.BytesIO(maxquant.export_kit("PXD000159")))
    assert sorted(archive.namelist()) == sorted(f"PXD000159-maxquant/{n}" for n in files)
    assert archive.getinfo("PXD000159-maxquant/run_all.sh").external_attr >> 16 == 0o755


@pytest.mark.parametrize("name, code, run_type, max_charge", [
    ("timsTOF Pro", 4, "TIMS-DDA", "4"), ("Bruker impact II", 1, "Standard", "4"), ("TripleTOF 6600", 2, "Standard", "4"),
    ("Agilent 6550 iFunnel Q-TOF", 3, "Standard", "4"), ("Q Exactive HF", 0, "Standard", "7")])
def test_instrument_group_sets_code_run_type_and_peak_settings(name, code, run_type, max_charge):
    """MaxQuant's codes: 0 Orbitrap, 1 Bruker Q-TOF, 2 Sciex Q-TOF, 3 Agilent Q-TOF, 4 Bruker TIMS (a timsTOF filed as 1 is read
    as a plain Q-TOF and loses its ion mobility)."""
    table = maxquant.read_sdrf(FIXTURES / "PXD000159.sdrf.tsv")
    column = table["columns"].index("comment[instrument]")
    table["rows"] = [r[:column] + [f"NT={name}"] + r[column + 1:] for r in table["rows"]]
    d = maxquant.design_of("PXD000159", table)
    xml = maxquant.mqpar_xml(d)
    g = group(xml)
    assert (g.findtext("msInstrument"), g.findtext("lcmsRunType"), g.findtext("maxCharge")) == (str(code), run_type, max_charge)
    assert (g.findtext("mainSearchTol") == "10") == (code != 0)
    assert maxquant.validate_mqpar(xml) == []


def test_licence_gate_and_measured_sizing(monkeypatch, tmp_path):
    monkeypatch.setattr(maxquant.sdrf, "sdrf_path", lambda accession: FIXTURES / f"{accession}.sdrf.tsv")
    monkeypatch.setattr(maxquant, "raw_files", lambda accession: [
        {"name": "SIRT6_negative_120125175013.raw", "bytes": 10_000_000_000, "url": "https://ftp.pride.ebi.ac.uk/x/a.raw", "checksum": ""}])
    files = maxquant.kit_files("PXD000159")
    assert "about 40 GB disk" in files["README.txt"] and "MAXQUANT_ACCEPT_LICENSE=1" in files["README.txt"]
    for name in ("preflight.sh", "run_maxquant.sh"):
        assert "MAXQUANT_ACCEPT_LICENSE" in files[name]
    assert "TMPDIR" in files["submit_slurm.sh"]
    if shutil.which("bash"):
        # Without the licence accepted the search refuses before it looks for raw files or pulls anything.
        (tmp_path / "run_maxquant.sh").write_text(files["run_maxquant.sh"])
        (tmp_path / "mqpar.xml").write_text(files["mqpar.xml"])
        env = {"PATH": "/usr/bin:/bin"}
        out = subprocess.run(["bash", "run_maxquant.sh"], cwd=tmp_path, env=env, capture_output=True, text=True)
        assert out.returncode == 1 and "MAXQUANT_ACCEPT_LICENSE=1" in out.stdout


def test_bruker_runs_are_fetched_zipped_and_unpacked(monkeypatch):
    table = maxquant.read_sdrf(FIXTURES / "PXD000159.sdrf.tsv")
    column = table["columns"].index("comment[data file]")
    table["rows"] = [r[:column] + [r[column].replace(".raw", ".d")] + r[column + 1:] for r in table["rows"]]
    monkeypatch.setattr(maxquant, "sdrf_table", lambda accession: table)
    runs = [r[column] for r in table["rows"]]
    monkeypatch.setattr(maxquant, "raw_files", lambda accession: [
        {"name": f"{run}.zip", "bytes": 1_000_000_000, "url": f"https://ftp.pride.ebi.ac.uk/x/{run}.zip", "checksum": ""} for run in runs])
    files = maxquant.kit_files("PXD000159")
    script = files["download_raw.sh"]
    assert f'fetch "{runs[0]}.zip"' in script and f'unpack "{runs[0]}" "{runs[0]}.zip"' in script
    assert "not in PRIDE's RAW listing" not in files["README.txt"]
    assert subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True).returncode == 0


def test_diff_lists_only_the_fields_that_differ():
    kits = {a: maxquant.mqpar_xml(design(a)) for a in ("PXD000159", "PXD000001")}
    text = maxquant.diff_fields(kits)
    assert "lcmsRunType" in text and "Reporter ion MS2" in text and "peptideFdr" not in text
