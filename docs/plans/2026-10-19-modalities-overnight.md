# Overnight 18–19 October: processing for more data types, honest about where it can run

Status: agreed with Juri at 21:45 BST on 18 October 2026. Designed, not built, at the time of writing. Branch `modalities` off `deploy-public` (PR #2), worktree `/home/jlw/fast/locus/omics-agent.wt/modalities`.

## Where things stand

- A public site runs at https://locus.204.168.183.57.sslip.io (playtime-vps: 2 vCPU, 3.8 GB RAM + 4 GB swap). It searches the full index (888,335 datasets, 18 repositories). New searches run on pgx's Qwen through a private tunnel. Process serves precomputed runs only (`OMICS_PROCESS=cached`).
- Bulk RNA-seq processing works on a laptop: subsampled ENA reads → salmon → `.count` files → DESeq2 → five figures (`omics_agent/process.py`, `deseq2.R`).
- The search for the demo question found GSE229705 (bulk RNA-seq) 1st and its single-nucleus half GSE229253 2nd, in 6 min 35 s on Qwen: planning 89 s, **screening 225 s**, facts 77 s.

## Decisions recorded tonight

1. **Every data type presents its compute options the same way: three rows**, each with what it costs *for this dataset* (time, memory, disk) and an honest label.

   | Row | Meaning |
   |---|---|
   | **Here, now** | Small analyses of files that are already processed (the authors' tables, a showcase run). Instant, and safe on the public server. |
   | **On your laptop** | A kit (one command, or a zip of scripts) that a 16 GB laptop can run, with locus checking the dataset fits before the user starts. |
   | **On a cluster** | A Slurm / nf-core kit, with a one-line reason a laptop cannot do it (for example "a human STAR index needs about 32 GB of memory"). |

   locus never pretends: a row that cannot work for this dataset is shown greyed with its reason, not hidden.

2. **Tonight's data types**, in priority order:
   1. **Bulk RNA-seq, cluster row**: the nf-core/rnaseq kit (STAR + salmon) for what already runs on a laptop, so the existing type shows all three rows.
   2. **Single-cell RNA-seq**: here, now = QC, clustering, UMAP, marker genes and pseudobulk differential expression from the authors' processed matrix when it is small enough; laptop = kb-python counts from subsampled reads, then the same analysis with scanpy; cluster = nf-core/scrnaseq kit. Test on GSE229253, the demo study's single-nucleus half.
   3. **Ribo-seq and translation efficiency**: cluster = nf-core/riboseq kit (samplesheet export already exists in `samplesheet.py`); laptop = the path the contract designed but nobody built (rRNA removal with bowtie2, alignment to the transcriptome, CDS counts, P-site offsets where the footprint length allows); with a matched RNA-seq library, translation efficiency and ΔTE using DESeq2 with an interaction term (the deltaTE approach). Test on GSE132703, whose Ribo-seq and RNA-seq libraries locus already pairs.
   Proteomics waits; the MaxQuant kit lives on the `maxquant-kit` branch.

3. **Qwen speed, quality first, cost second.** Thinking is already off by default (`LOCAL_LLM_THINK` is opt-in), so the time is in the number and size of calls, mostly screening. Measure before changing anything, and keep any change only if search quality holds.

## Work, in order

### 0. Baseline

- Point this worktree at the full index (`data/` → `/home/jlw/fast/locus/data`, fetched from the `data-2026-10-18` release; checksums verified).
- Run Hridya's harness questions on Qwen and record, per question: wall time per stage, number of model calls, tokens in and out, and recall against the Opus list in `docs/evaluation.md`. This is the quality bar every speed change must meet.

### 1. The three-row panel

One Process panel component for every data type, driven by an API that returns, per dataset, which rows apply, their requirements and the reason when a row does not. Requirements are estimated from ENA's read counts and file sizes, calibrated against measured runs (GSE273888 took 172 s; GSE295999 and GSE344137 timings are in `/tmp/demo-*.log` and their `process.log`). The public server (`OMICS_PROCESS=cached`) shows "Here, now" live and the other two rows as kits.

### 2. Bulk RNA-seq cluster kit

A zip: nf-core/rnaseq samplesheet built from the same GEO records and ENA runs as the laptop path, a Slurm submission script with stated memory and walltime, a minimal Nextflow config with an Apptainer profile, and a README naming the reference (GENCODE release) so results match the laptop tier's annotation.

### 3. Single-cell

As in decision 2. A UMAP and a dot plot of marker genes are the figures; pseudobulk DE per cell type is the comparison, and the nested-in-people warning that already exists applies to it.

### 4. Ribo-seq and TE

As in decision 2. The figures that matter to a translation researcher: a metagene plot around start and stop codons showing three-nucleotide periodicity, a footprint-length histogram, and a ΔTE scatter (Δ RNA vs Δ Ribo, coloured by class: translationally regulated, buffered, transcriptional). State plainly when the laptop path is a lower-fidelity approximation of the cluster pipeline.

### 5. Qwen speed

Profile the screening stage first. Candidates, each tested against the baseline: fewer or shorter screening calls, smaller per-call token budgets, batching datasets per call, the concurrency the vLLM server actually sustains. Keep a change only if harness recall is at least the baseline and the demo question still ranks GSE229705 and GSE229253 at the top.

## Rules

- **Do not touch the public server** (playtime-vps), the tunnel (`~/locus-tunnel.sh`, tmux `locus-tunnel`), or the vLLM server on port 8000. Leave a deployment note for the morning instead.
- Work only in `/home/jlw/fast/locus/omics-agent.wt/modalities` on branch `modalities`; test servers on ports 8040 and 3040; never touch `main` or other worktrees.
- pgx is ARM64: tools come from bioconda/conda-forge `linux-aarch64` through `~/bin/micromamba` with `MAMBA_ROOT_PREFIX=/home/jlw/.local/share/mamba`. If a tool has no ARM64 build, say so and choose another; do not pretend a kit was tested when it was not.
- riboseq-agent (private, unlicensed) is ideas only; copy no code. Use the open-source tools themselves (nf-core, kb-python, scanpy, bowtie2, DESeq2, riboWaltz or an equivalent) under their licences.
- Testing a cluster kit for real on Iridis is optional and last: at most one small subsampled run, submitted with `sbatch`, nothing heavy on login nodes.
- Never report a number or a figure that was not produced in this run.

## Status log

- 2026-10-18 21:50 BST: spec written; worktree created; index fetching to `/home/jlw/fast/locus/data`.
- 2026-10-18 22:12 BST: index in place (`data/` → `/home/jlw/fast/locus/data`, checksums OK). Agent instrumented: per-stage seconds, every local-model call with its tokens (`agent.TRACE`), `OMICS_FRESH_ANSWERS=1` to bypass remembered triage/screen answers. Baseline running: `uv run python scripts/qwen_baseline.py --out docs/evidence/qwen/baseline --demo`. q1 fresh: 457 s (plan 99, gather 21, triage 112, screen 98, facts 125); the per-request decode rate is about 7 tokens/s whatever the concurrency, so wall time follows the longest call's output, not the number of calls. Three-row options API (`GET /process/{GSE}/options`), row runs (`POST/GET /process/{GSE}/run/{row}`), kits (`GET /process/{GSE}/kit/{row}`) and the bulk RNA-seq cluster kit (nf-core/rnaseq 3.27.0, GENCODE 46) built and checked on GSE273888 over HTTP; web panel rewritten (`web/components/process-panel.tsx`), type-check clean. Single-cell and Ribo-seq modules in progress (two builders). The full Opus list of 34 is not on this machine (it lived in /tmp/locus-night on the laptop that ran it); recall is reported against the 7 sure and 3 probable picks the repository names.
- 2026-10-18 22:35 BST: **Ribo-seq and TE built and run on GSE132703** (`omics_agent/riboseq.py`, `riboseq_psite.py`, `deltate_deseq2.R`; 26 offline tests). Here, now (authors' CDS counts, 23 s, 961 MB peak): Torin 1 vs DMSO, 4 + 4 pairs, 10,301 genes tested; 463 translationally regulated, 9 buffered, 36 transcriptional, 6 intensified; top ΔTE-down genes VDAC1, PABPC1, GAPDH, CSDE1, PRPS2, KARS, CCT2 (TOP mRNAs, as expected under Torin1). Laptop (2 M reads per library, 240 s, 1.13 GB peak, 3.4 GB disk): linker CTGTAGGCACCATCAAT found in 93–96 % of reads, rRNA 56–87 % of footprint reads, footprints modal 31–33 nt, offsets 13 nt, periodicity 0.42–0.46 per library; 3,174 genes tested, 23 translationally regulated (GAPDH, PABPC1, YBX1, HSPA8, VIM, CCT2, CSDE1, HNRNPDL), 1 transcriptional. Figures: `deltate_scatter.png`, `metagene.png` (frame-0 start peak, 3-nt periodicity through the CDS, drop after the stop), `footprint_lengths.png`. Evidence copied to `docs/evidence/process/GSE132703/`. Cluster kit (nf-core/riboseq 1.2.0, 28 libraries, 3 within-genotype contrasts, 64 GB, 17 h) written, not run. Caveats in the result's warnings: transcriptome alignment to one transcript per gene, subsampled reads, the contrast pools wild-type and sgLARP1, 35YW RNA-seq libraries are mostly tRNA fragments. Three-row options now resolve for all three data types (GSE273888 bulk, GSE229253 single-nucleus, GSE132703 Ribo-seq) over HTTP.
- 2026-10-18 23:05 BST: **Single-cell built and run on GSE229253** (`omics_agent/singlecell.py`, `singlecell_analyse.py`, `pseudobulk_deseq2.R`; 13 offline tests). Here, now from the authors' per-sample matrices (8 of 33 samples, 4 tumor + 4 adjacent normal by 'source name', 214 MB): 37,575 nuclei → 37,536 after QC, 28,004 genes, 32 Leiden clusters; pseudobulk DESeq2 in the 8 clusters with ≥ 2 samples per condition, 309 significant gene tests (cluster 15: 155 of 10,266; cluster 4: 122 of 9,561); 14 clusters are > 90 % one sample, said so in the summary and warnings (no integration). Figures: `umap.png` (clusters; condition: tumour nuclei form their own islands, normal-lung clusters are shared across donors) and `markers_dotplot.png` (top 3 Wilcoxon markers per cluster, 86 genes). Run twice with identical results; 1,151 s / 3.06 GB the first time, 2,079 s / 4.04 GB the second, on a machine at 97 % RAM with 12 GB in swap (the analysis itself is a few minutes of CPU). Evidence in `docs/evidence/process/GSE229253/scrnaseq-here/`. Kits written, not run; important finding: ENA holds only the 75-nt cDNA read for this study (no barcode/UMI read), so the kb-python and nf-core/scrnaseq kits say the FASTQs must come from SRA with `fasterq-dump --include-technical`. kb-python in the env is 0.25.1 (the ARM64 build), not 0.30.
- 2026-10-18 23:13 BST: **Qwen baseline done** (`docs/evidence/qwen/baseline/summary.md`, 8 harness questions + the demo-study question, fresh triage and screen answers, plans and labels cached as in the app). Wall 350–874 s per question. Per stage: plan 73–150 s (one call, about 500 tokens out: the model decodes at 5–7 tokens/s for a single stream); triage 104–275 s (12 calls of 25 candidates, 6,650 tokens out in total: the `{n, score}` objects cost about 22 tokens a candidate); screen 89–247 s (15 calls of 4, about 7,000 tokens out); facts 0–214 s (0–38 label calls). Questions 3, 6 and 7 ran while the panel screenshot search and the two builders were also calling the model, so their triage and screen times are inflated by load; q1, q2, q4, q8 and the demo ran on a quieter server. Recall against the Opus picks the repository names: 2 of 7 sure (GSE35469 #34 on q1, GSE69352 #12 on q2), 0 of 3 probable; GSE36892 is missed on Qwen. Demo question: GSE229705 1st, GSE229253 15th (top 5: GSE229705, PRJNA608819, PRJNA792733, GSE287471, E-TABM-15). This is the bar for the speed work.
- 2026-10-19 09:58 BST (morning check): the run stopped at 23:13 on the Claude session limit and did not resume; `claude -p` exits when credits run out. Not started: the speed changes beyond the opt-in `OMICS_SCREEN_SHORT` flag (off by default, untested against the baseline), deployment. Re-checked this morning on this branch: `uv run pytest` 64 passed, `npm run build` passes. Committed the run's last edits as they stood.

_Paths updated 2026-10-27: the checkouts moved from ~/omics-agent* to ~/fast/locus/omics-agent(.wt/<branch>) and the index from ~/locus-data to ~/fast/locus/data on 25 Oct 2026._
