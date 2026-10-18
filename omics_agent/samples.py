import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from .sources import ncbi_get

GEO_SAMPLES = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
GEMMA = "https://gemma.msl.ubc.ca/rest/v2/datasets"
GEMMA_SKIP = {"block", "collection of material"}
CACHE = Path.home() / ".cache" / "omics-agent" / "geo-samples"

SAMPLE_TYPES = ["patient_tissue", "patient_biofluid", "primary_cells", "cell_line", "animal_or_organoid_model", "unknown"]

LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "group_field": {
            "type": "string",
            "description": "The field whose values separate disease samples from controls, or empty if no field does",
        },
        "case_values": {"type": "array", "items": {"type": "string"}},
        "control_values": {"type": "array", "items": {"type": "string"}},
        "sample_type": {"type": "string", "enum": SAMPLE_TYPES},
        "tissue": {"type": "string"},
        "assays": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Assays the samples were profiled with, by standard name, as the records show them",
        },
        "assay_field": {
            "type": "string",
            "description": "The field whose values tell which assay each sample is, or empty if every sample has the same assay",
        },
        "assay_values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"assay": {"type": "string"}, "values": {"type": "array", "items": {"type": "string"}}},
                "required": ["assay", "values"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["group_field", "case_values", "control_values", "sample_type", "tissue"],
    "additionalProperties": False,
}


FIELD_NAMES = {"!Sample_library_strategy": "library strategy", "!Sample_molecule_ch1": "molecule", "!Sample_source_name_ch1": "source name"}
RECORD_FIELDS = {"title pattern", *FIELD_NAMES.values()}
SAMPLE_META = {
    "!Sample_platform_id": "platform",
    "!Sample_instrument_model": "instrument",
    "!Sample_library_selection": "library_selection",
    "!Sample_library_source": "library_source",
}


