"""The traps an expert checks before trusting a case/control comparison, each with the counts that show it, and the
smallest change the study can detect. Read from the sample table and, for power, the fetched expression table."""

import math
import re
from collections import Counter

import numpy as np

from . import record, table, volcano

BATCH = re.compile(r"batch|plate|date|lane|\brun\b|institution|site|center|centre|hospital|cohort|processing|sequenc|flowcell|chip|slide|array|library prep|operator", re.I)
TISSUE = re.compile(r"tissue|cell type|source|organism part|organ|region|location|compartment", re.I)
Z = 1.959964 + 0.841621
UNKNOWN = re.compile(r"^(?:unknown|na|n/a|not applicable|none|-|missing|not available|nd|unclassified)$", re.I)


def _cramers_v(table_: dict[tuple[str, str], int], rows: list[str], cols: list[str]) -> float:
    n = sum(table_.values())
    if n == 0 or len(rows) < 2 or len(cols) < 2:
        return 0.0
    r = {a: sum(table_.get((a, b), 0) for b in cols) for a in rows}
    c = {b: sum(table_.get((a, b), 0) for a in rows) for b in cols}
    chi = sum((table_.get((a, b), 0) - r[a] * c[b] / n) ** 2 / (r[a] * c[b] / n) for a in rows for b in cols if r[a] and c[b])
    return math.sqrt(chi / (n * (min(len(rows), len(cols)) - 1)))


def _alias(name: str, levels: set[str], groups: dict[str, list[str]]) -> bool:
    words = {w.lower() for lv in groups["case"] + groups["control"] for w in re.findall(r"[A-Za-z]{3,}", lv)}
    return any(w in lv.lower() for lv in levels for w in words)


def check(accession: str, factor: str | None = None, case: list[str] | None = None, control: list[str] | None = None) -> dict:
    rec = record.record(accession)
    if not rec or not rec["samples"]:
        return {"accession": accession, "available": False, "reason": "the repository lists no sample table"}
    choice = volcano.groups(accession)
    if factor is None:
        if not choice["default"]:
            return {"accession": accession, "available": False, "reason": "no characteristic has a control-like group"}
        factor, case, control = choice["default"]["factor"], choice["default"]["case"], choice["default"]["control"]
    cols, rows = rec["samples"]["columns"], rec["samples"]["rows"]
    i = cols.index(factor)
    group = {r[0]: ("case" if r[i] in case else "control") for r in rows if r[i] in (case or []) + (control or [])}
    n = Counter(group.values())
    traps = []
    if min(n["case"], n["control"]) < 3:
        traps.append({"kind": "small", "title": f"{min(n['case'], n['control'])} samples in the smaller group", "detail": "too few to estimate variability", "factor": factor, "table": None})
    balanced = []
    for j, name in enumerate(cols):
        if name in ("Accession", "Title", factor):
            continue
        values = {r[0]: r[j] for r in rows if r[0] in group and r[j] and not UNKNOWN.match(r[j].strip())}
        levels = sorted(set(values.values()))
        if not 2 <= len(levels) <= 12 or len(values) < 0.6 * len(group):
            continue
        counts = Counter((values[s], group[s]) for s in values)
        v = _cramers_v(counts, levels, ["case", "control"])
        cross = [[lv, counts.get((lv, "case"), 0), counts.get((lv, "control"), 0)] for lv in levels]
        named_by_group = _alias(name, set(levels), {"case": case, "control": control}) or any(volcano.CONTROL.search(lv) for lv in levels)
        if BATCH.search(name):
            if v >= 0.25:
                traps.append({"kind": "batch", "title": f"{factor} {'goes with' if v >= 0.5 else 'partly goes with'} {name}", "detail": f"Cramér's V {v:.2f}", "factor": name, "table": cross})
            else:
                balanced.append({"factor": name, "v": round(v, 2)})
        elif v >= 0.9:
            words = lambda g: {w.lower() for lv, a, b in cross if (a if g == "case" else b) for w in re.findall(r"[A-Za-z]{4,}", lv)}
            if TISSUE.search(name) and not named_by_group and not words("case") & words("control"):
                traps.append({"kind": "tissue", "title": f"cases and controls differ in {name}", "detail": "no level is shared by both groups", "factor": name, "table": cross})
        elif len(levels) <= 4 and n["case"] and n["control"]:
            known = {g: sum(c for (lv, gg), c in counts.items() if gg == g) for g in ("case", "control")}
            if min(known.values()) == 0:
                continue
            shares = {lv: (a / known["case"], b / known["control"]) for lv, a, b in cross}
            worst = max(shares.items(), key=lambda kv: abs(kv[1][0] - kv[1][1]))
            if abs(worst[1][0] - worst[1][1]) >= 0.3:
                traps.append({"kind": "imbalance", "title": f"{name} is unbalanced", "detail": f"{worst[0]}: {worst[1][0]:.0%} of cases, {worst[1][1]:.0%} of controls with a stated value", "factor": name, "table": cross})
    power = None
    try:
        data = table.counts(accession) if re.fullmatch(r"GSE\d+", accession) else None
    except Exception:
        data = None
    if data:
        in_case = np.array([group.get(s) == "case" for s in data["samples"]])
        in_control = np.array([group.get(s) == "control" for s in data["samples"]])
        a, b = int(in_case.sum()), int(in_control.sum())
        if min(a, b) >= 2:
            m = data["matrix"].astype(float)
            values = np.log2(m / m.sum(axis=0) * 1e6 + 1) if data["kind"] == "raw counts" else (m if data["kind"] == "log scale" else np.log2(m + 1))
            expressed = (values[:, in_case | in_control] > np.percentile(values[:, in_case | in_control], 50)).mean(axis=1) > 0.5
            pooled = np.sqrt((values[expressed][:, in_case].var(axis=1, ddof=1) * (a - 1) + values[expressed][:, in_control].var(axis=1, ddof=1) * (b - 1)) / (a + b - 2))
            sd = float(np.median(pooled))
            lfc = Z * sd * math.sqrt(1 / a + 1 / b)
            power = {"n_case": a, "n_control": b, "median_sd": round(sd, 3), "detectable_log2fc": round(lfc, 3), "fold": round(2 ** lfc, 2),
                     "method": "two-sided p < 0.05 for one gene at 80% power, median within-group SD of log2 expression over expressed genes"}
    return {"accession": accession, "available": True, "factor": factor, "case": case, "control": control, "n_case": n["case"], "n_control": n["control"],
            "traps": traps, "balanced": balanced, "power": power}


if __name__ == "__main__":
    ipf = check("GSE150910")
    kinds = {(t["kind"], t["factor"]) for t in ipf["traps"]}
    print(ipf["n_case"], ipf["n_control"], kinds, ipf["power"])
    assert ("batch", "institution") in kinds and any(b["factor"] == "plate" for b in ipf["balanced"]), (kinds, ipf["balanced"])
    lung = check("GSE213001")
    assert {t["factor"] for t in lung["traps"]} >= {"age group"} and not {"diagnosis", "diseasegroup", "severity"} & {t["factor"] for t in lung["traps"]}, lung["traps"]
    donor = check("GSE124685")
    assert donor["power"] and 0 < donor["power"]["detectable_log2fc"] < 2, donor["power"]
    print("design check passed:", donor["power"])
