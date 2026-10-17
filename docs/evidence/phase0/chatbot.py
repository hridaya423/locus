import json, re, sys
import anthropic

client = anthropic.Anthropic()
question = (
    "I need matched RNA-seq and Ribo-seq data from human or mouse cells before and after mTOR inhibition "
    "(for example Torin1, rapamycin or INK128) to measure changes in translation efficiency. "
    "List the public datasets that fit, with their GEO accession, the number of treated and control samples, "
    "and whether every Ribo-seq library has a matched RNA-seq library."
)
with client.beta.messages.stream(
    model="claude-opus-5-5",
    max_tokens=16000,
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
    output_config={"effort": "medium"},
    tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
    messages=[{"role": "user", "content": question}],
) as stream:
    message = stream.get_final_message()
if message.stop_reason == "refusal":
    sys.exit(f"refused: {message.stop_details}")
text = "".join(b.text for b in message.content if b.type == "text")
open("/tmp/phase0/chatbot-answer.md", "w").write(text)
print(text)
print("\nACCESSIONS:", sorted(set(re.findall(r"GSE\d+", text))))
