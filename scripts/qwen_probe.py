"""Single calls against the local model, timed: how many output tokens each prompt shape costs, and whether the
per-stream decode rate holds as more calls run at once. Not a harness run; it informs which speed variant to try.

uv run python scripts/qwen_probe.py [--out docs/evidence/qwen/probe.json]
"""

import argparse
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
from omics_agent import agent, samples, store  # noqa: E402
from omics_agent.sources import Dataset  # noqa: E402

QUESTION = "Lung fibrosis single-cell and proteomics data from patients and healthy controls"


def datasets(n: int, offset: int = 0) -> list[Dataset]:
    db = sqlite3.connect(store.DB)
    rows = db.execute("SELECT accession, source, modality, organism, title, summary, url FROM datasets WHERE source='GEO' "
                      "AND summary LIKE '%fibrosis%' LIMIT ? OFFSET ?", (n, offset)).fetchall()
    return [Dataset(accession=a, source=s, modality=m, title=t, organism=o, samples=None, url=u, text=f"{t}. {sm}") for a, s, m, o, t, sm, u in rows]


def timed(label: str, prompt: str, schema: dict) -> dict:
    agent.TRACE.clear()
    t0 = time.monotonic()
    try:
        agent._ask(prompt, schema, effort="low", think=False)
        err = ""
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    tr = agent.TRACE[-1] if agent.TRACE else {}
    out = {"label": label, "seconds": round(time.monotonic() - t0, 1), "tokens_in": tr.get("tokens_in"), "tokens_out": tr.get("tokens_out"), "error": err}
    print(json.dumps(out), flush=True)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/evidence/qwen/probe.json")
    args = p.parse_args()
    results = {"single": [], "concurrency": []}
    batch25 = datasets(25)
    batch4 = batch25[:4]
    tri = agent.TRIAGE_PROMPT.replace("{question}", QUESTION).replace("{listing}", agent._listing(batch25, agent.TRIAGE_CHARS))
    results["single"].append(timed("triage numbered x25", tri, agent.TRIAGE_SCHEMA))
    results["single"].append(timed("triage compact x25", tri + agent.TRIAGE_COMPACT_NOTE, agent.TRIAGE_COMPACT_SCHEMA))
    scr = agent.SCREEN_PROMPT.replace("{question}", QUESTION).replace("{listing}", agent._listing(batch4, agent.SCREEN_CHARS))
    results["single"].append(timed("screen x4", scr, agent.SCREEN_SCHEMA))
    results["single"].append(timed("screen short x4", scr + agent.SCREEN_SHORT_NOTE, agent.SCREEN_SCHEMA))
    scr2 = agent.SCREEN_PROMPT.replace("{question}", QUESTION).replace("{listing}", agent._listing(batch4[:2], agent.SCREEN_CHARS))
    results["single"].append(timed("screen short x2", scr2 + agent.SCREEN_SHORT_NOTE, agent.SCREEN_SCHEMA))
    d = batch4[0]
    fields = samples.geo_fields(d.accession)
    results["single"].append(timed(f"label {d.accession}", samples.label_prompt("lung fibrosis", d.accession, fields, d.text[:2000]), samples.LABEL_SCHEMA))
    results["single"].append(timed(f"label {d.accession} again", samples.label_prompt("lung fibrosis", d.accession, fields, d.text[:2000]), samples.LABEL_SCHEMA))
    # Concurrency: N compact triage calls on distinct batches at once (about 60 tokens out each).
    for n in (1, 8, 16, 32):
        batches = [datasets(25, 25 * (i + 1)) for i in range(n)]
        prompts = [agent.TRIAGE_PROMPT.replace("{question}", QUESTION).replace("{listing}", agent._listing(b, agent.TRIAGE_CHARS)) + agent.TRIAGE_COMPACT_NOTE for b in batches]
        agent.TRACE.clear()
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=n) as pool:
            list(pool.map(lambda pr: agent._ask(pr, agent.TRIAGE_COMPACT_SCHEMA, effort="low", think=False), prompts))
        wall = round(time.monotonic() - t0, 1)
        secs = sorted(c["seconds"] for c in agent.TRACE)
        outs = [c["tokens_out"] for c in agent.TRACE]
        row = {"n": n, "wall": wall, "call_s_min": secs[0], "call_s_max": secs[-1], "tokens_out_mean": round(sum(outs) / len(outs), 1),
               "tok_per_s_per_stream": round(sum(outs) / len(outs) / secs[-1], 2)}
        print(json.dumps(row), flush=True)
        results["concurrency"].append(row)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
