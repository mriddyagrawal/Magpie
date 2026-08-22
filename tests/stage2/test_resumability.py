"""Tests for Ctrl-C resumability — manifest is updated per batch instead of
once-at-the-end, so cancellation never loses already-completed work.

Without this, a 38-minute push interrupted at 60% would re-do every
already-pushed batch on the next run because the manifest had no record of
their completion (despite the points already being in Qdrant).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.stage2 import db as db_mod
from src.stage2.db import upsert_summaries
from src.stage2.parser import ParsedSummary


def _summary(i: int) -> ParsedSummary:
    return ParsedSummary(
        source_path=f"file{i}.pdf",
        title=f"file {i}",
        summary=f"summary {i}",
        content_type="pdf",
        keywords=[],
        key_entities=[],
        identifiers=[],
        summary_file=f"Test Summaries/{i}.md",
    )


@patch.object(db_mod, "embed_dense")
@patch.object(db_mod, "embed_sparse")
@patch.object(db_mod, "_upsert_with_retry")
@patch.object(db_mod, "get_qdrant_client")
def test_on_batch_complete_fires_after_each_batch(
    mock_client, mock_upsert, mock_sparse, mock_dense
):
    """Callback is called once per batch with the indices in `summaries`."""
    mock_dense.return_value = [[0.1] * 384] * 70
    mock_sparse.return_value = [([1], [0.5])] * 70

    summaries = [_summary(i) for i in range(70)]  # 70 = >2 batches at 32

    completed_indices: list[list[int]] = []

    def on_batch(indices: list[int]) -> None:
        completed_indices.append(indices)

    upsert_summaries(summaries, on_batch_complete=on_batch)

    # 70 / 32 = 3 batches: [0..31], [32..63], [64..69]
    assert len(completed_indices) == 3
    assert completed_indices[0] == list(range(0, 32))
    assert completed_indices[1] == list(range(32, 64))
    assert completed_indices[2] == list(range(64, 70))


@patch.object(db_mod, "embed_dense")
@patch.object(db_mod, "embed_sparse")
@patch.object(db_mod, "_upsert_with_retry")
@patch.object(db_mod, "get_qdrant_client")
def test_callback_only_fires_after_successful_upsert(
    mock_client, mock_upsert, mock_sparse, mock_dense
):
    """If an upsert raises, the callback for that batch must NOT fire — the
    points aren't in Qdrant yet, so we can't claim them as done."""
    mock_dense.return_value = [[0.1] * 384] * 64
    mock_sparse.return_value = [([1], [0.5])] * 64

    # Second batch fails
    call_count = {"n": 0}

    def upsert_with_retry(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated qdrant down")

    mock_upsert.side_effect = upsert_with_retry

    summaries = [_summary(i) for i in range(64)]
    completed_indices: list[list[int]] = []

    try:
        upsert_summaries(summaries, on_batch_complete=completed_indices.append)
    except RuntimeError:
        pass

    # First batch's callback fired (its upsert succeeded)
    assert len(completed_indices) == 1
    assert completed_indices[0] == list(range(0, 32))


@patch.object(db_mod, "embed_dense")
@patch.object(db_mod, "embed_sparse")
@patch.object(db_mod, "_upsert_with_retry")
@patch.object(db_mod, "get_qdrant_client")
def test_no_callback_argument_is_noop(
    mock_client, mock_upsert, mock_sparse, mock_dense
):
    """Existing callers that don't pass `on_batch_complete` continue to work."""
    mock_dense.return_value = [[0.1] * 384] * 5
    mock_sparse.return_value = [([1], [0.5])] * 5

    summaries = [_summary(i) for i in range(5)]
    # Should not raise
    total = upsert_summaries(summaries)
    assert total == 5
