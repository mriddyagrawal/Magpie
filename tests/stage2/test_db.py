"""Tests for Qdrant database operations.

Verifies the IO contract:
- Input:  ParsedSummary objects
- Output: PointStruct with payload = {summary, source_path} only
- Embedding text combines title + summary + keywords
- Point IDs are deterministic from summary_file
"""

from src.stage2.db import _build_embedding_text, _point_id
from src.stage2.parser import ParsedSummary

SAMPLE = ParsedSummary(
    source_path="Test Content/Flight GSP - Hartford Receipt.pdf",
    title="Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley",
    summary="This receipt documents a $170.45 USD flight booking transaction.",
    content_type="pdf",
    keywords=["Breeze Airways", "Greenville-Spartanburg", "Flight Receipt"],
    key_entities=["Mridul Agrawal", "Rahul Ranjan Sah"],
    identifiers=["R2NDSL", "$170.45"],
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
    assert "R2NDSL" in text
    assert "$170.45" in text


def test_embedding_text_excludes_source_path():
    """Source path is metadata, not part of the embedding."""
    text = _build_embedding_text(SAMPLE)
    assert "Test Content/" not in text
