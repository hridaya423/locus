"""The answer at the top of a search: the two or three datasets to start with, each with the one counted fact that makes
it the best on one axis, and where on its page that fact is shown. No model; every fact is read from the hit."""

from concurrent.futures import ThreadPoolExecutor

import httpx

from . import table

CHECKED = 8


def _norm(name: str) -> str:
    return name.lower().replace("-", "").replace(" ", "")


def _matched(hit: dict, wanted: list[str]) -> int:
    libraries = (hit.get("facts") or {}).get("libraries") or {}
    by_name = {_norm(k): v for k, v in libraries.items()}
    per_assay = [sum((by_name.get(_norm(a)) or {}).values()) for a in wanted]
    return min(per_assay) if per_assay and all(per_assay) else 0


def _has_table(accession: str) -> dict | None:
    try:
        return table.available(accession)
    except (httpx.HTTPError, ValueError):
        return None


def pick(plan: dict, hits: list[dict]) -> list[dict]:
    strong = [h for h in hits if h["fit"] == "strong"]
    chosen: list[dict] = []

    def take(hit: dict | None, kind: str, fact: str, anchor: str) -> None:
        if hit and hit["accession"] not in {c["accession"] for c in chosen}:
            chosen.append({"accession": hit["accession"], "title": hit["title"], "source": hit["source"], "kind": kind, "fact": fact, "anchor": anchor})

    wanted = plan.get("matched_assays") or []
    if len(wanted) > 1:
        best = max(strong, key=lambda h: _matched(h, wanted), default=None)
        if best and _matched(best, wanted):
            by_name = {_norm(k): (k, v) for k, v in best["facts"]["libraries"].items()}
            parts = [f"{sum(by_name[_norm(a)][1].values())} {by_name[_norm(a)][0]}" for a in wanted]
            groups = {g for a in wanted for g in by_name[_norm(a)][1]}
            equal = all(len({by_name[_norm(a)][1].get(g, 0) for a in wanted}) == 1 for g in groups)
            take(best, "matched", f"{' and '.join(parts)} libraries" + (", equal in number in every group" if equal else ""), "measured")

    counted = [h for h in strong if (h.get("facts") or {}).get("case") and (h["facts"].get("control"))]
    taken = {c["accession"] for c in chosen}
    # People, not records: 540 single-cell records from 9 patients count as 9.
    size = lambda f: min(f["donors"]["case"], f["donors"]["control"]) if f.get("donors") else min(f["case"], f["control"])
    best = max((h for h in counted if h["accession"] not in taken), key=lambda h: size(h["facts"]), default=None)
    if best:
        f = best["facts"]
        d = f.get("donors")
        fact = (f"{d['case']} case and {d['control']} control {d['field']}s across {f['case'] + f['control']} sample records" if d
                else f"{f['case']} cases and {f['control']} controls, counted from {f['source']}")
        take(best, "cohort", fact, "samples")

    geo = sorted((h for h in strong if h["source"] == "GEO"), key=lambda h: -min((h.get("facts") or {}).get("case") or 0, (h.get("facts") or {}).get("control") or 0))[:CHECKED]
    with ThreadPoolExecutor(4) as pool:
        tables = dict(zip([h["accession"] for h in geo], pool.map(_has_table, [h["accession"] for h in geo])))
    ready = next((h for h in geo if tables.get(h["accession"]) and h["accession"] not in {c["accession"] for c in chosen}), None)
    if ready:
        take(ready, "ready", f"a processed gene table from NCBI ({tables[ready['accession']]['build']}) with a first look on its page", "first-look")
    return chosen[:3]


if __name__ == "__main__":
    hit = lambda acc, fit, case, control, libraries=None, source="GEO": {
        "accession": acc, "title": acc, "source": source, "fit": fit,
        "facts": {"case": case, "control": control, "source": f"{case + control} GEO sample records", "libraries": libraries or {}}}
    hits = [hit("GSE150910", "strong", 185, 103), hit("GSE124685", "strong", 49, 35), hit("GSE1", "partial", 900, 900),
            hit("GSE36892", "strong", 6, 6, {"Ribo-seq": {"case": 4, "control": 4}, "RNA-seq": {"case": 2, "control": 2}})]
    answer = pick({"matched_assays": ["Ribo-seq", "RNA-seq"]}, hits)
    assert [a["kind"] for a in answer][:2] == ["matched", "cohort"] and answer[1]["accession"] == "GSE150910", answer
    assert answer[0]["fact"] == "8 Ribo-seq and 4 RNA-seq libraries", answer[0]
    assert any(a["kind"] == "ready" and a["accession"] == "GSE124685" for a in answer), answer
    print("answer self-check passed:", [(a["accession"], a["kind"]) for a in answer])
