"""The whole record of one dataset, as its repository's own page shows it, in one shape for every repository, so the
locus page can replace the repository page. Values come from each repository's API or files, never from a model.

Each adapter names every source field it reads and every field it leaves out on purpose; any other field in a real
record lands in `unmapped`, and the self-check fails on it, so a field the repository page shows is never silently lost.
"""

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from . import samples, sources, store

CACHE = Path.home() / ".cache" / "omics-agent" / "records"
MAX_RUNS = 5000
GEO = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
GEO_FTP = "https://ftp.ncbi.nlm.nih.gov/geo/series/{}/{}/{}/"
PRIDE = "https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{}"
ENA_XML = "https://www.ebi.ac.uk/ena/browser/api/xml/{}"
ENA_RUNS = "https://www.ebi.ac.uk/ena/portal/api/filereport"
ENA_FIELDS = ("run_accession,sample_accession,scientific_name,sample_title,experiment_title,instrument_model,library_strategy,library_source,"
              "library_layout,read_count,base_count,fastq_ftp,fastq_bytes,submitted_ftp,submitted_bytes")
BIOSTUDIES = "https://www.ebi.ac.uk/biostudies/api/v1/studies/{}"
BIOSTUDIES_FILES = "https://www.ebi.ac.uk/biostudies/files/{}/{}"


@dataclass
class Record:
    accession: str
    source: str
    url: str
    title: str
    texts: list[tuple[str, str]] = field(default_factory=list)
    facts: list[tuple[str, list[str]]] = field(default_factory=list)
    people: list[dict] = field(default_factory=list)
    papers: list = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    samples: dict | None = None
    files: list[dict] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)

    def fact(self, label: str, *values) -> None:
        stated = list(dict.fromkeys(str(v).strip() for v in values if v not in (None, "") and str(v).strip()))
        if stated and label not in (f[0] for f in self.facts):
            self.facts.append((label, stated))

    def file(self, name: str, url: str, group: str, size: int | None, processed: bool, kind: str = "") -> None:
        self.files.append({"name": name, "url": url, "group": group, "bytes": size, "processed": processed, "kind": kind})


def _cached(name: str, url: str, params: dict | None = None, ncbi: bool = False) -> str:
    path = CACHE / name
    if not path.exists():
        response = sources.ncbi_get(url, params or {}) if ncbi else httpx.get(url, params=params, timeout=90, follow_redirects=True).raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text)
    return path.read_text()


def _https(location: str) -> str:
    return re.sub(r"^(ftp://)?", "https://", location, count=1) if not location.startswith("https://") else location


UNITS = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def _listing(url: str, name: str) -> list[tuple[str, int | None]]:
    """File names and approximate sizes from an NCBI FTP directory page; empty when the directory does not exist."""
    try:
        page = _cached(name, url)
    except httpx.HTTPStatusError:
        return []
    found = re.findall(r'<a href="([^"/?][^"]*)">[^<]*</a>\s+\S+ \S+\s+([\d.]+)([KMGT]?)', page)
    return [(n, round(float(v) * UNITS[u])) for n, v, u in found]


def _geo_text(lines: list[str]) -> str:
    """GEO splits long text over repeated lines; an empty line is a paragraph break."""
    return "\n\n".join(p for p in "\n".join(lines).split("\n\n") if p.strip()).strip()


def _person(name: str) -> str:
    return " ".join(part for part in name.split(",") if part)


# Series fields the page shows, and fields left out because another field already carries them.
GEO_SHOWN = {"title", "summary", "overall_design", "type", "status", "submission_date", "last_update_date", "pubmed_id",
             "contributor", "contact_name", "contact_email", "contact_institute", "contact_department", "contact_laboratory",
             "contact_address", "contact_city", "contact_state", "contact_zip/postal_code", "contact_country", "contact_phone",
             "contact_fax", "contact_web_link", "supplementary_file", "platform_id", "relation", "web_link", "citation", "sample_id"}
GEO_SKIPPED = {"geo_accession", "platform_organism", "platform_taxid", "sample_organism", "sample_taxid"}


