"""Where locus's datasets lack the sample metadata researchers filter on: by research domain, year and data type.

Reads the audit (scripts/metadata_audit.py) and the whole index, weights each audited dataset back to its repository's
size, and writes figures, tables and the numbers the report quotes.

    uv run python scripts/metadata_gaps_report.py --audit runs/metadata-audit --out docs/metadata-gaps
"""

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from metadata_audit import DB
from metadata_audit import fields as fields_of

# First match wins, so the specific domains come before the broad ones.
DOMAINS = [
    ("Cancer", r"cancer|tumou?r|carcinom|leukaemi|leukemi|lymphom|melanom|gliom|glioblastom|sarcom|myelom|neoplas|metasta|oncogen"),
    ("Neuroscience", r"\bbrain|neuro|neuron|cortex|cortical|hippocamp|alzheimer|parkinson|autism|schizophren|spinal cord|\bglia|synap|cerebr|retina"),
    ("Microbiome & environment", r"microbiom|microbiota|metagenom|16s|amplicon|\bsoil|marine|seawater|sediment|wastewater|rhizospher|environmental sample|ocean|lake|river"),
    ("Infection & immunity", r"infect|virus|viral|pathogen|immun|t.cells?\b|b.cells?\b|macrophag|cytokin|sars-cov|covid|\bhiv\b|influenza|tubercul|malaria|sepsis|vaccin|inflamm|antibod"),
    ("Cardiometabolic & organ", r"\bheart|cardi|vascular|diabet|obes|insulin|adipo|\bliver|hepat|kidney|renal|atheroscl|lipid|metabolic|muscle|\blung|pulmonar|intestin|colitis"),
    ("Development & stem cells", r"embryo|stem cell|\bipsc|pluripoten|differentiat|development|organoid|zygot|germ cell|spermat|oocyte|regenerat"),
    ("Plant & agriculture", r"\bplant|arabidopsis|\brice\b|oryza|maize|zea mays|wheat|triticum|soybean|glycine max|\bleaf|leaves|\broots?\b|\bseed|crop|tomato|cultivar|drought|grain"),
    ("Microbial genomes", r"\bstrain|isolate|whole genome|genome sequenc|assembl|bacteri|escherichia|salmonella|staphylococc|streptococc|klebsiella|yeast|saccharomyces|mycobacter|fung"),
]
OTHER = "Other / basic biology"

DATATYPES = [
    ("Proteomics", lambda s, m, t: s in ("PRIDE", "MassIVE", "iProX", "jPOST", "PeptideAtlas", "PanoramaPublic") or "proteom" in m),
    ("Metabolomics", lambda s, m, t: s in ("MetabolomicsWorkbench", "MetaboLights") or "metabol" in m),
    ("Single-cell", lambda s, m, t: s == "CELLxGENE" or re.search(r"single.?cell|single.?nucle|scrna|snrna|10x genomics", t + " " + m)),
    ("Amplicon & metagenomics", lambda s, m, t: re.search(r"amplicon|metagenom", m)),
    ("Microarray", lambda s, m, t: "by array" in m or "array" in m and "rna-seq" not in m),
    ("Epigenomics", lambda s, m, t: re.search(r"binding/occupancy|chip|methylation|bisulfite|atac|chromatin|mnase|dnase|hi-c", m)),
    ("Genome & variation", lambda s, m, t: s in ("EVA", "dbGaP") or re.search(r"\bwgs\b|\bwxs\b|exome|genotyp|variation|wga|snp", m)),
    ("Bulk RNA-seq", lambda s, m, t: re.search(r"rna-seq|expression profiling by high throughput|transcriptom|non-coding rna profiling|mirna|ncrna|rna-seq of", m)),
]
OTHER_TYPE = "Other assays"

