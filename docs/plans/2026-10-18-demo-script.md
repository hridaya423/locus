# Demo script: a question, a dataset, an answer (3 minutes)

Rehearsed 18 October 2026 at 01:29 BST on pgx (the ARM workstation, local model, no API key), driving the web app in
a browser against the API on port 8020. Measured: the search took 3 min 46 s with the question's plan and labels
already cached (a never-seen question takes about 8 minutes); clicking **Process** showed the full results panel in
4 seconds because the run is cached. Static fallback if anything breaks: the figures in
`docs/evidence/process/GSE273888/plots/`, the table `top_genes.tsv`, and the screenshot `web-results-panel.png` there.

Words to use on stage, so no one needs to know the jargon: an **archive** is where scientists deposit their raw
measurements (GEO for gene activity, PRIDE for proteins, ENA for raw sequencing reads). A **dataset** is one study's
measurements. **Treated and untreated samples** are the two groups being compared. A **gene that changed** is one whose
activity differs between the groups beyond what chance explains.

Before the demo: API on `OMICS_API_PORT=8020`; web app on 3020 started with `OMICS_API_URL=http://localhost:8020` and
`EXTRA_DEV_ORIGINS=<pgx-ip>` (without it the page never becomes interactive over the IP); `data/process/GSE273888/`
present. Submit the question before the pitch starts, or at 0:40 and talk over the wait.

## 0:00 – 0:40 What is it for, what was not working

"Every published study leaves its raw measurements in a public archive. A biologist with a question wants the right
study, and then wants to know what it shows. Today that is days of keyword searching, counting samples by hand in each
record, and then a pipeline, a cluster and a bioinformatician before a single gene is named. locus takes the question
in plain English, finds the studies, counts the samples from the records, and now runs the first analysis on an ordinary
computer."

## 0:40 – 1:20 Search

Type (or, if the app is open on `localhost`, press the microphone and say): **bulk RNA-seq of human cells treated with
an mTOR inhibitor such as Torin1 or rapamycin compared with vehicle**. Over `http://<pgx-ip>:3020` the microphone is
disabled with its reason on hover: browsers allow speech recognition only on localhost or HTTPS.

While it runs, point at the plan chips: it understood the drug family (rapamycin, Torin1), the organism (human) and the
kind of measurement (gene activity by sequencing). When the table appears (about 30 studies at the rehearsal; the
number varies between runs), say: "every count here comes from code reading the sample records; the model only chose
which field says treated or untreated." Open **GSE273888**: human cells, a drug called rapamycin, three treated and
three untreated samples.

## 1:20 – 2:20 Process

Click **Process**. The stages are listed as they pass; the cached run shows the finished panel in a few seconds. Say what
each stage did when it ran for real (3 minutes on this machine): fetch the first two million reads of each sample from
the archive; match them to the catalogue of human genes; count reads per gene; test which genes differ between the groups;
draw the figures; write a summary and check every number in it.

Show the panel:

- The first plot: the three untreated samples on one side, the three treated on the other. "The replicates agree, and
  the treatment is the biggest difference between the samples."
- The next two plots: 84 genes changed out of 6,471 tested (44 up, 40 down); the most changed are labelled.
- The table: DDIT4 and SCD went down. "Both are genes that textbooks link to the pathway this drug blocks, so the
  direction is what a biologist would expect." CCN2, CCN1 and THBS1 went up.
- The paragraph under "Written by the model from the numbers above": "The model wrote it from the numbers; code checked
  every number in it against the computed output before it was shown. If it had invented one, the paragraph would have
  been dropped and the panel would say so."
- Downloads: the per-sample count files, the results table, the five figures as slide-ready PNG and PDF (PCA, volcano,
  MA, sample-distance heatmap, top-gene counts) and `manifest.json`.

## 2:20 – 2:50 Honesty

"We used two million reads per sample, so this is a preview of the study, not a reanalysis. The manifest records every
tool and version, the reference catalogue, every sample and the read cap. The same inputs go to the standard cluster
pipeline for the full run. Everything shown is one command: `uv run omics process GSE273888`."

## 2:50 – 3:00 Close

"From a question to the genes that changed, in minutes, on a laptop, with every number traceable to a record or a tool."

## Likely questions

- *Is two million reads enough?* Not for a publication; enough to see whether the groups separate and which large
  effects are there. The number is a flag (`--reads`) and is written in the manifest.
- *Why this read-matching tool and not full genome alignment?* Full alignment of human data needs about 32 GB of memory;
  the transcript index took 3.3 GB and 7 minutes here. The contract keeps full alignment for the cluster tier.
- *Who chose which samples to compare?* Code: the most common control value against the most common treated value of
  the field the model labelled; at least 2 and at most 4 samples per side; every sample left out is listed with the
  reason.
- *What about mouse, or more than two conditions?* Mouse works the same way with its own catalogue. Designs with more
  than one factor are not handled.
- *Does the search always return the same list?* No: the plan and the sample labels are cached, but the scoring stages
  are not, so a repeat can rank or include studies differently (27 rows at the rehearsal, 34 the first time).
- *Did you reuse earlier code?* No. Other repositories were read for ideas only; this pipeline was written in the
  hackathon window under this repository's Apache-2.0 licence.
- *What is not finished?* Protein studies get sample counts only when a curated sample table exists (about 28% of
  PRIDE); ribosome-profiling processing is designed, not built; one comparison per dataset; the cluster tier is
  nf-core, not ours. The full list is the README's "Limits" section.
