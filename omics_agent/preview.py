"""What is inside one processed file of a dataset, read from its first bytes: the columns with their types and ranges, the
first rows, and, when the columns are samples, the group each belongs to. Only files listed in the dataset's own record are
fetched, by name, never a URL from the caller. A gzip is decompressed as it arrives and the read stops after READ bytes;
a small xlsx is downloaded whole into `~/omics-data/previews`. Every number comes from the bytes read; a total the file
has not shown stays None.
"""

import csv
import math
import re
import zlib
from functools import lru_cache
from pathlib import Path

import httpx

from . import design, record

CACHE = Path.home() / "omics-data" / "previews"
READ = 256 * 1024
MAX_XLSX = 20 * 1024**2
MAX_INFLATED = 32 * 1024**2
MAX_ROWS = 2000
MAX_COLUMNS = 1000
SHOWN = 20
CELL = 120
TABLE = re.compile(r"\.(tsv|csv|txt|mztab)(\.gz)?$", re.I)
XLSX = re.compile(r"\.xlsx$", re.I)
MISSING = {"", "na", "nan", "n/a", "null", "none", "-"}
INTEGER = re.compile(r"^[+-]?\d+$")
MZTAB = (("PRH", "PRT"), ("SMH", "SML"), ("PSH", "PSM"))


def previewable(f: dict) -> bool:
    return bool(f["processed"] and (TABLE.search(f["name"]) or XLSX.search(f["name"]) and (f["bytes"] or 0) <= MAX_XLSX))


def _head(url: str) -> tuple[bytes, int | None]:
    """The first READ bytes of a file as stored, and the file's size when the server states it."""
    headers = {"Range": f"bytes=0-{READ - 1}", "Accept-Encoding": "identity"}
    with httpx.stream("GET", url, headers=headers, timeout=30, follow_redirects=True) as r:
        r.raise_for_status()
        total = r.headers.get("content-range", "").rpartition("/")[2] if r.status_code == 206 else r.headers.get("content-length", "")
        data = b""
        for chunk in r.iter_raw():
            data += chunk
            if len(data) >= READ:
                break
    return data[:READ], int(total) if total.isdigit() else None


def _text(data: bytes, whole: bool) -> tuple[str, bool]:
    """The text of the bytes read, without the line the read cut, and whether it is the whole file."""
    if data[:2] == b"\x1f\x8b":
        inflater = zlib.decompressobj(31)
        try:
            data = inflater.decompress(data, MAX_INFLATED)
        except zlib.error as error:
            raise ValueError(f"The file is not a readable gzip: {error}.")
        whole = whole and inflater.eof
    text = data.decode("utf-8", errors="replace")
    return (text if whole else text.rpartition("\n")[0]), whole


def _delimiter(lines: list[str]) -> str:
    """The delimiter that splits the first lines into the same number, at least two, of fields."""
    best, width = "", 1
    for d in "\t,;|":
        counts = {len(line.split(d)) for line in lines}
        if len(counts) == 1 and (n := counts.pop()) > width:
            best, width = d, n
    return best


def _mztab(lines: list[str]) -> tuple[list[str], list[list[str]], str]:
    for head, body in MZTAB:
        header = next((l.split("\t")[1:] for l in lines if l.startswith(head + "\t")), None)
        if header:
            return header, [l.split("\t")[1:] for l in lines if l.startswith(body + "\t")], "mzTab"
    raise ValueError("The mzTab file shows no protein, small-molecule or PSM table in the bytes read.")


def _series_matrix(lines: list[str]) -> tuple[list[str], list[list[str]], list[dict[str, str]]]:
    """The table between the matrix markers, and one dict per sample from the `!Sample_` lines: accession, title, characteristics."""
    begin = next((i for i, l in enumerate(lines) if l.startswith("!series_matrix_table_begin")), None)
    if begin is None:
        raise ValueError("The series matrix shows no table in the bytes read.")
    per_sample: dict[str, list[list[str]]] = {}
    for l in lines[:begin]:
        if l.startswith("!Sample_"):
            key, *values = l.split("\t")
            per_sample.setdefault(key[8:], []).append([v.strip('"') for v in values])
    samples = []
    for i, gsm in enumerate((per_sample.get("geo_accession") or [[]])[0]):
        row = {"geo_accession": gsm, "title": next((v[i] for v in per_sample.get("title", []) if i < len(v)), "")}
        for values in per_sample.get("characteristics_ch1", []):
            name, sep, value = values[i].partition(": ") if i < len(values) else ("", "", "")
            if sep:
                row[name] = value
        samples.append(row)
    body = [l for l in lines[begin + 1:] if not l.startswith("!series_matrix_table_end")]
    rows = list(csv.reader(body, delimiter="\t"))
    return rows[0], rows[1:], samples


