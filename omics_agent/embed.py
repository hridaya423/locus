import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
from dotenv import load_dotenv
from huggingface_hub import create_inference_endpoint, get_inference_endpoint

from . import index, store

ENDPOINT = "omics-agent-embed"
PARTS = store.DB.parent / "vector_chunks"
REPLICAS = 3
CHUNK = 10_000
BATCH = 128


def start_endpoint():
    """A GPU Text Embeddings Inference endpoint for the corpus model; reused if it already exists."""
    try:
        endpoint = get_inference_endpoint(ENDPOINT)
        if endpoint.status in ("paused", "scaledToZero"):
            endpoint.resume()
    except Exception:
        endpoint = create_inference_endpoint(
            ENDPOINT,
            repository=index.MODEL,
            framework="pytorch",
            task="sentence-embeddings",
            accelerator="gpu",
            vendor="aws",
            region="us-east-1",
            instance_size="x1",
            instance_type="nvidia-l4",
            type="protected",
            min_replica=REPLICAS,
            max_replica=REPLICAS,
        )
    return endpoint.wait(timeout=1800)


def _embed(client: httpx.Client, url: str, texts: list[str]) -> np.ndarray:
    for attempt in range(6):
        try:
            # The root route accepts {"inputs": [...]} on both TEI and the default inference container.
            response = client.post(url, json={"inputs": texts}, timeout=300)
            if response.status_code == 200:
                body = response.json()
                # The default inference container wraps vectors in {"embeddings": [...]}; TEI returns the list directly.
                vectors = np.asarray(body["embeddings"] if isinstance(body, dict) else body, dtype=np.float32)
                return (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(np.float16)
        except httpx.HTTPError:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"embedding failed: {response.status_code} {response.text[:200]}")


def embed_corpus(url: str, redo: set[str] = frozenset()) -> None:
    """Embed every dataset not yet embedded, plus any in `redo` whose text changed, in resumable chunks,
    then join all chunks into one matrix. Each chunk records its accessions, so a later harvest or edit
    only embeds the rows it touched; the newest vector of an accession wins."""
    PARTS.mkdir(parents=True, exist_ok=True)
    done = {a for p in PARTS.glob("*.json") for a in json.loads(p.read_text())} - redo
    stored = store.connect().execute("SELECT accession, title, summary, organism, modality FROM datasets ORDER BY rowid").fetchall()
    rows = [r for r in stored if r[0] not in done]
    print(f"{len(done)} already embedded, {len(rows)} to embed", flush=True)
    headers = {"Authorization": f"Bearer {os.environ['HF_TOKEN']}"}
    with httpx.Client(headers=headers) as client, ThreadPoolExecutor(max_workers=8 * REPLICAS) as pool:
        probe = _embed(client, url, ["probe one", "probe two"])
        if probe.shape != (2, 768):
            raise RuntimeError(f"unexpected embedding shape {probe.shape}")
        first = len(list(PARTS.glob("*.json")))
        for n, start in enumerate(range(0, len(rows), CHUNK), first):
            chunk = rows[start:start + CHUNK]
            texts = [index.document(*r[1:]) for r in chunk]
            batches = [texts[i:i + BATCH] for i in range(0, len(texts), BATCH)]
            began = time.time()
            np.save(PARTS / f"{n:05d}.npy", np.vstack(list(pool.map(lambda b: _embed(client, url, b), batches))))
            # The id list is written last, so a chunk only counts as done once its vectors are saved.
            (PARTS / f"{n:05d}.json").write_text(json.dumps([r[0] for r in chunk]))
            print(f"embedded {start + len(chunk)}/{len(rows)} ({len(chunk) / (time.time() - began):.0f} docs/s)", flush=True)
    parts = sorted(PARTS.glob("*.json"))
    ids = [a for p in parts for a in json.loads(p.read_text())]
    # Later chunks re-embed edited rows, so keep each accession's last vector, and drop rows deleted since.
    live = {r[0] for r in stored}
    latest = {a: i for i, a in enumerate(ids) if a in live}
    keep = sorted(latest.values())
    np.save(index.VECTORS, np.vstack([np.load(p.with_suffix(".npy")) for p in parts])[keep])
    index.VECTOR_IDS.write_text(json.dumps([ids[i] for i in keep]))


if __name__ == "__main__":
    load_dotenv()
    endpoint = start_endpoint()
    print(f"endpoint ready: {endpoint.url}", flush=True)
    try:
        # `--redo FILE` re-embeds the accessions listed in FILE, one per line, after their text changed.
        redo = set(open(sys.argv[2]).read().split()) if sys.argv[1:2] == ["--redo"] else set()
        embed_corpus(endpoint.url, redo)
    finally:
        endpoint.delete()
        print("endpoint deleted", file=sys.stderr)
