"""Bring your own list: a pasted gene or protein list checked against MitoCarta 3.0 (mitochondrial recovery, the
quality check an organelle IP needs) and, given a dataset, against its first-look comparison."""

import html
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from math import comb
from pathlib import Path

import httpx

from . import everywhere, volcano

MITOCARTA = "https://www.broadinstitute.org/files/shared/metabolism/mitocarta/human.mitocarta3.0.html"
CITATION = "Rath S et al. MitoCarta3.0: an updated mitochondrial proteome now with sub-organelle localization and pathway annotations. Nucleic Acids Res 2021;49:D1541-D1547"
CACHE = Path.home() / "omics-data" / "mitocarta" / "human.mitocarta3.0.html"


def _cell(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text).replace("&shy;", "").replace("&nbsp", " ")).split())


@lru_cache(maxsize=1)
def mitocarta() -> dict[str, dict]:
    """MitoCarta 3.0 human genes keyed by symbol, every synonym and UniProt accession."""
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(httpx.get(MITOCARTA, timeout=60, follow_redirects=True).raise_for_status().content)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", CACHE.read_text(encoding="latin-1"), re.S)
    header = [_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], re.S)]
    index: dict[str, dict] = {}
    for row in rows[1:]:
        cells = dict(zip(header, (_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S))))
        gene = {"symbol": cells["Symbol"], "description": cells["Description"], "evidence": cells["Evidence"].replace(" ,", ","),
                "compartment": cells["Sub-compartment"], "pathways": cells["MitoPathways"].replace(" > ", " › "), "tissues": cells["Tissues"]}
        for key in [cells["Symbol"], *(s.strip() for s in cells["Synonyms"].split(","))]:
            if key and not key.startswith("gene:"):
                index.setdefault(key.upper(), gene)
    return index


def _items(text: str) -> list[str]:
    tokens = re.split(r"[\s,;]+", text)
    out = []
    for t in tokens:
        t = re.sub(r"^(?:sp|tr)\|([A-Z0-9]+)\|.*$", r"\1", t.strip().strip('"'))
        t = re.sub(r"-\d+$", "", t)
        if t and t.upper() not in {u.upper() for u in out}:
            out.append(t)
    return out[:5000]


def _genes(text: str, mc: dict) -> tuple[list[str], callable]:
    """The pasted items, one per gene (P08574 is CYC1; the first spelling is kept), and the gene each names."""
    gene = lambda i: mc[i.upper()]["symbol"].upper() if i.upper() in mc else i.upper()
    return list({gene(i): i for i in reversed(_items(text))}.values())[::-1], gene


def _against(items: list[str], gene, look: dict) -> tuple[dict, dict[str, dict]]:
    """How many items a first-look comparison tested and found significant, against chance (hypergeometric), and each
    tested item's rank, change and q."""
    ranks = {g[0].upper(): (n + 1, g) for n, g in enumerate(look["genes"])}
    coloured = {g[0].upper() for g in look["genes"] if g[3] < look["q"] and abs(g[1]) >= look["lfc"]}
    found = [i for i in items if gene(i) in ranks]
    overlap = [i for i in found if gene(i) in coloured]
    N, K, n, k = len(ranks), len(coloured), len(found), len(overlap)
    p = sum(comb(K, j) * comb(N - K, n - j) for j in range(k, min(K, n) + 1)) / comb(N, n) if n and N else None
    each = {i: {"rank": ranks[gene(i)][0], "log2fc": ranks[gene(i)][1][1], "q": ranks[gene(i)][1][3], "coloured": i in overlap} for i in found}
    summary = {"accession": look["accession"], "factor": look["factor"], "case": look["case"], "control": look["control"], "tested": N,
               "in_table": n, "coloured": k, "expected": round(n * K / N, 1) if N else None, "p": p, "method": look["method"]}
    return summary, each


def check(text: str, accession: str = "", factor: str | None = None, case: list[str] | None = None, control: list[str] | None = None) -> dict:
    mc = mitocarta()
    items, gene = _genes(text, mc)
    rows = [{"item": i, "mitocarta": mc.get(i.upper())} for i in items]
    hits = [r for r in rows if r["mitocarta"]]
    compartments: dict[str, int] = {}
    for r in hits:
        compartments[r["mitocarta"]["compartment"] or "not stated"] = compartments.get(r["mitocarta"]["compartment"] or "not stated", 0) + 1
    result = {"items": len(items), "mitocarta": len(hits), "recovery": round(len(hits) / len(items), 3) if items else None,
              "compartments": dict(sorted(compartments.items(), key=lambda kv: -kv[1])), "rows": rows,
              "source": {"name": "MitoCarta3.0, human", "url": MITOCARTA, "citation": CITATION, "genes": len({g["symbol"] for g in mc.values()})}}
    if accession:
        look = volcano.compare(accession, factor, case, control) if factor else volcano.compare(accession)
        if look.get("available"):
            result["dataset"], each = _against(items, gene, look)
            for r in rows:
                if r["item"] in each:
                    r["dataset"] = each[r["item"]]
        else:
            result["dataset"] = {"accession": accession, "reason": look.get("reason")}
    return result


def across(text: str, accessions: list[str], hint: str = "") -> dict:
    """The list against the first-look comparison of each GEO dataset (cases against controls, chosen as for one gene
    everywhere): how many items each tested, how many are significant there against chance, and which."""
    items, gene = _genes(text, mitocarta())

    def one(accession: str) -> dict:
        try:
            pick = everywhere._pick(accession, hint)
            if not pick:
                return {"accession": accession, "reason": "no sample characteristic has a control-like group"}
            look = volcano.compare(accession, pick["factor"], pick["case"], pick["control"])
        except (httpx.HTTPError, ValueError, OSError, LookupError) as error:
            return {"accession": accession, "reason": str(error)[:200]}
        if not look.get("available"):
            return {"accession": accession, "reason": look.get("reason")}
        summary, each = _against(items, gene, look)
        hits = sorted((i for i, e in each.items() if e["coloured"]), key=lambda i: each[i]["q"])
        return summary | {"hits": [{"item": i, "log2fc": each[i]["log2fc"], "q": each[i]["q"]} for i in hits]}

    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(one, accessions[:40]))
    return {"items": len(items), "rows": rows, "compared": sum("tested" in r for r in rows)}


if __name__ == "__main__":
    mc = mitocarta()
    assert len({g["symbol"] for g in mc.values()}) == 1136, len({g["symbol"] for g in mc.values()})
    r = check("CYC1, SDHB\nP08574 ACTB GAPDH TOMM20 sp|O94826|TOM70_HUMAN NDUFA4-2")
    assert r["items"] == 7 and r["mitocarta"] == 5, [(x["item"], bool(x["mitocarta"])) for x in r["rows"]]
    ipf = check("COL1A1 COL3A1 MMP7 SPP1 ACTB GAPDH", "GSE124685")
    assert ipf["dataset"]["coloured"] >= 4, ipf["dataset"]
    wide = across("COL1A1 COL3A1 MMP7 SPP1 ACTB GAPDH", ["GSE124685", "GSE150910", "GSE36892"], "ipf")
    by = {r["accession"]: r for r in wide["rows"]}
    assert by["GSE124685"]["coloured"] == ipf["dataset"]["coloured"] and "reason" in by["GSE36892"], wide
    print("lists self-check passed:", r["mitocarta"], "of", r["items"], "in MitoCarta;", ipf["dataset"])
