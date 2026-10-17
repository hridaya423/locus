# FASTQ → .count → DESeq2 → plots: overnight MVP for the 18 October demo

Status: agreed scope for the overnight run of 17–18 October 2026 (decided with Juri at 23:00 BST). Designed, not built, at the time of writing; the run updates the "Status log" at the end.

## Why

Judging (Hackathon slides): impact, technical execution ("is the tool working and usable?") and presentation ("can non-experts understand it?"), 10 points each. Pitch is 3 minutes of problem + demo. Today locus finds datasets and writes an nf-core samplesheet, but a biologist still has to install and run a pipeline before seeing any result. The MVP closes that loop: **question → dataset → counts → differential expression → plots**, on a laptop-class budget.

First user: a wet-lab biologist who has found a public bulk RNA-seq study in locus and wants to know which genes change between its conditions, without a cluster or a bioinformatician.

## The demo story (3 minutes)

1. Type a plain-English question in locus. A bulk RNA-seq GEO series with two conditions appears.
2. Click **Process**. Status advances: samplesheet → download (subsampled reads) → quantify → counts → DESeq2.
3. The results view shows PCA (samples separate by condition), volcano and MA plots, and a top-genes table. The `.count` files and DESeq2 table can be downloaded.
4. One sentence on honesty: reads are subsampled for the demo, and the manifest records every tool version and the reference.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| riboseq-agent (private, no licence, pre-hackathon) | Read for ideas only, write new code. Copy nothing. | Hackathon rule "no prior building", and the repo is Apache-2.0 while riboseq-agent has no licence |
| Demo dataset | Agent picks via a real locus query: human or mouse bulk RNA-seq, 2 conditions × ≥3 replicates, ≤ 8 samples, FASTQs on ENA | The query that found it becomes the demo script |
| Reads | First 2,000,000 reads per FASTQ, streamed from ENA (no full download) | Minutes per sample instead of hours; documented as subsampled |
| Quantifier | salmon (bioconda linux-aarch64, 2.8.x), transcriptome index without decoys, `-l A`; kallisto as the fallback if the index will not fit in memory | Laptop-tier choice from `docs/data-processing-contract.md` |
| Reference | GENCODE transcripts (human release 46 or mouse M35, whichever matches the dataset), cached under `~/omics-ref/` | One pinned version, recorded in the manifest |
| `.count` files | One `<sample>.count` per sample: tab-separated `gene_id<TAB>count`, integer, HTSeq-style; plus `counts.tsv` (genes × samples) | What the user asked for; DESeq2 reads it directly |
| Gene-level counts | tximport (`countsFromAbundance = "no"`) from salmon `quant.sf` | Standard route from salmon to DESeq2 |
| DE | DESeq2 1.50 `~ condition`, `lfcShrink(type = "apeglm")`, alpha 0.05 | Field standard |
| Plots | PCA on VST, volcano, MA; PNG for slides (R/ggplot2) and JSON for the web view (Recharts, already a dependency) | Live demo plus a static fallback |
| Runtime | micromamba env `omics-rnaseq` (salmon, tximport, DESeq2, apeglm, ggplot2, jsonlite); no Docker (most biocontainers are x86-only, pgx is ARM64) | Verified bioconda aarch64 builds exist |
| Interfaces | Python application layer `omics_agent/process.py`; CLI `uv run omics process <GSE>`; API job endpoints; web "Process" button + results panel | AGENT.md: GUI calls the API, logic stays out of the interface |

## Components

1. **Plan**: reuse `samplesheet.build` (GEO records + ENA run reports + labels) to get runs and conditions; pick exactly one two-level contrast; cap at 8 samples, balanced per condition.
2. **Fetch**: stream the first N reads of each ENA FASTQ over HTTPS (`curl | gzip -dc | head -n 4N | gzip`); paired-end keeps mates in sync.
3. **Reference**: download GENCODE transcripts + GTF once, build the salmon index, write `tx2gene.tsv`.
4. **Quantify**: `salmon quant` per sample.
5. **Count**: tximport → `counts.tsv` and per-sample `.count`.
6. **Test**: DESeq2 → `deseq2_results.tsv`, `normalized_counts.tsv`, `pca.json`, `volcano.json`, `ma.json`, PNGs.
7. **Manifest**: `manifest.json` per the contract (tier `laptop`, tool versions, reference release, accessions, read cap, start/end time, skipped samples).

Outputs land in `data/process/<GSE>/` (gitignored). A copy of the small outputs (plots, top-genes table, manifest, the demo query) is committed to `docs/evidence/process/<GSE>/`.

## Interfaces

- CLI: `uv run omics process GSE… [--reads 2000000] [--threads 8]`, prints each stage and the final summary.
- API: `POST /process/{accession}` starts a background job; `GET /process/{accession}` returns stage, log tail and, when done, the result JSON; `GET /process/{accession}/files/{name}` serves `.count`, results and PNGs.
- Web: a **Process** button on RNA-seq result cards; a results panel with stage progress, PCA, volcano, MA, top-genes table and download links.

