"""Tests for the search pipeline.

Mocked — both Kimi (query rewrite) and Qdrant (vector search) are external.
Tests verify the wiring: that `search_summaries` correctly connects
rewrite → embed → Qdrant query → SearchResult output.

Since the search pipeline now fuses both the `summaries` and `fast_tier`
(ColPali) collections, each test stubs `_search_fast_tier` to return an
empty list so we can assert purely on the summaries-collection behavior.
"""

from unittest.mock import MagicMock, patch

from src.stage2.search import SearchQuery, SearchResult, search_summaries


def _make_mock_point(summary: str, source_path: str, score: float) -> MagicMock:
    """Create a mock Qdrant ScoredPoint."""
    point = MagicMock()
    point.payload = {"summary": summary, "source_path": source_path}
    point.score = score
    return point


@patch("src.stage2.search._summary_for_result",
       return_value="This receipt documents a $170.45 USD flight booking.")
@patch("src.stage2.search._search_fast_tier", return_value=[])
@patch("src.stage2.search.rewrite_query")
@patch("src.stage2.search.embed_dense_query")
@patch("src.stage2.search.embed_sparse_query")
@patch("src.stage2.search.get_qdrant_client")
def test_search_returns_search_results(
    mock_client, mock_sparse, mock_dense, mock_rewrite, _mock_fast, _mock_summary
):
    """search_summaries must return a list of SearchResult with summary, path, score.

    The summary text is reconstructed from disk in `_summary_for_result`
    (since 2026-05 — payload-only Qdrant points). Mocked here so the test
    doesn't depend on a live manifest / summary markdown on disk."""
    mock_rewrite.return_value = SearchQuery(
        query="flight receipt booking cost",
        keywords=["flight", "receipt", "cost"],
    )
    mock_dense.return_value = [0.1] * 384
    mock_sparse.return_value = ([1, 2, 3], [0.5, 0.3, 0.2])

    # `summaries` collection exists; the fast-tier mock above bypasses that side.
    mock_client.return_value.collection_exists.return_value = True
    mock_response = MagicMock()
    mock_response.points = [
        _make_mock_point(
            summary="(unused — summary now reconstructed from disk)",
            source_path="Test Content/Flight GSP - Hartford Receipt.pdf",
            score=0.87,
        ),
    ]
    mock_client.return_value.query_points.return_value = mock_response

    results = search_summaries("how much was the flight?", top_k=5)

    assert len(results) == 1
    assert isinstance(results[0], SearchResult)
    assert results[0].summary == "This receipt documents a $170.45 USD flight booking."
    assert results[0].path == "Test Content/Flight GSP - Hartford Receipt.pdf"
    assert results[0].tier == "summary"


@patch("src.stage2.search._search_fast_tier", return_value=[])
@patch("src.stage2.search.rewrite_query")
@patch("src.stage2.search.embed_dense_query")
@patch("src.stage2.search.embed_sparse_query")
@patch("src.stage2.search.get_qdrant_client")
def test_search_empty_results(
    mock_client, mock_sparse, mock_dense, mock_rewrite, _mock_fast
):
    """search_summaries must return empty list when Qdrant finds nothing."""
    mock_rewrite.return_value = SearchQuery(
        query="something that matches nothing",
        keywords=["nonexistent"],
    )
    mock_dense.return_value = [0.0] * 384
    mock_sparse.return_value = ([1], [0.1])

    mock_client.return_value.collection_exists.return_value = True
    mock_response = MagicMock()
    mock_response.points = []
    mock_client.return_value.query_points.return_value = mock_response

    results = search_summaries("gibberish query", top_k=5)
    assert results == []


@patch("src.stage2.search._search_fast_tier", return_value=[])
@patch("src.stage2.search.rewrite_query")
@patch("src.stage2.search.embed_dense_query")
@patch("src.stage2.search.embed_sparse_query")
@patch("src.stage2.search.get_qdrant_client")
def test_search_respects_top_k(
    mock_client, mock_sparse, mock_dense, mock_rewrite, _mock_fast
):
    """top_k drives the final result-list length after fusion.

    (Internally the summary-tier prefetches 2× top_k for RRF headroom, so
    we assert on the fused output, not the Qdrant call limit.)
    """
    mock_rewrite.return_value = SearchQuery(query="test", keywords=["test"])
    mock_dense.return_value = [0.1] * 384
    mock_sparse.return_value = ([1], [0.1])

    mock_client.return_value.collection_exists.return_value = True
    mock_response = MagicMock()
    mock_response.points = [
        _make_mock_point(f"s{i}", f"p{i}", 0.9 - i * 0.05) for i in range(10)
    ]
    mock_client.return_value.query_points.return_value = mock_response

    results = search_summaries("test", top_k=3)
    assert len(results) == 3


@patch("src.stage2.search._search_fast_tier", return_value=[])
@patch("src.stage2.search.rewrite_query")
@patch("src.stage2.search.embed_dense_query")
@patch("src.stage2.search.embed_sparse_query")
@patch("src.stage2.search.get_qdrant_client")
def test_search_output_exposes_expected_fields(
    mock_client, mock_sparse, mock_dense, mock_rewrite, _mock_fast
):
    """SearchResult must expose summary, path, score, tier — the agreed surface.

    `tier` was added when fast-tier (ColPali) landed so callers can tell
    which collection produced each hit. Anything more than these four is
    a leak.
    """
    mock_rewrite.return_value = SearchQuery(query="test", keywords=["test"])
    mock_dense.return_value = [0.1] * 384
    mock_sparse.return_value = ([1], [0.1])

    mock_client.return_value.collection_exists.return_value = True
    mock_response = MagicMock()
    mock_response.points = [
        _make_mock_point("summary text", "path/to/file.pdf", 0.5),
    ]
    mock_client.return_value.query_points.return_value = mock_response

    results = search_summaries("test", top_k=1)
    r = results[0]

    fields = {f.name for f in r.__dataclass_fields__.values()}
    # `chunk_index` added 2026-05 alongside CSV row-level points (Plan #17).
    # Optional field — None for non-chunked file-level points.
    assert fields == {"summary", "path", "score", "tier", "chunk_index"}
