import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import httpx

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PRIDE = "https://www.ebi.ac.uk/pride/ws/archive/v3/search/projects"
CELLXGENE = "https://api.cellxgene.cziscience.com/curation/v1/datasets"
CACHE = Path.home() / ".cache" / "omics-agent" / "cellxgene.json"


_ncbi_lock = threading.Lock()
_ncbi_next = 0.0


def _ncbi_pace() -> None:
    """Space requests from every thread in this process so they stay under NCBI's limit together."""
    global _ncbi_next
    gap = 1 / 9 if os.environ.get("NCBI_API_KEY") else 1 / 3
    with _ncbi_lock:
        now = time.monotonic()
        _ncbi_next = max(_ncbi_next, now) + gap
        wait = _ncbi_next - gap - now
    if wait > 0:
        time.sleep(wait)


def ncbi_get(url: str, params: dict) -> httpx.Response:
    """NCBI allows 3 requests a second, or 10 with NCBI_API_KEY; back off and retry when throttled."""
    if key := os.environ.get("NCBI_API_KEY"):
        params = {**params, "api_key": key}
    for attempt in range(4):
        _ncbi_pace()
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



REPOSITORY_NAMES = {"MetabolomicsWorkbench": "Metabolomics Workbench", "ExpressionAtlas": "Expression Atlas", "PanoramaPublic": "Panorama Public"}


def download_plan(accession: str, source: str, url: str) -> str:
    """Shell commands that fetch a dataset's files. Shown for review; nothing runs them."""
    a = accession
    lines = [f"mkdir -p ~/omics-data/{a} && cd ~/omics-data/{a}"]
    if source in ("EGA", "dbGaP"):
        lines += ["# controlled access: apply to the data access committee on the study page, then use the repository's download client", f"open {url}"]
    elif source == "GEO":
        prefix = "GSE" if int(a[3:]) < 1000 else a[:-3]
        lines += [
            "# processed files from GEO",
            f'wget -r -np -nH --cut-dirs=3 -R "index.html*" https://ftp.ncbi.nlm.nih.gov/geo/series/{prefix}nnn/{a}/suppl/',
            "# raw reads from SRA (needs NCBI EDirect and sra-tools)",
            f"esearch -db sra -query {a} | efetch -format runinfo | cut -d, -f1 | grep -E '^[SED]RR' | xargs -n1 prefetch",
            "ls */*.sra | xargs -n1 fasterq-dump --split-files",
        ]
    elif source == "PRIDE":
        lines += ["# raw files", "uv tool install pridepy", f"pridepy download-all-public-raw-files -a {a} -o ."]
    elif source == "CELLxGENE":
        lines += [
            "# source .h5ad (needs pip install cellxgene-census)",
            f"python -c \"import cellxgene_census as c; c.download_source_h5ad('{a}', to_path='{a}.h5ad')\"",
        ]
    elif source == "ArrayExpress":
        cut = a.rfind("-") + 1
        lines += [
            "# all study files from BioStudies",
            f'wget -r -np -nH --cut-dirs=6 -R "index.html*" https://ftp.ebi.ac.uk/biostudies/fire/{a[:cut]}/{a[cut:][-3:].zfill(3)}/{a}/Files/',
        ]
    elif source == "ENA":
        lines += [
            "# raw reads from ENA",
            f'curl -s "https://www.ebi.ac.uk/ena/portal/api/filereport?accession={a}&result=read_run&fields=fastq_ftp&format=tsv" | tail -n +2 | cut -f2 | tr \';\' \'\\n\' | xargs -n1 -I{{}} wget ftp://{{}}',
        ]
    else:
        lines += [f"# files are listed on the {REPOSITORY_NAMES.get(source, source)} study page", f"open {url}"]
    return "\n".join(lines)


