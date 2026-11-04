"""Profile locus's search on the local model: per question, the seconds each stage took, the model calls with their
tokens, the datasets returned, and recall against the Claude Opus 5.5 picks that this repository records.

uv run python scripts/qwen_baseline.py --out docs/evidence/qwen/baseline [--only 1,3] [--demo] [--warm]

Triage and screen answers are asked afresh (OMICS_FRESH_ANSWERS=1) unless --warm, so the timings are real model calls.
The plan and the sample labels stay cached, as they are in the app. The full Opus list (34 datasets) lived in
/tmp/locus-night on the machine that ran the comparison; only the picks named in progress.md, docs/evaluation.md and
docs/evidence/phase0 are known here, so recall is reported against those, in two tiers.
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

QUESTIONS = [
    "Matched RNA-seq and Ribo-seq before and after mTOR inhibition",
    "How isoforms of one gene differ in how efficiently they are translated",
    "Lung fibrosis single-cell and proteomics data from patients and healthy controls",
    "Phosphoproteomics of human liver cancer against normal liver tissue",
    "Plasma metabolomics in type 2 diabetes against healthy controls",
    "The gut microbiome of infants born by caesarean section against vaginal birth",
    "Mitochondrial proteomics from organelle immunoprecipitation",
    "Human immunopeptidomics",
]
# The demo study: GSE229705 (bulk) and GSE229253 (single-nucleus) should rank at the top. The question typed on the
# public site on 18 October is not stored on this machine; this wording targets the same study.
DEMO = "Bulk RNA-seq of tumour-adjacent normal lung tissue in early-stage lung adenocarcinoma, patients who relapsed against patients who did not"
# Opus 5.5 picks that the repository's own records name (see the module docstring). "sure" are quoted as Opus's picks;
# "probable" are named only in the context of the recall evaluation.
OPUS = {
    1: {"sure": ["GSE36892", "GSE35469"], "probable": []},
    2: {"sure": ["GSE69352", "GSE100007"], "probable": []},
    3: {"sure": ["GSE136831"], "probable": ["PXD028149"]},
    7: {"sure": ["PXD058312"], "probable": ["PXD017210"]},
    8: {"sure": ["PXD020186"], "probable": ["MSV000084172"]},
}


# Claude API list prices in USD per million tokens (the claude-api reference, cached 2026-10-06): input, output,
# cache read (0.1 x input), cache write (1.25 x input, 5-minute TTL). Local calls cost nothing here.
PRICES = {"claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125), "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50)}


def cost(call: dict) -> float:
    model = call.get("model") or ""
    rates = next((r for m, r in PRICES.items() if model.startswith(m)), None)
    if not rates:
        return 0.0
    return (call["tokens_in"] * rates[0] + call["tokens_out"] * rates[1] + call.get("cache_read", 0) * rates[2] + call.get("cache_write", 0) * rates[3]) / 1e6


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/evidence/qwen/baseline")
    parser.add_argument("--only", default="")
    parser.add_argument("--demo", action="store_true", help="also run the demo-study question")
    parser.add_argument("--warm", action="store_true", help="reuse remembered triage and screen answers")
    parser.add_argument("--summarize", action="store_true", help="only rewrite summary.md from an earlier results.json")
    args = parser.parse_args()
    if args.summarize:
        write_summary(json.loads((Path(args.out) / "results.json").read_text()), Path(args.out))
        return
    if not args.warm:
        os.environ["OMICS_FRESH_ANSWERS"] = "1"
    load_dotenv()
    from omics_agent import agent  # noqa: E402  (after the environment is set)

    if not agent.LOCAL_LLM_URL and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Neither LOCAL_LLM_URL (local model) nor ANTHROPIC_API_KEY (Claude) is set")
    print("model:", f"local {agent.LOCAL_LLM_MODEL} at {agent.LOCAL_LLM_URL}" if agent.LOCAL_LLM_URL else f"Claude planner {agent.PLANNER}, worker {agent.WORKER}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {int(n) for n in args.only.split(",") if n}
    runs = [(n, q) for n, q in enumerate(QUESTIONS, 1) if not only or n in only]
    if args.demo:
        runs.append((0, DEMO))
    results = []
    for n, question in runs:
        t0 = time.monotonic()
        result = agent.run(question)
        wall = round(time.monotonic() - t0, 1)
        calls = defaultdict(lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0,
                                     "seconds_sum": 0.0, "seconds_max": 0.0})
        for c in agent.TRACE:
            s = calls[c["stage"]]
            s["calls"] += 1
            s["tokens_in"] += c["tokens_in"]
            s["tokens_out"] += c["tokens_out"]
            s["cache_read"] += c.get("cache_read", 0)
            s["cache_write"] += c.get("cache_write", 0)
            s["cost_usd"] = round(s["cost_usd"] + cost(c), 5)
            s["seconds_sum"] = round(s["seconds_sum"] + c["seconds"], 1)
            s["seconds_max"] = max(s["seconds_max"], c["seconds"])
        rows = [(d["accession"], d["fit"]) for d in result["datasets"]]
        accs = [a for a, _ in rows]
        picks = OPUS.get(n, {"sure": [], "probable": []})
        recall = {tier: {a: (accs.index(a) + 1 if a in accs else None) for a in picks[tier]} for tier in ("sure", "probable")}
        strong = {tier: [a for a in picks[tier] if a in accs and dict(rows)[a] == "strong"] for tier in ("sure", "probable")}
        entry = {"n": n, "question": question, "wall_seconds": wall, "timings": result["timings"], "calls": dict(calls),
                 "cost_usd": round(sum(v["cost_usd"] for v in calls.values()), 4),
                 "candidates": result["candidates"], "rows": rows, "recall": recall, "strong": strong,
                 "demo_ranks": {a: (accs.index(a) + 1 if a in accs else None) for a in ("GSE229705", "GSE229253")} if n == 0 else None,
                 "trace": list(agent.TRACE)}
        results.append(entry)
        (out / "results.json").write_text(json.dumps(results, indent=1))
        t = result["timings"]
        print(f"q{n} {wall:.0f}s  plan {t.get('plan', 0):.0f}  gather {t.get('gather', 0):.0f}  triage {t.get('triage', 0):.0f}  "
              f"screen {t.get('screen', 0):.0f}  facts {t.get('facts', 0):.0f}  grade {t.get('grade', 0):.0f}  rows={len(rows)}  "
              f"calls: " + ", ".join(f"{k} {v['calls']}×({v['tokens_in']}→{v['tokens_out']} tok, max {v['seconds_max']:.0f}s)" for k, v in calls.items())
              + (f"  cost ${entry['cost_usd']:.3f}" if entry["cost_usd"] else "")
              + (f"  recall sure {sum(1 for v in recall['sure'].values() if v)}/{len(picks['sure'])} probable {sum(1 for v in recall['probable'].values() if v)}/{len(picks['probable'])}" if n else f"  demo ranks {entry['demo_ranks']}"),
              flush=True)
    write_summary(results, out)


def write_summary(results: list[dict], out: Path) -> None:
    lines = ["| q | wall s | plan | gather | triage | prefetch | screen | facts | grade | triage calls | screen calls | screen tok in→out | facts calls | rows | cost $ | Opus sure | Opus probable |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        t, c = r["timings"], r["calls"]
        sc, tc, fc = c.get("screen", {}), c.get("triage", {}), c.get("facts", {})
        sure = f"{sum(1 for v in r['recall']['sure'].values() if v)}/{len(r['recall']['sure'])}" if r["recall"]["sure"] else "–"
        prob = f"{sum(1 for v in r['recall']['probable'].values() if v)}/{len(r['recall']['probable'])}" if r["recall"]["probable"] else "–"
        lines.append(f"| {r['n'] or 'demo'} | {r['wall_seconds']:.0f} | {t.get('plan', 0):.0f} | {t.get('gather', 0):.0f} | {t.get('triage', 0):.0f} | {t.get('prefetch', 0):.0f} | {t.get('screen', 0):.0f} | {t.get('facts', 0):.0f} | {t.get('grade', 0):.0f} "
                     f"| {tc.get('calls', 0)} | {sc.get('calls', 0)} | {sc.get('tokens_in', 0)}→{sc.get('tokens_out', 0)} | {fc.get('calls', 0)} | {len(r['rows'])} | {r.get('cost_usd', 0):.3f} | {sure} | {prob} |")
    total_sure = sum(sum(1 for v in r["recall"]["sure"].values() if v) for r in results)
    n_sure = sum(len(r["recall"]["sure"]) for r in results)
    total_prob = sum(sum(1 for v in r["recall"]["probable"].values() if v) for r in results)
    n_prob = sum(len(r["recall"]["probable"]) for r in results)
    lines += ["", f"Recall: {total_sure} of {n_sure} sure Opus picks returned, {total_prob} of {n_prob} probable.",
              f"Total wall {sum(r['wall_seconds'] for r in results):.0f} s; estimated API cost ${sum(r.get('cost_usd', 0) for r in results):.3f} (list prices; 0 for the local model).",
              "Top rows: " + "; ".join(f"q{r['n']}: " + ", ".join(a for a, _ in r["rows"][:5]) for r in results),
              "Per question: " + "; ".join(f"q{r['n']}: " + ", ".join(f"{a} #{v}" if v else f"{a} missed" for tier in ("sure", "probable") for a, v in r["recall"][tier].items()) for r in results if r["n"] and (r["recall"]["sure"] or r["recall"]["probable"]))]
    demo = next((r for r in results if r["n"] == 0), None)
    if demo:
        lines.append(f"Demo question ranks: {demo['demo_ranks']} (top rows: {', '.join(a for a, _ in demo['rows'][:5])}).")
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
