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