def paper_methods(paper: str) -> dict:
    """The methods section of a paper ('pmid:…' or 'doi:…') from its Europe PMC open-access full text, one entry per paragraph."""
    query = f"EXT_ID:{paper[5:]} AND SRC:MED" if paper.startswith("pmid:") else f'DOI:"{paper[4:]}"'
    found = httpx.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "resultType": "core"},
        timeout=30,
    ).json()["resultList"]["result"]
    if not found:
        return {"paper": paper, "available": False, "reason": "not found in Europe PMC"}
    record = found[0]
    head = {"paper": paper, "title": record.get("title", ""), "pmcid": record.get("pmcid")}
    if not record.get("pmcid") or record.get("isOpenAccess") != "Y":
        return head | {"available": False, "reason": "no open-access full text"}
    xml = httpx.get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{record['pmcid']}/fullTextXML", timeout=60)
    try:
        root = ElementTree.fromstring(xml.raise_for_status().content)
    except (httpx.HTTPStatusError, ElementTree.ParseError):
        return head | {"available": False, "reason": f"Europe PMC did not send the full text (HTTP {xml.status_code})"}
    sections = [
        s for s in root.iter("sec")
        if "method" in (s.get("sec-type") or "") or re.search(r"method|materials|experimental procedures", s.findtext("title") or "", re.I)
    ]
    outer = [s for s in sections if not any(s is not o and s in o.iter("sec") for o in sections)]
    paragraphs = []
    for section in outer:
        for sub in section.iter("sec"):
            heading = " ".join((sub.findtext("title") or "").split())
            paragraphs += [{"section": heading, "text": " ".join("".join(p.itertext()).split())} for p in sub.findall("p")]
    return head | {"available": bool(paragraphs), "paragraphs": paragraphs} | ({} if paragraphs else {"reason": "full text has no methods section"})


PRIDE_FILES = "https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{}/files"
PRIDE_FILES_CACHE = Path.home() / ".cache" / "omics-agent" / "pride-files"
# What a researcher can use without reprocessing, in the order it is shown.
FILE_KINDS = (
    ("protein table", re.compile(r"proteingroups|protein_groups|pg_matrix|proteins?[._-]|protein[ _-]?quant", re.I)),
    ("sample design", re.compile(r"\.sdrf|experimental.?design", re.I)),
    ("search output", re.compile(r"report|evidence|peptides?|psm|precursor|\.mztab|\.mzid|\.msf|\.xlsx?$|\.tsv$|\.csv$", re.I)),
)
SKIPPED_FILES = re.compile(r"parameters|mqpar|\.fasta|library|\.kit$|\.xml$|summary\.txt|msms", re.I)


def pride_files(accession: str) -> dict:
    """The author-processed files of a PRIDE project (protein tables, search output, sample design) and a summary of
    its raw files, so a researcher can see whether reprocessing is needed. Cached on disk."""
    path = PRIDE_FILES_CACHE / f"{accession}.json"
    if not path.exists():
        files, page = [], 0
        while batch := httpx.get(PRIDE_FILES.format(accession), params={"pageSize": 1000, "page": page}, timeout=60).raise_for_status().json():
            files += batch
            if len(batch) < 1000:
                break
            page += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(files))
    files = json.loads(path.read_text())
    raw = [f for f in files if f["fileCategory"]["value"] == "RAW"]
    processed = []
    for f in files:
        name, category = f["fileName"], f["fileCategory"]["value"]
        if category == "RAW" or SKIPPED_FILES.search(name):
            continue
        kind = "sample design" if category == "EXPERIMENTAL DESIGN" else next((k for k, pattern in FILE_KINDS if pattern.search(name)), None)
        ftp = next((loc["value"] for loc in f.get("publicFileLocations", []) if loc["value"].startswith("ftp://")), None)
        if kind and ftp:
            processed.append({"name": name, "kind": kind, "bytes": f["fileSizeBytes"], "url": ftp.replace("ftp://", "https://", 1)})
    order = [k for k, _ in FILE_KINDS]
    processed.sort(key=lambda p: (order.index(p["kind"]), -p["bytes"]))
    return {"processed": processed[:6], "more": max(0, len(processed) - 6), "raw": {"files": len(raw), "bytes": sum(f["fileSizeBytes"] for f in raw)}}