def _geo(accession: str, row: dict) -> Record:
    samples.geo_files(accession)
    series: dict[str, list[str]] = {}
    for line in (samples.CACHE / f"{accession}.series.txt").read_text().splitlines():
        key, _, value = line.partition(" = ")
        if key.startswith("!Series_"):
            series.setdefault(key[8:], []).append(value)
    one = lambda k: (series.get(k) or [""])[0]
    rec = Record(accession, "GEO", row["url"], one("title") or row["title"])
    rec.unmapped = sorted(set(series) - GEO_SHOWN - GEO_SKIPPED)
    rec.texts += [(label, text) for label, key in (("Summary", "summary"), ("Overall design", "overall_design")) if (text := _geo_text(series.get(key, [])))]
    rec.fact("Status", one("status"))
    rec.fact("Experiment type", *series.get("type", []))
    rec.fact("Organism", *series.get("sample_organism", []), *series.get("platform_organism", []))
    platforms = []
    for gpl in series.get("platform_id", []):
        brief = _cached(f"{gpl}.txt", GEO, {"acc": gpl, "targ": "self", "form": "text", "view": "brief"}, ncbi=True)
        title = re.search(r"^!Platform_title = (.*)$", brief, re.M)
        platforms.append(f"{gpl} {title.group(1)}" if title else gpl)
    rec.fact("Platforms", *platforms)
    rec.fact("Samples", len(series.get("sample_id", [])))
    rec.fact("Submitted", one("submission_date"))
    rec.fact("Last updated", one("last_update_date"))
    rec.fact("Citation", *series.get("citation", []))

    rec.people += [{"role": "Contributor", "name": _person(c)} for c in series.get("contributor", [])]
    if contact := one("contact_name"):
        place = ", ".join(one(k) for k in ("contact_department", "contact_laboratory", "contact_institute", "contact_address",
                                           "contact_city", "contact_state", "contact_zip/postal_code", "contact_country") if one(k))
        rec.people.append({"role": "Contact", "name": _person(contact), "affiliation": place, "email": one("contact_email").lower(),
                           "phone": one("contact_phone"), "web": one("contact_web_link")})
    rec.papers = [f"pmid:{p}" for p in series.get("pubmed_id", [])]

    bioproject = ""
    for relation in series.get("relation", []):
        label, _, target = relation.partition(": ")
        url = target if target.startswith("http") else f"{GEO}?acc={target}"
        rec.links.append((label, url))
        bioproject = bioproject or (re.search(r"PRJ[A-Z]{2}\d+", target) or [""])[0]
    rec.links += [("Web link", w) for w in series.get("web_link", [])]
    if bioproject and any(r.startswith("SRA") for r in series.get("relation", [])):
        rec.links.append(("SRA Run Selector", f"https://www.ncbi.nlm.nih.gov/Traces/study/?acc={bioproject}"))
    rec.links += [("SOFT", f"https://ftp.ncbi.nlm.nih.gov/geo/series/{_stub(accession)}/{accession}/soft/{accession}_family.soft.gz"),
                  ("MINiML", f"https://ftp.ncbi.nlm.nih.gov/geo/series/{_stub(accession)}/{accession}/miniml/{accession}_family.xml.tgz")]

    sizes = dict(_listing(GEO_FTP.format(_stub(accession), accession, "suppl"), f"{accession}.suppl.html"))
    for f in series.get("supplementary_file", []):
        if f != "NONE":
            name = f.rsplit("/", 1)[-1]
            rec.file(name, _https(f), "Supplementary files", sizes.get(name), True)
    for name, size in _listing(GEO_FTP.format(_stub(accession), accession, "matrix"), f"{accession}.matrix.html"):
        rec.file(name, GEO_FTP.format(_stub(accession), accession, "matrix") + name, "Series matrix", size, True, "series matrix")
    if bioproject:
        _ena_runs(rec, bioproject, files_only=True)

    records = samples.geo_records(accession)
    names = list(dict.fromkeys(k for r in records for k in r["fields"] if k != "title pattern"))
    platform = len({r["platform"] for r in records}) > 1
    rec.samples = {
        "columns": ["Accession", "Title", *(["Platform"] if platform else []), *names],
        "rows": [[r["gsm"], r["title"], *([r["platform"]] if platform else []), *(r["fields"].get(n, "") for n in names)] for r in records],
        "link": f"{GEO}?acc={{}}",
        "pages": True,
    }
    return rec


def _stub(accession: str) -> str:
    return f"{accession[:-3]}nnn" if len(accession) > 6 else f"{accession[:3]}nnn"


def _runs(accession: str) -> list[dict]:
    """ENA's read runs for a study, experiment or sample, with their files; GEO raw reads live in SRA, which ENA mirrors."""
    text = _cached(f"{accession}.runs.json", ENA_RUNS, {"accession": accession, "result": "read_run", "fields": ENA_FIELDS, "format": "json", "limit": MAX_RUNS})
    return json.loads(text) if text.strip() else []


def _run_files(rec: Record, run: dict) -> None:
    for prefix, group in (("fastq", "Raw reads (FASTQ)"), ("submitted", "Submitted files")):
        urls, sizes = run.get(f"{prefix}_ftp", "").split(";"), run.get(f"{prefix}_bytes", "").split(";")
        for url, size in zip(urls, sizes):
            if url:
                rec.file(url.rsplit("/", 1)[-1], _https(url), group, int(size) if size.isdigit() else None, False, run["run_accession"])
        if run.get(f"{prefix}_ftp"):
            return


