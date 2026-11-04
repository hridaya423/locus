#!/usr/bin/env python
"""QC, clustering, marker genes and pseudobulk count matrices for several single-cell (or single-nucleus) count matrices.

    python singlecell_analyse.py --samples samples.tsv --out results [--mito-max 0.2] [--threads 4] [--resolution 0.5]
                                 [--reference normal --target tumor]

samples.tsv has the columns gsm, condition and path, where path is a directory holding one sample's matrix: a 10x
triplet (*matrix.mtx[.gz] + *barcodes.tsv[.gz] + *features.tsv[.gz] or *genes.tsv[.gz]), a kb-python `counts_filtered`
folder (cells_x_genes.mtx), a 10x .h5, or one dense csv/tsv of genes x cells. Runs in the omics-sc environment (scanpy,
leidenalg, python-igraph), never in the app's own environment, so the same file ships unchanged in the laptop kit.

Writes qc.tsv, cells_per_cluster.tsv, markers.tsv, umap.png/.pdf, markers_dotplot.png/.pdf, analysed.h5ad (when under
--h5ad-max-mb), pseudobulk/<cluster>.counts.tsv with pseudobulk/cells.tsv, and summary.json with every number the
caller reports. Thresholds follow the scanpy tutorial defaults: cells with fewer than 200 genes, genes in fewer than 3
cells and cells above the mitochondrial fraction are removed.
"""

import argparse
import gzip
import importlib.metadata
import json
import os
import re
import sys
import time
import warnings
from pathlib import Path


STARTED = time.monotonic()


def say(message: str) -> None:
    """A progress line with the seconds since the script started, so a slow stage shows in the log."""
    print(f"  [{time.monotonic() - STARTED:5.0f} s] {message}", flush=True)


