"""What is inside one processed file of a dataset, read from its first bytes: the columns with their types and ranges, the
first rows, and, when the columns are samples, the group each belongs to. Only files listed in the dataset's own record are
fetched, by name, never a URL from the caller. A gzip is decompressed as it arrives and the read stops after READ bytes;
a small xlsx is downloaded whole into `~/omics-data/previews`. Every number comes from the bytes read; a total the file
has not shown stays None.
"""

import csv
import io
import math
import re
import struct
import zlib
from functools import lru_cache
from itertools import islice
from pathlib import Path

import httpx

from . import design, paper, record, samples as geo_samples

CACHE = Path.home() / "omics-data" / "previews"
READ = 256 * 1024
MAX_XLSX = 20 * 1024**2
MAX_INFLATED = 32 * 1024**2
MAX_ROWS = 2000
MAX_COLUMNS = 1000
SHOWN = 20
CELL = 120
TABLE = re.compile(r"\.(tsv|csv|txt|mztab)(\.gz)?$", re.I)
ZIP = re.compile(r"\.zip$", re.I)
# Inside a search-engine zip, the table a reader wants first: MaxQuant's protein groups, DIA-NN's protein matrix, then any table.
MEMBERS = [re.compile(p, re.I) for p in (r"(^|/)proteinGroups\.txt$", r"pg_matrix\.tsv$", r"(^|/)peptides\.txt$", r"(^|/)report\.tsv$")]
NOT_MEMBER = re.compile(r"summary|parameters|readme|log|msmsScans|msScans|allPeptides|\.mzid|\.xml", re.I)
XLSX = re.compile(r"\.xlsx$", re.I)
MISSING = {"", "na", "nan", "n/a", "null", "none", "-"}
INTEGER = re.compile(r"^[+-]?\d+$")
MZTAB = (("PRH", "PRT"), ("SMH", "SML"), ("PSH", "PSM"))


NOT_A_TABLE = re.compile(r"read.?me|md5|checksum|filelist", re.I)
SERIES_MATRIX = re.compile(r"(?:-(GPL\d+))?_series_matrix\.txt", re.I)


@lru_cache(maxsize=256)
def _data_rows(accession: str) -> dict[str, int] | None:
    """The data rows GEO states for the samples of a series, by platform and in total (key ""); None without a sample file."""
    path = geo_samples.CACHE / f"{accession}.txt"
    if not path.exists():
        return None
    rows = {"": 0}
    for block in path.read_text().split("^SAMPLE")[1:]:
        count = re.search(r"^!Sample_data_row_count = (\d+)", block, re.M)
        platform = re.search(r"^!Sample_platform_id = (\S+)", block, re.M)
        n = int(count.group(1)) if count else 1
        rows[""] += n
        if platform:
            rows[platform.group(1)] = rows.get(platform.group(1), 0) + n
    return rows


def previewable(f: dict, accession: str = "") -> bool:
    """A processed table, or an xlsx up to 20 MB; not a series matrix whose samples GEO says have no data rows."""
    name = f["name"]
    if ZIP.search(name) and (f["processed"] or f.get("group") in ("Search", "Result")):
        return True
    if not f["processed"] or NOT_A_TABLE.search(name):
        return False
    if XLSX.search(name):
        return (f["bytes"] or 0) <= MAX_XLSX
    if not TABLE.search(name):
        return False
    matrix = SERIES_MATRIX.search(name)
    rows = _data_rows(accession) if matrix else None
    return not (rows and not rows.get(matrix.group(1) or "", 1))


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


def _ranged(url: str, header: str, cap: int = 4 * READ) -> tuple[bytes, int] | None:
    with httpx.stream("GET", url, headers={"Range": header, "Accept-Encoding": "identity"}, timeout=120, follow_redirects=True) as r:
        if r.status_code != 206 or "/" not in r.headers.get("content-range", ""):
            return None
        data = b""
        for chunk in r.iter_raw():
            data += chunk
            if len(data) >= cap:
                break
        return data, int(r.headers["content-range"].rpartition("/")[2])


MAX_MEMBER = 200 * 1024**2


