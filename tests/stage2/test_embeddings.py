"""Tests for embedding models.

No mocks needed — both models run locally.
Verifies IO contract:
- Dense:  list[str] → list[list[float]], each 384-dim, normalized
- Sparse: list[str] → list[(indices, values)], indices are ints, values are floats
"""

from src.stage2.embeddings import (
    DENSE_VECTOR_SIZE,
    embed_dense,
    embed_dense_query,
    embed_sparse,
    embed_sparse_query,
)


# ---------------------------------------------------------------------------
# Dense embeddings (MiniLM)
# ---------------------------------------------------------------------------

def test_dense_single_query_shape():
    """Single query must return a flat list of 384 floats."""
    vec = embed_dense_query("flight receipt cost")
    assert isinstance(vec, list)
    assert len(vec) == DENSE_VECTOR_SIZE
    assert all(isinstance(v, float) for v in vec)


def test_dense_batch_shape():
    """Batch of N texts must return N vectors, each 384-dim."""
    texts = ["flight receipt", "Plato education", "club budget"]
    vecs = embed_dense(texts)
    assert len(vecs) == 3
    for vec in vecs:
        assert len(vec) == DENSE_VECTOR_SIZE


def test_dense_deterministic():
    """Same input must produce the same embedding."""
    v1 = embed_dense_query("Breeze Airways flight receipt")
    v2 = embed_dense_query("Breeze Airways flight receipt")
    assert v1 == v2


def test_dense_different_inputs_differ():
    """Different inputs must produce different embeddings."""
    v1 = embed_dense_query("flight receipt")
    v2 = embed_dense_query("Plato Republic philosophy")
    assert v1 != v2


def test_dense_normalized():
    """Vectors should be roughly unit length (normalized)."""
    vec = embed_dense_query("test normalization")
    magnitude = sum(v ** 2 for v in vec) ** 0.5
    assert abs(magnitude - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Sparse embeddings (BM25)
# ---------------------------------------------------------------------------

def test_sparse_single_query_shape():
    """Single query must return (indices, values) tuple."""
    indices, values = embed_sparse_query("flight receipt cost")
    assert isinstance(indices, list)
    assert isinstance(values, list)
    assert len(indices) == len(values)
    assert all(isinstance(i, int) for i in indices)
    assert all(isinstance(v, float) for v in values)


def test_sparse_batch_shape():
    """Batch of N texts must return N (indices, values) tuples."""
    texts = ["flight receipt", "Plato education"]
    results = embed_sparse(texts)
    assert len(results) == 2
    for indices, values in results:
        assert len(indices) == len(values)


def test_sparse_indices_unique():
    """BM25 term indices must be unique within a single vector."""
    indices, _ = embed_sparse_query("flight receipt booking cost")
    assert len(indices) == len(set(indices))


def test_sparse_values_positive():
    """BM25 term weights must be positive."""
    _, values = embed_sparse_query("flight receipt")
    assert all(v > 0 for v in values)
