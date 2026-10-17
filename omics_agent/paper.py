"""One paper as a locus page shows it: bibliographic facts, abstract, data availability statement and supplementary files
from Europe PMC, and every locus dataset that cites the paper. Nothing is generated; a fact Europe PMC does not give is
absent or marked as not stated.
"""

import html
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
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
NOT_SENT = "Europe PMC did not send the full text"
REUSED = re.compile(r"downloaded|obtained from|retrieved|previously (published|reported|generated)|external|re-?analy[sz]|published (data|dataset)|public(ly)? (data|dataset)", re.I)
DEPOSITED_SENTENCE = re.compile(r"deposited|submitted|uploaded|generated in this study|available (in|at|from|under|through|via)|accession (code|number)|can be (found|accessed)", re.I)
PEER_REVIEW = re.compile(r"peer.?review|review process|reviewer|rebuttal|decision letter", re.I)
ZIP_LIMIT = 200 << 20
DATASET_PAGE = 100


def paper_id(text: str) -> str | None:
    """'pmid:…', 'pmc:PMC…' or 'doi:…' for a PMID, PMCID, DOI or the URL of one; None for anything else."""
    text = text.strip()
    if m := re.fullmatch(r"(?:pmid\s*:?\s*(\d{1,9})|(?:https?://pubmed\.ncbi\.nlm\.nih\.gov/)?(\d{6,9}))/?", text, re.I):
        return f"pmid:{m[1] or m[2]}"
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
    response = httpx.get(f"{EPMC}/{pmcid}/fullTextXML", timeout=60)
    response.raise_for_status()
    return response.text


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
        return {"status": "stated", "section": "Sentences naming an accession", "text": "\n".join(dict.fromkeys(sentences))}
    return {"status": "not_stated", "note": NOT_STATED}


@lru_cache(maxsize=32)
def _zip_sizes(pmcid: str) -> dict[str, int]:
    """File sizes read from the directory of Europe PMC's zip of supplementary files; the zip is streamed through a temporary
    file and discarded, and skipped above ZIP_LIMIT."""
    try:
        with tempfile.SpooledTemporaryFile(max_size=16 << 20) as spool, httpx.stream("GET", f"{EPMC}/{pmcid}/supplementaryFiles", timeout=120) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                spool.write(chunk)
                if spool.tell() > ZIP_LIMIT:
                    return {}
            return {i.filename.rsplit("/", 1)[-1]: i.file_size for i in zipfile.ZipFile(spool).infolist() if not i.is_dir()}
    except (httpx.HTTPError, zipfile.BadZipFile):
        return {}


def _supplementary(xml: str, pmcid: str) -> dict:
    files = {}
    for block in re.findall(r"<supplementary-material\b[^>]*[^/]>.*?</supplementary-material>", xml, re.S):
        caption = html.unescape(" ".join(re.sub(r"<[^>]+>", " ", block.split("<media", 1)[0]).split()))
        for media in re.findall(r"<media\b.*?</media>", block, re.S):
            name = re.search(r'xlink:href="([^"]+)"', media)[1]
            size = re.search(r"<\?size (\d+)\?>", media)
            if not PEER_REVIEW.search(f"{name} {caption}"):
                files[name] = {"name": name, "caption": caption, "bytes": int(size[1]) if size else None, "url": PMC_FILE.format(pmcid[3:], quote(name))}
    if any(f["bytes"] is None for f in files.values()):
        sizes = _zip_sizes(pmcid)
        for f in files.values():
            f["bytes"] = f["bytes"] or sizes.get(f["name"])
    return {"zip": f"{EPMC}/{pmcid}/supplementaryFiles", "files": list(files.values()), "note": None}


def _abstract(raw: str) -> list[list[str]]:
    """[label, text] pairs; the label is empty when the abstract is not structured."""
    parts = re.split(r"<h4>(.*?)</h4>", raw)
    clean = lambda s: html.unescape(" ".join(re.sub(r"<[^>]+>", " ", s).split()))
    pairs = [["", clean(parts[0])]] + [[clean(parts[i]), clean(parts[i + 1])] for i in range(1, len(parts) - 1, 2)]
    return [p for p in pairs if p[1]]


