"""Tests for Qdrant database operations.

Verifies the IO contract:
- Input:  ParsedSummary objects
- Output: PointStruct with payload = {summary, source_path} only
- Embedding text combines title + summary + keywords
- Point IDs are deterministic from summary_file
"""

from unittest.mock import MagicMock, patch

import pytest

from src.stage2.db import (
    COLLECTION_NAME,
    DenseDimMismatchError,
    _build_embedding_text,
    _point_id,
    assert_dense_dim_match,
)
from src.stage2.embeddings import DENSE_VECTOR_SIZE
from src.stage2.parser import ParsedSummary

SAMPLE = ParsedSummary(
    source_path="Test Content/Flight GSP - Hartford Receipt.pdf",
    title="Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley",
    summary="This receipt documents a $170.45 USD flight booking transaction.",
    content_type="pdf",
    keywords=["Breeze Airways", "Greenville-Spartanburg", "Flight Receipt"],
    key_entities=["Mridul Agrawal", "Rahul Ranjan Sah"],
    identifiers=["X7QK2M", "$170.45"],
    summary_file="Test Summaries/8c2bbf673a91ef8d.md",
)


def test_point_id_deterministic():
    """Same summary_file must always produce the same point ID."""
    id1 = _point_id("Test Summaries/8c2bbf673a91ef8d.md")
    id2 = _point_id("Test Summaries/8c2bbf673a91ef8d.md")
    assert id1 == id2


def test_point_id_unique():
    """Different summary_files must produce different point IDs."""
    id1 = _point_id("Test Summaries/8c2bbf673a91ef8d.md")
    id2 = _point_id("Test Summaries/ee0b5a0cf8c431f7.md")
    assert id1 != id2


def test_embedding_text_contains_title():
    """Embedding text must include the title for semantic matching."""
    text = _build_embedding_text(SAMPLE)
    assert "Breeze Airways Flight Receipt" in text


def test_embedding_text_contains_summary():
    """Embedding text must include the summary body."""
    text = _build_embedding_text(SAMPLE)
    assert "$170.45" in text


def test_embedding_text_contains_keywords():
    """Embedding text must include keywords for richer embeddings."""
    text = _build_embedding_text(SAMPLE)
    assert "Greenville-Spartanburg" in text
    assert "Flight Receipt" in text


def test_embedding_text_includes_entities():
    """Key entities MUST be in the embedded text — discriminators for BM25.

    Updated from the original `excludes_entities` test: we deliberately
    include entities + identifiers in the embedding text now so BM25 can
    match verbatim tokens (names, order numbers, exact amounts) that dense
    embeddings tend to wash out. See `src/stage2/db.py:_build_embedding_text`.
    """
    text = _build_embedding_text(SAMPLE)
    assert "Mridul Agrawal" in text
    assert "Rahul Ranjan Sah" in text


def test_embedding_text_includes_identifiers():
    """Same reasoning: exact-match tokens (order #, dates, totals) reach BM25."""
    text = _build_embedding_text(SAMPLE)
    assert "X7QK2M" in text
    assert "$170.45" in text


def test_embedding_text_excludes_source_path():
    """Source path is metadata, not part of the embedding."""
    text = _build_embedding_text(SAMPLE)
    assert "Test Content/" not in text


# ---------------------------------------------------------------------------
# B3 — embedding-dimension mismatch detection
# ---------------------------------------------------------------------------


def _mock_collection_info(dense_size: int | None) -> MagicMock:
    """Build a Qdrant get_collection() response with the given dense vector size."""
    info = MagicMock()
    info.config = MagicMock()
    info.config.params = MagicMock()
    if dense_size is None:
        info.config.params.vectors = {}
    else:
        dense_cfg = MagicMock()
        dense_cfg.size = dense_size
        info.config.params.vectors = {"dense": dense_cfg}
    return info


@patch("src.stage2.db.get_qdrant_client")
def test_assert_dim_match_passes_on_correct_dim(mock_client):
    """When the stored dim equals the configured one, no exception."""
    client = mock_client.return_value
    client.collection_exists.return_value = True
    client.get_collection.return_value = _mock_collection_info(DENSE_VECTOR_SIZE)

    # Should not raise.
    assert_dense_dim_match(collection=COLLECTION_NAME)


@patch("src.stage2.db.get_qdrant_client")
def test_assert_dim_match_raises_on_mismatch(mock_client):
    """Mismatch raises DenseDimMismatchError with both sizes + remediation hint."""
    wrong_size = DENSE_VECTOR_SIZE + 384  # E5-base would be 768 vs MiniLM's 384
    client = mock_client.return_value
    client.collection_exists.return_value = True
    client.get_collection.return_value = _mock_collection_info(wrong_size)

    with pytest.raises(DenseDimMismatchError) as excinfo:
        assert_dense_dim_match(collection=COLLECTION_NAME)

    err = excinfo.value
    assert err.expected == DENSE_VECTOR_SIZE
    assert err.found == wrong_size
    assert err.collection == COLLECTION_NAME
    # Message mentions both sizes and tells user how to fix
    msg = str(err)
    assert str(DENSE_VECTOR_SIZE) in msg
    assert str(wrong_size) in msg
    assert "ingest --force" in msg


@patch("src.stage2.db.get_qdrant_client")
def test_assert_dim_match_noop_on_missing_collection(mock_client):
    """Fresh setup — collection doesn't exist yet — should pass silently."""
    client = mock_client.return_value
    client.collection_exists.return_value = False

    assert_dense_dim_match(collection=COLLECTION_NAME)
    # get_collection must NOT be called — that would error on a missing collection
    client.get_collection.assert_not_called()


@patch("src.stage2.db.get_qdrant_client")
def test_assert_dim_match_handles_collection_with_no_dense(mock_client):
    """A collection that has no `dense` named vector → no-op (nothing to compare).

    Defensive against schema migrations or stale configs from earlier versions
    of the project that used a different vector layout.
    """
    client = mock_client.return_value
    client.collection_exists.return_value = True
    info = _mock_collection_info(dense_size=None)
    client.get_collection.return_value = info

    # Should not raise.
    assert_dense_dim_match(collection=COLLECTION_NAME)
