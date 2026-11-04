"""Ribo-seq and translation efficiency for one GEO series, in the three tiers the Process panel shows.

Here, now: the authors' own CDS count tables from GEO (one per sample) joined into one matrix and tested with DESeq2's
interaction design, the deltaTE approach (Chothani et al. 2019): ΔTE is the condition:assay term, ΔRNA and ΔRibo come
from one-assay fits, and every gene is classed as translationally regulated, buffered, transcriptional, intensified or
unchanged. On your laptop: the path docs/data-processing-contract.md designed, a lower-fidelity approximation of
nf-core/riboseq: subsampled ENA reads, fastp, bowtie2 to rRNA then to one GENCODE transcript per gene, P-site offsets
by the mode rule, metagene and footprint-length figures, P-site counts per CDS, then the same ΔTE test. On a cluster:
a Slurm + nf-core/riboseq kit built on samplesheet.build.

Every run writes manifest.json (tier, tools, files, pairs, skipped libraries, timings) and result.json in the shape the
API and the web panel read. Conventions (`_run`, `micromamba()`, `ref_dir()`, `fetch`, progress callbacks) are
process.py's.
"""

import csv
import gzip
import io
import json
import math
import os
import re
import shlex
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import assay, process, samples, samplesheet, store
from .process import _run, micromamba, ref_dir

