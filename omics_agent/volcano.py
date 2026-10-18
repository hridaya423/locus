"""A first look: each gene's change between two groups of samples against its significance, from the fetched counts.

Method, stated wherever the result is shown: library-size CPM, genes with CPM >= 1 in at least as many samples as the
smaller group, Welch's t-test on log2(CPM + 1), Benjamini-Hochberg FDR. It is a screen, not DESeq2 or limma-voom."""

import re
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree

import httpx
import numpy as np
from scipy import stats

from . import design, record, table

FULLTEXT = Path.home() / ".cache" / "omics-agent" / "fulltext"
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
# Gene symbols that are also ordinary words or common abbreviations in papers.
NOT_GENES = {"SET", "CAT", "MAX", "REST", "CAMP", "PIGS", "HAS", "TAT", "SHE", "WAS", "CAD", "AIM", "IMPACT", "ACE", "CLOCK", "MET", "ARC",
             "BAD", "CAST", "COPD", "IPF", "MAP", "MARCH", "SEPT", "PC", "TNF", "AGO", "ATM", "BID", "CAP", "CAR", "COIL", "DO", "GC", "HR", "IMP",
             "MAL", "NHS", "PAH", "PIN", "POLE", "RAN", "RET", "SDS", "STAR", "TEC", "TH", "TOP", "WARS", "FAT", "SRY", "CPM", "DNA", "RNA", "PCR"}

# Pooled quality-control injections are neither cases nor controls (MTBLS10965: "pooled quality control sample").
QC_SAMPLE = re.compile(r"quality control|\bQC\b|\bpooled\b|\bblank\b", re.I)
CONTROL = re.compile(r"control|healt?h?y|normal|\bwt\b|^wt[_ -]?(?:ev|empty|vector|ctrl|\d+)$|empty vector|wild[- ]?type|vehicle|dmso|untreated|mock|baseline|donor|non-?diseased|sham|ctrl|\bnc\b", re.I)
METHOD = "Welch's t-test on log2(CPM + 1); genes with CPM ≥ 1 in at least as many samples as the smaller group; Benjamini–Hochberg FDR"
Q, LFC = 0.05, 1.0
# Metabolite levels move less than transcripts; a 1.5-fold change is the usual cut-off in metabolomics.
METABOLITE_LFC = 0.585


NUISANCE = re.compile(r"donor|patient|individual|subject|\bid\b|platform|batch|lane|run|replicate|\brep\b|sex|gender|\bage\b|title|library|molecule|"
                      r"flowcell|barcode|instrument|sequenc|plate|well|chip|slide|array|sample name", re.I)
EXPERIMENTAL = re.compile(r"cell line|cell type|strain|genotype|treatment|time|dose|agent|drug|knock|condition|stimul|infection|passage", re.I)
PREFER = re.compile(r"disease|diagnosis|condition|treatment|genotype|group|phenotype|state|status|infection|agent|stimul|drug|knock|strain|tissue type", re.I)


def _negated(level: str, levels: list[str]) -> bool:
    """'no PH (no pulmonary hypertension)' beside 'PH (pulmonary hypertension)': the absence of another level is its control.
    'Non-small cell lung cancer' names no other level, so it stays a case."""
    rest = re.sub(r"^(?:no|non)[- ]", "", level, flags=re.I)
    return rest != level and any(o != level and o.split()[0].lower() == rest.split()[0].lower() for o in levels if o.split())


def _keyed_control(level: str, about: str) -> bool:
    """A sample-name prefix the description keys to a control group: PXD047213's 'XAD1—XAD18 --- HCC adjacent normal tissues'."""
    return bool(re.search(rf"\b{re.escape(level)}\d*\b[^,;.\n]{{0,60}}?\b(?:adjacent|normal|control|healthy)\b", about, re.I))


