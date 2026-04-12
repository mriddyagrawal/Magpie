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
    summary_file="Summaries/8c2bbf673a91ef8d.md",
)


def test_point_id_deterministic():
    """Same summary_file must always produce the same point ID."""
    id1 = _point_id("Summaries/8c2bbf673a91ef8d.md")
    id2 = _point_id("Summaries/8c2bbf673a91ef8d.md")
    assert id1 == id2


def test_point_id_unique():
    """Different summary_files must produce different point IDs."""
    id1 = _point_id("Summaries/8c2bbf673a91ef8d.md")
    id2 = _point_id("Summaries/ee0b5a0cf8c431f7.md")
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


def test_embedding_text_excludes_entities():
    """Key entities feed BM25 via the full text, not the dense embedding input."""
    text = _build_embedding_text(SAMPLE)
    assert "Mridul Agrawal" not in text


def test_embedding_text_excludes_source_path():
    """Source path is metadata, not part of the embedding."""
    text = _build_embedding_text(SAMPLE)
    assert "Test Content/" not in text
