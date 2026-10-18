# locus

Find public omics datasets with a plain-English question, and see from the authors' own records whether each dataset fits.

Researchers often spend days searching GEO, PRIDE and other repositories for data that already exists. Keyword search misses studies, and repository fields do not say whether the samples are matched, how many controls there are, or which assay was really used. locus searches 891,000 datasets in 18 repositories. It counts the case and control samples from the sample records, grades each dataset against the question, and writes the input files for the analysis pipeline.

## What it does

- **Search.** It plans the search from your question, with synonyms, organism, the assays that can answer it, and the assays that must come from the same samples. Then it searches a local index of 18 repositories with keywords and embeddings.
- **Count.** For each GEO study, it reads the sample records and counts the case and control samples and the libraries per assay. A model chooses which record field marks case and control. Code does the counting, so a model never writes a number.
- **Grade.** It checks four things for each dataset: the topic, the sample material, the data type and the controls. Counted facts override the model. A dataset that meets every requirement is "usable as is". A dataset that misses one is a "close match", and locus shows which check failed.
- **Hand off.** For each result, it gives download commands. For GEO Ribo-seq studies, it also writes an [nf-core/riboseq](https://nf-co.re/riboseq) samplesheet (see [Samplesheet export](#samplesheet-export)).
- **Read each dataset.** Every dataset has its own locus page. It shows what was measured, read from the methods with the sentence that says so. It shows the samples, with cases and controls marked, people counted, and charts that filter the table and the download commands. It shows quality from the run table and the authors' own QC, and previews processed files, including the protein table inside a PRIDE zip. For GEO RNA-seq and Metabolomics Workbench studies, it adds a first look: a volcano plot, the paper's genes on it, pathways, and a design check. Each page lists the repository API requests it was read from.
- **Open anything.** An accession, PMID, DOI or informal citation opens its page. Papers and contributors have pages. One gene, or a whole list, can be checked across every dataset a search found.
- **Serve agents.** An MCP server gives the same functions to Claude Code or any MCP client (25 tools).

How each part is checked, with its failures: [`docs/evaluation.md`](docs/evaluation.md).

Accessions come only from repository records, never from the model. A quote is shown only if it appears word for word in the dataset metadata.

## Example

Question: "Matched RNA-seq and Ribo-seq before and after mTOR inhibition".

- The two *Nature* 2012 datasets on this topic are GSE36892 (Thoreen et al.) and GSE35469 (Hsieh et al.). locus ranks them 2nd and 7th.
- GEO DataSets search and OmicsDI return no results for the same plain-English question.
- locus counts GSE36892 as 4 + 4 Ribo-seq and 2 + 2 RNA-seq libraries, and warns that 4 Ribo-seq libraries have no matching RNA-seq. A chatbot with web search guessed 8 + 8 matched libraries for the same study.
- We recounted four studies by hand from the GEO records. All four counts were exact.

The raw outputs and the hand recounts are in [`docs/evidence/phase0/REPORT.md`](docs/evidence/phase0/REPORT.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/), Node 20+ and an Anthropic API key.

```sh
uv sync
cp .env.example .env    # add ANTHROPIC_API_KEY
uv run omics "I work on lung fibrosis in humans and need single-cell and proteomics data from patients and healthy controls"
uv run omics --json "..."    # machine-readable output
```

Without an Anthropic key, locus can run on a local model served through an OpenAI-compatible API, such as vLLM. Set `LOCAL_LLM_URL` (for example `http://localhost:8000/v1`) and `LOCAL_LLM_MODEL` in `.env`. The server must support JSON-schema structured output. Results then depend on that model and have not been checked against the Claude runs in `docs/evidence/`.

Without a local index, locus searches the live APIs of GEO, PRIDE and CELLxGENE only. To search all 18 repositories, build the index first.

### Build the index

The index is a SQLite file, `data/omics.db` (about 1.3 GB), with a full-text index. Each harvester is resumable and writes to the same file.

```sh
uv run python -m omics_agent.harvest                # GEO, all series; needs NCBI_API_KEY in .env
uv run python -m omics_agent.harvest_pride          # PRIDE and CELLxGENE
uv run python -m omics_agent.harvest_arrayexpress   # ArrayExpress, without copies of GEO series
uv run python -m omics_agent.harvest_omicsdi        # 14 repositories through OmicsDI, and Metabolomics Workbench
uv run python -m omics_agent.harvest_ena            # ENA studies with reads and no GEO series
uv run python -c "from omics_agent import store; store.rebuild_fts(store.connect())"
```

Embeddings are optional. Without them, locus uses keyword search only. `embed.py` embeds every dataset with `NeuML/pubmedbert-base-embeddings` on a Hugging Face Inference Endpoint, and writes `data/vectors.npy` (about 1.3 GB). It needs `HF_TOKEN`. The endpoint costs money while it runs, and the script deletes it when it finishes.

```sh
uv run python -m omics_agent.embed
```

### Web app

Run these in two terminals:

```sh
uv run omics-api                    # streaming API on http://localhost:8000 (docs at /docs)
cd web && npm ci && npm run dev     # http://localhost:3000
```

The web app calls `/api` on its own origin, and Next.js forwards it to port 8000, so the app also works through a tunnel such as ngrok.

If port 8000 is taken, set `OMICS_API_PORT` in `.env` and point the web app at it with `OMICS_API_URL`. To open the dev server from another machine by its IP address, list that address in `EXTRA_DEV_ORIGINS`:

```sh
OMICS_API_PORT=8010 uv run omics-api
cd web && OMICS_API_URL=http://localhost:8010 EXTRA_DEV_ORIGINS=152.78.149.61 npm run dev
```

### MCP server

```sh
claude mcp add locus -- uv run --directory "$PWD" omics-mcp
```

It has eight tools. Every tool is read-only.

| Tool | What it returns |
|---|---|
| `search_datasets(question)` | The full graded search, which takes about a minute. It returns the plan; each dataset's grade, checks, case/control counts, libraries per assay, paper and download plan; and groups of datasets from the same paper. |
| `plan_search(question)` | Topic terms, organism, the assays that can answer the question, the assays that must come from the same samples, and notes on what each method can and cannot measure. It does not search. |
| `find_datasets(query, repositories?, organism?, limit?)` | A fast keyword and semantic lookup in the local index, without grading. |
| `get_dataset(accession)` | The stored record: title, description, repository, organism, sample count, linked paper and download plan. |
| `geo_sample_groups(accession, topic)` | Case/control sample counts and libraries per assay for one GEO series. |
| `get_methods(accession)` | The methods section of the linked paper, one paragraph at a time, from Europe PMC open-access full text. If no full text is available, it says so. |
| `get_download_plan(accession)` | Shell commands that fetch the dataset's processed files and raw reads, for you to review before you run them. |
| `get_samplesheet(accession, topic)` | The nf-core/riboseq samplesheet, contrasts and README for one GEO series. |

## Samplesheet export

For a GEO study with Ribo-seq or TIS-seq libraries, locus writes a zip with three files for nf-core/riboseq 1.2.0. locus does not run the pipeline. You run it on your own compute.

- `samplesheet.csv` has one row for each sequencing run, with the GSM sample, the FASTQ links from ENA, the assay type (`riboseq`, `rnaseq` or `tiseq`), the condition, and each characteristic that varies in the study.
- `contrasts.csv` lists the translational efficiency comparisons for anota2seq. Each contrast compares case with control inside one level of a crossed factor, such as genotype.
- `README.txt` lists the labels to check, the libraries per condition, each contrast that was written or refused and why, the unpaired libraries, and the samples that were left out.

The pipeline gives a wrong result, not an error, when the pairs or conditions are wrong. So the export is strict:

- A Ribo-seq library pairs with an RNA-seq library only if they have the same title after the assay words are removed, and the same characteristics. An ambiguous library stays unpaired, and its condition gets the suffix `_unpaired`, so no contrast includes it.
- A contrast is written only if each side has at least two pairs, and all the paired samples in a condition share one title stem. For example, GSE129816 puts untreated and Torin1-treated wild-type cells under "control". The export refuses that contrast and names the two title stems.

Get the zip from the result row in the web app, from `GET /samplesheet/{accession}?topic=...`, or from the `get_samplesheet` MCP tool. We checked the export on 10 GEO Ribo-seq studies. All 10 samplesheets pass the pipeline's input schema. The design is in [`docs/plans/2026-10-17-samplesheet-export-design.md`](docs/plans/2026-10-17-samplesheet-export-design.md).

## How it works

1. **Plan.** Claude Sonnet 5.5 turns the question into search terms with synonyms, an organism, the repositories, the assays wanted, the assays that must be matched, and notes on what each method can measure. The plan is cached per question, so the same question always runs the same search.
2. **Gather.** locus searches the local index with full-text search (SQLite FTS5, BM25) and embedding similarity, and fuses the two rankings with reciprocal rank fusion.
3. **Triage and screen.** Claude Haiku 5.5 scores the candidates from their titles and summaries, then answers the four checks for the best ones.
4. **Count.** For GEO studies, locus reads the sample records. If Gemma has curated the study, locus uses Gemma's sample groups instead. CELLxGENE controls come from its disease labels.
5. **Grade.** Counted facts override the model's answers. Code computes the grade.
6. **Group.** Results from different repositories that share a paper (PubMed ID, or a DOI mapped to a PubMed ID through Europe PMC) are shown together.

## Repositories

| Repository | Datasets | Holds |
|---|---|---|
| ENA | 461,758 | Raw sequencing studies with no GEO series |
| GEO | 298,702 | Sequencing and microarray studies |
| PRIDE | 42,111 | Mass-spectrometry proteomics |
| ArrayExpress | 21,604 | Sequencing and microarray studies not in GEO |
| EGA | 18,671 | Controlled-access human data |
| MassIVE (with GNPS) | 12,719 | Proteomics and metabolomics |
| iProX | 8,207 | Proteomics |
| NODE | 7,865 | Sequencing studies |
| Metabolomics Workbench | 4,639 | Metabolomics |
| MetaboLights | 3,534 | Metabolomics |
| jPOST | 3,179 | Proteomics |
| PeptideAtlas | 2,294 | Peptide identifications |
| CELLxGENE | 2,243 | Curated single-cell atlases |
| dbGaP | 1,316 | Controlled-access genotype and phenotype studies |
| EVA | 1,021 | Genetic variation |
| Panorama Public | 476 | Targeted proteomics |
| LINCS | 447 | Responses to drugs and genetic perturbations |
| Expression Atlas | 195 | Curated, reanalysed expression experiments |

For controlled-access data (EGA, dbGaP), locus links to the access request. It does not offer a download.

## Limits

- Sample counts are counts of sample records, not of patients. One patient can have several libraries.
- Counts exist for GEO and CELLxGENE only. PRIDE sample files (SDRF) are not read yet.
- The model labels can change between runs, so a count can appear in one run and be missing in the next.
- A broad search term can count related diseases as cases.
- Most ENA, EGA, MetaboLights, NODE and dbGaP records have no species, so they pass every species filter.
- Rows from OmicsDI and ENA have no linked paper.

## Layout

| Path | Contents |
|---|---|
| `omics_agent/agent.py` | The search: plan, gather, triage, screen, count, grade, group. The CLI, API and MCP server share it. |
| `omics_agent/samples.py` | GEO sample records, labels and counts |
| `omics_agent/samplesheet.py` | The nf-core/riboseq export |
| `omics_agent/index.py`, `store.py` | The local index and hybrid search |
| `omics_agent/harvest*.py`, `embed.py` | Index builders |
| `omics_agent/api.py`, `cli.py`, `mcp_server.py` | The three interfaces |
| `web/` | Next.js app |
| `docs/` | Plans and evidence |

Self-checks run without network access:

```sh
uv run python -m omics_agent.samples
uv run python -m omics_agent.samplesheet
```

## Licence

Apache 2.0 (see [`LICENSE`](LICENSE)). The web interface is built on [PRIDE Map](https://github.com/FlynnLachendro/pridemap) by Flynn Lachendro, under the MIT licence ([`web/LICENSE.pridemap`](web/LICENSE.pridemap)).
