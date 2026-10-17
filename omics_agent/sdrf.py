"""Sample-level facts for a proteomics project from its SDRF table (one row per run and label channel).

The curated tables come from the Apache-2.0 corpus bigbio/sdrf-annotated-datasets, cloned into data/sdrf/. Three grains
are kept apart: individuals (distinct `characteristics[individual]`), samples (distinct `source name`) and runs
(rows). A missing individual column gives `unknown`, never a sample count passed off as patients. Pooled, QC and
reference rows are left out of the case/control counts and reported separately. The model only chooses which field
marks case and control, through the same label prompt the GEO path uses; code counts.
"""

import csv
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from .samples import group_of

SDRF_DIR = Path(os.environ.get("OMICS_SDRF_DIR") or "data/sdrf/datasets")
PRIDE_FILES = "https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{}/files"
CACHE = Path.home() / ".cache" / "omics-agent" / "sdrf"
MISSING = {"", "not available", "not applicable", "n/a", "na", "none", "unknown", "-"}
POOLED = re.compile(r"\b(pool|pooled|reference|bridge|qc|blank|boost|carrier)\b", re.I)
KEEP_COMMENTS = {"comment[label]": "label", "comment[instrument]": "instrument", "comment[proteomics data acquisition method]": "acquisition"}


def sdrf_path(accession: str) -> Path | None:
    """The curated SDRF for a project: datasets/<acc>.sdrf.tsv, datasets/<acc>/<acc>.sdrf.tsv or the first table in that folder."""
    direct = SDRF_DIR / f"{accession}.sdrf.tsv"
    if direct.exists():
        return direct
    folder = SDRF_DIR / accession
    if (folder / f"{accession}.sdrf.tsv").exists():
        return folder / f"{accession}.sdrf.tsv"
    return next(iter(sorted(folder.glob("*.sdrf.tsv"))), None) if folder.is_dir() else None


def _value(text: str) -> str:
    """`NT=Orbitrap Fusion;AC=MS:1002416` reduces to its name; missing markers reduce to an empty string."""
    text = text.strip()
    if match := re.search(r"(?:^|;)NT=([^;]*)", text):
        text = match.group(1).strip()
    return "" if text.lower() in MISSING else text


def parse(path: Path) -> dict:
    """{"columns": [...], "rows": [[...], ...]} with duplicate column names kept in order; cells are reduced with _value."""
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle, delimiter="\t")
        columns = [c.strip().lower() for c in next(reader)]
        rows = [[_value(cell) for cell in (row + [""] * len(columns))[:len(columns)]] for row in reader if any(cell.strip() for cell in row)]
    return {"columns": columns, "rows": rows}


