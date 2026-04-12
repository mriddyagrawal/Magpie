"""Qdrant Cloud client setup and collection operations."""

from __future__ import annotations

import hashlib
import os
import sys

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

from notanotherspotlight.embeddings import DENSE_VECTOR_SIZE, embed_dense, embed_sparse
from notanotherspotlight.parser import ParsedSummary

COLLECTION_NAME = "summaries"

_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """Return a cached Qdrant Cloud client, reading credentials from env vars."""
    global _client
    if _client is not None:
        return _client

    url = os.environ.get("Qdrant_CLUSTER_ENDPOINT")
    api_key = os.environ.get("Qdrant_API_KEY")
    if not url or not api_key:
        sys.exit(
            "error: Qdrant_CLUSTER_ENDPOINT and Qdrant_API_KEY must be set in .env"
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


def _point_id(summary_file: str) -> str:
    """Deterministic point ID from the summary filename hash."""
    return hashlib.md5(summary_file.encode()).hexdigest()


def _build_embedding_text(s: ParsedSummary) -> str:
    """Combine fields into a single string for dense embedding."""
    parts = [s.title, s.summary]
    if s.keywords:
        parts.append(", ".join(s.keywords))
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
                    id=_point_id(s.summary_file),
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
