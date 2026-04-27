"""Tests for src/stage2/rerank.py — cross-encoder reranker (B4).

The cross-encoder model is heavy (~80 MB download, transformers + torch),
so all tests mock `_load_model()` and assert on the wiring, not the model
itself. The model's actual ranking quality is its problem; we only verify
that we feed it the right pairs and respect its output ordering.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.stage2.rerank import rerank
from src.stage2.search import SearchResult


def _mk(path: str, summary: str, rrf_score: float = 0.016, tier: str = "summary") -> SearchResult:
    return SearchResult(summary=summary, path=path, score=rrf_score, tier=tier)


@patch("src.stage2.rerank._load_model")
def test_rerank_reorders_by_cross_encoder_score(mock_load):
    """Higher cross-encoder score → ranked higher in the output."""
    model = MagicMock()
    # Three candidates; cross-encoder thinks the second is most relevant,
    # then the third, then the first. RRF order would have been (a, b, c).
    model.predict.return_value = np.array([0.1, 0.9, 0.5])
    mock_load.return_value = model

    cands = [_mk("a", "Alice"), _mk("b", "Bob"), _mk("c", "Carol")]
    out = rerank("who is best", cands, top_k=3)

    assert [r.path for r in out] == ["b", "c", "a"]
    # Scores get rewritten with the cross-encoder values
    assert out[0].score == pytest.approx(0.9)
    assert out[1].score == pytest.approx(0.5)
    assert out[2].score == pytest.approx(0.1)


@patch("src.stage2.rerank._load_model")
def test_rerank_truncates_to_top_k(mock_load):
    """Reranker returns at most `top_k` results, in best-first order."""
    model = MagicMock()
    model.predict.return_value = np.array([0.5, 0.8, 0.2, 0.9, 0.6])
    mock_load.return_value = model

    cands = [_mk(f"p{i}", f"summary {i}") for i in range(5)]
    out = rerank("q", cands, top_k=3)

    assert len(out) == 3
    # Sorted descending by predicted score: p3 (0.9) > p1 (0.8) > p4 (0.6)
    assert [r.path for r in out] == ["p3", "p1", "p4"]


@patch("src.stage2.rerank._load_model")
def test_rerank_empty_input_returns_empty(mock_load):
    """Zero candidates → zero output, no model call."""
    out = rerank("q", [], top_k=5)
    assert out == []
    mock_load.assert_not_called()


@patch("src.stage2.rerank._load_model")
def test_rerank_single_candidate_short_circuits(mock_load):
    """One candidate is already ranked — skip the model entirely."""
    cands = [_mk("only", "the only one", rrf_score=0.42)]
    out = rerank("q", cands, top_k=5)

    assert out == cands
    assert out[0].score == pytest.approx(0.42)  # RRF score preserved
    mock_load.assert_not_called()


@patch("src.stage2.rerank._load_model")
def test_rerank_uses_summary_text_not_path(mock_load):
    """Cross-encoder pairs are (query, summary), not (query, path)."""
    model = MagicMock()
    model.predict.return_value = np.array([0.1, 0.9])
    mock_load.return_value = model

    cands = [
        _mk("/some/path/file_one.pdf", "talks about Mozart's operas"),
        _mk("/another/path/file_two.pdf", "covers tax form processing"),
    ]
    rerank("Mozart compositions", cands, top_k=2)

    # Verify the model was called with (query, summary) pairs.
    args, _ = model.predict.call_args
    pairs = args[0]
    assert pairs == [
        ("Mozart compositions", "talks about Mozart's operas"),
        ("Mozart compositions", "covers tax form processing"),
    ]


@patch("src.stage2.rerank._load_model")
def test_rerank_falls_back_to_path_when_summary_missing(mock_load):
    """Empty-summary candidates (e.g. fast-tier visual hits) use path as the doc text."""
    model = MagicMock()
    model.predict.return_value = np.array([0.5, 0.3])
    mock_load.return_value = model

    cands = [
        _mk("/path/to/visual_doc.pdf", ""),     # empty summary → fall back to path
        _mk("/path/normal.pdf", "real summary"),  # second candidate to force model call
    ]
    rerank("query", cands, top_k=2)

    args, _ = model.predict.call_args
    assert args[0] == [
        ("query", "/path/to/visual_doc.pdf"),
        ("query", "real summary"),
    ]


@patch("src.stage2.rerank._load_model")
def test_rerank_preserves_tier(mock_load):
    """The `tier` field on each result is preserved through rerank."""
    model = MagicMock()
    model.predict.return_value = np.array([0.5, 0.8])
    mock_load.return_value = model

    cands = [
        _mk("a", "from summary tier", tier="summary"),
        _mk("b", "from fast tier", tier="fast"),
    ]
    out = rerank("q", cands, top_k=2)

    # b ranks first (higher score) and keeps its fast-tier tag
    assert out[0].path == "b"
    assert out[0].tier == "fast"
    assert out[1].tier == "summary"