ENV = "omics-ribo"
R_ENV = process.ENV
STAGES_HERE = ["plan", "fetch", "deltate", "done"]
STAGES_LAPTOP = ["plan", "reference", "fetch", "clean", "align", "psite", "count", "deltate", "done"]
MIN_PAIRS = 2
MAX_PAIRS = 4
MIN_LENGTH, MAX_LENGTH = 25, 35
GEO_FTP = "https://ftp.ncbi.nlm.nih.gov/geo"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&rettype=fasta&id="
GENCODE = {
    "Homo sapiens": {"tag": "human-46", "release": "GENCODE 46", "rdna": "U13369.1",
                     "pc": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/gencode.v46.pc_transcripts.fa.gz",
                     "genome": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/GRCh38.primary_assembly.genome.fa.gz",
                     "gtf": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_46/gencode.v46.primary_assembly.annotation.gtf.gz"},
    "Mus musculus": {"tag": "mouse-M35", "release": "GENCODE M35", "rdna": "BK000964.3",
                     "pc": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M35/gencode.vM35.pc_transcripts.fa.gz",
                     "genome": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M35/GRCm39.primary_assembly.genome.fa.gz",
                     "gtf": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_mouse/release_M35/gencode.vM35.primary_assembly.annotation.gtf.gz"},
}
RRNA_GENE = re.compile(r"^(?:MT-RNR\d|mt-Rnr\d|RNA5S\d*|RNA5-8S|RNA18S|RNA28S|RNA45S|Rn5s|Rn5-8s|Rn18s|Rn28s|Rn45s)", re.I)
R_SCRIPT = Path(__file__).with_name("deltate_deseq2.R")
PSITE_SCRIPT = Path(__file__).with_name("riboseq_psite.py")
CLASSES = ["translationally regulated", "buffered", "transcriptional", "intensified", "unchanged"]
FIDELITY = ("The laptop tier is a lower-fidelity approximation of nf-core/riboseq: reads were subsampled, aligned with bowtie2 to one "
            "GENCODE transcript per gene (no genome alignment, no splice-aware mapping, no multi-isoform handling), and P-site "
            "offsets came from a simple mode rule rather than riboWaltz or a trained model.")
AUTHORS_COUNTS = "The counts are the authors' own quantification as deposited in GEO, not locus's; locus only joined and tested them."


# ---------------------------------------------------------------- which library is which

def library_kind(record: dict, labels: dict | None = None) -> str:
    """'riboseq', 'rnaseq' or '' for one GEO sample: its title decides (RPF, Ribo, footprint words; see assay.py), then
    the labels' assay field, then a library strategy of RNA-Seq. TIS-seq and other assays give ''."""
    if hit := assay._library_word(record["title"]):
        return {assay.RIBO: "riboseq", assay.RNA: "rnaseq"}.get(hit[0], "")
    if labels:
        if kind := samplesheet.TYPES.get(samplesheet._norm(samplesheet._assay(record["fields"], labels))):
            return kind if kind != "tiseq" else ""
    return "rnaseq" if samplesheet._norm(record["fields"].get("library strategy", "")) == "rnaseq" else ""


def detect(records: list[dict], labels: dict | None = None) -> bool:
    """True when the series has Ribo-seq libraries: a library strategy of OTHER or RNA-Seq with a footprint title, or
    labels naming Ribo-seq among the assays."""
    for r in records:
        strategy = samplesheet._norm(r["fields"].get("library strategy", ""))
        if strategy in ("other", "rnaseq", "") and (hit := assay._library_word(r["title"])) and hit[0] == assay.RIBO:
            return True
    if labels:
        named = [*labels.get("assays", []), *(a["assay"] for a in labels.get("assay_values", []))]
        return any(samplesheet.TYPES.get(samplesheet._norm(a)) == "riboseq" for a in named)
    return False


# ---------------------------------------------------------------- the authors' count tables on GEO

def _gsm_url(gsm: str, name: str) -> str:
    return f"{GEO_FTP}/samples/{gsm[:-3]}nnn/{gsm}/suppl/{name}"


def file_assay(name: str) -> str:
    """'riboseq', 'rnaseq' or '' from a supplementary file name: footprint words win over RNA words."""
    stem = re.sub(r"^GSM\d+_", "", name)
    if re.search(r"(?<![A-Za-z])(?:RPFs?|ribo|riboseq|footprints?|FP)(?![A-Za-z])", stem, re.I):
        return "riboseq"
    if re.search(r"(?<![A-Za-z])(?:RNA|mRNA|RNAseq|totalRNA|input)(?![A-Za-z])", stem, re.I):
        return "rnaseq"
    return ""


def parse_filelist(text: str) -> list[dict]:
    """Per-sample files from a GEO series filelist.txt: {gsm, name, bytes, url, assay}; the RAW tar is not a sample file."""
    files = []
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        name = row.get("Name", "")
        if row.get("#Archive/File") != "File" or not (m := re.match(r"(GSM\d+)_", name)):
            continue
        files.append({"gsm": m.group(1), "name": name, "bytes": int(row.get("Size") or 0), "url": _gsm_url(m.group(1), name), "assay": file_assay(name)})
    return files


def processed_counts(accession: str) -> list[dict]:
    """Per-sample count tables GEO holds for a series (from its filelist.txt, cached next to the sample records), with
    the assay read from the file name, else from the sample title."""
    path = samples.CACHE / f"{accession}.filelist.txt"
    if not path.exists():
        import httpx

        response = httpx.get(f"{GEO_FTP}/series/{accession[:-3]}nnn/{accession}/suppl/filelist.txt", timeout=60, follow_redirects=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text if response.status_code == 200 else "")
    files = [f for f in parse_filelist(path.read_text()) if re.search(r"count|cds|rpf|ribo|rna", f["name"], re.I)]
    if any(not f["assay"] for f in files):
        titles = {r["gsm"]: r for r in samples.geo_records(accession)}
        for f in files:
            if not f["assay"] and f["gsm"] in titles:
                f["assay"] = library_kind(titles[f["gsm"]])
    return files


def read_counts(path: Path) -> dict[str, int]:
    """gene -> count from one HTSeq-style table (gene<TAB>count, more count columns summed, as the DKO files that hold two
    sequencing runs do); htseq's `__no_feature` rows and a header line are dropped."""
    counts: dict[str, int] = {}
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2 or parts[0].startswith("__") or not parts[0]:
                continue
            try:
                counts[parts[0]] = counts.get(parts[0], 0) + sum(int(round(float(p))) for p in parts[1:] if p.strip())
            except ValueError:
                continue  # a header line
    return counts


# ---------------------------------------------------------------- pairs and the contrast

def _factors(kept: list[dict]) -> list[str]:
    """Characteristics that vary among the libraries and are not just another name for the assay (samplesheet.build's rule)."""
    names = sorted({f for s in kept for f in s["fields"]} - samples.RECORD_FIELDS)
    kinds = {s["type"] for s in kept}

    def assay_linked(f: str) -> bool:
        types_of = defaultdict(set)
        for s in kept:
            types_of[s["fields"].get(f, "")].add(s["type"])
        return len(kinds) > 1 and all(len(t) == 1 for t in types_of.values())

    return [f for f in names if len({s["fields"].get(f, "") for s in kept}) > 1 and not assay_linked(f)]


def _gsm_number(gsm: str) -> int:
    return int(re.sub(r"\D", "", gsm) or 0)


def choose_pairs(records: list[dict], labels: dict, available: dict[str, str] | None = None, cap: int = MAX_PAIRS, floor: int = MIN_PAIRS) -> dict:
    """The Ribo-seq/RNA-seq pairs that will run: libraries paired the way samplesheet._pairs does (same title once the
    assay words are gone, same characteristics), the most frequent control and case values of the labelled field as the
    two conditions, up to `cap` pairs per condition in GSM order. `available` maps GSM to why a library is usable (a
    file name or run); libraries missing from it, unpaired libraries, other values and pairs beyond the cap are listed
    under `skipped` with the reason. Raises ValueError when a side has fewer than `floor` pairs."""
    field = labels["group_field"]
    kept, skipped = [], []
    for r in sorted(records, key=lambda r: _gsm_number(r["gsm"])):
        kind = library_kind(r, labels)
        reason = (
            f"'{r['title']}' is neither a Ribo-seq nor an RNA-seq library" if not kind
            else "no count table or reads for this library" if available is not None and r["gsm"] not in available
            else ""
        )
        if reason:
            skipped.append({"gsm": r["gsm"], "title": r["title"], "reason": reason})
        else:
            kept.append({**r, "type": kind, "group": samples.group_of(r["fields"], labels), "value": r["fields"].get(field, "")})

    pair_of = samplesheet._pairs(kept, _factors(kept), samplesheet._assay_words(kept))
    by_pair = defaultdict(dict)
    for s in kept:
        if s["gsm"] in pair_of:
            by_pair[pair_of[s["gsm"]]][s["type"]] = s
        else:
            other = "RNA-seq" if s["type"] == "riboseq" else "Ribo-seq"
            skipped.append({"gsm": s["gsm"], "title": s["title"], "reason": f"no {other} library shares its title and characteristics, so it has no pair"})

    pairs = []
    for n in sorted(by_pair, key=lambda n: _gsm_number(by_pair[n]["riboseq"]["gsm"])):
        ribo, rna = by_pair[n]["riboseq"], by_pair[n]["rnaseq"]
        if ribo["group"] != rna["group"] or ribo["group"] not in ("case", "control"):
            for s in (ribo, rna):
                skipped.append({"gsm": s["gsm"], "title": s["title"], "reason": f"'{field}' is '{s['value']}', neither case nor control"})
            continue
        pairs.append({"ribo": ribo, "rna": rna, "group": ribo["group"], "value": ribo["value"]})

    levels = {}
    for group in ("control", "case"):
        values = Counter(p["value"] for p in pairs if p["group"] == group)
        if not values:
            raise ValueError(f"no paired {group} Ribo-seq/RNA-seq libraries; the labels mark {labels[group + '_values']} as {group}")
        levels[group] = values.most_common(1)[0][0]
    names = {g: samplesheet._slug(v) or g for g, v in levels.items()}
    if names["control"] == names["case"]:
        names = {"control": "control", "case": "case"}

    chosen = []
    for group in ("control", "case"):
        on_level = [p for p in pairs if p["group"] == group and p["value"] == levels[group]]
        for p in pairs:
            if p["group"] == group and p["value"] != levels[group]:
                for s in (p["ribo"], p["rna"]):
                    skipped.append({"gsm": s["gsm"], "title": s["title"], "reason": f"'{field}' is '{p['value']}'; the contrast uses '{levels[group]}'"})
        if len(on_level) < floor:
            raise ValueError(f"only {len(on_level)} {group} Ribo-seq/RNA-seq pair(s) with '{field}' = '{levels[group]}'; DESeq2 needs at least {floor} per condition")
        for p in on_level[cap:]:
            for s in (p["ribo"], p["rna"]):
                skipped.append({"gsm": s["gsm"], "title": s["title"], "reason": f"beyond the cap of {cap} pairs per condition"})
        chosen += [{**p, "condition": names[group]} for p in on_level[:cap]]

    out = []
    for i, p in enumerate(chosen, 1):
        for kind, s in (("riboseq", p["ribo"]), ("rnaseq", p["rna"])):
            out.append({"gsm": s["gsm"], "title": s["title"], "srx": s.get("srx", ""), "assay": kind, "pair": i, "group": p["group"],
                        "value": p["value"], "condition": p["condition"], "fields": s["fields"]})
    return {"field": field, "reference": names["control"], "target": names["case"], "levels": levels, "samples": out,
            "skipped": sorted(skipped, key=lambda s: _gsm_number(s["gsm"]))}


def pooled_factors(chosen: list[dict], field: str) -> list[str]:
    """Warnings for characteristics other than the contrast field that take several values among the chosen libraries."""
    warnings = []
    for f in sorted({k for s in chosen for k in s["fields"]} - samples.RECORD_FIELDS - {field}):
        values = sorted({s["fields"].get(f, "") for s in chosen})
        if len(values) > 1:
            warnings.append(f"'{f}' takes {len(values)} values among the chosen libraries ({', '.join(v or '(empty)' for v in values)}); the contrast pools them.")
    return warnings


def here_fits(accession: str, records: list[dict], labels: dict | None = None) -> tuple[bool, str]:
    """Whether "Here, now" can run: GEO holds per-sample count tables for at least MIN_PAIRS Ribo-seq and MIN_PAIRS
    RNA-seq libraries on each side of the contrast (without labels, at least 2 * MIN_PAIRS of each)."""
    files = processed_counts(accession)
    by_gsm = {f["gsm"]: f for f in files}
    kinds = Counter(f["assay"] for f in files)
    if not files:
        return False, "GEO holds no per-sample count tables for this series"
    if labels:
        try:
            plan = choose_pairs(records, labels, {g: f["name"] for g, f in by_gsm.items()})
        except ValueError as error:
            return False, str(error)
        n = Counter(s["condition"] for s in plan["samples"] if s["assay"] == "riboseq")
        return True, f"GEO holds the authors' count tables for {n[plan['target']]} + {n[plan['reference']]} Ribo-seq/RNA-seq pairs"
    need = 2 * MIN_PAIRS
    if kinds["riboseq"] >= need and kinds["rnaseq"] >= need:
        return True, f"GEO holds the authors' count tables for {kinds['riboseq']} Ribo-seq and {kinds['rnaseq']} RNA-seq libraries"
    return False, f"GEO holds count tables for {kinds['riboseq']} Ribo-seq and {kinds['rnaseq']} RNA-seq libraries; ΔTE needs at least {need} of each"


# ---------------------------------------------------------------- pure rules

def classify(padj_rna, lfc_rna, padj_ribo, lfc_ribo, padj_te, lfc_te, alpha: float = 0.05) -> str:
    """The deltaTE class of one gene at `alpha`. ΔTE significant and ΔRNA not: translationally regulated (deltaTE's
    "exclusive"). ΔTE and ΔRNA both significant: buffered when they point in opposite directions (the ribosomes do not
    follow the mRNA, i.e. ΔRibo is flat or opposite), intensified when they point the same way (all three move together).
    ΔRNA and ΔRibo significant with ΔTE not: transcriptional ("forwarded"). Anything else: unchanged. NA p-values count
    as not significant. deltate_deseq2.R applies the same rule; run_* checks the two agree."""
    def sig(p):
        return p is not None and not (isinstance(p, float) and math.isnan(p)) and float(p) < alpha

    te, rna, ribo = sig(padj_te), sig(padj_rna), sig(padj_ribo)
    if te and not rna:
        return "translationally regulated"
    if te and rna:
        return "buffered" if (float(lfc_te) > 0) != (float(lfc_rna) > 0) else "intensified"
    if rna and ribo:
        return "transcriptional"
    return "unchanged"


def psite_offset(distances, fallback: int = 12, minimum: int = 200) -> tuple[int, int, bool]:
    """The P-site offset for reads of one length: the mode of the distance from their 5′ ends to the start codon, over
    reads whose 5′ ends fall within 30 nt upstream of it (riboWaltz's rule, without its corrections). Returns (offset,
    reads, used_fallback); `fallback` applies when fewer than `minimum` reads were available."""
    counts = Counter(d for d in distances if 1 <= d <= 30)
    n = sum(counts.values())
    if n < minimum:
        return fallback, n, True
    best = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return best, n, False


def corrected_offset(temporary: int, frames: tuple[int, int, int], minimum_share: float = 0.4) -> tuple[int, bool]:
    """riboWaltz-style correction of one length's temporary offset: `frames` are the in-CDS counts of 5′ ends by frame
    relative to the start codon. When one frame holds at least `minimum_share` of them, the offset becomes the value
    nearest `temporary` that moves that frame to frame 0 (P-sites of elongating ribosomes sit in frame 0), so a
    start-codon mode that is off by one no longer puts the bulk of a length's reads out of frame. Returns (offset,
    corrected)."""
    total = sum(frames)
    if not total:
        return temporary, False
    dominant = max(range(3), key=lambda f: (frames[f], -f))
    if frames[dominant] / total < minimum_share:
        return temporary, False
    for shift in (0, 1, -1, 2, -2):
        if (dominant + temporary + shift) % 3 == 0:
            return temporary + shift, shift != 0
    return temporary, False


# ---------------------------------------------------------------- shared pieces of a run

def _log_to(out: Path, progress):
    log_file = open(out / "process.log", "a")

    def log(message: str) -> None:
        log_file.write(message + "\n")
        log_file.flush()
        progress("log", message)

    def stage(name: str, data: dict | None = None) -> None:
        log(f"[{name}]")
        progress(name, data or {})

    return log, stage, log_file


def _labels(topic: str, accession: str, labels_for) -> dict:
    if labels_for is None:
        from . import agent

        labels_for = agent.geo_labels
    labels = labels_for(topic, accession, store.summary(accession))
    if not labels.get("group_field"):
        raise ValueError(f"the labels found no field that separates cases from controls for '{topic}'")
    return labels


def _tool(*args: str) -> list[str]:
    return [micromamba(), "run", "-n", ENV, *args]


def _version(env: str, cmd: list[str]) -> str:
    """The version a tool prints (fastp prints it to stderr; bowtie2 after a path, so 'version X' is preferred)."""
    done = subprocess.run([micromamba(), "run", "-n", env, *cmd], capture_output=True, text=True)
    text = done.stdout + "\n" + done.stderr
    m = re.search(r"version (\d+\.\d+(?:\.\d+)?)", text) or re.search(r"(?<![\w/.-])(\d+\.\d+(?:\.\d+)?)", text)
    return m.group(1) if m else "unknown"


def write_counts(tables: dict[str, dict[str, int]], order: list[str], path: Path) -> tuple[int, list[str]]:
    """counts.tsv (gene × library, columns in `order`) from per-library gene -> count maps; genes missing from a library
    count 0 there. Returns the gene count and warnings about libraries whose gene lists differ."""
    gene_sets = {gsm: set(t) for gsm, t in tables.items()}
    union = set().union(*gene_sets.values()) if gene_sets else set()
    warnings = [f"{gsm} lists {len(union) - len(genes)} fewer genes than the others; they count 0 there" for gsm, genes in gene_sets.items() if len(genes) < len(union)]
    genes = sorted(union)
    with open(path, "w") as handle:
        handle.write("gene\t" + "\t".join(order) + "\n")
        for g in genes:
            handle.write(g + "\t" + "\t".join(str(tables[gsm].get(g, 0)) for gsm in order) + "\n")
    return len(genes), warnings


def write_samples(chosen: list[dict], path: Path) -> None:
    with open(path, "w") as handle:
        handle.write("sample\tpair\tassay\tcondition\n")
        for s in chosen:
            handle.write(f"{s['gsm']}\t{s['pair']}\t{'ribo' if s['assay'] == 'riboseq' else 'rna'}\t{s['condition']}\n")


def deltate(out: Path, reference: str, target: str, log) -> dict:
    """deltate_deseq2.R on out/counts.tsv and out/samples.tsv; returns deltate_summary.json after checking that the R
    classes agree with `classify`."""
    _run([micromamba(), "run", "-n", R_ENV, "Rscript", str(R_SCRIPT), str(out / "counts.tsv"), str(out / "samples.tsv"), str(out), reference, target], log)
    summary = json.loads((out / "deltate_summary.json").read_text())
    disagree = 0
    with open(out / "deltate_results.tsv", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            padj = [None if row[k] in ("NA", "") else float(row[k]) for k in ("padj_rna", "padj_ribo", "padj_te")]
            lfc = [0.0 if row[k] in ("NA", "") else float(row[k]) for k in ("log2fc_rna", "log2fc_ribo", "log2fc_te")]
            if classify(padj[0], lfc[0], padj[1], lfc[1], padj[2], lfc[2]) != row["class"]:
                disagree += 1
    if disagree:
        raise RuntimeError(f"{disagree} genes are classed differently by deltate_deseq2.R and riboseq.classify")
    log(f"  {summary['genes_tested']} genes tested; " + ", ".join(f"{summary['classes'][c]} {c}" for c in CLASSES))
    return summary


def _summary_sentences(summary: dict, chosen: list[dict], plan: dict) -> list[str]:
    n = Counter(s["condition"] for s in chosen if s["assay"] == "riboseq")
    c = summary["classes"]
    top = [g["gene"] for g in summary.get("top_translational", [])][:8]
    lines = [
        f"{plan['levels']['case']} versus {plan['levels']['control']} ('{plan['field']}'): {n[plan['target']]} Ribo-seq/RNA-seq pairs against "
        f"{n[plan['reference']]}, {summary['genes_tested']:,} genes tested of {summary['genes']:,} counted.",
        f"At padj < 0.05, {c['translationally regulated']:,} genes are translationally regulated (ΔTE changes while the mRNA does not), "
        f"{c['buffered']:,} are buffered, {c['transcriptional']:,} change transcriptionally with the ribosomes following the mRNA, "
        f"{c['intensified']:,} are intensified and {c['unchanged']:,} are unchanged.",
        f"ΔTE falls in {summary['te_down']:,} genes and rises in {summary['te_up']:,}.",
    ]
    if top:
        lines.append("The translationally regulated genes with the smallest ΔTE adjusted p-values are " + ", ".join(top) + ".")
    return lines


def _scatter_caption(summary: dict, plan: dict) -> str:
    c = summary["classes"]
    return (f"Δ RNA against Δ Ribo (log2 fold change, {plan['levels']['case']} vs {plan['levels']['control']}) for {summary['genes_tested']:,} genes; "
            f"{c['translationally regulated']:,} translationally regulated, {c['buffered']:,} buffered, {c['transcriptional']:,} transcriptional, "
            f"{c['intensified']:,} intensified at padj < 0.05; the dashed line is Δ Ribo = Δ RNA.")


def _result_title(plan: dict, chosen: list[dict], summary: dict) -> str:
    n = Counter(s["condition"] for s in chosen if s["assay"] == "riboseq")
    return (f"{plan['levels']['case']} vs {plan['levels']['control']} from '{plan['field']}', {n[plan['target']]} + {n[plan['reference']]} "
            f"Ribo-seq/RNA-seq pairs, {summary['genes_tested']:,} genes tested")


def files_of(out: Path) -> list[dict]:
    names = ["counts.tsv", "samples.tsv", "deltate_results.tsv", "deltate_summary.json", "deltate_scatter.png", "deltate_scatter.pdf",
             "metagene.png", "metagene.pdf", "footprint_lengths.png", "footprint_lengths.pdf", "psite_summary.json", "manifest.json", "result.json"]
    return [{"name": n, "bytes": (out / n).stat().st_size} for n in names if (out / n).exists()]


# ---------------------------------------------------------------- here, now

def run_here(accession: str, topic: str, out: Path, labels_for=None, progress=lambda stage, data: None) -> dict:
    """ΔTE from the authors' per-sample count tables on GEO. Writes counts.tsv, samples.tsv, deltate_results.tsv,
    deltate_summary.json, deltate_scatter.png/.pdf, manifest.json and result.json under `out`."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    log, stage, log_file = _log_to(out, progress)
    started = datetime.now(timezone.utc)
    timings = {}
    try:
        t = time.monotonic()
        stage("plan")
        records = samples.geo_records(accession)
        if not records:
            raise LookupError(f"{accession}: no sample records in GEO")
        labels = _labels(topic, accession, labels_for)
        files = {f["gsm"]: f for f in processed_counts(accession)}
        plan = choose_pairs(records, labels, {g: f["name"] for g, f in files.items()})
        chosen = plan["samples"]
        warnings = pooled_factors(chosen, plan["field"])
        log(f"  '{plan['field']}': {plan['levels']['case']} vs {plan['levels']['control']}; {len(chosen) // 2} pairs; {len(plan['skipped'])} libraries left out")
        progress("plan", {"reference": plan["reference"], "target": plan["target"], "samples": chosen, "skipped": plan["skipped"]})
        timings["plan"] = round(time.monotonic() - t, 1)

        t = time.monotonic()
        stage("fetch", {"count": len(chosen)})
        counts_dir = out / "counts"
        counts_dir.mkdir(exist_ok=True)
        tables = {}
        for i, s in enumerate(chosen, 1):
            f = files[s["gsm"]]
            path = counts_dir / f["name"]
            if not path.exists():
                log(f"  {f['url']}")
                _run(["curl", "-sSL", "--retry", "3", "-o", f"{path}.part", f["url"]], log)
                os.replace(f"{path}.part", path)
            tables[s["gsm"]] = read_counts(path)
            s["file"] = {"name": f["name"], "bytes": path.stat().st_size, "url": f["url"]}
            progress("fetch", {"count": len(chosen), "done": i})
        genes, more = write_counts(tables, [s["gsm"] for s in chosen], out / "counts.tsv")
        warnings += more
        write_samples(chosen, out / "samples.tsv")
        log(f"  {genes} genes × {len(chosen)} libraries")
        timings["fetch"] = round(time.monotonic() - t, 1)

        t = time.monotonic()
        stage("deltate")
        summary = deltate(out, plan["reference"], plan["target"], log)
        timings["deltate"] = round(time.monotonic() - t, 1)

        finished = datetime.now(timezone.utc)
        tools = {"locus riboseq": "here", **summary["versions"]}
        manifest = {
            "accession": accession, "tier": "here", "pipeline": "locus riboseq", "topic": topic, "tools": tools,
            "note": AUTHORS_COUNTS, "design": "DESeq2 ~ condition + assay + condition:assay (ΔTE), ~ condition on RNA-seq (ΔRNA) and on Ribo-seq (ΔRibo); deltaTE, Chothani et al. 2019",
            "contrast": {"field": plan["field"], "reference": plan["reference"], "target": plan["target"], "levels": plan["levels"]},
            "files": [{"gsm": s["gsm"], **s["file"]} for s in chosen],
            "pairs": [{"pair": s["pair"], "gsm": s["gsm"], "assay": s["assay"], "condition": s["condition"]} for s in chosen],
            "skipped": plan["skipped"], "warnings": warnings, "stage_seconds": timings,
            "started": started.isoformat(timespec="seconds"), "finished": finished.isoformat(timespec="seconds"), "seconds": round((finished - started).total_seconds()),
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        result = {
            "accession": accession, "data_type": "riboseq", "tier": "here", "title": _result_title(plan, chosen, summary),
            "summary": [AUTHORS_COUNTS, *_summary_sentences(summary, chosen, plan)],
            "figures": [{"file": "deltate_scatter.png", "title": "ΔTE", "caption": _scatter_caption(summary, plan)}],
            "tables": [{"file": "deltate_results.tsv", "title": "ΔTE per gene"}],
            "warnings": warnings, "contrast": manifest["contrast"],
            "samples": [{"gsm": s["gsm"], "title": s["title"], "assay": s["assay"], "pair": s["pair"], "condition": s["condition"]} for s in chosen],
            "skipped": plan["skipped"], "classes": summary["classes"], "genes_tested": summary["genes_tested"],
            "files": files_of(out), "seconds": manifest["seconds"], "tools": tools,
        }
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        stage("done", result)
        return result
    finally:
        log_file.close()


# ---------------------------------------------------------------- laptop: reference

def _parse_pc_header(header: str) -> dict | None:
    """transcript, gene_id, gene_name, length, cds_start, cds_end (1-based, inclusive, stop codon included) from a GENCODE
    pc_transcripts header, or None when it carries no CDS range."""
    parts = header[1:].strip().split("|")
    cds = next((p for p in parts if p.startswith("CDS:")), None)
    if not cds or len(parts) < 7 or "PAR_Y" in parts[0]:
        return None
    start, end = cds[4:].split("-")
    return {"transcript": parts[0], "gene_id": parts[1], "gene_name": parts[5], "length": int(parts[6]), "cds_start": int(start), "cds_end": int(end)}


def select_transcripts(pc_fasta: Path, transcripts_fa: Path, cds_tsv: Path) -> dict:
    """One transcript per gene from a GENCODE pc_transcripts FASTA: the longest CDS (ties by transcript length) among
    those whose CDS starts with ATG and is a whole number of codons. Writes transcripts.fa and cds.tsv (transcript,
    gene_id, gene_name, gene, cds_start, cds_end, length; `gene` is the name when unique among the kept genes, else
    the gene_id). Returns counts."""
    best: dict[str, tuple] = {}
    seqs: dict[str, str] = {}
    header, chunks = None, []

    def close():
        if header is None:
            return
        info = _parse_pc_header(header)
        if info:
            seq = "".join(chunks)
            cds = seq[info["cds_start"] - 1:info["cds_end"]]
            if len(cds) % 3 == 0 and cds.startswith("ATG") and len(cds) >= 90:
                key = (len(cds), info["length"])
                if info["gene_id"] not in best or key > best[info["gene_id"]][0]:
                    if info["gene_id"] in best:
                        seqs.pop(best[info["gene_id"]][1]["transcript"], None)
                    best[info["gene_id"]] = (key, info)
                    seqs[info["transcript"]] = seq

    with gzip.open(pc_fasta, "rt") as handle:
        for line in handle:
            if line.startswith(">"):
                close()
                header, chunks = line, []
            else:
                chunks.append(line.strip())
        close()

    names = Counter(info["gene_name"] for _, info in best.values())
    with open(f"{transcripts_fa}.part", "w") as fa, open(f"{cds_tsv}.part", "w") as tsv:
        tsv.write("transcript\tgene_id\tgene_name\tgene\tcds_start\tcds_end\tlength\n")
        for gene_id in sorted(best):
            info = best[gene_id][1]
            gene = info["gene_name"] if info["gene_name"] and names[info["gene_name"]] == 1 else gene_id
            tsv.write(f"{info['transcript']}\t{gene_id}\t{info['gene_name']}\t{gene}\t{info['cds_start']}\t{info['cds_end']}\t{info['length']}\n")
            seq = seqs[info["transcript"]]
            fa.write(f">{info['transcript']}\n" + "\n".join(seq[i:i + 80] for i in range(0, len(seq), 80)) + "\n")
    os.replace(f"{transcripts_fa}.part", transcripts_fa)
    os.replace(f"{cds_tsv}.part", cds_tsv)
    return {"genes": len(best), "transcripts": len(seqs)}


def _rrna_from_gencode(full_fasta: Path, out, log) -> int:
    """Append the rRNA genes (MT-RNR1/2, RNA5S, RNA5-8S, RNA18S/28S/45S when present) of a GENCODE transcripts FASTA."""
    n, keep = 0, False
    with gzip.open(full_fasta, "rt") as handle:
        for line in handle:
            if line.startswith(">"):
                parts = line[1:].split("|")
                keep = len(parts) > 5 and bool(RRNA_GENE.match(parts[5]))
                if keep:
                    n += 1
                    out.write(f">{parts[0]}|{parts[5]}\n")
            elif keep:
                out.write(line)
    return n


def reference(organism: str, threads: int, log) -> dict:
    """The laptop tier's reference for one organism under ref_dir()/riboseq/<tag>/: GENCODE protein-coding transcripts
    reduced to one per gene (transcripts.fa, cds.tsv, bowtie2 index 'transcripts') and an rRNA contaminant index
    ('rrna': the rDNA repeat from NCBI plus GENCODE's rRNA genes). Built once; build.json records what and how long."""
    spec = GENCODE[organism]
    base = ref_dir() / "riboseq" / spec["tag"]
    base.mkdir(parents=True, exist_ok=True)
    build_json = base / "build.json"
    if build_json.exists() and (base / "transcripts.1.bt2").exists() and (base / "rrna.1.bt2").exists():
        return json.loads(build_json.read_text())
    build = {"organism": organism, "release": spec["release"], "sources": {}, "seconds": {}}

    pc = base / "pc_transcripts.fa.gz"
    if not pc.exists():
        log(f"  downloading {spec['pc']}")
        t = time.monotonic()
        _run(["curl", "-sSL", "--retry", "3", "-o", f"{pc}.part", spec["pc"]], log)
        os.replace(f"{pc}.part", pc)
        build["seconds"]["download_pc_transcripts"] = round(time.monotonic() - t)
    build["sources"]["pc_transcripts"] = spec["pc"]

    t = time.monotonic()
    log("  one transcript per gene: the longest CDS")
    counts = select_transcripts(pc, base / "transcripts.fa", base / "cds.tsv")
    build.update(counts)
    build["seconds"]["select_transcripts"] = round(time.monotonic() - t)
    log(f"  {counts['genes']} genes kept")

    rrna = base / "rrna.fa"
    rdna = base / f"{spec['rdna']}.fa"
    if not rdna.exists():
        log(f"  downloading {spec['rdna']} from NCBI")
        _run(["curl", "-sSL", "--retry", "3", "-o", f"{rdna}.part", EFETCH + spec["rdna"]], log)
        os.replace(f"{rdna}.part", rdna)
    if not rdna.read_text().startswith(">"):
        rdna.unlink()
        raise RuntimeError(f"NCBI efetch did not return a FASTA for {spec['rdna']}")
    build["sources"]["rdna"] = EFETCH + spec["rdna"]
    full_tag, full_url = process.GENCODE[organism]
    full = ref_dir() / "gencode" / full_tag / "transcripts.fa.gz"
    if not full.exists():
        full.parent.mkdir(parents=True, exist_ok=True)
        log(f"  downloading {full_url} for the rRNA genes")
        _run(["curl", "-sSL", "--retry", "3", "-o", f"{full}.part", full_url], log)
        os.replace(f"{full}.part", full)
    build["sources"]["rrna_genes"] = full_url
    with open(f"{rrna}.part", "w") as out:
        out.write(rdna.read_text())
        build["rrna_genes"] = _rrna_from_gencode(full, out, log)
    os.replace(f"{rrna}.part", rrna)
    log(f"  rRNA index: {spec['rdna']} + {build['rrna_genes']} GENCODE rRNA genes")

    for name in ("rrna", "transcripts"):
        t = time.monotonic()
        log(f"  bowtie2-build {name}")
        _run(_tool("bowtie2-build", "--threads", str(threads), "-q", str(base / f"{name}.fa"), str(base / name)), log)
        build["seconds"][f"bowtie2_build_{name}"] = round(time.monotonic() - t)
    build.update({"dir": str(base), "cds": str(base / "cds.tsv"), "transcripts_index": str(base / "transcripts"), "rrna_index": str(base / "rrna"),
                  "bowtie2": _version(ENV, ["bowtie2", "--version"]), "built": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    build_json.write_text(json.dumps(build, indent=2) + "\n")
    return build


# ---------------------------------------------------------------- laptop: per-library steps

LINKERS = {
    "CTGTAGGCACCATCAAT": "Ingolia ribosome-profiling linker",
    "AGATCGGAAGAGCACACGTCT": "TruSeq / NEBNext small RNA 3′ adapter",
    "TGGAATTCTCGGGTGCCAAGG": "Illumina small RNA 3′ adapter",
    "AAAAAAAAAAAAAAA": "poly(A) tail",
}
SCAN_READS = 20_000
FIVE_PRIME_G = re.compile(r"^.?(G{3,})")


def read_structure(fastq: Path, n: int = SCAN_READS) -> dict:
    """What the first `n` reads of a FASTQ carry: the 3′ linker to trim (among LINKERS, the one present in at least 30% of
    reads that sits furthest upstream, because footprint libraries can hold a ligation linker and then the sequencing
    adapter, as GSE132703 does) and the share of reads with three or more untemplated 5′ G's after the first base
    (template-switching or ligation artefacts that end-to-end alignment would reject)."""
    hits, positions, g_runs, total = Counter(), defaultdict(list), 0, 0
    with gzip.open(fastq, "rt") as handle:
        for i, line in enumerate(handle):
            if i % 4 != 1:
                continue
            total += 1
            if total > n:
                break
            seq = line.strip()
            if FIVE_PRIME_G.match(seq):
                g_runs += 1
            for linker in LINKERS:
                at = seq.find(linker[:12])
                if at >= 0:
                    hits[linker] += 1
                    positions[linker].append(at)
    total = max(min(total, n), 1)
    present = [l for l in LINKERS if hits[l] / total >= 0.3]
    adapter = min(present, key=lambda l: sum(positions[l]) / len(positions[l])) if present else ""
    return {"adapter": adapter, "adapter_name": LINKERS.get(adapter, ""), "adapter_share": round(hits[adapter] / total, 3) if adapter else 0.0,
            "five_prime_g": round(g_runs / total, 3), "reads_scanned": total}


def clean(sample: dict, fastq: Path, out: Path, threads: int, log) -> dict:
    """fastp, single-end: the linker read_structure found (else fastp's own detection), reads shorter than 20 nt
    dropped, Ribo-seq reads cut at 45 nt. Returns the adapter used, the 5′ G share and the read counts before and
    after, from fastp's JSON report."""
    trimmed, report = out / f"{sample['gsm']}.trimmed.fastq.gz", out / f"{sample['gsm']}.fastp.json"
    structure = read_structure(fastq)
    if not report.exists():
        cmd = _tool("fastp", "-i", str(fastq), "-o", str(trimmed), "-w", str(min(threads, 6)), "--length_required", "20",
                    "-j", str(report), "-h", str(out / f"{sample['gsm']}.fastp.html"))
        if structure["adapter"]:
            cmd += ["--adapter_sequence", structure["adapter"]]
        if sample["assay"] == "riboseq":
            cmd += ["--max_len1", "45"]
        _run(cmd, log)
    data = json.loads(report.read_text())
    found = (data.get("adapter_cutting") or {}).get("read1_adapter_sequence", "")
    adapter = structure["adapter"] or (found if found and found != "unspecified" else "")
    before, after = data["summary"]["before_filtering"]["total_reads"], data["summary"]["after_filtering"]["total_reads"]
    return {"trimmed": str(trimmed), "adapter": adapter, "adapter_source": "linker scan" if structure["adapter"] else "fastp auto-detection",
            "adapter_name": structure["adapter_name"], "adapter_share": structure["adapter_share"], "five_prime_g": structure["five_prime_g"],
            "reads_in": before, "reads_clean": after, "mean_length_clean": round(data["summary"]["after_filtering"]["read1_mean_length"], 1)}


def _bowtie2_summary(log_path: Path) -> dict:
    """reads, unaligned, unique, multi from a bowtie2 alignment summary."""
    text = log_path.read_text()
    grab = lambda rx: int(m.group(1)) if (m := re.search(rx, text)) else 0
    return {"reads": grab(r"(\d+) reads; of these"), "unaligned": grab(r"(\d+) \([\d.]+%\) aligned 0 times"),
            "unique": grab(r"(\d+) \([\d.]+%\) aligned exactly 1 time"), "multi": grab(r"(\d+) \([\d.]+%\) aligned >1 times")}


LOCAL_IF_G_SHARE = 0.05


def alignment_mode(adapter_found: bool, five_prime_g: float) -> tuple[str, str]:
    """End-to-end after a clean trim; local (soft-clipping, as STAR does by default in nf-core/riboseq) when no adapter
    was found or when more than 5% of reads carry untemplated 5′ G's. Returns the bowtie2 preset and the reason."""
    if not adapter_found:
        return "--very-sensitive-local", "no adapter found, so untrimmed tails are soft-clipped"
    if five_prime_g > LOCAL_IF_G_SHARE:
        return "--very-sensitive-local", f"{five_prime_g:.0%} of reads carry 3+ untemplated 5′ G's, soft-clipped"
    return "--very-sensitive", "end-to-end after adapter trimming"


def align(sample: dict, trimmed: str, mode: str, ref: dict, threads: int, out: Path, log) -> dict:
    """bowtie2 to the rRNA index (the unaligned reads are kept), then to the transcript index, sorted and indexed with
    samtools; `mode` is the preset from alignment_mode. Returns the rRNA, aligned and unaligned fractions."""
    gsm = sample["gsm"]
    bam, no_rrna = out / f"{gsm}.bam", out / f"{gsm}.no_rrna.fastq.gz"
    rrna_log, tx_log = out / f"{gsm}.rrna.log", out / f"{gsm}.transcripts.log"
    q = lambda path: shlex.quote(str(path))
    if not (out / f"{gsm}.bam.bai").exists():
        bt = f"{micromamba()} run -n {ENV} bowtie2 -p {threads} {mode}"
        st = f"{micromamba()} run -n {ENV} samtools"
        _run(f"{bt} -x {q(ref['rrna_index'])} -U {q(trimmed)} --un-gz {q(no_rrna)} > /dev/null 2> {q(rrna_log)}", log, shell=True)
        _run(f"{bt} -x {q(ref['transcripts_index'])} -U {q(no_rrna)} 2> {q(tx_log)} | {st} sort -@ 2 -m 512M -o {q(bam)} - && {st} index {q(bam)}", log, shell=True)
    r, t = _bowtie2_summary(rrna_log), _bowtie2_summary(tx_log)
    total = max(r["reads"], 1)
    return {"bam": str(bam), "reads_clean": r["reads"], "rrna": r["unique"] + r["multi"], "aligned": t["unique"] + t["multi"], "unaligned": t["unaligned"],
            "fraction_rrna": round((r["unique"] + r["multi"]) / total, 4), "fraction_aligned": round((t["unique"] + t["multi"]) / total, 4),
            "fraction_unaligned": round(t["unaligned"] / total, 4)}


# ---------------------------------------------------------------- laptop: the run

def run_laptop(accession: str, topic: str, out: Path, reads: int = 2_000_000, threads: int = 4, labels_for=None,
               progress=lambda stage, data: None, max_per_condition: int = MAX_PAIRS) -> dict:
    """The laptop tier for one series: plan, reference, fetch, clean, align, psite, count, deltate. Writes the ΔTE files
    of run_here plus metagene.png/.pdf, footprint_lengths.png/.pdf and psite_summary.json under `out`."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    log, stage, log_file = _log_to(out, progress)
    started = datetime.now(timezone.utc)
    timings = {}
    try:
        t = time.monotonic()
        stage("plan")
        records = samples.geo_records(accession)
        if not records:
            raise LookupError(f"{accession}: no sample records in GEO")
        organism = Counter(r["organism"] for r in records).most_common(1)[0][0]
        if organism not in GENCODE:
            raise ValueError(f"{accession} is {organism}; only {' and '.join(GENCODE)} have a pinned reference")
        labels = _labels(topic, accession, labels_for)
        runs = samplesheet.ena_runs(sorted({r["srx"] for r in records if r["srx"]}))
        run_of = {r["gsm"]: runs[r["srx"]][0] for r in records if r["srx"] and runs.get(r["srx"])}
        plan = choose_pairs(records, labels, {gsm: run["run"] for gsm, run in run_of.items()}, cap=max_per_condition)
        chosen = plan["samples"]
        for s in chosen:
            s["run"], s["fastq"] = run_of[s["gsm"]]["run"], run_of[s["gsm"]]["fastq"][:1]
        warnings = [FIDELITY, *pooled_factors(chosen, plan["field"])]
        if any(len(run_of[s["gsm"]]["fastq"]) == 2 for s in chosen):
            warnings.append("Paired-end libraries were aligned from their first mate only.")
        log(f"  {organism}; '{plan['field']}': {plan['levels']['case']} vs {plan['levels']['control']}; {len(chosen) // 2} pairs; {len(plan['skipped'])} libraries left out")
        progress("plan", {"organism": organism, "reference": plan["reference"], "target": plan["target"], "samples": chosen, "skipped": plan["skipped"]})
        timings["plan"] = round(time.monotonic() - t, 1)

        t = time.monotonic()
        stage("reference")
        ref = reference(organism, threads, log)
        timings["reference"] = round(time.monotonic() - t, 1)

        t = time.monotonic()
        stage("fetch", {"count": len(chosen)})
        raw = out / "reads"
        raw.mkdir(exist_ok=True)
        with ThreadPoolExecutor(process.DOWNLOADS) as pool:
            fastqs = list(pool.map(lambda s: process.fetch(s, reads, raw, log)[0], chosen))
        timings["fetch"] = round(time.monotonic() - t, 1)

        t = time.monotonic()
        stage("clean", {"count": len(chosen)})
        for i, (s, fq) in enumerate(zip(chosen, fastqs), 1):
            s.update(clean(s, fq, raw, threads, log))
            log(f"  {s['gsm']}: adapter {s['adapter'] or 'not found'} ({s['adapter_name'] or s['adapter_source']}, in {s['adapter_share']:.0%} of scanned reads); "
                f"5′ G-runs in {s['five_prime_g']:.1%}; {s['reads_clean']:,} of {s['reads_in']:,} reads kept, mean {s['mean_length_clean']} nt")
            progress("clean", {"count": len(chosen), "done": i})
        timings["clean"] = round(time.monotonic() - t, 1)

        t = time.monotonic()
        stage("align", {"count": len(chosen)})
        bams = out / "bam"
        bams.mkdir(exist_ok=True)
        for i, s in enumerate(chosen, 1):
            mode, why = alignment_mode(bool(s["adapter"]), s["five_prime_g"])
            s.update(align(s, s["trimmed"], mode, ref, threads, bams, log), mode=mode, mode_reason=why)
            log(f"  {s['gsm']} ({s['assay']}, {mode}: {why}): rRNA {s['fraction_rrna']:.1%}, aligned {s['fraction_aligned']:.1%}, unaligned {s['fraction_unaligned']:.1%}")
            progress("align", {"count": len(chosen), "done": i})
        timings["align"] = round(time.monotonic() - t, 1)
        if lost := [s for s in chosen if s["fraction_unaligned"] > 0.5]:
            warnings.append(f"{len(lost)} librar{'y' if len(lost) == 1 else 'ies'} ({', '.join(s['gsm'] for s in lost)}) had more than half of their reads match neither rRNA nor a "
                            "protein-coding transcript; such reads are usually other non-coding RNA (tRNA, snoRNA) that the one-transcript-per-gene reference does not hold, "
                            "so the counts rest on the smaller mRNA fraction.")

        t = time.monotonic()
        stage("psite")
        ribo = [s for s in chosen if s["assay"] == "riboseq"]
        _run(_tool("python", str(PSITE_SCRIPT), "psite", "--cds", ref["cds"], "--out", str(out), "--min-length", str(MIN_LENGTH), "--max-length", str(MAX_LENGTH),
                   *(f"{s['gsm']}={s['bam']}" for s in ribo)), log)
        psite = json.loads((out / "psite_summary.json").read_text())
        for s in ribo:
            s["psite"] = psite["libraries"][s["gsm"]]
            log(f"  {s['gsm']}: periodicity {s['psite']['periodicity']:.3f}, {s['psite']['psites']:,} P-sites, offsets {s['psite']['offsets']}")
        timings["psite"] = round(time.monotonic() - t, 1)

        t = time.monotonic()
        stage("count")
        rna = [s for s in chosen if s["assay"] == "rnaseq"]
        _run(_tool("python", str(PSITE_SCRIPT), "count", "--cds", ref["cds"], "--out", str(out), *(f"{s['gsm']}={s['bam']}" for s in rna)), log)
        tables = {s["gsm"]: read_counts(out / "counts" / f"{s['gsm']}.count") for s in chosen}
        genes, more = write_counts(tables, [s["gsm"] for s in chosen], out / "counts.tsv")
        warnings += more
        write_samples(chosen, out / "samples.tsv")
        for s in chosen:
            s["counted"] = sum(tables[s["gsm"]].values())
        log(f"  {genes} genes × {len(chosen)} libraries; counted reads per library: " + ", ".join(f"{s['gsm']} {s['counted']:,}" for s in chosen))
        timings["count"] = round(time.monotonic() - t, 1)

        t = time.monotonic()
        stage("deltate")
        summary = deltate(out, plan["reference"], plan["target"], log)
        timings["deltate"] = round(time.monotonic() - t, 1)

        finished = datetime.now(timezone.utc)
        tools = {"locus riboseq": "laptop", "fastp": _version(ENV, ["fastp", "--version"]), "bowtie2": ref["bowtie2"], "samtools": _version(ENV, ["samtools", "--version"]),
                 "pysam": psite["versions"]["pysam"], "matplotlib": psite["versions"]["matplotlib"], **summary["versions"]}
        per_library = [{k: s.get(k) for k in ("gsm", "title", "srx", "run", "fastq", "assay", "pair", "condition", "adapter", "adapter_name", "adapter_source",
                                                 "adapter_share", "five_prime_g", "mode", "mode_reason", "reads_in", "reads_clean", "mean_length_clean",
                                                 "fraction_rrna", "fraction_aligned", "fraction_unaligned", "counted", "psite")} for s in chosen]
        periodicity = {s["gsm"]: s["psite"]["periodicity"] for s in ribo}
        manifest = {
            "accession": accession, "tier": "laptop", "pipeline": "locus riboseq", "organism": organism, "topic": topic, "tools": tools, "fidelity": FIDELITY,
            "reference": {"source": ref["release"], **{k: ref[k] for k in ("sources", "genes", "rrna_genes", "dir")}, "built_seconds": ref["seconds"]},
            "reads_per_fastq": reads, "subsampled": True, "psite_rule": f"5′-end offset per read length {MIN_LENGTH}–{MAX_LENGTH} nt = mode of the distance to the start codon (the most abundant length's offset when fewer than 200 reads or more than 3 nt away from it), then corrected to the nearest value that puts the dominant in-CDS frame of that length in frame 0 (riboWaltz-style); CDS counts exclude the first 15 and last 5 codons; MAPQ ≥ 10",
            "contrast": {"field": plan["field"], "reference": plan["reference"], "target": plan["target"], "levels": plan["levels"]},
            "samples": per_library, "skipped": plan["skipped"], "warnings": warnings, "stage_seconds": timings,
            "started": started.isoformat(timespec="seconds"), "finished": finished.isoformat(timespec="seconds"), "seconds": round((finished - started).total_seconds()),
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        lengths = ", ".join(f"{s['gsm']} {s['psite']['modal_length']} nt" for s in ribo)
        result = {
            "accession": accession, "data_type": "riboseq", "tier": "laptop", "title": _result_title(plan, chosen, summary),
            "summary": [
                f"{reads:,} reads per library were subsampled from ENA; rRNA took {min(s['fraction_rrna'] for s in ribo):.0%}–{max(s['fraction_rrna'] for s in ribo):.0%} of the Ribo-seq reads and "
                f"{min(s['fraction_aligned'] for s in chosen):.0%}–{max(s['fraction_aligned'] for s in chosen):.0%} of all reads aligned to the one-transcript-per-gene transcriptome.",
                "Three-nucleotide periodicity (share of P-sites in frame 0 within CDSs) per Ribo-seq library: " + ", ".join(f"{g} {p:.2f}" for g, p in periodicity.items()) + ".",
                *_summary_sentences(summary, chosen, plan),
            ],
            "figures": [
                {"file": "metagene.png", "title": "Metagene", "caption": f"P-site coverage around start and stop codons, pooled over {len(ribo)} Ribo-seq libraries, coloured by reading frame; periodicity per library " + ", ".join(f"{g} {p:.2f}" for g, p in periodicity.items()) + "."},
                {"file": "footprint_lengths.png", "title": "Footprint lengths", "caption": f"Read-length distribution after trimming per Ribo-seq library; modal lengths {lengths}."},
                {"file": "deltate_scatter.png", "title": "ΔTE", "caption": _scatter_caption(summary, plan)},
            ],
            "tables": [{"file": "deltate_results.tsv", "title": "ΔTE per gene"}, {"file": "counts.tsv", "title": "CDS counts per library"}],
            "warnings": warnings, "contrast": manifest["contrast"],
            "samples": [{"gsm": s["gsm"], "title": s["title"], "assay": s["assay"], "pair": s["pair"], "condition": s["condition"], "fraction_rrna": s["fraction_rrna"],
                         "fraction_aligned": s["fraction_aligned"], "periodicity": periodicity.get(s["gsm"])} for s in chosen],
            "skipped": plan["skipped"], "classes": summary["classes"], "genes_tested": summary["genes_tested"], "periodicity": periodicity,
            "files": files_of(out), "seconds": manifest["seconds"], "stage_seconds": timings, "tools": tools,
        }
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        stage("done", result)
        return result
    finally:
        log_file.close()


# ---------------------------------------------------------------- requirements and the cluster kit

def ena_stats(experiments: list[str]) -> dict[str, dict]:
    """read_count and fastq bytes per SRA experiment, summed over its runs, from ENA."""
    stats: dict[str, dict] = defaultdict(lambda: {"reads": 0, "bytes": 0})
    for start in range(0, len(experiments), 100):
        query = " OR ".join(f'experiment_accession="{x}"' for x in experiments[start:start + 100])
        response = samplesheet._ena_post({"result": "read_run", "query": query, "fields": "experiment_accession,read_count,fastq_bytes", "format": "tsv", "limit": 0})
        for row in csv.DictReader(io.StringIO(response.text), delimiter="\t"):
            stats[row["experiment_accession"]]["reads"] += int(row.get("read_count") or 0)
            stats[row["experiment_accession"]]["bytes"] += sum(int(b) for b in (row.get("fastq_bytes") or "0").split(";") if b)
    return dict(stats)


def _human_time(minutes: float) -> str:
    if minutes < 1.5:
        return "about a minute"
    if minutes < 90:
        return f"about {int(round(minutes / 5.0) * 5) or 5} min"
    return f"about {minutes / 60:.0f} h"


def _human_bytes(n: float) -> str:
    return f"{n / 1e9:.0f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB" if n >= 1e6 else "under 1 MB"


def requirements(reads_total: int, bytes_total: int, libraries: int) -> dict:
    """Time, memory and disk for the three rows, as short strings. Calibrated on GSE132703 on pgx (18 October 2026, 6 threads):
    here: 16 count tables (1.3 MB) joined and tested in 23 s, peak RSS 0.96 GB. Laptop: 16 libraries × 2,000,000 reads
    (32 M) in 240 s: fetch 23 s, fastp 42 s, bowtie2 147 s, P-sites 9 s, counts 7 s, DESeq2 11 s; the reference built once
    in 22 s; peak RSS 1.13 GB; 3.4 GB on disk (reads, trimmed reads, BAMs). A 4-thread laptop on a slower link is budgeted
    at twice that: 2 min + 0.25 min per million subsampled reads (at most 2 M per library), 1.5 GB, 220 MB per library +
    250 MB reference. Cluster (not measured tonight; nf-core/riboseq with STAR): 2 h + 1 h per 50 M reads on 16 cores,
    64 GB because a human STAR index needs about 32 GB, disk 4 × the FASTQs + 20 GB of work."""
    libs = max(libraries, 1)
    laptop_reads = min(reads_total, libs * 2_000_000)
    return {
        "here": {"time": "under a minute", "memory": "about 1 GB", "disk": "under 50 MB"},
        "laptop": {"time": _human_time(2 + 0.25 * laptop_reads / 1e6), "memory": "about 1.5 GB", "disk": _human_bytes(220e6 * libs + 250e6)},
        "cluster": {"time": _human_time(120 + 60 * reads_total / 50e6), "memory": "64 GB per job (STAR index 32 GB)", "disk": _human_bytes(4 * bytes_total + 20e9)},
    }


def kit_files(accession: str, organism: str, reads_total: int, libraries: int, sheets: dict[str, str]) -> dict[str, str]:
    """The cluster kit's texts: samplesheet.build's files plus run.sbatch, nextflow.config and README.md."""
    spec = GENCODE.get(organism, GENCODE["Homo sapiens"])
    hours = max(4, math.ceil(2 + reads_total / 50e6))
    contrasts = " --contrasts contrasts.csv" if "contrasts.csv" in sheets else ""
    sbatch = f"""#!/bin/bash
#SBATCH --job-name={accession}-riboseq
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time={hours}:00:00
#SBATCH --output={accession}-riboseq.%j.log
# nf-core/riboseq 1.2.0 for {accession} ({organism}; {libraries} libraries, {reads_total:,} reads in ENA).
# Walltime = 2 h + 1 h per 50 M reads for the head job; the pipeline submits its own Slurm jobs through nextflow.config.
# Written by locus; not run on a cluster. Fill in the module names of your site, then: sbatch run.sbatch
module load nextflow            # placeholder: your site's Nextflow module (>= 24.04)
module load apptainer           # placeholder: your site's Apptainer/Singularity module
export NXF_APPTAINER_CACHEDIR=${{NXF_APPTAINER_CACHEDIR:-$HOME/.apptainer/nf-core}}
export NXF_OPTS="-Xms1g -Xmx4g"

# {spec['release']}: the same release the laptop tier aligns to, so gene sets match between tiers.
FASTA={spec['genome']}
GTF={spec['gtf']}

nextflow run nf-core/riboseq -r 1.2.0 -profile apptainer,slurm -c nextflow.config \\
  --input samplesheet.csv{contrasts} \\
  --fasta "$FASTA" --gtf "$GTF" \\
  --outdir results -resume
"""
    config = f"""// nf-core/riboseq on Slurm with Apptainer, written by locus for {accession}.
profiles {{
    slurm {{
        process.executor = 'slurm'
        process.queue = 'batch'          // placeholder: your partition
        // process.clusterOptions = '--account=YOUR_ACCOUNT'
        executor.queueSize = 50
        executor.submitRateLimit = '10/1min'
    }}
}}
apptainer {{
    enabled = true
    autoMounts = true
    cacheDir = System.getenv('NXF_APPTAINER_CACHEDIR') ?: "${{HOME}}/.apptainer/nf-core"
}}
process {{
    resourceLimits = [ cpus: 16, memory: 64.GB, time: {hours}.h ]
    withName: 'STAR_GENOMEGENERATE' {{ memory = 48.GB }}
}}
"""
    readme = f"""# {accession}: nf-core/riboseq kit (cluster tier)

Files: samplesheet.csv, contrasts.csv (when a contrast can run), README.txt (how the labels were read, from samplesheet.build),
run.sbatch, nextflow.config.

Why a laptop cannot run this: nf-core/riboseq aligns with STAR, and a {organism} genome index needs about 32 GB of memory;
the pipeline also runs Ribo-TISH, riboWaltz and anota2seq per contrast. A 16 GB laptop runs the locus laptop tier instead
(bowtie2 to one GENCODE transcript per gene, subsampled reads), which is a lower-fidelity approximation.

Reference: {spec['release']} primary assembly and annotation (URLs in run.sbatch), the release the laptop tier uses.
Walltime in run.sbatch: {hours} h for {reads_total:,} reads across {libraries} libraries (2 h + 1 h per 50 M reads).

This kit was written by locus on {datetime.now(timezone.utc).date()} and was NOT run on a cluster. Check the module
names, the partition and the account in run.sbatch and nextflow.config before submitting.
"""
    return {**sheets, "run.sbatch": sbatch, "nextflow.config": config, "README.md": readme}


def cluster_kit(accession: str, topic: str, labels_for=None) -> dict[str, str]:
    """File name -> text for the cluster zip: samplesheet.build's files (via agent.samplesheet_files when the labels
    come from the app) plus run.sbatch, nextflow.config and README.md."""
    records = samples.geo_records(accession)
    if labels_for is None:
        from . import agent

        sheets = agent.samplesheet_files(accession, topic)
    else:
        labels = _labels(topic, accession, labels_for)
        runs = samplesheet.ena_runs(sorted({r["srx"] for r in records if r["srx"]}))
        sheets = samplesheet.build(accession, records, labels, runs, assay.library_types(accession))
    organism = Counter(r["organism"] for r in records).most_common(1)[0][0] if records else "Homo sapiens"
    stats = ena_stats(sorted({r["srx"] for r in records if r["srx"]}))
    kept = sum(1 for line in sheets["samplesheet.csv"].splitlines()[1:] if line.strip())
    return kit_files(accession, organism, sum(s["reads"] for s in stats.values()), kept, sheets)
