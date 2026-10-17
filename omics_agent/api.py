import json
import os
import queue
import threading
from dataclasses import asdict
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints

load_dotenv()

from . import agent, design, record, sources, table, volcano  # noqa: E402  (needs the API key loaded first)

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


@app.get("/table/{accession}")
def processed_table(accession: str = Path(pattern=r"^GSE\d+$")) -> dict:
    """Whether locus can hand over the finished counts table for a GEO series, its size and its source."""
    return table.summary(accession)


@app.get("/table/{accession}/download")
def processed_table_zip(accession: str = Path(pattern=r"^GSE\d+$")) -> Response:
    """counts, sample metadata, gene annotation and a manifest, as one zip."""
    if not table.summary(accession)["available"]:
        raise HTTPException(404, f"No processed table for {accession}.")
    return Response(table.bundle(accession), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{accession}_locus_table.zip"'})


@app.get("/first-look/{accession}")
def first_look(accession: str = Path(pattern=r"^GSE\d+$"), factor: str | None = None, case: Annotated[list[str] | None, Query()] = None,
               control: Annotated[list[str] | None, Query()] = None) -> dict:
    """Each gene's change between two sample groups and its significance, from the fetched counts; the method is in the result."""
    return volcano.compare(accession, factor, case, control) if factor else volcano.compare(accession)


@app.get("/first-look/{accession}/paper")
def first_look_paper(accession: str = Path(pattern=r"^GSE\d+$"), factor: str | None = None, case: Annotated[list[str] | None, Query()] = None,
                     control: Annotated[list[str] | None, Query()] = None) -> dict:
    """The genes the dataset's paper names, and where each lands in the same comparison."""
    look = volcano.compare(accession, factor, case, control) if factor else volcano.compare(accession)
    return volcano.paper_genes(accession, look) if look.get("available") else {"available": False, "reason": look.get("reason")}


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
