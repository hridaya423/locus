#!/usr/bin/env python3
"""
tese_lysoip_analysis.py — LysoTag lyso-IP proteomics analysis for PINK1 TESE mice
==================================================================================

Analyzes lyso-IP proteomics exports (IP / whole-cell / mock-bead intensities) and
produces the core TESE-vs-WT results established in the project notebook:

  1. tag-vs-tag TESE effect        (lyso-IP eluate, TESE vs WT)
  2. input-normalized enrichment   (tag effect minus whole-cell abundance effect)
  3. canonical mock-controlled dod (per-replicate input-normalized enrichment
                                    interaction; beads-only mock IPs subtracted)
  4. batch comparison              (proteins TESE-high replicated across batches)
  5. receptor / module summary     (optional, via --receptors / --modules)

Usage
-----
  # single dataset
  python tese_lysoip_analysis.py --input "2 batch young Lyso IP TESE.csv" \
      --name young_b2 --outdir results_young_b2

  # several datasets + cross-batch summary
  python tese_lysoip_analysis.py \
      --input "batvh 1 young lyso ip tese.csv" --name young_b1 \
      --input "2 batch young Lyso IP TESE.csv" --name young_b2 \
      --input "1 batch Lysol ip tese aging.csv" --name aging_b1 \
      --outdir results_all

  # with mitochondrial annotation and receptor/module tables
  python tese_lysoip_analysis.py --input ... --name ... \
      --mito-annot diff_results_mito_fraction.csv \
      --receptors receptors.txt --modules modules.tsv --outdir results_all

Input format
------------
CSV export with per-protein rows and columns:
  - 'Genes'                       gene symbol(s)
  - 'N.Sequences'                 peptide count (optional)
  - 'log2FC', '-log10 P.Value'    precomputed WT-vs-TESE comparison (sign is
                                  flipped internally; TESE-positive = positive)
  - intensity columns named       <prefix>_IP_LTKI.N   (TESE lyso-IP)
                                  <prefix>_IP_LTWT.N   (WT lyso-IP)
                                  <prefix>_IP_WTKI.N   (TESE mock beads)
                                  <prefix>_IP_WTWT.N   (WT mock beads)
                                  <prefix>_WC_LTKI.N   (TESE whole cell)
                                  <prefix>_WC_LTWT.N   (WT whole cell)
  where <prefix> is e.g. 'Set1_Brain' (set with --prefix) and N = replicate index.
  Replicates are paired by column index within each group pair.

Notes
-----
  * WC intensities may be linear-scale; everything is log2-transformed here.
  * dod p-values are nominal (uncorrected, one-sample t-test on per-replicate
    contrast values).
  * Sign convention: positive = TESE-high everywhere.

Requires: pandas, numpy, scipy
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# Default receptor panel (mitophagy/autophagy receptors and mediators)
DEFAULT_RECEPTORS = [
    "NBR1", "SQSTM1", "OPTN", "TBK1", "CALCOCO2", "TAX1BP1", "FUNDC1",
    "BNIP3", "BNIP3L", "BCL2L13", "PHB2", "FKBP8", "NCOA4", "RETREG1",
    "ATL3", "TEX264", "CCPG1", "SEC62", "STBD1", "TRIM13", "AMFR",
    "FBXO27", "BAG3", "MUL1", "PGAM5", "ARIH1", "SMURF1", "VCP",
    "PINK1", "PARK2", "MFN1", "MFN2",
]

# Default modules (module name -> genes). OXPHOS/TCA/mitophagy are mouse KEGG
# members used in the project; edit or supply --modules to customize.
DEFAULT_MODULES = {
    "Mito_receptors": ["BNIP3", "BNIP3L", "FUNDC1", "TOMM70", "BAX"],
}

GROUPS = ["LTKI", "WTKI", "LTWT", "WTWT"]  # TESE-IP, TESE-mock, WT-IP, WT-mock

# role -> default group suffix in column names <prefix>_IP_<suffix>.N
DEFAULT_SUFFIXES = {"TESE_IP": "LTKI", "TESE_MOCK": "WTKI",
                    "WT_IP": "LTWT", "WT_MOCK": "WTWT"}


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_dataset(path, prefix, wc_label="WC", suffixes=None):
    """Load one export CSV; return (dataframe, {role: [intensity columns]}).

    suffixes maps roles TESE_IP / TESE_MOCK / WT_IP / WT_MOCK to the group
    suffix used in the column names. Use suffix 'none' for absent groups
    (e.g. batch-1 young has no TESE mock: 'Het_KO,none,Het_WT,WT_WT').
    """
    d = pd.read_csv(path, low_memory=False)
    d["gene_u"] = d["Genes"].astype(str).str.upper()
    suffixes = suffixes or DEFAULT_SUFFIXES

    cols = {}
    for role, suf in suffixes.items():
        if suf.strip().lower() == "none":
            cols[role] = []
            continue
        for comp in ("IP", wc_label):
            pat = f"{prefix}_{comp}_{suf}."
            found = sorted(
                (c for c in d.columns if c.startswith(pat)),
                key=lambda c: int(c.rsplit(".", 1)[1]),
            )
            cols[f"{comp if comp == 'IP' else 'WC'}_{role}"] = found
    for role in suffixes:
        if not cols.get(f"IP_{role}") and suffixes[role].strip().lower() != "none":
            sys.exit(f"[error] {path}: no IP columns for group '{role}' "
                     f"(check --prefix / --suffixes)")
    return d, cols


def group_matrix(d, colnames):
    """Replicate x protein matrix (log2, clipped at 1), columns = proteins."""
    m = d[colnames].apply(pd.to_numeric, errors="coerce").T
    return np.log2(m.clip(lower=1))


# --------------------------------------------------------------------------- #
# Core metrics
# --------------------------------------------------------------------------- #
def tag_effect(d, cols):
    """Tag-vs-tag TESE effect + Welch p, from precomputed comparison columns."""
    out = pd.DataFrame({"gene_u": d["gene_u"]})
    if "log2FC" in d.columns:
        # precomputed log2FC is WT-vs-TESE -> flip for TESE-positive
        out["l2_tese"] = -pd.to_numeric(d["log2FC"], errors="coerce")
        if "-log10 P.Value" in d.columns:
            out["p_tag"] = np.power(
                10.0, -pd.to_numeric(d["-log10 P.Value"], errors="coerce"))
    return out


def input_norm_effect(d, cols):
    """Input-normalized enrichment: (IP_TESE - WC_TESE) - (IP_WT - WC_WT),
    per-replicate one-sample t-test on paired log2 differences."""
    res = pd.DataFrame({"gene_u": d["gene_u"]})
    for tag, role in [("TESE", "TESE_IP"), ("WT", "WT_IP")]:
        ip = group_matrix(d, cols[f"IP_{role}"])
        wc = group_matrix(d, cols[f"WC_{role}"])
        n = min(ip.shape[0], wc.shape[0])
        diff = ip.iloc[:n].values - wc.iloc[:n].values  # replicates x proteins
        res[f"inorm_{tag}"] = np.nanmean(diff, axis=0)
        if diff.shape[0] > 1:
            res[f"p_inorm_{tag}"] = stats.ttest_1samp(
                diff, 0.0, axis=0, nan_policy="omit").pvalue
        else:
            res[f"p_inorm_{tag}"] = np.nan
    res["input_norm"] = res["inorm_TESE"] - res["inorm_WT"]
    return res


def canonical_dod(d, cols):
    """Mock-controlled delivery metric (project-canonical, notebook cell 177).

    For each of the four group pairs, per-replicate input-normalized enrichment
    d_i = log2(IP_i) - log2(WC_i), paired by replicate index (each pair uses its
    own replicate count):
        m1 = TESE IP vs TESE WC      (TESE_IP)
        m2 = TESE mock vs TESE WC    (TESE_MOCK)
        m3 = WT IP vs WT WC          (WT_IP)
        m4 = WT mock vs WT WC        (WT_MOCK)
    dod = mean(m1) - mean(m2) - mean(m3) + mean(m4)
    SE  = sqrt(v1/n1 + v2/n2 + v3/n3 + v4/n4)   (Welch-style)
    p   = two-sided t on df = min(n1+n2+n3+n4-4, 100)
    TESE_specific = mean(m1) - mean(m2).

    If either mock group is absent (e.g. young batch 1), dod falls back to the
    unmocked input-normalized interaction m1 - m3 and p_dod is NaN.
    """
    stats_g = {}
    for role in ("TESE_IP", "TESE_MOCK", "WT_IP", "WT_MOCK"):
        if not cols.get(f"IP_{role}"):
            stats_g[role] = None
            continue
        ip = group_matrix(d, cols[f"IP_{role}"])   # replicates x proteins
        wc = group_matrix(d, cols[f"WC_{role}"])
        n = min(ip.shape[0], wc.shape[0])
        diff = ip.iloc[:n].values - wc.iloc[:n].values
        stats_g[role] = (np.nanmean(diff, axis=0),
                         np.nanvar(diff, axis=0, ddof=1), n)

    m1, v1, n1 = stats_g["TESE_IP"]
    m3, v3, n3 = stats_g["WT_IP"]

    if stats_g["TESE_MOCK"] is None or stats_g["WT_MOCK"] is None:
        out = pd.DataFrame({
            "gene_u": d["gene_u"],
            "dod": m1 - m3, "p_dod": np.nan,
            "TESE_specific": np.nan, "WT_specific": np.nan,
        })
        return out

    m2, v2, n2 = stats_g["TESE_MOCK"]
    m4, v4, n4 = stats_g["WT_MOCK"]
    contrast = m1 - m2 - m3 + m4
    se = np.sqrt(v1 / n1 + v2 / n2 + v3 / n3 + v4 / n4)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = contrast / se
        p = 2 * stats.t.sf(np.abs(t), df=min(n1 + n2 + n3 + n4 - 4, 100))

    out = pd.DataFrame({
        "gene_u": d["gene_u"],
        "dod": contrast,
        "p_dod": p,
        "TESE_specific": m1 - m2,
        "WT_specific": m3 - m4,
    })
    return out


def dedup_genes(result):
    """Collapse to one row per gene: means for effects, min for p-values."""
    agg = {"l2_tese": "mean", "p_tag": "min",
           "inorm_TESE": "mean", "p_inorm_TESE": "min",
           "inorm_WT": "mean", "p_inorm_WT": "min",
           "input_norm": "mean", "dod": "mean", "p_dod": "min",
           "TESE_specific": "mean", "WT_specific": "mean",
           "N.Sequences": "max"}
    agg = {k: v for k, v in agg.items() if k in result.columns}
    out = result.groupby("gene_u", as_index=False).agg(agg)
    if "is_mito" in result.columns:
        out["is_mito"] = out["gene_u"].map(
            result.groupby("gene_u")["is_mito"].max())
    return out


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #
def receptor_table(result, receptors):
    sub = result[result["gene_u"].isin({r.upper() for r in receptors})]
    cols = ["gene_u", "l2_tese", "p_tag", "input_norm", "dod", "p_dod",
            "TESE_specific", "N.Sequences"]
    return sub[[c for c in cols if c in sub.columns]].sort_values(
        "dod", ascending=False)


def module_table(result, modules):
    rows = []
    for name, genes in modules.items():
        sub = result[result["gene_u"].isin({g.upper() for g in genes})]
        if sub.empty:
            continue
        rows.append({
            "module": name, "n_quantified": len(sub),
            "median_l2_tese": sub["l2_tese"].median(),
            "median_dod": sub["dod"].median(),
            "frac_positive": (sub["l2_tese"] > 0).mean(),
        })
    return pd.DataFrame(rows)


def batch_common_hits(batch_results, p_thresh=0.05, require_p=False):
    """Proteins TESE-high in every batch (optionally also p < p_thresh)."""
    merged = None
    for name, res in batch_results.items():
        r = res[["gene_u", "l2_tese", "p_tag"]].rename(
            columns={"l2_tese": f"l2_{name}", "p_tag": f"p_{name}"})
        merged = r if merged is None else merged.merge(r, on="gene_u")
    if merged is None:
        return pd.DataFrame()
    l2_cols = [c for c in merged.columns if c.startswith("l2_")]
    ok = merged[l2_cols].gt(0)
    if require_p:
        p_cols = [c for c in merged.columns if c.startswith("p_")]
        ok &= merged[p_cols].lt(p_thresh)
    return merged[ok.all(axis=1)].sort_values(
        l2_cols[0], ascending=False)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def analyze_one(path, name, prefix, mito_genes, wc_label="WC", suffixes=None):
    d, cols = load_dataset(path, prefix, wc_label=wc_label, suffixes=suffixes)
    result = tag_effect(d, cols)
    result = result.merge(input_norm_effect(d, cols), on="gene_u")
    result = result.merge(canonical_dod(d, cols), on="gene_u")
    if "N.Sequences" in d.columns:
        result["N.Sequences"] = pd.to_numeric(d["N.Sequences"], errors="coerce")
    if mito_genes is not None:
        result["is_mito"] = result["gene_u"].isin(mito_genes)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="LysoTag lyso-IP TESE analysis (tag / input-norm / dod)")
    ap.add_argument("--input", action="append", required=True,
                    help="raw export CSV (repeat for multiple batches)")
    ap.add_argument("--name", action="append", required=True,
                    help="batch label matching each --input, e.g. young_b2")
    ap.add_argument("--prefix", default="Set1_Brain",
                    help="column prefix before _IP_/_WC_ (default: Set1_Brain)")
    ap.add_argument("--wc-label", default="WC",
                    help="whole-cell column label: 'WC' or 'WCL' "
                         "(default: WC)")
    ap.add_argument("--suffixes", default=None,
                    help="comma-separated group suffixes in order "
                         "TESE_IP,TESE_MOCK,WT_IP,WT_MOCK "
                         "(default: LTKI,WTKI,LTWT,WTWT; "
                         "batch-1 young: Het_KO,none,Het_WT,WT_WT; "
                         "use 'none' for an absent group)")
    ap.add_argument("--outdir", default="lysoip_results",
                    help="output directory (default: lysoip_results)")
    ap.add_argument("--mito-annot", default=None,
                    help="CSV with 'Genes' + 'mito_annotated_GOCC' columns, "
                         "or a plain text file of gene symbols (one per line)")
    ap.add_argument("--receptors", default=None,
                    help="text file of receptor genes (one per line); "
                         "default = built-in 32-gene panel")
    ap.add_argument("--modules", default=None,
                    help="TSV file: module name <tab> comma-separated genes")
    args = ap.parse_args(argv)

    if len(args.input) != len(args.name):
        sys.exit("[error] --input and --name counts differ")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # mito gene set
    mito_genes = None
    if args.mito_annot:
        src = Path(args.mito_annot)
        if src.suffix == ".txt":
            mito_genes = {g.strip().upper() for g in src.read_text().splitlines()
                          if g.strip()}
        else:
            ann = pd.read_csv(src, low_memory=False,
                              usecols=["Genes", "mito_annotated_GOCC"])
            mito_genes = set(ann.query("mito_annotated_GOCC == True")
                             ["Genes"].str.upper())

    receptors = DEFAULT_RECEPTORS
    if args.receptors:
        receptors = [g.strip() for g in
                     Path(args.receptors).read_text().splitlines() if g.strip()]

    modules = dict(DEFAULT_MODULES)
    if args.modules:
        mods = pd.read_csv(args.modules, sep="\t", names=["module", "genes"])
        modules = {r.module: [g.strip() for g in r.genes.split(",")]
                   for r in mods.itertuples()}

    # per-batch analysis
    suffixes = None
    if args.suffixes:
        parts = args.suffixes.split(",")
        if len(parts) != 4:
            sys.exit("[error] --suffixes needs exactly 4 comma-separated values")
        suffixes = dict(zip(DEFAULT_SUFFIXES, parts))

    batch_results = {}
    for path, name in zip(args.input, args.name):
        res = analyze_one(path, name, args.prefix, mito_genes,
                          wc_label=args.wc_label, suffixes=suffixes)
        res = dedup_genes(res)          # one row per gene
        batch_results[name] = res
        res.to_csv(outdir / f"results_{name}.csv", index=False)
        rec = receptor_table(res, receptors)
        rec.to_csv(outdir / f"receptors_{name}.csv", index=False)
        mod = module_table(res, modules)
        mod.to_csv(outdir / f"modules_{name}.csv", index=False)
        if "is_mito" in res:
            n_mito = int(res["is_mito"].sum())
            med = res.loc[res["is_mito"], "l2_tese"].median()
            print(f"[{name}] {len(res)} proteins | mito: {n_mito} | "
                  f"median mito TESE effect: {med:+.2f}")
        else:
            print(f"[{name}] {len(res)} proteins")

    # cross-batch summary
    if len(batch_results) > 1:
        common = batch_common_hits(batch_results)
        common.to_csv(outdir / "common_hits_all_batches.csv", index=False)
        print(f"common hits (TESE-high in all batches): {len(common)}")

        # receptor dod across batches
        rec_all = None
        for name, res in batch_results.items():
            r = receptor_table(res, receptors)[["gene_u", "dod", "p_dod"]]
            r = r.rename(columns={"dod": f"dod_{name}", "p_dod": f"p_{name}"})
            rec_all = r if rec_all is None else rec_all.merge(r, on="gene_u",
                                                              how="outer")
        if rec_all is not None:
            rec_all.to_csv(outdir / "receptors_all_batches.csv", index=False)


if __name__ == "__main__":
    main()
