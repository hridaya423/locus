from dataclasses import asdict

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

load_dotenv()

from . import agent, index, table, volcano  # noqa: E402  (needs the API key loaded first)
from .sources import Dataset, download_plan, paper_methods  # noqa: E402

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

mcp = MCPServer(
    "locus",
    instructions=(
        "locus finds public omics datasets for a research question and checks that they fit. "
        "Start with search_datasets for a graded answer, or find_datasets for a fast unscored lookup. "
        "Use plan_search to learn which assays can answer a question before searching. "
        "To check one dataset, use get_dataset, then geo_sample_groups for counted case/control samples and "
        "libraries per assay, and get_methods for the paper's methods text (assay identity, how samples were "
        "matched, the authors' QC). get_download_plan and get_samplesheet prepare the data for download and for an "
        "nf-core/riboseq run. Accessions come only from the repositories; never invent one."
    ),
)


def _dataset(accession: str) -> Dataset | None:
    found = index.load([accession])
    return found[0] if found else None


def _record(d: Dataset) -> dict:
    return {k: v for k, v in asdict(d).items() if k != "text"} | {"description": d.text}


@mcp.tool(annotations=READ_ONLY)
def search_datasets(question: str, limit_per_repository: int = 60) -> dict:
    """Find public omics datasets for a research question in plain English, graded and checked. Takes about a minute.

    Searches GEO, ArrayExpress, ENA, PRIDE, MassIVE, MetaboLights, CELLxGENE and more. Returns the search plan and
    each relevant dataset with a grade (strong or partial), checks (same topic, patient material, requested data type,
    controls), case and control sample counts and libraries per assay read from the sample records where available,
    a reason, a verbatim quote from the dataset metadata, the linked paper, and a download plan. Also returns groups
    of datasets from the same paper.
    """
    return agent.run(question, limit_per_repository)


@mcp.tool(annotations=READ_ONLY)
def plan_search(question: str) -> dict:
    """Turn a research question into a search plan without searching: the topic terms and synonyms, organism,
    assays that can answer it, assays that must come from the same samples, and notes on what each method can
    and cannot measure. Fast; use it to learn which experiment types fit before searching."""
    return agent.plan(question)


@mcp.tool(annotations=READ_ONLY)
def find_datasets(query: str, repositories: list[str] | None = None, organism: str = "", limit: int = 20) -> list[dict]:
    """Fast lookup in the local index of public omics datasets by keywords and meaning, without grading or sample
    counts. `repositories` limits the search (for example ["GEO", "PRIDE"]); omit it to search all of them.
    `organism` is a Latin species name such as "Homo sapiens"."""
    sources = repositories or list(agent.ARCHIVES)
    found = index.load(index.search(query, [query], sources, organism, limit))
    return [_record(d) | {"description": d.text[:500]} for d in found]


@mcp.tool(annotations=READ_ONLY)
def get_dataset(accession: str) -> dict:
    """Everything stored about one dataset (for example GSE36892 or PXD012345): title, repository, organism, data
    type, sample count, date, full description, linked paper, and a download plan."""
    d = _dataset(accession)
    if not d:
        return {"accession": accession, "error": "not in the locus index"}
    record = _record(d)
    agent.add_papers([record])
    return record | {"download_plan": download_plan(d.accession, d.source, d.url)}


@mcp.tool(annotations=READ_ONLY)
def geo_sample_groups(accession: str, topic: str) -> dict:
    """Count case and control samples in one GEO series (for example GSE36892) from its sample records, and how many
    libraries of each assay fall in each group, so unmatched assays show up (for example 4 Ribo-seq but 2 RNA-seq
    libraries per condition). `topic` is the condition that counts as a case, for example "Torin1 mTOR inhibition"."""
    d = _dataset(accession) or Dataset(accession, "GEO", "", "", "", None, "", "")
    agent._geo_facts(topic, d)
    return d.facts or {"accession": accession, "error": "no sample records found"}