def _ena_runs(rec: Record, project: str, files_only: bool = False) -> None:
    """Every run of a study with its read files and sizes."""
    runs = _runs(project)
    for run in runs:
        _run_files(rec, run)
    if runs:
        rec.fact("Organism", *sorted({r["scientific_name"] for r in runs if r.get("scientific_name")}))
        total = sum(int(r["base_count"]) for r in runs if r.get("base_count", "").isdigit())
        rec.fact("Sequencing runs", f"{len(runs):,}" + (f"+ (first {MAX_RUNS:,} shown)" if len(runs) == MAX_RUNS else ""))
        rec.fact("Bases sequenced", f"{total / 1e9:,.1f} Gb" if total else "")
    if files_only or not runs:
        return
    columns = [("Run", "run_accession"), ("Sample", "sample_accession"), ("Sample title", "sample_title"), ("Experiment", "experiment_title"),
               ("Instrument", "instrument_model"), ("Strategy", "library_strategy"), ("Source", "library_source"),
               ("Layout", "library_layout"), ("Reads", "read_count"), ("Bases", "base_count")]
    used = [(label, key) for label, key in columns if any(r.get(key) for r in runs)]
    rec.samples = {"columns": [label for label, _ in used], "rows": [[r.get(key, "") for _, key in used] for r in runs],
                   "link": "https://www.ebi.ac.uk/ena/browser/view/{}", "pages": True}


def _names(values: list) -> list[str]:
    return [v["name"] for v in values or [] if isinstance(v, dict) and v.get("name")]


def _pi(p: dict) -> str:
    return " ".join(x for x in (p.get("title"), p.get("firstName"), p.get("lastName")) if x)


PRIDE_SHOWN = {"accession", "title", "projectDescription", "sampleProcessingProtocol", "dataProcessingProtocol", "projectTags",
               "keywords", "doi", "submissionType", "license", "submissionDate", "publicationDate", "submitters", "labPIs",
               "instruments", "softwares", "experimentTypes", "quantificationMethods", "countries", "sampleAttributes", "organisms",
               "organismParts", "diseases", "references", "identifiedPTMStrings", "totalFileDownloads", "additionalAttributes"}
PRIDE_SKIPPED = {"botCount", "hubCount", "organicCount"}


def _pride(accession: str, row: dict) -> Record:
    p = json.loads(_cached(f"{accession}.pride.json", PRIDE.format(accession)))
    rec = Record(accession, "PRIDE", row["url"], p.get("title") or row["title"])
    rec.unmapped = sorted(set(p) - PRIDE_SHOWN - PRIDE_SKIPPED)
    rec.texts += [(label, p[key].strip()) for label, key in (("Description", "projectDescription"), ("Sample processing protocol", "sampleProcessingProtocol"),
                                                             ("Data processing protocol", "dataProcessingProtocol")) if (p.get(key) or "").strip()]
    rec.fact("Organism", *_names(p.get("organisms")))
    rec.fact("Organism part", *_names(p.get("organismParts")))
    rec.fact("Disease", *_names(p.get("diseases")))
    for attribute in p.get("sampleAttributes") or []:
        rec.fact(attribute["key"]["name"].capitalize(), *_names(attribute.get("value")))
    rec.fact("Experiment type", *_names(p.get("experimentTypes")))
    rec.fact("Instrument", *_names(p.get("instruments")))
    rec.fact("Software", *_names(p.get("softwares")))
    rec.fact("Quantification", *_names(p.get("quantificationMethods")))
    rec.fact("Modifications", *_names(p.get("identifiedPTMStrings")))
    rec.fact("Keywords", *[k.strip() for kw in p.get("keywords") or [] for k in re.split(r"[;,]", kw)])
    rec.fact("Project tags", *(p.get("projectTags") or []))
    for extra in p.get("additionalAttributes") or []:
        if isinstance(extra, dict):
            rec.fact(str(extra.get("name", "Attribute")).capitalize(), extra.get("value"))
    rec.fact("Submission type", (p.get("submissionType") or "").capitalize())
    rec.fact("Country", *(p.get("countries") or []))
    rec.fact("Submitted", p.get("submissionDate"))
    rec.fact("Published", p.get("publicationDate"))
    rec.fact("License", p.get("license"))
    rec.fact("Downloads", f"{int(p['totalFileDownloads']):,}" if str(p.get("totalFileDownloads", "")).isdigit() else "")
    rec.people += [{"role": "Submitter", "name": _pi(s), "affiliation": s.get("affiliation", ""), "email": s.get("email", "")} for s in p.get("submitters") or []]
    rec.people += [{"role": "Lab head", "name": _pi(s), "affiliation": s.get("affiliation", ""), "email": s.get("email", "")} for s in p.get("labPIs") or []]
    for ref in p.get("references") or []:
        if ref.get("pubmedID") and str(ref["pubmedID"]) != "0":
            rec.papers.append(f"pmid:{ref['pubmedID']}")
        elif ref.get("doi"):
            rec.papers.append(f"doi:{ref['doi'].lower()}")
        elif ref.get("referenceLine"):
            rec.papers.append({"title": ref["referenceLine"], "journal": "", "year": "", "url": ""})
    if p.get("doi"):
        rec.links.append(("Dataset DOI", f"https://doi.org/{p['doi']}"))
    rec.links.append(("ProteomeXchange", f"https://proteomecentral.proteomexchange.org/cgi/GetDataset?ID={accession}"))

    sources.pride_files(accession)
    kinds = {f["url"]: f["kind"] for f in _pride_kinds(accession)}
    for f in json.loads((sources.PRIDE_FILES_CACHE / f"{accession}.json").read_text()):
        ftp = next((loc["value"] for loc in f.get("publicFileLocations", []) if loc["value"].startswith("ftp://")), None)
        if ftp:
            url = _https(ftp)
            group = f["fileCategory"]["value"].capitalize()
            rec.file(f["fileName"], url, group, f.get("fileSizeBytes"), url in kinds, kinds.get(url, ""))
    return rec


