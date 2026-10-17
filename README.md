# omics-agent

Find public omics datasets with a plain-English question.

```sh
uv sync
cp .env.example .env   # add ANTHROPIC_API_KEY
uv run omics "I work on lung fibrosis in humans and need single-cell and proteomics data from patients and healthy controls"
uv run omics --json "..."   # machine-readable output for agents
```

Web UI (two terminals):

```sh
uv run omics-api                 # streaming API on http://localhost:8000 (docs at /docs)
cd web && npm ci && npm run dev  # http://localhost:3000
```

MCP server (stdio), for Claude Code or any MCP client:

```sh
claude mcp add locus -- uv run --directory "$PWD" omics-mcp
```

It exposes eight tools. Every tool is read-only.

| Tool | What it returns |
|---|---|
| `search_datasets(question)` | The full graded search, which takes about a minute. It returns the plan; each dataset's grade, checks, case/control counts, libraries per assay, paper and download plan; and groups of datasets from the same paper. |
| `plan_search(question)` | Topic terms, organism, the assays that can answer the question, the assays that must come from the same samples, and notes on what each method can and cannot measure. It does not search. |
| `find_datasets(query, repositories?, organism?, limit?)` | A fast keyword and semantic lookup in the local index, without grading. |
| `get_dataset(accession)` | The stored record: title, description, repository, organism, sample count, linked paper and download plan. |
| `geo_sample_groups(accession, topic)` | Case/control sample counts and libraries per assay for one GEO series. For example, GSE36892 has 4 + 4 Ribo-seq libraries but only 2 + 2 RNA-seq libraries. |
| `get_methods(accession)` | The methods section of the linked paper, one paragraph at a time, from Europe PMC open-access full text. If no full text is available, it says so. |
| `get_download_plan(accession)` | Shell commands that fetch the dataset's processed files and raw reads, for the user to review before running. |
| `get_samplesheet(accession, topic)` | An nf-core/riboseq samplesheet for one GEO series: a CSV with each sample's FASTQ links from ENA, the contrasts between conditions, and a README that says which samples were paired or left out, and why. |

How it works:

1. Claude Haiku 5.5 turns the question into search terms (with synonyms such as IPF), an organism, the data types wanted, and whether controls are needed. The plan is cached per question, so the same question always runs the same search.
2. The CLI searches the live APIs of GEO (bulk RNA-seq, and single-cell with a single-cell filter), PRIDE (proteomics), and CELLxGENE (single-cell).
3. For each GEO study, it downloads the sample records, and Haiku picks which field separates disease samples from controls. Code then counts the samples, so counts such as "case 19 · control 20" come from the records, not the model. CELLxGENE control facts come from its disease labels.
4. Haiku answers four checks per dataset (same disease, patient material, requested data type, controls). Counted facts override the model's answers. Code computes the grade: strong if every check passes, partial if the disease matches but a check fails.
5. Results from different repositories that share a paper (PubMed ID or DOI, linked through Europe PMC) are shown together.

Accessions come only from the repository APIs, never from the model. A quote is shown only if it appears word for word in the dataset metadata.

The web interface is built on [PRIDE Map](https://github.com/FlynnLachendro/pridemap) (MIT) by Flynn Lachendro.
