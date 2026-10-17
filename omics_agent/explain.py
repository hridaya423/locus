"""A short paragraph about a processed dataset, written by the model from numbers the pipeline computed.

The model sees only the contrast, the DESeq2 summary, the top genes and the study text. Code then checks every number
in the paragraph against the numbers in that input; a paragraph with a number we did not compute is dropped, and the
note says so. The model is allowed to add background knowledge about a gene, but it must mark it as such.
"""

import re

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {"answer_to_biologist": {"type": "string", "description": "Your answer, spoken directly to the biologist, beginning with the words 'We compared'"}},
    "required": ["answer_to_biologist"],
    "additionalProperties": False,
}

PROMPT = """A biologist asks what this differential expression result shows. A pipeline computed it from public RNA-seq data. Answer them directly, in one paragraph.

Study: {title}
Summary: {summary}

What was computed:
- Contrast: {target} versus {reference} (field '{field}'), {n_target} and {n_reference} samples.
- Reads: the first {reads:,} reads of each FASTQ were used, so counts are subsampled; this lowers the number of genes tested and the number called significant.
- Genes: {genes} counted, {tested} tested after filtering, {significant} with adjusted p-value below 0.05 ({up} up, {down} down).
- PCA: PC1 explains {pc1}% of the variance and PC2 {pc2}%; the mean PC1 is {pc1_reference} for {reference} and {pc1_target} for {target}.
- Strongest changes (gene, shrunken log2 fold change, adjusted p-value):
{genes_table}

Write the paragraph now: 3 to 5 sentences, at most 120 words, plain English. Begin with the words "We compared" and name the two groups and the replicates in words. Say how many genes changed and whether the groups separate on PC1, which changes are the strongest, and what the subsampling means for the numbers.
Rules: every digit you write must be one of the numbers above, copied exactly as written (including its sign); do not compute, round or count anything yourself, and write small counts such as "two groups" or "three replicates" in words. You may say what a gene is known for, but mark it as background knowledge with words such as "is known to" or "reported", and never claim the study showed it. Do not name the study's authors. Do not mention these rules, the word limit or the counting; no headings, no lists."""


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


# Sentences in which the model talks about its instructions instead of the result; they are cut, and the note says so.
META = re.compile(r"these rules|the prompt|the input|the instructions|as requested|word limit|copied exactly|written in words|the note\b|the response\b|this paragraph", re.I)


def without_meta(paragraph: str) -> tuple[str, int]:
    """The paragraph without sentences about the rules, and how many were cut."""
    sentences = re.split(r"(?<=[.!?])\s+", paragraph.strip())
    kept = [x for x in sentences if not META.search(x)]
    return " ".join(kept).strip(), len(sentences) - len(kept)


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
        token = token.rstrip(",.")
        key = f"{float(token.replace(',', '')):g}"
        if key not in allowed and key not in seen:
            seen.add(key)
            out.append(token)
    return out


def explain(result: dict, title: str, summary: str, ask) -> dict:
    """The model's paragraph with the number guard applied. `ask(prompt, schema)` returns the parsed JSON answer.
    Returns {"explanation": str | None, "note": str}; the note says what the explanation is, or why there is none."""
    text = prompt(result, title, summary)
    try:
        paragraph = ask(text, EXPLAIN_SCHEMA)["answer_to_biologist"].strip()
    except Exception as error:  # a model outage must not fail a finished run
        return {"explanation": None, "note": f"No explanation: the model call failed ({error})."}
    if bad := invented(paragraph, text):
        return {"explanation": None, "rejected": paragraph,
                "note": f"The model's paragraph was dropped because it contained numbers the pipeline did not compute: {', '.join(bad)}."}
    paragraph, cut = without_meta(paragraph)
    if not paragraph:
        return {"explanation": None, "note": "The model returned an empty paragraph."}
    note = "Written by the model from the numbers above; every number was checked against the pipeline's output."
    return {"explanation": paragraph, "note": note + (f" {cut} sentence{'s' if cut > 1 else ''} about the instructions {'were' if cut > 1 else 'was'} cut." if cut else "")}