YEARS = [(0, 2010, "≤2010"), (2011, 2015, "2011–15"), (2016, 2019, "2016–19"), (2020, 2022, "2020–22"), (2023, 2024, "2023–24"), (2025, 2100, "2025–26")]
VERTEBRATE = re.compile(r"homo sapiens|human|mus musculus|mouse|rattus|\brat\b|danio|zebrafish|sus scrofa|bos taurus|gallus|macaca|ovis|equus|canis", re.I)
LIVE = ("GEO", "ENA", "ArrayExpress", "PRIDE", "MetabolomicsWorkbench", "MetaboLights")
DESCRIPTIVE = ["tissue_cell", "disease_condition", "intervention", "age_stage", "sex", "environment_host"]
# The fields a researcher in each kind of study needs; a field that does not apply is not counted as missing.
MICROBIAL = ("Microbiome & environment", "Microbial genomes")
LABELS = {"tissue_cell": "Tissue, cell type\nor sample source", "disease_condition": "Disease, condition\nor group", "intervention": "Treatment, genotype\nor strain",
          "age_stage": "Age, stage\nor time", "sex": "Sex\n(vertebrates)", "environment_host": "Host or environment\n(microbial)",
          "sample_table": "Any per-sample\nattribute", "paper": "Linked\npaper", "raw_files": "Raw files\nlisted", "organism": "Organism"}

# Validated categorical slots (dataviz reference palette, light), then a neutral for "Other".
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
OTHER_GREY = "#bdbbb4"
SURFACE, INK, MUTED = "#fcfcfb", "#0b0b0b", "#52514e"
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def domain_of(text: str, vertebrate: bool = False) -> str:
    # A mouse "strain" is not a microbial genome.
    return next((name for name, rx in DOMAINS if re.search(rx, text) and not (vertebrate and name == "Microbial genomes")), OTHER)


def datatype_of(source: str, modality: str, text: str) -> str:
    return next((name for name, test in DATATYPES if test(source, modality.lower(), text)), OTHER_TYPE)


def year_of(published: str | None) -> str | None:
    y = int(published[:4]) if published and published[:4].isdigit() else None
    return next((label for lo, hi, label in YEARS if y and lo <= y <= hi), None)


def classify_index() -> dict[str, dict]:
    db = sqlite3.connect(DB)
    out = {}
    for acc, source, title, summary, organism, modality, published, papers in db.execute(
            "select accession, source, title, summary, organism, modality, published, papers from datasets"):
        text = f"{title} {summary[:1500]}".lower()
        vertebrate = bool(VERTEBRATE.search(f"{organism} {title}"))
        out[acc] = {"source": source, "domain": domain_of(text, vertebrate), "datatype": datatype_of(source, modality, text),
                    "year": year_of(published), "vertebrate": vertebrate,
                    "paper": papers not in ("", "[]"), "short_summary": len(summary) < 200}
    return out


def applicable(field: str, meta: dict) -> bool:
    if meta["domain"] in MICROBIAL:
        return field in ("tissue_cell", "intervention", "environment_host")
    if field == "environment_host":
        return False
    if field == "sex":
        return meta["vertebrate"]
    if field == "disease_condition":
        return meta["domain"] != "Plant & agriculture"
    return True


def poor(fields: dict, meta: dict) -> tuple[bool, int, int]:
    """Metadata-poor: at most one of the descriptive fields that apply to this kind of study is stated (per sample or for the study)."""
    fs = [f for f in DESCRIPTIVE if applicable(f, meta)]
    stated = sum(fields[f] != "missing" for f in fs)
    return stated <= 1, stated, len(fs)


def weighted_rate(rows: list[dict], key, weights) -> float:
    w = np.array([weights[r["source"]] for r in rows])
    v = np.array([key(r) for r in rows], dtype=float)
    return float((w * v).sum() / w.sum()) if len(rows) else float("nan")


def bootstrap(rows: list[dict], group: str, weights, reps: int = 400, seed: int = 7) -> dict[str, tuple[float, float]]:
    """Per-group 90% interval for the weighted metadata-poor rate, resampling within each repository."""
    rng = np.random.default_rng(seed)
    by_source = defaultdict(list)
    for r in rows:
        by_source[r["source"]].append(r)
    draws = defaultdict(list)
    for _ in range(reps):
        sample = [s[i] for s in by_source.values() for i in rng.integers(0, len(s), len(s))]
        acc = defaultdict(lambda: [0.0, 0.0])
        for r in sample:
            acc[r[group]][0] += weights[r["source"]] * r["poor"]
            acc[r[group]][1] += weights[r["source"]]
        for g, (num, den) in acc.items():
            draws[g].append(num / den)
    return {g: (float(np.percentile(v, 5)), float(np.percentile(v, 95))) for g, v in draws.items()}


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#d6d4cd")
    ax.tick_params(colors=MUTED, labelsize=9, length=0)


