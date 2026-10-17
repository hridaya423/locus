"""Can two datasets be used together? Pure rules over two dataset profiles; the one judgement code cannot make
(is the contrast the same?) comes in as an argument, so nothing here calls a model or the network.

Each facet in RULES says which statuses let a dataset pair be pooled, and which let it be compared as effects.
The verdict is the first of pool and effects whose required facets are all satisfied. Below that it is no when a
required facet differs, and unclear when the only obstacles are facts the records do not state: missing evidence
is not evidence against combining.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from collections import Counter
from typing import Literal, NamedTuple

from .samples import group_of

Verdict = Literal["pool", "effects", "no", "unclear"]
Status = Literal["same", "related", "differs", "unknown"]


@dataclass(frozen=True)
class Profile:
    accession: str
    source: str
    title: str
    organism: str | None
    layer: str | None
    technology: str | None
    platform: str | None
    material: str | None
    tissue: str | None
    case: int | None
    control: int | None
    contrast: str | None  # the raw case and control labels from the records: the evidence
    build: str | None
    contrast_name: str | None = None  # a plain-language name for the contrast, for display only
    access: str | None = None  # what can be downloaded: raw reads, processed files, or controlled access
    sex: str | None = None  # share of women in each group, when the sample records state sex
    sex_split: dict[str, dict[str, int]] | None = None  # women and men per group, for display
    files: tuple[str, ...] = ()  # download links for the processed files
    shared: int | None = None  # samples that also appear in the other dataset; None when not checked


@dataclass(frozen=True)
class Facet:
    key: str
    label: str
    a: str | None
    b: str | None
    status: Status
    note: str
    source: str
    required: bool


@dataclass(frozen=True)
class Comparison:
    a: Profile
    b: Profile
    verdict: Verdict
    reason: str
    facets: list[Facet]
    steps: list[str]


# The first row that matches an assay name decides its layer and technology. A dataset with several assays has
# several layers (ribosome profiling with matched RNA-seq holds a translatome and a transcriptome). None means not
# stated.
ASSAYS = (
    (r"tis-?seq|translation initiation", "translatome", "TIS-seq"),
    (r"ribo|footprint", "translatome", "Ribo-seq"),
    (r"single.?cell.*atac|sc-?atac", "epigenome", "single-cell ATAC-seq"),
    (r"atac", "epigenome", "ATAC-seq"),
    (r"chip-?seq", "epigenome", "ChIP-seq"),
    (r"methyl|bisulfite|binding/occupancy", "epigenome", None),
    (r"single.?cell|sc-?rna|sn-?rna|10x|cite-?seq", "transcriptome", "single-cell RNA-seq"),
    (r"\bdia\b|data.independent", "proteome", "DIA"),
    (r"\bdda\b|data.dependent", "proteome", "DDA"),
    (r"proteom|mass spec", "proteome", None),
    (r"metabolom", "metabolome", None),
    (r"variation|snp|genotyp|wgs|exome|whole.genome", "genome", None),
    (r"micro-?array|by array|tiling array", "transcriptome", "microarray"),
    (r"rna-?seq", "transcriptome", "RNA-seq"),
    (r"(expression|rna) profiling|transcription profiling", "transcriptome", None),
)


def _assay(names: list[str]) -> tuple[str | None, str | None]:
    hits = [h for name in names if (h := next(((i, layer, tech) for i, (p, layer, tech) in enumerate(ASSAYS) if re.search(p, name, re.I)), None))]
    hits.sort(key=lambda h: h[0])
    join = lambda values: " + ".join(dict.fromkeys(v for v in values if v)) or None
    return join(layer for _, layer, _ in hits), join(tech for _, _, tech in hits)


def _joined(values: set[str]) -> str | None:
    return "; ".join(sorted(values - {""})) or None


CONTROLLED = {"EGA", "dbGaP"}
SEX = {"f": "female", "female": "female", "woman": "female", "women": "female", "m": "male", "male": "male", "man": "male", "men": "male"}


def _access(source: str, records: list[dict], files: list[str] | None) -> str | None:
    if source in CONTROLLED:
        return "controlled access"
    if not records:
        return None
    parts = [*(["raw reads"] if any(r.get("srx") for r in records) else []), *(["processed files"] if files else [])]
    return " + ".join(parts) or "none listed"


def _sex_split(records: list[dict], labels: dict | None) -> dict[str, dict[str, int]] | None:
    """Women and men among cases and among controls, or None unless both groups have stated sexes."""
    if not labels or not labels.get("group_field"):
        return None
    groups = {"cases": Counter(), "controls": Counter()}
    for r in records:
        fields = r.get("fields", {})
        sex = next((SEX.get(v.strip().lower()) for k, v in fields.items() if re.search(r"\b(sex|gender)\b", k, re.I)), None)
        if sex and (group := {"case": "cases", "control": "controls"}.get(group_of(fields, labels))):
            groups[group][sex] += 1
    return {g: {"female": c["female"], "male": c["male"]} for g, c in groups.items()} if all(groups.values()) else None


def _sex(split: dict[str, dict[str, int]] | None) -> str | None:
    if not split:
        return None
    return "; ".join(f"{g} {round(100 * c['female'] / (c['female'] + c['male']))}% female" for g, c in split.items())


def _balanced(a: str, b: str) -> bool:
    """Both datasets have groups within 20 percentage points of each other in their share of women."""
    shares = [[int(n) for n in re.findall(r"(\d+)%", v)] for v in (a, b)]
    return all(abs(case - control) <= 20 for case, control in shares)


def _tagged(facts: dict) -> tuple[str, str | None, str | None]:
    """Layer, technology and platform of a PRIDE dataset from its trusted method tags only."""
    stated = {f: t["label"] for f, t in facts["methods"].items() if t["trusted"]}
    technology = " ".join(stated[f] for f in ("labelling", "acquisition") if f in stated) or None
    return facts["assays"][0].split(" (")[0], technology, stated.get("instrument_family")


def build_profile(row: dict, records: list[dict], labels: dict | None, facts: dict | None, files: list[str] | None = None) -> Profile:
    """`row` is the store row (accession, source, title, organism, modality), `records` the GEO sample records,
    `labels` the case/control labelling, `facts` the counted facts and `files` the series' processed files;
    the last four are empty for non-GEO rows."""
    facts, labels = facts or {}, labels or {}
    layer, technology = _assay(facts.get("assays") or [])
    if layer is None:
        layer, technology = _assay(row["modality"].split(";"))
    platform = _joined({r["instrument"] or r["platform"] for r in records})
    if facts.get("methods"):
        layer, technology, platform = _tagged(facts)
    case, control = labels.get("case_values"), labels.get("control_values")
    known = facts.get("has_control") is not None
    return Profile(
        accession=row["accession"],
        source=row["source"],
        title=row["title"],
        organism=row["organism"] or _joined({r["organism"] for r in records}),
        layer=layer,
        technology=technology,
        platform=platform,
        material=None if facts.get("sample_type") in (None, "unknown") else facts["sample_type"].replace("_", " "),
        tissue=facts.get("tissue") or None,
        case=facts.get("case") if known else None,
        control=facts["control"] + facts["mixed"] if known else None,
        contrast=f"{'; '.join(case)} vs {'; '.join(control)}" if case and control else None,
        build=_joined({r["genome_build"] for r in records}),
        access=_access(row["source"], records, files),
        sex=_sex(split := _sex_split(records, labels)),
        sex_split=split,
        files=tuple(files or ()),
    )


class Rule(NamedTuple):
    key: str
    label: str
    read: Callable[[Profile], str | None]
    pool: tuple[Status, ...]  # statuses that satisfy pooling; empty means the facet is only a caution
    effects: tuple[Status, ...]
    differs: str  # the consequence, shown when the datasets differ
    source: str
    agree: Callable[[str, str], bool] | None = None  # both values are known; default compares them as words


BOTH = "cases and controls"


def _groups(p: Profile) -> str | None:
    if p.case is None or p.control is None:
        return None
    return BOTH if p.case and p.control else "cases only" if p.case else "controls only" if p.control else "no samples"


def _sizes(p: Profile) -> str | None:
    return None if p.case is None or p.control is None else f"{p.case} cases, {p.control} controls"


def _enough(a: str, b: str) -> bool:
    return all(int(n) >= MIN_GROUP for n in re.findall(r"\d+", f"{a} {b}"))


MIN_GROUP = 3


RULES = (
    Rule("organism", "Organism", lambda p: p.organism, ("same",), (),
         "Different organisms: genes match only through orthologs, so the samples cannot be mixed.", "repository record"),
    Rule("layer", "Molecular layer", lambda p: p.layer, ("same", "related"), ("same", "related"),
         "Different molecular layers measure different things; combining them is multi-omics integration, a different analysis.",
         "assay labels, else repository data type"),
    Rule("technology", "Technology", lambda p: p.technology, ("same", "related"), (),
         "Different technologies have different biases and scales that reprocessing cannot remove, so analyse each dataset on its own.",
         "assay labels, else repository data type"),
    Rule("groups", "Both groups in each", _groups, ("same",), ("same",),
         "A dataset without both cases and controls cannot show an effect by itself; pooled, the study and the condition would be the same variable, and no batch term can separate them.",
         "GEO sample counts", lambda a, b: a == b == BOTH),
    Rule("contrast", "Contrast", lambda p: p.contrast_name or p.contrast, ("same",), ("same", "related"),
         "", "case and control labels"),
    Rule("shared", "Shared samples", lambda p: None if p.shared is None else "none" if p.shared == 0 else f"{p.shared} in both", (), (),
         "Some samples appear in both datasets: pooled they count twice, and the two results are not independent. Remove the duplicates first.",
         "GEO sample accessions", lambda a, b: a == b == "none"),
    Rule("access", "Data available", lambda p: p.access, (), (),
         "The datasets offer different data; to pool them, start from what both have, usually the raw reads.", "GEO sample and series records"),
    Rule("platform", "Platform", lambda p: p.platform, (), (),
         "Different platforms or instruments add a batch effect; model it.", "GEO platform and instrument"),
    Rule("material", "Material", lambda p: p.material, (), (),
         "Different kinds of material (cell line, tissue, primary cells) can respond differently.", "sample type label"),
    Rule("tissue", "Tissue or cell type", lambda p: p.tissue, (), (),
         "Different tissues or cell types can respond differently; the effects may not carry over.", "tissue label"),
    Rule("build", "Genome build", lambda p: p.build, (), (),
         "Different genome builds: reprocess both against one build before comparing counts.", "GEO data processing"),
    Rule("sex", "Women in each group", lambda p: p.sex, (), (),
         "In at least one dataset the groups differ in sex by more than 20 points; add sex as a covariate, or check it is not confounded with the condition.",
         "sex in the sample characteristics", _balanced),
    Rule("sizes", "Group sizes", _sizes, (), (),
         f"A group with fewer than {MIN_GROUP} samples gives an unreliable effect estimate.", "GEO sample counts", _enough),
)


SHARED = {"layer", "technology"}


def _parts(value: str) -> set[str]:
    return {_norm(part) for part in value.split(" + ")}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"\(.*?\)", " ", text).casefold().split())


def _facet(rule: Rule, a: Profile, b: Profile, contrast: dict) -> Facet:
    va, vb = rule.read(a), rule.read(b)
    if rule.key == "contrast":
        status, note = contrast["status"], contrast["note"]
    elif va is None or vb is None:
        status, note = "unknown", f"Not stated for {' and '.join(p.accession for p, v in ((a, va), (b, vb)) if v is None)}: {rule.label.lower()}."
    elif (rule.agree or (lambda x, y: _norm(x) == _norm(y)))(va, vb):
        status, note = "same", ""
    elif rule.key in SHARED and (shared := [part for part in va.split(" + ") if _norm(part) in _parts(vb)]):
        status, note = "related", f"Only part of the data matches; use the {' and '.join(shared)} data from both."
    else:
        status, note = "differs", rule.differs
    return Facet(rule.key, rule.label, va, vb, status, note, rule.source, bool(rule.pool or rule.effects))


def compare(a: Profile, b: Profile, contrast: dict) -> Comparison:
    """`contrast` is the judged status of the two contrasts and a one-sentence note: {"status": ..., "note": ...}."""
    facets = [_facet(rule, a, b, contrast) for rule in RULES]
    stopped = {
        level: [f for rule, f in zip(RULES, facets) if getattr(rule, level) and f.status not in getattr(rule, level)]
        for level in ("pool", "effects")
    }
    verdict = (
        "pool" if not stopped["pool"]
        else "effects" if not stopped["effects"]
        else "no" if any(f.status == "differs" for f in stopped["effects"])
        else "unclear"
    )
    if verdict == "pool":
        reason = f"{', '.join(r.label.lower() for r in RULES if r.pool).capitalize()} all agree."
    else:
        blocking = stopped["pool" if verdict == "effects" else "effects"]
        first = next(f for f in blocking if f.status == "differs") if verdict == "no" else blocking[0]
        # The model's sentence about a related contrast can sound like agreement; say what "related" means first.
        reason = f"The contrasts are related, not the same: {first.note}" if first.key == "contrast" and first.status == "related" else first.note
    # Samples counted twice break both pooling and comparing results, whatever else agrees.
    if (shared := next(f for f in facets if f.key == "shared")).status == "differs":
        verdict, reason = "no", shared.note
    organisms = next(f for f in facets if f.key == "organism")
    partial = [f.note for f in sorted(facets, key=lambda f: f.key != "technology") if f.key in SHARED and f.status == "related"][:1]
    steps = {
        "pool": [*partial, "Reprocess both datasets from raw reads with one pipeline.", "Analyse the samples together and model the study as a batch term."],
        "effects": [
            *partial,
            "Analyse each dataset on its own, with the same method.",
            "Compare the fold changes, their direction and the overlap of hits between the two results.",
            *(["Map genes between the organisms through orthologs."] if organisms.status == "differs" else []),
        ],
        "no": [f"Do not combine these datasets. {reason}"],
        "unclear": [f"Check the {f.label.lower()} in the records of both datasets before combining them." for f in stopped["effects"]],
    }[verdict]
    return Comparison(a, b, verdict, reason, facets, steps)


if __name__ == "__main__":
    def profile(accession: str, **given) -> Profile:
        base = dict(
            accession=accession, source="GEO", title="t", organism="Mus musculus", layer="translatome + transcriptome", technology="Ribo-seq + RNA-seq",
            platform="Illumina HiSeq 4000", material="cell line", tissue="fibroblast", case=4, control=4, contrast="Torin1 vs vehicle", build="mm10",
        )
        return Profile(**base | given)

    assert _assay(["Ribo-seq", "RNA-seq"]) == ("translatome + transcriptome", "Ribo-seq + RNA-seq")

    same = {"status": "same", "note": "Both compare Torin1 with vehicle."}
    a = profile("A")

    pool = compare(a, profile("B", tissue="neuroblastoma", build="mm9", case=12, control=6), same)
    assert pool.verdict == "pool" and [f.key for f in pool.facets if f.status == "differs"] == ["tissue", "build"], pool
    assert [f.key for f in pool.facets if f.required] == ["organism", "layer", "technology", "groups", "contrast"]
    small = compare(a, profile("B", case=2, control=6), same)
    assert next(f for f in small.facets if f.key == "sizes").status == "differs", "a group under three samples is flagged"

    confounded = compare(profile("A", control=0), profile("B", case=0), same)
    assert confounded.verdict == "no" and "same variable" in confounded.reason, confounded

    species = compare(a, profile("B", organism="Homo sapiens (human)", tissue="prostate"), same)
    assert species.verdict == "effects" and "orthologs" in species.steps[-1] and "Different organisms" in species.reason, species

    related = compare(a, profile("B"), {"status": "related", "note": "Both inhibit mTOR."})
    assert related.verdict == "effects" and related.reason == "The contrasts are related, not the same: Both inhibit mTOR.", related.reason

    unknown = compare(a, profile("B", technology=None), same)
    assert unknown.verdict == "effects" and unknown.reason == "Not stated for B: technology.", "an unknown required facet does not satisfy"

    missing = compare(a, profile("B", case=None, control=None), same)
    assert missing.verdict == "unclear" and missing.reason == "Not stated for B: both groups in each.", missing

    rna = compare(a, profile("B", layer="transcriptome", technology="RNA-seq"), same)
    assert rna.verdict == "pool" and rna.steps[0].endswith("use the RNA-seq data from both."), rna

    layer = compare(a, profile("B", layer="proteome", technology=None, case=None, control=None), same)
    assert layer.verdict == "no" and "multi-omics" in layer.reason, layer

    differs = compare(a, profile("B"), {"status": "differs", "note": "One is a knockout."})
    assert differs.verdict == "no" and differs.reason == "One is a knockout.", differs

    row = {"accession": "GSE1", "source": "GEO", "title": "t", "organism": "Mus musculus", "modality": "Expression profiling by high throughput sequencing"}
    records = [{"organism": "Mus musculus", "instrument": "Illumina HiSeq 4000", "platform": "GPL21103", "genome_build": "mm10"}]
    labels = {"case_values": ["Torin1"], "control_values": ["vehicle"]}
    facts = {"case": 4, "control": 3, "mixed": 1, "has_control": True, "sample_type": "cell_line", "tissue": "fibroblast", "assays": ["Ribo-seq", "RNA-seq"]}
    built = build_profile(row, records, labels, facts)
    assert (built.layer, built.technology, built.platform, built.build) == ("translatome + transcriptome", "Ribo-seq + RNA-seq", "Illumina HiSeq 4000", "mm10"), built
    assert (built.case, built.control, built.material, built.contrast) == (4, 4, "cell line", "Torin1 vs vehicle"), built

    pride = {"accession": "PXD1", "source": "PRIDE", "title": "t", "organism": "Homo sapiens (human)", "modality": "Proteomics: Bottom-up proteomics"}
    bare = build_profile(pride, [], None, None)
    assert (bare.layer, bare.technology, bare.platform, bare.case, bare.contrast) == ("proteome", None, None, None, None), bare
    assert build_profile(row | {"modality": "Expression profiling by array"}, [], None, None).technology == "microarray"
    assert build_profile(row | {"modality": "Methylation profiling by array"}, [], None, None).layer == "epigenome"
    overlap = compare(profile("A", shared=12), profile("B", shared=12), same)
    assert overlap.verdict == "no" and "count twice" in overlap.reason, overlap
    assert compare(profile("A", shared=0), profile("B", shared=0), same).verdict == "pool"
    sexed = [records[0] | {"srx": "SRX1", "fields": {"group": g, "Sex": s}} for g, s in (("Torin1", "F"), ("Torin1", "M"), ("vehicle", "female"), ("vehicle", "male"))]
    with_sex = build_profile(row, sexed, labels | {"group_field": "group"}, facts, ["counts.txt.gz"])
    assert (with_sex.sex, with_sex.access) == ("cases 50% female; controls 50% female", "raw reads + processed files"), with_sex
    assert not _balanced("cases 80% female; controls 30% female", "cases 50% female; controls 50% female")
    assert build_profile(row | {"source": "EGA"}, [], None, None).access == "controlled access"
    tagged = {"case": None, "control": None, "mixed": 0, "has_control": None, "sample_type": "cell_line", "tissue": "liver", "assays": ["phosphoproteome (TMT)"],
              "methods": {"enrichment": {"value": "phospho", "label": "phospho enrichment", "trusted": True}, "labelling": {"value": "TMT", "label": "TMT", "trusted": True},
                          "acquisition": {"value": "DDA", "label": "DDA", "trusted": False}, "instrument_family": {"value": "orbitrap", "label": "Orbitrap", "trusted": True}}}
    phospho = build_profile(pride, [], None, tagged)
    assert (phospho.layer, phospho.technology, phospho.platform) == ("phosphoproteome", "TMT", "Orbitrap"), "untrusted DDA is left out"
    print("ok")