def pride_sdrf(accession: str) -> Path | None:
    """The SDRF the project itself lists in PRIDE (file category EXPERIMENTAL DESIGN or a name ending in .sdrf.tsv),
    downloaded once into the cache. None when the project lists none or PRIDE cannot be reached. A missing listing is
    remembered too, so a project without an SDRF costs one request, not one per search."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path, missing = CACHE / f"{accession}.sdrf.tsv", CACHE / f"{accession}.none"
    if path.exists():
        return path
    if missing.exists():
        return None
    try:
        files = httpx.get(PRIDE_FILES.format(accession), params={"pageSize": 1000}, timeout=60).raise_for_status().json()
        listed = [f for f in files if f["fileCategory"]["value"] == "EXPERIMENTAL DESIGN" or f["fileName"].lower().endswith(".sdrf.tsv")]
        # A community-annotated table comes after the authors' own; prefer the shorter, original name.
        for f in sorted(listed, key=lambda f: (len(f["fileName"]), f["fileName"])):
            url = next((loc["value"] for loc in f.get("publicFileLocations", []) if loc["value"].startswith("ftp://")), None)
            if url:
                text = httpx.get(url.replace("ftp://", "https://", 1), timeout=120, follow_redirects=True).raise_for_status().text
                if "source name" in text.split("\n", 1)[0].lower():
                    path.write_text(text)
                    return path
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    missing.write_text(json.dumps({"files": len(files), "listed": [f["fileName"] for f in listed]}))
    return None


def sdrf_for(accession: str) -> dict | None:
    """The curated corpus table first, else the SDRF the project lists in PRIDE."""
    path = sdrf_path(accession) or pride_sdrf(accession)
    return parse(path) if path else None


def column(table: dict, name: str) -> list[str] | None:
    """The first column with this name, or None when the table has no such column."""
    try:
        i = table["columns"].index(name)
    except ValueError:
        return None
    return [row[i] for row in table["rows"]]


def _field_name(column_name: str) -> str | None:
    if match := re.fullmatch(r"characteristics\[(.+)\]", column_name):
        return match.group(1)
    if match := re.fullmatch(r"factor value\[(.+)\]", column_name):
        return f"factor: {match.group(1)}"
    return KEEP_COMMENTS.get(column_name)


def samples_of(table: dict) -> list[dict[str, str]]:
    """One record per sample (distinct `source name`), with its characteristics, factor values, label and instrument,
    in the shape GEO sample records take. Values that differ between a sample's runs are joined with ' | '."""
    names = {i: name for i, c in enumerate(table["columns"]) if (name := _field_name(c))}
    source = table["columns"].index("source name") if "source name" in table["columns"] else None
    by_sample: dict[str, dict[str, set]] = {}
    for n, row in enumerate(table["rows"]):
        sample = row[source] if source is not None else f"row {n + 1}"
        fields = by_sample.setdefault(sample, defaultdict(set))
        for i, name in names.items():
            if row[i]:
                fields[name].add(row[i])
    records = []
    for sample, fields in by_sample.items():
        record = {"source name": sample, "runs": sum(1 for row in table["rows"] if source is None or row[source] == sample)}
        record.update({name: " | ".join(sorted(values)) for name, values in fields.items() if name != "runs"})
        records.append(record)
    return records


def is_pooled(record: dict[str, str]) -> bool:
    """A pooled, QC, reference, bridge or blank sample, by the pooled-sample column or by its name and sample type."""
    pooled = record.get("pooled sample", "").lower()
    if pooled in ("pooled", "yes", "true"):
        return True
    if pooled in ("not pooled", "no", "false"):
        return False
    return bool(POOLED.search(record["source name"]) or POOLED.search(record.get("sample type", "")))


def sdrf_fields(table: dict) -> dict[str, Counter]:
    """Field -> value counts over the non-pooled samples, the same shape samples.geo_fields returns, so the label
    prompt and label resolution work unchanged. Fields with one value for every sample are kept: they describe the study."""
    fields: dict[str, Counter] = defaultdict(Counter)
    for record in samples_of(table):
        if is_pooled(record):
            continue
        for name, value in record.items():
            if name not in ("source name", "runs") and value:
                fields[name][value] += 1
    return dict(fields)


FLUIDS = re.compile(r"fluid|serum|plasma|blood|urine|saliva|semen|sputum|lavage|milk|sweat|tears|csf|bile|ascites", re.I)


def material_of(fields: dict[str, Counter], organism: str) -> str | None:
    """The sample type as the table states it: a cell line column means cell_line, a biofluid material or organism
    part means patient_biofluid, other human material patient_tissue, non-human material a model. None when the table
    does not say, so the model's label stands."""
    if any(v for v in fields.get("cell line", {})):
        return "cell_line"
    if organism and "homo sapiens" not in organism.lower():
        return "animal_or_organoid_model"
    material = " ".join(fields.get("material type", {})).lower()
    part = " ".join(fields.get("organism part", {})).lower()
    if "biofluid" in material or FLUIDS.search(part):
        return "patient_biofluid"
    if material or part:
        return "patient_tissue"
    return None


