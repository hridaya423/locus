import json
import os
import queue
import threading
from dataclasses import asdict
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints

load_dotenv()

from . import agent, design, record, sources, subset  # noqa: E402  (needs the API key loaded first)

app = FastAPI(title="omics-agent")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


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
        while True:
            event = events.get()
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
    return design.design(accession, source) or {}


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


@app.get("/record/{accession}")
def dataset_record(accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """Everything the repository's own page shows for one dataset: texts, facts, people, papers, links, samples and files."""
    if not (found := record.record(accession)):
        raise HTTPException(404, f"{accession} is not in the index.")
    return found


@app.get("/record/{accession}/samples/{sample}")
def sample_record(accession: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$"), sample: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")) -> dict:
    """One sample as its repository's sample page shows it: characteristics, protocols, facts, links and files."""
    try:
        found = record.sample(accession, sample)
    except LookupError as error:
        raise HTTPException(404, str(error))
    if not found:
        raise HTTPException(404, f"locus has no sample pages for {accession}.")
    return found


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
