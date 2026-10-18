import json
import os
import queue
import threading
from dataclasses import asdict
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints

load_dotenv()

from . import agent, process, sources  # noqa: E402  (needs the API key loaded first)

HEARTBEAT = 10

app = FastAPI(title="omics-agent")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:3020"], allow_methods=["*"], allow_headers=["*"])


class SearchIn(BaseModel):
    question: str
    limit: int = 40


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


JOBS: dict[str, dict] = {}
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


@app.get("/files/{accession}")
def files(accession: str = Path(pattern=r"^PXD\d{6}$")) -> dict:
    """The author-processed files of a PRIDE project and a summary of its raw files."""
    return sources.pride_files(accession)


def main() -> None:
    import uvicorn

    from . import index

    # Load the embedding model and vectors before serving, so the first search does not pay for it.
    index.semantic_search("warm up", ["GEO"], "", 1)
    # OMICS_API_PORT lets the API move off 8000 when that port is taken; the web app's OMICS_API_URL must match.
    uvicorn.run(app, port=int(os.environ.get("OMICS_API_PORT") or 8000))
