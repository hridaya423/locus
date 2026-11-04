"""A MaxQuant search kit for one PRIDE project, built from its SDRF: mqpar.xml, the download and run scripts, a Slurm
submission script and a README. locus generates and validates the kit; the user runs it on a cluster or a workstation
that meets MaxQuant's requirements. It does not run here (see README_CAVEAT).

The SDRF is the only source of the run list, labelling, fractions, instrument, enzymes and modifications. A project
without an SDRF is refused with a clear message rather than guessed at, because a wrong mqpar.xml fails hours into a
run rather than at the start.

The mqpar contract (which fields must be present, absent, empty or sized to another field) and the shape of the scripts
follow PRIDE Map (github.com/FlynnLachendro/pridemap, MIT, see LICENSE.pridemap), re-implemented here in this
repository's style. Every row of that contract records a MaxQuant 2.0.3 run that died 10 to 37 minutes in.
"""

import csv
import io
import json
import math
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET

from . import sdrf, sources

MAXQUANT_VERSION = "2.0.3.0"
MAXQUANT_IMAGE = f"quay.io/biocontainers/maxquant:{MAXQUANT_VERSION}--py310hdfd78af_1"
KIT_DIR = "__KIT_DIR__"  # run_maxquant.sh substitutes the unpacked kit directory; MaxQuant's workers need absolute paths
MIN_MEMORY_GB = 16  # per search; PRIDE Map measured a 13.4 GB peak for two DDA runs (PXD046787, 2026-10-20)
THREADS = 8
MISSING = sdrf.MISSING
NO_FRACTION = 32767  # MaxQuant's value for "not fractionated"

README_CAVEAT = (
    "THIS KIT DID NOT RUN ON THE MACHINE THAT MADE IT. MaxQuant needs 16 GB of RAM per search, disk of about four times "
    f"the raw data, and the published container ({MAXQUANT_IMAGE}) is x86-64 only. A small project (a few raw files) "
    "fits an x86-64 workstation; a large one belongs on a cluster. Run preflight.sh where you want to search, then "
    "run_all.sh or sbatch submit_slurm.sh. locus generated and validated this kit; it has not run the search."
)
LICENCE_NOTE = (
    "MaxQuant (and the Thermo and Bruker raw-file readers bundled inside it) is free for academic and non-profit use under "
    "its own licence (https://www.maxquant.org); locus does not ship it and the kit fetches it at run time. The scripts "
    "refuse to run it until MAXQUANT_ACCEPT_LICENSE=1 is set, meaning you have read and accept those terms. Do not push "
    "a container built from it to a public registry."
)

# MaxQuant's instrument groups, by words in the SDRF's comment[instrument]: msInstrument code (0 Orbitrap, 1 Bruker Q-TOF,
# 2 Sciex Q-TOF, 3 Agilent Q-TOF, 4 Bruker TIMS) and the peak-detection and tolerance settings MaxQuant's GUI fills in
# when that group is chosen. Anything unmatched is treated as an Orbitrap and listed under "check" in the README.
INSTRUMENTS = [(re.compile(r"tims", re.I), "Bruker TIMS"), (re.compile(r"impact|maxis|compact|bruker", re.I), "Bruker Q-TOF"),
               (re.compile(r"triple ?tof|zeno ?tof|x500|sciex|ab sciex", re.I), "Sciex Q-TOF"), (re.compile(r"agilent", re.I), "Agilent Q-TOF")]
_TOF = {"maxCharge": "4", "minPeakLen": "3", "diaMinPeakLen": "2", "useMs1Centroids": "True", "useMs2Centroids": "True", "intensityDetermination": "3",
        "centroidMatchTol": "10", "valleyFactor": "1.2", "advancedPeakSplitting": "True", "intensityThresholdMs1": "30", "intensityThresholdMs2": "30"}
PROFILES = {  # MaxQuant 2.x defaults per group (czbiohub-sf/mspipelines settings/ms_instrument.tsv; a timsTOF mqpar saved by 2.0.3.1)
    "Orbitrap": (0, {"maxCharge": "7"}),
    "Bruker Q-TOF": (1, _TOF),
    "Sciex Q-TOF": (2, _TOF | {"minPeakLen": "2", "useMs1Centroids": "False", "useMs2Centroids": "False", "intensityThresholdMs1": "100", "intensityThresholdMs2": "20"}),
    "Agilent Q-TOF": (3, _TOF | {"intensityThresholdMs1": "0", "intensityThresholdMs2": "0"}),
    "Bruker TIMS": (4, _TOF | {"minPeakLen": "2", "useMs1Centroids": "False", "useMs2Centroids": "False"}),
}
TOF_TOLERANCES = {"mainSearchTol": "10", "isotopeMatchTol": "0.005", "isotopeMatchTolInPpm": "False", "checkMassDeficit": "False",
                  "intensityDependentCalibration": "True", "minScoreForCalibration": "40"}

# SDRF cleavage agent names (PSI-MS) to MaxQuant enzyme names.
ENZYMES = {"trypsin": "Trypsin/P", "trypsin/p": "Trypsin/P", "lys-c": "LysC", "lysc": "LysC", "chymotrypsin": "Chymotrypsin+",
           "glu-c": "GluC", "gluc": "GluC", "asp-n": "AspN", "aspn": "AspN", "arg-c": "ArgC", "argc": "ArgC",
           "lys-n": "LysN", "pepsina": "PepsinA", "unspecific cleavage": None, "no cleavage": None}

# UniProt reference proteomes for the organisms that cover most of PRIDE; others are looked up by download_fasta.sh.
PROTEOMES = {"homo sapiens": "UP000005640", "mus musculus": "UP000000589", "rattus norvegicus": "UP000002494",
             "saccharomyces cerevisiae": "UP000002311", "escherichia coli": "UP000000625", "arabidopsis thaliana": "UP000006548",
             "drosophila melanogaster": "UP000000803", "caenorhabditis elegans": "UP000001940", "danio rerio": "UP000000437",
             "bos taurus": "UP000009136", "sus scrofa": "UP000008227", "gallus gallus": "UP000000539",
             "pectobacterium carotovorum": "UP000032257", "enterococcus faecalis": "UP000001415"}

# Reporter channels per isobaric reagent, in MaxQuant's naming: "<plex>-Lys<channel>" and "<plex>-Nter<channel>".
PLEXES = {
    "TMT6plex": ["126", "127", "128", "129", "130", "131"],
    "TMT10plex": ["126C", "127N", "127C", "128N", "128C", "129N", "129C", "130N", "130C", "131N"],
    "TMT11plex": ["126C", "127N", "127C", "128N", "128C", "129N", "129C", "130N", "130C", "131N", "131C"],
    "TMTpro16plex": ["126C", "127N", "127C", "128N", "128C", "129N", "129C", "130N", "130C", "131N", "131C", "132N", "132C", "133N", "133C", "134N"],
    "TMTpro18plex": ["126C", "127N", "127C", "128N", "128C", "129N", "129C", "130N", "130C", "131N", "131C", "132N", "132C", "133N", "133C", "134N", "134C", "135N"],
    "iTRAQ4plex": ["114", "115", "116", "117"],
    "iTRAQ8plex": ["113", "114", "115", "116", "117", "118", "119", "121"],
}
SILAC = {"light": "", "medium": "Arg6;Lys4", "heavy": "Arg10;Lys8"}