def count(table: dict, labels: dict, source: str) -> dict:
    """Case and control counts at sample grain, individuals when the table names them (`None` means unknown), runs,
    the pooled samples left out, and runs per label type. Same keys as samples.count, plus grain, individuals, runs,
    excluded_pooled and labels; `libraries` and `assays` stay empty so the grading code does not read label types as assays."""
    records = samples_of(table)
    kept = [r for r in records if not is_pooled(r)]
    pooled = [r for r in records if is_pooled(r)]
    groups = {r["source name"]: group_of(r, labels) for r in kept}
    tally = Counter(groups.values())
    case, control, mixed = tally["case"], tally["control"], tally["mixed"]
    known = case + control + mixed > 0
    has_individual = "individual" in table["columns"] or "characteristics[individual]" in table["columns"]
    individuals = None
    by_group_individuals: dict[str, int] = {}
    if has_individual:
        per_group: dict[str, set] = defaultdict(set)
        for r in kept:
            if r.get("individual"):
                per_group[groups[r["source name"]]].add(r["individual"])
        individuals = len(set().union(*per_group.values())) if per_group else 0
        by_group_individuals = {g: len(v) for g, v in per_group.items() if g in ("case", "control")}
    label_runs: dict[str, Counter] = defaultdict(Counter)
    for r in kept:
        label_runs[re.sub(r"\d+[NC]?$", "", r.get("label", "")).strip() or "unlabelled"][groups[r["source name"]]] += r["runs"]
    fields = sdrf_fields(table)
    organism = " ".join(fields.get("organism", {}))
    return {
        "case": case if known else None,
        "control": control if known else None,
        "mixed": mixed,
        "has_control": control + mixed > 0 if known else None,
        "sample_type": material_of(fields, organism) or labels["sample_type"],
        "tissue": labels["tissue"],
        "assays": [],
        "library": {},
        "libraries": {},
        "grain": "samples",
        "individuals": individuals,
        "individuals_by_group": by_group_individuals,
        "runs": len(table["rows"]),
        "excluded_pooled": len(pooled),
        "labels": {k: dict(v) for k, v in label_runs.items()},
        "source": f"{len(records)} {source}",
    }


if __name__ == "__main__":
    import io
    import tempfile

    text = (
        "source name\tcharacteristics[organism]\tcharacteristics[disease]\tcharacteristics[individual]\tcharacteristics[pooled sample]\tcomment[label]\tcomment[instrument]\tcomment[data file]\n"
        "S1\tHomo sapiens\tcancer\tP1\tnot pooled\tNT=TMT126;AC=MS:1\tNT=Orbitrap;AC=MS:2\ta.raw\n"
        "S2\tHomo sapiens\tcancer\tP1\tnot pooled\tNT=TMT127N;AC=MS:1\tNT=Orbitrap;AC=MS:2\ta.raw\n"
        "S3\tHomo sapiens\tnormal\tP2\tnot pooled\tNT=TMT128N;AC=MS:1\tNT=Orbitrap;AC=MS:2\ta.raw\n"
        "S3\tHomo sapiens\tnormal\tP2\tnot pooled\tNT=TMT128N;AC=MS:1\tNT=Orbitrap;AC=MS:2\tb.raw\n"
        "Pool\tHomo sapiens\tnot applicable\tnot applicable\tpooled\tNT=TMT131;AC=MS:1\tNT=Orbitrap;AC=MS:2\ta.raw\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".sdrf.tsv", delete=False) as f:
        f.write(text)
    table = parse(Path(f.name))
    fields = sdrf_fields(table)
    assert fields["disease"] == Counter({"cancer": 2, "normal": 1}) and "Pool" not in str(fields), fields
    labels = {"group_field": "disease", "case_values": ["cancer"], "control_values": ["normal"], "sample_type": "patient_tissue", "tissue": "x"}
    facts = count(table, labels, "SDRF samples")
    assert (facts["case"], facts["control"], facts["individuals"], facts["runs"], facts["excluded_pooled"]) == (2, 1, 2, 5, 1), facts
    assert facts["individuals_by_group"] == {"case": 1, "control": 1} and facts["labels"] == {"TMT": {"case": 2, "control": 2}}, facts
    print("ok")
