"""A first look: each gene's change between two groups of samples against its significance, from the fetched counts.

Method, stated wherever the result is shown: library-size CPM, genes with CPM >= 1 in at least as many samples as the
smaller group, Welch's t-test on log2(CPM + 1), Benjamini-Hochberg FDR. It is a screen, not DESeq2 or limma-voom."""

import re

import numpy as np
from scipy import stats

from . import record, table

CONTROL = re.compile(r"control|healthy|normal|\bwt\b|wild[- ]?type|vehicle|dmso|untreated|mock|baseline|donor|non-?diseased|sham|ctrl|\bnc\b", re.I)
METHOD = "Welch's t-test on log2(CPM + 1); genes with CPM ≥ 1 in at least as many samples as the smaller group; Benjamini–Hochberg FDR"
Q, LFC = 0.05, 1.0


def groups(accession: str) -> dict:
    """The sample table's factors whose levels could split cases from controls, with the default comparison."""
    rec = record.record(accession)
    if not rec or not rec["samples"]:
        return {"factors": [], "default": None}
    cols, rows = rec["samples"]["columns"], rec["samples"]["rows"]
    factors = []
    for i, name in enumerate(cols):
        if name in ("Accession", "Title"):
            continue
        levels: dict[str, int] = {}
        for r in rows:
            if r[i]:
                levels[r[i]] = levels.get(r[i], 0) + 1
        if 2 <= len(levels) <= 12 and sum(n >= 2 for n in levels.values()) >= 2:
            factors.append({"name": name, "levels": dict(sorted(levels.items(), key=lambda kv: -kv[1]))})
    default = None
    for f in factors:
        controls = [lv for lv in f["levels"] if CONTROL.search(lv)]
        if controls:
            cases = [lv for lv in f["levels"] if lv not in controls]
            if cases:
                default = {"factor": f["name"], "case": [max(cases, key=f["levels"].get)], "control": controls}
                break
    if not default and factors:
        f = factors[0]
        top = list(f["levels"])[:2]
        default = {"factor": f["name"], "case": [top[0]], "control": [top[1]]}
    return {"factors": factors, "default": default}


def compare(accession: str, factor: str | None = None, case: list[str] | None = None, control: list[str] | None = None) -> dict:
    data = table.counts(accession)
    if not data:
        return {"accession": accession, "available": False, "reason": "GEO has no NCBI-generated counts for this series"}
    choice = groups(accession)
    if factor is None:
        if not choice["default"]:
            return {"accession": accession, "available": False, "reason": "the sample table has no factor with two groups"}
        factor, case, control = choice["default"]["factor"], choice["default"]["case"], choice["default"]["control"]
    rec = record.record(accession)
    cols = rec["samples"]["columns"]
    if factor not in cols:
        return {"accession": accession, "available": False, "reason": f"no sample characteristic named {factor}"}
    level = {r[0]: r[cols.index(factor)] for r in rec["samples"]["rows"]}
    in_case = np.array([level.get(s) in case for s in data["samples"]])
    in_control = np.array([level.get(s) in control for s in data["samples"]])
    n_case, n_control = int(in_case.sum()), int(in_control.sum())
    if min(n_case, n_control) < 2:
        return {"accession": accession, "available": False, "reason": f"{n_case} case and {n_control} control samples have counts; each group needs at least 2"}

    m = data["matrix"].astype(float)
    cpm = m / m.sum(axis=0) * 1e6
    keep = (cpm[:, in_case | in_control] >= 1).sum(axis=1) >= min(n_case, n_control)
    logged = np.log2(cpm[keep] + 1)
    a, b = logged[:, in_case], logged[:, in_control]
    lfc = a.mean(axis=1) - b.mean(axis=1)
    t, p = stats.ttest_ind(a, b, axis=1, equal_var=False)
    p = np.nan_to_num(p, nan=1.0)
    q = stats.false_discovery_control(p)
    symbols = np.array(data["symbols"])[keep]
    order = np.argsort(p)
    genes = [[str(symbols[i]), round(float(lfc[i]), 3), round(float(-np.log10(max(p[i], 1e-300))), 3), float(f"{q[i]:.3g}")] for i in order]
    up = [g for g in genes if g[3] < Q and g[1] >= LFC]
    down = [g for g in genes if g[3] < Q and g[1] <= -LFC]
    return {
        "accession": accession, "available": True, "factor": factor, "case": case, "control": control,
        "n_case": n_case, "n_control": n_control, "tested": int(keep.sum()), "method": METHOD, "q": Q, "lfc": LFC,
        "up": len(up), "down": len(down), "genes": genes, "source": data["source"], "groups": choice,
    }


if __name__ == "__main__":
    g = groups("GSE124685")
    assert g["default"] == {"factor": "disease state", "case": ["IPF"], "control": ["healthy donor"]}, g["default"]
    r = compare("GSE124685")
    assert (r["n_case"], r["n_control"]) == (49, 35), (r["n_case"], r["n_control"])
    top = {g[0]: g for g in r["genes"][:2000]}
    for gene in ("MMP7", "SPP1", "COL1A1"):
        assert gene in top and top[gene][1] > 1, (gene, top.get(gene))
    print("volcano self-check passed:", r["tested"], "genes tested,", r["up"], "up,", r["down"], "down; top", [g[0] for g in r["genes"][:8]])
