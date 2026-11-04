import argparse
import json
import os
import re
import sys

from dotenv import load_dotenv

from . import process


def describe(facts: dict) -> str:
    parts = [facts["tissue"], facts["sample_type"].replace("_", " ")]
    if facts["case"] is not None:
        parts.append(f"case {facts['case']} · control {facts['control']}")
        if facts.get("mixed"):
            parts.append(f"mixed pools {facts['mixed']}")
    if facts.get("grain"):
        individuals = "unknown" if facts["individuals"] is None else facts["individuals"]
        parts.append(f"{individuals} individuals / {facts['source'].split()[0]} samples / {facts['runs']} runs" + (f" · {facts['excluded_pooled']} pooled left out" if facts["excluded_pooled"] else ""))
    elif facts["has_control"] is not None:
        parts.append("has controls" if facts["has_control"] else "no controls")
    return " · ".join(p for p in parts if p) + f"  (from {facts['source']})"


def process_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="omics process", description="Run one GEO bulk RNA-seq series from subsampled ENA reads to DESeq2 results and plots.")
    parser.add_argument("accession", help="a GEO series, such as GSE123456")
    parser.add_argument("--topic", default="", help="the search question the labels answer; defaults to the study title")
    parser.add_argument("--reads", type=int, default=process.READS, help="reads taken from the start of each FASTQ")
    parser.add_argument("--threads", type=int, default=process.THREADS)
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--tier", default="laptop", choices=["laptop", "riboseq-here", "riboseq-laptop", "scrnaseq-here"],
                        help="which run: the bulk RNA-seq laptop pipeline (default), or a single-cell / Ribo-seq row of the Process panel")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"GSE\d+", args.accession):
        parser.error("the accession must be a GEO series (GSE…)")

    load_dotenv()
    log = lambda msg: print(msg, file=sys.stderr, flush=True)
    stages = {
        "plan": "planning: sample records, labels and ENA runs",
        "reference": "reference: GENCODE transcripts and salmon index",
        "fetch": "fetching the first reads of each FASTQ from ENA",
        "quantify": "quantifying with salmon",
        "count": "counting: tximport, counts.tsv and .count files",
        "test": "testing: DESeq2 with apeglm, PCA, volcano and MA plots",
        "explain": "explaining: the model writes a paragraph from the numbers; code checks every number",
    }

    announced: set[str] = set()

    def progress(stage: str, data) -> None:
        if stage == "log":
            log(data)
        elif stage not in announced and stage != "done":
            announced.add(stage)
            log(stages.get(stage, f"{stage}…") + (f" ({data['count']} samples)" if isinstance(data, dict) and "count" in data else ""))

    try:
        if args.tier == "laptop":
            result = process.run(args.accession, args.topic, args.reads, args.threads, progress=progress)
        else:
            result = _row_run(args, progress)
    except (LookupError, ValueError) as error:
        sys.exit(f"cannot process {args.accession}: {error}")
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.tier == "laptop":
        print("\n".join(process.summary_lines(result)))
    else:
        print("\n".join(row_summary_lines(result)))


def _row_run(args, progress) -> dict:
    """A single-cell or Ribo-seq row from the Process panel, written under data/process/<GSE>/<tier>/."""
    out = process.out_dir(args.accession) / args.tier
    if args.tier == "scrnaseq-here":
        from . import singlecell
        return singlecell.run_here(args.accession, args.topic, out, progress=progress, threads=min(args.threads, 6))
    from . import riboseq
    if args.tier == "riboseq-here":
        return riboseq.run_here(args.accession, args.topic, out, progress=progress)
    return riboseq.run_laptop(args.accession, args.topic, out, reads=args.reads, threads=min(args.threads, 6), progress=progress)


def row_summary_lines(result: dict) -> list[str]:
    lines = [result["title"], *result.get("summary", []), *(f"warning: {w}" for w in result.get("warnings", [])),
             "figures:", *(f"  {f['file']}: {f['caption']}" for f in result.get("figures", [])), "files:",
             *(f"  {f['bytes']:>12,}  {f['name']}" for f in result.get("files", []))]
    if result.get("skipped"):
        lines += ["left out:", *(f"  {s['gsm']}: {s['reason']}" for s in result["skipped"])]
    return lines


def main() -> None:
    if sys.argv[1:2] == ["process"]:
        process_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(prog="omics", description="Find public omics datasets with a plain-English question.")
    parser.add_argument("question", help="a question, or 'process' to run a GEO series (see 'omics process --help')")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    parser.add_argument("--limit", type=int, default=agent.KEEP, help="how many triaged candidates to screen")
    args = parser.parse_args()

    load_dotenv()
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LOCAL_LLM_URL")):
        sys.exit("locus needs a model: set ANTHROPIC_API_KEY, or LOCAL_LLM_URL and LOCAL_LLM_MODEL for a local server, in .env (see .env.example).")
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
