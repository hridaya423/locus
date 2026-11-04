# locus

Find public omics datasets with a plain-English question, and see from the authors' own records whether each dataset fits.

Researchers often spend days searching the public archives (GEO for gene activity, PRIDE for proteins, and others) for data that already exists. Keyword search misses studies, and repository fields do not say whether the samples are matched, how many controls there are, or which assay was really used. locus searches 891,000 datasets in 18 repositories. It counts the case and control samples from the sample records, grades each dataset against the question, and writes the input files for the analysis pipeline.

## In plain words

**What it is for.** Scientists publish the raw measurements behind their papers in public archives: GEO (gene activity), PRIDE (proteins), ENA (raw sequencing reads) and others. A biologist with a question wants the right study from those archives, and then wants to know what it shows. locus takes the question in plain English, finds the studies, and for a gene-expression study runs the first analysis on an ordinary computer: which genes changed between the two conditions, with the figures a paper would show.

**What was not working.** Archive search is by keyword, so a question phrased differently from the authors' title misses the study. The archives do not say how many diseased and healthy samples a study has, or whether the samples are matched; people open each record and count by hand, and chatbots guess. And a found dataset is still raw files: turning them into "these genes changed" takes a pipeline, a cluster and someone who knows how to run both.

**What we made better.** locus plans the search from the question (synonyms, organism, the kinds of measurement that can answer it), counts cases and controls from the sample records with code, and shows which check a dataset fails. New in this hackathon: one click, or one command, takes a bulk RNA-seq study from the archive to counts per gene, a differential-expression table, five figures and a short written summary, in about three minutes on a laptop, with every tool version and every sample recorded so someone else can check it. Proteomics studies get sample counts read from their sample tables too, with "unknown" shown rather than a guess when the table does not say.

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

