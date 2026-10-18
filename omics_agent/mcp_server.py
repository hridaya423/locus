from dataclasses import asdict

from dotenv import load_dotenv
import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

load_dotenv()

from . import agent, assay, browse, design_check, everywhere, index, lists, paper, person, preview, qc, record, resolve, subset, table, volcano, why  # noqa: E402  (needs the API key loaded first)
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
        "nf-core/riboseq run. To pick samples by experimental factor (disease, tissue, treatment) and download only those, "
        "use filter_samples. Accessions come only from the repositories; never invent one."
        "nf-core/riboseq run. list_files then preview_file look inside a dataset's processed tables without downloading them. Accessions come only from the repositories; never invent one."
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
def why_matched(accession: str, terms: list[str], quote: str = "") -> dict:
    """Where search terms (and, optionally, a quote) appear in one dataset's own record, to check why a search returned
    it. Case-insensitive, whole-word, with plurals and hyphen variants (scRNA-seq, scRNAseq, single-cell RNA sequencing).
    Returns each term's count and first place, and the matched spans by field (Title, Summary, Overall design,
    protocols, facts) with character offsets into that field's text. A term with a count of zero is not in the
    record's text, so the search found the dataset by other means. `quote` is an exact phrase, such as a search
    result's evidence."""
    return why.why(accession, terms, quote) or {"accession": accession, "error": "not in the locus index"}


@mcp.tool(annotations=READ_ONLY)
def classify_assays(accession: str) -> dict:
    """What a dataset really measured, read from its protocols, reagents, antibodies and instruments rather than the
    author's label: droplet vs plate single-cell, Ribo-seq vs TIS-seq (harringtonine/lactimidomycin), TMT, DIA,
    phospho enrichment, immunopeptidomics (W6/32), organelle IP and more. Each call quotes the sentence and record field
    it came from; for GEO footprint studies it lists which samples are which library, how the authors labelled them,
    and the methods sentence saying where matched RNA-seq and Ribo-seq samples were split."""
    return assay.classify(accession) or {"accession": accession, "error": "not in the index"}


@mcp.tool(annotations=READ_ONLY)
def sample_qc(accession: str) -> dict:
    """Quality from the records: reads and bases per sample from the ENA run table, grouped by library type, with
    samples far from their group's median flagged; and the authors' own QC criteria (trimming, length selection, rRNA
    filtering, thresholds) quoted from the record's processing text and the paper's open-access methods, with fields."""
    return qc.sample_qc(accession)


@mcp.tool(annotations=READ_ONLY)
def get_table(accession: str) -> dict:
    """The finished, processed counts table locus can hand over for a GEO RNA-seq series (NCBI-generated raw counts,
    one pipeline for all of GEO): genes, samples, total reads, genome build, source URL and checksum. The zip with
    counts.tsv, samples.tsv, features.tsv and manifest.json is served at /table/<accession>/download by the locus API."""
    return table.summary(accession)


@mcp.tool(annotations=READ_ONLY)
def first_look(accession: str, factor: str = "", case: list[str] | None = None, control: list[str] | None = None, top: int = 25, pathways: bool = False) -> dict:
    """A first differential look at a GEO RNA-seq series from its fetched counts, or at a Metabolomics Workbench study
    (accession ST…) from its mwTab metabolite table (feature: metabolite; 1.5-fold cut-off): features up and down between
    two groups of samples defined by one sample characteristic (factor) and its levels. Without a factor, locus picks
    the characteristic with a control-like level. Returns group sizes, the method, counts of significant genes, the
    top genes each way with log2 fold change, -log10 p and BH q, and paper_check: the genes the dataset's paper names
    (Europe PMC full text or text-mined mentions) and where each lands here. With pathways=True, also the Reactome pathways
    Enrichr finds over-represented among the top 200 genes each way. A screen, not DESeq2."""
    result = volcano.compare(accession, factor, case, control) if factor else volcano.compare(accession)
    if not result.get("available"):
        return {k: v for k, v in result.items() if k != "groups"} | {"factors": result.get("groups", {}).get("factors", [])}
    genes_measured = result["feature"] == "gene"
    check = volcano.paper_genes(accession, result) if genes_measured else {"available": False, "reason": "a metabolite table; the paper check reads genes"}
    if pathways and genes_measured:
        try:
            result["pathways"] = volcano.pathways(result)
        except httpx.HTTPError as error:
            result["pathways"] = {"available": False, "reason": f"Enrichr did not answer: {error}"}
    genes = result.pop("genes")
    result.pop("groups")
    result["paper_check"] = {k: v for k, v in check.items() if k != "genes"} | {"genes": [
        {k: g[k] for k in ("gene", "log2fc", "q", "significant", "where", "sentence")} for g in check.get("genes", [])[:top]]}
    columns = [result["feature"], "log2_fold_change", "minus_log10_p", "q"]
    result["top_up"] = [dict(zip(columns, g)) for g in genes if g[3] < result["q"] and g[1] >= result["lfc"]][:top]
    result["top_down"] = [dict(zip(columns, g)) for g in genes if g[3] < result["q"] and g[1] <= -result["lfc"]][:top]
    return result


