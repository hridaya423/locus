"""A short paragraph about a processed dataset, written by the model from numbers the pipeline computed.

The model sees only the contrast, the DESeq2 summary, the top genes and the study text. Code then checks every number
in the paragraph against the numbers in that input; a paragraph with a number we did not compute is dropped, and the
note says so. The model is allowed to add background knowledge about a gene, but it must mark it as such.
"""

import re

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {"explanation": {"type": "string", "description": "3 to 5 plain sentences for a biologist"}},
    "required": ["explanation"],
    "additionalProperties": False,
}

PROMPT = """You are writing a short note for a biologist about a differential expression result that a pipeline computed from public RNA-seq data.

Study: {title}
Summary: {summary}

What was computed:
- Contrast: {target} versus {reference} (field '{field}'), {n_target} and {n_reference} samples.
- Reads: the first {reads:,} reads of each FASTQ were used, so counts are subsampled; this lowers the number of genes tested and the number called significant.
- Genes: {genes} counted, {tested} tested after filtering, {significant} with adjusted p-value below 0.05 ({up} up, {down} down).
- PCA: PC1 explains {pc1}% of the variance and PC2 {pc2}%; the mean PC1 is {pc1_reference} for {reference} and {pc1_target} for {target}.
- Strongest changes (gene, shrunken log2 fold change, adjusted p-value):
{genes_table}

Write 3 to 5 sentences (at most 120 words) in plain English: what was compared, how many genes changed and whether the groups separate, which changes are the strongest, and what the subsampling means for the numbers.
Rules: every digit you write must be one of the numbers above, copied exactly as written (including its sign); do not compute, round or count anything yourself, and write small counts such as "two groups" or "three replicates" in words. You may say what a gene is known for, but mark it as background knowledge with words such as "is known to" or "reported", and never claim the study showed it. Do not name the study's authors. No headings, no lists."""


def prompt(result: dict, title: str, summary: str) -> str:
    c = result["contrast"]
    conditions = [s["condition"] for s in result["samples"]]
    rows = "\n".join(f"  {g['gene_name'] or g['gene_id']}: {g['log2fc']:+}, {g['padj']:g}" for g in result["top_genes"][:15])
    return PROMPT.format(
        title=title or result["accession"], summary=(summary or "not available")[:1500],
        target=c["target"], reference=c["reference"], field=c["field"],
        n_target=conditions.count(c["target"]), n_reference=conditions.count(c["reference"]), reads=result["reads_per_fastq"],
        genes=result["genes"], tested=result["genes_tested"], significant=result["significant"], up=result["up"], down=result["down"],
        pc1=result["pca"]["variance"][0], pc2=result["pca"]["variance"][1],
        pc1_reference=result["pca"]["means"][c["reference"]]["PC1"], pc1_target=result["pca"]["means"][c["target"]]["PC1"],
        genes_table=rows,
    )


# A number is digits with optional thousands commas, decimals and an exponent, not touching a letter or digit on either
# side, so KRT7, log2, PC1 and 4EBP1 are words, not numbers.
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")


def numbers(text: str) -> set[str]:
    """Every number in a text in a canonical form: no commas, no sign, numerically equal values alike (0.50 = 0.5)."""
    found = set()
    for token in NUMBER.findall(text):
        token = token.replace(",", "").rstrip(".")
        try:
            value = float(token)
        except ValueError:
            continue
        found.add(f"{value:g}")
    return found


def invented(paragraph: str, source: str) -> list[str]:
    """Numbers in the paragraph that do not appear in the source text, in order of appearance."""
    allowed = numbers(source)
    seen, out = set(), []
    for token in NUMBER.findall(paragraph):
        key = f"{float(token.replace(',', '').rstrip('.')):g}"
        if key not in allowed and key not in seen:
            seen.add(key)
            out.append(token)
    return out


def explain(result: dict, title: str, summary: str, ask) -> dict:
    """The model's paragraph with the number guard applied. `ask(prompt, schema)` returns the parsed JSON answer.
    Returns {"explanation": str | None, "note": str}; the note says what the explanation is, or why there is none."""
    text = prompt(result, title, summary)
    try:
        paragraph = ask(text, EXPLAIN_SCHEMA)["explanation"].strip()
    except Exception as error:  # a model outage must not fail a finished run
        return {"explanation": None, "note": f"No explanation: the model call failed ({error})."}
    if bad := invented(paragraph, text):
        return {"explanation": None, "rejected": paragraph,
                "note": f"The model's paragraph was dropped because it contained numbers the pipeline did not compute: {', '.join(bad)}."}
    if not paragraph:
        return {"explanation": None, "note": "The model returned an empty paragraph."}
    return {"explanation": paragraph, "note": "Written by the model from the numbers above; every number was checked against the pipeline's output."}