def main() -> None:
    args = parse_args()
    set_threads(args.threads)

    import matplotlib

    matplotlib.use("Agg")
    import anndata as ad
    import numpy as np
    import pandas as pd
    import scanpy as sc
    import scipy.sparse as sp

    sc.settings.n_jobs = args.threads
    sc.settings.verbosity = 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    samples = pd.read_csv(args.samples, sep="\t", dtype=str)

    # ---- read and QC each sample on its own, so the per-sample numbers are known before concatenation
    parts, qc_rows = [], []
    for row in samples.itertuples(index=False):
        a = read_sample(Path(row.path), sc, sp, pd, ad, np)
        a.obs["sample"] = row.gsm
        a.obs["condition"] = row.condition
        a.obs_names = [f"{row.gsm}:{b}" for b in a.obs_names]
        a.var["mito"] = a.var_names.str.match(r"^(MT|mt|Mt)-")
        sc.pp.calculate_qc_metrics(a, qc_vars=["mito"], percent_top=None, log1p=False, inplace=True)
        before = a.n_obs
        low_genes = a.obs["n_genes_by_counts"] < args.min_genes
        high_mito = a.obs["pct_counts_mito"] > 100 * args.mito_max
        a = a[~(low_genes | high_mito)].copy()
        qc_rows.append({
            "sample": row.gsm, "condition": row.condition, "cells_before": before, "cells_after": a.n_obs,
            "removed_low_genes": int(low_genes.sum()), "removed_high_mito": int((high_mito & ~low_genes).sum()),
            "median_genes": int(a.obs["n_genes_by_counts"].median()) if a.n_obs else 0,
            "median_counts": int(a.obs["total_counts"].median()) if a.n_obs else 0,
            "median_mito_pct": round(float(a.obs["pct_counts_mito"].median()), 2) if a.n_obs else 0.0,
        })
        say(f"{row.gsm}: {before} cells, {a.n_obs} after QC")
        parts.append(a)
    has_symbols = any(p.var["mito"].any() for p in parts)
    qc = pd.DataFrame(qc_rows)
    qc.to_csv(out / "qc.tsv", sep="\t", index=False)

    adata = ad.concat(parts, join="inner", merge="same")
    adata.obs_names_make_unique()
    sc.pp.filter_genes(adata, min_cells=args.min_cells)
    adata.layers["counts"] = adata.X.copy()
    say(f"{adata.n_obs} cells x {adata.n_vars} genes after QC")

    # ---- normalise, embed, cluster (scanpy defaults except the batch-aware HVG selection and the stated resolution)
    sc.pp.normalize_total(adata)
    sc.pp.log1p(adata)
    adata.raw = adata
    sc.pp.highly_variable_genes(adata, batch_key="sample" if samples.shape[0] > 1 else None)
    say("normalised, highly variable genes chosen")
    sc.tl.pca(adata, mask_var="highly_variable")
    say("PCA")
    sc.pp.neighbors(adata)
    say("neighbours")
    sc.tl.leiden(adata, resolution=args.resolution, flavor="igraph", n_iterations=2, directed=False, key_added="leiden", random_state=0)
    say("Leiden")
    sc.tl.umap(adata, random_state=0)
    clusters = list(adata.obs["leiden"].cat.categories)
    say(f"{len(clusters)} Leiden clusters at resolution {args.resolution}")

    counts = pd.crosstab(adata.obs["leiden"], adata.obs["sample"])
    counts["total"] = counts.sum(axis=1)
    counts.index.name = "cluster"
    counts.to_csv(out / "cells_per_cluster.tsv", sep="\t")
    # A cluster that is nearly all one sample is donor or batch structure, not a shared cell type; no integration is run here.
    shares = counts.drop(columns="total").div(counts["total"], axis=0)
    dominated = {c: shares.columns[shares.loc[c].argmax()] for c in clusters if shares.loc[c].max() > 0.9}

    # ---- markers: Wilcoxon per cluster against the rest, on the log-normalised values of every gene
    sc.tl.rank_genes_groups(adata, "leiden", method="wilcoxon")
    say("markers ranked")
    markers = sc.get.rank_genes_groups_df(adata, group=None)
    markers = markers.rename(columns={"group": "cluster", "names": "gene", "scores": "score", "logfoldchanges": "log2fc", "pvals": "pvalue", "pvals_adj": "padj"})
    markers["rank"] = markers.groupby("cluster").cumcount() + 1
    top10 = markers[markers["rank"] <= 10][["cluster", "rank", "gene", "score", "log2fc", "pvalue", "padj"]]
    top10.to_csv(out / "markers.tsv", sep="\t", index=False, float_format="%.4g")
    top3 = {c: list(markers[(markers["cluster"] == c) & (markers["rank"] <= 3)]["gene"]) for c in clusters}

    # ---- figures
    draw_umap(adata, sc, out, args.reference, args.target, len(clusters), args.unit)
    draw_dotplot(adata, sc, top3, out)

    # ---- pseudobulk: raw counts summed per (cluster, sample); clusters with >= 2 samples per condition and >= min cells
    pseudo = out / "pseudobulk"
    pseudo.mkdir(exist_ok=True)
    for old in pseudo.glob("cluster_*.counts.tsv"):
        old.unlink()
    cells_rows, tested = [], []
    cond_of = dict(zip(samples["gsm"], samples["condition"]))
    for c in clusters:
        in_cluster = adata.obs["leiden"] == c
        per_sample = adata.obs.loc[in_cluster, "sample"].value_counts()
        keep = [s for s in samples["gsm"] if per_sample.get(s, 0) >= args.min_cells_pseudobulk]
        for s in samples["gsm"]:
            cells_rows.append({"cluster": c, "sample": s, "condition": cond_of[s], "cells": int(per_sample.get(s, 0)), "used": s in keep})
        by_condition = pd.Series([cond_of[s] for s in keep]).value_counts() if keep else pd.Series(dtype=int)
        if len(by_condition) < 2 or by_condition.min() < 2:
            continue
        mask = in_cluster.values & adata.obs["sample"].isin(keep).values
        groups = pd.Categorical(adata.obs.loc[mask, "sample"], categories=keep)
        indicator = sp.csr_matrix((np.ones(mask.sum()), (groups.codes, np.arange(mask.sum()))), shape=(len(keep), int(mask.sum())))
        summed = np.asarray((indicator @ adata.layers["counts"][mask]).todense()).T
        frame = pd.DataFrame(summed.astype(int), index=adata.var_names, columns=keep)
        frame.index.name = "gene"
        frame.to_csv(pseudo / f"cluster_{c}.counts.tsv", sep="\t")
        tested.append({"cluster": c, "samples": {k: int(v) for k, v in by_condition.items()}})
    pd.DataFrame(cells_rows).to_csv(pseudo / "cells.tsv", sep="\t", index=False)
    say(f"pseudobulk counts for {len(tested)} clusters")

    # ---- the analysed object: raw counts in X (sparse), embeddings and clusters in obs/obsm; kept only when small
    h5ad = out / "analysed.h5ad"
    slim = ad.AnnData(X=adata.layers["counts"], obs=adata.obs, var=adata.var[[c for c in adata.var.columns if c in ("gene_id", "highly_variable", "mito")]],
                      obsm={"X_pca": adata.obsm["X_pca"], "X_umap": adata.obsm["X_umap"]})
    slim.uns["note"] = "X holds raw counts; sc.pp.normalize_total then sc.pp.log1p reproduces the analysed values"
    slim.write_h5ad(h5ad, compression="gzip")
    h5ad_bytes = h5ad.stat().st_size
    kept = h5ad_bytes <= args.h5ad_max_mb * 1_000_000
    if not kept:
        h5ad.unlink()

    summary = {
        "samples": qc_rows, "cells_before": int(qc["cells_before"].sum()), "cells_after": int(adata.n_obs), "genes": int(adata.n_vars),
        "clusters": len(clusters), "cluster_sizes": {c: int(counts.loc[c, "total"]) for c in clusters}, "top_markers": top3, "sample_dominated": dominated,
        "pseudobulk_clusters": tested, "mito_symbols_found": bool(has_symbols),
        "thresholds": {"min_genes": args.min_genes, "min_cells": args.min_cells, "mito_max": args.mito_max, "resolution": args.resolution,
                       "min_cells_per_sample_for_pseudobulk": args.min_cells_pseudobulk},
        "h5ad": {"kept": kept, "bytes": h5ad_bytes, "limit_mb": args.h5ad_max_mb},
        "versions": versions(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    say(f"wrote {out / 'summary.json'}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--samples", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--mito-max", type=float, default=0.2, help="fraction of counts from mitochondrial genes above which a cell is removed")
    p.add_argument("--min-genes", type=int, default=200)
    p.add_argument("--min-cells", type=int, default=3)
    p.add_argument("--min-cells-pseudobulk", type=int, default=10, help="a sample enters a cluster's pseudobulk only with at least this many cells there")
    p.add_argument("--resolution", type=float, default=0.5)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--h5ad-max-mb", type=int, default=300)
    p.add_argument("--unit", default="cells", help="'cells' or 'nuclei', for titles")
    p.add_argument("--reference", default="control")
    p.add_argument("--target", default="case")
    return p.parse_args()


def set_threads(n: int) -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, str(n))


def versions() -> dict[str, str]:
    out = {}
    for name in ("scanpy", "anndata", "leidenalg", "igraph", "scipy", "pandas", "numpy", "matplotlib"):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    out["python"] = sys.version.split()[0]
    return out


# ---------------------------------------------------------------- reading

def _open(path: Path):
    return gzip.open(path, "rt") if path.suffix == ".gz" else open(path)


def read_sample(folder: Path, sc, sp, pd, ad, np):
    """One sample's matrix as cells x genes AnnData with integer counts and unique gene symbols as var_names."""
    files = sorted(p for p in folder.iterdir() if p.is_file())
    names = {p.name.lower(): p for p in files}
    mtx = next((p for p in files if re.search(r"\.mtx(\.gz)?$", p.name)), None)
    h5 = next((p for p in files if p.suffix in (".h5", ".hdf5")), None)
    if mtx:
        kb_layout = "cells_x_genes" in mtx.name
        barcodes = next((p for p in files if re.search(r"barcodes\.(tsv|txt)(\.gz)?$", p.name)), None)
        features = next((p for p in files if re.search(r"(features|genes)\.(tsv|txt)(\.gz)?$", p.name)), None)
        if not (barcodes and features):
            raise FileNotFoundError(f"{folder}: a .mtx without barcodes and features/genes files")
        with _open(mtx) as handle, warnings.catch_warnings():
            from scipy.io import mmread
            warnings.simplefilter("ignore", DeprecationWarning)
            m = mmread(handle)
        m = sp.csr_matrix(m if kb_layout else m.T)
        with _open(barcodes) as handle:
            cells = [line.split()[0] for line in handle if line.strip()]
        with _open(features) as handle:
            rows = [line.rstrip("\n").split("\t") for line in handle if line.strip()]
        ids = [r[0] for r in rows]
        symbols = [r[1] if len(r) > 1 and r[1] else r[0] for r in rows]
        a = ad.AnnData(X=m.astype(np.float32), obs=pd.DataFrame(index=cells), var=pd.DataFrame({"gene_id": ids}, index=ad.utils.make_index_unique(pd.Index(symbols))))
    elif h5:
        a = sc.read_10x_h5(h5)
        if "gene_ids" in a.var:
            a.var = a.var.rename(columns={"gene_ids": "gene_id"})
    else:
        dense = next((p for p in files if re.search(r"\.(csv|tsv|txt)(\.gz)?$", p.name)), None)
        if not dense:
            raise FileNotFoundError(f"{folder}: no matrix (.mtx, .h5 or dense table) found among {sorted(names)}")
        sep = "," if ".csv" in dense.name else "\t"
        table = pd.read_csv(dense, sep=sep, index_col=0)
        a = ad.AnnData(X=sp.csr_matrix(table.T.values.astype(np.float32)), obs=pd.DataFrame(index=table.columns.astype(str)), var=pd.DataFrame({"gene_id": table.index.astype(str)}, index=table.index.astype(str)))
    a.var_names = a.var_names.astype(str)
    a.var_names_make_unique()
    a.obs_names = a.obs_names.astype(str)
    return a


# ---------------------------------------------------------------- figures
# One style for both figures: white panel, thin dark-grey axis lines, 8-9 pt sans text. Conditions take the validated
# categorical pair blue/orange that the bulk figures use; clusters are labelled on the plot itself, so their identity
# never rests on colour alone (scanpy's default_20/default_28 series for up to 28 clusters).

BLUE, ORANGE, INK, GREY = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e"


def _style(ax, title: str) -> None:
    ax.set_title(title, fontsize=9, color=INK, loc="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_linewidth(0.4)
        ax.spines[side].set_color(GREY)
    ax.tick_params(labelsize=7, colors=GREY, width=0.4)
    ax.xaxis.label.set_size(8)
    ax.yaxis.label.set_size(8)


def draw_umap(adata, sc, out: Path, reference: str, target: str, n_clusters: int, unit: str = "cells") -> None:
    import matplotlib.pyplot as plt

    size = max(2.0, min(12.0, 120_000 / max(adata.n_obs, 1)))
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.9))
    sc.pl.umap(adata, color="leiden", ax=axes[0], show=False, legend_loc="on data", legend_fontsize=7, legend_fontoutline=1.5, size=size, frameon=True, title="")
    palette = {reference: BLUE, target: ORANGE}
    sc.pl.umap(adata, color="condition", ax=axes[1], show=False, size=size, frameon=True, title="",
               palette=[palette.get(c, GREY) for c in adata.obs["condition"].cat.categories])
    _style(axes[0], f"{n_clusters} Leiden clusters (resolution 0.5), {adata.n_obs:,} {unit}")
    _style(axes[1], f"Condition: {target} vs {reference}")
    legend = axes[1].get_legend()
    if legend:
        legend.set_frame_on(False)
        for text in legend.get_texts():
            text.set_fontsize(7)
    fig.tight_layout()
    fig.savefig(out / "umap.png", dpi=300, facecolor="white")
    fig.savefig(out / "umap.pdf", facecolor="white")
    plt.close(fig)


def draw_dotplot(adata, sc, top3: dict, out: Path) -> None:
    import matplotlib.pyplot as plt

    plot = sc.pl.dotplot(adata, top3, groupby="leiden", show=False, return_fig=True, dendrogram=False, standard_scale="var",
                         title="Top 3 Wilcoxon markers per cluster (colour: mean expression scaled per gene; dot size: fraction of cells expressing)")
    plot.style(cmap="Blues", dot_edge_color=GREY, dot_edge_lw=0.3, grid=False)
    plot.legend(width=1.4)
    plot.savefig(out / "markers_dotplot.png", dpi=300, facecolor="white", bbox_inches="tight")
    plot.savefig(out / "markers_dotplot.pdf", facecolor="white", bbox_inches="tight")
    plt.close("all")


if __name__ == "__main__":
    main()
