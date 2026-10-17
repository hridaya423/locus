# Phase 2 (overnight 17–18 Oct): explain the result, and read PRIDE SDRF at sample level

Status: agreed with Juri at 23:55 BST on 17 October 2026, after the Phase 1 MVP (`2026-10-18-fastq-to-deseq2-mvp.md`) passed its acceptance criteria. Designed, not built, at the time of writing.

Decisions recorded tonight:

- Demo minute 2 stays **search → Process → plots on one dataset** (option A). Compare-through-pipeline is not attempted tonight.
- Add **"explain the result"** (2.1) because it is cheap, helps non-expert judges, and fits the "ready to interface with AI" brief.
- Add **SDRF sample-level counts for PRIDE** (2.2). It closes the documented gap "PRIDE sample files (SDRF) are not read yet" and the PRIDE metadata blocker from 17 Oct. The idea comes from reading hashkanna's msagent (no licence, no code copied): count individuals, samples and runs separately from SDRF, and report `unknown` rather than passing sample count off as patient count.
- Hridya's `locus` repo is a snapshot of this repo from 15:32 on 17 Oct and contains nothing extra; their overnight work is merged in the morning (meeting 09:00).
- Future, not tonight: an opt-in "advanced search" that activates the Nexus expert skills for niche questions.

## 2.1 Explain the result

After DESeq2, ask the model (the same `_ask` path locus uses, so it runs on the local model) for a short paragraph: what the contrast was, how many genes changed, what the strongest changes are and whether they are expected for this treatment, and what the subsampling means for the numbers.

- Input is only data we computed: the contrast, `deseq2_summary.json`, the top 15 genes with log2FC and padj, the study title and summary, and the read cap. The prompt tells the model to use only numbers from the input and to mark background knowledge as such ("DDIT4 is a known mTORC1 target").
- Guard in code: every number in the paragraph must appear in the input; otherwise the paragraph is dropped and a note says why. The model never writes a number we did not compute.
- Stored as `explanation` in `result.json`; printed by the CLI; shown in the results panel under a visible "Written by the model from the numbers above" label.
- Saved to `docs/evidence/process/<GSE>/explanation.md` for the slides.

## 2.2 SDRF sample-level counts for PRIDE

SDRF-Proteomics is a TSV with one row per raw file (run): `source name`, `characteristics[organism]`, `characteristics[organism part]`, `characteristics[disease]`, `characteristics[cell type]`, `characteristics[cell line]`, `characteristics[individual]`, `characteristics[biological replicate]`, `comment[label]` (label-free, TMT126…), `comment[instrument]`, `comment[fraction identifier]`, `comment[technical replicate]`, `comment[data file]`, plus `factor value[...]` columns naming the design factors.

Source: the Apache-2.0 corpus `bigbio/sdrf-annotated-datasets` (about 12k PRIDE projects with curated SDRF; cloned once into `data/sdrf/`, gitignored, with the commit recorded), and as a fallback the SDRF file PRIDE lists for the project (`sources.py` already detects `.sdrf` in the file list).

New module `omics_agent/sdrf.py`:

1. `sdrf_for(accession)` returns the parsed table or `None` (duplicate column names are kept; `NT=…;AC=…` cells reduce to the NT value; `not applicable` / `not available` are missing).
2. `sdrf_fields(table)` builds the same `dict[str, Counter]` shape `samples.geo_fields` returns, so `label_prompt`, `resolve_labels` and `count` work unchanged and the model again only chooses which field marks case vs control.
3. Counts are reported at three grains: **individuals** (distinct `characteristics[individual]`; `unknown` when the column is absent, never substituted), **samples** (distinct `source name`), **runs** (rows). Pooled, QC and reference rows (`characteristics[pooled sample]`, `pool`, `QC`, `reference` in label or source name) are excluded from case/control counts and reported separately.
4. `facts` for a PRIDE hit gains `grain`, `individuals`, `excluded_pooled`, and `libraries` per `comment[label]` / instrument, in the shape the GEO path uses.
5. Each check keeps a three-way verdict: when the deciding column is absent the result is `unclear`, not `no`.

Wired into `agent.py` where PRIDE hits get facts, the result card (count line reads "n individuals / n samples / n runs" with `unknown` shown as such), the MCP server (same facts object), and the README Limits section.

Tests: two or three real SDRF files vendored as fixtures under `tests/fixtures/sdrf/` (small ones, Apache-2.0, with the project accession in the filename): one label-free with individuals, one TMT with pooled reference channels, one without an individual column (must give `unknown`).

Evidence: `docs/evidence/sdrf/` with the facts JSON for five PRIDE projects and one sentence each on whether the counts match the paper.

## Acceptance criteria (Phase 2)

