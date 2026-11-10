# The three-row Process panel on a real dataset (GSE273888)

Taken on 18 October 2026 at 22:24 BST by `scripts/panel_shot.mjs` against the test servers of the `modalities`
worktree (API on port 8040, web on 3040, model: Qwen on pgx through `LOCAL_LLM_URL`).

What the script did: typed "Bulk RNA-seq of human cells treated with an mTOR inhibitor such as Torin1 or rapamycin
compared with vehicle" into the search box, waited for the results, opened GSE273888's row, clicked **Process**,
screenshotted the panel at 1280 px (`GSE273888-rows-1280.png`) and 390 px (`GSE273888-rows-390.png`), then clicked
**Show the results** on the "Here, now" row and screenshotted the results (`GSE273888-here-results-1280.png`).
`GSE273888-panel.txt` is the panel's text as rendered.

The rows and the requirements shown come from `GET /process/GSE273888/options`:

| Row | Shown as | Requirements stated |
|---|---|---|
| Here, now | a run computed earlier on this dataset, with its figures | instant · memory none · disk none |
| On your laptop | subsampled reads → salmon → counts → DESeq2; 100_nm_rapamycin vs no_treatment from 'treatment', 6 samples | about 6 min for 6 samples plus about 7 min once for the reference · memory about 4 GB · disk about 3.3 GB |
| On a cluster | nf-core/rnaseq (STAR + salmon) on the full reads, as a Slurm kit; "not a laptop job: a human STAR index needs about 32 GB of memory" | walltime 3 h (6 samples as parallel jobs; the largest has 23 M reads) · memory 32 GB per alignment job · disk about 45 GB |

The cluster kit downloaded from the same panel is a zip with `samplesheet.csv` (6 rows, full ENA FASTQ URLs,
strandedness auto), `run.sbatch` (nf-core/rnaseq 3.27.0, GENCODE 46 genome and annotation), `nextflow.config`
(Apptainer, slurm profile, 36 GB for STAR) and `README.md`. It was not run on a cluster.

The run's console reported one problem, fixed afterwards: the row component rendered a `<li>` inside the panel's `<li>`
(a hydration warning); the inner element is now a `<div>`.

## The same panel on a Ribo-seq dataset (GSE132703)

At 22:32 BST the script ran "Matched RNA-seq and Ribo-seq before and after mTOR inhibition" (cached search, 20 s;
GSE132703 ranked first of 11), clicked **Process** on GSE132703, and opened the "Here, now" row
(`GSE132703-rows-1280.png`, `GSE132703-rows-390.png`, `GSE132703-here-results-1280.png`, `GSE132703-panel.txt`).
Rows shown: Here, now (ΔTE from the authors' CDS counts; under a minute, about 1 GB, under 50 MB), On your laptop
(subsampled reads → rRNA removal → transcriptome alignment → P-sites, metagene, footprint lengths, CDS counts → ΔTE;
about 5 min, about 1.5 GB, 2 GB; labelled a lower-fidelity approximation of the cluster pipeline), On a cluster
(nf-core/riboseq kit; about 8 h, 64 GB per job, 63 GB; "STAR against the human genome needs about 32 GB of memory").
The results view showed the ΔTE scatter with its caption, the summary sentences, the downloads and the tool versions.
No console errors.

## The same panel on a single-nucleus dataset (GSE229253)

At 23:21 BST the script ran "Single-nucleus RNA-seq of tumour-adjacent normal lung and tumour in early-stage lung
adenocarcinoma, recurrence versus no recurrence" (a fresh search had taken 401 s a few minutes earlier; this cached
rerun took 3 s; GSE229253 ranked second, grouped with its bulk half GSE229706), opened the group, clicked **Process** on
GSE229253 and opened the "Here, now" row (`GSE229253-rows-1280.png`, `GSE229253-rows-390.png`,
`GSE229253-here-results-1280.png`, `GSE229253-panel.txt`). Rows shown: Here, now (QC, clustering, UMAP, markers and
pseudobulk DE from the authors' matrices; "GEO holds per-sample matrices for 33 of 33 samples; 8 would be used, 214 MB
to download"; 18 min, 3.8 GB, 0.1 GB), On your laptop (kb-python kit; 2.8 h, about 4 GB, 20 GB), On a cluster
(nf-core/scrnaseq kit; 14 h, 48 GB per STARsolo task, 151 GB; "a human STARsolo index needs about 32 GB of memory").
The results view showed the UMAP and the marker dot plot with their captions, the summary and the warnings, including
"Samples are nested in people". No console errors.
