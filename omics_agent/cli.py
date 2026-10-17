import argparse
import json
import sys

from dotenv import load_dotenv


def describe(facts: dict) -> str:
    parts = [facts["tissue"], facts["sample_type"].replace("_", " ")]
    if facts["case"] is not None:
        parts.append(f"case {facts['case']} · control {facts['control']}")
        if facts.get("mixed"):
            parts.append(f"mixed pools {facts['mixed']}")
    elif facts["has_control"] is not None:
        parts.append("has controls" if facts["has_control"] else "no controls")
    return " · ".join(p for p in parts if p) + f"  (from {facts['source']})"


def main() -> None:
    parser = argparse.ArgumentParser(prog="omics", description="Find public omics datasets with a plain-English question.")
    parser.add_argument("question")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    parser.add_argument("--limit", type=int, default=40, help="max candidates per repository")
    args = parser.parse_args()

    load_dotenv()
    from . import agent

    log = lambda msg: print(msg, file=sys.stderr)
    stages = {
        "plan": lambda p: f"terms: {', '.join(p['terms'])}\norganism: {p['organism'] or 'any'}  assays: {', '.join(p['assays'])}" + "".join(f"\nnote: {n}" for n in p['method_notes']),
        "candidates": lambda d: f"candidates: {d['count']}, checking relevance...",
        "screened": lambda d: f"relevant: {d['count']}, reading sample records...",
        "facts": lambda d: f"sample groups found for {d['count']}",
    }
    result = agent.run(args.question, args.limit, lambda stage, data: log(stages[stage](data)))

    if args.json:
        print(json.dumps(result, indent=2))
        return

    hits = result["datasets"]
    names = {h["accession"]: h["source"] for h in hits}
    for group in result["same_paper"]:
        print("\nSame paper, several data types: " + "  +  ".join(f"{a} ({names[a]})" for a in group))

    for h in hits:
        samples = f"{h['samples']} samples" if h["samples"] else ""
        print(f"\n[{h['fit']}] {h['accession']}  {h['source']}  {h['modality']}  {samples}")
        print(f"  {h['title']}")
        if h["facts"]:
            print(f"  facts: {describe(h['facts'])}")
        print("  checks: " + "  ".join(f"{k.replace('_', ' ')} {v}" for k, v in h["checks"].items()))
        print(f"  why: {h['reason']}")
        if h["evidence"]:
            print(f'  source says: "{h["evidence"]}"')
        print(f"  {h['url']}")
    log(f"\n{len(hits)} relevant of {result['candidates']} candidates")


if __name__ == "__main__":
    main()