def _pride_kinds(accession: str) -> list[dict]:
    """The author-processed files, as `sources.pride_files` sorts them, without its cap on how many are listed."""
    files = json.loads((sources.PRIDE_FILES_CACHE / f"{accession}.json").read_text())
    out = []
    for f in files:
        name, category = f["fileName"], f["fileCategory"]["value"]
        if category == "RAW" or sources.SKIPPED_FILES.search(name):
            continue
        kind = "sample design" if category == "EXPERIMENTAL DESIGN" else next((k for k, pattern in sources.FILE_KINDS if pattern.search(name)), None)
        ftp = next((loc["value"] for loc in f.get("publicFileLocations", []) if loc["value"].startswith("ftp://")), None)
        if kind and ftp:
            out.append({"url": _https(ftp), "kind": kind})
    return out


# The read files these links point to are listed in full from the runs.
ENA_FILE_LINKS = {"ENA-FASTQ-FILES", "ENA-SUBMITTED-FILES"}
ENA_SHOWN = {"IDENTIFIERS", "NAME", "TITLE", "DESCRIPTION", "SUBMISSION_PROJECT", "UMBRELLA_PROJECT", "PROJECT_LINKS",
             "PROJECT_ATTRIBUTES", "RELATED_PROJECTS", "COLLABORATORS"}


def _ena(accession: str, row: dict) -> Record:
    root = ET.fromstring(_cached(f"{accession}.ena.xml", ENA_XML.format(accession)))
    project = root.find("PROJECT")
    if project is None:
        return _stored(accession, row)
    text = lambda path: " ".join((project.findtext(path) or "").split())
    rec = Record(accession, "ENA", row["url"], text("TITLE") or row["title"])
    rec.unmapped = sorted({child.tag for child in project} - ENA_SHOWN)
    if description := (project.findtext("DESCRIPTION") or "").strip():
        rec.texts.append(("Description", description))
    rec.fact("Study name", text("NAME"))
    rec.fact("Secondary accession", *[e.text for e in project.findall("IDENTIFIERS/SECONDARY_ID")])
    rec.fact("Center", project.get("center_name"))
    rec.fact("Organism", *[e.text for e in project.iter("SCIENTIFIC_NAME")])
    rec.fact("Project type", *[child.tag.replace("_", " ").capitalize() for child in project.findall("SUBMISSION_PROJECT/*") if child.tag != "ORGANISM"])
    rec.fact("Umbrella project", "yes" if project.find("UMBRELLA_PROJECT") is not None else "")
    rec.people += [{"role": "Collaborator", "name": " ".join((c.text or "").split())} for c in project.findall("COLLABORATORS/COLLABORATOR")]
    for attribute in project.findall("PROJECT_ATTRIBUTES/PROJECT_ATTRIBUTE"):
        tag, value = attribute.findtext("TAG") or "", attribute.findtext("VALUE") or ""
        if tag.lower() == "pubmed_id":
            rec.papers += [f"pmid:{p.strip()}" for p in value.split(",") if p.strip().isdigit()]
            continue
        rec.fact({"ENA-FIRST-PUBLIC": "First public", "ENA-LAST-UPDATE": "Last updated"}.get(tag, tag.replace("ENA-", "").replace("-", " ").capitalize()), value)
    for link in project.findall("PROJECT_LINKS/PROJECT_LINK/*"):
        db, ident = link.findtext("DB") or "", link.findtext("ID") or ""
        if link.tag == "URL_LINK":
            rec.links.append((link.findtext("LABEL") or "Link", link.findtext("URL") or ""))
        elif db.upper() == "PUBMED":
            rec.papers.append(f"pmid:{ident}")
        elif db in ENA_FILE_LINKS:
            continue
        elif db and ident:
            rec.links.append((db.replace("ENA-", "").replace("-", " ").capitalize(), ident if ident.startswith("http") else f"https://www.ebi.ac.uk/ena/browser/view/{ident}"))
    for related in project.findall("RELATED_PROJECTS/RELATED_PROJECT/*"):
        if related.get("accession"):
            rec.links.append((related.tag.replace("_", " ").capitalize(), f"https://www.ebi.ac.uk/ena/browser/view/{related.get('accession')}"))
    _ena_runs(rec, accession)
    return rec


