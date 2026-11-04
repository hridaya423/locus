import json
import os
import queue
import re
import threading
from dataclasses import asdict
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints

load_dotenv()

from . import samples, store  # noqa: E402
from . import agent, assay, browse, design, design_check, everywhere, follows, kits, lists, maxquant, options, pace, paper, person, preview, process, qc, record, resolve, saved, settings, sources, subset, table, users, volcano, watches, why  # noqa: E402  (needs the API key loaded first)

HEARTBEAT = 10

app = FastAPI(title="omics-agent")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:3020"], allow_methods=["*"], allow_headers=["Content-Type"])
# Accounts: /account/* routes and the shared {"error": {...}} shape (users.py holds sessions, CSRF guard, rate limits).
users.install(app)
# Saved datasets and named lists under /lists/* (saved.py); the gene-list checker keeps POST /list.
saved.install(app)
# Watched searches kept in an account under /follows/questions (watches.py).
watches.install(app)
# Followed researchers by ORCID under /follows/people, and /person/identity for the person page (follows.py).
follows.install(app)
# Settings under /account (settings.py): name, passkeys, recovery codes, ORCID unlink, export, delete the account.
settings.install(app)


class SearchIn(BaseModel):
    question: str
    limit: int = agent.KEEP


@app.post("/search")
def search(body: SearchIn) -> StreamingResponse:
    """Streams one JSON line per stage (plan, candidates, screened, facts), then the result as {"stage": "done"}."""
    events: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            result = agent.run(body.question, body.limit, lambda stage, data: events.put({"stage": stage, "data": data}))
            events.put({"stage": "done", "data": result})
        except Exception as error:
            events.put({"stage": "error", "data": str(error)})

    threading.Thread(target=work, daemon=True).start()

    def stream():
        # A stage on a local model can take minutes; a heartbeat line keeps proxies from closing the idle stream.
        while True:
            try:
                event = events.get(timeout=HEARTBEAT)
            except queue.Empty:
                yield json.dumps({"stage": "working"}) + "\n"
                continue
            yield json.dumps(event) + "\n"
            if event["stage"] in ("done", "error"):
                return

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class CompareIn(BaseModel):
    # Accessions reach cache file paths, so no separators or leading dots.
    accessions: list[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")]] = Field(min_length=2, max_length=2)
    topic: str


@app.post("/compare")
def compare(body: CompareIn) -> dict:
    """Whether two datasets can be pooled, compared as effects, or not combined, with the facts behind the verdict."""
    a, b = body.accessions
    if a == b:
        raise HTTPException(422, "Compare two different datasets.")
    try:
        return asdict(agent.compare_datasets(a, b, body.topic))
    except LookupError as error:
        raise HTTPException(404, str(error))
    except ValueError as error:
        raise HTTPException(422, str(error))


@app.get("/samplesheet/{accession}")
def samplesheet(topic: str, accession: str = Path(pattern=r"^GSE\d+$")) -> Response:
    """nf-core/riboseq samplesheet, contrasts and README for one GEO series, as a zip. `topic` is the search's terms, so the labels match the result table."""
    return Response(
        agent.export_samplesheet(accession, topic),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{accession}-riboseq.zip"'},
    )


@app.get("/design/{accession}")
def sample_design(source: str, accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """The factors that vary across a dataset's samples, their levels and counts, and what all samples share."""
    found = design.design(accession, source)
    if not found:
        return {}
    comparison = volcano.groups(accession)["default"]
    return found | {"comparison": comparison, "people": design.people(accession, comparison)}


class SubsetIn(BaseModel):
    filters: dict[str, list[str]] = {}
    text: str = ""


@app.post("/subset/{accession}")
def sample_subset(body: SubsetIn, accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """The samples matching levels chosen in the dataset's factors and a text, as row indexes into its sample table, with the
    sample count of every level inside that selection and the commands that download just those samples."""
    try:
        return subset.select(accession, body.filters, body.text)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except ValueError as error:
        raise HTTPException(422, str(error))
@app.get("/assay/{accession}")
def assays(accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """What was measured, read from the methods text with the sentence for each call, and the author's label beside it."""
    if not (found := assay.classify(accession)):
        raise HTTPException(404, f"{accession} is not in the index.")
    return found


@app.get("/qc/{accession}")
def quality(accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """Reads per sample from the run table with outliers flagged, and the authors' QC criteria quoted from their methods."""
    return qc.sample_qc(accession)
@app.get("/table/{accession}")
def processed_table(accession: str = Path(pattern=r"^(GSE\d+|ST\d{6}|MTBLS\d+|PXD\d+)$")) -> dict:
    """Whether locus can hand over the finished counts table for a GEO series, its size and its source."""
    return table.summary(accession)


@app.get("/table/{accession}/download")
def processed_table_zip(accession: str = Path(pattern=r"^(GSE\d+|ST\d{6}|MTBLS\d+|PXD\d+)$")) -> Response:
    """counts, sample metadata, gene annotation and a manifest, as one zip."""
    if not table.summary(accession)["available"]:
        raise HTTPException(404, f"No processed table for {accession}.")
    return Response(table.bundle(accession), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{accession}_locus_table.zip"'})


@app.get("/first-look/{accession}")
def first_look(accession: str = Path(pattern=r"^(GSE\d+|ST\d{6}|MTBLS\d+|PXD\d+)$"), factor: str | None = None, case: Annotated[list[str] | None, Query()] = None,
               control: Annotated[list[str] | None, Query()] = None, within_factor: str | None = None, within: str | None = None) -> dict:
    """Each gene's change between two sample groups and its significance, from the fetched counts; the method is in the result."""
    try:
        return volcano.compare(accession, factor, case, control, (within_factor, within) if within_factor and within else None)
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(502, f"The table could not be read: {error}") from error


@app.get("/first-look/{accession}/paper")
def first_look_paper(accession: str = Path(pattern=r"^(GSE\d+|ST\d{6}|MTBLS\d+|PXD\d+)$"), factor: str | None = None, case: Annotated[list[str] | None, Query()] = None,
                     control: Annotated[list[str] | None, Query()] = None) -> dict:
    """The genes the dataset's paper names, and where each lands in the same comparison."""
    look = volcano.compare(accession, factor, case, control)
    return volcano.paper_genes(accession, look) if look.get("available") else {"available": False, "reason": look.get("reason")}


@app.get("/first-look/{accession}/pathways")
def first_look_pathways(accession: str = Path(pattern=r"^(GSE\d+|ST\d{6}|MTBLS\d+|PXD\d+)$"), factor: str | None = None, case: Annotated[list[str] | None, Query()] = None,
                        control: Annotated[list[str] | None, Query()] = None, within: Annotated[list[str] | None, Query()] = None) -> dict:
    """Reactome pathways over-represented among the top genes up and down in the same comparison, from Enrichr."""
    look = volcano.compare(accession, factor, case, control, tuple(within) if within and len(within) == 2 else None)
    if not look.get("available"):
        return {"available": False, "reason": look.get("reason")}
    try:
        return volcano.pathways(look)
    except httpx.HTTPError:
        raise HTTPException(502, "Enrichr did not answer. Please try again.")


@app.get("/gene/{symbol}")
def gene_across(symbol: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,29}$"), accession: Annotated[list[str] | None, Query(alias="in")] = None, hint: str = "") -> dict:
    """One gene's change between cases and controls in each listed GEO dataset, one row each."""
    accessions = [a for a in (accession or []) if re.fullmatch(r"GSE\d+", a)][:40]
    return everywhere.gene_everywhere(symbol, accessions, hint)


@app.get("/design-check/{accession}")
def design_checks(accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$"), factor: str | None = None, case: Annotated[list[str] | None, Query()] = None,
                  control: Annotated[list[str] | None, Query()] = None) -> dict:
    """Confounding with batch, unbalanced characteristics, different tissues and small groups for one comparison, and the smallest detectable change."""
    return design_check.check(accession, factor, case, control)


class ListIn(BaseModel):
    text: str = Field(max_length=200_000)
    accession: str = Field(default="", pattern=r"^(GSE\d+)?$")
    factor: str | None = None
    case: list[str] | None = None
    control: list[str] | None = None


@app.post("/list")
def your_list(body: ListIn) -> dict:
    """A pasted gene or protein list against MitoCarta 3.0 and, given a GEO dataset, against its first-look comparison."""
    return lists.check(body.text, body.accession, body.factor, body.case, body.control)


class AcrossIn(BaseModel):
    text: str = Field(max_length=200_000)
    accessions: list[Annotated[str, StringConstraints(pattern=r"^GSE\d+$")]] = Field(max_length=40)
    hint: str = Field(default="", max_length=300)


@app.post("/list/across")
def list_across(body: AcrossIn) -> dict:
    """A pasted list against the cases-and-controls comparison of each GEO dataset: tested, significant, against chance."""
    return lists.across(body.text, body.accessions, body.hint)
@app.get("/browse")
def browse_value(field: str, value: str, source: str = "", offset: int = 0) -> dict:
    """Every locus dataset that shares one stated value (organism, instrument, data type, keyword), newest first."""
    return browse.browse(field, value[:200], source, max(0, offset))


@app.get("/record/{accession}")
def dataset_record(accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """Everything the repository's own page shows for one dataset: texts, facts, people, papers, links, samples and files."""
    try:
        found = record.record(accession)
    except httpx.HTTPError as error:
        raise HTTPException(502, f"The repository did not answer: {error}") from error
    if not found:
        raise HTTPException(404, f"{accession} is not in the index.")
    for f in found["files"]:
        f["preview"] = preview.previewable(f, accession)
    return found


@app.get("/record/{accession}/samples/{sample}")
def sample_record(accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$"), sample: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """One sample as its repository's sample page shows it: characteristics, protocols, facts, links and files."""
    try:
        found = record.sample(accession, sample)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except httpx.HTTPError as error:
        raise HTTPException(502, f"The repository did not answer: {error}") from error
    if not found:
        raise HTTPException(404, f"locus has no sample pages for {accession}.")
    return found


class WhyIn(BaseModel):
    terms: list[Annotated[str, StringConstraints(max_length=200)]] = Field(max_length=60)
    quote: Annotated[str, StringConstraints(max_length=1000)] = ""


@app.post("/why/{accession}")
def why_matched(body: WhyIn, accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """Where the search's terms and its quote appear in one dataset's own record: spans with character offsets, by field."""
    if not (found := why.why(accession, body.terms, body.quote)):
        raise HTTPException(404, f"{accession} is not in the index.")
    return found


JOBS: dict[str, dict] = {}
# OMICS_PROCESS=cached serves earlier runs only: a public server shows them but does not start new ones.
PROCESS_LIVE = os.environ.get("OMICS_PROCESS", "live") != "cached"
JOBS_LOCK = threading.Lock()


def _job_state(accession: str) -> dict:
    """The job in memory, else an earlier complete run on disk, else nothing."""
    if job := JOBS.get(accession):
        return job
    if result := process.cached(accession):
        return {"stage": "done", "log": [], "result": result, "error": None}
    return {"stage": None, "log": [], "result": None, "error": None}


@app.post("/process/{accession}", status_code=202)
def process_start(topic: str = "", accession: str = Path(pattern=r"^GSE\d+$")) -> dict:
    """Starts the laptop-tier pipeline for one GEO series in the background, unless it is running or already done.
    `topic` is the search's terms, so the case/control labels are the ones the result table showed."""
    with JOBS_LOCK:
        state = _job_state(accession)
        if state["stage"] and state["stage"] not in ("done", "error"):
            return {"accession": accession, "stage": state["stage"], "started": False}
        if state["stage"] == "done":
            return {"accession": accession, "stage": "done", "started": False}
        if not PROCESS_LIVE:
            JOBS[accession] = {"stage": "error", "log": [], "result": None, "error": (
                f"This public site shows runs that were computed beforehand. To process {accession} yourself, install "
                f"locus and run `uv run omics process {accession}`: about 3 minutes on a laptop for a small study "
                "(see the README, \"Process a dataset\").")}
            return {"accession": accession, "stage": "error", "started": False}
        job = JOBS[accession] = {"stage": "plan", "log": [], "result": None, "error": None}

    def progress(stage: str, data) -> None:
        if stage == "log":
            job["log"] = (job["log"] + [data])[-200:]
        elif stage in process.STAGES:
            job["stage"] = stage
            job.setdefault("stages", {})[stage] = data

    def work() -> None:
        try:
            job["result"] = process.run(accession, topic, progress=progress)
            job["stage"] = "done"
        except Exception as error:
            job["stage"], job["error"] = "error", str(error)

    threading.Thread(target=work, daemon=True).start()
    return {"accession": accession, "stage": "plan", "started": True}


@app.get("/process/{accession}")
def process_status(accession: str = Path(pattern=r"^GSE\d+$")) -> dict:
    """The job's stage (plan, reference, fetch, quantify, count, test, done or error), the last log lines, per-stage
    data, and the result once it is done. Unknown accessions have stage null."""
    state = _job_state(accession)
    return {"accession": accession, "stage": state["stage"], "log": state["log"][-30:], "stages": state.get("stages", {}),
            "result": state["result"] if state["stage"] == "done" else None, "error": state["error"]}


@app.get("/process/{accession}/files/{name:path}")
def process_file(accession: str = Path(pattern=r"^GSE\d+$"), name: str = Path(pattern=r"^(plots/)?[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")) -> FileResponse:
    """One output of a finished run: a .count file, a results table, a plot (top level or under plots/) or the manifest."""
    path = process.out_dir(accession) / name
    if name not in {f["name"] for f in process.files_of(process.out_dir(accession))} or not path.is_file():
        raise HTTPException(404, f"{accession} has no file {name}")
    return FileResponse(path, filename=path.name)



# ---------------------------------------------------------------- the three rows, for every data type

ROW = Path(pattern=r"^(here|laptop|cluster)$")


def _runner(kind: str, row: str):
    """The function that runs one row of one data type on this machine, or None when the row is a kit or a link."""
    if kind == "bulk_rnaseq" and row == "laptop":
        return lambda accession, topic, progress: process.run(accession, topic, progress=progress)
    if kind == "scrnaseq" and row == "here":
        from . import singlecell
        return lambda accession, topic, progress: singlecell.run_here(accession, topic, process.out_dir(accession) / f"{kind}-{row}", progress=progress)
    if kind == "riboseq" and row == "here":
        from . import riboseq
        return lambda accession, topic, progress: riboseq.run_here(accession, topic, process.out_dir(accession) / f"{kind}-{row}", progress=progress)
    if kind == "riboseq" and row == "laptop":
        from . import riboseq
        return lambda accession, topic, progress: riboseq.run_laptop(accession, topic, process.out_dir(accession) / f"{kind}-{row}", progress=progress)
    return None


def _run_dir(accession: str, kind: str, row: str):
    return process.out_dir(accession) if kind == "bulk_rnaseq" else process.out_dir(accession) / f"{kind}-{row}"


def _run_state(accession: str, kind: str, row: str) -> dict:
    # Bulk RNA-seq's "here, now" is the laptop run computed earlier, so both rows read the same job.
    if kind == "bulk_rnaseq":
        return _job_state(accession)
    if job := JOBS.get(f"{accession}/{kind}/{row}"):
        return job
    result_file = _run_dir(accession, kind, row) / "result.json"
    if result_file.exists():
        return {"stage": "done", "log": [], "result": json.loads(result_file.read_text()), "error": None}
    return {"stage": None, "log": [], "result": None, "error": None}


@app.get("/process/{accession}/options")
def process_options(topic: str = "", accession: str = Path(pattern=r"^GSE\d+$")) -> dict:
    """The three rows (here, now / on your laptop / on a cluster) for one GEO series: which apply to this dataset, what
    each costs in time, memory and disk, and the reason when a row cannot work. `topic` is the search's terms."""
    try:
        out = options.options(accession, topic, PROCESS_LIVE)
    except LookupError as error:
        raise HTTPException(404, str(error))
    for row in out["rows"]:
        if row.get("action") in ("run", "cached"):
            state = _run_state(accession, out["data_type"], row["id"])
            row["state"] = state["stage"]
    return out


@app.post("/process/{accession}/run/{row}", status_code=202)
def process_row_start(topic: str = "", accession: str = Path(pattern=r"^GSE\d+$"), row: str = ROW) -> dict:
    """Starts one row's analysis on this machine in the background: the bulk RNA-seq laptop pipeline, a single-cell or
    Ribo-seq 'here, now' analysis of the authors' files, or the Ribo-seq laptop path. Kits are fetched, not run."""
    opts = options.options(accession, topic, PROCESS_LIVE)
    kind = opts["data_type"]
    chosen = next((r for r in opts["rows"] if r["id"] == row), None)
    if not kind or not chosen or not chosen["available"]:
        raise HTTPException(409, (chosen or {}).get("reason") or opts.get("reason") or f"{accession} has no {row} row")
    if (kind, row) == ("bulk_rnaseq", "laptop"):
        return process_start(topic, accession)
    runner = _runner(kind, row)
    if runner is None:
        raise HTTPException(409, f"the {row} row of {opts['data_type_label']} is a kit: GET /process/{accession}/kit/{row}")
    if row == "laptop" and not PROCESS_LIVE:
        raise HTTPException(409, "This public site does not run laptop pipelines; use the command shown or install locus.")
    key = f"{accession}/{kind}/{row}"
    with JOBS_LOCK:
        state = _run_state(accession, kind, row)
        if state["stage"] and state["stage"] != "error":
            return {"accession": accession, "row": row, "stage": state["stage"], "started": False}
        job = JOBS[key] = {"stage": "plan", "log": [], "result": None, "error": None}

    def progress(stage: str, data) -> None:
        if stage == "log":
            job["log"] = (job["log"] + [data])[-200:]
        else:
            job["stage"] = stage
            job.setdefault("stages", {})[stage] = data if isinstance(data, dict) and stage != "done" else {}

    def work() -> None:
        try:
            job["result"] = runner(accession, topic, progress)
            job["stage"] = "done"
        except Exception as error:
            job["stage"], job["error"] = "error", str(error)

    threading.Thread(target=work, daemon=True).start()
    return {"accession": accession, "row": row, "stage": "plan", "started": True}


@app.get("/process/{accession}/run/{row}")
def process_row_status(topic: str = "", accession: str = Path(pattern=r"^GSE\d+$"), row: str = ROW) -> dict:
    """The row's job: stage, last log lines, per-stage data, and the result once done (result.json's shape)."""
    kind = _kind_of(accession, topic)
    state = _run_state(accession, kind, row)
    return {"accession": accession, "row": row, "data_type": kind, "stage": state["stage"], "log": state["log"][-30:], "stages": state.get("stages", {}),
            "result": state["result"] if state["stage"] == "done" else None, "error": state["error"]}


@app.get("/process/{accession}/run/{row}/files/{name:path}")
def process_row_file(accession: str = Path(pattern=r"^GSE\d+$"), row: str = ROW, name: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,120}$"), topic: str = "") -> FileResponse:
    """One output of a finished row run."""
    kind = _kind_of(accession, topic)
    if kind == "bulk_rnaseq":
        return process_file(accession, name)
    state = _run_state(accession, kind, row)
    path = _run_dir(accession, kind, row) / name
    if ".." in name or not state["result"] or name not in {f["name"] for f in state["result"].get("files", [])} or not path.is_file():
        raise HTTPException(404, f"{accession} {row} has no file {name}")
    return FileResponse(path, filename=path.name)


@app.get("/process/{accession}/kit/{row}")
def process_kit(topic: str = "", accession: str = Path(pattern=r"^GSE\d+$"), row: str = ROW) -> Response:
    """The zip for one row: a laptop kit or a cluster (Slurm / nf-core) kit, built from the records and ENA runs."""
    try:
        name, data = kits.kit(accession, topic, row)
    except ValueError as error:
        raise HTTPException(404, str(error))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _kind_of(accession: str, topic: str) -> str:
    records = samples.geo_records(accession)
    labels = agent.geo_labels(topic or store.summary(accession).split(". ")[0] or accession, accession, store.summary(accession)) if records else None
    return options.data_type(records, labels) or ""


@app.get("/files/{accession}")
def files(accession: str = Path(pattern=r"^PXD\d{6}$")) -> dict:
    """The author-processed files of a PRIDE project and a summary of its raw files."""
    return sources.pride_files(accession)


@app.get("/maxquant-kit/{accession}")
def maxquant_kit(accession: str = Path(pattern=r"^PXD\d{6}$")) -> Response:
    """A MaxQuant search kit for one PRIDE project (mqpar.xml from its SDRF, download and run scripts, a Slurm script and a
    README), as a zip. Generated and validated here; the search runs on an x86-64 workstation or cluster, not on this
    machine. 404 when the project has no SDRF, 422 when the SDRF states a design the kit cannot map."""
    try:
        data = maxquant.export_kit(accession)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except ValueError as error:
        raise HTTPException(422, str(error))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{accession}-maxquant.zip"'})


@app.get("/preview/{accession}")
def file_preview(file: str, accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """The columns, first rows and sample groups of one processed file in the dataset's record, read from its first bytes."""
    try:
        return preview.preview(accession, file)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except ValueError as error:
        raise HTTPException(422, str(error))
    except httpx.HTTPStatusError as error:
        code = error.response.status_code
        raise HTTPException(*(410, "The repository no longer serves this file (404).") if code == 404 else (502, f"The repository answered {code} for this file."))
    except httpx.HTTPError:
        raise HTTPException(502, "The repository did not answer.")
@app.get("/resolve/{identifier:path}")
def resolve_identifier(identifier: str) -> dict | None:
    """The locus page an accession, sample or run, PMID, PMCID or DOI names; null when the text is not an identifier."""
    try:
        return resolve.resolve(identifier)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except httpx.HTTPError:
        raise HTTPException(502, "A repository did not answer. Please try again.")


@app.get("/cite")
def cite_paper(q: str = Query(min_length=6, max_length=300)) -> dict:
    """The paper a citation-like query names (surname, year and a title word) and its locus datasets; {} when none."""
    try:
        return paper.cite(q) or {}
    except pace.PaceTimeout:
        raise HTTPException(503, BUSY, headers={"Retry-After": str(pace.RETRY_AFTER)})
    except httpx.HTTPError:
        return {}


BUSY = "locus is reading Europe PMC for many people at once. Please try again in a few seconds."


@app.get("/person")
def person_page(request: Request, name: str = Query(min_length=3, max_length=120)) -> dict:
    """A contributor's papers in Europe PMC (author search by surname and initials), their journals, which papers have
    supplementary files, and the locus datasets those papers deposited or cite. Answers that need Europe PMC are
    rate-limited per caller and overall (follows.PERSON_LIMIT); cached answers are not counted. 503 with Retry-After
    when the Europe PMC pacing or the upstream cap is full."""
    ip = users.client_ip(request)
    try:
        return person.person(name, admit=lambda: follows.PERSON_LIMIT.check(ip))
    except pace.PaceTimeout:
        raise HTTPException(503, BUSY, headers={"Retry-After": str(pace.RETRY_AFTER)})
    except httpx.HTTPError:
        raise HTTPException(502, "Europe PMC did not answer. Please try again.")


@app.get("/paper/{identifier:path}")
def paper_page(identifier: str, offset: int = Query(0, ge=0)) -> dict:
    """A paper's title, authors, abstract, data availability statement, supplementary files and the locus datasets that cite it,
    `offset` datasets in."""
    try:
        return paper.paper(identifier, offset)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except pace.PaceTimeout:
        raise HTTPException(503, BUSY, headers={"Retry-After": str(pace.RETRY_AFTER)})
    except httpx.HTTPError:
        raise HTTPException(502, "Europe PMC did not answer. Please try again.")


def main() -> None:
    import uvicorn

    from . import index

    users.connect().close()  # create or migrate the users DB (OMICS_USERS_DB) before serving
    # Load the embedding model and vectors before serving, so the first search does not pay for it.
    index.semantic_search("warm up", ["GEO"], "", 1)
    # OMICS_API_PORT lets the API move off 8000 when that port is taken; the web app's OMICS_API_URL must match.
    uvicorn.run(app, port=int(os.environ.get("OMICS_API_PORT") or 8000))
