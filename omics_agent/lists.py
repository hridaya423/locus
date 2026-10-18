"""Bring your own list: a pasted gene or protein list checked against MitoCarta 3.0 (mitochondrial recovery, the
quality check an organelle IP needs) and, given a dataset, against its first-look comparison."""

import html
import re
from functools import lru_cache
from math import comb
from pathlib import Path

import httpx

from . import volcano

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


def check(text: str, accession: str = "", factor: str | None = None, case: list[str] | None = None, control: list[str] | None = None) -> dict:
    items = _items(text)
    mc = mitocarta()
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
            ranks = {g[0].upper(): (n + 1, g) for n, g in enumerate(look["genes"])}
            coloured = {g[0].upper() for g in look["genes"] if g[3] < look["q"] and abs(g[1]) >= look["lfc"]}
            found = [i for i in items if i.upper() in ranks]
            overlap = [i for i in found if i.upper() in coloured]
            N, K, n, k = len(ranks), len(coloured), len(found), len(overlap)
            p = sum(comb(K, j) * comb(N - K, n - j) for j in range(k, min(K, n) + 1)) / comb(N, n) if n and N else None
            for r in rows:
                if r["item"].upper() in ranks:
                    rank, g = ranks[r["item"].upper()]
                    r["dataset"] = {"rank": rank, "log2fc": g[1], "q": g[3], "coloured": r["item"].upper() in coloured}
            result["dataset"] = {"accession": accession, "factor": look["factor"], "case": look["case"], "control": look["control"], "tested": N,
                                 "in_table": n, "coloured": k, "expected": round(n * K / N, 1) if N else None, "p": p, "method": look["method"]}
        else:
            result["dataset"] = {"accession": accession, "reason": look.get("reason")}
    return result


if __name__ == "__main__":
    mc = mitocarta()
    assert len({g["symbol"] for g in mc.values()}) == 1136, len({g["symbol"] for g in mc.values()})
    r = check("CYC1, SDHB\nP08574 ACTB GAPDH TOMM20 sp|O94826|TOM70_HUMAN NDUFA4-2")
    assert r["items"] == 8 and r["mitocarta"] == 6, [(x["item"], bool(x["mitocarta"])) for x in r["rows"]]
    ipf = check("COL1A1 COL3A1 MMP7 SPP1 ACTB GAPDH", "GSE124685")
    assert ipf["dataset"]["coloured"] >= 4, ipf["dataset"]
    print("lists self-check passed:", r["mitocarta"], "of", r["items"], "in MitoCarta;", ipf["dataset"])