@mcp.tool(annotations=READ_ONLY)
def gene_everywhere(gene: str, accessions: list[str], hint: str = "") -> dict:
    """One gene across several GEO RNA-seq datasets: in each, its log2 fold change and BH q between the cases and the
    controls (the characteristic with a control-like level; the case level preferring words of `hint`, e.g. the disease),
    from NCBI's counts or the authors' own table. One row per dataset, with the reason when a dataset cannot answer."""
    return everywhere.gene_everywhere(gene, accessions, hint)


@mcp.tool(annotations=READ_ONLY)
def check_design(accession: str, factor: str = "", case: list[str] | None = None, control: list[str] | None = None) -> dict:
    """The traps an expert checks before trusting a case/control comparison in a dataset: the condition going with a
    batch-like characteristic (plate, date, institution; Cramér's V), unbalanced characteristics (sex, age, smoking),
    cases and controls from different tissues, groups under 3, each with its cross-table; batch-like characteristics
    found balanced; and the smallest fold change detectable at p < 0.05 with 80% power from the expression table."""
    return design_check.check(accession, factor or None, case, control)


@mcp.tool(annotations=READ_ONLY)
def check_list(items: str, accession: str = "", across_datasets: list[str] | None = None, hint: str = "") -> dict:
    """A pasted gene or protein list (symbols, UniProt accessions or FASTA headers) checked against MitoCarta 3.0:
    how many are mitochondrial (the recovery an organelle IP should show), their sub-compartments, evidence and
    pathways; with a GEO accession, also each item's rank, log2 fold change and q in that dataset's first look and
    the overlap with its significant genes against chance (hypergeometric p). With across_datasets (up to 40 GEO
    accessions; hint words such as the disease pick each one's case group), the same overlap in every dataset."""
    result = lists.check(items, accession)
    if across_datasets:
        result["across"] = lists.across(items, across_datasets, hint)
    return result


@mcp.tool(annotations=READ_ONLY)
def browse_datasets(field: str, value: str, source: str = "", offset: int = 0) -> dict:
    """Every locus dataset that shares one stated value from a dataset record: an organism ('Homo sapiens'), an
    instrument ('Illumina NovaSeq 6000', 'Q Exactive HF-X'), a data type or a keyword. Returns the total, counts per
    repository and 50 datasets per page, newest first, with where the value was matched."""
    return browse.browse(field, value, source, offset)


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
def filter_samples(accession: str, filters: dict[str, list[str]], text: str = "", limit: int = 200) -> dict:
    """Pick samples of one GEO, ENA or ArrayExpress dataset by the levels of its experimental factors. `filters` maps a
    factor to the levels wanted, for example {"diagnosis": ["IPF", "Control"], "Sex": ["female"]}: levels of one factor
    combine with OR, factors with AND. `text` keeps rows with that text in any cell. Call it with empty `filters` to list
    the factors and their levels. Returns the matching sample rows (at most `limit`), the count of every level of every
    factor inside the selection (a factor's own filter is left out of its counts; `unstated` counts samples with no value
    for the factor), and the commands that download only those samples' files, with a note on what they leave out and the
    record fields they were read from. `commands` is null when the repository does not link samples to files; use
    get_download_plan then. `truncated` says that `rows` holds fewer rows than `samples`."""
    try:
        found = subset.select(accession, filters, text)
    except (LookupError, ValueError) as error:
        return {"accession": accession, "error": str(error)}
    sheet = subset.table(accession)
    return {
        "accession": accession, "samples": found["samples"], "total": found["total"], "columns": sheet["columns"],
        "rows": [sheet["rows"][i] for i in found["rows"][:limit]], "truncated": len(found["rows"]) > limit,
        "unstated": found["unstated"],
        "counts": found["counts"], "downloads": found["downloads"],
    }


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


MAX_LISTED = 200


