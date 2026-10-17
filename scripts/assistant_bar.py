"""The milestone bar: Claude Opus 5.5 with web search answers the harness questions, so a critic can compare it with locus.

uv run python scripts/assistant_bar.py [--out DIR] [--only 1,3]
Stops before the night's cap ($5 for Opus 5.5) and records the spend per question.
"""

import argparse
import json
from pathlib import Path

import anthropic
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
ASK = ("I am a researcher. Find me public datasets for this question: {q}. For each dataset give the accession, "
       "the repository, why it fits, the number of case and control samples, and how I get the processed data. "
       "Then tell me which one I should start with.")
CAP = 4.5
PRICE = {"input": 4 / 1e6, "output": 20 / 1e6, "cache_read": 0.2 / 1e6, "search": 10 / 1000}


def cost(usage) -> float:
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    return (usage.input_tokens * PRICE["input"] + usage.output_tokens * PRICE["output"]
            + (usage.cache_read_input_tokens or 0) * PRICE["cache_read"] + searches * PRICE["search"])


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/locus-night/assistant")
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "spend.json"
    spent = json.loads(ledger.read_text())["total"] if ledger.exists() else 0.0
    only = {int(n) for n in args.only.split(",") if n}
    client = anthropic.Anthropic()
    for n, question in enumerate(QUESTIONS, 1):
        if (only and n not in only) or (out / f"{n}.json").exists():
            continue
        if spent >= CAP:
            print(f"stopped at ${spent:.2f}, the cap is ${CAP}")
            break
        with client.beta.messages.stream(
            model="claude-opus-5-5",
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
            messages=[{"role": "user", "content": ASK.format(q=question)}],
        ) as stream:
            response = stream.get_final_message()
        text = "\n".join(b.text for b in response.content if b.type == "text")
        dollars = cost(response.usage)
        spent += dollars
        (out / f"{n}.json").write_text(json.dumps({"question": question, "answer": text, "stop_reason": response.stop_reason,
                                                   "model": response.model, "dollars": round(dollars, 4)}, indent=1))
        ledger.write_text(json.dumps({"total": round(spent, 4)}))
        print(f"q{n} ${dollars:.3f} (total ${spent:.2f}) {response.stop_reason}")


if __name__ == "__main__":
    main()
