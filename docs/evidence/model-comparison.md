# Model comparison, 19 October 2026

Two measured comparisons on the same code, database and nine harness questions (eight from Hridya's harness and the
demo-study question), in-process on pgx with `scripts/qwen_baseline.py`. Numbers below are from this run's
`results.json` files; nothing is quoted from memory.

1. **Planner:** Gemini (`gemini-flash-latest`, free tier) planning with Qwen doing the rest, against Qwen planning afresh.
   Juri's 11:51 decision replaced the Haiku arm with this one because no Anthropic key exists.
2. **Qwen speed:** the 18 October baseline against the configuration accepted today (`LOCAL_LLM_COMPACT_JSON=1`,
   `OMICS_SCREEN_BATCH=2`, and from variant 5 on `OMICS_TRIAGE_KEYED=1`), measured with cold caches for the first two.

Model: Qwen3.8-27B FP8 on vLLM 0.29 (pgx, GB10, `--enforce-eager`, thinking off), decoding about 5–7 tokens/s per
stream. Recall is against the Opus 5.5 picks this repository names (7 "sure", 3 "probable"; the full list of 34 is not
on this machine). Every run here asks triage and screen answers afresh (`OMICS_FRESH_ANSWERS=1`).

## 1. Planner: Gemini + Qwen against Qwen alone

