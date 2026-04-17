"""Qdrant Cloud client setup and collection operations."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Modifier,
    NamedSparseVector,
    NamedVector,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from src.stage2.embeddings import DENSE_VECTOR_SIZE, embed_dense, embed_sparse
from src.stage2.parser import ParsedSummary

COLLECTION_NAME = "summaries"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOCAL_PATH = _REPO_ROOT / "qdrant_data"

_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """Return a cached Qdrant client.

    Selected by `QDRANT_PROVIDER` env var (default: ``cloud``):

    - ``cloud``   — remote Qdrant Cloud cluster via HTTPS + API key. Requires
                    ``QDRANT_CLUSTER_ENDPOINT`` and ``QDRANT_API_KEY``.
    - ``local``   — embedded Qdrant persisted to a local directory. No server,
                    no network. Directory path is taken from
                    ``QDRANT_LOCAL_PATH`` (default: ``./qdrant_data`` at the
                    repo root). Data persists across runs; delete the folder
                    to wipe the index.
    """
    global _client
    if _client is not None:
        return _client

    provider = os.environ.get("QDRANT_PROVIDER", "cloud").strip().lower()

    if provider == "local":
        path = Path(os.environ.get("QDRANT_LOCAL_PATH") or _DEFAULT_LOCAL_PATH)
        if not path.is_absolute():
            path = _REPO_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        _client = QdrantClient(path=str(path))
        return _client

    if provider != "cloud":
        sys.exit(
            f"error: QDRANT_PROVIDER={provider!r} is unknown. "
            f"Valid values: cloud, local."
        )

    url = os.environ.get("QDRANT_CLUSTER_ENDPOINT")
    api_key = os.environ.get("QDRANT_API_KEY")
    if not url or not api_key:
        sys.exit(
            "error: QDRANT_CLUSTER_ENDPOINT and QDRANT_API_KEY must be set in .env "
            "(or set QDRANT_PROVIDER=local to use embedded Qdrant)."
        )

    _client = QdrantClient(url=url, api_key=api_key)
    return _client


def create_collection(*, recreate: bool = False) -> None:
    """Create the summaries collection with dense + sparse vector config.

    If recreate is True, drops and recreates the collection.
    """
    client = get_qdrant_client()

    if recreate:
        client.delete_collection(COLLECTION_NAME)
    elif client.collection_exists(COLLECTION_NAME):
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": VectorParams(
                size=DENSE_VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(
                index=SparseIndexParams(on_disk=False),
                modifier=Modifier.IDF,
            ),
        },
    )


def _point_id(key: str) -> str:
    """Deterministic point ID from a string key, formatted as a dashed UUID.

    Callers pass the **source path** (repo-relative), not the summary file name.
    Source paths are stable across re-summarizations; summary filenames change
    (the filename is the content digest). A stable point ID means Qdrant
    upsert cleanly overwrites in place on content change instead of leaking
    an orphan point at the old digest.

    We emit the MD5 as a dashed UUID (8-4-4-4-12) because that's how Qdrant
    canonicalizes IDs it stores; returning the dashed form here keeps
    `_point_id(...)` and `str(scrolled_point.id)` comparable in set math.
    """
    h = hashlib.md5(key.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _build_embedding_text(s: ParsedSummary) -> str:
    """Combine fields into a single string for both dense + BM25 embedding.

    Includes key_entities and identifiers so BM25 can match exact tokens
    (order numbers, dates, product names) that dense embeddings tend to wash out.
    """
    parts = [s.title, s.summary]
    if s.keywords:
        parts.append(", ".join(s.keywords))
    if s.key_entities:
        parts.append(", ".join(s.key_entities))
    if s.identifiers:
        parts.append(", ".join(s.identifiers))
    return " ".join(parts)


BATCH_SIZE = 32


def upsert_summaries(summaries: list[ParsedSummary]) -> int:
    """Embed and upsert parsed summaries into Qdrant in batches with progress.

    Returns the number of points upserted.
    """
    from tqdm import tqdm

    if not summaries:
        return 0

    client = get_qdrant_client()
    total = 0

    for i in tqdm(range(0, len(summaries), BATCH_SIZE), desc="ingesting", unit="batch"):
        batch = summaries[i : i + BATCH_SIZE]
        texts = [_build_embedding_text(s) for s in batch]
        dense_vectors = embed_dense(texts)
        sparse_vectors = embed_sparse(texts)

        points = []
        for s, dense_vec, (sparse_idx, sparse_val) in zip(
            batch, dense_vectors, sparse_vectors
        ):
            points.append(
                PointStruct(
                    id=_point_id(s.source_path),
                    vector={
                        "dense": dense_vec,
                        "sparse": SparseVector(indices=sparse_idx, values=sparse_val),
                    },
                    payload={
                        "summary": s.summary,
                        "source_path": s.source_path,
                    },
                )
            )

        client.upsert(collection_name=COLLECTION_NAME, points=points)
        total += len(points)

    return total


def upsert_csv_rows(csv_path: Path, source_rel: str) -> int:
    """Read a CSV, embed each row, and upsert one Qdrant point per row.

    Point IDs use the scheme ``_point_id(f"{source_rel}::row:{i}")``.
    The ``source_path`` payload field points to the parent CSV file so the
    answer stage reads the full file.

    Returns the number of data rows upserted.
    """
    import csv as csv_mod

    from tqdm import tqdm

    with csv_path.open(encoding="utf-8") as f:
        reader = csv_mod.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        return 0

    # Build "header: value, header: value, ..." text per row.
    texts = [
        ", ".join(f"{h}: {row.get(h, '')}" for h in headers)
        for row in rows
    ]

    client = get_qdrant_client()
    total = 0

    for i in tqdm(range(0, len(texts), BATCH_SIZE), desc=f"ingesting {csv_path.name}", unit="batch"):
        batch_texts = texts[i : i + BATCH_SIZE]
        batch_offset = i
        dense_vectors = embed_dense(batch_texts)
        sparse_vectors = embed_sparse(batch_texts)

        points = []
        for j, (text, dense_vec, (sparse_idx, sparse_val)) in enumerate(
            zip(batch_texts, dense_vectors, sparse_vectors)
        ):
            points.append(
                PointStruct(
                    id=_point_id(f"{source_rel}::row:{batch_offset + j}"),
                    vector={
                        "dense": dense_vec,
                        "sparse": SparseVector(indices=sparse_idx, values=sparse_val),
                    },
                    payload={
                        "summary": text,
                        "source_path": source_rel,
                    },
                )
            )

        client.upsert(collection_name=COLLECTION_NAME, points=points)
        total += len(points)

    return total


def get_all_point_ids() -> set[str]:
    """Return the set of all point IDs currently in the collection.

    Used for orphan cleanup: after incremental ingest, any point whose ID
    isn't in the expected set (from the manifest) gets hard-deleted.
    """
    client = get_qdrant_client()
    ids: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=512,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        ids.update(str(p.id) for p in points)
        if offset is None:
            break
    return ids


def delete_points(ids: list[str]) -> int:
    """Hard-delete the given point IDs. Returns count deleted."""
    if not ids:
        return 0
    client = get_qdrant_client()
    client.delete(collection_name=COLLECTION_NAME, points_selector=ids)
    return len(ids)
