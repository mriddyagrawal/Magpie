"""Embedding utilities: dense vectors via sentence-transformers, sparse via fastembed BM25."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import SparseTextEmbedding
    from sentence_transformers import SentenceTransformer

DENSE_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DENSE_VECTOR_SIZE = 384

SPARSE_MODEL_NAME = "Qdrant/bm25"

# Cached model instances — loaded once on first use.
_dense_model: SentenceTransformer | None = None
_sparse_model: SparseTextEmbedding | None = None


def get_dense_model() -> SentenceTransformer:
    """Return a cached sentence-transformers model for dense embeddings."""
    global _dense_model
    if _dense_model is None:
        from sentence_transformers import SentenceTransformer
        _dense_model = SentenceTransformer(DENSE_MODEL_NAME)
    return _dense_model


def get_sparse_model() -> SparseTextEmbedding:
    """Return a cached fastembed BM25 model for sparse embeddings."""
    global _sparse_model
    if _sparse_model is None:
        from fastembed import SparseTextEmbedding
        _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
    return _sparse_model


def embed_dense(texts: list[str]) -> list[list[float]]:
    """Encode texts into dense 384-dim vectors using all-MiniLM-L6-v2."""
    model = get_dense_model()
    return model.encode(texts, normalize_embeddings=True).tolist()


def embed_dense_query(query: str) -> list[float]:
    """Encode a single query into a dense vector."""
    return embed_dense([query])[0]


def embed_sparse(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    """Encode texts into sparse BM25 vectors.

    Returns a list of (indices, values) tuples — one per input text.
    """
    model = get_sparse_model()
    results = list(model.embed(texts))
    return [(r.indices.tolist(), r.values.tolist()) for r in results]


def embed_sparse_query(query: str) -> tuple[list[int], list[float]]:
    """Encode a single query into a sparse BM25 vector."""
    return embed_sparse([query])[0]