def groups(accession: str, present: set[str] | None = None) -> dict:
    """The sample table's factors that could split cases from controls, counted over the samples that have data, and the
    default comparison: only a non-nuisance factor with a control-like level; no default otherwise."""
    rec = record.record(accession)
    if not rec or not rec["samples"]:
        return {"factors": [], "default": None}
    cols, rows = rec["samples"]["columns"], rec["samples"]["rows"]
    rows = [r for r in rows if present is None or r[0] in present]
    factors = []
    for i, name in enumerate(cols):
        if name in ("Accession", "Title"):
            continue
        levels: dict[str, int] = {}
        for r in rows:
            if r[i]:
                levels[r[i]] = levels.get(r[i], 0) + 1
        if 2 <= len(levels) <= 12 and sum(n >= 2 for n in levels.values()) >= 2:
            factors.append({"name": name, "levels": dict(sorted(levels.items(), key=lambda kv: -kv[1])), "nuisance": bool(NUISANCE.search(name))})
    about = " ".join(text for _, text in rec.get("texts", []))
    default = None
    for f in sorted((f for f in factors if not f["nuisance"]), key=lambda f: not PREFER.search(f["name"])):
        usable = [lv for lv in f["levels"] if f["levels"][lv] >= 2 and not QC_SAMPLE.search(lv)]
        controls = [lv for lv in usable if CONTROL.search(lv) or _negated(lv, usable)] or [lv for lv in usable if _keyed_control(lv, about)]
        # 'WT EGD' beside 'KO EGD' is wild type under a second condition, not the baseline (PXD011513).
        controls = [lv for lv in controls if not ((rest := re.sub(r"[\s_-]+", " ", CONTROL.sub(" ", lv)).strip()) and any(rest in o for o in usable if o not in controls))] or controls
        cases = [lv for lv in usable if lv not in controls]
        if controls and cases:
            default = {"factor": f["name"], "case": [max(cases, key=f["levels"].get)], "control": controls}
            break
    return {"factors": factors, "default": default}


