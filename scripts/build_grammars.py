"""Write omics_agent/grammars.json: for every JSON schema the agent sends to the local model, an EBNF grammar that
allows no newlines or indentation between tokens (xgrammar, any_whitespace=False), keyed by the schema's hash.
With LOCAL_LLM_COMPACT_JSON=1, agent._ask_local sends the grammar instead of the schema (see agent.py).

uv run --with xgrammar python scripts/build_grammars.py
"""

import json
from pathlib import Path

import xgrammar as xgr

from omics_agent import agent, explain, samples

# The plan schema is left out on purpose: one call per question, and under the no-whitespace grammar Qwen's plans
# repeated a search term in 3 of 9 and dropped the demo question's comparison terms (docs/evidence/qwen/fresh-plan-plangrammar/).
SCHEMAS = {
    "triage": agent.TRIAGE_SCHEMA,
    "screen": agent.SCREEN_SCHEMA,
    "contrast": agent.CONTRAST_SCHEMA,
    "labels": samples.LABEL_SCHEMA,
    "explain": explain.EXPLAIN_SCHEMA,
    **{f"triage compact {n}": agent._compact_schema(n) for n in range(1, agent.TRIAGE_BATCH + 1)},
    **{f"triage keyed {n}": agent._keyed_schema(n) for n in range(1, agent.TRIAGE_BATCH + 1)},
    # The numbered forms are sent with the batch's size fixed, for every batch size up to the larger batch setting.
    **{f"triage x{n}": agent._sized(agent.TRIAGE_SCHEMA, n) for n in range(1, max(agent.TRIAGE_BATCH, agent.SCREEN_BATCH) + 1)},
    **{f"screen x{n}": agent._sized(agent.SCREEN_SCHEMA, n) for n in range(1, max(agent.TRIAGE_BATCH, agent.SCREEN_BATCH) + 1)},
}


def main() -> None:
    out = {}
    for name, schema in SCHEMAS.items():
        out[agent.schema_key(schema)] = str(xgr.Grammar.from_json_schema(json.dumps(schema), any_whitespace=False))
        print(f"{name}: {agent.schema_key(schema)} ({len(out[agent.schema_key(schema)])} chars)")
    agent.GRAMMARS_FILE.write_text(json.dumps(out, indent=0))
    print(f"{len(out)} grammars written to {agent.GRAMMARS_FILE}")


if __name__ == "__main__":
    main()
