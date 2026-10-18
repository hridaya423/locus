"""Which samples of a dataset match chosen levels of its factors, how many samples every level keeps, and the commands
that download only those samples' files. Levels within a factor combine with OR, factors with AND. Factors, levels and
sample rows come from `design` and `record`; no model is involved.
"""

import re
from collections import Counter
from functools import lru_cache

from . import design, record, samples, sources

WEIGHT = "No. of Samples"
GSM = re.compile(r"\bGSM\d+")
BIOPROJECT = re.compile(r"PRJ[A-Z]{2}\d+")
READ_GROUPS = ("Raw reads (FASTQ)", "Submitted files")


@lru_cache(maxsize=8)
def _prepared(accession: str) -> tuple[record.Record, dict]:
    if not (row := record._row(accession)):
        raise LookupError(f"{accession} is not in the index.")
    rec = record.raw(accession, row)
    if not rec.samples:
        raise LookupError(f"{sources.REPOSITORY_NAMES.get(rec.source, rec.source)} lists no samples for {accession}.")
    return rec, design.design(accession, row["source"]) or {}


def table(accession: str) -> dict:
    return _prepared(accession)[0].samples


def _block(title: str, name: str, urls: list[str]) -> list[str]:
    return [f"# {title}", f"cat > {name} <<'EOF'", *urls, "EOF", f"wget -c -i {name}"] if urls else []


def _sample_files(accession: str) -> dict[str, list[str]]:
    found = {}
    for block in (samples.CACHE / f"{accession}.txt").read_text().split("^SAMPLE")[1:]:
        lines = [line.partition(" = ") for line in block.splitlines()]
        found[block.split("\n", 1)[0].strip(" =")] = [record._https(v) for k, _, v in lines if k.startswith("!Sample_supplementary_file") and v != "NONE"]
    return found


def downloads(accession: str, rec: record.Record, chosen: list[list[str]]) -> dict:
    """Commands for the chosen sample rows, the note on what they leave out, and where each part was read from. Commands
    are None when the repository does not say which file belongs to which sample."""
    columns = rec.samples["columns"]
    reads: dict[str, list[str]] = {}
    for f in rec.files:
        if f["group"] in READ_GROUPS and f["kind"]:
            reads.setdefault(f["kind"], []).append(f["url"])
    parts, notes, basis = [], [], []
    if rec.source == "GEO":
        gsms = [r[0] for r in chosen]
        per_sample = _sample_files(accession)
        processed = [u for g in gsms for u in per_sample.get(g, [])]
        parts += _block(f"processed files of the {len(gsms):,} samples", "processed-urls.txt", processed)
        if not processed and any(f["processed"] for f in rec.files):
            notes.append("GEO gives the processed files for the whole series, not per sample; they are listed under Files.")
        basis.append("processed files: !Sample_supplementary_file of each sample record")
        project = next((m[0] for label, url in rec.links if label == "BioProject" and (m := BIOPROJECT.search(url))), None)
        runs = {}
        for run in record._runs(project) if project else []:
            if (gsm := GSM.search(run.get("experiment_title", ""))) and run["run_accession"] in reads:
                runs.setdefault(gsm[0], []).extend(reads[run["run_accession"]])
        parts += _block("raw reads from ENA", "reads-urls.txt", [u for g in gsms for u in runs.get(g, [])])
        if runs and (missing := sum(g not in runs for g in gsms)):
            notes.append(f"{missing:,} of the {len(gsms):,} samples have no reads in ENA.")
        elif not runs:
            notes.append("ENA holds no reads for this series.")
        basis.append(f"raw reads: ENA read_run of {project}, matched by the GSM accession in experiment_title")
    elif rec.source == "ENA":
        run_column = columns.index("Run")
        parts += _block(f"raw reads of the {len(chosen):,} runs", "reads-urls.txt", [u for r in chosen for u in reads.get(r[run_column], [])])
        basis.append("raw reads: ENA read_run files of each run in the Run column")
    else:
        notes.append(f"{sources.REPOSITORY_NAMES.get(rec.source, rec.source)} does not link samples to files.")
    commands = "\n".join([f"mkdir -p ~/omics-data/{accession}/selection && cd ~/omics-data/{accession}/selection", *parts]) if parts else None
    return {"commands": commands, "note": " ".join(notes) or None, "basis": basis}