def _zip_member(url: str, whole: bool = False) -> tuple[bytes, bool, str, int]:
    """The first bytes of the most useful table inside a zip, inflated, without downloading the zip: two Range reads, one
    for the central directory and one for the start of the member; with `whole`, the entire member (up to 200 MB
    unpacked). Returns the bytes, whether they are the whole member, its path and how many files the zip holds."""
    files = paper.directory(lambda header: _ranged(url, header))
    if not files:
        raise ValueError("locus could not read this zip's list of files (the server ignores Range, or it is a zip64 archive).")
    tables = [f for f in files if TABLE.search(f["path"]) and not NOT_MEMBER.search(f["path"])]
    pick = next((f for rx in MEMBERS for f in tables if rx.search(f["path"])), max(tables, key=lambda f: f["size"], default=None))
    if not pick or pick["method"] not in (0, 8):
        raise ValueError(f"The zip holds {len(files)} files and no table locus can read.")
    if whole and pick["size"] > MAX_MEMBER:
        raise ValueError(f"{pick['path']} is larger than 200 MB unpacked, so locus reads only its first bytes.")
    span = 30 + 1024 + (pick["compressed"] if whole else READ)
    head = _ranged(url, f"bytes={pick['offset']}-{pick['offset'] + span}", cap=span + 1 if whole else 4 * READ)
    if not head or head[0][:4] != b"PK\x03\x04":
        raise ValueError("locus could not read the start of the table inside the zip.")
    name, extra = struct.unpack_from("<HH", head[0], 26)
    raw = head[0][30 + name + extra:][:pick["compressed"] if whole else min(pick["compressed"], 4 * READ)]
    if pick["method"] == 0:
        return raw, len(raw) >= pick["size"], pick["path"], len(files)
    inflater = zlib.decompressobj(-15)
    data = inflater.decompress(raw, 0 if whole else MAX_INFLATED)
    return data, inflater.eof, pick["path"], len(files)


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


DELIMITERS = {"\t": "tab-separated", ",": "comma-separated", ";": "semicolon-separated", "|": "pipe-separated", " ": "space-separated"}


def _reader(text: str, delimiter: str):
    return csv.reader(io.StringIO(text), delimiter=delimiter, skipinitialspace=delimiter == " ")


def _delimiter(text: str) -> str:
    """The delimiter that splits the first rows into the same number, at least two, of fields; a header one field short of
    the rows is a row-names table written by R."""
    best, width = "", 1
    for d in DELIMITERS:
        try:
            widths = [len(r) for r in islice(_reader(text, d), 10) if r]
        except csv.Error:
            continue
        n = max(widths, default=0)
        if n > width and all(w == n for w in widths[1:]) and widths[0] in (n, n - 1):
            best, width = d, n
    return best


def _table(text: str) -> tuple[list[str], list[list[str]], str, int]:
    """The header, rows, delimiter name and number of `#` comment lines above the header of a delimited table."""
    lines = text.split("\n")
    first = next((i for i, l in enumerate(lines) if l.strip() and not l.startswith("#")), 0)
    comments = sum(1 for l in lines[:first] if l.startswith("#"))
    body = "\n".join(lines[first:])
    if not (d := _delimiter(body)):
        raise ValueError("This file is not a table: no tab, comma, semicolon, pipe or space splits its first lines into the same columns.")
    try:
        header, *rows = islice(_reader(body, d), MAX_ROWS + 3)
    except csv.Error as error:
        raise ValueError(f"This file is not a readable table: {error}.")
    return header, rows, DELIMITERS[d], comments