def geo_records(accession: str) -> list[dict]:
    """Each sample of a GEO series: its GSM and SRX accessions, full title, organism, platform, instrument, library selection
    and source, genome build, and the `fields` that labelling reads. Fields other than RECORD_FIELDS are the sample characteristics."""
    path = CACHE / f"{accession}.txt"
    if not path.exists():
        response = ncbi_get(GEO_SAMPLES, {"acc": accession, "targ": "gsm", "form": "text", "view": "brief"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text)

    records = []
    for record in path.read_text().split("^SAMPLE")[1:]:
        sample: dict = {"gsm": record.split("\n", 1)[0].strip(" ="), "title": "", "organism": "", "srx": "", "genome_build": "", **dict.fromkeys(SAMPLE_META.values(), ""), "fields": {}}
        fields = sample["fields"]
        for line in record.splitlines():
            key, _, value = line.partition(" = ")
            if key == "!Sample_title":
                sample["title"] = value
                fields["title pattern"] = re.sub(r"\d+", "#", value)
            elif key == "!Sample_organism_ch1":
                sample["organism"] = value
            elif key == "!Sample_relation" and (srx := re.search(r"\b[SED]RX\d+", value)):
                sample["srx"] = srx.group()
            elif key in SAMPLE_META:
                sample[SAMPLE_META[key]] = value
            elif key == "!Sample_data_processing" and (build := re.match(r"Genome_build:\s*(\S.*)", value)) and not sample["genome_build"]:
                sample["genome_build"] = build.group(1).strip()
            elif key in FIELD_NAMES:
                fields[FIELD_NAMES[key]] = value
            elif key == "!Sample_characteristics_ch1":
                name, sep, val = value.partition(": ")
                name = name if sep else "characteristic"
                fields[f"{name} (characteristic)" if name in RECORD_FIELDS else name] = val if sep else value
        records.append(sample)
    return records


def geo_files(accession: str) -> list[str]:
    """Download links for the processed files a GEO series offers, at series or sample level; one cached series request."""
    path = CACHE / f"{accession}.series.txt"
    if not path.exists():
        response = ncbi_get(GEO_SAMPLES, {"acc": accession, "targ": "self", "form": "text", "view": "brief"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text)
    samples = CACHE / f"{accession}.txt"
    lines = path.read_text().splitlines() + (samples.read_text().splitlines() if samples.exists() else [])
    files = (line.partition(" = ")[2] for line in lines if line.startswith(("!Series_supplementary_file", "!Sample_supplementary_file")))
    # Series-level files (often one bundle of every sample's file) come before per-sample files.
    return sorted({f.replace("ftp://", "https://", 1) for f in files if f and f != "NONE"}, key=lambda f: ("/geo/samples/" in f, f))


def geo_samples(accession: str) -> list[dict[str, str]]:
    """Each sample of a GEO series as a field-to-value map."""
    return [record["fields"] for record in geo_records(accession)]


def geo_fields(accession: str) -> dict[str, Counter]:
    """Distinct values of every sample field in a GEO series, with how many samples carry each."""
    fields: dict[str, Counter] = defaultdict(Counter)
    for sample in geo_samples(accession):
        for name, value in sample.items():
            fields[name][value] += 1
    return fields


def gemma_fields(accession: str) -> dict[str, Counter] | None:
    """Experimental factors that Gemma curators assigned to each sample, or None if Gemma has not curated the series."""
    path = CACHE / f"{accession}.gemma.json"
    if not path.exists():
        response = httpx.get(f"{GEMMA}/{accession}/samples", timeout=60)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text if response.status_code == 200 else "null")
    data = json.loads(path.read_text())
    if not data:
        return None
    fields: dict[str, Counter] = defaultdict(Counter)
    for record in data["data"]:
        sample = record["sample"]
        factors = [item for factor in sample.get("fvbasicVOs") or [] for item in factor.get("characteristics") or []]
        for prefix, items in (("curated ", factors), ("", sample.get("characteristics") or [])):
            for item in items:
                # Gemma leaves the category empty on some curated values; without a name they cannot be a field.
                if item.get("category") and item["category"] not in GEMMA_SKIP and item.get("value"):
                    fields[prefix + item["category"]][item["value"]] += 1
    return fields or None


def summarize(fields: dict[str, Counter]) -> str:
    lines = []
    for name, values in fields.items():
        shown = ", ".join(f"{v!r} ×{n}" for v, n in values.most_common(40))
        more = f" (+{len(values) - 40} more values)" if len(values) > 40 else ""
        lines.append(f"{name}: {shown}{more}")
    return "\n".join(lines)


def group_of(sample: dict[str, str], labels: dict) -> str:
    value = sample.get(labels["group_field"], "")
    case, control = value in labels["case_values"], value in labels["control_values"]
    return "mixed" if case and control else "case" if case else "control" if control else "other"


def libraries(records: list[dict[str, str]], labels: dict) -> dict[str, dict[str, int]]:
    """How many libraries of each assay fall in each group, so unmatched assays show up."""
    assay_of = {v: a["assay"] for a in labels.get("assay_values", []) for v in a["values"]}
    table: dict[str, Counter] = defaultdict(Counter)
    for sample in records:
        if assay := assay_of.get(sample.get(labels.get("assay_field", ""), "")):
            table[assay][group_of(sample, labels)] += 1
    return {assay: dict(groups) for assay, groups in table.items()}


def resolve(name: str, values: set[str], fields: dict[str, Counter]) -> str:
    """The labelled field if it exists, else the field holding most of the labelled values; the model sometimes renames fields."""
    if name in fields or not values:
        return name
    best = max(fields, key=lambda f: len(values & set(fields[f])), default="")
    return best if best and values & set(fields[best]) else name


def resolve_labels(labels: dict, fields: dict[str, Counter]) -> dict:
    return labels | {
        "group_field": resolve(labels["group_field"], set(labels["case_values"]) | set(labels["control_values"]), fields),
        "assay_field": resolve(labels.get("assay_field", ""), {v for a in labels.get("assay_values", []) for v in a["values"]}, fields),
    }


DONOR = re.compile(r"^(?:host[ _])?(?:patient|donor|subject|individual|participant)[ _-]?(?:id|number|no|code)?$", re.I)


def donors(fields: dict[str, Counter], labels: dict, records: list[dict[str, str]], total: int) -> dict | None:
    """Distinct people per group when a field names the patient or donor, so 540 single cells from 9 patients count as 9."""
    field = next((f for f in fields if DONOR.match(f.strip()) and 2 <= len(fields[f]) < total), None)
    if not field:
        return None
    people: dict[str, set] = {"case": set(), "control": set()}
    for r in records:
        if (group := group_of(r, labels)) in people and r.get(field):
            people[group].add(r[field])
    return {"case": len(people["case"]), "control": len(people["control"]), "field": field} if all(people.values()) else None


def count(fields: dict[str, Counter], labels: dict, source: str, records: list[dict[str, str]] | None = None) -> dict:
    labels = resolve_labels(labels, fields)
    values = fields.get(labels["group_field"], Counter())
    cases, controls = set(labels["case_values"]) & set(values), set(labels["control_values"]) & set(values)
    case = sum(values[v] for v in cases - controls)
    control = sum(values[v] for v in controls - cases)
    mixed = sum(values[v] for v in cases & controls)
    known = case + control + mixed > 0
    total = max(sum(c.values()) for c in fields.values())
    libs = libraries(records, labels) if records else {}
    if not libs and known and len(labels.get("assays", [])) == 1:
        libs = {labels["assays"][0]: {k: v for k, v in (("case", case), ("control", control), ("mixed", mixed)) if v}}
    return {
        "case": case if known else None,
        "control": control if known else None,
        "mixed": mixed,
        "has_control": control + mixed > 0 if known else None,
        "sample_type": labels["sample_type"],
        "tissue": labels["tissue"],
        "assays": labels.get("assays", []),
        "library": dict(fields.get("library strategy", {})),
        "libraries": libs,
        "donors": donors(fields, labels, records, total) if records and known else None,
        "source": f"{total} {source}",
    }


def label_prompt(topic: str, accession: str, fields: dict[str, Counter], summary: str = "") -> str:
    return (
        f"Research topic: {topic}\n\n"
        + (f"Series description: {summary}\n\n" if summary else "")
        + f"These are the sample fields of GEO series {accession}, with every distinct value "
        f"and how many samples carry it:\n\n{summarize(fields)}\n\n"
        "Pick the one field that separates samples with the disease or condition of the "
        "research topic (cases) from healthy or untreated comparison samples (controls). "
        "Copy every case value and every control value exactly as written above, including "
        "each variant of a pattern (for example both 'IPF_#a_RNA' and 'IPF_#b_RNA'). Leave a value out "
        "if it is neither. In 'title pattern', # stands for any number. "
        "Fields starting with 'curated' were assigned by expert curators: prefer them for the group field. "
        "'reference subject role' means a control. "
        "If no field separates them, return an empty group_field. "
        "Also say what kind of material the samples are, and the tissue. "
        "List the assays the samples were profiled with, by standard name (for example RNA-seq, Ribo-seq, ATAC-seq, CITE-seq, "
        "microarray), reading library strategy, molecule, source names, and title patterns. A library strategy of OTHER needs "
        "the other fields to name it; never guess an assay the records do not support. Library strategy is often wrong for "
        "ribosome profiling: titles or sources saying footprint, RPF or ribosome-protected mean Ribo-seq even when the "
        "strategy says RNA-Seq, and harringtonine or lactimidomycin treatment means TIS-seq, not Ribo-seq. "
        "If samples differ in assay, name the field that tells them apart as assay_field and map each of its values to "
        "its assay in assay_values, copying values exactly; leave assay_field empty if every sample has the same assay."
    )



if __name__ == "__main__":
    records = [
        {"title pattern": f"{kind} for {cond}-treated MEFs Replicate #"}
        for kind, cond in [("Footprint", "Torin1")] * 4 + [("Footprint", "vehicle")] * 4 + [("mRNA-seq", "Torin1")] * 2 + [("mRNA-seq", "vehicle")] * 2
    ]
    values = sorted({r["title pattern"] for r in records})
    labels = {
        "group_field": "title pattern",
        "case_values": [v for v in values if "Torin1" in v],
        "control_values": [v for v in values if "vehicle" in v],
        "assay_field": "title pattern",
        "assay_values": [{"assay": "Ribo-seq", "values": [v for v in values if v.startswith("Footprint")]},
                         {"assay": "RNA-seq", "values": [v for v in values if v.startswith("mRNA")]}],
    }
    assert libraries(records, labels) == {"Ribo-seq": {"case": 4, "control": 4}, "RNA-seq": {"case": 2, "control": 2}}
    fields = {"title pattern": Counter(r["title pattern"] for r in records)}
    renamed = labels | {"group_field": "title", "assay_field": "", "sample_type": "unknown", "tissue": ""}
    facts = count(fields, renamed, "test", records)
    assert (facts["case"], facts["control"]) == (6, 6), "renamed group field resolves by its values"
    assert facts["libraries"] == libraries(records, labels), "missing assay field resolves by its values"
    print("ok")