def statement_accessions(text: str) -> list[dict]:
    """Each accession named in the data availability statement, whether the sentence says the authors deposited it or reused
    it from other studies, and whether locus holds the record."""
    named: dict[str, str] = {}
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.replace("\n", " ")):
        role = "reused" if REUSED.search(sentence) else "deposited" if DEPOSITED_SENTENCE.search(sentence) else "named"
        for accession in dict.fromkeys(ACCESSION.findall(sentence)):
            named.setdefault(accession, role)
    marks = ",".join("?" * len(named))
    held = {a for (a,) in store.connect().execute(f"SELECT accession FROM datasets WHERE accession IN ({marks})", list(named))} if named else set()
    return [{"accession": a, "role": r, "in_locus": a in held} for a, r in named.items()]


def _rows(rows) -> list[dict]:
    return [{"accession": a, "source": s, "title": t, "modality": m.split(" | ")[0], "samples": n, "url": u, "path": f"/d/{quote(a)}"} for a, s, t, m, n, u in rows]


def datasets(core: dict, named: list[dict], offset: int = 0) -> dict:
    """Locus datasets of the paper: those the statement names (first page only), then those whose stored paper IDs include its
    PMID or DOI, DATASET_PAGE at a time from `offset`. `cited_total` counts the second kind."""
    keys = [f'"pmid:{core["pmid"]}"'] if core.get("pmid") else []
    keys += [f'"doi:{core["doi"].lower()}"'] if core.get("doi") else []
    db = store.connect()
    columns = "accession, source, title, modality, samples, url"
    roles = {n["accession"]: n["role"] for n in named}
    held = [n["accession"] for n in named if n["in_locus"]]
    mentioned = _rows(db.execute(f"SELECT {columns} FROM datasets WHERE accession IN ({','.join('?' * len(held))}) ORDER BY source, accession", held)) if held and not offset else []
    where, args = "", []
    if keys:
        where = "papers != '[]' AND (" + " OR ".join("instr(lower(papers), ?) > 0" for _ in keys) + ")" + (f" AND accession NOT IN ({','.join('?' * len(held))})" if held else "")
        args = keys + held
    cited = _rows(db.execute(f"SELECT {columns} FROM datasets WHERE {where} ORDER BY source, accession LIMIT {DATASET_PAGE} OFFSET ?", args + [offset])) if keys else []
    total = db.execute(f"SELECT COUNT(*) FROM datasets WHERE {where}", args).fetchone()[0] if keys else 0
    return {
        "datasets": [d | {"role": roles[d["accession"]] if roles.get(d["accession"]) != "named" else "cited"} for d in mentioned] + [d | {"role": "cited"} for d in cited],
        "cited_total": total,
        "dataset_count": total + len(held),
    }


def paper(identifier: str, offset: int = 0) -> dict:
    """The paper page for a PMID, PMCID or DOI; LookupError when Europe PMC does not know it. A full text that cannot be read
    leaves the availability statement and supplementary files unavailable, and the rest of the page intact."""
    if not (pid := paper_id(identifier)) or not (core := lookup(pid)):
        raise LookupError(f"Europe PMC has no paper {identifier}.")
    pmcid = core.get("pmcid")
    availability, supplementary = {"status": "no_full_text", "note": NOT_OPEN}, {"zip": None, "files": [], "note": NOT_OPEN}
    if pmcid and core.get("isOpenAccess") == "Y":
        try:
            xml = _full_text(pmcid)
            availability, supplementary = _availability(xml), _supplementary(xml, pmcid)
        except (httpx.HTTPError, ET.ParseError):
            availability, supplementary = {"status": "unavailable", "note": NOT_SENT}, {"zip": None, "files": [], "note": NOT_SENT}
    named = statement_accessions(availability["text"]) if availability["status"] == "stated" else []
    pubmed = ARTICLE.format("MED", core["pmid"]) if core.get("pmid") else None
    return {
        "pmid": core.get("pmid"), "pmcid": pmcid, "doi": core.get("doi"), "path": path(core),
        "title": core.get("title", "").rstrip("."),
        "authors": [a.get("fullName") or a.get("collectiveName") for a in core.get("authorList", {}).get("author", [])],
        "journal": core.get("journalInfo", {}).get("journal", {}).get("title") or "",
        "year": core.get("pubYear") or "",
        "abstract": _abstract(core.get("abstractText") or ""),
        "data_availability": availability | {"accessions": named},
        "supplementary": supplementary,
        **datasets(core, named, offset),
        "sources": {
            "metadata": f"{EPMC}/search?query={quote(_query(pid))}&format=json&resultType=core",
            "full_text": f"{EPMC}/{pmcid}/fullTextXML" if availability["status"] in ("stated", "not_stated") else None,
            "europe_pmc": pubmed or (ARTICLE.format("PMC", pmcid) if pmcid else None),
            "doi": f"https://doi.org/{core['doi']}" if core.get("doi") else None,
        },
    }