def fold(shares: dict[str, float], keep: int = 5, order: list[str] | None = None) -> list[tuple[str, float]]:
    if order:
        return [(k, shares[k]) for k in order if shares.get(k)]
    ranked = sorted(shares.items(), key=lambda kv: -kv[1])
    head, tail = ranked[:keep], ranked[keep:]
    return head + ([(f"{len(tail)} more", sum(v for _, v in tail))] if tail else [])


def pies(groups: dict[str, dict[str, float]], counts: dict[str, dict[str, float]], path: Path, total_poor: float) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.6), facecolor=SURFACE)
    years = [label for *_, label in YEARS] + ["no date"]
    for ax, (title, shares) in zip(axes, groups.items()):
        chronological = "year" in title
        parts = fold(shares, order=years if chronological else None)
        # Years are ordered, so they take one hue light to dark; categories take the fixed categorical order.
        ramp = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]
        colours = [OTHER_GREY if name.endswith("more") or name == "no date" else ramp[i] if chronological else SLOTS[i]
                   for i, (name, _) in enumerate(parts)]
        values = [v for _, v in parts]
        wedges, _ = ax.pie(values, colors=colours, startangle=90, counterclock=False,
                           wedgeprops={"linewidth": 2, "edgecolor": SURFACE, "width": 0.42})
        for w, (name, v) in zip(wedges, parts):
            angle = np.deg2rad((w.theta2 + w.theta1) / 2)
            x, y = np.cos(angle), np.sin(angle)
            ax.annotate(f"{name}\n{v / sum(values):.0%}  ({v / 1000:,.0f}k)", xy=(0.8 * x, 0.8 * y), xytext=(1.3 * x, 1.25 * y),
                        ha="left" if x >= 0 else "right", va="center", fontsize=9, color=INK,
                        arrowprops={"arrowstyle": "-", "color": "#a8a59c", "lw": 0.8})
        ax.set_title(title, fontsize=12, color=INK, pad=22, loc="center")
    fig.suptitle(f"Where the metadata-poor datasets are: an estimated {total_poor / 1000:,.0f}k of the {sum(counts['all'].values()) / 1000:,.0f}k "
                 "datasets in GEO, ENA, ArrayExpress, PRIDE and the two metabolomics repositories", fontsize=12.5, color=INK, x=0.02, ha="left")
    fig.text(0.02, 0.035, "Metadata-poor: at most one of the fields that apply is stated in the repository record. Biomedical and other studies: "
             "tissue/cell type, disease/condition (not plants), treatment/genotype, age/stage, sex (vertebrates).",
             fontsize=8.5, color=MUTED)
    fig.text(0.02, 0.01, "Microbiome, environmental and microbial-genome studies: sample source, strain/treatment, host or environment. "
             "Audit of randomly drawn datasets, weighted to each repository's size; counts are estimates for the whole index.", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.07, 1, 0.92))
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def rate_bars(panels: dict[str, list[tuple[str, float, tuple[float, float], int]]], path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2), facecolor=SURFACE, gridspec_kw={"wspace": 0.75})
    for ax, (title, rows) in zip(axes, panels.items()):
        style(ax)
        names = [r[0] for r in rows]
        ys = np.arange(len(rows))[::-1]
        rates = [r[1] for r in rows]
        lo = [r[1] - r[2][0] for r in rows]
        hi = [r[2][1] - r[1] for r in rows]
        ax.barh(ys, rates, height=0.6, color=SLOTS[0])
        ax.errorbar(rates, ys, xerr=[lo, hi], fmt="none", ecolor="#52514e", elinewidth=1, capsize=0)
        for y, r in zip(ys, rows):
            ax.text(min(r[2][1] + 0.02, 1.02), y, f"{r[1]:.0%}  n={r[3]}", va="center", fontsize=8.5, color=MUTED)
        ax.set_yticks(ys, names, fontsize=9.5, color=INK)
        ax.set_xlim(0, 1.18)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1], ["0", "25%", "50%", "75%", "100%"])
        ax.xaxis.grid(True, color="#ebe9e4", lw=0.8)
        ax.set_axisbelow(True)
        ax.set_title(title, fontsize=12, color=INK, loc="left")
    fig.suptitle("Share of datasets that are metadata-poor, with 90% bootstrap intervals (n = audited datasets)",
                 fontsize=12.5, color=INK, x=0.02, ha="left")
    fig.subplots_adjust(left=0.13, right=0.98, top=0.86, bottom=0.08)
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def heatmap(matrix: np.ndarray, rows: list[str], cols: list[str], path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(13.5, 0.5 * len(rows) + 2.4), facecolor=SURFACE)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("blues", BLUES)
    ax.imshow(matrix, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i in range(len(rows)):
        for j in range(len(cols)):
            v = matrix[i, j]
            ax.text(j, i, "–" if np.isnan(v) else f"{v:.0%}", ha="center", va="center", fontsize=9,
                    color="white" if v > 0.55 else INK)
    ax.set_xticks(range(len(cols)), cols, rotation=0, fontsize=9, color=INK, wrap=True)
    ax.set_yticks(range(len(rows)), rows, fontsize=9.5, color=INK)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(len(cols) + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(len(rows) + 1) - 0.5, minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    ax.xaxis.tick_top()
    ax.set_title(title, fontsize=12, color=INK, loc="left", pad=34)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def main(audit_dir: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    index = classify_index()
    totals = json.loads((audit_dir / "draw.json").read_text())["totals"]
    audited = [json.loads(line) for line in (audit_dir / "audit.jsonl").open()]
    rows = []
    for a in audited:
        if a.get("error") or a["source"] not in LIVE or a.get("level") != "live record":
            continue
        meta = index[a["accession"]]
        found = fields_of(a)
        is_poor, stated, n_applicable = poor(found, meta)
        rows.append({**meta, **{f"f_{k}": v for k, v in found.items()}, "accession": a["accession"], "poor": is_poor,
                     "stated": stated, "applicable": n_applicable, "sdrf": a.get("sdrf", False)})
    n_by_source = defaultdict(int)
    for r in rows:
        n_by_source[r["source"]] += 1
    weights = {s: totals[s] / n for s, n in n_by_source.items()}
    population = sum(totals[s] for s in n_by_source)

    # Index-wide composition (no sampling): how many datasets each group holds in the live repositories.
    counts = {"all": defaultdict(float)}
    for g in ("domain", "datatype", "year"):
        counts[g] = defaultdict(float)
    for meta in index.values():
        if meta["source"] in n_by_source:
            counts["all"][meta["source"]] += 1
            for g in ("domain", "datatype", "year"):
                counts[g][meta[g] or "no date"] += 1

    # Estimated number of metadata-poor datasets per group (weighted audit).
    poor_n = {g: defaultdict(float) for g in ("domain", "datatype", "year")}
    for r in rows:
        if r["poor"]:
            for g in poor_n:
                poor_n[g][r[g] or "no date"] += weights[r["source"]]
    total_poor = sum(poor_n["domain"].values())
    pies({"By research domain": poor_n["domain"], "By year published": poor_n["year"], "By data type": poor_n["datatype"]},
         counts, out / "poor-share-pies.png", total_poor)

    panels, summary = {}, {"population": population, "audited_live": len(rows), "estimated_poor": total_poor,
                           "poor_rate": weighted_rate(rows, lambda r: r["poor"], weights), "groups": {}}
    order = {"year": [label for *_, label in YEARS]}
    for g, title in (("domain", "Research domain"), ("year", "Year published"), ("datatype", "Data type")):
        cis = bootstrap(rows, g, weights)
        groups = defaultdict(list)
        for r in rows:
            groups[r[g] or "no date"].append(r)
        stats = [(name, weighted_rate(rs, lambda r: r["poor"], weights), cis.get(name, (np.nan, np.nan)), len(rs))
                 for name, rs in groups.items() if len(rs) >= 15]
        stats.sort(key=lambda s: order[g].index(s[0]) if g in order and s[0] in order[g] else -s[1])
        panels[title] = stats
        summary["groups"][g] = {name: {"poor_rate": rate, "ci90": ci, "n_audited": n, "estimated_poor": poor_n[g].get(name, 0),
                                       "datasets": counts[g].get(name, 0)} for name, rate, ci, n in stats}
    rate_bars(panels, out / "poor-rate-bars.png")

    # Field by field: which ones are most often absent, per domain (weighted share not stated anywhere in the record).
    fields = DESCRIPTIVE + ["sample_table", "paper"]
    domains = [d for d, _ in sorted(summary["groups"]["domain"].items(), key=lambda kv: -kv[1]["estimated_poor"])]
    matrix = np.full((len(domains) + 1, len(fields)), np.nan)
    field_rates = {}
    for j, f in enumerate(fields):
        everyone = [r for r in rows if f not in DESCRIPTIVE or applicable(f, r)]
        matrix[-1, j] = field_rates[f] = weighted_rate(everyone, lambda r: r[f"f_{f}"] == "missing", weights)
        for i, d in enumerate(domains):
            sub = [r for r in everyone if r["domain"] == d]
            if len(sub) >= 15:
                matrix[i, j] = weighted_rate(sub, lambda r: r[f"f_{f}"] == "missing", weights)
    summary["field_missing"] = field_rates
    summary["field_per_sample"] = {f: weighted_rate([r for r in rows if applicable(f, r)], lambda r: r[f"f_{f}"] == "samples", weights)
                                   for f in DESCRIPTIVE}
    heatmap(matrix, domains + ["All live repositories"], [LABELS[f] for f in fields],
            out / "missing-fields-heatmap.png", "Share of datasets whose repository record does not state each field")

    # Per repository, so the curation effort can be pointed at a source.
    summary["by_source"] = {s: {"n_audited": n_by_source[s], "datasets": totals[s],
                                "poor_rate": weighted_rate([r for r in rows if r["source"] == s], lambda r: r["poor"], weights),
                                **{f"missing_{f}": weighted_rate([r for r in rows if r["source"] == s and (f not in DESCRIPTIVE or applicable(f, r))],
                                                                 lambda r: r[f"f_{f}"] == "missing", weights) for f in fields}}
                            for s in n_by_source}
    summary["pride_sdrf"] = sum(r["sdrf"] for r in rows if r["source"] == "PRIDE") / max(1, n_by_source["PRIDE"])
    # Repositories locus reads only from its own index (no live adapter yet).
    summary["index_only"] = {s: totals[s] for s in totals if s not in LIVE}
    # Index-wide, no sampling: linked papers by year.
    by_year = defaultdict(lambda: [0, 0])
    for meta in index.values():
        if meta["year"]:
            by_year[meta["year"]][0] += not meta["paper"]
            by_year[meta["year"]][1] += 1
    summary["index_no_paper_by_year"] = {y: m / n for y, (m, n) in by_year.items()}
    summary["index_domain_counts"] = dict(counts["domain"])
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    with (out / "audited.tsv").open("w") as f:
        keys = ["accession", "source", "domain", "datatype", "year", "vertebrate", "poor", "stated", "applicable", "sdrf"] + [f"f_{k}" for k in LABELS]
        f.write("\t".join(keys) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(k, "")) for k in keys) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k in ("population", "audited_live", "estimated_poor", "poor_rate", "field_missing",
                                                                 "field_per_sample", "pride_sdrf")}, indent=1, default=float))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=Path("runs/metadata-audit"))
    parser.add_argument("--out", type=Path, default=Path("docs/metadata-gaps"))
    args = parser.parse_args()
    main(args.audit, args.out)