# The MaxQuant mqpar contract, from PRIDE Map's tests/test_mqpar_contract.py. Each row is a run that failed late.
MSMS_PARAMS = [  # name, match tol, in ppm, deisotope tol, in ppm, de-novo tol, in ppm, deisotope, topx
    ("FTMS", "20", "True", "7", "True", "25", "True", "True", "12"),
    ("ITMS", "0.5", "False", "0.15", "False", "0.5", "False", "False", "8"),
    ("TOF", "40", "True", "0.01", "False", "25", "True", "True", "10"),
    ("Unknown", "20", "True", "7", "True", "25", "True", "True", "12"),
]
FRAGMENTATION_TYPES = ["CID", "HCD", "ETD", "PQD", "ETHCD", "ETCID", "UVPD", "Unknown"]
RESTRICT_MODS = ["Oxidation (M)", "Acetyl (Protein N-term)"]
EMPTY_GROUP_LISTS = ["additionalVariableModifications", "additionalVariableModificationProteins", "crosslinkModifications",
                     "crosslinkSites", "crosslinkNetworkFiles", "diaLibraryPaths", "diaMsmsPaths", "diaPeptidePaths", "diaEvidencePaths"]
ABSENT = ["referenceChannel", "parameterGroups/parameterGroup/enzymesFirstSearch", "parameterGroups/parameterGroup/variableModificationsFirstSearch"]
PER_RUN = ["filePaths", "experiments", "fractions", "ptms", "paramGroupIndices"]


@dataclass
class Run:
    file: str
    experiment: str
    fraction: int
    channels: list[str] = field(default_factory=list)  # reporter channels seen for this file, e.g. ["126", "127"]


@dataclass
class Design:
    accession: str
    runs: list[Run]
    labelling: str  # "label free", a PLEXES key, or "SILAC"
    channels: list[str]  # isobaric channels, or SILAC states (light/medium/heavy), in MaxQuant order
    instrument: str
    ms_instrument: int
    organism: str
    enzymes: list[str]
    unspecific: bool
    fixed: list[str]
    variable: list[str]
    checks: list[str]  # values the user must confirm by hand before running

    @property
    def fractionated(self) -> bool:
        return any(r.fraction != NO_FRACTION for r in self.runs)


class NoSdrf(LookupError):
    """The project has no SDRF, so the kit cannot know its runs, labels and fractions; nothing is guessed."""


def read_sdrf(path: Path) -> dict:
    """Columns (lower-cased) and raw rows. Unlike sdrf.parse this keeps the full `NT=...;AC=...;TA=...` cells, which the
    modification and label mappings need."""
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle, delimiter="\t")
        columns = [c.strip().lower() for c in next(reader)]
        rows = [[cell.strip() for cell in (row + [""] * len(columns))[:len(columns)]] for row in reader if any(cell.strip() for cell in row)]
    return {"columns": columns, "rows": rows}


def sdrf_table(accession: str) -> dict:
    path = sdrf.sdrf_path(accession) or sdrf.pride_sdrf(accession)
    if not path:
        raise NoSdrf(f"{accession} has no SDRF: none in the curated corpus and none listed in PRIDE. The kit takes its raw file "
                     "list, labelling, fractions, instrument and modifications from the SDRF, so without one it would be a guess; "
                     "write an SDRF for the project first (https://github.com/bigbio/proteomics-sample-metadata).")
    return read_sdrf(path)


def _nt(cell: str) -> str:
    """The NT= name of a CV cell, else the cell; missing markers reduce to ''."""
    if match := re.search(r"(?:^|;)\s*NT=([^;]*)", cell):
        cell = match.group(1).strip()
    return "" if cell.lower() in MISSING else cell


def _keys(cell: str) -> dict[str, str]:
    return {k.strip().upper(): v.strip() for k, _, v in (part.partition("=") for part in cell.split(";")) if k.strip()}


def _cells(table: dict, name: str) -> list[list[str]]:
    """Per row, the values of every column with this name (SDRF repeats column names for multi-valued fields)."""
    idx = [i for i, c in enumerate(table["columns"]) if c == name]
    return [[row[i] for i in idx] for row in table["rows"]]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "sample"


def _stem(name: str) -> str:
    return re.sub(r"\.(raw|d|wiff|wiff2|mzml|mzxml|baf|tdf)(\.gz|\.zip|\.tar(\.gz)?)?$", "", Path(name).name, flags=re.I)


def modification_name(cell: str) -> str | None:
    """A MaxQuant modification name from an SDRF `comment[modification parameters]` cell, e.g.
    `NT=Oxidation;AC=UNIMOD:35;TA=M;MT=Variable` -> `Oxidation (M)`. None for an empty cell."""
    keys = _keys(cell)
    name = keys.get("NT", "")
    if not name or name.lower() in MISSING:
        return None
    targets = re.sub(r"[,\s]", "", keys.get("TA", ""))
    position = keys.get("PP", "")
    if name.lower() == "deamidated":
        name = "Deamidation"
    if name.lower().startswith("gln->pyro-glu"):
        return "Gln->pyro-Glu"
    if name.lower().startswith("glu->pyro-glu"):
        return "Glu->pyro-Glu"
    if name.upper() == "GG":
        name = "GlyGly"
    if position and position.lower() not in ("anywhere", "any"):
        return f"{name} ({position})" if not targets or position.lower().startswith("protein") else f"{name} ({targets})"
    return f"{name} ({targets})" if targets else name


def _labelling(labels: list[str]) -> tuple[str, list[str], list[str]]:
    """(labelling, channels, checks) from the distinct comment[label] names. Refuses mixed or unknown labelling."""
    names = sorted({l for l in labels if l})
    if not names:
        raise ValueError("comment[label] is empty for every run; state the labelling in the SDRF before building a kit")
    if all(n.lower() == "label free sample" for n in names):
        return "label free", [], []
    if any(n.lower() == "label free sample" for n in names):
        raise ValueError(f"runs disagree on labelling ({', '.join(names)}); build the kit from an SDRF that covers one labelling")
    channel = re.compile(r"^(TMT|iTRAQ)\s*(\d{3}[NC]?)$", re.I)
    if channels := [m.group(2).upper() for n in names if (m := channel.match(n))]:
        reagent = "TMT" if names[0].upper().startswith("TMT") else "iTRAQ"
        suffixed = any(c[-1] in "NC" for c in channels)
        for plex, known in PLEXES.items():
            if plex.startswith(reagent) and all(c in known for c in channels) and (not plex.startswith("TMT") or suffixed == (plex != "TMT6plex")):
                return plex, [c for c in known if c in channels], []
        raise ValueError(f"reporter channels {channels} fit no {reagent} reagent MaxQuant knows ({', '.join(p for p in PLEXES if p.startswith(reagent))})")
    if len(names) == 1 and (plex := next((p for p in PLEXES if p.lower().replace("pro", "") == names[0].lower().replace("pro", "").replace(" ", "")), None)):
        return plex, PLEXES[plex], [f"the SDRF names the reagent ({names[0]}) but not the channels used; all {len(PLEXES[plex])} are listed"]
    if all("silac" in n.lower() or n.lower() in SILAC for n in names):
        states = [s for s in SILAC if any(s in n.lower() for n in names)]
        if len(states) == len(names):
            return "SILAC", states, ["SILAC labels assumed as " + ", ".join(f"{s}: {SILAC[s] or 'none'}" for s in states) + "; the SDRF does not name the amino acids"]
    raise ValueError(f"labelling {', '.join(names)} is not one the kit can map (label free, TMT, iTRAQ or SILAC); set it in MaxQuant by hand")


