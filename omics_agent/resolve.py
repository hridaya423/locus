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
STUDY = re.compile(r"PRJ[NED][AB]\d+|[SED]RP\d+", re.I)
URL = re.compile(r"(?:https?://|www\.)\S+|(?:[\w-]+\.)+(?:org|gov|uk|com|net|edu)/\S+", re.I)
IN_URL = re.compile(r"GS[EM]\d+|PRJ[NED][AB]\d+|R?PXD\d+|E-[A-Z]+-\d+|MTBLS\d+|MSV\d+|[SED]R[RXPS]\d+|PMC\d+|EGA[DS]\d+|ST\d{6}|phs\d+", re.I)


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
    """A run or experiment opens its sample page; a study opens its dataset, the GEO series when the study came from one."""
    study = bool(STUDY.fullmatch(accession))
    runs = httpx.get(ENA_RUNS, params={"accession": accession, "result": "read_run", "format": "json", "limit": 1 if study else 0,
                                       "fields": "run_accession,study_accession,experiment_alias,sample_alias"}, timeout=30).json()
    if not runs:
        raise LookupError(f"ENA has no {accession}.")
    run = min(runs, key=lambda r: r["run_accession"])
    source = f"ENA read run record of {run['run_accession']}, study {run['study_accession']}"
    if gsm := next((a for a in (run["experiment_alias"], run["sample_alias"]) if re.fullmatch(r"GSM\d+", a)), None):
        found = _geo_sample(gsm)
        return _dataset_page(found["dataset"], found["found_in"]) if study else found
    if study:
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


def _identifier_in(text: str) -> str:
    """The identifier a pasted link stands for, or the text without stray punctuation and with an accession's prefix joined to its number."""
    if URL.fullmatch(text):
        if m := re.search(r"doi\.org/(10\.\d{4,9}/[^\s?#]+)", text, re.I):
            return m[1]
        if m := re.search(r"(?:pubmed\.ncbi\.nlm\.nih\.gov|/MED|/pubmed)/(\d+)", text, re.I):
            return f"PMID:{m[1]}"
        if m := IN_URL.search(text) or re.search(r"10\.\d{4,9}/[^\s?#]+", text):
            return m[0]
        raise LookupError("locus finds no identifier in this link.")
    text = text.strip("\"'“”()[]<> ").rstrip(".,;:")
    return re.sub(r"^([A-Za-z]{2,6}(?:-[A-Za-z]{2,5})?-?)\s+(\d+)$", lambda m: m[1] + m[2] if KNOWN.match(m[1] + m[2]) else m[0], text)


def resolve(text: str) -> dict | None:
    """Page, kind and source of the record an identifier names; None when the text is not an identifier, so a search can take it.
    LookupError (with a one-line reason) when it is an identifier of something locus does not have."""
    text = _identifier_in(text.strip())
    if pid := paper.paper_id(text):
        return _paper(pid)
    if not SEQUENCE_TOKEN.fullmatch(text):
        return None
    if STUDY.fullmatch(text):
        try:
            return _ena(text.upper())
        except httpx.HTTPError:
            pass
    if found := _dataset_page(text, "locus index"):
        return found
    if match := re.fullmatch(r"E-GEOD-(\d+)", text, re.I):
        if found := _dataset_page(f"GSE{match[1]}", f"locus index (ArrayExpress E-GEOD-{match[1]} is GEO series GSE{match[1]})"):
            return found
    if not KNOWN.match(text):
        return None
    if text.upper().startswith("GSM"):
        return _geo_sample(text.upper())
    if SAMPLE.fullmatch(text) or STUDY.fullmatch(text):
        return _ena(text.upper())
    raise LookupError(f"locus has no {text}.")


if __name__ == "__main__":
    for text, kind, path in [
        ("GSE36892", "dataset", "/d/GSE36892"), ("gse36892", "dataset", "/d/GSE36892"), ("PXD012345", "dataset", "/d/PXD012345"), ("E-MTAB-6149", "dataset", "/d/E-MTAB-6149"),
        ("MTBLS1", "dataset", "/d/MTBLS1"), ("MSV000065796", "dataset", "/d/MSV000065796"), ("PRJNA999969", "dataset", "/d/PRJNA999969"),
        ("E-GEOD-36892", "dataset", "/d/GSE36892"), ("GSM2306940", "sample", "/d/GSE86618/GSM2306940"),
        ("GSE36892.", "dataset", "/d/GSE36892"), ("GSE 36892", "dataset", "/d/GSE36892"), ("GSE36892,", "dataset", "/d/GSE36892"),
        ("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE36892", "dataset", "/d/GSE36892"),
        ("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM2306940", "sample", "/d/GSE86618/GSM2306940"),
        ("https://www.ebi.ac.uk/biostudies/arrayexpress/studies/E-MTAB-6149", "dataset", "/d/E-MTAB-6149"),
        ("https://www.ebi.ac.uk/pride/archive/projects/PXD012345", "dataset", "/d/PXD012345"),
        ("https://www.ebi.ac.uk/ena/browser/view/PRJNA999969", "dataset", "/d/PRJNA999969"),
        ("https://pmc.ncbi.nlm.nih.gov/articles/PMC7745072/", "paper", "/p/33331123"), ("https://europepmc.org/article/MED/33331123", "paper", "/p/33331123"),
        ("https://europepmc.org/article/PMC/PMC7745072", "paper", "/p/33331123"), ("https://pubmed.ncbi.nlm.nih.gov/33331123/?term=mesoplasma", "paper", "/p/33331123"),
        ("doi.org/10.15252/msb.20209844", "paper", "/p/33331123"),
        ("SRP011987", "dataset", "/d/GSE36892"), ("PRJNA157105", "dataset", "/d/GSE36892"), ("PRJNA270957", "dataset", "/d/PRJNA270957"),
        ("33331123", "paper", "/p/33331123"), ("PMID:33331123", "paper", "/p/33331123"), ("PMC7745072", "paper", "/p/33331123"),
        ("https://doi.org/10.15252/msb.20209844", "paper", "/p/33331123"), ("10.1186/s13059-021-02508-7", "paper", "/p/34649616"),
    ]:
        found = resolve(text)
        assert found and (found["kind"], found["path"]) == (kind, path), (text, found)
    for text in ("lung fibrosis in humans", "cancer", "RNA-seq", "covid19", "", "2020", "10"):
        assert resolve(text) is None, text
    for text in ("GSE99999999", "PXD99999999", "GSM99999999", "10.1000/not-a-real-doi", "PMC1"):
        try:
            resolve(text)
        except LookupError as error:
            print(text, "->", error)
        else:
            raise AssertionError(f"{text} should not resolve")
    print("ok")
