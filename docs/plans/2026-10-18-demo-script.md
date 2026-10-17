# Demo script: question → dataset → counts → differential expression (3 minutes)

Rehearsed 17–18 October 2026 on pgx (ARM64, local vLLM model, no Anthropic key). Static fallback: the PNGs and
`top_genes.tsv` in `docs/evidence/process/GSE273888/`, and the screenshot `web-results-panel.png` there.

Before the demo: the API on `OMICS_API_PORT=8020`, the web app on 3020 with `OMICS_API_URL=http://localhost:8020`, and
`data/process/GSE273888/` already present so the Process button returns the cached run in seconds. The live search
takes 8 minutes on the local model, so start it before the pitch or use the cached question below (the plan and the
sample labels are cached per question, which makes a repeat run much faster).

## 0:00 – 0:40 Problem

"A biologist with a question spends days in GEO and PRIDE, and when they find a study they still cannot see what it
says without a bioinformatician and a cluster. locus searches 891,000 datasets in 18 repositories, counts the case and
control samples from the sample records, and now runs the first analysis on a laptop."

## 0:40 – 1:20 Search

Type: **bulk RNA-seq of human cells treated with an mTOR inhibitor such as Torin1 or rapamycin compared with vehicle**

Point at the plan (terms: mTOR inhibitor, Torin1, rapamycin, mTORC1, mTORC2; organism Homo sapiens; assay bulk
RNA-seq) and at the table: 34 strong GEO hits with case and control counts. Open **GSE273888**: HeLa cells, 100 nM
rapamycin, 3 treated and 3 untreated, paired-end reads on ENA. "The counts come from code reading the sample records;
the model only chose which field marks treatment."

## 1:20 – 2:20 Process

Click **Process**. Name the stages as they pass: contrast from the labels → GENCODE 46 salmon index (cached) → first
2,000,000 reads of each FASTQ streamed from ENA → salmon → tximport gene counts and one `.count` file per sample →
DESeq2 with apeglm shrinkage. On pgx the whole run took 3 minutes; the cached result appears at once.

Show the panel:

- PCA: the three untreated samples sit at PC1 ≈ −2.9, the three rapamycin samples at +2.9 (25% of variance).
- Volcano and MA: 84 genes with padj < 0.05 out of 6,471 tested (44 up, 40 down).
- Top genes: DDIT4 and SCD go down. Both are transcripts whose expression depends on mTORC1 (SCD through SREBP, DDIT4
  through ATF4), so their fall after rapamycin is the expected direction. CCN2, CCN1 and THBS1 rise.
- The paragraph under "Written by the model from the numbers above": the model wrote it from the computed numbers,
  and code checked every number in it against the pipeline's output before it was shown.
- Downloads: `GSM….count`, `counts.tsv`, `deseq2_results.tsv`, the PNGs and `manifest.json`.

## 2:20 – 2:50 Honesty

"Reads are subsampled: 2 million per FASTQ, so this is a preview of the study, not a reanalysis. The manifest records
salmon 2.8.0, DESeq2 1.50.2, tximport 1.38.2, apeglm 1.32.0, GENCODE release 46, every run accession and the read cap.
The same samplesheet goes to nf-core/rnaseq on a cluster for the full run. Everything shown is reproducible with one
command: `uv run omics process GSE273888`."

## 2:50 – 3:00 Close

"Question to differential expression in minutes, on a laptop, with every number traceable to a record or a tool."

## Likely questions

- *Is 2 million reads enough?* No for a publication; yes to see whether the conditions separate and which large effects
  are there. The read cap is a flag (`--reads`) and is written in the manifest.
- *Why salmon and not STAR?* A human STAR index needs about 32 GB; the salmon transcriptome index took 3.3 GB and
  7 minutes on this machine. The contract (`docs/data-processing-contract.md`) keeps STAR for the HPC tier.
- *Who chose the contrast?* Code: the most frequent control value against the most frequent case value of the field the
  model labelled; at least 2 and at most 4 samples per side; every sample left out is listed with the reason.
- *What about mouse, or more than two conditions?* Mouse uses GENCODE M35, the same path. Multi-factor designs are out
  of scope for the laptop tier tonight.
- *Did you reuse earlier code?* No. The riboseq-agent repository was read for ideas only; this pipeline was written in
  the hackathon window under the Apache-2.0 licence of this repository.
