# SDRF sample-level counts: five PRIDE projects

Run on 18 October 2026 (00:18 BST) with `omics_agent.sdrf` on the curated tables of
[bigbio/sdrf-annotated-datasets](https://github.com/bigbio/sdrf-annotated-datasets) at commit `b7d0b73f` (Apache-2.0),
cloned into `data/sdrf/`. The local vLLM model (qwen38-unc) chose the case/control field through the same label prompt
the GEO path uses; code counted. The facts for each project are in `<accession>.facts.json`.

Three grains are kept apart: **individuals** (distinct `characteristics[individual]`; `null` means the table has no
such column, shown as "unknown"), **samples** (distinct `source name`) and **runs** (rows, one per raw file and label
channel). Pooled, QC and reference samples are left out of the case/control counts and reported as `excluded_pooled`.

| Project | Topic given | Case / control (samples) | Individuals | Runs | Pooled left out | Labels |
|---|---|---|---|---|---|---|
| PXD027637 | male infertility, sperm | 3 / 3 | 6 (3 / 3) | 6 | 0 | label-free |
| PXD042101 | endometriosis | 3 / 6 | 9 (3 / 6) | 120 | 1 | TMT |
| PXD028392 | Alzheimer's disease | 3 / 3 | unknown | 6 | 0 | label-free |
| PXD025522 | hepatocellular carcinoma, cirrhosis | 4 / 4 | unknown | 8 | 0 | label-free |
| PXD041457 | cystic fibrosis | 5 / 5 | 10 (5 / 5) | 60 | 4 | label-free |

Against the PRIDE project description (fetched from the PRIDE API on 18 October 2026):

- **PXD027637.** The description says 7 normozoospermic and 11 asthenozoospermic sperm samples; the curated SDRF lists
  6 runs (3 + 3) with one individual each. The count is right for the table and short of the paper's cohort: the SDRF
  covers only part of the study, which is why the count line names its source. The model labelled the sample type
  "cell_line" for sperm, which is wrong; the table's organism part (semen) overrides it to a biofluid, so the label never
  decides the patient-material check.
- **PXD042101.** Menstrual-fluid extracellular vesicles, TMT. The SDRF has 120 rows (10 samples × 12 fractions): 3
  endometriosis, 6 controls and one pooled reference, each sample from one individual. The description gives no cohort
  size to check against; the pooled channel was correctly left out.
- **PXD028392.** Alzheimer's serum autoantibody immunoprecipitation: 3 AD and 3 control runs, no individual column, so
  individuals are "unknown" rather than 6. The description does not state the number of sera in the MS arm.
- **PXD025522.** Serum extracellular vesicles in hepatocellular carcinoma: the field 'disease' has 4 HCC, 2 normal and 2
  cirrhosis; the labels put normal and cirrhosis together as controls (4 / 4). No individual column, so "unknown". The
  description does not give the number of patients.
- **PXD041457.** Bronchoalveolar lavage, cystic fibrosis vs disease controls: 14 samples of which 4 are pools (the
  description says samples were pooled by CF status and microbial diversity), leaving 5 + 5 individual samples from 10
  individuals, 60 runs. The pooled rows were excluded as intended; the description does not state the cohort size.

None of the five descriptions states a cohort size that the SDRF contradicts; one (PXD027637) states a larger cohort
than the SDRF covers. That is the expected failure mode of curated tables, and the reason the count line says "SDRF
samples" and never "patients".

## Live search: "proteomics of cerebrospinal fluid from Alzheimer's disease patients and healthy controls"

Run 18 October 2026 00:34–00:39 BST on the local model, live PRIDE API (the index on pgx is empty), after the
`search_pride` fix. Output in `search-alzheimer-csf.json`. 19 PRIDE hits shown, 16 with
SDRF-derived counts, 12 of them with an unknown number of individuals. "Not labelled"
means the model found no field whose values separate cases from controls (often because every sample is a case, or the
contrast is in a free-text column); the sample, individual and run counts are still shown.

| Project | Title | Case / control (samples) | Individuals | Samples | Runs | Pooled left out |
|---|---|---|---|---|---|---|
| PXD014557 | Microdissected brain tissue Alzheimer's | not labelled | 40 | 40 | 400 | 0 |
| PXD012059 | Ventriculomics analyses of autopsy AD tissue | not labelled | unknown | 6 | 6 | 0 |
| PXD075438 | Glycoproteomics of Human and Mouse Brains in Alzheimer’s Dis | 2 / 2 | unknown | 4 | 4 | 0 |
| PXD072063 | Association of tear fluid glutathione synthetase and glutath | not labelled | unknown | 60 | 60 | 0 |
| PXD073336 | Retinal proteome changes mirror brain pathology and reveal s | 32 / 30 | 16 | 62 | 62 | 0 |
| PXD063590 | Single cell proteomic analysis of human prefrontal cortex in | 2000 / 750 | 3 | 2928 | 2928 | 178 |
| PXD042026 | Targeting the Post-Synaptic Proteome in Alzheimer Disease wi | not labelled | unknown | 8 | 8 | 0 |
| PXD028282 | Microdissected pyramidal cell proteomics of Alzheimer brain  | not labelled | unknown | 10 | 10 | 0 |
| PXD023340 | APOE-Dependent Molecular Abnormalities in the Cerebrovascula | not labelled | unknown | 9 | 9 | 0 |
| PXD021718 | Proteome of systemic extracellular vesicles from sporadic an | not labelled | unknown | 15 | 15 | 0 |
| PXD020717 | Quantitative PTM Maps of Human Pathologic Tau Identify Patie | 10 / 8 | unknown | 18 | 18 | 0 |
| PXD020482 | Quantitative PTM Maps of Human Pathologic Tau Identify Patie | not labelled | unknown | 13 | 13 | 0 |
| PXD072965 | Post-translational regulation of human D-3-phosphoglycerate  | not labelled | unknown | 8 | 8 | 0 |
| PXD061828 | Familial Alzheimer disease mutation in SORL1 impairs release | not labelled | unknown | 7 | 7 | 0 |
| PXD032192 | Proteopathic tau seeds contain key similarities to mature pa | not labelled | unknown | 2 | 2 | 0 |
| PXD079144 | Serine-65 phosphorylated ubiquitin associates with soluble T | not labelled | 5 | 5 | 10 | 0 |

PXD063590 is single-cell proteomics: its "samples" are 2,928 cells from 3 individuals, which is exactly why the three
grains are shown separately. The hits are mostly brain tissue rather than CSF; that is the model's topic check, not the
SDRF counts, and is outside this phase.
