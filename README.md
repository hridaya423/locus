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
claude mcp add omics-agent -- uv run --directory "$PWD" omics-mcp
```

It exposes two tools: `search_datasets(question)` runs the full search, and `geo_sample_groups(accession, topic)` counts disease and control samples in one GEO series.

How it works:

1. Claude Haiku 5.5 turns the question into search terms (with synonyms such as IPF), an organism, the data types wanted, and whether controls are needed. The plan is cached per question, so the same question always runs the same search.
2. The CLI searches the live APIs of GEO (bulk RNA-seq, and single-cell with a single-cell filter), PRIDE (proteomics), and CELLxGENE (single-cell).
3. For each GEO study, it downloads the sample records, and Haiku picks which field separates disease samples from controls. Code then counts the samples, so counts such as "case 19 · control 20" come from the records, not the model. CELLxGENE control facts come from its disease labels.
4. Haiku answers four checks per dataset (same disease, patient material, requested data type, controls). Counted facts override the model's answers. Code computes the grade: strong if every check passes, partial if the disease matches but a check fails.
5. Results from different repositories that share a paper (PubMed ID or DOI, linked through Europe PMC) are shown together.

Accessions come only from the repository APIs, never from the model. A quote is shown only if it appears word for word in the dataset metadata.

The web interface is built on [PRIDE Map](https://github.com/FlynnLachendro/pridemap) (MIT) by Flynn Lachendro.
