"""One paper as a locus page shows it: bibliographic facts, abstract, data availability statement and supplementary files
from Europe PMC, and every locus dataset that cites the paper. Nothing is generated; a fact Europe PMC does not give is
absent or marked as not stated.
"""

import html
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from urllib.parse import quote

import httpx

from . import store

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
ARTICLE = "https://europepmc.org/article/{}/{}"
PMC_FILE = "https://pmc.ncbi.nlm.nih.gov/articles/instance/{}/bin/{}"

ACCESSION = re.compile(r"\b(?:GSE\d+|PRJ[NED][AB]\d+|PXD\d+|E-[A-Z]+-\d+|MTBLS\d+|MSV\d+|[SED]RP\d+|EGA[DS]\d+|phs\d+)\b")
AVAILABILITY_TITLE = re.compile(r"data (and \w+ )?availab|availability of (data|materials)|accession (code|number)", re.I)
DEPOSITED = re.compile(r"deposited|available (in|at|from|through|via|under)|accession", re.I)
DOI = re.compile(r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+?)[.,;)]*", re.I)

NOT_OPEN = "full text not open access"
NOT_STATED = "not stated in the open-access text"


def paper_id(text: str) -> str | None:
    """'pmid:…', 'pmc:PMC…' or 'doi:…' for a PMID, PMCID, DOI or the URL of one; None for anything else."""
    text = text.strip()
    if m := re.fullmatch(r"(?:pmid\s*:?\s*|https?://pubmed\.ncbi\.nlm\.nih\.gov/)?(\d{1,9})/?", text, re.I):
        return f"pmid:{m[1]}"
    if m := re.fullmatch(r"(?:pmcid\s*:?\s*)?(PMC\d+)", text, re.I):
        return f"pmc:{m[1].upper()}"
    if m := DOI.fullmatch(text):
        return f"doi:{m[1].lower()}"
    return None


def _query(pid: str) -> str:
    kind, _, value = pid.partition(":")
    return {"pmid": f"EXT_ID:{value} AND SRC:MED", "pmc": f"PMCID:{value}", "doi": f'DOI:"{value}"'}[kind]


@lru_cache(maxsize=256)
def lookup(pid: str) -> dict | None:
    """Europe PMC's core record for a paper ID from paper_id(); the first match, or None."""
    found = httpx.get(f"{EPMC}/search", params={"query": _query(pid), "format": "json", "resultType": "core"}, timeout=30).json()["resultList"]["result"]
    return found[0] if found else None


def path(core: dict) -> str:
    """The locus page of a paper: its PMID, or its DOI when it has none."""
    return f"/p/{core['pmid']}" if core.get("pmid") else f"/p/{quote(core['doi'], safe='/')}"


@lru_cache(maxsize=64)
def _full_text(pmcid: str) -> str:
    return httpx.get(f"{EPMC}/{pmcid}/fullTextXML", timeout=60).text


