"""nf-core/riboseq 1.2.0 samplesheet and contrasts for one GEO series, built from its sample records and labels.

The pipeline runs anota2seq per contrast on only the samples whose `condition` matches, and matches Ribo-seq to RNA-seq
samples by sorting both on `pair`. So every library in a contrast must be paired, which is why unpaired libraries get
their own condition.
"""

import csv
import io
import re
import time
import zipfile
from collections import Counter, defaultdict

import httpx

from .samples import RECORD_FIELDS, group_of

ENA_SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"
PIPELINE = "nf-core/riboseq 1.2.0"
TYPES = {
    "riboseq": "riboseq", "ribosomeprofiling": "riboseq", "rpf": "riboseq",
    "rnaseq": "rnaseq", "mrnaseq": "rnaseq", "totalrnaseq": "rnaseq",
    "tisseq": "tiseq",
}
CORE = ["sample", "fastq_1", "fastq_2", "strandedness", "type", "pair", "condition", "group"]
NUISANCE = re.compile(r"\brep|batch|lane|donor|patient|individual|subject|\bsex\b|gender|\bage\b|\bid\b", re.I)
MIN_PAIRS = 2
REPLICATE = re.compile(r"\d+|[a-z]|[a-z]\d+|rep\d+|replicate\d+")


def ena_runs(experiments: list[str]) -> dict[str, list[dict]]:
    """The sequencing runs of each SRA experiment, with HTTPS FASTQ URLs, from one ENA query per 100 experiments."""
    runs = defaultdict(list)
    for start in range(0, len(experiments), 100):
        query = " OR ".join(f'experiment_accession="{x}"' for x in experiments[start:start + 100])
        response = _ena_post({"result": "read_run", "query": query, "fields": "experiment_accession,fastq_ftp", "format": "tsv", "limit": 0})
        for row in csv.DictReader(io.StringIO(response.text), delimiter="\t"):
            if row["fastq_ftp"]:
                runs[row["experiment_accession"]].append({"run": row["run_accession"], "fastq": _reads(row["fastq_ftp"].split(";"))})
    return runs


def _ena_post(data: dict) -> httpx.Response:
    """ENA sometimes drops the TLS connection or returns a 5xx; retry before failing the export."""
    for attempt in range(4):
        try:
            response = httpx.post(ENA_SEARCH, data=data, timeout=120)
            if response.status_code < 500:
                response.raise_for_status()
                return response
        except httpx.TransportError:
            if attempt == 3:
                raise
        time.sleep(1 + attempt)
    response.raise_for_status()
    return response


def _reads(paths: list[str]) -> list[str]:
    """Paired runs can list an orphan-read file before the two mates; keep only the mates."""
    mates = sorted(p for p in paths if re.search(r"_[12]\.f(ast)?q\.gz$", p))
    return [f"https://{p}" for p in (mates if len(mates) == 2 else paths[:1])]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _clean(text: str) -> str:
    """Nextflow's splitCsv reads no quotes, so a comma inside a value would shift every later column."""
    return re.sub(r"[,\"\r\n]+", ";", text).strip()


def _level_names(field: str, values: list[str]) -> dict[str, str]:
    """Readable condition parts; numbered when two values slug the same, as '4EBP1/2 +/+' and '4EBP1/2 -/-' do."""
    names = {v: _slug(v) or "none" for v in values}
    if len(set(names.values())) < len(names):
        names = {v: f"{_slug(field)}{i}" for i, v in enumerate(sorted(values), 1)}
    return names


def _assay(fields: dict[str, str], labels: dict) -> str:
    if labels.get("assay_field"):
        return next((a["assay"] for a in labels.get("assay_values", []) if fields.get(labels["assay_field"], "") in a["values"]), "")
    return labels["assays"][0] if len(labels.get("assays", [])) == 1 else ""


