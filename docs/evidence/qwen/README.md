# Qwen search profiling, 18–19 October 2026

The 19 October decisions and numbers are summarised in `../model-comparison.md` and in the run directory's ledger (`~/hillclimb/locus-modalities-20261019/ledger.tsv`).

Model: Qwen3.8-27B (FP8) served by vLLM on pgx (`LOCAL_LLM_URL`, thinking off). Index: the full local index
(888,335 datasets). Script: `scripts/qwen_baseline.py`; comparison: `scripts/qwen_compare.py`.

Each folder holds `results.json` (per question: wall seconds, seconds per stage, every model call with its stage, seconds
and tokens in and out, the rows returned with their grade, recall against the Opus picks, and for the demo question the
ranks of GSE229705 and GSE229253) and `summary.md` (the table).

| Folder | What | Conditions |
|---|---|---|
| `baseline/` | The 8 harness questions and the demo-study question, triage and screen answers asked afresh (`OMICS_FRESH_ANSWERS=1`), plans and labels cached as in the app | 21:55–23:12 BST; questions 3, 6 and 7 overlapped with other model users (a browser search and two pipeline builders), so their times are inflated |
| `compact-short/` | q1, q2, q3, q7 and the demo with `OMICS_TRIAGE_COMPACT=1 OMICS_SCREEN_SHORT=1` | 23:21–23:41 BST, quiet server; plans and labels cached from the baseline |
| `probe.json` | 19 Oct, idle server: output tokens per prompt shape and per-stream decode rate against concurrency (`scripts/qwen_probe.py`) |
| `v1-triage-compact/` | 19 Oct: `OMICS_TRIAGE_COMPACT=1` with the list length fixed by the schema, all 9 questions, cached plans. Rejected: recall 1/7 |
| `v2-compact-json/` | 19 Oct: no-whitespace grammar, q1–q3 only, stopped: the grammar let the model close answer lists early (54/48/57 of 60 screen answers) |
| `v3-compact-json-sized/` | 19 Oct: no-whitespace grammar with answer lists fixed to the batch size, all 9 questions, cached plans. **Accepted** |
| `v4-screen-batch-2/` | 19 Oct: variant 3 + `OMICS_SCREEN_BATCH=2`, all 9 questions, cached plans. **Accepted** (public-site load during its triage) |
| `v5-triage-keyed/` | 19 Oct: variant 4 + `OMICS_TRIAGE_KEYED=1` (scores keyed by candidate number), all 9 questions, cached plans. **Accepted** |
| `v6-screen-batch-3/` | 19 Oct: variant 5 with `OMICS_SCREEN_BATCH=3`, all 9 questions, cached plans. Rejected (screen 534 → 669 s); the measured fallback under public-site load |
| `control-v3-quiet/`, `control-v4-quiet/` | 19 Oct 14:02–14:16, server idle: variant 3's and variant 4's configurations on q1, q2 and the demo, back to back |
| `fresh-plan-final/` | 19 Oct 14:57–15:27: **the final configuration with cold caches**, all 9 questions (variants 3 + 4 + 5, plans pretty-printed). The headline before/after against `baseline/` |
| `fresh-plan-plangrammar/` | 19 Oct: fresh Qwen plans under the grammar (q1–q3 own run; q4–demo from the Gemini arm's fallback): plans repeated or lost terms, so the plan schema left the grammar route |
| `fresh-plan/` | 19 Oct 13:21–13:59: variants 3 + 4 with cold caches, all 9 questions (`LOCAL_LLM_COMPACT_JSON=1` for triage, screen and labels; `OMICS_SCREEN_BATCH=2`; plans pretty-printed). The Qwen arm of `../model-comparison.md` |
| `baseline-quiet/` | q1, q2, q7 and the demo with the baseline configuration again | after 23:42 BST, quiet server; the run-to-run noise control |

Recall is against the Opus 5.5 picks that this repository names (`progress.md`, `docs/evaluation.md`,
`docs/evidence/phase0/`): 7 "sure" (GSE36892, GSE35469; GSE69352, GSE100007; GSE136831; PXD058312; PXD020186) and
3 "probable" (PXD028149, PXD017210, MSV000084172). The full list of 34 from the 17–18 October night lived in
`/tmp/locus-night` on the laptop that ran it and is not in the repository.

What the baseline showed: the model decodes a single stream at about 5–7 tokens/s, so a stage's wall time is set by the
output tokens of its longest call; triage's `{n, score}` objects cost about 550 tokens a call, screening's reasons and
evidence about 460 tokens a call. The compact triage format (one list of scores) was returned with the wrong length in
most batches and fell back to the numbered form, so it bought nothing and stays off. The short screening note (reasons
under 15 words, evidence under 10) cut screening output tokens by about a fifth; whether it is kept is decided against
the noise control in the status log of `docs/plans/2026-10-19-modalities-overnight.md`.