**Setup.** Both arms: own plan cache (`HOME` under the run directory), fresh answers, shared GEO sample records,
the accepted speed switches on. The Gemini arm sends only the planning call to Gemini's OpenAI-compatible endpoint
(`PLAN_LLM_*`); its triage, screening and labelling ran on Qwen exactly as the other arm's. The Gemini free tier allows
20 requests a day per model and was exhausted after q3 (one test call and the public site's searches used the rest), so
**the planner comparison covers q1–q3**; q4–q8 and the demo need a Gemini re-run after the quota returns (about 07:40 BST
on 20 October). The Gemini arm ran 12:21–13:05 while the public site was also being searched, which slowed its triage
and screening stages (same calls as the Qwen arm's, which ran 13:21–13:59 on a quieter server).

| q | arm | wall s | plan | gather | triage | screen | facts | rows | plan call | model calls | tokens out | recall | demo ranks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | gemini | 328 | 22 | 12 | 103 | 64 | 126 | 55 | 3208→471 tok, 11 s on gemini-flash-latest | 84 | 15393 | 1/2 sure |  |
| 1 | qwen | 354 | 96 | 15 | 76 | 61 | 105 | 48 | 3610→637 tok, 96 s on qwen38-unc | 78 | 15418 | 1/2 sure |  |
| 2 | gemini | 321 | 10 | 2 | 108 | 105 | 95 | 43 | 3206→519 tok, 10 s on gemini-flash-latest | 77 | 13452 | 1/2 sure |  |
| 2 | qwen | 292 | 76 | 2 | 74 | 55 | 84 | 51 | 3607→510 tok, 76 s on qwen38-unc | 50 | 11690 | 1/2 sure |  |
| 3 | gemini | 284 | 13 | 2 | 82 | 96 | 85 | 48 | 3207→542 tok, 13 s on gemini-flash-latest | 89 | 14203 | 0/1 sure, 0/1 probable |  |
| 3 | qwen | 257 | 94 | 2 | 74 | 59 | 22 | 46 | 3609→616 tok, 94 s on qwen38-unc | 46 | 10802 | 0/1 sure, 0/1 probable |  |

- **gemini** over 3 questions: wall 934 s (plan 45, triage 293, screen 265, facts 306); sure Opus picks returned 2/5; q1: GSE36892 missed, GSE35469 #14; q2: GSE69352 #22, GSE100007 missed; q3: GSE136831 missed, PXD028149 missed.
- **qwen** over 3 questions: wall 903 s (plan 266, triage 224, screen 174, facts 211); sure Opus picks returned 2/5; q1: GSE36892 missed, GSE35469 #14; q2: GSE69352 #19, GSE100007 missed; q3: GSE136831 missed, PXD028149 missed.

q1 top 5: gemini: GSE312196, GSE225683, GSE241588, GSE129816, GSE263767; qwen: PRJEB93983, GSE225683, GSE241588, GSE132703, GSE118422
q2 top 5: gemini: GSE179525, PRJNA299254, E-MTAB-7382, PRJEB29402, PRJNA79987; qwen: PRJNA299254, PRJNA870904, GSE180669, GSE126736, E-MTAB-10452
q3 top 5: gemini: GSE159354, PRJNA507827, GSE122960, GSE331144, GSE326573; qwen: MSV000093129, PXD069424, PXD029341, PXD010965, PXD064472


**Reading.** Gemini plans a question in 10–13 s against 76–96 s on Qwen (one call, about 500 output tokens either way).
On these three questions the plans found the same sure picks (GSE35469 #14 in both arms, GSE69352 #22 against #19) and
overlapped in the top rows (GSE225683 and GSE241588 on q1, PRJNA299254 on q2). Gemini's plans leave `organism` empty on
q1 and q2 where Qwen's say Homo sapiens, which widens the pool, and Gemini's GEO queries are more specific (named
inhibitors on q1, `[Title/Description]` fields on q2). The per-question wall time ended about equal because the Gemini
arm's Qwen stages were slowed by other traffic; the planning saving itself is 60–85 s a question, which is what a user
of the public site waits before the first candidates appear. Cost: nothing on the free tier, which is also its limit;
a paid key would remove the 20-a-day cap.

Plans (search terms and GEO query per arm):
- q1 gemini: terms ['mTOR inhibition', 'mTOR inhibitor', 'rapamycin', 'Torin 1', 'Torin1', 'everolimus']; organism ''; assays ['RNA-seq', 'Ribo-seq']; repositories ['GEO', 'ArrayExpress', 'ENA', 'NODE']; geo_query '("mTOR" OR rapamycin OR "Torin 1" OR "Torin1" OR everolimus) AND ("Ribo-seq" OR "ribosome profiling" OR "ribosome footprinting") AND (vehicle[Description] OR control[Description] OR untreated[Description] OR DMSO[Description])'
- q1 qwen: terms ['mTOR', 'mTORC1', 'mTORC2', 'mTOR inhibitor', 'rapamycin', 'translation']; organism 'Homo sapiens'; assays ['RNA-seq', 'Ribo-seq']; repositories ['GEO', 'ArrayExpress', 'ENA', 'ExpressionAtlas']; geo_query '("mTOR"[Title] OR "mTOR"[Description] OR "mTORC1"[Title] OR "mTORC1"[Description] OR "mTORC2"[Title] OR "mTORC2"[Description] OR "rapamycin"[Title] OR "rapamycin"[Description] OR "torin"[Title] OR "torin"[Description] OR "mTOR inhibitor"[Title] OR "mTOR inhibitor"[Description]) AND ("Ribo-seq"[Title] OR "Ribo-seq"[Description] OR "ribosome profiling"[Title] OR "ribosome profiling"[Description] OR "polysome"[Title] OR "polysome"[Description] OR "translation"[Title] OR "translation"[Description]) AND ("control"[Description] OR "vehicle"[Description] OR "untreated"[Description] OR "DMSO"[Description])'
- q2 gemini: terms ['isoform-specific translation', 'translation efficiency', 'ribosome profiling', 'Ribo-seq', 'polysome profiling', 'alternative splicing translation']; organism ''; assays ['Ribo-seq', 'RNA-seq', 'Polysome-seq', 'long-read RNA-seq']; repositories ['GEO', 'ArrayExpress', 'ENA']; geo_query '("translation efficiency"[Title/Description] OR "isoform-specific translation"[Title/Description]) AND ("ribosome profiling"[Title/Description] OR "Ribo-seq"[Title/Description] OR "riboseq"[Title/Description] OR "polysome profiling"[Title/Description]) AND (isoform*[Title/Description] OR "alternative splicing"[Title/Description])'
- q2 qwen: terms ['isoform-specific translation', 'alternative splicing', 'ribosome profiling', 'translational efficiency', 'mRNA isoforms']; organism 'Homo sapiens'; assays ['Ribo-seq', 'RNA-seq']; repositories ['GEO', 'ENA', 'ArrayExpress']; geo_query '("ribosome profiling"[Title] OR "Ribo-seq"[Title] OR "ribosome footprinting"[Title] OR "translational efficiency"[Title] OR "isoform-specific translation"[Title]) AND ("alternative splicing"[Description] OR "isoform"[Description] OR "splice variant"[Description] OR "mRNA isoforms"[Description])'
- q3 gemini: terms ['lung fibrosis', 'pulmonary fibrosis', 'idiopathic pulmonary fibrosis', 'IPF']; organism 'Homo sapiens'; assays ['scRNA-seq', 'snRNA-seq', 'mass spectrometry proteomics', 'LC-MS/MS']; repositories ['GEO', 'ArrayExpress', 'ENA', 'CELLxGENE', 'PRIDE', 'MassIVE', 'iProX', 'jPOST']; geo_query '("pulmonary fibrosis"[Title] OR "idiopathic pulmonary fibrosis"[Title] OR "lung fibrosis"[Title] OR IPF[Title]) AND ("single cell"[Description] OR "single-cell"[Description] OR scRNA[Description] OR "single nucleus"[Description] OR snRNA[Description] OR proteom*[Description]) AND (control[Description] OR healthy[Description] OR normal[Description] OR donor[Description])'
- q3 qwen: terms ['lung fibrosis', 'idiopathic pulmonary fibrosis', 'IPF', 'pulmonary fibrosis', 'interstitial lung disease']; organism 'Homo sapiens'; assays ['scRNA-seq', 'DIA proteomics']; repositories ['GEO', 'CELLxGENE', 'PRIDE', 'MassIVE', 'iProX', 'jPOST']; geo_query '("lung fibrosis"[Title] OR "idiopathic pulmonary fibrosis"[Title] OR "IPF"[Title] OR "pulmonary fibrosis"[Title] OR "interstitial lung disease"[Title]) AND ("single-cell"[Description] OR "scRNA-seq"[Description] OR "proteomics"[Description] OR "mass spectrometry"[Description]) AND ("healthy"[Description] OR "control"[Description] OR "normal"[Description])'

## 2. Qwen speed: the 18 October baseline against today's accepted configuration

The speed variants (`../hillclimb/locus-modalities-20261019/ledger.tsv`, folders under `docs/evidence/qwen/`) were
measured with the baseline's cached plans and labels, so their wall times leave out planning. The fresh-Qwen arm above
is the clean comparison: cold plan cache, cold answers, the final configuration.

| run | wall s | plan | triage | screen | facts | sure recall | demo ranks (GSE229705, GSE229253) | rows per question |
|---|---|---|---|---|---|---|---|---|
| baseline, 18 Oct (plans computed in the run, pretty-printed answers, screen batches of 4) | 4665 | 909 | 1508 | 1360 | 822 | 2/7 | 1, 15 | 44, 39, 51, 53, 40, 43, 60, 56, 48 |
| variant 3: no-whitespace grammar, cached plans | 1440 | 0 | 549 | 762 | 85 | 2/7 | 3, 16 | 42, 43, 51, 46, 39, 52, 60, 60, 39 |
| variant 4: + screen batches of 2, cached plans (public-site load during triage) | 1493 | 0 | 784 | 594 | 66 | 2/7 | 1, 10 | 45, 50, 51, 50, 36, 51, 60, 60, 40 |
| variant 5: + keyed triage scores, cached plans | 1115 | 0 | 344 | 534 | 189 | 2/7 | 1, 12 | 55, 43, 52, 51, 42, 53, 60, 58, 37 |
| **variants 3 + 4, cold caches (the fresh-Qwen arm, 19 Oct 13:21–13:59; before variant 5)** | **2252** | 721 | 682 | 536 | 251 | 2/7 | 1, 9 | 48, 51, 46, 48, 43, 52, 58, 60, 34 |
| **final configuration (variants 3 + 4 + 5), cold caches (`qwen/fresh-plan-final/`, 19 Oct 14:57–15:27)** | **1860** | 743 | 327 | 553 | 193 | 2/7 | 1, 10 | 52, 44, 51, 52, 36, 53, 60, 60, 42 |

Over the nine questions, cold caches to cold caches, 18 October against the final configuration: wall 4665 → 1860 s,
planning 909 → 743 s (the plan call stays pretty-printed on purpose; all nine fresh plans have the 18 October search
terms, so the candidate pools match), triage 1508 → 327 s, screen 1360 → 553 s, recall 2/7 → 2/7 with
the same two picks (GSE35469 5th, GSE69352 26th), demo study 1st in both (GSE229253 15th → 10th). Facts
822 → 193 s is not a like-for-like number: today's runs found most labels cached from earlier runs.

Where the time went and what changed: vLLM pretty-prints every schema-constrained answer, and on this server a stage's
wall time is its longest call's output tokens at about 5 tokens/s. Sending a no-whitespace grammar instead of the schema
cut triage from 554 to 322 output tokens a call and screening from about 460 to 370, with the same fields and values
(`docs/evidence/qwen/probe.json`, `README.md`). Screening batches of 2 shorten the longest screening call further, and keyed triage scores (one object, a score under each candidate's number) cut a triage call to 167 tokens with the alignment guaranteed by the required keys.
Two things did not survive: the one-list triage format (variant 1, coarser scores, recall 1/7) and applying the grammar
to the plan call (`fresh-plan-plangrammar/`: a repeated term in 3 of 9 plans, GSE229705 6th on the demo).

## Caveats

- Three questions for the planner comparison; the Gemini quota resets at about 07:40 on 20 October.
- The vLLM server is shared with the public site. Juri was searching on it during variant 4 and the Gemini arm; the
  affected stages are named in the run log. A quiet control at 14:02–14:16 (q1, q2 and the demo, cached plans, server
  otherwise idle) gave variant 3's configuration 477 s (triage 213, screen 250) and variant 4's 352 s (triage 175,
  screen 163), same recall, GSE229705 1st in both (`qwen/control-v3-quiet/`, `control-v4-quiet/`).
- Row counts vary between runs of one configuration (q2 returned 43 rows in the variant 3 run and 21 in its control),
  so recall and the demo rank are the stable quality signals, not the number of rows.
- Recall is against 7 sure and 3 probable picks, not the full Opus list; 2 of 7 is the bar every accepted change met.
- Per-call API tokens and costs are recorded for Claude and Gemini calls (`cost_usd` is 0 for local and free-tier calls).