def _attrs(section: dict) -> list[tuple[str, str]]:
    return [(a["name"], str(a.get("value") or "")) for a in section.get("attributes", []) if a.get("name")]


def _subsections(section: dict):
    for sub in section.get("subsections", []):
        yield from (sub if isinstance(sub, list) else [sub])


# File descriptions that only repeat the section a file is in.
AE_PLAIN = {"raw data file", "processed data", "processed data file"}
AE_SHOWN = {"Protocols", "Author", "Organization", "Publication", "Samples", "Assays and Data", "MINSEQE Score", "MIAME Score"}


def _arrayexpress(accession: str, row: dict) -> Record:
    study = json.loads(_cached(f"{accession}.biostudies.json", BIOSTUDIES.format(accession)))
    section = study["section"]
    top = dict(_attrs(study))
    rec = Record(accession, "ArrayExpress", row["url"], top.get("Title") or row["title"])
    for name, value in _attrs(section):
        if name == "Description":
            rec.texts.insert(0, ("Description", value))
        elif name != "Title":
            rec.fact(name, *[v for n, v in _attrs(section) if n == name])
    rec.fact("Released", top.get("ReleaseDate"))
    organisations = {}
    for sub in _subsections(section):
        if sub.get("type") == "Organization":
            organisations[sub.get("accno")] = dict(_attrs(sub)).get("Name", "")
    for sub in _subsections(section):
        kind, attrs = sub.get("type", ""), _attrs(sub)
        values = dict(attrs)
        if kind not in AE_SHOWN:
            rec.unmapped.append(kind)
        elif kind == "Protocols":
            rec.texts.append((f"Protocol: {values.get('Type', values.get('Name', ''))}", values.get("Description", "")))
        elif kind == "Author":
            rec.people.append({"role": values.get("Role", "Author").capitalize(), "name": values.get("Name", ""),
                               "affiliation": organisations.get(values.get("affiliation"), ""), "email": values.get("Email", "")})
        elif kind == "Publication":
            ident = f"pmid:{values['PubMed ID']}" if values.get("PubMed ID") else f"doi:{values['DOI'].lower()}" if values.get("DOI") else None
            rec.papers.append(ident or {"title": values.get("Title", ""), "journal": values.get("Authors", ""), "year": "", "url": ""})
        elif kind in ("MINSEQE Score", "MIAME Score"):
            rec.fact(kind, ", ".join(n for n, v in attrs if v == "*") or "none")
        elif kind == "Samples":
            for name, _ in attrs:
                rec.fact(name, *[v for n, v in attrs if n == name])
            table = next((t for s in _subsections(sub) if s.get("type") == "Source Characteristics" for t in [s]), None)
            rows = [dict(_attrs(t)) for t in _subsections(table)] if table else []
            if rows:
                columns = list(dict.fromkeys(k for r in rows for k in r))
                rec.samples = {"columns": columns, "rows": [[r.get(c, "") for c in columns] for r in rows], "link": ""}
        elif kind == "Assays and Data":
            for name, _ in attrs:
                rec.fact(name, *[v for n, v in attrs if n == name])
            for data in _subsections(sub):
                group = data.get("type", "Files")
                for f in (x for batch in data.get("files", []) for x in (batch if isinstance(batch, list) else [batch])):
                    description = dict(_attrs(f)).get("Description", "")
                    rec.file(f["path"].rsplit("/", 1)[-1], BIOSTUDIES_FILES.format(accession, f["path"]), group, f.get("size"),
                             group == "Processed Data", "" if description.lower() in AE_PLAIN else description)
    for link in (x for batch in section.get("links", []) for x in (batch if isinstance(batch, list) else [batch])):
        url = link.get("url", "")
        rec.links.append((dict(_attrs(link)).get("Type", "Link"), url if url.startswith("http") else f"https://www.ebi.ac.uk/biostudies/studies/{url}"))
    return rec


