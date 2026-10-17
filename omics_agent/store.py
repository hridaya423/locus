import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "omics.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
  accession TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  organism TEXT NOT NULL,
  modality TEXT NOT NULL,
  samples INTEGER,
  published TEXT,
  papers TEXT NOT NULL,
  url TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS datasets_source ON datasets(source);
CREATE VIRTUAL TABLE IF NOT EXISTS datasets_fts USING fts5(
  accession UNINDEXED, title, summary, organism, modality, content='datasets', tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS annotations (
  accession TEXT PRIMARY KEY,
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS methods (
  accession TEXT PRIMARY KEY,
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (
  accession TEXT PRIMARY KEY,
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
  accession TEXT NOT NULL,
  topic TEXT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (accession, topic)
);
"""

COLUMNS = ("accession", "source", "title", "summary", "organism", "modality", "samples", "published", "papers", "url")


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=120)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def upsert(db: sqlite3.Connection, rows: list[dict]) -> None:
    """Insert or replace dataset rows. `papers` is a list of 'pmid:…'/'doi:…' strings. Run rebuild_fts() after a harvest."""
    db.executemany(
        f"INSERT OR REPLACE INTO datasets ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
        [tuple(json.dumps(r[c]) if c == "papers" else r[c] for c in COLUMNS) for r in rows],
    )
    db.commit()


def rebuild_fts(db: sqlite3.Connection) -> None:
    """Rebuild the full-text index from the datasets table in one pass; far faster than per-row index updates."""
    db.execute("DROP TABLE IF EXISTS datasets_fts")
    db.executescript(SCHEMA)
    db.execute("INSERT INTO datasets_fts(datasets_fts) VALUES('rebuild')")
    db.commit()



def has_index() -> bool:
    """True once a harvest has stored datasets. The file alone is not enough: caching facts creates it empty."""
    return DB.exists() and connect().execute("SELECT EXISTS (SELECT 1 FROM datasets)").fetchone()[0] == 1


def cached_facts(accession: str, topic: str) -> dict | None:
    """Counted sample groups for a dataset and topic, from an earlier search."""
    row = connect().execute("SELECT data FROM facts WHERE accession = ? AND topic = ?", (accession, topic)).fetchone()
    return json.loads(row[0]) if row else None


def cache_facts(accession: str, topic: str, facts: dict) -> None:
    db = connect()
    db.execute("INSERT OR REPLACE INTO facts (accession, topic, data) VALUES (?, ?, ?)", (accession, topic, json.dumps(facts)))
    db.commit()


def summary(accession: str) -> str:
    row = connect().execute("SELECT title || '. ' || summary FROM datasets WHERE accession = ?", (accession,)).fetchone()
    return row[0] if row else ""


def methods(accessions: list[str]) -> dict[str, dict]:
    """PRIDE Map method tags for the given accessions, where they exist."""
    rows = connect().execute(f"SELECT accession, data FROM methods WHERE accession IN ({','.join('?' * len(accessions))})", accessions)
    return {a: json.loads(d) for a, d in rows}


# Structured metadata read from each repository's own API, beyond what the bulk listings carry. Every value is a
# list of strings except sample_count; a key is left out when the repository does not state it.
METADATA_KEYS = ("instruments", "tissues", "cell_types", "diseases", "keywords", "modifications", "quantification",
                 "experiment_types", "technologies", "sample_count", "source")


def put_metadata(db: sqlite3.Connection, rows: dict[str, dict]) -> None:
    """Store structured metadata per accession, replacing earlier values; unknown keys are rejected."""
    if bad := {k for d in rows.values() for k in d} - set(METADATA_KEYS):
        raise ValueError(f"unknown metadata keys: {sorted(bad)}")
    db.executemany("INSERT OR REPLACE INTO metadata (accession, data) VALUES (?, ?)", [(a, json.dumps(d)) for a, d in rows.items()])
    db.commit()


def metadata(accessions: list[str]) -> dict[str, dict]:
    rows = connect().execute(f"SELECT accession, data FROM metadata WHERE accession IN ({','.join('?' * len(accessions))})", accessions)
    return {a: json.loads(d) for a, d in rows}
