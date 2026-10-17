import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PRIDE = "https://www.ebi.ac.uk/pride/ws/archive/v3/search/projects"
CELLXGENE = "https://api.cellxgene.cziscience.com/curation/v1/datasets"
CACHE = Path.home() / ".cache" / "omics-agent" / "cellxgene.json"


def ncbi_get(url: str, params: dict) -> httpx.Response:
    """NCBI allows 3 requests a second, or 10 with NCBI_API_KEY; back off and retry when throttled."""
    if key := os.environ.get("NCBI_API_KEY"):
        params = {**params, "api_key": key}
    for attempt in range(4):
        response = httpx.get(url, params=params, timeout=60)
        if response.status_code != 429 and "API rate limit exceeded" not in response.text[:200]:
            response.raise_for_status()
            return response
        time.sleep(1 + attempt)
    response.raise_for_status()
    return response


@dataclass
class Dataset:
    accession: str
    source: str
    modality: str
    title: str
    organism: str
    samples: int | None
    url: str
    text: str
    papers: list[str] = field(default_factory=list)
    facts: dict | None = None
    published: str | None = None


def _geo_ids(query: str, limit: int) -> list[str]:
    return ncbi_get(
        f"{EUTILS}/esearch.fcgi",
        {"db": "gds", "term": query, "retmode": "json", "retmax": limit},
    ).json()["esearchresult"].get("idlist", [])


def search_geo(plan: dict, limit: int) -> list[Dataset]:
    """Run the planner's precise query first; top up with a broad synonym query if it finds too little."""
    scope = " AND gse[ETYP]"
    if plan["organism"]:
        scope += f' AND "{plan["organism"]}"[Organism]'
    ids = _geo_ids(f"({plan['geo_query']}){scope}", limit) if plan.get("geo_query") else []
    if len(ids) < limit // 2:
        broad = "(" + " OR ".join(f'"{t}"[All Fields]' for t in plan["terms"]) + ")"
        ids += [i for i in _geo_ids(broad + scope, limit - len(ids)) if i not in ids]
    if not ids:
        return []
    result = {}
    for start in range(0, len(ids), 200):
        batch = ncbi_get(f"{EUTILS}/esummary.fcgi", {"db": "gds", "id": ",".join(ids[start:start + 200]), "retmode": "json"}).json()["result"]
        result |= {uid: batch[uid] for uid in batch["uids"]}
    return [
        Dataset(
            accession=r["accession"],
            source="GEO",
            modality=r["gdstype"],
            title=r["title"],
            organism=r["taxon"],
            samples=int(r["n_samples"]),
            url=f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={r['accession']}",
            text=f"{r['title']}\n{r['summary']}",
            papers=[f"pmid:{p}" for p in r.get("pubmedids") or []],
            published=r.get("pdat", "").replace("/", "-") or None,
        )
        for r in result.values()
    ]


def _pride_papers(references: list[str]) -> list[str]:
    papers = []
    for ref in references:
        papers += [f"pmid:{m}" for m in re.findall(r"pubMed:(\d+)", ref) if m != "0"]
        papers += [f"doi:{m.lower().rstrip('.')}" for m in re.findall(r"doi:\s*(10\.\S+)", ref)]
    return papers


def search_pride(plan: dict, limit: int) -> list[Dataset]:
    found: dict[str, Dataset] = {}
    organism = plan["organism"]
    for keyword in plan.get("pride_keywords") or plan["terms"]:
        projects = httpx.get(PRIDE, params={"keyword": keyword, "pageSize": limit}, timeout=30).json()
        for p in projects:
            organisms = ", ".join(p.get("organisms") or [])
            if organism and organism.lower() not in organisms.lower():
                continue
            found.setdefault(
                p["accession"],
                Dataset(
                    accession=p["accession"],
                    source="PRIDE",
                    modality="Proteomics: " + ", ".join(p.get("experimentTypes") or []),
                    title=p["title"],
                    organism=organisms,
                    samples=None,
                    url=f"https://www.ebi.ac.uk/pride/archive/projects/{p['accession']}",
                    text=(
                        f"{p['title']}\n{p.get('projectDescription', '')}\n"
                        f"Diseases: {', '.join(p.get('diseases') or [])}\n"
                        f"Tissues: {', '.join(p.get('organismsPart') or [])}\n"
                        f"Instruments: {', '.join(p.get('instruments') or [])}"
                    ),
                    papers=_pride_papers(p.get("references") or []),
                ),
            )
    return list(found.values())[:limit]


def _cellxgene_datasets() -> list[dict]:
    if CACHE.exists() and time.time() - CACHE.stat().st_mtime < 86400:
        return json.loads(CACHE.read_text())
    datasets = httpx.get(CELLXGENE, timeout=120).json()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(datasets))
    return datasets


def cellxgene_facts(d: dict) -> dict:
    """Control and tissue facts straight from a CELLxGENE dataset's curated labels."""
    return {
        "case": None,
        "control": None,
        "has_control": any(x["label"] == "normal" for x in d.get("disease") or []),
        "sample_type": "patient_tissue" if d.get("is_primary_data") else "unknown",
        "tissue": ", ".join(x["label"] for x in d.get("tissue") or []),
        "source": "CELLxGENE disease labels",
    }


def cellxgene_diseases() -> list[str]:
    return sorted({x["label"] for d in _cellxgene_datasets() for x in d.get("disease") or []} - {"normal"})


def search_cellxgene(plan: dict, limit: int) -> list[Dataset]:
    """Match the planner's exact CELLxGENE disease labels; fall back to the search terms in the text."""
    wanted = set(plan.get("cellxgene_diseases") or [])
    pattern = re.compile("|".join(rf"\b{re.escape(t)}\b" for t in plan["terms"]), re.IGNORECASE)
    organism = plan["organism"]
    hits = []
    for d in _cellxgene_datasets():
        labels = lambda key: ", ".join(x["label"] for x in d.get(key) or [])
        organisms = labels("organism")
        if organism and organism.lower() not in organisms.lower():
            continue
        label_match = bool(wanted & {x["label"] for x in d.get("disease") or []})
        text = (
            f"{d['title']}\nCollection: {d['collection_name']}\n"
            f"Diseases: {labels('disease')}\nTissues: {labels('tissue')}\n"
            f"Cells: {d['cell_count']}, donors: {len(d.get('donor_id') or [])}"
        )
        if not label_match and not pattern.search(text):
            continue
        hits.append(
            Dataset(
                accession=d["dataset_id"],
                source="CELLxGENE",
                modality="Single-cell: " + labels("assay"),
                title=d["title"],
                organism=organisms,
                samples=len(d.get("donor_id") or []) or None,
                url=f"https://cellxgene.cziscience.com/collections/{d['collection_id']}",
                text=text,
                papers=[f"doi:{d['collection_doi'].lower()}"] if d.get("collection_doi") else [],
                facts=cellxgene_facts(d),
            )
        )
    return hits[:limit]

