"""A first look: each gene's change between two groups of samples against its significance, from the fetched counts.

Method, stated wherever the result is shown: library-size CPM, genes with CPM >= 1 in at least as many samples as the
smaller group, Welch's t-test on log2(CPM + 1), Benjamini-Hochberg FDR. It is a screen, not DESeq2 or limma-voom."""

import re
from pathlib import Path
from xml.etree import ElementTree

import httpx
import numpy as np
from scipy import stats

from . import record, table

FULLTEXT = Path.home() / ".cache" / "omics-agent" / "fulltext"
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UP = re.compile(r"\b(?:increas|elevat|up-?regulat|higher|induc|enrich|overexpress|gain)", re.I)
DOWN = re.compile(r"\b(?:decreas|reduc|down-?regulat|lower|loss|lost|depleted|suppress|diminish)", re.I)
# Gene symbols that are also ordinary words or common abbreviations in papers.
NOT_GENES = {"SET", "CAT", "MAX", "REST", "CAMP", "PIGS", "HAS", "TAT", "SHE", "WAS", "CAD", "AIM", "IMPACT", "ACE", "CLOCK", "MET", "ARC",
             "BAD", "CAST", "COPD", "IPF", "MAP", "MARCH", "SEPT", "PC", "TNF", "AGO", "ATM", "BID", "CAP", "CAR", "COIL", "DO", "GC", "HR", "IMP",
             "MAL", "NHS", "PAH", "PIN", "POLE", "RAN", "RET", "SDS", "STAR", "TEC", "TH", "TOP", "WARS", "FAT", "SRY", "CPM", "DNA", "RNA", "PCR"}

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
        return {"accession": accession, "available": False, "reason": "no gene by sample table: neither NCBI's counts nor the authors' files"}
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
    smaller = min(n_case, n_control)
    if data["kind"] == "raw counts":
        cpm = m / m.sum(axis=0) * 1e6
        keep = (cpm[:, in_case | in_control] >= 1).sum(axis=1) >= smaller
        logged = np.log2(cpm[keep] + 1)
        method = METHOD
    else:
        values = m if data["kind"] == "log scale" else np.log2(m + 1)
        floor = np.percentile(values[:, in_case | in_control], 25)
        keep = (values[:, in_case | in_control] > floor).sum(axis=1) >= smaller
        logged = values[keep]
        method = f"Welch's t-test on the authors' {'log-scale' if data['kind'] == 'log scale' else 'normalised values, log2(x + 1)'}; genes above the 25th percentile in at least as many samples as the smaller group; Benjamini–Hochberg FDR"
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
        "n_case": n_case, "n_control": n_control, "tested": int(keep.sum()), "method": method, "q": Q, "lfc": LFC,
        "up": len(up), "down": len(down), "genes": genes, "source": data["source"], "groups": choice,
    }


def _fulltext(paper: str) -> tuple[ElementTree.Element | None, dict]:
    query = f"EXT_ID:{paper[5:]} AND SRC:MED" if paper.startswith("pmid:") else f'DOI:"{paper[4:]}"'
    found = httpx.get(f"{EUROPE_PMC}/search", params={"query": query, "format": "json", "resultType": "core"}, timeout=30).json()["resultList"]["result"]
    if not found:
        return None, {"paper": paper, "reason": "not found in Europe PMC"}
    hit = found[0]
    head = {"paper": paper, "pmcid": hit.get("pmcid"), "title": hit.get("title", ""), "journal": (hit.get("journalInfo") or {}).get("journal", {}).get("title", ""),
            "year": hit.get("pubYear", "")}
    if not hit.get("pmcid") or hit.get("isOpenAccess") != "Y":
        return None, head | {"reason": "the paper has no open-access full text"}
    path = FULLTEXT / f"{hit['pmcid']}.xml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(httpx.get(f"{EUROPE_PMC}/{hit['pmcid']}/fullTextXML", timeout=60).raise_for_status().content)
    return ElementTree.fromstring(path.read_bytes()), head | {"url": f"https://europepmc.org/article/PMC/{hit['pmcid']}"}


