#!/usr/bin/env python3
"""
tese_lysoip_compare_batches.py — Compare TESE effects between two lyso-IP datasets
===================================================================================

Compares per-protein TESE effects (tag-vs-tag, input-normalized enrichment,
mock-controlled dod) between two datasets — e.g. young batch 1 vs young batch 2 —
and reports concordance, replication, and a scatter figure.

Outputs (in --outdir):
  comparison_<nameA>_vs_<nameB>.csv   per-gene merged effects
  common_hits_<A>_vs_<B>.csv          TESE-high + p<0.05 in BOTH datasets
  batch_specific_<A>_vs_<B>.csv       significant in one, not the other
  compare_<A>_vs_<B>.svg/.png         scatter of TESE effects (mito highlighted)
  summary printed to stdout

Example (the two young brain batches):
  python tese_lysoip_compare_batches.py \
      --input-a "batvh 1 young lyso ip tese.csv" --name-a young_b1 \
      --prefix-a Set1_Brain --wc-label-a WCL \
      --suffixes-a "Het_KO,none,Het_WT,WT_WT" \
      --input-b "2 batch young Lyso IP TESE.csv" --name-b young_b2 \
      --mito-annot diff_results_mito_fraction.csv --outdir compare_young

Notes
-----
  * Sign convention: positive = TESE-high (precomputed WT-vs-TESE log2FC is
    flipped internally).
  * Batch 1 has no TESE mock IPs, so its dod falls back to the unmocked
    input-normalized interaction (m1 - m3) and its dod p-values are NaN.
  * dod p-values are nominal (uncorrected).

Requires: pandas, numpy, scipy, matplotlib
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from tese_lysoip_analysis import analyze_one, dedup_genes

# Poster palette (project style)
FG = "#2B2B33"
MAGENTA = "#C55187"   # TESE / mito
GREEN = "#5E997D"     # WT
GREY = "#B9B9C0"
BEIGE = "#F5F1E6"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Compare TESE lyso-IP effects between two datasets")
    for side in ("a", "b"):
        ap.add_argument(f"--input-{side}", required=True,
                        help=f"raw export CSV for dataset {side.upper()}")
        ap.add_argument(f"--name-{side}", required=True,
                        help=f"short label for dataset {side.upper()}")
        ap.add_argument(f"--prefix-{side}", default="Set1_Brain",
                        help=f"column prefix for {side.upper()} "
                             f"(default: Set1_Brain)")
        ap.add_argument(f"--wc-label-{side}", default="WC",
                        help=f"whole-cell label for {side.upper()}: "
                             f"'WC' or 'WCL' (default: WC)")
        ap.add_argument(f"--suffixes-{side}", default=None,
                        help="comma-separated TESE_IP,TESE_MOCK,WT_IP,WT_MOCK "
                             f"suffixes for {side.upper()} (default: "
                             "LTKI,WTKI,LTWT,WTWT; batch-1 young: "
                             "Het_KO,none,Het_WT,WT_WT)")
    ap.add_argument("--mito-annot", default=None,
                    help="CSV with 'Genes' + 'mito_annotated_GOCC', or a "
                         "plain text file of gene symbols")
    ap.add_argument("--p-thresh", type=float, default=0.05)
    ap.add_argument("--outdir", default="lysoip_comparison")
    args = ap.parse_args(argv)
    return args


def load_mito(path):
    src = Path(path)
    if src.suffix == ".txt":
        return {g.strip().upper() for g in src.read_text().splitlines() if g.strip()}
    ann = pd.read_csv(src, low_memory=False,
                      usecols=["Genes", "mito_annotated_GOCC"])
    return set(ann.query("mito_annotated_GOCC == True")["Genes"].str.upper())


def run_analysis(path, name, prefix, wc_label, suffixes, mito_genes):
    res = analyze_one(path, name, prefix, mito_genes,
                      wc_label=wc_label, suffixes=suffixes)
    return dedup_genes(res)


def corr_stats(merged, mito_mask):
    out = []
    for label, mask in [("all proteins", np.ones(len(merged), bool)),
                        ("mito proteins", mito_mask.fillna(False).values)]:
        sub = merged[mask & merged["l2_A"].notna() & merged["l2_B"].notna()]
        pr = stats.pearsonr(sub["l2_A"], sub["l2_B"])
        sr = stats.spearmanr(sub["l2_A"], sub["l2_B"])
        same_sign = (np.sign(sub["l2_A"]) == np.sign(sub["l2_B"])).mean()
        out.append({"set": label, "n": len(sub),
                    "pearson_r": pr[0], "pearson_p": pr[1],
                    "spearman_rho": sr.statistic,
                    "frac_same_direction": same_sign})
    return pd.DataFrame(out)


def scatter_plot(merged, mito_mask, name_a, name_b, outpath, p_thresh):
    plt.rcParams.update({
        "font.family": ["Liberation Sans", "Arimo", "DejaVu Sans"],
        "svg.fonttype": "none", "text.color": FG,
        "axes.edgecolor": FG, "axes.labelcolor": FG,
        "xtick.color": FG, "ytick.color": FG,
    })
    fig, ax = plt.subplots(figsize=(5.6, 5.6))
    fig.patch.set_facecolor("white")

    # beige quadrants for concordant TESE-high / WT-high
    lim = 4.0
    ax.axhspan(0, lim, xmin=0, xmax=1, color="none")
    ax.add_patch(plt.Rectangle((0, 0), lim, lim, color=BEIGE, zorder=0))
    ax.add_patch(plt.Rectangle((-lim, -lim), lim, lim, color=BEIGE, zorder=0))

    x = merged["l2_A"].clip(-lim, lim)
    y = merged["l2_B"].clip(-lim, lim)
    mito = mito_mask.fillna(False).values

    ax.scatter(x[~mito], y[~mito], s=6, c=GREY, alpha=0.35, lw=0,
               label="non-mito", rasterized=True)
    ax.scatter(x[mito], y[mito], s=10, c=MAGENTA, alpha=0.75, lw=0,
               label="mito", rasterized=True)
    ax.axhline(0, color=FG, lw=0.8)
    ax.axvline(0, color=FG, lw=0.8)
    ax.plot([-lim, lim], [-lim, lim], color=FG, lw=0.8, ls="--", alpha=0.5)

    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel(f"TESE effect — {name_a} (log2)")
    ax.set_ylabel(f"TESE effect — {name_b} (log2)")
    ax.set_title(f"TESE effect: {name_a} vs {name_b}", loc="left",
                 fontweight="bold")
    ax.legend(loc="lower right", frameon=False)

    for ext in ("svg", "png"):
        fig.savefig(outpath.with_suffix(f".{ext}"), dpi=200)
    plt.close(fig)


def main(argv=None):
    args = parse_args(argv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    mito_genes = load_mito(args.mito_annot) if args.mito_annot else None

    def suffix_map(s):
        if not s:
            return None
        parts = s.split(",")
        if len(parts) != 4:
            sys.exit("[error] --suffixes-* needs 4 comma-separated values")
        return dict(zip(("TESE_IP", "TESE_MOCK", "WT_IP", "WT_MOCK"), parts))

    res_a = run_analysis(args.input_a, args.name_a, args.prefix_a,
                         args.wc_label_a, suffix_map(args.suffixes_a),
                         mito_genes)
    res_b = run_analysis(args.input_b, args.name_b, args.prefix_b,
                         args.wc_label_b, suffix_map(args.suffixes_b),
                         mito_genes)

    merged = (res_a[["gene_u", "l2_tese", "p_tag", "dod", "p_dod"]]
              .rename(columns={"l2_tese": "l2_A", "p_tag": "p_A",
                               "dod": "dod_A", "p_dod": "p_dod_A"})
              .merge(res_b[["gene_u", "l2_tese", "p_tag", "dod", "p_dod"]]
                     .rename(columns={"l2_tese": "l2_B", "p_tag": "p_B",
                                      "dod": "dod_B", "p_dod": "p_dod_B"}),
                     on="gene_u"))
    if mito_genes is not None:
        merged["is_mito"] = merged["gene_u"].isin(mito_genes)
    merged.to_csv(outdir / f"comparison_{args.name_a}_vs_{args.name_b}.csv",
                  index=False)

    # concordance stats
    if mito_genes is not None:
        cstats = corr_stats(merged, merged["is_mito"])
    else:
        cstats = corr_stats(merged, pd.Series(False, index=merged.index))
    print(f"=== TESE effect concordance: {args.name_a} vs {args.name_b} ===")
    print(cstats.round(3).to_string(index=False))

    # replication classes (tag-vs-tag, p < thresh, TESE-positive)
    p = args.p_thresh
    sig_a = (merged["l2_A"] > 0) & (merged["p_A"] < p)
    sig_b = (merged["l2_B"] > 0) & (merged["p_B"] < p)
    common = merged[sig_a & sig_b].sort_values("l2_A", ascending=False)
    only_a = merged[sig_a & ~sig_b].sort_values("l2_A", ascending=False)
    only_b = merged[sig_b & ~sig_a].sort_values("l2_B", ascending=False)
    common.to_csv(outdir / f"common_hits_{args.name_a}_vs_{args.name_b}.csv",
                  index=False)
    only_a.to_csv(outdir / f"specific_{args.name_a}.csv", index=False)
    only_b.to_csv(outdir / f"specific_{args.name_b}.csv", index=False)

    n_mito_common = int(common["is_mito"].sum()) if mito_genes is not None else -1
    print(f"\nreplicated TESE-high hits (p<{p} in both): {len(common)} "
          f"| mito: {n_mito_common}")
    print(f"{args.name_a}-only: {len(only_a)} | {args.name_b}-only: {len(only_b)}")
    if mito_genes is not None and len(common):
        print(f"mito enrichment among replicated hits: "
              f"{n_mito_common}/{len(common)}")

    if mito_genes is not None:
        scatter_plot(merged, merged["is_mito"], args.name_a, args.name_b,
                     outdir / f"compare_{args.name_a}_vs_{args.name_b}",
                     p)
        print(f"\nfigure: compare_{args.name_a}_vs_{args.name_b}.svg/.png")


if __name__ == "__main__":
    main()