@mcp.tool(annotations=READ_ONLY)
def get_methods(accession: str) -> dict:
    """The methods section of the paper linked to a dataset, one paragraph at a time, from its open-access full
    text in Europe PMC. Use it to check which assay was really run (for example Ribo-seq versus TIS-seq), how
    samples were split for matched assays, and the QC the authors applied. Says so when no full text is available."""
    d = _dataset(accession)
    if not d or not d.papers:
        return {"accession": accession, "available": False, "reason": "no linked paper"}
    return {"accession": accession} | paper_methods(d.papers[0])


@mcp.tool(annotations=READ_ONLY)
def get_table(accession: str) -> dict:
    """The finished, processed counts table locus can hand over for a GEO RNA-seq series (NCBI-generated raw counts,
    one pipeline for all of GEO): genes, samples, total reads, genome build, source URL and checksum. The zip with
    counts.tsv, samples.tsv, features.tsv and manifest.json is served at /table/<accession>/download by the locus API."""
    return table.summary(accession)


@mcp.tool(annotations=READ_ONLY)
def first_look(accession: str, factor: str = "", case: list[str] | None = None, control: list[str] | None = None, top: int = 25) -> dict:
    """A first differential-expression look at a GEO RNA-seq series from its fetched counts: genes up and down between
    two groups of samples defined by one sample characteristic (factor) and its levels. Without a factor, locus picks
    the characteristic with a control-like level. Returns group sizes, the method, counts of significant genes, the
    top genes each way with log2 fold change, -log10 p and BH q, and paper_check: the genes the dataset's paper names
    (Europe PMC full text or text-mined mentions) and where each lands here. A screen, not DESeq2."""
    result = volcano.compare(accession, factor, case, control) if factor else volcano.compare(accession)
    if not result.get("available"):
        return result
    check = volcano.paper_genes(accession, result)
    genes = result.pop("genes")
    result.pop("groups")
    result["paper_check"] = {k: v for k, v in check.items() if k != "genes"} | {"genes": [
        {k: g[k] for k in ("gene", "log2fc", "q", "significant", "says", "agrees", "where", "sentence")} for g in check.get("genes", [])[:top]]}
    columns = ["gene", "log2_fold_change", "minus_log10_p", "q"]
    result["top_up"] = [dict(zip(columns, g)) for g in genes if g[1] > 0][:top]
    result["top_down"] = [dict(zip(columns, g)) for g in genes if g[1] < 0][:top]
    return result


@mcp.tool(annotations=READ_ONLY)
def get_download_plan(accession: str) -> dict:
    """Shell commands that fetch a dataset's processed files and raw reads, for the user to review and run."""
    d = _dataset(accession)
    if not d:
        return {"accession": accession, "error": "not in the locus index"}
    return {"accession": accession, "plan": download_plan(d.accession, d.source, d.url)}


@mcp.tool(annotations=READ_ONLY)
def get_samplesheet(accession: str, topic: str) -> dict:
    """An nf-core/riboseq samplesheet for one GEO series, ready for a pipeline run: the samplesheet CSV with each
    sample's FASTQ links from ENA, the contrasts between conditions, and a README that says which samples were paired
    or left out and why. `topic` is the condition that counts as a case, for example "Torin1 mTOR inhibition"."""
    return {"accession": accession, "files": agent.samplesheet_files(accession, topic)}


@mcp.tool(annotations=READ_ONLY)
def compare_datasets(a: str, b: str, topic: str) -> dict:
    """Whether two datasets can be used together: "pool" (reprocess both and analyse as one, study as a batch term),
    "effects" (analyse each on its own and compare fold changes and hits), or "no". Returns the verdict, the deciding
    reason, one row per fact compared (organism, molecular layer, technology, both case and control groups in each,
    contrast, platform, material, tissue, genome build, group sizes) and the next steps. `topic` is the condition that
    counts as a case, for example "Torin1 mTOR inhibition"."""
    try:
        return asdict(agent.compare_datasets(a, b, topic))
    except LookupError as error:
        return {"error": str(error)}


def main() -> None:
    mcp.run()