def _words(title: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", title.lower())


def _assay_words(samples: list[dict]) -> set[str]:
    """Words that only one assay's titles use (Footprint, RPF, mRNA)."""
    words = {kind: {w for s in samples if s["type"] == kind for w in _words(s["title"])} for kind in ("riboseq", "rnaseq")}
    return {w for w in words["riboseq"] ^ words["rnaseq"] if not any(c.isdigit() for c in w)}


def _stem(title: str, assay_words: set[str]) -> str:
    """The title without assay words, replicate numbers and replicate letters; one design group shares one stem."""
    return " ".join(w for w in _words(title) if w not in assay_words and not REPLICATE.fullmatch(w))


def _pairs(samples: list[dict], factors: list[str], assay_words: set[str]) -> dict[str, int]:
    """Pair a Ribo-seq and an RNA-seq library when they alone share the title left after removing assay words and agree
    on every characteristic. Ambiguous libraries stay unpaired."""
    by_key = defaultdict(list)
    for s in samples:
        if s["type"] in ("riboseq", "rnaseq"):
            title = tuple(w for w in _words(s["title"]) if w not in assay_words)
            by_key[(title, tuple(s["fields"].get(f, "") for f in factors))].append(s)
    matched = [group for group in by_key.values() if sorted(s["type"] for s in group) == ["riboseq", "rnaseq"]]
    return {s["gsm"]: n for n, group in enumerate(matched, 1) for s in group}


def build(accession: str, records: list[dict], labels: dict, runs: dict[str, list[dict]], methods: tuple[dict[str, str], str] = ({}, "")) -> dict[str, str]:
    """samplesheet.csv, contrasts.csv (only if a contrast can run) and README.txt for one GEO series. `methods` is
    assay.library_types: where the methods show a library's type, it overrides the model's label."""
    kept, left_out, retyped = [], [], []
    for r in records:
        assay = _assay(r["fields"], labels)
        kind = TYPES.get(_norm(assay))
        shown = TYPES.get(_norm(methods[0].get(r["gsm"], "").split(" (")[0]))
        if shown and shown != kind:
            retyped.append(f"{r['gsm']} {kind or 'unknown'} -> {shown}")
            kind = shown
        reason = (
            f"assay '{assay or 'unknown'}' is not Ribo-seq, RNA-seq or TIS-seq" if not kind
            else "no SRA experiment in the GEO record" if not r["srx"]
            else f"no FASTQ in ENA for {r['srx']}" if not runs.get(r["srx"])
            else ""
        )
        if reason:
            left_out.append((r["gsm"], r["title"], reason))
        else:
            kept.append({**r, "type": kind, "group": group_of(r["fields"], labels)})

    names = sorted({f for s in kept for f in s["fields"]} - RECORD_FIELDS)
    values = {f: [s["fields"].get(f, "") for s in kept] for f in names}
    kinds = {s["type"] for s in kept}

    def assay_linked(f: str) -> bool:
        types_of = defaultdict(set)
        for s in kept:
            types_of[s["fields"].get(f, "")].add(s["type"])
        return len(kinds) > 1 and all(len(t) == 1 for t in types_of.values())

    def group_linked(f: str) -> bool:
        groups_of = defaultdict(set)
        for s in kept:
            if s["group"] in ("case", "control"):
                groups_of[s["fields"].get(f, "")].add(s["group"])
        return all(len(g) == 1 for g in groups_of.values())

    factors = [f for f in names if len(set(values[f])) > 1 and not assay_linked(f)]
    design = [f for f in factors if not NUISANCE.search(f) and all(f in s["fields"] for s in kept)]
    crossed = [f for f in design if not group_linked(f)]
    levels = [f for f in design if group_linked(f)]
    parts = {f: _level_names(f, sorted(set(values[f]))) for f in crossed + levels}

    assay_words = _assay_words(kept)
    pair_of = _pairs(kept, factors, assay_words)
    for s in kept:
        level = [parts[f][s["fields"][f]] for f in levels] or [s["group"]]
        s["stratum"] = tuple(parts[f][s["fields"][f]] for f in crossed)
        s["condition"] = "_".join([*s["stratum"], *level])
        if pair_of and s["type"] in ("riboseq", "rnaseq") and s["gsm"] not in pair_of:
            s["condition"] += "_unpaired"

    pairs = Counter((s["stratum"], s["condition"], s["group"]) for s in kept if s["gsm"] in pair_of and s["type"] == "riboseq")
    stems = defaultdict(set)
    for s in kept:
        if s["gsm"] in pair_of:
            stems[s["condition"]].add(_stem(s["title"], assay_words))
    mixed = {c: sorted(v) for c, v in stems.items() if len(v) > 1}
    contrasts, skipped = [], []
    for (stratum, reference, ref_group), n_ref in sorted(pairs.items()):
        for (other, target, tgt_group), n_tgt in sorted(pairs.items()):
            if other == stratum and ref_group == "control" and tgt_group == "case":
                if mix := next((c for c in (target, reference) if c in mixed), None):
                    skipped.append(f"{target} vs {reference}: the titles in {mix} differ ({' | '.join(mixed[mix])}), so the labels may miss a factor")
                elif min(n_ref, n_tgt) >= MIN_PAIRS:
                    contrasts.append({"id": f"{target}_vs_{reference}", "variable": "condition", "reference": reference, "target": target, "batch": "", "pair": "pair"})
                else:
                    skipped.append(f"{target} vs {reference}: {n_tgt} and {n_ref} Ribo-seq/RNA-seq pairs; anota2seq needs at least {MIN_PAIRS} on each side")

    columns = {f: _slug(f) if _slug(f) not in CORE else f"geo_{_slug(f)}" for f in factors}
    sheet = io.StringIO()
    writer = csv.writer(sheet, lineterminator="\n")
    writer.writerow([*CORE, *columns.values(), "title", "srx", "run"])
    for s in kept:
        for run in runs[s["srx"]]:
            fastq = run["fastq"] + [""]
            writer.writerow([
                s["gsm"], fastq[0], fastq[1], "auto", s["type"], pair_of.get(s["gsm"], ""), s["condition"], s["group"],
                *(_clean(s["fields"].get(f, "")) for f in factors), _clean(s["title"]), s["srx"], run["run"],
            ])

    files = {"samplesheet.csv": sheet.getvalue()}
    if contrasts:
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(contrasts[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(contrasts)
        files["contrasts.csv"] = out.getvalue()
    files["README.txt"] = _readme(accession, labels, kept, left_out, pair_of, crossed, levels, parts, contrasts, skipped)
    if retyped:
        files["README.txt"] += f"\nLibrary types corrected from the methods ({'; '.join(retyped)})" + (f", which say: \"{methods[1]}\"" if methods[1] else "") + "\n"
    return files


def _readme(accession, labels, kept, left_out, pair_of, crossed, levels, parts, contrasts, skipped) -> str:
    organism = ", ".join(sorted({s["organism"] for s in kept})) or "unknown"
    lines = [
        f"{accession}: samplesheet for {PIPELINE}, written by locus from the GEO sample records and ENA run reports.",
        "",
        "Run it with a genome FASTA and GTF of one release for the organism below:",
        "",
        f"  nextflow run nf-core/riboseq -r 1.2.0 -profile docker --input samplesheet.csv{' --contrasts contrasts.csv' if contrasts else ''} \\",
        "    --fasta genome.fa.gz --gtf genes.gtf.gz --outdir results",
        "",
        f"Organism: {organism}",
        f"Libraries: {len(kept)} kept, {len(left_out)} left out. Strandedness is 'auto': the pipeline infers it from the reads.",
        "",
        "Check these labels before you run the pipeline. Claude Haiku read them from the GEO records; code applied them.",
        f"  Case and control come from the field '{labels['group_field'] or '(none)'}'.",
        f"  Case values: {'; '.join(labels['case_values']) or '(none)'}",
        f"  Control values: {'; '.join(labels['control_values']) or '(none)'}",
        f"  The assay comes from the field '{labels.get('assay_field') or '(one assay for all samples)'}'.",
        "",
        "Condition = " + " + ".join([*(f"'{f}'" for f in crossed), *(f"'{f}'" for f in levels)] or ["group (case or control)"]) + ".",
    ]
    if crossed:
        lines.append("Contrasts compare case with control inside each level of " + ", ".join(f"'{f}'" for f in crossed) + ".")
    for f in crossed + levels:
        if any(name != _slug(value) for value, name in parts[f].items()):
            lines.append(f"  {f}: " + "; ".join(f"{name} = {value}" for value, name in parts[f].items()))

    by_condition = defaultdict(Counter)
    for s in kept:
        by_condition[s["condition"]][s["type"]] += 1
        by_condition[s["condition"]]["pairs"] += s["gsm"] in pair_of and s["type"] == "riboseq"
    lines += ["", "Libraries per condition (Ribo-seq / RNA-seq / TIS-seq, then Ribo-seq/RNA-seq pairs):"]
    lines += [f"  {c}: {n['riboseq']} / {n['rnaseq']} / {n['tiseq']}, pairs {n['pairs']}" for c, n in sorted(by_condition.items())]

    lines += ["", "Translational efficiency (anota2seq):"]
    kinds = {s["type"] for s in kept}
    if not {"riboseq", "rnaseq"} <= kinds:
        lines.append("  Not possible: it needs both Ribo-seq and RNA-seq libraries.")
    elif not pair_of:
        lines.append("  No Ribo-seq library could be matched to one RNA-seq library from titles and characteristics. Add a 'pair' column by hand.")
    elif not {"case", "control"} <= {s["group"] for s in kept if s["gsm"] in pair_of}:
        lines.append("  No contrast: the labels mark no paired case and control samples for this topic. Set 'condition' by hand, then write contrasts.csv.")
    elif not contrasts and not skipped:
        lines.append("  No contrast: paired case and control samples never share a level of " + ", ".join(f"'{f}'" for f in crossed) + ".")
    else:
        lines += [f"  Written: {c['id']}" for c in contrasts]
        lines += [f"  Not written: {s}" for s in skipped]
        unpaired = [s["gsm"] for s in kept if s["type"] in ("riboseq", "rnaseq") and s["gsm"] not in pair_of]
        if unpaired:
            lines.append(f"  Unpaired libraries ({len(unpaired)}), kept out of every contrast by the '_unpaired' condition: {', '.join(unpaired)}")
    if left_out:
        lines += ["", "Left out of the samplesheet:"]
        lines += [f"  {gsm} ({title}): {reason}" for gsm, title, reason in left_out]
    return "\n".join(lines) + "\n"


def zipped(accession: str, files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(f"{accession}-riboseq/{name}", text)
    return out.getvalue()


if __name__ == "__main__":
    def record(gsm, title, genotype, treatment):
        return {"gsm": gsm, "title": title, "organism": "Mus musculus", "srx": f"SRX{gsm}",
                "fields": {"title pattern": re.sub(r"\d+", "#", title), "genotype": genotype, "treatment": treatment, "cell type": "MEF"}}

    # GSE36892: two genotypes; replicate 2 has footprints only.
    records = [
        record(f"{i}", f"{kind} for {drug}-treated {geno} MEFs Replicate {rep}", geno, drug)
        for i, (rep, kind, geno, drug) in enumerate(
            [(1, k, g, d) for g in ("wild-type", "KO") for k in ("Footprint", "mRNA-seq") for d in ("vehicle", "Torin1")]
            + [(2, "Footprint", g, d) for g in ("wild-type", "KO") for d in ("vehicle", "Torin1")]
        )
    ]
    patterns = {r["fields"]["title pattern"] for r in records}
    labels = {"group_field": "treatment", "case_values": ["Torin1"], "control_values": ["vehicle"], "assay_field": "title pattern",
              "assay_values": [{"assay": "Ribo-seq", "values": [p for p in patterns if p.startswith("Footprint")]},
                               {"assay": "RNA-seq", "values": [p for p in patterns if p.startswith("mRNA")]}]}
    runs = {r["srx"]: [{"run": f"SRR{r['gsm']}", "fastq": [f"https://x/{r['gsm']}.fastq.gz"]}] for r in records}
    files = build("GSE36892", records, labels, runs)
    rows = list(csv.DictReader(io.StringIO(files["samplesheet.csv"])))
    assert sum(bool(r["pair"]) for r in rows) == 8 and len({r["pair"] for r in rows if r["pair"]}) == 4
    assert {r["condition"] for r in rows if r["pair"]} == {"ko_vehicle", "ko_torin1", "wild_type_vehicle", "wild_type_torin1"}
    assert all(r["condition"].endswith("_unpaired") for r in rows if "Replicate 2" in r["title"])
    assert "contrasts.csv" not in files and "anota2seq needs at least 2" in files["README.txt"]

    # GSE35469: two drugs against one vehicle, two paired replicates each.
    records = [
        record(f"{i}", f"{kind} for {drug} treated PC3 cells, replicate #{rep}.", "PC3", drug)
        for i, (rep, kind, drug) in enumerate((r, k, d) for r in (1, 2) for d in ("vehicle", "rapamycin", "PP242") for k in ("mRNA-seq", "Footprint"))
    ]
    patterns = {r["fields"]["title pattern"] for r in records}
    labels = {"group_field": "treatment", "case_values": ["rapamycin", "PP242"], "control_values": ["vehicle"], "assay_field": "title pattern",
              "assay_values": [{"assay": "Ribo-seq", "values": [p for p in patterns if p.startswith("Footprint")]},
                               {"assay": "RNA-seq", "values": [p for p in patterns if p.startswith("mRNA")]}]}
    runs = {r["srx"]: [{"run": f"SRR{r['gsm']}", "fastq": [f"https://x/{r['gsm']}.fastq.gz"]}] for r in records}
    files = build("GSE35469", records, labels, runs)
    contrasts = list(csv.DictReader(io.StringIO(files["contrasts.csv"])))
    assert [c["id"] for c in contrasts] == ["pp242_vs_vehicle", "rapamycin_vs_vehicle"], contrasts
    header, *lines = files["samplesheet.csv"].splitlines()
    assert all(line.count(",") == header.count(",") for line in lines), "a comma in a title shifted the columns"

    # GSE129816: Torin1-treated wild type only differs from untreated wild type in the title, so the wild-type condition mixes them.
    records = [
        {"gsm": f"{kind}{name}{rep}", "title": f"{kind}_{name}_{rep}", "organism": "Mus musculus", "srx": f"SRX{kind}{name}{rep}",
         "fields": {"title pattern": f"{kind}_{name}_#", "gneotype": "C1483Y" if name == "C1483Y" else "WT"}}
        for kind in ("RPF", "mRNA") for name in ("WT", "C1483Y", "Torin1") for rep in (1, 2, 3)
    ]
    labels = {"group_field": "gneotype", "case_values": ["C1483Y"], "control_values": ["WT"], "assay_field": "title pattern",
              "assay_values": [{"assay": "Ribo-seq", "values": [f"RPF_{n}_#" for n in ("WT", "C1483Y", "Torin1")]},
                               {"assay": "RNA-seq", "values": [f"mRNA_{n}_#" for n in ("WT", "C1483Y", "Torin1")]}]}
    runs = {r["srx"]: [{"run": "SRR1", "fastq": [f"https://x/{r['gsm']}.fastq.gz"]}] for r in records}
    files = build("GSE129816", records, labels, runs)
    assert "contrasts.csv" not in files and "the titles in wt differ (torin1 | wt)" in files["README.txt"], files["README.txt"]
    assert all(line.count(",") == header.count(",") for line in lines), "a comma in a title shifted the columns"
    print("ok")
