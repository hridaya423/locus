import json
import sys
import time

import anthropic
from dotenv import load_dotenv

from . import store

MODEL = "claude-haiku-5-5"
SOURCES = ("GEO", "CELLxGENE")
# Batch API prices for Claude Haiku 5.5, USD per million tokens (half the standard $0.10 / $0.50).
PRICE_IN, PRICE_OUT = 0.05, 0.25

SCHEMA = {
    "type": "object",
    "properties": {
        "diseases": {"type": "array", "items": {"type": "string"}, "description": "Diseases or conditions studied, standard names; empty if none"},
        "tissues": {"type": "array", "items": {"type": "string"}, "description": "Tissues, organs, or cell types sampled"},
        "sample_type": {
            "type": "string",
            "enum": ["patient_tissue", "patient_biofluid", "primary_cells", "cell_line", "animal_model", "organoid", "plant", "microbe", "other", "unclear"],
        },
        "design": {
            "type": "string",
            "enum": ["case_control", "treatment_vs_control", "genotype_comparison", "time_course", "atlas_or_reference", "other"],
        },
        "has_controls": {"type": "string", "enum": ["yes", "no", "unclear"], "description": "Healthy, untreated, or wild-type comparison samples are included"},
        "assay": {"type": "string", "description": "Short assay name, for example bulk RNA-seq, scRNA-seq, microarray, ChIP-seq, ATAC-seq"},
    },
    "required": ["diseases", "tissues", "sample_type", "design", "has_controls", "assay"],
    "additionalProperties": False,
}

PROMPT = """Tag this public omics dataset for a search index. Use only what the record says; use "unclear" or an empty list when it does not say.

Title: {title}
Organism: {organism}
Data type: {modality}
Summary: {summary}"""


def _request(accession: str, title: str, organism: str, modality: str, summary: str) -> dict:
    return {
        "custom_id": accession,
        "params": {
            "model": MODEL,
            "max_tokens": 400,
            "thinking": {"type": "disabled"},
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": PROMPT.format(title=title, organism=organism, modality=modality, summary=summary[:1500])}],
        },
    }


def submit(limit: int | None = None, sample: bool = False) -> list[str]:
    """Submit untagged GEO and CELLxGENE datasets as batches of up to 100,000 requests; returns batch IDs."""
    db = store.connect()
    order = "RANDOM()" if sample else "rowid"
    rows = db.execute(
        f"SELECT accession, title, organism, modality, summary FROM datasets "
        f"WHERE source IN {SOURCES} AND accession NOT IN (SELECT accession FROM annotations) ORDER BY {order}"
        + (f" LIMIT {limit}" if limit else "")
    ).fetchall()
    client = anthropic.Anthropic()
    ids = []
    for start in range(0, len(rows), 100_000):
        batch = client.messages.batches.create(requests=[_request(*r) for r in rows[start:start + 100_000]])
        ids.append(batch.id)
        print(f"submitted {batch.id}: {min(len(rows) - start, 100_000)} requests", flush=True)
    return ids


def collect(batch_id: str) -> dict:
    """Wait for a batch, store every successful tag, and return counts and token usage."""
    client = anthropic.Anthropic()
    while (batch := client.messages.batches.retrieve(batch_id)).processing_status != "ended":
        time.sleep(30)
    db = store.connect()
    stats = {"succeeded": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0}
    rows = []
    for result in client.messages.batches.results(batch_id):
        if result.result.type != "succeeded" or result.result.message.stop_reason != "end_turn":
            stats["failed"] += 1
            continue
        message = result.result.message
        text = next(b.text for b in message.content if b.type == "text")
        rows.append((result.custom_id, json.dumps({"tags": json.loads(text)})))
        stats["succeeded"] += 1
        stats["input_tokens"] += message.usage.input_tokens
        stats["output_tokens"] += message.usage.output_tokens
    db.executemany(
        "INSERT INTO annotations (accession, data) VALUES (?, ?) ON CONFLICT(accession) DO UPDATE SET data = json_patch(data, excluded.data)",
        rows,
    )
    db.commit()
    stats["cost_usd"] = (stats["input_tokens"] * PRICE_IN + stats["output_tokens"] * PRICE_OUT) / 1e6
    stats["elapsed_s"] = (batch.ended_at - batch.created_at).total_seconds()
    return stats


if __name__ == "__main__":
    load_dotenv()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    for batch_id in submit(limit, sample=limit is not None):
        print(json.dumps({"batch": batch_id, **collect(batch_id)}), flush=True)