def _stored(accession: str, row: dict) -> Record:
    """Repositories without an adapter yet: what locus stored when it harvested the dataset."""
    rec = Record(accession, row["source"], row["url"], row["title"])
    if row["summary"]:
        rec.texts.append(("Summary", row["summary"]))
    rec.fact("Organism", *row["organism"].split(";"))
    rec.fact("Data type", *row["modality"].split(" | ")[0].split(";"))
    rec.fact("Samples", row["samples"])
    rec.fact("Published", row["published"])
    for key, values in store.metadata([accession]).get(accession, {}).items():
        if key not in ("source", "sample_count"):
            rec.fact(key.replace("_", " ").capitalize(), *(values if isinstance(values, list) else [values]))
    rec.papers = json.loads(row["papers"] or "[]")
    return rec


WORKBENCH = "https://www.metabolomicsworkbench.org/rest/study"


def _entries(text: str) -> list[dict]:
    """A Metabolomics Workbench REST answer as a list: several results come keyed "1", "2", …; one comes bare."""
    data = json.loads(text) if text.strip() else {}
    return list(data.values()) if data and all(isinstance(v, dict) for v in data.values()) else [data] if data else []


def _workbench(accession: str, row: dict) -> Record:
    """What locus stored, plus each sample's factors and each analysis with its mwTab table (metabolite by sample)."""
    rec = _stored(accession, row)
    factors = _entries(_cached(f"{accession}.mw-factors.json", f"{WORKBENCH}/study_id/{accession}/factors"))
    analyses = _entries(_cached(f"{accession}.mw-analysis.json", f"{WORKBENCH}/study_id/{accession}/analysis"))
    pairs = [dict(p.partition(":")[::2] for p in f.get("factors", "").split(" | ") if ":" in p) for f in factors]
    keys = list(dict.fromkeys(k.strip() for p in pairs for k in p))
    if factors:
        rec.samples = {"columns": ["Accession", "Title", "Sample source", *keys], "link": "",
                       "rows": [[f.get("mb_sample_id", ""), f.get("local_sample_id", ""), f.get("sample_source", ""), *[p.get(k, "").strip() for k in keys]] for f, p in zip(factors, pairs)]}
    for a in analyses:
        described = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in a.items() if v and k not in ("study_id", "analysis_id"))
        rec.texts.append((f"Analysis {a['analysis_id']}", described))
        rec.file(f"{a['analysis_id']}_mwtab.txt", f"{WORKBENCH}/analysis_id/{a['analysis_id']}/mwtab/txt", "Processed", None, True, "mwTab: metabolite by sample table")
    rec.fact("Instrument", *[a.get("ms_instrument_name") or a.get("nmr_instrument_type") for a in analyses])
    rec.fact("Chromatography", *[a.get("chromatography_type") for a in analyses])
    rec.fact("Units", *[a.get("units") for a in analyses])
    return rec


ADAPTERS = {"GEO": _geo, "PRIDE": _pride, "ENA": _ena, "ArrayExpress": _arrayexpress, "MetabolomicsWorkbench": _workbench}


def _paper_links(ids: list) -> list[dict]:
    from .agent import paper_details

    found = paper_details([p for p in ids if isinstance(p, str)])
    out = []
    for p in dict.fromkeys(json.dumps(x) for x in ids):
        p = json.loads(p)
        if isinstance(p, dict):
            out.append(p)
        elif p in found:
            out.append(found[p] | {"id": p})
        else:
            url = f"https://europepmc.org/article/MED/{p[5:]}" if p.startswith("pmid:") else f"https://doi.org/{p[4:]}"
            out.append({"title": p.replace("pmid:", "PMID ").replace("doi:", "DOI "), "journal": "", "year": "", "url": url, "id": p})
    return list({p["url"] or p["title"]: p for p in out}.values())


def _row(accession: str) -> dict | None:
    db = store.connect()
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM datasets WHERE accession = ?", (accession,)).fetchone()
    return dict(row) if row else None


def raw(accession: str, row: dict) -> Record:
    """The record with paper IDs unresolved; a repository that fails falls back to what locus stored."""
    try:
        return ADAPTERS.get(row["source"], _stored)(accession, row)
    except (httpx.HTTPError, ET.ParseError, ValueError, KeyError) as error:
        rec = _stored(accession, row)
        rec.unmapped.append(f"live record unavailable: {type(error).__name__}")
        return rec