def _xlsx(accession: str, f: dict) -> tuple[list[str], list[list[str]], bool, int, str]:
    from openpyxl import load_workbook

    path = CACHE / re.sub(r"[^\w.-]", "_", f"{accession}_{f['name']}")
    if not path.exists():
        data = b""
        with httpx.stream("GET", f["url"], timeout=60, follow_redirects=True) as r:
            r.raise_for_status()
            for chunk in r.iter_raw():
                data += chunk
                if len(data) > MAX_XLSX:
                    raise ValueError("The file is larger than 20 MB, so locus does not download it to preview it.")
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    book = load_workbook(path, read_only=True, data_only=True)
    sheet = book.worksheets[0]
    rows = []
    for cells in sheet.iter_rows(values_only=True):
        if any(c is not None for c in cells):
            rows.append(["" if c is None else str(c) for c in cells])
        if len(rows) > MAX_ROWS:
            break
    whole = len(rows) <= MAX_ROWS
    return rows[0], rows[1:MAX_ROWS + 1], whole, path.stat().st_size, sheet.title


def _column(name: str, values: list[str]) -> dict:
    stated = [v for v in values if v.strip().lower() not in MISSING]
    out = {"name": name, "type": "empty", "missing": len(values) - len(stated)}
    if not stated:
        return out
    try:
        numbers = [float(v) for v in stated]
    except ValueError:
        numbers = None
    if numbers and all(math.isfinite(n) for n in numbers):
        whole = all(INTEGER.match(v) for v in stated)
        out |= {"type": "integer" if whole else "number", "min": f"{min(numbers):.6g}", "max": f"{max(numbers):.6g}"}
    elif {v.lower() for v in stated} <= {"true", "false"}:
        out["type"] = "boolean"
    else:
        out |= {"type": "text", "distinct": len(set(stated))}
    return out


def _groups(headers: list[str], table: dict | None, samples: list[dict] | None = None) -> tuple[dict | None, list[str | None]]:
    """Which sample each column is, by the identifier column of the sample table that matches most headers, and the
    leading grouping factor of those samples. The first column is the feature identifier and is not matched."""
    if samples:
        table = {"columns": list(dict.fromkeys(k for s in samples for k in s)), "rows": []}
        table["rows"] = [[s.get(c, "") for c in table["columns"]] for s in samples]
    ids = set(headers[1:])
    if not table or not table["rows"]:
        return None, []
    cols = table["columns"]
    found = [sum(1 for v in {r[i] for r in table["rows"]} if v in ids) for i in range(len(cols))]
    key = max(range(len(cols)), key=found.__getitem__)
    if found[key] < 2:
        return None, []
    rows = [dict(zip(cols, r)) for r in table["rows"]]
    factors = (design.from_rows([{c: v for c, v in r.items() if c != cols[key]} for r in rows], "") or {}).get("factors", [])
    summary = {"by": cols[key], "matched": found[key], "of": len(ids), "factor": None, "levels": {}}
    if not factors:
        return summary, []
    factor = next(c for c in cols if design._clean(c) == factors[0]["name"])
    level = {r[cols[key]]: r[factor] for r in rows}
    groups = [level.get(h) if i else None for i, h in enumerate(headers)]
    counts: dict[str, int] = {}
    for g in groups:
        if g:
            counts[g] = counts.get(g, 0) + 1
    return summary | {"factor": design._clean(factor), "levels": counts}, groups


