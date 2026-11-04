"""The planner comparison: per question and stage, wall time, calls, tokens, recall and demo ranks for two or more arms
written by scripts/qwen_baseline.py (for example Gemini planning + Qwen against Qwen planning afresh), as Markdown.

uv run python scripts/plan_compare.py gemini=docs/evidence/gemini-plan/baseline:<home> qwen=docs/evidence/qwen/fresh-plan:<home> [...]

The optional <home> is the HOME the arm ran with; its .cache/omics-agent/plans.json supplies the plans themselves.
"""

import json
import sys
from pathlib import Path


def load(path: str) -> dict[int, dict]:
    return {r["n"]: r for r in json.loads((Path(path) / "results.json").read_text())}


def recall(r: dict) -> str:
    parts = []
    for tier in ("sure", "probable"):
        if r["recall"][tier]:
            parts.append(f"{sum(1 for v in r['recall'][tier].values() if v)}/{len(r['recall'][tier])} {tier}")
    return ", ".join(parts) or "–"


def plan_tokens(r: dict) -> str:
    p = r["calls"].get("plan")
    if not p:
        return "cached"
    model = next((c.get("model", "") for c in r["trace"] if c["stage"] == "plan"), "")
    return f"{p['tokens_in']}→{p['tokens_out']} tok, {p['seconds_max']:.0f} s on {model}"


def main() -> None:
    arms = {a.split("=", 1)[0]: a.split("=", 1)[1].split(":") for a in sys.argv[1:]}
    data = {name: load(spec[0]) for name, spec in arms.items()}
    plans = {name: json.loads((Path(spec[1]) / ".cache" / "omics-agent" / "plans.json").read_text()) if len(spec) > 1 else {} for name, spec in arms.items()}
    questions = sorted(set.intersection(*(set(d) for d in data.values())), key=lambda n: (n == 0, n))
    print("| q | arm | wall s | plan | gather | triage | screen | facts | rows | plan call | model calls | tokens out | recall | demo ranks |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n in questions:
        for name, d in data.items():
            r = d[n]
            t = r["timings"]
            calls = sum(v["calls"] for v in r["calls"].values())
            out = sum(v["tokens_out"] for v in r["calls"].values())
            print(f"| {n or 'demo'} | {name} | {r['wall_seconds']:.0f} | {t.get('plan', 0):.0f} | {t.get('gather', 0):.0f} | {t.get('triage', 0):.0f} "
                  f"| {t.get('screen', 0):.0f} | {t.get('facts', 0):.0f} | {len(r['rows'])} | {plan_tokens(r)} | {calls} | {out} | {recall(r)} | {r.get('demo_ranks') or ''} |")
    print()
    for name, d in data.items():
        rs = [d[n] for n in questions]
        tot = lambda k: sum(r["timings"].get(k, 0) for r in rs)
        sure = sum(sum(1 for v in r["recall"]["sure"].values() if v) for r in rs)
        n_sure = sum(len(r["recall"]["sure"]) for r in rs)
        print(f"- **{name}** over {len(rs)} questions: wall {sum(r['wall_seconds'] for r in rs):.0f} s (plan {tot('plan'):.0f}, triage {tot('triage'):.0f}, "
              f"screen {tot('screen'):.0f}, facts {tot('facts'):.0f}); sure Opus picks returned {sure}/{n_sure}; "
              + "; ".join(f"q{r['n'] or 'demo'}: " + ", ".join(f"{a} #{v}" if v else f"{a} missed" for tier in ("sure", "probable") for a, v in r["recall"][tier].items()) for r in rs if r["recall"]["sure"] or r["recall"]["probable"]) + ".")
    print()
    for n in questions:
        print(f"q{n or 'demo'} top 5: " + "; ".join(f"{name}: " + ", ".join(a for a, _ in d[n]["rows"][:5]) for name, d in data.items()))
    print()
    print("Plans (search terms and GEO query per arm):")
    for n in questions:
        for name, d in data.items():
            q = " ".join(d[n]["question"].lower().split())
            plan = next((v for k, v in plans[name].items() if k.endswith(" " + q)), None)
            if plan:
                print(f"- q{n or 'demo'} {name}: terms {plan.get('terms')}; organism {plan.get('organism')!r}; assays {plan.get('assays')}; "
                      f"repositories {plan.get('repositories')}; geo_query {plan.get('geo_query')!r}")


if __name__ == "__main__":
    main()