def design_of(accession: str, table: dict) -> Design:
    """The search design the SDRF states: one Run per data file, the labelling, instrument, organism, enzymes and
    modifications. Raises ValueError when the SDRF lacks the data-file column or states a labelling the kit cannot map."""
    cols = table["columns"]
    if "comment[data file]" not in cols:
        raise ValueError(f"{accession}: the SDRF has no comment[data file] column, so the runs are unknown")
    files = [c[0] for c in _cells(table, "comment[data file]")]
    sources = [c[0] for c in _cells(table, "source name")] if "source name" in cols else [""] * len(files)
    labels = [_nt(c[0]) for c in _cells(table, "comment[label]")] if "comment[label]" in cols else [""] * len(files)
    fractions = [c[0] for c in _cells(table, "comment[fraction identifier]")] if "comment[fraction identifier]" in cols else [""] * len(files)
    labelling, channels, checks = _labelling(labels)

    # One Run per data file; a multiplexed file has one SDRF row per channel, and its rows together are one "mixture".
    by_file: dict[str, dict] = {}
    for file, source, label, fraction in zip(files, sources, labels, fractions):
        name = Path(file.strip()).name
        if not name or name.lower() in MISSING:
            continue
        entry = by_file.setdefault(name, {"sources": [], "channels": [], "fraction": fraction})
        entry["sources"].append(source)
        if labelling in PLEXES and (m := re.search(r"(\d{3}[NC]?)$", label)):
            entry["channels"].append(m.group(1).upper())
    if not by_file:
        raise ValueError(f"{accession}: comment[data file] names no raw files")
    mixtures: dict[tuple, str] = {}
    runs = []
    for name, entry in by_file.items():
        distinct = sorted(set(entry["sources"]))
        if len(distinct) == 1 and distinct[0]:
            experiment = _slug(distinct[0])
        else:
            experiment = mixtures.setdefault(tuple(distinct), f"mixture{len(mixtures) + 1}")
        runs.append(Run(name, experiment, _fraction(entry["fraction"]), [c for c in PLEXES.get(labelling, []) if c in entry["channels"]]))
    # A dataset with one fraction per experiment is not fractionated: MaxQuant wants 32767 then, not 1.
    if all(r.fraction == 1 for r in runs) or len({(r.experiment, r.fraction) for r in runs}) == len({r.experiment for r in runs}):
        for r in runs:
            r.fraction = NO_FRACTION

    instrument = next((n for c in _cells(table, "comment[instrument]") for n in [_nt(c[0])] if n), "") if "comment[instrument]" in cols else ""
    instrument_group = next((group for pattern, group in INSTRUMENTS if pattern.search(instrument)), "Orbitrap")
    ms_instrument = PROFILES[instrument_group][0]
    if not instrument:
        checks.append("comment[instrument] is empty; msInstrument is set to Orbitrap (0)")
    elif instrument_group == "Orbitrap" and not re.search(r"orbitrap|exactive|q ?exactive|fusion|lumos|eclipse|astral|exploris|ltq|velos", instrument, re.I):
        checks.append(f"instrument '{instrument}' is not a known Orbitrap; msInstrument is set to Orbitrap (0)")
    elif instrument_group != "Orbitrap":
        checks.append(f"{instrument_group} settings are MaxQuant's defaults for that instrument group; open mqpar.xml in the MaxQuant GUI once to confirm them")
    organism = next((c[0] for c in _cells(table, "characteristics[organism]") if c[0].lower() not in MISSING), "") if "characteristics[organism]" in cols else ""
    if not organism:
        checks.append("characteristics[organism] is empty; download_fasta.sh needs an organism or a FASTA placed by hand")

    enzymes, unspecific = [], False
    for cell in (_cells(table, "comment[cleavage agent details]")[0] if "comment[cleavage agent details]" in cols else []):
        name = _nt(cell)
        if not name:
            continue
        if name.lower() not in ENZYMES:
            checks.append(f"cleavage agent '{name}' is not in the kit's table; passed to MaxQuant as written")
            enzymes.append(name)
        elif ENZYMES[name.lower()] is None:
            unspecific = True
        else:
            enzymes.append(ENZYMES[name.lower()])
    if not enzymes and not unspecific:
        enzymes, note = ["Trypsin/P"], "comment[cleavage agent details] is empty; Trypsin/P assumed"
        checks.append(note)

    fixed, variable = [], []
    for cell in (_cells(table, "comment[modification parameters]")[0] if "comment[modification parameters]" in cols else []):
        name = modification_name(cell)
        if not name or (labelling in PLEXES and re.match(r"TMT|iTRAQ", name, re.I)):
            continue  # reporter labels are declared through isobaricLabels, not as modifications
        (fixed if _keys(cell).get("MT", "").lower() == "fixed" else variable).append(name)
    if not fixed and not variable:
        fixed, variable = ["Carbamidomethyl (C)"], ["Oxidation (M)", "Acetyl (Protein N-term)"]
        checks.append("comment[modification parameters] is empty; Carbamidomethyl (C) fixed and Oxidation (M), Acetyl (Protein N-term) variable assumed")
    return Design(accession, runs, labelling, channels, instrument, ms_instrument, organism, enzymes, unspecific,
                  list(dict.fromkeys(fixed)), list(dict.fromkeys(variable)), checks)


def _fraction(text: str) -> int:
    try:
        return int(float(text))
    except ValueError:
        return 1


def fasta_path(design: Design) -> str:
    return f"fasta/{_slug(design.organism) if design.organism else 'REPLACE_WITH_LOCAL'}.fasta"


