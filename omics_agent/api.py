import json
import os
import queue
import re
import threading
from dataclasses import asdict
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
import httpx
from pydantic import BaseModel, Field, StringConstraints

load_dotenv()

from . import agent, assay, browse, design, design_check, everywhere, lists, paper, preview, qc, record, resolve, sources, subset, table, volcano, why  # noqa: E402  (needs the API key loaded first)

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
               control: Annotated[list[str] | None, Query()] = None, within_factor: str | None = None, within: str | None = None) -> dict:
    """Each gene's change between two sample groups and its significance, from the fetched counts; the method is in the result."""
    try:
        return volcano.compare(accession, factor, case, control, (within_factor, within) if within_factor and within else None)
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(502, f"The table could not be read: {error}") from error


@app.get("/first-look/{accession}/paper")
def first_look_paper(accession: str = Path(pattern=r"^GSE\d+$"), factor: str | None = None, case: Annotated[list[str] | None, Query()] = None,
                     control: Annotated[list[str] | None, Query()] = None) -> dict:
    """The genes the dataset's paper names, and where each lands in the same comparison."""
    look = volcano.compare(accession, factor, case, control)
    return volcano.paper_genes(accession, look) if look.get("available") else {"available": False, "reason": look.get("reason")}


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


@app.get("/files/{accession}")
def files(accession: str = Path(pattern=r"^PXD\d{6}$")) -> dict:
    """The author-processed files of a PRIDE project and a summary of its raw files."""
    return sources.pride_files(accession)


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


@app.get("/paper/{identifier:path}")
def paper_page(identifier: str, offset: int = Query(0, ge=0)) -> dict:
    """A paper's title, authors, abstract, data availability statement, supplementary files and the locus datasets that cite it,
    `offset` datasets in."""
    try:
        return paper.paper(identifier, offset)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except httpx.HTTPError:
        raise HTTPException(502, "Europe PMC did not answer. Please try again.")


def main() -> None:
    import uvicorn

    from . import index

    # Load the embedding model and vectors before serving, so the first search does not pay for it.
    index.semantic_search("warm up", ["GEO"], "", 1)
    # OMICS_API_PORT lets the API move off 8000 when that port is taken; the web app's OMICS_API_URL must match.
    uvicorn.run(app, port=int(os.environ.get("OMICS_API_PORT") or 8000))