def compare(accession: str, factor: str | None = None, case: list[str] | None = None, control: list[str] | None = None,
            within: tuple[str, str] | None = None) -> dict:
    data = table.counts(accession)
    if not data:
        reason = ("no gene by sample table: neither NCBI's counts nor the authors' files" if accession.startswith("GSE")
                  else "no MaxQuant protein table with intensities for at least 4 named samples" if accession.startswith("PXD")
                  else "no metabolite by sample table whose columns are the samples")
        return {"accession": accession, "available": False, "reason": reason}
    rec = record.record(accession)
    present = set(data["samples"])
    choice = groups(accession, present)
    base = {"accession": accession, "groups": choice, "samples_with_data": len(present & {r[0] for r in rec["samples"]["rows"]}),
            "record_samples": len(rec["samples"]["rows"])}
    if factor is None:
        if not choice["default"]:
            return base | {"available": False, "reason": "no characteristic has a control-like group; choose two groups to compare"}
        factor, case, control = choice["default"]["factor"], choice["default"]["case"], choice["default"]["control"]
    cols = rec["samples"]["columns"]
    if factor not in cols:
        return base | {"available": False, "reason": f"no sample characteristic named {factor}"}
    if not case or not control:
        f = next((f for f in choice["factors"] if f["name"] == factor), None)
        controls = [lv for lv in (f["levels"] if f else {}) if CONTROL.search(lv)]
        cases = [lv for lv in (f["levels"] if f else {}) if lv not in controls]
        if not (controls and cases):
            return base | {"available": False, "reason": f"{factor} has no control-like level; name the case and control levels"}
        case, control = case or [max(cases, key=f["levels"].get)], control or controls
    if set(case) & set(control):
        return base | {"available": False, "reason": "the case and control groups overlap"}
    value = {r[0]: r for r in rec["samples"]["rows"]}
    keep_row = lambda s: s in value and (within is None or (within[0] in cols and value[s][cols.index(within[0])] == within[1]))
    level = {s: value[s][cols.index(factor)] for s in data["samples"] if keep_row(s)}
    in_case = np.array([level.get(s) in case for s in data["samples"]])
    in_control = np.array([level.get(s) in control for s in data["samples"]])
    n_case, n_control = int(in_case.sum()), int(in_control.sum())
    if min(n_case, n_control) < 2:
        return base | {"available": False, "reason": f"{n_case} case and {n_control} control samples have data; each group needs at least 2"}

    m = data["matrix"].astype(float)
    smaller = min(n_case, n_control)
    if data["kind"] == "raw counts":
        cpm = m / m.sum(axis=0) * 1e6
        keep = (cpm[:, in_case | in_control] >= 1).sum(axis=1) >= smaller
        logged = np.log2(cpm[keep] + 1)
        method = METHOD
    else:
        values = m if data["kind"] == "log scale" else np.log2(m + 1)
        feature = data.get("feature", "gene")
        if feature == "gene":
            floor = np.nanpercentile(values[:, in_case | in_control], 25)
            keep = (values[:, in_case | in_control] > floor).sum(axis=1) >= smaller
            kept = "above the 25th percentile"
        else:
            # A metabolite panel or protein table is already what the authors could measure; a low concentration is not
            # noise (ST003390's cysteic acid, p 4e-23, fell under a matrix-wide percentile).
            measured = np.isfinite(m) & (m != 0) if data["kind"] != "log scale" else np.isfinite(m)
            keep = measured[:, in_case | in_control].sum(axis=1) >= smaller
            kept = "measured"
        logged = values[keep]
        method = f"Welch's t-test on the authors' {'log-scale' if data['kind'] == 'log scale' else 'normalised values, log2(x + 1)'}; {feature}s {kept} in at least as many samples as the smaller group; Benjamini–Hochberg FDR"
    a, b = logged[:, in_case], logged[:, in_control]
    # Protein tables leave unquantified values missing; every statistic skips them (count tables have none).
    lfc = np.nanmean(a, axis=1) - np.nanmean(b, axis=1)
    t, p = stats.ttest_ind(a, b, axis=1, equal_var=False, nan_policy="omit")
    p = np.asarray(p, dtype=float)
    p = np.nan_to_num(p, nan=1.0)
    q = stats.false_discovery_control(p)
    symbols = [str(s) if not str(s).isdigit() else f"GeneID:{s}" for s in np.array(data["symbols"])[keep]]
    order = np.argsort(p)
    genes = [[symbols[i], round(float(lfc[i]), 3), round(float(-np.log10(max(p[i], 1e-300))), 3), float(f"{q[i]:.3g}")] for i in order]
    cut = METABOLITE_LFC if data.get("feature") == "metabolite" else LFC
    up = int(((q < Q) & (lfc >= cut)).sum())
    down = int(((q < Q) & (lfc <= -cut)).sum())
    chosen = [s for s in data["samples"] if level.get(s) in case + control]
    pooled = []
    for i, name in enumerate(cols):
        if name in ("Accession", "Title", factor) or NUISANCE.search(name) or not EXPERIMENTAL.search(name) or re.match(r"rs\d", name):
            continue
        seen = {g: {value[s][i] for s in chosen if level.get(s) in grp and value[s][i]} for g, grp in (("case", case), ("control", control))}
        if len(seen["case"]) > 1 and len(seen["control"]) > 1 and sorted(seen["case"] | seen["control"]) not in [p["levels"] for p in pooled]:
            pooled.append({"factor": name, "levels": sorted(seen["case"] | seen["control"])})
    warnings = []
    if smaller < 3:
        warnings.append(f"{smaller} samples in the smaller group: too few for a reliable test")
    if max(n_case, n_control) > 4 * smaller:
        warnings.append(f"groups of {n_case} and {n_control} are unbalanced")
    warnings += [f"pooled across {p['factor']} ({', '.join(p['levels'][:4])}{'…' if len(p['levels']) > 4 else ''})" for p in pooled]
    # Several samples from one person (single cells, repeated visits) are not independent; the test counts them as if they were.
    people = design.people(accession, {"factor": factor, "case": case, "control": control})
    if people and people.get("case") and people["case"] + people["control"] < n_case + n_control:
        warnings.append(f"the {n_case + n_control} samples come from {people['case']} and {people['control']} people ({people['field']}); "
                        f"samples from one person are not independent, so these q values overstate the evidence")
    return base | {
        "available": True, "factor": factor, "case": case, "control": control, "within": list(within) if within else None,
        "n_case": n_case, "n_control": n_control, "tested": int(keep.sum()), "method": method, "q": Q, "lfc": cut,
        "up": up, "down": down, "genes": genes, "source": data["source"], "pooled": pooled, "warnings": warnings, "feature": data.get("feature", "gene"),
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


ENRICHR = "https://maayanlab.cloud/Enrichr"
LIBRARY = "Reactome_2022"
PATHWAY_GENES, PATHWAYS_SHOWN = 200, 8


@lru_cache(maxsize=128)
def _enrich(genes: tuple[str, ...]) -> list:
    added = httpx.post(f"{ENRICHR}/addList", files={"list": (None, "\n".join(genes)), "description": (None, "locus first look")}, timeout=30).raise_for_status().json()
    return httpx.get(f"{ENRICHR}/enrich", params={"userListId": added["userListId"], "backgroundType": LIBRARY}, timeout=30).raise_for_status().json()[LIBRARY]


UNIPROT = re.compile(r"[OPQ]\d[A-Z\d]{3}\d|[A-NR-Z]\d(?:[A-Z][A-Z\d]{2}\d){1,2}")
FEW_PROTEINS = 1000


def _not_genes(look: dict, universe: bool = True) -> str | None:
    """Why a protein comparison cannot be read as genes: proteins named by UniProt ID, or too few tested for a genome-wide background."""
    if look.get("feature") == "phosphosite":
        return "the rows are phosphosites, and a site's change is not its gene's"
    if look.get("feature") != "protein":
        return None
    if sum(bool(UNIPROT.fullmatch(g[0])) for g in look["genes"]) > len(look["genes"]) / 2:
        return "the proteins are named by UniProt ID, not gene symbols"
    if universe and look["tested"] < FEW_PROTEINS:
        return f"{look['tested']:,} proteins were tested, too few to compare against a whole-genome background"
    return None


def pathways(look: dict) -> dict:
    """Reactome pathways over-represented among the most significant genes up and down, from Enrichr."""
    if reason := _not_genes(look):
        return {"available": False, "reason": reason}
    sides = {}
    for side, sign in (("up", 1), ("down", -1)):
        genes = [g[0].upper() for g in look["genes"] if g[3] < look["q"] and sign * g[1] >= look["lfc"] and not g[0].startswith("GeneID:")][:PATHWAY_GENES]
        if len(genes) < 5:
            sides[side] = {"genes": len(genes), "terms": [], "reason": f"{len(genes)} significant genes; Enrichr needs at least 5"}
            continue
        terms = [{"term": re.sub(r"\s*R-HSA-\d+$", "", r[1]), "id": (re.search(r"R-HSA-\d+", r[1]) or [""])[0], "p": r[2], "q": r[6], "genes": r[5]}
                 for r in _enrich(tuple(genes)) if r[6] < 0.05]
        sides[side] = {"genes": len(genes), "terms": terms[:PATHWAYS_SHOWN], "significant": len(terms)}
    return {"available": True, "library": LIBRARY, "source": f"{ENRICHR}/", "sides": sides,
            "method": f"The {PATHWAY_GENES} most significant genes each way (q < {look['q']}, |log2FC| ≥ {look['lfc']:g}) sent to Enrichr; Fisher's exact test against "
                      f"Enrichr's whole-genome background, not the {look['tested']:,} genes tested here; Benjamini–Hochberg q < 0.05"}


def paper_genes(accession: str, look: dict) -> dict:
    """The genes the dataset's paper names in its results (open-access full text, methods left out), where each lands on
    this comparison, and whether the sentence naming it states the same direction."""
    if reason := _not_genes(look, universe=False):
        return {"available": False, "reason": reason}
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
                    g = here[symbol]
                    named[symbol] = {"gene": symbol, "sentence": sentence if sentence != symbol else None, "where": where,
                                     "log2fc": g[1], "q": g[3], "significant": g[3] < look["q"] and abs(g[1]) >= look["lfc"]}
    genes = sorted(named.values(), key=lambda n: n["q"])
    return {"available": True, **head, "genes": genes, "named": len(genes), "significant": sum(n["significant"] for n in genes),
            "by_chance": round(len(genes) * (look["up"] + look["down"]) / look["tested"], 1)}


if __name__ == "__main__":
    g = groups("GSE124685")
    assert g["default"] == {"factor": "disease state", "case": ["IPF"], "control": ["healthy donor"]}, g["default"]
    r = compare("GSE124685")
    assert (r["n_case"], r["n_control"]) == (49, 35), (r["n_case"], r["n_control"])
    top = {x[0]: x for x in r["genes"][:2000]}
    for gene in ("MMP7", "SPP1", "COL1A1"):
        assert gene in top and top[gene][1] > 1, (gene, top.get(gene))
    partial = compare("GSE254942")
    assert "groups" in partial and (partial["available"] or partial["reason"]), "a partial table must not lose the pickers"
    assert compare("GSE150411")["available"] is False or compare("GSE150411")["factor"] != "donor", "donor is never the default"
    assert not compare("GSE124685", "disease state", ["IPF"], ["IPF"])["available"], "overlapping groups are refused"
    pooled = compare("GSE227269")
    assert not pooled["available"] or pooled["pooled"] or pooled["factor"] != "treatment", pooled.get("warnings")
    check = paper_genes("GSE124685", r)
    assert check["available"] and check["named"] >= 5, {k: v for k, v in check.items() if k != "genes"}
    print("volcano self-check passed:", r["tested"], "tested,", r["up"], "up,", r["down"], "down; GSE227269", pooled.get("warnings"), pooled.get("factor"))
