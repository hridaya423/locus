"""Before-and-after for a Qwen speed change: stage seconds, screen/triage calls and tokens, recall and top rows per
question, from two results.json files written by scripts/qwen_baseline.py.

uv run python scripts/qwen_compare.py docs/evidence/qwen/baseline docs/evidence/qwen/<variant>
"""

import json
import sys
from pathlib import Path


def load(path: str) -> dict[int, dict]:
    return {r["n"]: r for r in json.loads((Path(path) / "results.json").read_text())}


def recall(r: dict) -> str:
    sure = r["recall"]["sure"]
    prob = r["recall"]["probable"]
    parts = []
    if sure:
        parts.append(f"{sum(1 for v in sure.values() if v)}/{len(sure)} sure")
    if prob:
        parts.append(f"{sum(1 for v in prob.values() if v)}/{len(prob)} probable")
    return ", ".join(parts) or "–"


def main() -> None:
    before, after = load(sys.argv[1]), load(sys.argv[2])
    shared = [n for n in before if n in after]
    print("| q | wall before → after | triage s | screen s | facts s | screen calls, tokens out | triage calls, tokens out | rows | recall before → after | top-5 overlap |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for n in shared:
        b, a = before[n], after[n]
        tb, ta = b["timings"], a["timings"]
        cb, ca = b["calls"], a["calls"]
        top_b, top_a = [x for x, _ in b["rows"][:5]], [x for x, _ in a["rows"][:5]]
        overlap = len(set(top_b) & set(top_a))
        print(f"| {n or 'demo'} | {b['wall_seconds']:.0f} → {a['wall_seconds']:.0f} | {tb.get('triage', 0):.0f} → {ta.get('triage', 0):.0f} | {tb.get('screen', 0):.0f} → {ta.get('screen', 0):.0f} "
              f"| {tb.get('facts', 0):.0f} → {ta.get('facts', 0):.0f} | {cb.get('screen', {}).get('calls', 0)}, {cb.get('screen', {}).get('tokens_out', 0)} → {ca.get('screen', {}).get('calls', 0)}, {ca.get('screen', {}).get('tokens_out', 0)} "
              f"| {cb.get('triage', {}).get('calls', 0)}, {cb.get('triage', {}).get('tokens_out', 0)} → {ca.get('triage', {}).get('calls', 0)}, {ca.get('triage', {}).get('tokens_out', 0)} "
              f"| {len(b['rows'])} → {len(a['rows'])} | {recall(b)} → {recall(a)} | {overlap}/5 |")
    for n in shared:
        b, a = before[n], after[n]
        print(f"q{n or 'demo'} top 5 before: {', '.join(x for x, _ in b['rows'][:5])}; after: {', '.join(x for x, _ in a['rows'][:5])}")
        if n == 0:
            print(f"  demo ranks before {b['demo_ranks']} after {a['demo_ranks']}")
    tot = lambda rs, key: sum(r["timings"].get(key, 0) for r in rs)
    bs, as_ = [before[n] for n in shared], [after[n] for n in shared]
    print(f"\nTotals over {len(shared)} questions: wall {sum(r['wall_seconds'] for r in bs):.0f} → {sum(r['wall_seconds'] for r in as_):.0f} s; "
          f"triage {tot(bs, 'triage'):.0f} → {tot(as_, 'triage'):.0f}; screen {tot(bs, 'screen'):.0f} → {tot(as_, 'screen'):.0f}; facts {tot(bs, 'facts'):.0f} → {tot(as_, 'facts'):.0f}.")
    sure_b = sum(sum(1 for v in r["recall"]["sure"].values() if v) for r in bs)
    sure_a = sum(sum(1 for v in r["recall"]["sure"].values() if v) for r in as_)
    n_sure = sum(len(r["recall"]["sure"]) for r in bs)
    print(f"Sure Opus picks returned: {sure_b}/{n_sure} → {sure_a}/{n_sure}.")


if __name__ == "__main__":
    main()
