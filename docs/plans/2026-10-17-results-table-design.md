# Results table design

## Problem

The results list showed one tall card per dataset. A live fibrosis search returned 38 datasets, 25 graded "usable as is", which made a scroll of about 5,500 px. A scientist could not compare two datasets side by side. Each card repeated text that carried no new information:

- The model's reason sentence restated the title. 19 of 38 reasons started with "This is" or "This study".
- Every card showed "usable as is", although the cards already sat under a section with that name.
- A full-width case/control bar repeated the two numbers beside it.

## Design

Each grade is a table: one for "usable as is", and one for close matches, which is collapsed by default. A row has these columns:

| Column | Content |
|---|---|
| Select | Checkbox |
| Dataset | Line 1: accession, repository, year, assay, tissue and material. Line 2: the title. |
| Case | Count from sample records, with a thin bar scaled to the largest value in the column |
| Control | The same as Case. Pooled libraries show as "+N pooled". |
| Samples | Number of sample records |

- **Counts not taken from records.** The cell shows "–" and a tooltip that says the samples were not counted.
- **Sorting.** The scientist can sort by case, control, samples or year. The default sort is controls, then cases, highest first.
- **Filters.** Above the table, the scientist can toggle each repository and "counted only".
- **Expanded row.** Clicking a row shows the paper, failed checks, the source quote and the download plan. The reason sentence appears only for close matches, because there it explains what failed.
- **Same study.** Rows that share a paper are placed next to each other and marked "same study".
- **Selection.** Selecting rows shows a sticky bar. The bar can copy one combined download plan or export a CSV with these fields: accession, url, repository, year, assay, tissue, material, case, control, pooled, samples, counted, fit and paper.

## Decisions

- **Pooled libraries.** A pooled library holds patient and control cells together, as in a multiplexed single-cell run. GSE292589 has 2 case and 2 mixed libraries, and the backend counts it as having controls (`samples.py`). That rule stays unchanged. The table shows the pooled count, so the scientist can judge it.
- **Width.** The results stay in the 768 px column. On phones, the table hides the Samples column, and the tissue and assay move into the expanded row.