def paper_genes(accession: str, look: dict) -> dict:
    """The genes the dataset's paper names in its results (open-access full text, methods left out), where each lands on
    this comparison, and whether the sentence naming it states the same direction."""
    rec = record.record(accession)
    papers = [p["id"] for p in rec["papers"] if p.get("id")] if rec else []
    if not papers:
        return {"available": False, "reason": "no paper is linked to this dataset"}
    root, head = _fulltext(papers[0])
    if root is not None:
        body = root.find("body")
        methods = {id(p) for sec in (body.iter("sec") if body is not None else []) if re.search(r"method|materials", sec.findtext("title") or "", re.I) for p in sec.iter()}
        texts = [(" ".join("".join(el.itertext()).split()), "figure legend" if el.tag == "caption" else "text") for el in (body.iter() if body is not None else []) if el.tag in ("p", "caption") and id(el) not in methods]
        head |= {"read": "open-access full text, methods left out"}
    elif head.get("pmcid") or papers[0].startswith("pmid:"):
        ids = f"PMC:{head['pmcid']}" if head.get("pmcid") else f"MED:{papers[0][5:]}"
        found = httpx.get(f"https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds", params={"articleIds": ids, "type": "Gene_Proteins", "format": "JSON"}, timeout=30).json()
        mentions = found[0]["annotations"] if found else []
        texts = [(" ".join(f"{m.get('prefix', '')} {m['exact']} {m.get('postfix', '')}".split()), re.sub(r"\s*\(http.*", "", m.get("section") or "figure or table"))
                 for m in mentions if not re.search(r"method", m.get("section") or "", re.I)]
        if not texts:
            return {"available": False} | head
        head = {k: v for k, v in head.items() if k != "reason"} | {"read": "Europe PMC text-mined gene mentions (no open-access full text)",
                                                                    "url": f"https://europepmc.org/article/MED/{papers[0][5:]}" if papers[0].startswith("pmid:") else ""}
    else:
        return {"available": False} | head
    here = {g[0]: g for g in look["genes"]}
    named: dict[str, dict] = {}
    for text, where in texts:
        for sentence in re.split(r"(?<=[.;])\s+(?=[A-Z(])", text):
            for symbol in dict.fromkeys(re.findall(r"(?<![\w-])[A-Z][A-Z0-9]{2,}(?![\w-])", sentence)):
                if symbol in here and symbol not in NOT_GENES and symbol not in named:
                    up, down = bool(UP.search(sentence)), bool(DOWN.search(sentence))
                    says = "higher" if up and not down else "lower" if down and not up else None
                    g = here[symbol]
                    significant = g[3] < look["q"] and abs(g[1]) >= look["lfc"]
                    agrees = None if says is None or not significant else (says == "higher") == (g[1] > 0)
                    named[symbol] = {"gene": symbol, "sentence": sentence if sentence != symbol else None, "where": where, "says": says, "log2fc": g[1], "q": g[3], "significant": significant, "agrees": agrees}
    genes = sorted(named.values(), key=lambda n: n["q"])
    return {"available": True, **head, "genes": genes, "named": len(genes), "significant": sum(n["significant"] for n in genes),
            "agree": sum(n["agrees"] is True for n in genes), "disagree": sum(n["agrees"] is False for n in genes),
            "by_chance": round(len(genes) * (look["up"] + look["down"]) / look["tested"], 1)}


if __name__ == "__main__":
    g = groups("GSE124685")
    assert g["default"] == {"factor": "disease state", "case": ["IPF"], "control": ["healthy donor"]}, g["default"]
    r = compare("GSE124685")
    assert (r["n_case"], r["n_control"]) == (49, 35), (r["n_case"], r["n_control"])
    top = {g[0]: g for g in r["genes"][:2000]}
    for gene in ("MMP7", "SPP1", "COL1A1"):
        assert gene in top and top[gene][1] > 1, (gene, top.get(gene))
    check = paper_genes("GSE124685", r)
    assert check["available"] and check["named"] >= 5, {k: v for k, v in check.items() if k != "genes"}
    print("paper check:", {k: v for k, v in check.items() if k != "genes"})
    print("volcano self-check passed:", r["tested"], "genes tested,", r["up"], "up,", r["down"], "down; top", [g[0] for g in r["genes"][:8]])