## Machine constraints (pgx, verified 17 Oct 23:00)

- ARM64 (NVIDIA GB10), 20 cores, ~11 GB RAM free. **vLLM on :8000 holds ~110 GB and must not be stopped**: locus search runs on it (`LOCAL_LLM_URL` in `.env`, no Anthropic key).
- The other session works in `/home/jlw/omics-agent` (branch `main`). The overnight run works only in the worktree `/home/jlw/omics-agent-pipeline` (branch `juri-processing-pipeline`). Use API port 8020 and web port 3020, because 8000 and 8010 are taken.
- `.env` and `data/` in the worktree are symlinks to the main checkout.

## Out of scope tonight

Full-depth runs, nf-core/rnaseq itself (it stays the documented HPC-tier target), alignment and bigWigs, single-cell, proteomics, Ribo-seq/ΔTE, multi-factor designs.

## Acceptance criteria

Prove each one with command output in the session.

1. `micromamba run -n omics-rnaseq salmon --version` and an R line printing the DESeq2, tximport and apeglm versions both succeed.
2. `uv run omics process <GSE>` exits 0 on the chosen dataset, end to end, in under 45 minutes wall time (index build excluded). It prints the list of output files with sizes, `head -5` of one `.count` file, the number of genes, and the number with padj < 0.05.
3. Sanity: PCA PC1 or PC2 separates the two conditions (print the per-group PC means), and the top genes are plausible for the study. Write one sentence of reasoning per study. No invented biology.
4. `uv run pytest` passes, including new tests for contrast selection and `.count` writing on a tiny fixture.
5. API: curl shows `POST /process/<GSE>` then `GET` reaching `done` (the cached result is fine).
6. Web: `npm run build` passes. The results panel renders the plots for the chosen dataset, with a screenshot saved under `docs/evidence/process/<GSE>/`.
7. Docs: README "Process a dataset" section; `docs/evidence/process/<GSE>/` (PNGs, top genes, manifest, query); a 3-minute demo script at `docs/plans/2026-10-18-demo-script.md`; the status log below updated.
8. All work committed on `juri-processing-pipeline` and pushed to origin; `git status` clean. Do not merge to `main`.

If time runs short, deliver in this order: 2 → 3 → 4 → PNGs → 5 → 6. A working CLI with PNGs beats a half-working GUI.

## Status log

- 2026-10-17 23:00 BST: spec written; worktree created; no code yet.
- 2026-10-17 23:27 BST: `~/bin/micromamba` was a tar archive, not a binary (exec format error); replaced with the aarch64 binary extracted at `~/omics-ref/mm-extract/bin/micromamba` (the archive is kept as `~/bin/micromamba.tar`). Env `omics-rnaseq` created: salmon 2.8.0, R 4.5.3, DESeq2 1.50.2, tximport 1.38.2, apeglm 1.32.0, ggplot2 4.0.3, jsonlite 2.0.0.
- 2026-10-17 23:36 BST: human GENCODE 46 salmon index (k=31, no decoys, `--gencode`) built in 6 min 41 s, peak RSS 3.3 GB, 644 MB on disk. No kallisto fallback needed. tx2gene comes from the FASTA headers, so the GTF is not downloaded (deviation from the "transcripts + GTF" line above; the gene name is header field 6).
- 2026-10-17 23:35 BST: dataset chosen by the locus query "bulk RNA-seq of human cells treated with an mTOR inhibitor such as Torin1 or rapamycin compared with vehicle" (8 min 14 s on the local model; 34 strong GEO hits). GSE273888: HeLa, 100 nM rapamycin vs no treatment, 3 + 3, paired-end, ENA FASTQs.
- 2026-10-17 23:48 BST: `uv run omics process GSE273888 --topic "mTOR inhibitor, Torin1, rapamycin, mTORC1, mTORC2, mTOR signaling"` exit 0 from a clean `data/process/GSE273888/` in 172 s (fetch 30 s, salmon ~25 s per sample at <1 GB RSS, R ~40 s). 62,646 genes counted, 6,471 with an adjusted p-value, 84 with padj < 0.05 (44 up, 40 down). Mapping rate 89.3–89.8%, library type IU. PCA: no_treatment PC1 mean −2.85, 100_nm_rapamycin +2.85 (PC1 25%, PC2 20.3%); every sample on the correct side. Top genes include DDIT4 (−0.72) and SCD (−0.49), both mTORC1-dependent transcripts (via ATF4 and SREBP), falling after rapamycin as expected; CCN2, CCN1, THBS1 rise.
- 2026-10-17 23:49 BST: `uv run pytest` 8 passed (contrast selection, cap and refusals, `.count` writing, tx2gene, top genes). API on 8020: POST /process/GSE273888 → `{"stage": "done"}` (cached), GET returns the result, files endpoint 200 for a `.count` file and 404 for an unknown name. `npm run build` and `npm run lint` pass.
