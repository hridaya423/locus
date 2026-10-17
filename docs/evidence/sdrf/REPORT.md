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
