"""Tests for `_rrf_merge` keying — pure function, no Qdrant.

The 2026-05 audit caught a real correctness bug: when many CSV row hits
share the same `source_path`, the old `chosen[r.path] = r` keying
collapsed them all into one SearchResult, silently losing every row's
`chunk_index` except the last. These tests pin the new
`(path, chunk_index)` composite key.
"""

from __future__ import annotations

import pytest

from src.stage2.search import SearchResult, _hit_key, _rrf_merge


def _hit(path: str, chunk_index=None, summary: str = "x") -> SearchResult:
    return SearchResult(summary=summary, path=path, score=0.0, chunk_index=chunk_index)


# ---------------------------------------------------------------------------
# _hit_key
# ---------------------------------------------------------------------------

def test_hit_key_includes_chunk_index():
    """Composite key — file path + chunk index."""
    a = _hit("foo.csv", chunk_index=5)
    b = _hit("foo.csv", chunk_index=6)
    c = _hit("foo.csv", chunk_index=None)
    assert _hit_key(a) != _hit_key(b)
    assert _hit_key(a) != _hit_key(c)
    assert _hit_key(c) == ("foo.csv", None)


def test_hit_key_collapses_for_same_chunk():
    """Same path AND same chunk → same key (idempotent dedup)."""
    a = _hit("foo.csv", chunk_index=5)
    b = _hit("foo.csv", chunk_index=5)
    assert _hit_key(a) == _hit_key(b)


# ---------------------------------------------------------------------------
# _rrf_merge — the bug
# ---------------------------------------------------------------------------

def test_rrf_preserves_distinct_chunks_in_same_file():
    """REGRESSION: 5 row hits in the same CSV must survive RRF as 5
    SearchResults, NOT collapse to 1. Pre-fix `chosen[path] = r` kept
    only the last; this test pins the new `(path, chunk_index)` keying."""
    summary_hits = [
        _hit("furman.csv", chunk_index=5,  summary="row 5"),
        _hit("furman.csv", chunk_index=6,  summary="row 6"),
        _hit("furman.csv", chunk_index=47, summary="row 47"),
    ]
    fused = _rrf_merge(summary_hits, fast_hits=[], top_k=10)

    assert len(fused) == 3, f"all 3 row hits must survive; got {len(fused)}"
    surviving_chunks = {r.chunk_index for r in fused}
    assert surviving_chunks == {5, 6, 47}


def test_rrf_file_level_dedup_across_tiers_still_works():
    """A non-chunked PDF point in summary tier + same path in fast tier
    should still merge to one SearchResult (legacy behavior preserved
    via `(path, None)` key collapse)."""
    summary_hits = [_hit("doc.pdf", chunk_index=None, summary="prose")]
    fast_hits = [_hit("doc.pdf", chunk_index=None, summary="(visual)")]
    fused = _rrf_merge(summary_hits, fast_hits, top_k=10)

    assert len(fused) == 1
    # The summary-tier entry wins (has the human-readable summary).
    assert fused[0].summary == "prose"
    assert fused[0].tier == "both"


def test_rrf_csv_rows_dont_collide_with_file_level_pdf():
    """Distinct files don't merge regardless of chunk_index."""
    summary_hits = [
        _hit("a.csv", chunk_index=0, summary="csv row"),
        _hit("b.pdf", chunk_index=None, summary="pdf prose"),
    ]
    fused = _rrf_merge(summary_hits, fast_hits=[], top_k=10)

    assert len(fused) == 2
    paths = {r.path for r in fused}
    assert paths == {"a.csv", "b.pdf"}


def test_rrf_score_accumulates_per_chunk_not_per_path():
    """Each (path, chunk_index) should accumulate its own RRF score from
    summary + fast tiers separately. CSV rows and a same-path PDF page
    don't share scores."""
    summary_hits = [_hit("foo.csv", chunk_index=0)]
    fast_hits = [_hit("foo.csv", chunk_index=0)]  # hypothetical fast on same chunk
    fused = _rrf_merge(summary_hits, fast_hits, top_k=10)

    # The (foo.csv, 0) key appears in both tiers → tier="both".
    assert len(fused) == 1
    assert fused[0].tier == "both"
    # Score is the sum of both tiers' RRF contributions.
    # (rank=1 in both → 2/(60+1) = 2/61)
    assert fused[0].score == pytest.approx(2.0 / 61.0)


def test_rrf_top_k_truncates():
    """The top_k argument still truncates after fusion."""
    summary_hits = [
        _hit("a.csv", chunk_index=i) for i in range(20)
    ]
    fused = _rrf_merge(summary_hits, fast_hits=[], top_k=5)
    assert len(fused) == 5


def test_rrf_path_dedup_collapses_duplicate_chunk():
    """Two summary-tier hits at the same (path, chunk_index) are deduped
    into one — but the score accumulates."""
    summary_hits = [
        _hit("foo.csv", chunk_index=5, summary="first"),
        _hit("foo.csv", chunk_index=5, summary="second"),
    ]
    fused = _rrf_merge(summary_hits, fast_hits=[], top_k=10)
    assert len(fused) == 1
    # Last one wins on the dict assignment.
    assert fused[0].summary == "second"
    # Score accumulates from both ranks: 1/61 + 1/62
    expected = 1.0 / 61.0 + 1.0 / 62.0
    assert fused[0].score == pytest.approx(expected)
