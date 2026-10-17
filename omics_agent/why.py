"""Where a search's terms and quote appear in one dataset's own record, as character offsets into the record's texts.

Every match is an exact span of the record's title, a text or a fact value, never generated. Offsets count Unicode code points.
"""

import re

from . import record

# Hyphens, dashes and spaces are interchangeable, and optional: scRNA-seq, scRNAseq and "sc RNA seq" are one term.
SEP = r"[\s\-‐-―]*"
# Spelled-out forms of the short assay names the planner uses.
EXPANDED = {"seq": r"seq(?:uencing)?", "scrna": r"(?:scRNA|single[\s\-]*cell\s+RNA)", "snrna": r"(?:snRNA|single[\s\-]*nucle(?:us|i)\s+RNA)"}


def _word(token: str, last: bool) -> str:
    if (expanded := EXPANDED.get(token.lower())):
        return expanded
    if not last or len(token) < 3:
        return re.escape(token)
    lower = token.lower()
    if lower.endswith("ies"):
        return re.escape(token[:-3]) + "(?:y|ies)"
    if lower.endswith("y") and lower[-2] not in "aeiou":
        return re.escape(token[:-1]) + "(?:y|ies)"
    if lower.endswith("s") and not lower.endswith(("ss", "is", "us")):
        return re.escape(token[:-1]) + "s?"
    return re.escape(token) + "(?:s|es)?"


def _pattern(term: str) -> re.Pattern:
    tokens = [t for t in re.split(r"[\s\-‐-―]+", term.strip()) if t]
    body = SEP.join(_word(t, i == len(tokens) - 1) for i, t in enumerate(tokens))
    return re.compile(rf"(?<!\w){body}(?!\w)", re.I)


def _fields(rec: dict) -> list[dict]:
    """Every string of the record that can match, in the order the page shows them."""
    out = [{"field": "Title", "kind": "title", "index": 0, "text": rec["title"]}]
    out += [{"field": label, "kind": "text", "index": i, "text": text} for i, (label, text) in enumerate(rec["texts"])]
    out += [{"field": label, "kind": "fact", "index": i, "value": j, "text": value}
            for i, (label, values) in enumerate(rec["facts"]) for j, value in enumerate(values)]
    return out


def _merge(found: list[tuple[int, int, str]]) -> list[dict]:
    """Overlapping matches become one span that names every term it covers."""
    spans: list[dict] = []
    for start, end, term in sorted(found):
        if spans and start < spans[-1]["end"]:
            spans[-1]["end"] = max(end, spans[-1]["end"])
            spans[-1]["terms"] += [term] * (term not in spans[-1]["terms"])
        else:
            spans.append({"start": start, "end": end, "terms": [term]})
    return spans


def why(accession: str, terms: list[str], quote: str = "") -> dict | None:
    """The spans of the record's title, texts and facts that hold each term, whole-word and case-insensitive, and the span
    that holds the quote with its whitespace read loosely. Terms found nowhere are listed with a count of zero."""
    if not (rec := record.record(accession)):
        return None
    terms = list(dict.fromkeys(t.strip() for t in terms if len(t.strip()) > 1))
    patterns = [(t, _pattern(t)) for t in terms]
    counts = dict.fromkeys(terms, 0)
    first: dict[str, dict] = {}
    fields = []
    for f in _fields(rec):
        found = [(m.start(), m.end(), t) for t, p in patterns for m in p.finditer(f["text"])]
        for _, _, t in found:
            counts[t] += 1
        spans = _merge(found)
        for span in spans:
            span["text"] = f["text"][span["start"]:span["end"]]
            for t in span["terms"]:
                first.setdefault(t, {k: f[k] for k in ("field", "kind", "index") if k in f} | {"start": span["start"], "end": span["end"]})
        if spans:
            fields.append({k: v for k, v in f.items() if k != "text"} | {"matches": spans})
    spot = None
    if quote.strip():
        loose = re.compile(r"\s+".join(map(re.escape, quote.split())), re.I)
        spot = next(({k: f[k] for k in ("field", "kind", "index") if k in f} | {"start": m.start(), "end": m.end()}
                     for f in _fields(rec) if (m := loose.search(f["text"]))), None)
    return {"accession": accession, "terms": [{"term": t, "count": counts[t], "first": first.get(t)} for t in terms], "fields": fields, "quote": spot}


if __name__ == "__main__":
    ipf = why("GSE150910", ["idiopathic pulmonary fibrosis", "IPF", "pulmonary fibrosis", "lung fibroses", "RNA-seq", "scRNA-seq", "psoriasis"],
              "transcriptome analysis of lung samples from CHP")
    by = {t["term"]: t for t in ipf["terms"]}
    title = next(f for f in ipf["fields"] if f["kind"] == "title")
    assert [m["text"] for m in title["matches"]] == ["RNA-Sequencing", "Idiopathic Pulmonary Fibrosis"], title
    assert set(title["matches"][1]["terms"]) == {"idiopathic pulmonary fibrosis", "pulmonary fibrosis"}
    assert by["IPF"]["count"] >= 1 and by["IPF"]["first"]["kind"] == "text"
    assert by["psoriasis"] == {"term": "psoriasis", "count": 0, "first": None}
    assert by["lung fibroses"]["count"] == 0
    rec = record.record("GSE150910")
    overall = rec["texts"][ipf["quote"]["index"]][1]
    assert ipf["quote"]["kind"] == "text" and overall[ipf["quote"]["start"]:ipf["quote"]["end"]].lower() == "transcriptome analysis of lung samples from chp"
    for f in ipf["fields"]:
        text = rec["title"] if f["kind"] == "title" else rec["texts"][f["index"]][1] if f["kind"] == "text" else rec["facts"][f["index"]][1][f["value"]]
        assert all(text[m["start"]:m["end"]] == m["text"] and re.search(r"\w", m["text"]) for m in f["matches"])

    sc = why("GSE146981", ["scRNA-seq", "single-cell RNA sequencing", "lung fibrosis", "IPF", "Fibroses"], "Single cell\n RNAseq")
    by = {t["term"]: t for t in sc["terms"]}
    assert by["scRNA-seq"]["count"] >= 2 and by["scRNA-seq"]["first"]["kind"] == "title", by
    assert by["single-cell RNA sequencing"]["count"] == 1
    assert by["IPF"]["count"] >= 1 and by["lung fibrosis"]["count"] == 0
    assert sc["quote"] and sc["quote"]["kind"] == "title"
    assert why("GSE0", ["x"]) is None
    assert _pattern("RNA-seq").search("bulk RNAseq and RNA sequencing") and not _pattern("IPF").search("ZIPFS")
    assert _pattern("cell lines").search("a cell line") and _pattern("fibroblast").search("fibroblasts")
    print("ok")
