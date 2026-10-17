"""Turn a pasted identifier into the locus page it names: a dataset, a sample or run, or a paper."""

import re
import sqlite3
from urllib.parse import quote

import httpx

from . import paper, record, sources, store

ENA_RUNS = "https://www.ebi.ac.uk/ena/portal/api/filereport"
KNOWN = re.compile(r"(?:GS[EM]|GDS|PRJ[NED][AB]|R?PXD|PAD|PAe|E-[A-Z]+-|MTBLS|MSV|ST|EGA[DS]|phs|OEX|[ELR]DS-|[SED]R[RXPS])\d", re.I)
SAMPLE = re.compile(r"GSM\d+|[SED]R[RX]\d+", re.I)
SEQUENCE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,59}")


def _dataset(token: str) -> sqlite3.Row | None:
    db = store.connect()
    db.row_factory = sqlite3.Row
    return db.execute("SELECT accession, source, title FROM datasets WHERE accession IN (?, ?, ?)", (token, token.upper(), token.lower())).fetchone()


def _found(kind: str, path: str, found_in: str, **fields) -> dict:
    return {"kind": kind, "path": path, "found_in": found_in} | fields


def _dataset_page(token: str, found_in: str) -> dict | None:
    if row := _dataset(token):
        return _found("dataset", f"/d/{quote(row['accession'])}", found_in, accession=row["accession"], repository=row["source"], title=row["title"])


def _sample_page(dataset: str, sample: str, found_in: str) -> dict | None:
    if (row := _dataset(dataset)) and row["source"] in record.SAMPLE_ADAPTERS:
        return _found("sample", f"/d/{quote(row['accession'])}/{quote(sample)}", found_in, accession=sample, dataset=row["accession"], repository=row["source"], title=row["title"])


def _geo_sample(gsm: str) -> dict:
    page = sources.ncbi_get(record.GEO, {"acc": gsm, "targ": "self", "form": "text", "view": "brief"}).text
    series = re.findall(r"^!Sample_series_id = (GSE\d+)", page, re.M)
    if not series:
        raise LookupError(f"NCBI GEO has no sample {gsm}.")
    for gse in series:
        if found := _sample_page(gse, gsm, f"NCBI GEO sample record {gsm}, series_id {gse}"):
            return found
    raise LookupError(f"{gsm} belongs to {', '.join(series)}, which locus does not have.")


def _ena(accession: str) -> dict:
    runs = httpx.get(ENA_RUNS, params={"accession": accession, "result": "read_run", "format": "json",
                                       "fields": "run_accession,study_accession,experiment_alias,sample_alias"}, timeout=30).json()
    if not runs:
        raise LookupError(f"ENA has no {accession}.")
    run = runs[0]
    source = f"ENA read run record of {run['run_accession']}, study {run['study_accession']}"
    if gsm := next((a for a in (run["experiment_alias"], run["sample_alias"]) if re.fullmatch(r"GSM\d+", a)), None):
        return _geo_sample(gsm)
    if re.fullmatch(r"[SED]RP\d+", accession, re.I):
        found = _dataset_page(run["study_accession"], source)
    else:
        found = _sample_page(run["study_accession"], run["run_accession"], source) or _dataset_page(run["study_accession"], source)
    if not found:
        raise LookupError(f"{accession} belongs to {run['study_accession']}, which locus does not have.")
    return found


def _paper(pid: str) -> dict:
    if not (core := paper.lookup(pid)):
        raise LookupError(f"Europe PMC has no paper {pid.partition(':')[2]}.")
    return _found("paper", paper.path(core), f"Europe PMC record of {pid.partition(':')[2]}", title=core.get("title", "").rstrip("."), pmid=core.get("pmid"), doi=core.get("doi"))


def resolve(text: str) -> dict | None:
    """Page, kind and source of the record an identifier names; None when the text is not an identifier, so a search can take it.
    LookupError (with a one-line reason) when it is an identifier of something locus does not have."""
    text = text.strip()
    if pid := paper.paper_id(text):
        return _paper(pid)
    if not SEQUENCE_TOKEN.fullmatch(text):
        return None
    if found := _dataset_page(text, "locus index"):
        return found
    if match := re.fullmatch(r"E-GEOD-(\d+)", text, re.I):
        if found := _dataset_page(f"GSE{match[1]}", f"locus index (ArrayExpress E-GEOD-{match[1]} is GEO series GSE{match[1]})"):
            return found
    if not KNOWN.match(text):
        return None
    if text.upper().startswith("GSM"):
        return _geo_sample(text.upper())
    if SAMPLE.fullmatch(text) or re.fullmatch(r"[SED]RP\d+", text, re.I):
        return _ena(text.upper())
    raise LookupError(f"locus has no {text}.")


if __name__ == "__main__":
    for text, kind, path in [
        ("GSE36892", "dataset", "/d/GSE36892"), ("gse36892", "dataset", "/d/GSE36892"), ("PXD012345", "dataset", "/d/PXD012345"), ("E-MTAB-6149", "dataset", "/d/E-MTAB-6149"),
        ("MTBLS1", "dataset", "/d/MTBLS1"), ("MSV000065796", "dataset", "/d/MSV000065796"), ("PRJNA999969", "dataset", "/d/PRJNA999969"),
        ("E-GEOD-36892", "dataset", "/d/GSE36892"), ("GSM2306940", "sample", "/d/GSE86618/GSM2306940"),
        ("33331123", "paper", "/p/33331123"), ("PMID:33331123", "paper", "/p/33331123"), ("PMC7745072", "paper", "/p/33331123"),
        ("https://doi.org/10.15252/msb.20209844", "paper", "/p/33331123"), ("10.1186/s13059-021-02508-7", "paper", "/p/34649616"),
    ]:
        found = resolve(text)
        assert found and (found["kind"], found["path"]) == (kind, path), (text, found)
    for text in ("lung fibrosis in humans", "cancer", "RNA-seq", "covid19", ""):
        assert resolve(text) is None, text
    for text in ("GSE99999999", "PXD99999999", "GSM99999999", "10.1000/not-a-real-doi", "PMC1"):
        try:
            resolve(text)
        except LookupError as error:
            print(text, "->", error)
        else:
            raise AssertionError(f"{text} should not resolve")
    print("ok")