def record(accession: str) -> dict | None:
    if not (row := _row(accession)):
        return None
    rec = raw(accession, row)
    rec.papers = _paper_links(rec.papers)
    return asdict(rec) | {
        "modality": row["modality"].split(" | ")[0], "organism": row["organism"], "published": row["published"],
        "sample_count": row["samples"], "download_plan": sources.download_plan(accession, row["source"], row["url"]),
    }


# GEO sample fields, as the sample page shows them. Fields of the second channel of a two-colour array carry "_ch2".
GSM_TEXTS = {"description": "Description", "treatment_protocol": "Treatment protocol", "growth_protocol": "Growth protocol",
             "extract_protocol": "Extraction protocol", "label_protocol": "Labelling protocol", "hyb_protocol": "Hybridisation protocol",
             "scan_protocol": "Scan protocol", "data_processing": "Data processing"}
GSM_FACTS = {"source_name": "Source", "organism": "Organism", "molecule": "Molecule", "label": "Label", "type": "Sample type",
             "instrument_model": "Instrument", "library_strategy": "Library strategy", "library_source": "Library source",
             "library_selection": "Library selection", "status": "Status", "submission_date": "Submitted", "last_update_date": "Last updated",
             "data_row_count": "Data rows"}
GSM_SHOWN = {"title", "characteristics", "platform_id", "relation", "series_id", "supplementary_file", "channel_count", *GSM_TEXTS, *GSM_FACTS,
             *(k for k in GEO_SHOWN if k.startswith("contact_"))}
GSM_SKIPPED = {"geo_accession", "taxid"}


def _gsm_fields(dataset: str, gsm: str) -> dict[str, list[str]]:
    samples.geo_records(dataset)
    for block in (samples.CACHE / f"{dataset}.txt").read_text().split("^SAMPLE = ")[1:]:
        if block.split("\n", 1)[0].strip() == gsm:
            fields: dict[str, list[str]] = {}
            for line in block.splitlines()[1:]:
                key, _, value = line.partition(" = ")
                if key.startswith("!Sample_"):
                    fields.setdefault(key[8:], []).append(value)
            return fields
    raise LookupError(f"{gsm} is not a sample of {dataset}.")


def _gsm(dataset: str, gsm: str) -> Record:
    fields = _gsm_fields(dataset, gsm)
    two = (fields.get("channel_count") or ["1"])[0] == "2"
    base = lambda key: re.sub(r"_(ch\d|\d+)$", "", key)
    rec = Record(gsm, "GEO", f"{GEO}?acc={gsm}", (fields.get("title") or [gsm])[0])
    rec.unmapped = sorted({k for k in fields if base(k) not in GSM_SHOWN | GSM_SKIPPED})
    channel = lambda key: f" (channel {key[-1]})" if two and re.search(r"_ch\d$", key) else ""
    characteristics = []
    for key in sorted(k for k in fields if base(k) == "characteristics"):
        for value in fields[key]:
            name, sep, val = value.partition(": ")
            characteristics.append((f"{name}{channel(key)}" if sep else f"characteristic{channel(key)}", val if sep else value))
    for key, values in fields.items():
        if base(key) in GSM_TEXTS and (text := _geo_text(values)):
            rec.texts.append((GSM_TEXTS[base(key)] + channel(key), text))
    for short, label in GSM_FACTS.items():
        for key in [k for k in fields if base(k) == short]:
            rec.fact(label + channel(key), *fields[key])
    for gpl in fields.get("platform_id", []):
        brief = _cached(f"{gpl}.txt", GEO, {"acc": gpl, "targ": "self", "form": "text", "view": "brief"}, ncbi=True)
        title = re.search(r"^!Platform_title = (.*)$", brief, re.M)
        rec.fact("Platform", f"{gpl} {title.group(1)}" if title else gpl)
    rec.fact("Series", *fields.get("series_id", []))
    one = lambda k: (fields.get(k) or [""])[0]
    if contact := one("contact_name"):
        place = ", ".join(one(k) for k in ("contact_department", "contact_laboratory", "contact_institute", "contact_address",
                                           "contact_city", "contact_state", "contact_zip/postal_code", "contact_country") if one(k))
        rec.people.append({"role": "Contact", "name": _person(contact), "affiliation": place, "email": one("contact_email").lower()})
    experiment = ""
    for relation in fields.get("relation", []):
        label, _, target = relation.partition(": ")
        rec.links.append((label, target if target.startswith("http") else f"{GEO}?acc={target}"))
        experiment = experiment or (re.search(r"\b[SED]RX\d+", target) or [""])[0]
    sizes = dict(_listing(f"https://ftp.ncbi.nlm.nih.gov/geo/samples/{_stub(gsm)}/{gsm}/suppl/", f"{gsm}.suppl.html"))
    for key in (k for k in fields if base(k) == "supplementary_file"):
        for f in fields[key]:
            if f != "NONE":
                name = f.rsplit("/", 1)[-1]
                rec.file(name, _https(f), "Supplementary files", sizes.get(name), True)
    for run in _runs(experiment) if experiment else []:
        _run_files(rec, run)
    rec.samples = {"columns": ["Characteristic", "Value"], "rows": [list(c) for c in characteristics], "link": ""}
    return rec


