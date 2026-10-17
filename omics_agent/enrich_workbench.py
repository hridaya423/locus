import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import store

MWTAB = "https://www.metabolomicsworkbench.org/rest/study/study_id/{}/mwtab"
DATA = Path(__file__).resolve().parent.parent / "data"
DETAILS = DATA / "workbench_details"
CHANGED = DATA / "workbench_summaries_changed.txt"
WORKERS = 6
BATCH = 200


def _fetch(client: httpx.Client, accession: str) -> dict | None:
    """PROJECT and STUDY sections of the study's mwtab, cached under data/workbench_details (empty results too). None after repeated errors.
    The sections come first in the JSON, so the stream is cut before SUBJECT and the large factor and data tables are never downloaded."""
    path = DETAILS / f"{accession}.json"
    if path.exists():
        return json.loads(path.read_text())
    for attempt in range(6):
        try:
            with client.stream("GET", MWTAB.format(accession), timeout=120) as response:
                if response.status_code != 200:
                    raise httpx.HTTPError(str(response.status_code))
                text = ""
                for chunk in response.iter_text():
                    text += chunk
                    if '"SUBJECT"' in text:
                        break
            head = text.split('"SUBJECT"')[0].rstrip(", \n")
            try:
                sections = json.loads(head + "}")
            except ValueError:
                sections = {}
            if not sections and text.strip():
                raise httpx.HTTPError("unparsable response")
            details = {k: sections[k] for k in ("PROJECT", "STUDY") if isinstance(sections.get(k), dict)}
            path.write_text(json.dumps(details))
            return details
        except httpx.HTTPError:
            time.sleep(2 ** attempt)
    return None


def _papers(details: dict) -> list[str]:
    """PMIDs and DOIs from the free-text PUBLICATIONS of the project and study; the formats range from 'PMID: 123' and pubmed URLs to full citations."""
    text = " ".join(str(details.get(k, {}).get("PUBLICATIONS", "")) for k in ("PROJECT", "STUDY"))
    pmids = re.findall(r"(?:pmid|pubmed)\D{0,12}?(\d{5,9})\b", text, re.I)
    dois = [d.rstrip(".,;)]>\"'").lower() for d in re.findall(r"\b10\.\d{4,9}/[^\s\"<>]+", text)]
    return list(dict.fromkeys([f"pmid:{p}" for p in pmids] + [f"doi:{d}" for d in dois]))


def _summary(details: dict) -> str:
    """The study summary, else the project summary; '-' and one-word placeholders are not summaries."""
    for section, key in (("STUDY", "STUDY_SUMMARY"), ("PROJECT", "PROJECT_SUMMARY")):
        text = " ".join(str(details.get(section, {}).get(key, "")).split())
        if len(text.split()) >= 5:
            return text
    return ""


def _retry(db: sqlite3.Connection, work) -> None:
    """Run `work` and commit, retrying while another process holds the write lock."""
    for attempt in range(20):
        try:
            work()
            return db.commit()
        except sqlite3.OperationalError:
            db.rollback()
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError("database stayed locked")


def _write(db: sqlite3.Connection, papers: list[tuple[str, str]], summaries: list[tuple[str, str]]) -> list[str]:
    """Fill empty `papers` and replace only the synthetic summaries. Returns the accessions whose summary changed."""
    changed = []

    def work() -> None:
        changed.clear()
        db.executemany("UPDATE datasets SET papers=? WHERE accession=? AND papers='[]'", papers)
        for summary, accession in summaries:
            if db.execute("UPDATE datasets SET summary=? WHERE accession=? AND summary LIKE '% metabolomics study of %'", (summary, accession)).rowcount:
                changed.append(accession)

    _retry(db, work)
    return changed


def enrich(sample: int | None = None) -> None:
    DETAILS.mkdir(parents=True, exist_ok=True)
    db = store.connect()
    rows = db.execute(
        "SELECT accession, papers = '[]', summary LIKE '% metabolomics study of %' FROM datasets WHERE source='MetabolomicsWorkbench' ORDER BY accession"
    ).fetchall()
    todo = rows[:: max(len(rows) // sample, 1)][:sample] if sample else rows
    print(f"{len(rows)} Workbench rows, {len(todo)} to fetch", flush=True)

    papers, summaries, got, failed, new_summary = [], [], 0, 0, 0
    started = time.time()
    with httpx.Client(limits=httpx.Limits(max_connections=WORKERS)) as client, ThreadPoolExecutor(WORKERS) as pool:
        for n, ((accession, no_papers, synthetic), details) in enumerate(zip(todo, pool.map(lambda t: _fetch(client, t[0]), todo)), 1):
            if details is None:
                failed += 1
                continue
            links, summary = _papers(details), _summary(details)
            got += bool(links)
            new_summary += bool(summary)
            if links and no_papers:
                papers.append((json.dumps(links), accession))
            if summary and synthetic:
                summaries.append((summary, accession))
            if len(papers) + len(summaries) >= BATCH and not sample:
                CHANGED.open("a").writelines(f"{a}\n" for a in _write(db, papers, summaries))
                papers, summaries = [], []
            if n % 500 == 0:
                print(f"{n}/{len(todo)} {n / (time.time() - started):.1f}/s", flush=True)
    if (papers or summaries) and not sample:
        CHANGED.open("a").writelines(f"{a}\n" for a in _write(db, papers, summaries))

    elapsed = time.time() - started
    print(f"{got}/{len(todo)} with publications, {new_summary}/{len(todo)} with a real summary, {failed} failed")
    print(f"done: {len(todo)} accessions in {elapsed:.0f}s ({len(todo) / max(elapsed, 1):.1f}/s){' [sample, DB untouched]' if sample else ''}", flush=True)


if __name__ == "__main__":
    enrich(int(sys.argv[2]) if sys.argv[1:2] == ["--sample"] else None)