def _text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _availability(xml: str) -> dict:
    root = ET.fromstring(xml)
    sections = [s for s in root.iter("sec") if "data-availability" in (s.get("sec-type") or "") or AVAILABILITY_TITLE.search(s.findtext("title") or "")]
    sections += [n for n in root.iter("notes") if "data-availability" in (n.get("notes-type") or "")]
    if sections:
        section = sections[0]
        paragraphs = [_text(p) for p in section.iter("p")]
        return {"status": "stated", "section": " ".join((section.findtext("title") or "Data availability").split()), "text": "\n".join(p for p in paragraphs if p)}
    sentences = [s for p in root.iter("p") for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", _text(p)) if ACCESSION.search(s) and DEPOSITED.search(s)]
    if sentences:
        return {"status": "stated", "section": "Sentences of the full text that name an accession", "text": "\n".join(dict.fromkeys(sentences))}
    return {"status": "not_stated", "note": NOT_STATED}


def _supplementary(xml: str, pmcid: str) -> dict:
    files = []
    for block in re.findall(r"<supplementary-material\b[^>]*[^/]>.*?</supplementary-material>", xml, re.S):
        caption = html.unescape(" ".join(re.sub(r"<[^>]+>", " ", block.split("<media", 1)[0]).split()))
        for media in re.findall(r"<media\b.*?</media>", block, re.S):
            name = re.search(r'xlink:href="([^"]+)"', media)[1]
            size = re.search(r"<\?size (\d+)\?>", media)
            files.append({"name": name, "caption": caption, "bytes": int(size[1]) if size else None, "url": PMC_FILE.format(pmcid[3:], quote(name))})
    return {"zip": f"{EPMC}/{pmcid}/supplementaryFiles", "files": files}


def _abstract(raw: str) -> list[list[str]]:
    """[label, text] pairs; the label is empty when the abstract is not structured."""
    parts = re.split(r"<h4>(.*?)</h4>", raw)
    clean = lambda s: html.unescape(" ".join(re.sub(r"<[^>]+>", " ", s).split()))
    pairs = [["", clean(parts[0])]] + [[clean(parts[i]), clean(parts[i + 1])] for i in range(1, len(parts) - 1, 2)]
    return [p for p in pairs if p[1]]


def datasets(core: dict) -> list[dict]:
    """Locus datasets whose stored paper IDs include this paper's PMID or DOI."""
    keys = [f'"pmid:{core["pmid"]}"'] if core.get("pmid") else []
    keys += [f'"doi:{core["doi"].lower()}"'] if core.get("doi") else []
    if not keys:
        return []
    rows = store.connect().execute(
        "SELECT accession, source, title, modality, samples, url FROM datasets WHERE papers != '[]' AND ("
        + " OR ".join("instr(lower(papers), ?) > 0" for _ in keys) + ") ORDER BY source, accession",
        keys,
    )
    return [{"accession": a, "source": s, "title": t, "modality": m.split(" | ")[0], "samples": n, "url": u, "path": f"/d/{quote(a)}"} for a, s, t, m, n, u in rows]


def paper(identifier: str) -> dict:
    """The paper page for a PMID, PMCID or DOI; LookupError when Europe PMC does not know it."""
    if not (pid := paper_id(identifier)) or not (core := lookup(pid)):
        raise LookupError(f"Europe PMC has no paper {identifier}.")
    pmcid = core.get("pmcid")
    is_open = bool(pmcid) and core.get("isOpenAccess") == "Y"
    xml = _full_text(pmcid) if is_open else ""
    pubmed = ARTICLE.format("MED", core["pmid"]) if core.get("pmid") else None
    return {
        "pmid": core.get("pmid"), "pmcid": pmcid, "doi": core.get("doi"), "path": path(core),
        "title": core.get("title", "").rstrip("."),
        "authors": [a.get("fullName") or a.get("collectiveName") for a in core.get("authorList", {}).get("author", [])],
        "journal": core.get("journalInfo", {}).get("journal", {}).get("title") or "",
        "year": core.get("pubYear") or "",
        "abstract": _abstract(core.get("abstractText") or ""),
        "data_availability": _availability(xml) if is_open else {"status": "no_full_text", "note": NOT_OPEN},
        "supplementary": _supplementary(xml, pmcid) if is_open else None,
        "datasets": datasets(core),
        "sources": {
            "metadata": f"{EPMC}/search?query={quote(_query(pid))}&format=json&resultType=core",
            "full_text": f"{EPMC}/{pmcid}/fullTextXML" if is_open else None,
            "europe_pmc": pubmed or (ARTICLE.format("PMC", pmcid) if pmcid else None),
            "doi": f"https://doi.org/{core['doi']}" if core.get("doi") else None,
        },
    }


if __name__ == "__main__":
    for text, expected in {"33331123": "pmid:33331123", "PMID: 33331123": "pmid:33331123", "PMC7745072": "pmc:PMC7745072",
                           "https://doi.org/10.15252/MSB.20209844": "doi:10.15252/msb.20209844", "doi:10.1038/s41588-026-02716-6.": "doi:10.1038/s41588-026-02716-6",
                           "GSE36892": None, "lung fibrosis": None}.items():
        assert paper_id(text) == expected, (text, paper_id(text))

    first = paper("33331123")
    assert first["title"].startswith("Integrative characterization of the near-minimal bacterium")
    assert first["authors"][0] == "Matteau D" and first["journal"] == "Molecular systems biology" and first["year"] == "2020"
    assert first["data_availability"]["status"] == "stated" and "GSE152985" in first["data_availability"]["text"]
    assert {d["source"] for d in first["datasets"]} >= {"GEO", "PRIDE"}, first["datasets"]
    assert any(f["name"].endswith(".xlsx") and f["bytes"] for f in first["supplementary"]["files"])
    assert first["sources"]["doi"] == "https://doi.org/10.15252/msb.20209844"

    second = paper("doi:10.1186/s13059-021-02508-7")
    assert second["pmid"] == "34649616" and second["path"] == "/p/34649616"
    assert len(second["datasets"]) >= 2 and second["data_availability"]["status"] in ("stated", "not_stated")

    closed = paper("15155910")
    assert closed["data_availability"] == {"status": "no_full_text", "note": NOT_OPEN} and closed["supplementary"] is None
    assert {d["source"] for d in closed["datasets"]} >= {"GEO", "ENA"}
    print(first["data_availability"]["text"][:120].replace("\n", " "), len(first["supplementary"]["files"]), "files,", len(second["datasets"]), "datasets, ok")