def mqpar_xml(design: Design) -> str:
    """The MaxQuant 2.0.3 parameter file for this design, honouring the contract in validate_mqpar."""
    root = ET.Element("MaxQuantParams", {"xmlns:xsd": "http://www.w3.org/2001/XMLSchema", "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    fasta = ET.SubElement(ET.SubElement(root, "fastaFiles"), "FastaFileInfo")
    _text(fasta, "fastaFilePath", f"{KIT_DIR}/{fasta_path(design)}")
    _text(fasta, "identifierParseRule", ">.*\\|(.*)\\|")
    _text(fasta, "descriptionParseRule", ">(.*)")
    for tag in ("taxonomyParseRule", "variationParseRule", "modificationParseRule", "taxonomyId"):
        _text(fasta, tag, "")
    for tag in ("fastaFilesProteogenomics", "fastaFilesFirstSearch", "fixedSearchFolder"):
        ET.SubElement(root, tag)
    # MaxQuant creates combined/ inside this folder; run_maxquant.sh and the Slurm script look for it at the kit root.
    _text(root, "fixedCombinedFolder", KIT_DIR)
    _text(root, "includeContaminants", "True")
    _text(root, "maxQuantVersion", MAXQUANT_VERSION)
    _text(root, "numThreads", str(THREADS))
    _text(root, "useDotNetCore", "True")  # without it the Linux worker launch wraps the path in quotes and fails with ENOENT
    _list(root, "filePaths", [f"{KIT_DIR}/raw/{r.file}" for r in design.runs])
    _list(root, "experiments", [r.experiment for r in design.runs])
    _list(root, "fractions", [str(r.fraction) for r in design.runs], "short")
    _list(root, "ptms", ["False"] * len(design.runs), "boolean")
    _list(root, "paramGroupIndices", ["0"] * len(design.runs), "int")
    group = ET.SubElement(ET.SubElement(root, "parameterGroups"), "parameterGroup")
    _text(group, "msInstrument", str(design.ms_instrument))
    tof = design.ms_instrument != 0
    for tag, value in next(p for code, p in PROFILES.values() if code == design.ms_instrument).items():
        _text(group, tag, value)
    isobaric, silac = design.labelling in PLEXES, design.labelling == "SILAC"
    _text(group, "lcmsRunType", "Reporter ion MS2" if isobaric else "TIMS-DDA" if design.ms_instrument == 4 else "Standard")
    for tag, value in (TOF_TOLERANCES.items() if tof else ()):
        _text(group, tag, value)
    _text(group, "lfqMode", "1" if design.labelling == "label free" else "0")
    _text(group, "matchBetweenRuns", "True" if design.labelling == "label free" else "False")
    # Labelling is never omitted: GetLmods() dereferences these even for label-free, and labelMods must hold exactly
    # <multiplicity> entries (one empty string when there is no label).
    multiplicity = len(design.channels) if silac else 1
    _text(group, "multiplicity", str(multiplicity))
    _text(group, "maxLabeledAa", "3" if silac else "0")
    _list(group, "labelMods", [SILAC[s] for s in design.channels] if silac else [""])
    _text(group, "enzymeMode", "4" if design.unspecific else "0")  # 0 specific, 4 unspecific
    _list(group, "enzymes", design.enzymes)
    _text(group, "maxMissedCleavages", "2")
    _list(group, "variableModifications", design.variable)
    _list(group, "fixedModifications", design.fixed)
    labels = ET.SubElement(group, "isobaricLabels")
    for channel in (design.channels if isobaric else []):
        info = ET.SubElement(labels, "IsobaricLabelInfo")
        _text(info, "internalLabel", f"{design.labelling}-Lys{channel}")
        _text(info, "terminalLabel", f"{design.labelling}-Nter{channel}")
        for tag in ("correctionFactorM2", "correctionFactorM1", "correctionFactorP1", "correctionFactorP2"):
            _text(info, tag, "0")
        _text(info, "tmtLike", "True" if design.labelling.startswith("TMT") else "False")
    if isobaric:
        _text(group, "reporterMassTolerance", "0.003")
        _text(group, "reporterPif", "0.75")
        _text(group, "filterPif", "False")
        _text(group, "reporterFraction", "0")
        _text(group, "reporterBasePeakRatio", "0")
    for tag in EMPTY_GROUP_LISTS:
        ET.SubElement(group, tag)
    params = ET.SubElement(root, "msmsParamsArray")
    for name, match, match_ppm, deiso, deiso_ppm, denovo, denovo_ppm, deisotope, topx in MSMS_PARAMS:
        p = ET.SubElement(params, "msmsParams")
        for tag, value in (("Name", name), ("MatchTolerance", match), ("MatchToleranceInPpm", match_ppm), ("DeisotopeTolerance", deiso),
                           ("DeisotopeToleranceInPpm", deiso_ppm), ("DeNovoTolerance", denovo), ("DeNovoToleranceInPpm", denovo_ppm),
                           ("Deisotope", deisotope), ("Topx", topx), ("TopxInterval", "100"), ("HigherCharges", "True"), ("IncludeWater", "True"),
                           ("IncludeAmmonia", "True"), ("DependentLosses", "True"), ("Recalibration", "False")):
            _text(p, tag, value)
    frags = ET.SubElement(root, "fragmentationParamsArray")
    for name in FRAGMENTATION_TYPES:
        f = ET.SubElement(frags, "fragmentationParams")
        for tag, value in (("Name", name), ("Connected", "False"), ("ConnectedScore0", "1"), ("ConnectedScore1", "1"), ("ConnectedScore2", "1"),
                           ("InternalFragments", "False"), ("InternalFragmentWeight", "1"), ("InternalFragmentAas", "KRH")):
            _text(f, tag, value)
    _text(root, "restrictProteinQuantification", "True")
    _list(root, "restrictMods", RESTRICT_MODS)
    ET.SubElement(root, "massDifferenceMods")
    # referenceChannel, enzymesFirstSearch and variableModificationsFirstSearch are deliberately absent: see validate_mqpar.
    _text(root, "peptideFdr", "0.01")
    _text(root, "proteinFdr", "0.01")
    _text(root, "minPepLen", "7")
    _text(root, "writeMzTab", "True")
    ET.indent(root, space="   ")
    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="utf-8"?>\n<!-- Generated by locus for {design.accession} from its SDRF. Check every value before running. -->\n{body}\n'


def _text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = value
    return el


def _list(parent: ET.Element, tag: str, items: list[str], item_tag: str = "string") -> ET.Element:
    el = ET.SubElement(parent, tag)
    for item in items:
        _text(el, item_tag, item)
    return el


def _children(parent: ET.Element | None, tag: str) -> list[ET.Element]:
    el = parent.find(tag) if parent is not None else None
    return list(el) if el is not None else []


def validate_mqpar(xml: str) -> list[str]:
    """Problems with an mqpar.xml against the contract MaxQuant 2.0.3 enforces at run time (PRIDE Map's
    test_mqpar_contract.py, each row a run that died 10 to 37 minutes in). Empty when the file satisfies it."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        return [f"not well-formed XML: {error}"]
    problems = []
    group = root.find("parameterGroups/parameterGroup")
    if group is None:
        return ["parameterGroups/parameterGroup is absent"]
    for tag in ("multiplicity", "maxLabeledAa", "labelMods", "enzymes", "variableModifications", "fixedModifications", "isobaricLabels", *EMPTY_GROUP_LISTS):
        if group.find(tag) is None:
            problems.append(f"parameterGroup/{tag} is absent (GetLmods or ToModifications dereferences it, job 7 or 19)")
    multiplicity = group.findtext("multiplicity")
    if multiplicity and group.find("labelMods") is not None and len(_children(group, "labelMods")) != int(multiplicity):
        problems.append(f"labelMods has {len(_children(group, 'labelMods'))} entries but multiplicity is {multiplicity} (index out of bounds, job 8)")
    if group.findtext("lcmsRunType") == "Reporter ion MS2" and not _children(group, "isobaricLabels"):
        problems.append("lcmsRunType is Reporter ion MS2 but isobaricLabels is empty")
    analysers = [e.findtext("Name") for e in _children(root, "msmsParamsArray")]
    if analysers != [p[0] for p in MSMS_PARAMS]:
        problems.append(f"msmsParamsArray must list {[p[0] for p in MSMS_PARAMS]}, has {analysers} (key 'FTMS' not present, job 8)")
    types = [e.findtext("Name") for e in _children(root, "fragmentationParamsArray")]
    if types != FRAGMENTATION_TYPES:
        problems.append(f"fragmentationParamsArray must list {FRAGMENTATION_TYPES}, has {types}")
    mods = [e.text for e in _children(root, "restrictMods")]
    if mods != RESTRICT_MODS:
        problems.append(f"restrictMods must be MaxQuant's default {RESTRICT_MODS}, is {mods} (NullReferenceException job 19, or silently different quantification)")
    for path in ABSENT:
        if root.find(path) is not None:
            problems.append(f"{path} must be absent, not present-and-empty (IndexOutOfRangeException at job 48)")
    counts = {tag: len(_children(root, tag)) for tag in PER_RUN}
    if len(set(counts.values())) != 1 or not counts["filePaths"]:
        problems.append(f"per-run arrays are not parallel or are empty: {counts}")
    for p in [e.text or "" for e in _children(root, "filePaths")] + [root.findtext(".//fastaFilePath") or ""]:
        if not p.startswith(f"{KIT_DIR}/"):
            problems.append(f"path is not kit-relative: {p}")
    if root.findtext("useDotNetCore") != "True":
        problems.append("useDotNetCore must be True (worker launch ENOENT on Linux)")
    return problems


def mqpar_fields(xml: str) -> dict[str, str]:
    """Flat field -> value view of an mqpar.xml for diffing: scalars by path, lists joined, per-run arrays as their
    distinct values plus a `runs` count, isobaric channels as one line. The two lookup tables MaxQuant indexes by name
    (msmsParamsArray, fragmentationParamsArray) are constant and left out."""
    root = ET.fromstring(xml)
    out = {"runs": str(len(_children(root, "filePaths")))}
    for el in root.iter():
        path = _path(root, el)
        if path is None or path.startswith(("msmsParamsArray", "fragmentationParamsArray", "parameterGroups/parameterGroup/isobaricLabels/")):
            continue
        if el.tag == "filePaths":
            continue
        if el.tag == "isobaricLabels":
            out[path] = ", ".join(info.findtext("internalLabel") or "" for info in el) or "(empty)"
        elif len(el) and all(child.tag in ("string", "short", "boolean", "int") for child in el):
            values = list(dict.fromkeys(c.text or "" for c in el))
            shown = ", ".join(values[:4]) + (f" … ({len(values)} distinct)" if len(values) > 4 else "")
            out[path] = shown or "(empty)"
        elif not len(el) and el.tag not in ("string", "short", "boolean", "int"):
            out[path] = el.text or "(empty)"
    return out


def _path(root: ET.Element, el: ET.Element) -> str | None:
    parents = {child: parent for parent in root.iter() for child in parent}
    parts = []
    while el is not root:
        parts.append(el.tag)
        el = parents.get(el)
        if el is None:
            return None
    return "/".join(reversed(parts))


def diff_fields(kits: dict[str, str]) -> str:
    """A table of the mqpar fields that differ between kits (accession -> mqpar.xml)."""
    fields = {acc: mqpar_fields(xml) for acc, xml in kits.items()}
    keys = sorted({k for f in fields.values() for k in f})
    rows = [(k, [fields[a].get(k, "(absent)") for a in kits]) for k in keys]
    rows = [(k, v) for k, v in rows if len(set(v)) > 1]
    width = max(len(k) for k, _ in rows) if rows else 10
    lines = [f"{'field':<{width}}  " + "  |  ".join(kits), "-" * (width + 2 + 5 * len(kits) + sum(len(a) for a in kits))]
    lines += [f"{k:<{width}}  " + "  |  ".join(v) for k, v in rows]
    lines.append(f"{len(rows)} fields differ; {len(keys) - len(rows)} are the same")
    return "\n".join(lines)


def raw_files(accession: str) -> list[dict]:
    """PRIDE's RAW listing for the project: name, bytes, https URL and checksum (often blank in PRIDE)."""
    sources.pride_files(accession)  # fills the cache
    files = json.loads((sources.PRIDE_FILES_CACHE / f"{accession}.json").read_text())
    out = []
    for f in files:
        if f["fileCategory"]["value"] != "RAW":
            continue
        ftp = next((loc["value"] for loc in f.get("publicFileLocations", []) if loc["value"].startswith("ftp://")), None)
        if ftp:
            out.append({"name": f["fileName"], "bytes": f.get("fileSizeBytes") or 0, "url": ftp.replace("ftp://", "https://", 1), "checksum": f.get("checksum") or ""})
    return out


def resources(design: Design, raw_bytes: int) -> dict:
    """Memory, CPUs, walltime and disk for the search: 16 GB and 8 threads per search; roughly 1.5 h per raw file
    (fractions and isobaric runs are quicker per file, label-free match-between-runs slower), at least 4 h, at most 7 days;
    disk for the raw files plus MaxQuant's intermediates, about 4 times the raw size (PRIDE Map measured a 15.8 GB peak for
    4 GB of raw data). Feature detection is I/O-bound: on node-local disk it ran about 6 times faster than on network storage."""
    hours = max(4, math.ceil(1.5 * len(design.runs)))
    return {"memory_gb": MIN_MEMORY_GB, "cpus": THREADS, "hours": min(hours, 7 * 24), "disk_gb": max(20, math.ceil(4 * raw_bytes / 1e9))}


def kit_files(accession: str) -> dict[str, str]:
    """Every file of the kit, by name. Raises NoSdrf without an SDRF and ValueError when the SDRF cannot be mapped."""
    design = design_of(accession, sdrf_table(accession))
    xml = mqpar_xml(design)
    if problems := validate_mqpar(xml):
        raise ValueError(f"{accession}: the generated mqpar.xml breaks the MaxQuant contract: " + "; ".join(problems))
    try:
        raw = raw_files(accession)
    except Exception:  # noqa: BLE001  PRIDE unreachable: the kit still lists the SDRF's files, without sizes or checksums
        raw = []
    by_name = {f["name"]: f for f in raw}
    # Bruker runs are .d folders, which PRIDE stores zipped: one 'X.d.zip' (or 'X.zip') per run is fetched and unpacked.
    for r in design.runs:
        if r.file.endswith(".d") and r.file not in by_name:
            packed = by_name.get(f"{r.file}.zip") or by_name.get(f"{r.file[:-2]}.zip")
            if packed:
                by_name[r.file] = packed | {"name": r.file, "zip": packed["name"]}
    listed = [by_name.get(r.file, {"name": r.file, "bytes": 0, "url": "", "checksum": ""}) for r in design.runs]
    missing = [r.file for r in design.runs if r.file not in by_name] if raw else []
    if missing and all(m.endswith(".d") for m in missing) and any(f["name"].endswith(".zip") for f in raw):
        design.checks.append(f"the SDRF names Bruker .d folders that PRIDE packs into shared zip archives "
                             f"({', '.join(f['name'] for f in raw if f['name'].endswith('.zip'))[:200]}); download and unpack them into raw/ by hand")
    # Unmatched runs (bundled archives) carry no size: size the disk from the whole RAW listing then.
    need = resources(design, sum(f["bytes"] for f in listed) or sum(f["bytes"] for f in raw))
    return {
        "mqpar.xml": xml,
        "preflight.sh": preflight_sh(accession, need),
        "download_raw.sh": download_raw_sh(accession, listed),
        "download_fasta.sh": download_fasta_sh(design),
        "run_maxquant.sh": run_maxquant_sh(accession, need),
        "run_all.sh": run_all_sh(accession),
        "submit_slurm.sh": submit_slurm_sh(accession, need),
        "README.txt": readme_txt(design, listed, missing, need),
        "LICENSE.pridemap": (Path(__file__).resolve().parents[1] / "LICENSE.pridemap").read_text(),
    }


def export_kit(accession: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in kit_files(accession).items():
            info = zipfile.ZipInfo(f"{accession}-maxquant/{name}")
            info.external_attr = (0o755 if name.endswith(".sh") else 0o644) << 16
            archive.writestr(info, text)
    return out.getvalue()


# ---- scripts. Each is resume-safe, appends a JSON line per stage to progress.jsonl, and exits on first failure.

PROGRESS = """progress() {  # progress <stage> <status> [detail]  -- one JSON line per event, for a watcher or a log
  printf '{"time":"%s","stage":"%s","status":"%s","detail":"%s"}\\n' "$(date -u +%FT%TZ)" "$1" "$2" "${3:-}" >> progress.jsonl
  printf '%s  %-12s %s %s\\n' "$(date +%T)" "$1" "$2" "${3:-}"
}"""


def preflight_sh(accession: str, need: dict) -> str:
    return f"""#!/usr/bin/env bash
# Preflight for the {accession} MaxQuant kit: lists every blocker on this machine before any download starts.
# Exit 0 when the search can run here, 1 when it cannot. Nothing is downloaded or built.
#
# {README_CAVEAT}
#
# {LICENCE_NOTE}
set -euo pipefail
cd "$(dirname "$0")"
{PROGRESS}

NEED_MEM_GB={need['memory_gb']}
NEED_DISK_GB={need['disk_gb']}
NEED_CPUS={need['cpus']}
IMAGE="{MAXQUANT_IMAGE}"
blockers=0
block() {{ printf '  BLOCKER  %s\\n' "$1"; blockers=$((blockers + 1)); }}
ok() {{ printf '  ok       %s\\n' "$1"; }}

arch="$(uname -m)"
case "$arch" in
  x86_64|amd64) ok "architecture $arch (the MaxQuant container is x86-64)" ;;
  *) block "architecture is $arch; the MaxQuant container ($IMAGE) is x86-64 only and would run under emulation, if at all. Use an x86-64 node." ;;
esac

if [ -r /proc/meminfo ]; then
  total_gb=$(awk '/MemTotal/ {{printf "%d", $2/1048576}}' /proc/meminfo)
  avail_gb=$(awk '/MemAvailable/ {{printf "%d", $2/1048576}}' /proc/meminfo)
elif command -v sysctl >/dev/null 2>&1; then
  total_gb=$(( $(sysctl -n hw.memsize) / 1073741824 )); avail_gb=$total_gb
else
  total_gb=0; avail_gb=0
fi
if [ "$avail_gb" -ge "$NEED_MEM_GB" ]; then
  ok "memory: $avail_gb GB available of $total_gb GB (needs $NEED_MEM_GB GB per search)"
else
  block "memory: $avail_gb GB available of $total_gb GB; MaxQuant needs $NEED_MEM_GB GB per search or it is killed mid-run"
fi

cpus=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
if [ "$cpus" -ge "$NEED_CPUS" ]; then ok "cpus: $cpus (mqpar.xml asks for $NEED_CPUS threads)"; else block "cpus: $cpus, fewer than the $NEED_CPUS threads in mqpar.xml; lower numThreads or use a bigger node"; fi

free_gb=$(df -Pk . | awk 'NR==2 {{printf "%d", $4/1048576}}')
if [ "$free_gb" -ge "$NEED_DISK_GB" ]; then ok "disk: $free_gb GB free here (needs about $NEED_DISK_GB GB for raw files and intermediates)"; else block "disk: $free_gb GB free here, needs about $NEED_DISK_GB GB"; fi

if [ "${{MAXQUANT_ACCEPT_LICENSE:-}}" = "1" ]; then
  ok "MaxQuant licence accepted (MAXQUANT_ACCEPT_LICENSE=1)"
else
  block "MaxQuant's licence is not accepted. Read https://www.maxquant.org (free for academic and non-profit use), then export MAXQUANT_ACCEPT_LICENSE=1"
fi

# Thermo's RawFileReader fails on a symlinked .raw with 'NoSelectedDeviceException: RunHeaderEx' and no hint why.
links=$(find raw -maxdepth 1 -type l 2>/dev/null | head -3 | tr '\n' ' ')
if [ -n "$links" ]; then block "raw/ holds symlinks ($links); MaxQuant's Thermo reader cannot open them. Copy the files in instead"; fi

if command -v MaxQuantCmd >/dev/null 2>&1 || command -v maxquant >/dev/null 2>&1; then
  ok "MaxQuant is on PATH (run_maxquant.sh will use it directly)"
elif command -v apptainer >/dev/null 2>&1 || command -v singularity >/dev/null 2>&1; then
  ok "apptainer/singularity found; run_maxquant.sh will pull $IMAGE"
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ok "docker is running; run_maxquant.sh will pull $IMAGE"
else
  block "no MaxQuant, apptainer/singularity or running docker found; on a cluster try 'module load maxquant' or 'module load apptainer'"
fi

if [ "$blockers" -eq 0 ]; then
  progress preflight ok "arch=$arch mem=${{avail_gb}}GB cpus=$cpus disk=${{free_gb}}GB"
  echo "preflight: this machine can run the search. Next: bash run_all.sh (or sbatch submit_slurm.sh on a cluster)."
else
  progress preflight blocked "$blockers blocker(s): arch=$arch mem=${{avail_gb}}GB cpus=$cpus disk=${{free_gb}}GB"
  echo "preflight: $blockers blocker(s). This machine cannot run the search; copy the kit to a cluster or x86-64 workstation that meets the requirements in README.txt."
  exit 1
fi
"""


def download_raw_sh(accession: str, files: list[dict]) -> str:
    total = sum(f["bytes"] for f in files)
    lines = [
        "#!/usr/bin/env bash",
        f"# Download the {len(files)} raw file(s) of {accession} from PRIDE into raw/" + (f" (about {total / 1e9:.1f} GB)." if total else "."),
        "# Resume-safe: a file already at its full size (and matching PRIDE's SHA-1 where PRIDE publishes one) is skipped;",
        "# a partial file is continued. Exits on the first failure.",
        "set -euo pipefail",
        'cd "$(dirname "$0")"',
        PROGRESS,
        "mkdir -p raw",
        "",
        "fetch() {  # fetch <name> <bytes> <sha1> <url>",
        '  local name="$1" bytes="$2" sha1="$3" url="$4"',
        '  if [ -z "$url" ]; then progress download failed "$name has no PRIDE URL; place it in raw/ by hand"; exit 1; fi',
        '  if [ -f "raw/$name" ] && [ -n "$bytes" ] && [ "$(wc -c < "raw/$name" | tr -d " ")" = "$bytes" ]; then',
        '    if [ -n "$sha1" ] && command -v sha1sum >/dev/null 2>&1 && [ "$(sha1sum "raw/$name" | cut -d" " -f1)" != "$sha1" ]; then',
        '      progress download retry "$name is complete but its SHA-1 differs from PRIDE; re-downloading"; rm -f "raw/$name"',
        "    else",
        '      progress download skip "$name already downloaded"; return',
        "    fi",
        "  fi",
        '  progress download start "$name"',
        '  curl -fL --retry 5 --retry-delay 10 -C - -o "raw/$name" "$url"',
        '  if [ -n "$sha1" ] && command -v sha1sum >/dev/null 2>&1 && [ "$(sha1sum "raw/$name" | cut -d" " -f1)" != "$sha1" ]; then',
        '    progress download failed "$name: SHA-1 does not match PRIDE"; exit 1',
        "  fi",
        '  progress download finished "$name"',
        "}",
        "",
    ]
    if any(f.get("zip") for f in files):
        lines += [
            "unpack() {  # unpack <run.d> <zip>: a Bruker run folder PRIDE stores zipped",
            '  local name="$1" packed="$2"',
            '  if [ -d "raw/$name" ]; then return; fi',
            '  unzip -q -o "raw/$packed" -d raw/ && [ -d "raw/$name" ] || { progress download failed "raw/$packed does not hold $name"; exit 1; }',
            '  rm -f "raw/$packed"; progress download unpacked "$name"',
            "}",
            "",
        ]
    for f in files:
        if f.get("zip"):
            lines.append(f'[ -d "raw/{f["name"]}" ] || {{ fetch "{f["zip"]}" "{f["bytes"] or ""}" "{f["checksum"]}" "{f["url"]}"; unpack "{f["name"]}" "{f["zip"]}"; }}')
        else:
            lines.append(f'fetch "{f["name"]}" "{f["bytes"] or ""}" "{f["checksum"]}" "{f["url"]}"')
    lines += ["", f'progress download complete "{len(files)} file(s) in raw/"', ""]
    return "\n".join(lines)


def download_fasta_sh(design: Design) -> str:
    path, organism = fasta_path(design), design.organism
    proteome = PROTEOMES.get(organism.lower())
    lines = [
        "#!/usr/bin/env bash",
        f"# UniProt reference proteome for {organism or 'an organism the SDRF does not state'} -> {path}",
        "# MaxQuant adds its own contaminants (includeContaminants is True in mqpar.xml). Resume-safe: skipped when the file exists.",
        "set -euo pipefail",
        'cd "$(dirname "$0")"',
        PROGRESS,
        "mkdir -p fasta",
        f'if [ -s "{path}" ]; then progress fasta skip "{path} exists"; exit 0; fi',
    ]
    if not organism:
        lines += [f'progress fasta failed "the SDRF names no organism; save a FASTA as {path} by hand"', "exit 1", ""]
        return "\n".join(lines)
    if proteome:
        lines.append(f'UP="{proteome}"')
    else:
        lines += [
            "# Not in the kit's table of common organisms: ask UniProt for the reference proteome of this organism.",
            f'UP=$(curl -fsSL "https://rest.uniprot.org/proteomes/search?query=organism_name:%22{organism.replace(" ", "%20")}%22%20AND%20proteome_type:1&fields=upid&format=tsv&size=1" | sed -n 2p | tr -d "\\r")',
            f'if [ -z "$UP" ]; then progress fasta failed "UniProt lists no reference proteome for {organism}; save a FASTA as {path} by hand"; exit 1; fi',
        ]
    lines += [
        'progress fasta start "UniProt proteome $UP"',
        f'curl -fsSL --retry 5 "https://rest.uniprot.org/uniprotkb/stream?query=proteome:$UP&format=fasta&compressed=true" -o "{path}.gz"',
        f'gunzip -f "{path}.gz"',
        f'[ -s "{path}" ] || {{ progress fasta failed "{path} is empty"; exit 1; }}',
        f'progress fasta finished "$(grep -c "^>" "{path}") sequences in {path}"',
        "",
    ]
    return "\n".join(lines)


def run_maxquant_sh(accession: str, need: dict) -> str:
    return f"""#!/usr/bin/env bash
# Run MaxQuant {MAXQUANT_VERSION} on the raw files in raw/ with mqpar.xml. Resume-safe: skipped when combined/txt/proteinGroups.txt
# exists. A run that died part-way is not safely re-enterable; delete combined/ and re-run.
# Uses, in order: MaxQuantCmd on PATH (e.g. after module load maxquant), apptainer/singularity, docker. All x86-64 only.
set -euo pipefail
cd "$(dirname "$0")"
{PROGRESS}
IMAGE="{MAXQUANT_IMAGE}"
KIT="$(pwd -P)"

if [ -s combined/txt/proteinGroups.txt ]; then progress search skip "combined/txt/proteinGroups.txt exists"; exit 0; fi
# Fail closed before anything is pulled: MaxQuant's licence must be accepted by whoever runs it (see README.txt).
[ "${{MAXQUANT_ACCEPT_LICENSE:-}}" = "1" ] || {{ progress search blocked "set MAXQUANT_ACCEPT_LICENSE=1 after reading MaxQuant's licence; see README.txt"; exit 1; }}
case "$(uname -m)" in x86_64|amd64) ;; *) progress search blocked "$(uname -m) is not x86-64; see README.txt"; exit 1 ;; esac
for f in $(grep -o '__KIT_DIR__/raw/[^<]*' mqpar.xml | sed 's#__KIT_DIR__/##'); do
  [ -s "$f" ] || {{ progress search blocked "$f is missing; run download_raw.sh first"; exit 1; }}
  [ -L "$f" ] && {{ progress search blocked "$f is a symlink; MaxQuant's Thermo reader cannot open it, copy the file in"; exit 1; }}
done
[ -s "$(grep -o '__KIT_DIR__/fasta/[^<]*' mqpar.xml | sed 's#__KIT_DIR__/##')" ] || {{ progress search blocked "FASTA missing; run download_fasta.sh first"; exit 1; }}

# MaxQuant's workers resolve paths from their own working directory, so the shipped placeholder becomes this directory.
sed "s#{KIT_DIR}#$KIT#g" mqpar.xml > mqpar.local.xml
progress search start "{need['cpus']} threads, needs {need['memory_gb']} GB"
if command -v MaxQuantCmd >/dev/null 2>&1; then
  MaxQuantCmd mqpar.local.xml
elif command -v maxquant >/dev/null 2>&1; then
  maxquant mqpar.local.xml
elif command -v apptainer >/dev/null 2>&1 || command -v singularity >/dev/null 2>&1; then
  RUNNER=$(command -v apptainer || command -v singularity)
  "$RUNNER" exec --bind "$KIT:$KIT" "docker://$IMAGE" maxquant mqpar.local.xml
elif command -v docker >/dev/null 2>&1; then
  docker run --rm --platform linux/amd64 -v "$KIT:$KIT" -w "$KIT" "$IMAGE" maxquant mqpar.local.xml
else
  progress search blocked "no MaxQuant, apptainer/singularity or docker found"; exit 1
fi
[ -s combined/txt/proteinGroups.txt ] || {{ progress search failed "MaxQuant exited without writing combined/txt/proteinGroups.txt"; exit 1; }}
progress search finished "combined/txt/proteinGroups.txt, $(($(wc -l < combined/txt/proteinGroups.txt) - 1)) protein groups"
"""


def run_all_sh(accession: str) -> str:
    return f"""#!/usr/bin/env bash
# The whole {accession} kit in order: preflight, raw download, FASTA, search. Each stage is resume-safe and the run
# stops at the first failure; re-run this script to continue. Progress goes to progress.jsonl and stdout.
set -euo pipefail
cd "$(dirname "$0")"
{PROGRESS}
progress run_all start "{accession}"
bash preflight.sh
bash download_fasta.sh
bash download_raw.sh
bash run_maxquant.sh
progress run_all finished "results in combined/txt/ (proteinGroups.txt, peptides.txt, evidence.txt) and combined/txt/*.mzTab"
"""


def submit_slurm_sh(accession: str, need: dict) -> str:
    hours = need["hours"]
    return f"""#!/usr/bin/env bash
#SBATCH --job-name=mq-{accession}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={need['cpus']}
#SBATCH --mem={need['memory_gb'] * 2}G
#SBATCH --time={hours // 24}-{hours % 24:02d}:00:00
#SBATCH --output=slurm-%j.out
# Submit from inside the unpacked kit directory on an x86-64 cluster:  sbatch submit_slurm.sh
# Memory is twice the {need['memory_gb']} GB minimum for headroom; walltime is an estimate of 1.5 h per raw file, at least 4 h.
# Adjust --partition, --account and module names to your cluster. Downloads run in the job; if compute nodes have no
# internet, run download_fasta.sh and download_raw.sh on a login node first (both are resume-safe).
# Accept MaxQuant's licence before submitting (see README.txt):  export MAXQUANT_ACCEPT_LICENSE=1; sbatch submit_slurm.sh
#
# The search runs on node-local disk when the node has about {need['disk_gb']} GB free there ($TMPDIR): feature detection
# is I/O-bound and ran about 6 times faster on local disk than on network storage. Results are copied back to combined/.
set -euo pipefail
KIT="${{SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")" && pwd -P)}}"
cd "$KIT"
module load maxquant 2>/dev/null || module load apptainer 2>/dev/null || module load singularity 2>/dev/null || true
bash preflight.sh
bash download_fasta.sh
bash download_raw.sh
LOCAL="${{TMPDIR:-}}"
if [ -n "$LOCAL" ] && [ -d "$LOCAL" ] && [ ! -s combined/txt/proteinGroups.txt ] \
   && [ "$(df -Pk "$LOCAL" | awk 'NR==2 {{printf "%d", $4/1048576}}')" -ge {need['disk_gb']} ]; then
  WORK="$LOCAL/mq-{accession}"
  mkdir -p "$WORK"
  cp -r mqpar.xml run_maxquant.sh fasta "$WORK"/
  mkdir -p "$WORK/raw" && cp raw/* "$WORK/raw/"
  bash "$WORK/run_maxquant.sh"
  mkdir -p combined && cp -r "$WORK/combined/txt" combined/
  cat "$WORK/progress.jsonl" >> progress.jsonl 2>/dev/null || true
  rm -rf "$WORK"
else
  bash run_maxquant.sh
fi
"""


def readme_txt(design: Design, files: list[dict], missing: list[str], need: dict) -> str:
    total = sum(f["bytes"] for f in files)
    lines = [
        f"MaxQuant search kit for {design.accession}",
        "=" * (len(design.accession) + 25),
        "",
        README_CAVEAT,
        "",
        "Licence",
        "-------",
        LICENCE_NOTE,
        "",
        "What this kit is",
        "----------------",
        f"A MaxQuant {MAXQUANT_VERSION} parameter file (mqpar.xml) filled in from the project's SDRF, with scripts that fetch the raw files",
        "and the reference proteome and run the search. locus generated the kit and checked mqpar.xml against the contract MaxQuant",
        "enforces at run time (fields that must be present, absent, empty or sized to one another). It did not run the search.",
        "",
        "Design read from the SDRF",
        "-------------------------",
        f"  runs:          {len(design.runs)} raw file(s), {len({r.experiment for r in design.runs})} experiment(s)" + (f", {len({r.fraction for r in design.runs})} fractions" if design.fractionated else ", not fractionated"),
        f"  labelling:     {design.labelling}" + (f" ({len(design.channels)} channels: {', '.join(design.channels)})" if design.channels else ""),
        f"  instrument:    {design.instrument or 'not stated'} (msInstrument {design.ms_instrument})",
        f"  organism:      {design.organism or 'not stated'} -> {fasta_path(design)}",
        f"  enzymes:       {'unspecific' if design.unspecific else ', '.join(design.enzymes)}, 2 missed cleavages",
        f"  fixed mods:    {', '.join(design.fixed) or 'none'}",
        f"  variable mods: {', '.join(design.variable) or 'none'}",
        f"  raw data:      {total / 1e9:.1f} GB in PRIDE" if total else "  raw data:      sizes unknown (PRIDE was not reachable when the kit was built)",
        "",
        "Check before running",
        "--------------------",
    ]
    lines += [f"  - {c}" for c in design.checks] or ["  - nothing flagged; still open mqpar.xml in the MaxQuant GUI once and read it through"]
    if missing:
        lines.append(f"  - {len(missing)} file(s) named in the SDRF are not in PRIDE's RAW listing: {', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}")
    lines += [
        "",
        "Requirements",
        "------------",
        f"  x86-64 Linux; {need['memory_gb']} GB RAM per search ({need['memory_gb'] * 2} GB requested in submit_slurm.sh); {need['cpus']} CPUs;",
        f"  about {need['disk_gb']} GB disk; roughly {need['hours']} h walltime; MaxQuant on PATH, or apptainer/singularity or docker to pull",
        f"  {MAXQUANT_IMAGE}.",
        "",
        "Commands",
        "--------",
        f"  unzip {design.accession}-maxquant.zip && cd {design.accession}-maxquant",
        "  export MAXQUANT_ACCEPT_LICENSE=1   # after reading MaxQuant's licence (see above)",
        "  bash preflight.sh          # lists every blocker on this machine; exits 1 if the search cannot run here",
        "  sbatch submit_slurm.sh     # on a Slurm cluster: preflight, downloads and search as one job",
        "  bash run_all.sh            # on a workstation that passed preflight",
        "",
        "  Each script is resume-safe: re-run after an interruption and it continues. Progress is appended to progress.jsonl.",
        "  Results: combined/txt/proteinGroups.txt, peptides.txt, evidence.txt and the mzTab in combined/txt/.",
        "",
        "Files",
        "-----",
        "  mqpar.xml          MaxQuant parameters; paths carry the __KIT_DIR__ placeholder that run_maxquant.sh fills in",
        "  preflight.sh       architecture, memory, CPU, disk and MaxQuant availability checks",
        "  download_fasta.sh  UniProt reference proteome into fasta/",
        "  download_raw.sh    raw files from PRIDE into raw/, with size and SHA-1 checks where PRIDE publishes them",
        "  run_maxquant.sh    the search",
        "  run_all.sh         the four above in order, stopping at the first failure",
        "  submit_slurm.sh    Slurm job with the memory, CPUs and walltime above; searches on node-local disk when it fits",
        "",
        "Credit",
        "------",
        "The mqpar.xml contract, the shape of these scripts and the resource measurements come from PRIDE Map",
        "(github.com/FlynnLachendro/pridemap),",
        "MIT licence, copyright Flynn Lachendro, Charlotte Ellison, Juri Westendorf, Ahmed Dawoud; see LICENSE.pridemap.",
        "Re-implemented in locus (github.com/UoSDDNB/omics-agent).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """`python -m omics_agent.maxquant PXD... [PXD...] --out DIR` writes one kit directory per project, prints the design
    summary and validator result for each, and the field diff when more than one is given."""
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("kits")
    accessions = [a for a in argv if a.startswith("PXD")]
    if not accessions:
        print("usage: python -m omics_agent.maxquant PXD000159 [PXD000001 ...] [--out DIR]", file=sys.stderr)
        return 2
    kits = {}
    for accession in accessions:
        try:
            files = kit_files(accession)
        except (LookupError, ValueError) as error:
            print(f"{accession}: refused: {error}")
            continue
        folder = out / f"{accession}-maxquant"
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (folder / name).write_text(text)
            if name.endswith(".sh"):
                (folder / name).chmod(0o755)
        kits[accession] = files["mqpar.xml"]
        design = design_of(accession, sdrf_table(accession))
        print(f"{accession}: {len(design.runs)} runs, {design.labelling}, {'fractionated' if design.fractionated else 'not fractionated'}, "
              f"{design.instrument}, {design.organism}; mqpar contract: {'ok' if not validate_mqpar(kits[accession]) else validate_mqpar(kits[accession])}; written to {folder}")
    if len(kits) > 1:
        print()
        print(diff_fields(kits))
    return 0 if len(kits) == len(accessions) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