def select(accession: str, filters: dict[str, list[str]], text: str = "") -> dict:
    """The sample rows (as indexes into the record's sample table) that match every filter and the text, the samples
    each level of every factor has within that selection, and the commands for just those samples. A factor's own
    filter is left out of its own counts, so another level of it can be added."""
    rec, built = _prepared(accession)
    factors = built.get("factors", [])
    columns, rows = rec.samples["columns"], rec.samples["rows"]
    at = {f["name"]: columns.index(f["column"]) for f in factors}
    known = {f["name"]: f["levels"] for f in factors}
    for name, levels in filters.items():
        if name not in known:
            raise ValueError(f"{accession} has no factor {name!r}; its factors are {', '.join(known) or 'none'}.")
        if unknown := [v for v in levels if v not in known[name]]:
            raise ValueError(f"{name} has no level {unknown[0]!r}; its levels are {', '.join(known[name])}.")
    chosen = {name: set(levels) for name, levels in filters.items() if levels}
    needle = text.strip().lower()
    weight = columns.index(WEIGHT) if WEIGHT in columns else None
    count = lambda r: int(r[weight]) if weight is not None and r[weight].isdigit() else 1
    keeps = lambda r, skip="": all(r[at[n]].strip() in levels for n, levels in chosen.items() if n != skip) and (not needle or any(needle in v.lower() for v in r))
    matched = [i for i, r in enumerate(rows) if keeps(r)]
    counts, unstated = {}, {}
    for f in factors:
        tally: Counter = Counter()
        for r in rows:
            if keeps(r, f["name"]):
                tally[r[at[f["name"]]].strip()] += count(r)
        counts[f["name"]] = {level: tally[level] for level in f["levels"]}
        unstated[f["name"]] = sum(n for level, n in tally.items() if level not in f["levels"])
    narrowed = bool(chosen or needle)
    found = {
        "samples": sum(count(rows[i]) for i in matched), "total": sum(count(r) for r in rows), "rows": matched, "counts": counts, "unstated": unstated,
        "downloads": (downloads(accession, rec, [rows[i] for i in matched]) if matched else {"commands": None, "note": "No samples are selected.", "basis": []}) if narrowed else None,
    }
    if crossed := built.get("crossed"):
        a, b = at[crossed["rows"]], at[crossed["columns"]]
        pairs: Counter = Counter()
        for i in matched:
            pairs[rows[i][a].strip(), rows[i][b].strip()] += count(rows[i])
        found["crossed"] = [[x, y, n] for (x, y), n in pairs.items()]
    return found


if __name__ == "__main__":
    # GEO: 540 RNA-seq samples with reads in ENA. ArrayExpress: grouped rows, so counts are weighted.
    geo = select("GSE86618", {})
    assert geo["total"] == geo["samples"] == len(geo["rows"]) == 540 and geo["downloads"] is None, geo["samples"]
    levels = design.design("GSE86618", "GEO")["factors"][0]
    assert geo["counts"][levels["name"]] == levels["levels"], (geo["counts"], levels)
    name, (first, second) = levels["name"], list(levels["levels"])[:2]
    one = select("GSE86618", {name: [first]})
    assert one["samples"] == levels["levels"][first] and one["counts"][name] == geo["counts"][name]
    assert sum(one["counts"]["patientid"].values()) == one["samples"], one["counts"]
    both = select("GSE86618", {name: [first, second]})
    assert both["samples"] == levels["levels"][first] + levels["levels"][second]
    narrow = select("GSE86618", {name: [first], "patientid": [next(p for p, n in one["counts"]["patientid"].items() if n)]})
    assert 0 < narrow["samples"] < one["samples"] and select("GSE86618", {name: [first]}, "no such text")["samples"] == 0
    assert sum(n for x, y, n in one["crossed"]) == one["samples"], one["crossed"]
    commands = one["downloads"]["commands"]
    assert commands.count("ftp.sra.ebi.ac.uk") == one["samples"] and "reads-urls.txt" in commands, one["downloads"]["note"]
    assert "whole series" in one["downloads"]["note"], one["downloads"]["note"]
    try:
        select("GSE86618", {"no such factor": ["x"]})
        raise AssertionError("an unknown factor must fail")
    except ValueError:
        pass

    assert not select("GSE86618", {name: [first]}, "no such text")["downloads"]["commands"]
    assert select("GSE86618", {name: [first]}, "no such text")["downloads"]["note"] == "No samples are selected."

    sex = next(f for f in design.design("GSE188464", "GEO")["factors"] if f["name"].lower() == "gender")
    sexes = select("GSE188464", {})
    assert sexes["unstated"][sex["name"]] == sex["unstated"] > 0, sex
    assert sum(sexes["counts"][sex["name"]].values()) + sexes["unstated"][sex["name"]] == sexes["total"] == 48, sexes["counts"]

    ae = select("E-TABM-937", {})
    built = design.design("E-TABM-937", "ArrayExpress")
    assert ae["total"] == built["samples"] == 181 and len(ae["rows"]) == 19, (ae["total"], len(ae["rows"]))
    assert all(ae["counts"][f["name"]] == f["levels"] for f in built["factors"]), ae["counts"]
    first = built["factors"][0]
    level = next(iter(first["levels"]))
    picked = select("E-TABM-937", {first["name"]: [level]})
    assert picked["samples"] == first["levels"][level] and picked["downloads"]["commands"] is None and "does not link samples" in picked["downloads"]["note"]

    ena = select("PRJEB2016", {})
    factor = design.design("PRJEB2016", "ENA")["factors"][0]
    top = next(iter(factor["levels"]))
    ena_picked = select("PRJEB2016", {factor["name"]: [top]})
    assert ena["total"] == 134 and ena_picked["samples"] == factor["levels"][top], ena_picked["samples"]
    assert ena_picked["downloads"]["commands"].count("ftp.sra.ebi.ac.uk") >= ena_picked["samples"], ena_picked["downloads"]["note"]
    print("ok")
