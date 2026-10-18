import json
import re
from functools import cache

import numpy as np

from . import methods, store
from .sources import Dataset, _cellxgene_datasets, cellxgene_facts

MODEL = "NeuML/pubmedbert-base-embeddings"
VECTORS = store.DB.parent / "vectors.npy"
VECTOR_IDS = store.DB.parent / "vector_ids.json"
RRF_K = 60


def document(title: str, summary: str, organism: str, modality: str) -> str:
    """The text that represents a dataset for embedding: title, data type, and species, then the opening of its summary."""
    return f"{title}. {modality}. {organism}. {summary}"[:2000]


def _fts_query(terms: list[str]) -> str:
    """Each term matches when all of its words appear, in any order; terms are alternatives."""
    groups = {" AND ".join(f'"{w}"' for w in re.sub(r'["*^:()]', " ", t).split()) for t in terms}
    return " OR ".join(f"({g})" for g in groups if g)


def keyword_search(terms: list[str], sources: list[str], organism: str, limit: int) -> list[str]:
    """BM25 ranking over title, summary, organism, and data type of every stored dataset."""
    db = store.connect()
    placeholders = ",".join("?" * len(sources))
    rows = db.execute(
        f"SELECT d.accession FROM datasets_fts JOIN datasets d ON d.rowid = datasets_fts.rowid "
        f"WHERE datasets_fts MATCH ? AND d.source IN ({placeholders}) AND (d.organism LIKE ? OR d.organism = '') "
        f"ORDER BY bm25(datasets_fts, 0, 4, 1, 1, 1) LIMIT ?",
        [_fts_query(terms), *sources, f"%{organism}%", limit],
    )
    return [r[0] for r in rows]


@cache
def _encoder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL, device="cpu")


@cache
def _vectors() -> tuple[np.ndarray, list[str], dict[str, tuple[str, str]]]:
    ids = json.loads(VECTOR_IDS.read_text())
    meta = {a: (s, o) for a, s, o in store.connect().execute("SELECT accession, source, organism FROM datasets")}
    return np.load(VECTORS), ids, meta


def semantic_search(question: str, sources: list[str], organism: str, limit: int) -> list[str]:
    """Cosine similarity between the question and every embedded dataset."""
    if not VECTORS.exists():
        return []
    matrix, ids, meta = _vectors()
    query = _encoder().encode(question, normalize_embeddings=True).astype(matrix.dtype)
    wanted, organism = set(sources), organism.lower()
    hits = []
    for i in np.argsort(-(matrix @ query)):
        source, species = meta.get(ids[i], ("", ""))
        # Some repositories record species per sample, not per study; their rows pass any species filter.
        if source in wanted and (organism in species.lower() or not species):
            hits.append(ids[i])
            if len(hits) == limit:
                break
    return hits


def fuse(*rankings: list[str]) -> list[str]:
    """Reciprocal rank fusion: a dataset ranked high in several lists rises to the top."""
    score: dict[str, float] = {}
    for ranking in rankings:
        for rank, accession in enumerate(ranking):
            score[accession] = score.get(accession, 0) + 1 / (RRF_K + rank)
    return sorted(score, key=score.get, reverse=True)


def search(question: str, terms: list[str], sources: list[str], organism: str = "", limit: int = 300) -> list[str]:
    return fuse(keyword_search(terms, sources, organism, limit), semantic_search(question, sources, organism, limit))[:limit]


def load(accessions: list[str]) -> list[Dataset]:
    """Stored rows as pipeline Datasets, in the given order, with CELLxGENE's curated facts attached."""
    db = store.connect()
    placeholders = ",".join("?" * len(accessions))
    rows = {r[0]: r for r in db.execute(
        f"SELECT accession, source, modality, title, organism, samples, url, summary, papers, published FROM datasets WHERE accession IN ({placeholders})",
        accessions,
    )}
    cellxgene = {d["dataset_id"]: d for d in _cellxgene_datasets()} if any(rows[a][1] == "CELLxGENE" for a in rows) else {}
    tagged = store.methods([a for a in rows if rows[a][1] == "PRIDE"])
    return [
        Dataset(
            accession=a, source=r[1], modality=r[2], title=r[3], organism=r[4], samples=r[5], url=r[6],
            text=f"{r[3]}\n{r[7]}", papers=json.loads(r[8]), published=r[9],
            facts=cellxgene_facts(cellxgene[a]) if a in cellxgene else methods.facts(tagged[a], r[4], f"{r[3]}\n{r[7]}") if a in tagged else None,
        )
        for a in accessions if (r := rows.get(a))
    ]