1. `uv run omics process GSE273888` prints the explanation; the number guard is tested (a paragraph with an invented number is rejected).
2. The results panel shows the explanation with its label; `npm run build` passes.
3. `uv run omics "<a proteomics question that returns PRIDE hits>"` shows at least three PRIDE hits with SDRF-derived counts, including one `unknown` individuals case; the facts come from code, not the model.
4. `uv run pytest` passes with the new SDRF tests.
5. README Limits updated; `docs/evidence/sdrf/` written; this file's status log updated.
6. All committed and pushed on `juri-processing-pipeline`; `git status` clean; `main` untouched.

Priority if time runs short: 1 → 2 → 4 → 3 → 5.

## Status log

- 2026-10-17 23:55 BST: spec written; no code yet.
- 2026-10-18 00:10 BST: Phase 1 pushed (commit 9d726cb); this spec found in the worktree and committed unchanged; work started in priority order 1 → 2 → 4 → 3 → 5.
- 2026-10-18 00:25 BST (2.1): `omics_agent/explain.py` written and wired into `process.run` as an `explain` stage; `uv run omics process GSE273888` exit 0, prints the paragraph; `explanation.md` next to the outputs and in `docs/evidence/process/GSE273888/`. The number guard is tested (an invented 12,000 and 30 are rejected; a paragraph with only computed numbers passes; a failed model call leaves a note). On the local model the first attempts narrated the task ("The note compares…", "All numbers are copied exactly from the prompt…") and once counted its own words (118, rejected by the guard); fixed by naming the schema field `answer_to_biologist`, anchoring the first words "We compared", capping the answer at 1,500 tokens, and cutting sentences that mention the rules (reported in the note). Final paragraph: "We compared three replicates of no_treatment against three replicates of 100_nm_rapamycin. The analysis identified 84 genes with adjusted p-value below 0.05, and the groups clearly separate on PC1, which explains 25% of the variance. The strongest changes include CCN2 (+1.219) and PPP1R12B (-2.276), while CCN2 is known to be a growth factor. Because only the first 2,000,000 reads were used, the counts are subsampled, which lowers the number of genes tested and the number called significant."
- 2026-10-18 00:25 BST (2.2): `omics_agent/sdrf.py` written; corpus cloned (`data/sdrf/`, commit b7d0b73f, 12,704 SDRF files, 746 MB); three real tables vendored under `tests/fixtures/sdrf/` (PXD027637 label-free with individuals, PXD042101 TMT with a pooled reference, PXD028392 without an individual column); 8 tests. The model labelled sperm, serum and lavage samples "cell_line", so the table's own cell line / material type / organism part columns now decide the sample type and the label is the fallback. Facts for five projects in `docs/evidence/sdrf/` with `REPORT.md`. Found on the way: the index on pgx is empty (`data/omics.db` 131 KB), so every search here runs on the live APIs; PRIDE's keyword search returns nothing for a phrase of three or more words, so the planned phrases found no PRIDE project at all (candidates: 0); `search_pride` now also tries each search term (50 hits, 24 with SDRF, for the Alzheimer CSF question).
- 2026-10-18 00:39 BST (2.2, acceptance 3): `uv run omics --json "proteomics of cerebrospinal fluid from Alzheimer's disease patients and healthy controls"`, 5 min 39 s on the local model: 19 PRIDE hits, 16 with SDRF-derived counts (4 with labelled case/control counts: PXD075438 2/2, PXD073336 32/30, PXD063590 2000/750 cells from 3 individuals, PXD020717 10/8), 12 with individuals "unknown". Table in `docs/evidence/sdrf/REPORT.md`, output in `search-alzheimer-csf.json`. An earlier run with the pre-override code lost every SDRF-labelled hit at grading because the model called tissue and fluid samples "cell_line"; the table's own columns now decide.

### Acceptance criteria at hand-over (2026-10-18 00:40 BST)

| # | Criterion | Result |
|---|---|---|
| 1 | `omics process GSE273888` prints the explanation; number guard tested | pass: exit 0, paragraph printed; 5 guard tests (invented 12,000 and 30 rejected; failed call → note; sentences about the rules cut) |
| 2 | Results panel shows the explanation with its label; `npm run build` passes | pass: `web-results-panel-crop.png` shows "Written by the model from the numbers above"; build and lint pass |
| 3 | ≥3 PRIDE hits with SDRF counts, one with unknown individuals, counts from code | pass: 16 of 19 hits, 12 unknown; counts from `sdrf.count`, the model only labelled the field |
| 4 | `uv run pytest` with SDRF tests | pass: 20 tests (8 pipeline, 5 explanation, 7 SDRF) |
| 5 | README Limits updated; `docs/evidence/sdrf/`; this status log | pass |
| 6 | Committed and pushed on `juri-processing-pipeline`, clean tree, `main` untouched | pass (see the final commit) |

Not done / limits: the SDRF facts are not yet wired into `compare.py` or shown in the MCP server beyond the facts object it already returns; "not labelled" PRIDE hits show samples/individuals/runs but no case/control; the corpus clone is manual (`git clone --depth 1 https://github.com/bigbio/sdrf-annotated-datasets data/sdrf`); the local model's explanation needed prompt tricks and may still need a re-run on another dataset.