def _mwtab(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """The metabolite-by-sample block of a Metabolomics Workbench mwTab file: its 'Samples' row is the header."""
    start = next((i for i, l in enumerate(lines) if re.match(r"(MS|NMR)_(METABOLITE|BINNED)_DATA_START", l)), None)
    if start is None:
        raise ValueError("The mwTab file has no metabolite data block in the bytes read.")
    rows = []
    for line in lines[start + 1:]:
        if line.endswith("_DATA_END"):
            break
        rows.append(line.split("\t"))
    header = ["Metabolite", *rows[0][1:]] if rows and rows[0][0] == "Samples" else []
    return header, [r for r in rows[1:] if r[0] != "Factors"]
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


def _xlsx(accession: str, f: dict) -> tuple[list[str], list[list[str]], bool, int, str, int]:
    """Header, rows, whether all rows were read, file size, sheet name, and the rows above the header, which is the first
    row with at least half as many filled cells as the widest of the first 50 rows."""
    from openpyxl import load_workbook

    path = CACHE / re.sub(r"[^\w.-]", "_", f"{accession}_{f['name']}")
    if not path.exists():
        data = b""
        with httpx.stream("GET", f["url"], timeout=60, follow_redirects=True) as r:
            r.raise_for_status()
            for chunk in r.iter_raw():
                data += chunk
                if len(data) > MAX_XLSX:
                    raise ValueError("This xlsx is larger than 20 MB, so locus does not download it to preview it.")
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    sheet = load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = []
    for cells in sheet.iter_rows(values_only=True):
        if any(c is not None for c in cells):
            rows.append(["" if c is None else str(c) for c in cells])
        if len(rows) > MAX_ROWS + 50:
            break
    filled = [sum(1 for c in r if c) for r in rows[:50]]
    start = next((i for i, n in enumerate(filled) if n >= max(2, math.ceil(max(filled, default=0) / 2))), 0)
    body = rows[start + 1:]
    return rows[start], body[:MAX_ROWS + 1], len(body) <= MAX_ROWS, path.stat().st_size, sheet.title, start


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


SAMPLE_KEY = re.compile(r"^(geo_accession|accession|title|run|sample|sample title|sample name|source name|name)$", re.I)
ACCESSION = re.compile(r"^([A-Z]{3,5})\d+$")


def _groups(headers: list[str], table: dict | None, samples: list[dict] | None = None) -> tuple[dict | None, list[str | None]]:
    """Which sample each column is, matched only on a sample accession or a title that is unique in the sample table, and the
    leading grouping factor of those samples. The first column is the feature identifier and is not matched. When no
    column matches, the summary says which keys were tried and which accessions the headers look like."""
    if samples:
        table = {"columns": list(dict.fromkeys(k for s in samples for k in s)), "rows": []}
        table["rows"] = [[s.get(c, "") for c in table["columns"]] for s in samples]
    ids = headers[1:]
    if not table or not table["rows"] or len(ids) < 2:
        return None, []
    cols = table["columns"]
    keys = {}
    for i, c in enumerate(cols):
        values = [r[i] for r in table["rows"] if r[i]]
        if SAMPLE_KEY.match(c) and len(values) == len(set(values)):
            keys[i] = sum(1 for v in values if v in set(ids))
    key = max(keys, key=keys.get, default=None)
    if key is None or keys[key] < 2:
        prefixes = [m.group(1) for h in ids if (m := ACCESSION.match(h))]
        looks = max(set(prefixes), key=prefixes.count) if len(prefixes) * 2 >= len(ids) else None
        return {"by": None, "matched": 0, "of": len(ids), "keys": [cols[i] for i in keys], "looks_like": looks, "factor": None, "levels": {}}, []
    rows = [dict(zip(cols, r)) for r in table["rows"]]
    factors = (design.from_rows([{c: v for c, v in r.items() if c != cols[key]} for r in rows], "") or {}).get("factors", [])
    summary = {"by": cols[key], "matched": keys[key], "of": len(ids), "factor": None, "levels": {}}
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


INTENSITY = re.compile(r"^(?:LFQ intensity|Intensity) (?![LMH]$)(.+)$")
CHANNEL = re.compile(r"^Reporter intensity (?:corrected )?(\d+)(?: (.+))?$")


def experiments(header: list[str]) -> dict | None:
    """The samples a MaxQuant table measured, from its column names ('Intensity XAD_1', 'Reporter intensity corrected 3
    WT1'), grouped by name without the trailing number, and the isobaric channels per run when there are any."""
    names = sorted(dict.fromkeys(m[1] for h in header if (m := INTENSITY.match(h))), key=lambda n: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", n)])
    channels = len({m[1] for h in header if (m := CHANNEL.match(h))})
    if len(names) < 2 and channels < 2:
        return None
    stems: dict[str, int] = {}
    for n in names:
        stem = re.sub(r"[_ .-]*\d+$", "", n) or n
        stems[stem] = stems.get(stem, 0) + 1
    return {"names": names, "groups": stems if 1 < len(stems) < len(names) else None, "channels": channels or None}


@lru_cache(maxsize=64)
def preview(accession: str, file: str) -> dict:
    """The columns, first rows and sample groups of one processed file of a dataset. LookupError when the dataset or
    file is not in its record, ValueError when the file has no table, httpx.HTTPError when the repository fails."""
    if not (row := record._row(accession)):
        raise LookupError(f"{accession} is not in the index.")
    rec = record.raw(accession, row)
    f = next((f for f in rec.files if f["name"] == file and previewable(f, accession)), None)
    if not f:
        raise LookupError(f"{accession} lists no processed table named {file}.")
    sheet, samples, skipped, member = None, None, 0, None
    if ZIP.search(file):
        data, whole, path, count = _zip_member(f["url"])
        member = {"path": path, "files": count}
        text = data.decode("utf-8", errors="replace")
        text = text if whole else text.rpartition("\n")[0]
        header, body, kind, skipped = _table(text)
        read, size = len(data), f["bytes"]
    elif XLSX.search(file):
        header, body, whole, read, sheet, skipped = _xlsx(accession, f)
        kind, size = "xlsx", read
    else:
        data, size = _head(f["url"])
        size = size or f["bytes"]
        text, whole = _text(data, len(data) < READ or len(data) == size)
        read = len(data)
        lines = [l.rstrip("\r") for l in text.split("\n")]
        if lines[0].startswith("#METABOLOMICS WORKBENCH"):
            header, body = _mwtab(lines)
            kind = "mwTab metabolite data"
        elif lines[0].startswith("MTD"):
            header, body, kind = _mztab(lines)
        elif lines[0].startswith("!"):
            header, body, samples = _series_matrix(lines)
            kind = "series matrix"
        else:
            header, body, kind, skipped = _table(text)
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
        "accession": accession, "file": file, "url": f["url"], "format": kind, "sheet": sheet, "member": member, "experiments": experiments(header), "skipped": skipped, "bytes_read": read, "size": size,
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

    space = preview("GSE114436", "GSE114436_Experiment1.txt.gz")
    assert space["format"] == "space-separated" and space["column_count"] == 11 and space["columns"][0]["name"] == "", space["columns"][:2]
    assert space["samples"]["by"] is None and space["samples"]["keys"] == ["Accession", "Title"], space["samples"]
    quoted = preview("E-MTAB-10554", "fold_change.txt")
    assert quoted["format"] == "tab-separated" and quoted["column_count"] == 56 and quoted["columns"][0]["name"] == "probe_set", quoted["columns"][:2]
    twice = preview("E-TABM-346", "E-TABM-346-processed-data-2496486478.txt")
    assert twice["column_count"] == 319, twice["column_count"]
    sheet = preview("PXD066171", "AlgPro2_Resume_samples2.xlsx")
    assert sheet["columns"][1]["name"] == "#name" and sheet["skipped"] == 8 and sheet["complete"], (sheet["skipped"], sheet["columns"][:2])

    empty = next(f for f in record.raw("GSE235388", record._row("GSE235388")).files if f["name"].endswith("GPL20301_series_matrix.txt.gz"))
    assert not previewable(empty, "GSE235388") and previewable(empty | {"name": "GSE86618_series_matrix.txt.gz"}, "GSE86618") is False

    header, rows, kind, comments = _table("# Program:featureCounts v2\nGeneid\tChr\tS1\nA\t1\t5\nB\t1\t6")
    assert header == ["Geneid", "Chr", "S1"] and len(rows) == 2 and kind == "tab-separated" and comments == 1
    header, rows, kind, comments = _table('"S1" "S2"\n"g1" 1 2\n"g2" 3 4')
    assert header == ["S1", "S2"] and rows[0] == ["g1", "1", "2"] and kind == "space-separated"
    aggregate = {"columns": ["tissue", "diagnosis"], "rows": [["liver", "normal"], ["kidney", "normal"]]}
    assert _groups(["gene", "liver", "kidney"], aggregate)[0]["by"] is None, "a characteristic value is not a sample key"
    repeated = {"columns": ["Title", "diagnosis"], "rows": [["a", "x"], ["a", "y"], ["b", "x"]]}
    assert _groups(["gene", "a", "b"], repeated)[0]["by"] is None, "a repeated title is not a sample key"

    for accession, file in [("GSE86618", "https://example.org/x.txt"), ("GSE86618", "GSE86618_RAW.tar"), ("PXD069556", "missing.txt")]:
        try:
            preview(accession, file)
        except LookupError:
            continue
        raise AssertionError(f"{file} is not a processed table of {accession}'s record")
    print("ok")
