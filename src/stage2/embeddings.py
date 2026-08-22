"""Embedding utilities: dense + sparse vectors, both via fastembed (ONNX runtime).

Switched from sentence-transformers to fastembed on 2026-04-27 to cut per-process
model load time from ~5s to ~1.5s. Same MiniLM-L6-v2 weights (ONNX export of the
original PyTorch model), same 384 output dim, same retrieval results — just a
faster deserialization path. The sparse BM25 path was already on fastembed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import SparseTextEmbedding, TextEmbedding

DENSE_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DENSE_VECTOR_SIZE = 384

SPARSE_MODEL_NAME = "Qdrant/bm25"

# Cached model instances — loaded once on first use.
_dense_model: TextEmbedding | None = None
_sparse_model: SparseTextEmbedding | None = None


def get_dense_model() -> TextEmbedding:
    """Return a cached fastembed TextEmbedding for dense MiniLM vectors."""
    global _dense_model
    if _dense_model is None:
        from fastembed import TextEmbedding
        _dense_model = TextEmbedding(model_name=DENSE_MODEL_NAME)
    return _dense_model


def get_sparse_model() -> SparseTextEmbedding:
    """Return a cached fastembed BM25 model for sparse embeddings."""
    global _sparse_model
    if _sparse_model is None:
        from fastembed import SparseTextEmbedding
        _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
    return _sparse_model


def embed_dense(texts: list[str]) -> list[list[float]]:
    """Encode texts into dense 384-dim vectors using all-MiniLM-L6-v2.

    fastembed's TextEmbedding emits L2-normalized vectors by default for the
    sentence-transformers/* models — same default as `SentenceTransformer.encode(
    normalize_embeddings=True)` we used to call. So existing Qdrant points
    embedded with the old path remain comparable to fresh queries.
    """
    model = get_dense_model()
    return [vec.tolist() for vec in model.embed(texts)]


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
