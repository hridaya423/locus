"""One gene across many datasets: its change between each dataset's cases and controls, one row per dataset."""

import re
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import record, table, volcano


def _pick(accession: str, hint: str) -> dict | None:
    """The comparison to use: the factor with a control-like level, its case level preferring words of the hint."""
    choice = volcano.groups(accession)
    words = [w for w in re.findall(r"[a-z0-9]{3,}", hint.lower())]
    for f in choice["factors"]:
        controls = [lv for lv in f["levels"] if volcano.CONTROL.search(lv)]
        cases = [lv for lv in f["levels"] if lv not in controls]
        if controls and cases:
            hinted = [lv for lv in cases if any(w in lv.lower() for w in words)]
            return {"factor": f["name"], "case": [hinted[0] if hinted else max(cases, key=f["levels"].get)], "control": controls}
    return choice["default"]


def one(gene: str, accession: str, hint: str = "") -> dict:
    rec = record.record(accession)
    row = {"accession": accession, "title": rec["title"] if rec else ""}
    try:
        pick = _pick(accession, hint)
        if not pick:
            return row | {"status": "no groups", "reason": "the sample table has no factor with a control-like level"}
        look = volcano.compare(accession, pick["factor"], pick["case"], pick["control"])
    except (httpx.HTTPError, ValueError, OSError, LookupError) as error:
        return row | {"status": "failed", "reason": str(error)[:200]}
    if not look.get("available"):
        return row | {"status": "no table", "reason": look.get("reason", "")}
    hit = next((g for g in look["genes"] if g[0].upper() == gene.upper()), None)
    base = row | {"factor": look["factor"], "case": look["case"], "control": look["control"], "n_case": look["n_case"], "n_control": look["n_control"],
                  "source": look["source"]["pipeline"], "file": look["source"]["file"]}
    if not hit:
        present = gene.upper() in (s.upper() for s in table.counts(accession)["symbols"])
        return base | {"status": "not tested", "reason": "expressed too low to test" if present else "not in the table"}
    significant = hit[3] < look["q"] and abs(hit[1]) >= look["lfc"]
    return base | {"status": "higher" if significant and hit[1] > 0 else "lower" if significant else "no clear change",
                   "log2fc": hit[1], "minus_log10_p": hit[2], "q": hit[3], "rank": look["genes"].index(hit) + 1, "tested": look["tested"]}


def gene_everywhere(gene: str, accessions: list[str], hint: str = "") -> dict:
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda a: one(gene, a, hint), accessions))
    measured = [r for r in rows if "log2fc" in r]
    described = next((info for info in table._genes("Homo sapiens").values() if info[0].upper() == gene.upper()), None)
    return {
        "gene": gene.upper(), "description": described[1] if described else "not stated", "hint": hint, "rows": rows,
        "measured": len(measured), "higher": sum(r["status"] == "higher" for r in rows), "lower": sum(r["status"] == "lower" for r in rows),
        "method": volcano.METHOD,
    }


if __name__ == "__main__":
    result = gene_everywhere("SPP1", ["GSE124685", "GSE150910", "GSE213001", "GSE52463", "GSE36892"], "ipf idiopathic pulmonary fibrosis")
    by = {r["accession"]: r for r in result["rows"]}
    assert all(by[a]["log2fc"] > 1 for a in ("GSE124685", "GSE150910", "GSE213001", "GSE52463")), result
    assert by["GSE36892"]["status"] in ("no table", "no groups"), by["GSE36892"]
    print("everywhere self-check passed:", result["higher"], "higher of", result["measured"], "measured")