@lru_cache(maxsize=64)
def preview(accession: str, file: str) -> dict:
    """The columns, first rows and sample groups of one processed file of a dataset. LookupError when the dataset or
    file is not in its record, ValueError when the file has no table, httpx.HTTPError when the repository fails."""
    if not (row := record._row(accession)):
        raise LookupError(f"{accession} is not in the index.")
    rec = record.raw(accession, row)
    f = next((f for f in rec.files if f["name"] == file), None)
    if not f or not previewable(f):
        raise LookupError(f"{accession} lists no processed table named {file}.")
    sheet, samples = None, None
    if XLSX.search(file):
        header, body, whole, read, sheet = _xlsx(accession, f)
        kind, size = "xlsx", read
    else:
        data, size = _head(f["url"])
        size = size or f["bytes"]
        text, whole = _text(data, len(data) < READ or len(data) == size)
        read = len(data)
        lines = [l.rstrip("\r") for l in text.split("\n")]
        if lines[0].startswith("MTD"):
            header, body, kind = _mztab(lines)
        elif lines[0].startswith("!"):
            header, body, samples = _series_matrix(lines)
            kind = "series matrix"
        else:
            lines = [l for l in lines if l.strip()]
            if not (d := _delimiter(lines[:10])):
                raise ValueError("The first lines of the file are not a table with separated columns.")
            header, *body = csv.reader(lines, delimiter=d)
            kind = {"\t": "tab-separated", ",": "comma-separated", ";": "semicolon-separated", "|": "pipe-separated"}[d]
    body = [r for r in body if any(c.strip() for c in r)]
    whole = whole and len(body) <= MAX_ROWS
    body = body[:MAX_ROWS]
    if not body:
        raise ValueError("The file has no data rows" + ("." if whole else " in the bytes read."))
    if len(header) == len(body[0]) - 1:
        header = ["", *header]
    width = len(header)
    body = [(r + [""] * width)[:width] for r in body]
    columns = [_column(h, [r[i] for r in body]) for i, h in enumerate(header)]
    summary, groups = _groups(header, rec.samples, samples)
    for c, g in zip(columns, groups or [None] * width):
        c["group"] = g
    return {
        "accession": accession, "file": file, "url": f["url"], "format": kind, "sheet": sheet, "bytes_read": read, "size": size,
        "complete": whole, "rows_read": len(body), "total_rows": len(body) if whole else None, "column_count": width,
        "columns": columns[:MAX_COLUMNS], "rows": [[v[:CELL] for v in r[:MAX_COLUMNS]] for r in body[:SHOWN]], "samples": summary,
    }


if __name__ == "__main__":
    tpm = preview("GSE86618", "GSE86618_34816genes-540cells-tpm.txt.gz")
    assert tpm["format"] == "tab-separated" and tpm["column_count"] == 541 and not tpm["complete"] and tpm["total_rows"] is None, tpm
    assert tpm["bytes_read"] <= READ and len(tpm["rows"]) == SHOWN and tpm["columns"][1]["type"] == "number", tpm["columns"][:2]
    assert tpm["samples"]["matched"] == 540 and set(tpm["samples"]["levels"]) == {"IPF", "Control"}, tpm["samples"]

    matrix = preview("GSE41331", "GSE41331_series_matrix.txt.gz")
    assert matrix["format"] == "series matrix" and matrix["columns"][0]["name"] == "ID_REF" and matrix["column_count"] == 16, matrix["columns"][:2]
    assert matrix["samples"]["factor"] == "treatment" and matrix["columns"][1]["group"], matrix["samples"]

    small = preview("E-MTAB-5584", "processed1.txt")
    assert small["complete"] and small["total_rows"] == small["rows_read"] == 110 and small["column_count"] == 30, small["rows_read"]
    assert small["columns"][0]["type"] == "text" and small["columns"][3]["type"] == "number" and small["columns"][3]["min"] < small["columns"][3]["max"]

    proteins = preview("PXD069556", "proteinGroups_LFQ_Oct25.txt")
    assert proteins["column_count"] == 1534 and len(proteins["columns"]) == MAX_COLUMNS and proteins["samples"] is None, proteins["column_count"]
    assert not proteins["complete"] and proteins["bytes_read"] <= READ

    for accession, file in [("GSE86618", "https://example.org/x.txt"), ("GSE86618", "GSE86618_RAW.tar"), ("PXD069556", "missing.txt")]:
        try:
            preview(accession, file)
        except LookupError:
            continue
        raise AssertionError(f"{file} is not a processed table of {accession}'s record")
    print("ok")
