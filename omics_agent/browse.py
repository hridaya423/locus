"""Doors become pages: every locus dataset that shares one stated value (an organism, an instrument, a data type, a
keyword), from the local index, newest first."""

import re

from . import store

COLUMN = {"Organism": "organism", "Organisms": "organism", "Species": "organism"}
PAGE = 50


def _phrase(value: str) -> str:
    return re.sub(r"^GPL\d+\s+|\s*\([^)]*\)\s*$", "", value).strip()


def _match(column: str | None, phrase: str) -> str:
    quoted = '"' + " ".join(re.sub(r'["*^:()]', " ", phrase).split()) + '"'
    return f"{column}: {quoted}" if column else quoted


def _from_metadata(db, phrase: str) -> set[str]:
    """Datasets whose enrichment metadata (instruments, tissues, keywords, technologies) names the value."""
    return {a for (a,) in db.execute("SELECT accession FROM metadata WHERE data LIKE ?", [f'%"{phrase}"%'])}


def browse(field: str, value: str, source: str = "", offset: int = 0) -> dict:
    phrase = _phrase(value)
    if not phrase:
        return {"field": field, "value": value, "total": 0, "datasets": [], "by_source": {}}
    db = store.connect()
    column = COLUMN.get(field) or "modality"
    query = _match(column, phrase)
    if not db.execute("SELECT 1 FROM datasets_fts WHERE datasets_fts MATCH ? LIMIT 1", [query]).fetchone():
        column, query = None, _match(None, phrase)
    extra = _from_metadata(db, phrase) if column != "organism" else set()
    db.execute("CREATE TEMP TABLE IF NOT EXISTS picked (accession TEXT PRIMARY KEY)")
    db.execute("DELETE FROM picked")
    db.execute("INSERT OR IGNORE INTO picked SELECT accession FROM datasets_fts WHERE datasets_fts MATCH ?", [query])
    db.executemany("INSERT OR IGNORE INTO picked VALUES (?)", [(a,) for a in extra])
    by_source = dict(db.execute("SELECT d.source, count(*) FROM picked JOIN datasets d USING (accession) GROUP BY d.source ORDER BY 2 DESC").fetchall())
    rows = db.execute(
        "SELECT d.accession, d.source, d.title, d.samples, d.published, d.modality FROM picked JOIN datasets d USING (accession) "
        f"{'WHERE d.source = ?' if source else ''} ORDER BY d.published DESC LIMIT ? OFFSET ?", [*([source] if source else []), PAGE, offset]).fetchall()
    where = (column or "any text") + (" and repository metadata" if extra else "")
    return {
        "field": field, "value": value, "phrase": phrase, "matched_in": where, "source": source,
        "total": by_source.get(source, 0) if source else sum(by_source.values()), "by_source": by_source, "offset": offset,
        "datasets": [{"accession": a, "source": s, "title": t, "samples": n, "published": p, "modality": m} for a, s, t, n, p, m in rows],
    }


if __name__ == "__main__":
    human = browse("Organism", "Homo sapiens")
    assert human["matched_in"].startswith("organism") and human["total"] > 100_000 and len(human["datasets"]) == PAGE, human["total"]
    nova = browse("Instrument", "Illumina NovaSeq 6000")
    assert nova["total"] > 1000 and all(d["accession"] for d in nova["datasets"]), nova["total"]
    hfx = browse("Instruments", "Q Exactive HFX mass spectrometer (Orbitrap Ms, Thermo)")
    gpl = browse("Platforms", "GPL16791 Illumina HiSeq 2500 (Homo sapiens)")
    assert gpl["phrase"] == "Illumina HiSeq 2500" and gpl["total"] > 0, gpl
    geo = browse("Organism", "Homo sapiens", "GEO", 50)
    assert geo["total"] == human["by_source"]["GEO"] and all(d["source"] == "GEO" for d in geo["datasets"])
    print("browse self-check passed:", human["total"], nova["total"], gpl["total"])