if __name__ == "__main__":
    for text, expected in {"33331123": "pmid:33331123", "PMID: 33331123": "pmid:33331123", "PMID:1": "pmid:1", "2020": None, "10": None, "PMC7745072": "pmc:PMC7745072",
                           "https://doi.org/10.15252/MSB.20209844": "doi:10.15252/msb.20209844", "doi:10.1038/s41588-026-02716-6.": "doi:10.1038/s41588-026-02716-6",
                           "GSE36892": None, "lung fibrosis": None}.items():
        assert paper_id(text) == expected, (text, paper_id(text))

    first = paper("33331123")
    assert first["title"].startswith("Integrative characterization of the near-minimal bacterium")
    assert first["authors"][0] == "Matteau D" and first["journal"] == "Molecular systems biology" and first["year"] == "2020"
    assert first["data_availability"]["status"] == "stated" and "GSE152985" in first["data_availability"]["text"]
    assert {a["accession"]: a["in_locus"] for a in first["data_availability"]["accessions"]} == {"GSE152985": True, "PXD019922": True}
    assert {d["source"] for d in first["datasets"]} >= {"GEO", "PRIDE"}, first["datasets"]
    assert any(f["name"].endswith(".xlsx") and f["bytes"] for f in first["supplementary"]["files"])
    assert first["sources"]["doi"] == "https://doi.org/10.15252/msb.20209844"

    second = paper("doi:10.1186/s13059-021-02508-7")
    assert second["pmid"] == "34649616" and second["path"] == "/p/34649616"
    assert len(second["datasets"]) >= 2 and second["data_availability"]["status"] in ("stated", "not_stated")

    closed = paper("15155910")
    assert closed["data_availability"]["status"] == "no_full_text" and closed["supplementary"]["files"] == []
    assert {d["source"] for d in closed["datasets"]} >= {"GEO", "ENA"}

    deposit = paper("35680905")
    roles = {a["accession"]: a["role"] for a in deposit["data_availability"]["accessions"]}
    assert roles["GSE184894"] == roles["MSV000089303"] == "deposited" and roles["GSE169049"] == roles["GSE94086"] == "reused", roles
    assert {d["accession"]: d["role"] for d in deposit["datasets"]} == {"GSE184894": "deposited", "GSE169049": "reused", "GSE94086": "reused"}
    assert not {a["accession"]: a["in_locus"] for a in deposit["data_availability"]["accessions"]}["MSV000089303"]

    sizes = paper("36439880")["supplementary"]["files"]
    assert sizes and all(f["bytes"] for f in sizes) and not any(PEER_REVIEW.search(f["name"] + f["caption"]) for f in sizes), sizes

    big = paper("22955616")
    assert big["data_availability"]["status"] in ("stated", "not_stated", "unavailable") and big["cited_total"] > 1000
    assert len(big["datasets"]) <= DATASET_PAGE and paper("22955616", DATASET_PAGE)["datasets"][0] != big["datasets"][0]
    print(first["data_availability"]["text"][:120].replace("\n", " "), len(first["supplementary"]["files"]), "files,", len(second["datasets"]), "datasets,", big["cited_total"], "cited by 22955616, ok")
