"""Tests for the search pipeline.

Mocked — both Kimi (query rewrite) and Qdrant (vector search) are external.
Tests verify the wiring: that search_summaries correctly connects
rewrite → embed → Qdrant query → SearchResult output.
"""

from unittest.mock import MagicMock, patch

from src.stage2.search import SearchQuery, SearchResult, search_summaries


def _make_mock_point(summary: str, source_path: str, score: float) -> MagicMock:
    """Create a mock Qdrant ScoredPoint."""
    point = MagicMock()
    point.payload = {"summary": summary, "source_path": source_path}
    point.score = score
    return point


@patch("src.stage2.search.rewrite_query")
@patch("src.stage2.search.embed_dense_query")
@patch("src.stage2.search.embed_sparse_query")
@patch("src.stage2.search.get_qdrant_client")
def test_search_returns_search_results(mock_client, mock_sparse, mock_dense, mock_rewrite):
    """search_summaries must return a list of SearchResult with summary, path, score."""
    mock_rewrite.return_value = SearchQuery(
        query="flight receipt booking cost",
        keywords=["flight", "receipt", "cost"],
    )
    mock_dense.return_value = [0.1] * 384
    mock_sparse.return_value = ([1, 2, 3], [0.5, 0.3, 0.2])

    mock_response = MagicMock()
    mock_response.points = [
        _make_mock_point(
            summary="This receipt documents a $170.45 USD flight booking.",
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
    assert results[0].score == 0.87


@patch("src.stage2.search.rewrite_query")
@patch("src.stage2.search.embed_dense_query")
@patch("src.stage2.search.embed_sparse_query")
@patch("src.stage2.search.get_qdrant_client")
def test_search_empty_results(mock_client, mock_sparse, mock_dense, mock_rewrite):
    """search_summaries must return empty list when Qdrant finds nothing."""
    mock_rewrite.return_value = SearchQuery(
        query="something that matches nothing",
        keywords=["nonexistent"],
    )
    mock_dense.return_value = [0.0] * 384
    mock_sparse.return_value = ([1], [0.1])

    mock_response = MagicMock()
    mock_response.points = []
    mock_client.return_value.query_points.return_value = mock_response

    results = search_summaries("gibberish query", top_k=5)
    assert results == []


@patch("src.stage2.search.rewrite_query")
@patch("src.stage2.search.embed_dense_query")
@patch("src.stage2.search.embed_sparse_query")
@patch("src.stage2.search.get_qdrant_client")
def test_search_respects_top_k(mock_client, mock_sparse, mock_dense, mock_rewrite):
    """The top_k parameter must be forwarded to Qdrant query_points."""
    mock_rewrite.return_value = SearchQuery(query="test", keywords=["test"])
    mock_dense.return_value = [0.1] * 384
    mock_sparse.return_value = ([1], [0.1])

    mock_response = MagicMock()
    mock_response.points = []
    mock_client.return_value.query_points.return_value = mock_response

    search_summaries("test", top_k=3)

    call_kwargs = mock_client.return_value.query_points.call_args
    assert call_kwargs.kwargs["limit"] == 3


@patch("src.stage2.search.rewrite_query")
@patch("src.stage2.search.embed_dense_query")
@patch("src.stage2.search.embed_sparse_query")
@patch("src.stage2.search.get_qdrant_client")
def test_search_output_has_only_three_fields(mock_client, mock_sparse, mock_dense, mock_rewrite):
    """SearchResult must expose exactly summary, path, score — nothing else."""
    mock_rewrite.return_value = SearchQuery(query="test", keywords=["test"])
    mock_dense.return_value = [0.1] * 384
    mock_sparse.return_value = ([1], [0.1])

    mock_response = MagicMock()
    mock_response.points = [
        _make_mock_point("summary text", "path/to/file.pdf", 0.5),
    ]
    mock_client.return_value.query_points.return_value = mock_response

    results = search_summaries("test", top_k=1)
    r = results[0]

    fields = {f.name for f in r.__dataclass_fields__.values()}
    assert fields == {"summary", "path", "score"}
