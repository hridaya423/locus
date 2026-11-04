# Planner comparison, 19 October 2026: Gemini planning + Qwen against Qwen planning afresh

Decision (Juri, 11:51 BST): no Anthropic key exists, so the Haiku arm became **Gemini plan + Qwen rest**. Only the
planning call goes to Gemini (`gemini-flash-latest`, free tier, OpenAI-compatible endpoint, `PLAN_LLM_*` in
`omics_agent/agent.py`); triage, screening and labelling stay on pgx's Qwen. Both arms plan freshly (own `HOME`, own
`plans.json`), ask triage and screen answers afresh (`OMICS_FRESH_ANSWERS=1`), share the on-disk GEO sample records,
and run with the two speed switches accepted earlier that day (`LOCAL_LLM_COMPACT_JSON=1 OMICS_SCREEN_BATCH=2`).
Script: `scripts/qwen_baseline.py` through the run directory's `tools/run_gemini.sh`; report: `scripts/plan_compare.py`.

| Folder | What |
|---|---|
| `baseline/` | q1, q2, q3 planned on Gemini (`results.json` trace shows `gemini-flash-latest` for the plan call). The free tier allows 20 requests per day per model; it was exhausted at q4 (my one test call and the public site's searches used the rest), so q4–q8 and the demo question need a re-run after the quota returns (about 07:40 BST on 20 October). |
| `../qwen/fresh-plan/` | The same harness planned on Qwen afresh: q4–q8 and the demo came from the Gemini arm's run after its planner fell back to Qwen (same switches, same fresh caches; verified from the traces), q1–q3 from a separate run (`fresh-plan-q123`, folded in). |

Recall is against the Opus 5.5 picks named in this repository (see `../qwen/README.md`). The comparison of the two
planners therefore rests on q1–q3 today; the Qwen-fresh arm covers all 9 questions and is also the fair "cold cache"
measurement of the accepted speed switches (the 18 October baseline and the speed variants used cached plans and labels).