@mcp.tool(annotations=READ_ONLY)
def list_files(accession: str) -> dict:
    """The files a dataset's repository lists, to find a `file_name` for preview_file: name, group, size in bytes, whether
    the repository or locus counts it as processed, and whether preview_file can read it. Processed files come first; at
    most 200 are returned and `total` is the full count."""
    if not (row := record._row(accession)):
        return {"accession": accession, "error": "not in the locus index"}
    files = sorted(record.raw(accession, row).files, key=lambda f: not f["processed"])
    return {"accession": accession, "total": len(files), "files": [
        {"name": f["name"], "group": f["group"], "bytes": f["bytes"], "processed": f["processed"], "previewable": preview.previewable(f, accession)}
        for f in files[:MAX_LISTED]]}


@mcp.tool(annotations=READ_ONLY)
def preview_file(accession: str, file_name: str) -> dict:
    """Look inside one processed file of a dataset without downloading it: the columns with their inferred types and
    numeric ranges, the first 20 rows, and the column count. Works for delimited tables (tab, comma, semicolon or space separated, gzipped or not),
    GEO series matrices, mzTab, small xlsx files, and the main table inside a search-engine zip (MaxQuant's
    proteinGroups.txt in a PRIDE txt.zip; `member` names it), read by two Range requests. Reads only the first 256 KB; `bytes_read`, `size` and
    `url` say what was read, and `total_rows` is null unless the whole file was read. When the columns are samples, each
    column carries its group (for example diagnosis: IPF or Control) from the dataset's sample table. `file_name` is a
    name from list_files, for example "GSE86618_34816genes-540cells-tpm.txt.gz". `samples` says whether the columns
    matched the sample table's accessions or titles."""
    try:
        return preview.preview(accession, file_name)
    except (LookupError, ValueError) as error:
        return {"accession": accession, "file": file_name, "error": str(error)}
    except httpx.HTTPError as error:
        return {"accession": accession, "file": file_name, "error": f"The repository did not answer: {error}"}
@mcp.tool(annotations=READ_ONLY)
def resolve_id(identifier: str) -> dict:
    """The locus page for an accession, sample or run, study, PMID, PMCID or DOI, or a link to one (for example GSE36892,
    GSM2306940, SRR4216351, SRP011987, PXD012345, E-MTAB-6149, PMID:33331123, 10.15252/msb.20209844). Returns the page
    path (/d/… for a dataset or sample, /p/… for a paper), the kind of record, and where the match was read. A study
    that came from a GEO series opens that series. Says so when locus does not have it."""
    try:
        return resolve.resolve(identifier) or {"error": f"{identifier} is not an identifier; use search_datasets or find_datasets"}
    except (LookupError, httpx.HTTPError) as error:
        return {"error": str(error) if isinstance(error, LookupError) else f"A repository did not answer: {error}"}


@mcp.tool(annotations=READ_ONLY)
def get_paper(id: str, dataset_offset: int = 0) -> dict:
    """Facts about one paper from Europe PMC, by PMID, PMCID or DOI: title, authors, journal, year, abstract, the data
    availability statement quoted from the open-access full text (or why none) with each accession in it marked deposited
    or reused and whether locus holds it, supplementary files with sizes and download links, and the locus datasets of the
    paper (deposited, reused, or citing it). Datasets that only cite the paper come 100 at a time from `dataset_offset`;
    `cited_total` counts them. `sources` holds the URL each fact came from. Returns an error object when Europe PMC cannot answer."""
    try:
        return paper.paper(id, dataset_offset)
    except LookupError as error:
        return {"error": str(error)}
    except httpx.HTTPError as error:
        return {"error": f"Europe PMC did not answer: {error}"}


@mcp.tool(annotations=READ_ONLY)
def find_cited_paper(citation: str) -> dict:
    """The paper an informal citation names, such as 'Philippe 2020 PNAS LARP1' or 'Ingolia et al. 2011 ribosome
    profiling': first author's surname, year and at least one word of its title, matched in Europe PMC. Returns its
    title, journal, year, authors, locus path and up to 6 locus datasets that cite it, or an error when nothing matches."""
    try:
        return paper.cite(citation) or {"error": "no paper matches a surname, a year and a title word in this text"}
    except httpx.HTTPError as error:
        return {"error": f"Europe PMC did not answer: {error}"}


@mcp.tool(annotations=READ_ONLY)
def get_person(name: str) -> dict:
    """A dataset contributor's track record: their papers in Europe PMC, newest first (up to 100; `matched` counts all),
    found by surname and initials, so a common name mixes people. Per paper: journal, year, preprint or not, citations,
    open access, supplementary files, last author or not, and the locus datasets it deposited or cites. Also the journals
    they publish in, with counts. Pass the name as a record shows it, for example 'Carson C Thoreen'."""
    try:
        return person.person(name)
    except httpx.HTTPError as error:
        return {"error": f"Europe PMC did not answer: {error}"}


def main() -> None:
    mcp.run()