BIOSAMPLES = "https://www.ebi.ac.uk/biosamples/samples/{}"


def _ena_run(project: str, run_accession: str) -> Record:
    run = next((r for r in _runs(project) if r["run_accession"] == run_accession), None)
    if not run:
        raise LookupError(f"{run_accession} is not a run of {project}.")
    rec = Record(run_accession, "ENA", f"https://www.ebi.ac.uk/ena/browser/view/{run_accession}",
                 run.get("sample_title") or run.get("experiment_title") or run_accession)
    for label, key in (("Organism", "scientific_name"), ("Sample", "sample_accession"), ("Experiment", "experiment_title"),
                       ("Instrument", "instrument_model"), ("Library strategy", "library_strategy"), ("Library source", "library_source"),
                       ("Library layout", "library_layout")):
        rec.fact(label, run.get(key))
    rec.fact("Reads", f"{int(run['read_count']):,}" if run.get("read_count", "").isdigit() else "")
    rec.fact("Bases", f"{int(run['base_count']) / 1e9:,.2f} Gb" if run.get("base_count", "").isdigit() else "")
    _run_files(rec, run)
    characteristics = []
    if sample := run.get("sample_accession"):
        biosample = json.loads(_cached(f"{sample}.biosample.json", BIOSAMPLES.format(sample)))
        for name, values in (biosample.get("characteristics") or {}).items():
            characteristics += [(name, v.get("text", "")) for v in values if v.get("text")]
        rec.fact("Sample name", biosample.get("name"))
        rec.fact("Released", (biosample.get("release") or "")[:10])
        rec.links.append(("BioSample", f"https://www.ebi.ac.uk/biosamples/samples/{sample}"))
        rec.links.append(("ENA sample", f"https://www.ebi.ac.uk/ena/browser/view/{sample}"))
    rec.samples = {"columns": ["Characteristic", "Value"], "rows": [list(c) for c in characteristics], "link": ""}
    return rec


SAMPLE_ADAPTERS = {"GEO": _gsm, "ENA": _ena_run}


def sample(dataset: str, accession: str) -> dict | None:
    """One sample of a dataset as its repository's sample page shows it, with its place in the dataset's sample list."""
    if not (row := _row(dataset)) or row["source"] not in SAMPLE_ADAPTERS:
        return None
    rec = SAMPLE_ADAPTERS[row["source"]](dataset, accession)
    order = [r[0] for r in (raw(dataset, row).samples or {}).get("rows", [])]
    at = order.index(accession) if accession in order else -1
    return asdict(rec) | {
        "dataset": {"accession": dataset, "title": row["title"], "source": row["source"]},
        "position": {"index": at, "total": len(order), "previous": order[at - 1] if at > 0 else None,
                     "next": order[at + 1] if 0 <= at < len(order) - 1 else None},
    }


if __name__ == "__main__":
    import sys

    for accession in sys.argv[1:] or ["GSE150910", "PXD012345", "PRJEB1973", "E-MTAB-6149", "MTBLS1"]:
        r = record(accession)
        assert r, f"{accession} is not in the index"
        print(accession, r["source"], "facts", len(r["facts"]), "texts", len(r["texts"]), "people", len(r["people"]), "papers", len(r["papers"]),
              "links", len(r["links"]), "files", len(r["files"]), "samples", len((r["samples"] or {}).get("rows", [])), "unmapped", r["unmapped"])
        assert not r["unmapped"], f"{accession} has source fields the page does not show: {r['unmapped']}"
    for dataset in ("GSE150910", "GSE10384", "PRJEB1973"):
        first = record(dataset)["samples"]["rows"][0][0]
        s = sample(dataset, first)
        print(dataset, first, "characteristics", len(s["samples"]["rows"]), "texts", len(s["texts"]), "facts", len(s["facts"]),
              "files", len(s["files"]), "next", s["position"]["next"], "unmapped", s["unmapped"])
        assert not s["unmapped"], f"{first} has source fields the page does not show: {s['unmapped']}"
    print("ok")