Without a local index, locus searches the live APIs of GEO, PRIDE and CELLxGENE only. To search all 18 repositories, download the index (about 1.8 GB) from the [data release](https://github.com/hridaya423/locus/releases/tag/data-2026-10-18):

```sh
mkdir -p data && cd data
base=https://github.com/hridaya423/locus/releases/download/data-2026-10-18
curl -LO $base/omics.db.gz -LO $base/vectors.npy -LO $base/vector_ids.json.gz -LO $base/pridemap.tar.gz -LO $base/SHA256SUMS
shasum -a 256 -c SHA256SUMS
gunzip omics.db.gz vector_ids.json.gz && tar -xzf pridemap.tar.gz && rm pridemap.tar.gz
cd ..
```

This gives `data/omics.db` (888,335 datasets, with the PRIDE method tags and repository metadata), `data/vectors.npy` and `data/vector_ids.json` (the embeddings), and `data/pridemap/`. To rebuild them yourself instead, follow the next section.

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

The microphone button in the search bar uses the browser's own speech recognition (no key, nothing sent by our code): press it, speak, and the transcript lands in the search box for you to edit before searching. Browsers allow this only in a secure context, so it works on `localhost` or over HTTPS, and the button is disabled with the reason when the app is opened over plain HTTP on another machine's address.

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

## MaxQuant search kit

For a PRIDE project with an SDRF, locus writes a zip that a researcher takes to an x86-64 workstation or a cluster to reprocess the raw data with MaxQuant. **The search does not run on the machine serving locus.** Measured on two DDA runs (PXD046787, 4 GB of raw data), MaxQuant peaked at 13.4 GB of RAM, 15.8 GB of disk and about 10 busy cores, so the kit asks for 16 GB of RAM, 8 threads and disk of four times the raw data. A few raw files fit a workstation; a large project belongs on a cluster such as Iridis. The published container is x86-64 only. locus generates and validates the kit; the user runs it.

MaxQuant is free for academic and non-profit use under its own licence, and the kit fetches it at run time. The scripts refuse to run it until `MAXQUANT_ACCEPT_LICENSE=1` is set, and the image must not be pushed to a public registry.

- `mqpar.xml` is filled in from the SDRF: the raw file list, experiments (one per sample, or one per mixture for a multiplexed file), fractions, labelling (`comment[label]` → label-free, TMT or iTRAQ reporter channels, or SILAC states), instrument group (Orbitrap, Bruker timsTOF, or Bruker, Sciex or Agilent Q-TOF, each with MaxQuant's default peak settings), enzymes and the fixed and variable modifications the SDRF states. Fields the SDRF leaves empty get MaxQuant's usual defaults and are listed under "Check before running" in the README.
- `download_fasta.sh`, `download_raw.sh`, `run_maxquant.sh`, `run_all.sh` and `preflight.sh` are resume-safe, append one JSON line per stage to `progress.jsonl`, and stop at the first failure. `preflight.sh` lists the blockers on the machine it runs on (architecture, memory, CPUs, disk, MaxQuant availability) and exits 1 instead of pretending it can proceed.
- `submit_slurm.sh` wraps the run in a Slurm job with the memory, CPUs and walltime the search needs, and searches on node-local disk (`$TMPDIR`) when it has room. Feature detection is I/O-bound; on local disk it ran about 6 times faster than on network storage.
- `preflight.sh` also blocks on symlinked raw files: Thermo's reader fails on them with an error that does not say why.
- `README.txt` repeats the design read from the SDRF, the requirements, the exact commands and the caveat above.

A project without an SDRF is refused with a message saying so; nothing is guessed, because a wrong `mqpar.xml` fails hours into a run. Before the zip is written, `mqpar.xml` is checked against the contract MaxQuant 2.0.3 enforces at run time (fields that must be present, absent, empty or sized to one another; each row is a run that died 10 to 37 minutes in). The contract, the shape of the scripts, the resource measurements and the licence gate come from [PRIDE Map](https://github.com/FlynnLachendro/pridemap) (MIT, [`LICENSE.pridemap`](LICENSE.pridemap)), re-implemented here.

Get the zip from a PRIDE study page (**MaxQuant kit**, under Files) or from `GET /maxquant-kit/{accession}`. To write kits to disk and see which fields differ between projects:

```sh
uv run python -m omics_agent.maxquant PXD000159 PXD000001 PXD001345 --out kits
```

The design is in [`docs/plans/2026-10-18-maxquant-kit.md`](docs/plans/2026-10-18-maxquant-kit.md).

## Process a dataset

For a GEO bulk RNA-seq study (gene activity measured by sequencing) with counted case and control samples, locus can run the laptop-tier pipeline from `docs/data-processing-contract.md` on your own machine. In plain terms: it fetches the first 2,000,000 sequencing reads of each sample from ENA (the European archive of raw reads), matches them to the known human or mouse transcripts with salmon (a fast read-counting tool) using the GENCODE reference (the standard catalogue of genes), sums the counts per gene with tximport, and tests which genes differ between the two conditions with DESeq2 (the standard statistical method for this), with apeglm shrinkage so that small, noisy fold changes are not overstated. "padj" in the outputs is the adjusted p-value: the chance a gene's change is a fluke, corrected for testing thousands of genes at once; the usual cut-off is 0.05. Reads are subsampled, so the result is a preview of the study, not a reanalysis; the manifest says so.

It needs [micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html) and one environment (bioconda has builds for linux-64, linux-aarch64 and osx-arm64):

```sh
micromamba create -n omics-rnaseq -c conda-forge -c bioconda salmon bioconductor-deseq2 bioconductor-tximport bioconductor-apeglm r-ggplot2 r-jsonlite
uv run omics process GSE273888 --topic "mTOR inhibitor, rapamycin"
```

`--topic` is the question the case/control labels answer (the search's terms); without it the study title is used. The first run for an organism downloads GENCODE transcripts (human release 46 or mouse M35) to `~/omics-ref/` and builds the salmon index, which takes about 7 minutes and 3.3 GB of memory on an 8-core ARM machine. After that a 6-sample study takes a few minutes. Outputs land in `data/process/<GSE>/`:

| File | Contents |
|---|---|
| `<GSM>.count` | One per sample: `gene_id<TAB>count`, integer, HTSeq-style |
| `counts.tsv`, `normalized_counts.tsv` | Genes × samples, raw and DESeq2-normalised |
| `deseq2_results.tsv`, `top_genes.tsv` | Shrunken log2 fold changes, p-values and adjusted p-values for the chosen contrast |
| `plots/` | Five figures as 300 dpi PNG and vector PDF: PCA with sample labels and per-condition hulls, volcano (adjusted p, thresholds drawn, top genes labelled), MA, a sample-to-sample distance heatmap and normalised counts of the top six genes. `pca.png`, `volcano.png` and `ma.png` at the top level are copies for the web panel, which reads the same data from the JSON files |
| `manifest.json` | Tool versions, reference release, samples, runs, read cap, timings and the samples left out, with the reason |
| `explanation.md` | A short paragraph the model wrote from the numbers above. Code checks every number in it against the pipeline's output and drops the paragraph if one was invented; the note under it says what happened |

The contrast is one two-level comparison: the most frequent control value of the labelled field against the most frequent case value, up to 4 samples per side, at least 2. Samples with other values, other assays or no FASTQ in ENA are listed in the manifest with the reason. Only human and mouse have a pinned reference.

The same run is available as a background job from the API (`POST /process/{accession}?topic=…`, then `GET /process/{accession}` until `stage` is `done`, and `GET /process/{accession}/files/{name}` for each output) and from the **Process** button on a GEO RNA-seq row in the web app, which shows the stages and then the plots, the top genes and the downloads. The worked example is in [`docs/evidence/process/GSE273888/`](docs/evidence/process/GSE273888/).

### Where it can run: three rows for every data type

The **Process** button on a GEO row (bulk RNA-seq, single-cell RNA-seq or Ribo-seq) opens three rows, each with what it
costs *for this dataset* (time, memory, disk, estimated from ENA's read counts and file sizes and calibrated on measured
runs) and an honest label. A row that cannot work for the dataset is shown greyed with its reason, never hidden.

| Row | Meaning |
|---|---|
| **Here, now** | Small analyses of files that are already processed: the authors' tables or matrices, or a run computed earlier. Safe on the public server. |
| **On your laptop** | What a 16 GB laptop can run: the subsampled-reads pipeline (run here when locus runs live; otherwise the one command, and a zip of the samples it uses). |
| **On a cluster** | A Slurm / nf-core kit (samplesheet, `run.sbatch`, `nextflow.config`, README with the GENCODE release), with the one-line reason a laptop cannot do it, for example "a human STAR index needs about 32 GB of memory". Written from the records; not run on a cluster. |

| Data type | Here, now | On your laptop | On a cluster |
|---|---|---|---|
| Bulk RNA-seq | the First look from the authors' table, or an earlier run | salmon → DESeq2 on 2,000,000 reads per FASTQ (above) | nf-core/rnaseq 3.27.0 kit (STAR + salmon) |
| Single-cell / single-nucleus RNA-seq | QC, Leiden clusters, UMAP, marker dot plot and pseudobulk DESeq2 per cluster from the authors' per-sample matrices in GEO (scanpy; `--tier scrnaseq-here`) | kb-python kit on subsampled reads, then the same scanpy script | nf-core/scrnaseq kit (STARsolo) |
| Ribo-seq (with matched RNA-seq) | ΔTE from the authors' CDS count tables: DESeq2 with an interaction term (the deltaTE approach), gene classes and a Δ RNA vs Δ Ribo scatter (`--tier riboseq-here`) | fastp → bowtie2 against rRNA, then one GENCODE transcript per gene → P-site offsets, metagene with 3-nt periodicity, footprint lengths, CDS counts → ΔTE (`--tier riboseq-laptop`; a lower-fidelity approximation of the cluster pipeline, and it says so) | nf-core/riboseq kit, with the samplesheet and contrasts above |

API: `GET /process/{GSE}/options?topic=…` (the rows), `POST` then `GET /process/{GSE}/run/{here|laptop}?topic=…`
(a run and its status; `…/files/{name}` for outputs), `GET /process/{GSE}/kit/{laptop|cluster}?topic=…` (a zip).
Single-cell needs the `omics-sc` micromamba environment (scanpy, leidenalg, python-igraph, kb-python) and Ribo-seq the
`omics-ribo` one (bowtie2, samtools, fastp, pysam, seqkit, matplotlib); both exist for linux-aarch64. Worked examples:
[`docs/evidence/process/GSE229253/`](docs/evidence/process/GSE229253/) (single-nucleus) and
[`docs/evidence/process/GSE132703/`](docs/evidence/process/GSE132703/) (Ribo-seq); the panel itself in
[`docs/evidence/process/panel/`](docs/evidence/process/panel/).

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

What a judge or a reviewer should know before trusting a result. None of these is hidden in the output; the manifest, the notes and the count lines say so.

**Processing a dataset**

- Reads are subsampled: the first 2,000,000 reads of each file. Enough to see whether the conditions separate and which large changes are there, not enough for a publication-grade gene list. The number is a flag (`--reads`) and is written in the manifest.
- One comparison per dataset: the most frequent control value against the most frequent case value of one field, at most 4 samples per side. Multi-factor designs, time courses and paired designs are not modelled.
- Only the first sequencing run of each sample is used; human (GENCODE 46) and mouse (M35) are the only references.
- Transcript-level quantification without decoy sequences; no genome alignment, no bigWig tracks. The HPC tier in the contract is nf-core/rnaseq, which this repository does not run.
- The written summary is model text. Every number in it is checked against the pipeline's output and the paragraph is dropped if one was invented, but the sentences around the numbers (for example what a gene "is known to" do) are the model's and are labelled as such.
- Which field marks case and control is the model's choice; code counts, but a wrong field gives a wrong contrast. The manifest names the field and the values.
- The worked example (GSE273888) was run on one machine; the figures were looked at, the biology was not reviewed by a wet-lab scientist.

**Search and counts**

- Sample counts are counts of sample records, not of patients. One patient can have several libraries.
- On a machine without the local index, locus searches the live GEO, PRIDE and CELLxGENE APIs only, not all 18 repositories. Download the index from the data release to search all 18.
- The first two stages of a search (candidate scoring and the four checks) are not cached, so repeating a question can rank or include datasets differently; the plan and the sample labels are cached.
- Results on the local model (Qwen via vLLM) have not been compared with the Claude runs in `docs/evidence/`; a search takes 4–8 minutes on it.
- Counts exist for GEO, CELLxGENE and the PRIDE projects with a curated SDRF in [bigbio/sdrf-annotated-datasets](https://github.com/bigbio/sdrf-annotated-datasets) (about 28% of PRIDE; clone it shallow into `data/sdrf/`), or an SDRF the project itself lists in PRIDE. For those, locus counts individuals, samples and runs separately and leaves pooled, QC and reference channels out; a missing individual column shows as "unknown", never as a sample count. Other PRIDE projects have no counts.
- The model labels can change between runs, so a count can appear in one run and be missing in the next.
- A broad search term can count related diseases as cases.
- Most ENA, EGA, MetaboLights, NODE and dbGaP records have no species, so they pass every species filter.
- Rows from OmicsDI and ENA have no linked paper.
- Proteomics sample tables (SDRF) cover about 28% of PRIDE; where the table covers only part of a study, the counts are for the table, not the paper (PXD027637 in `docs/evidence/sdrf/` is an example).

**Not built**

- The laptop Ribo-seq path aligns to one transcript per gene with bowtie2, on subsampled reads; it is a preview, not nf-core/riboseq. Single-cell "here, now" uses the authors' matrices and runs no batch integration, so clusters can follow donors (the result says when they do). Cluster kits were written from the records and not run on a cluster.
- No proteomics or metabolomics processing (the MaxQuant kit lives on the `maxquant-kit` branch).
- Voice input uses the browser's own speech recognition, which browsers allow only on `localhost` or over HTTPS; over plain HTTP to another machine the button is disabled and says why.

## Layout

| Path | Contents |
|---|---|
| `omics_agent/agent.py` | The search: plan, gather, triage, screen, count, grade, group. The CLI, API and MCP server share it. |
| `omics_agent/samples.py` | GEO sample records, labels and counts |
| `omics_agent/samplesheet.py` | The nf-core/riboseq export |
| `omics_agent/maxquant.py` | The MaxQuant search kit for PRIDE projects (generated here, run on a workstation or cluster) |
| `omics_agent/process.py`, `deseq2.R` | The laptop-tier RNA-seq pipeline: ENA reads → salmon → counts → DESeq2 → plots |
| `omics_agent/options.py`, `kits.py` | The three rows per data type with their requirements, and the laptop and cluster kits |
| `omics_agent/singlecell.py`, `singlecell_analyse.py`, `pseudobulk_deseq2.R` | Single-cell: scanpy QC, clusters, UMAP, markers, pseudobulk DESeq2; kb-python and nf-core/scrnaseq kits |
| `omics_agent/riboseq.py`, `riboseq_psite.py`, `deltate_deseq2.R` | Ribo-seq: ΔTE from counts or from subsampled reads (rRNA removal, transcriptome alignment, P-sites, metagene); nf-core/riboseq kit |
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

Apache 2.0 (see [`LICENSE`](LICENSE)). The web interface is built on [PRIDE Map](https://github.com/FlynnLachendro/pridemap) by Flynn Lachendro, under the MIT licence ([`web/LICENSE.pridemap`](web/LICENSE.pridemap)); the MaxQuant kit's `mqpar.xml` contract and scripts are re-implemented from the same project ([`LICENSE.pridemap`](LICENSE.pridemap)).
