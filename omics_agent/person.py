"""One contributor as a locus page shows them: their papers in Europe PMC, newest first, the journals they publish in,
which papers have supplementary files, and the locus datasets those papers deposited or cite. The author search is by
surname and initials, so a common name mixes people; the count says how many papers matched."""

import re
import unicodedata
from functools import lru_cache

import httpx

from . import store
from .paper import EPMC

PAGE = 100
TITLES = re.compile(r"^(dr|prof|professor|mr|mrs|ms|sir)\.?$", re.I)
PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "da", "di", "du", "le", "la", "dos", "das", "ter", "ten"}


def author_query(name: str) -> str | None:
    """Europe PMC's form of a name, surname then initials: 'Carson C Thoreen' and 'Thoreen, Carson C.' give 'Thoreen CC'."""
    if "," in name:
        surname, _, given = name.partition(",")
        words, last = given.split(), surname.split()
    else:
        parts = [p for p in name.replace(".", ". ").split() if not TITLES.match(p)]
        if len(parts) < 2:
            return None
        cut = len(parts) - 1
        while cut > 1 and parts[cut - 1].lower() in PARTICLES:
            cut -= 1
        words, last = parts[:cut], parts[cut:]
    initials = "".join(w[0] for part in words for w in part.replace(".", " ").replace("-", " ").split() if w[0].isalpha())
    return f"{' '.join(last)} {initials.upper()}".strip() if last and initials else None


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _datasets(papers: list[dict]) -> dict[str, list[dict]]:
    """Locus datasets whose stored paper IDs include each paper's PMID or DOI, in one pass over the index."""
    keys = {f'"pmid:{p["pmid"]}"': p["key"] for p in papers if p.get("pmid")} | {f'"doi:{p["doi"].lower()}"': p["key"] for p in papers if p.get("doi")}
    if not keys:
        return {}
    where = " OR ".join("instr(lower(papers), ?) > 0" for _ in keys)
    found: dict[str, list[dict]] = {}
    for accession, source, title, modality, papers_json in store.connect().execute(
        f"SELECT accession, source, title, modality, papers FROM datasets WHERE papers != '[]' AND ({where}) ORDER BY source, accession", list(keys)
    ):
        for key, paper in keys.items():
            if key in papers_json.lower() and accession not in {d["accession"] for d in found.get(paper, [])}:
                found.setdefault(paper, []).append({"accession": accession, "source": source, "title": title, "modality": modality.split(" | ")[0]})
    return found


@lru_cache(maxsize=64)
def person(name: str) -> dict:
    query = author_query(name)
    if not query:
        return {"name": name, "available": False, "reason": "the name has no surname and given name to search by"}
    body = httpx.get(f"{EPMC}/search", params={"query": f'AUTH:"{query}"', "format": "json", "resultType": "lite", "pageSize": PAGE, "sort": "P_PDATE_D desc"},
                     timeout=30).raise_for_status().json()
    papers = []
    for r in body["resultList"]["result"]:
        preprint = r.get("source") == "PPR" or "preprint" in (r.get("pubType") or "")
        papers.append({
            "key": r["id"], "pmid": r.get("pmid"), "doi": r.get("doi"), "title": (r.get("title") or "").rstrip("."), "year": r.get("pubYear"),
            "journal": r.get("journalTitle") or (r.get("bookOrReportDetails") or {}).get("publisher") or "", "preprint": preprint,
            "authors": r.get("authorString", ""), "cited_by": r.get("citedByCount", 0), "open_access": r.get("isOpenAccess") == "Y",
            "supplementary": r.get("hasSuppl") == "Y", "accessions_in_text": r.get("hasTMAccessionNumbers") == "Y",
            "last_author": _plain(r.get("authorString", "")).rstrip(".").split(", ")[-1] == _plain(query),
        })
    linked = _datasets(papers)
    for p in papers:
        p["datasets"] = linked.get(p["key"], [])
    journals: dict[str, int] = {}
    for p in papers:
        if p["journal"] and not p["preprint"]:
            journals[p["journal"]] = journals.get(p["journal"], 0) + 1
    return {
        "name": name, "query": query, "available": True, "matched": body["hitCount"], "shown": len(papers),
        "search": f"https://europepmc.org/search?query=AUTH%3A%22{query.replace(' ', '%20')}%22",
        "journals": dict(sorted(journals.items(), key=lambda kv: -kv[1])),
        "counts": {"preprints": sum(p["preprint"] for p in papers), "supplementary": sum(p["supplementary"] for p in papers),
                   "open_access": sum(p["open_access"] for p in papers), "last_author": sum(p["last_author"] for p in papers),
                   "with_datasets": sum(bool(p["datasets"]) for p in papers), "datasets": len({d["accession"] for p in papers for d in p["datasets"]})},
        "papers": papers,
    }


if __name__ == "__main__":
    for raw, want in [("Carson C Thoreen", "Thoreen CC"), ("Dr Juliane S. Walz", "Walz JS"), ("Thoreen, Carson C.", "Thoreen CC"),
                      ("Ludwig van der Berg", "van der Berg L"), ("Jean-Pierre Dupont", "Dupont JP"), ("Madonna", None)]:
        assert author_query(raw) == want, (raw, author_query(raw), want)
    p = person("Carson C Thoreen")
    assert p["matched"] >= 30 and any(d["accession"] == "GSE132703" for x in p["papers"] for d in x["datasets"]), p["counts"]
    print("person self-check passed:", p["query"], p["matched"], "papers;", p["counts"], list(p["journals"].items())[:4])
