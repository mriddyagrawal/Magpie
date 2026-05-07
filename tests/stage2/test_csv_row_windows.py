"""Tests for `build_csv_row_window_block` (Plan #17 Part B).

Validates the row-window construction + merging logic without any Qdrant /
LLM dependencies.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.stage2.search import (
    CSV_NEIGHBOR_WINDOW,
    _csv_rows_cache,
    build_csv_row_window_block,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """`_load_csv_rows` caches per-process. Clear between tests so each
    test sees a fresh read of its fixture file."""
    _csv_rows_cache.clear()
    yield
    _csv_rows_cache.clear()


def _write_csv(tmp_path: Path, rows: list[list[str]]) -> Path:
    p = tmp_path / "rows.csv"
    with p.open("w", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)
    return p


def _csv_with_n_data_rows(tmp_path: Path, n: int) -> Path:
    """Header + N rows with predictable content: row {i} → 'r{i}'."""
    rows = [["id", "name"]] + [[str(i), f"r{i}"] for i in range(n)]
    return _write_csv(tmp_path, rows)


# ---------------------------------------------------------------------------
# single-hit window
# ---------------------------------------------------------------------------

def test_single_hit_includes_neighbors(tmp_path):
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [10])
    assert block is not None
    assert "[row 10 (match)]" in block
    # ±2 neighbors = rows 8, 9, 11, 12
    assert "[row 8]" in block
    assert "[row 9]" in block
    assert "[row 11]" in block
    assert "[row 12]" in block
    # No row outside the window.
    assert "[row 7]" not in block
    assert "[row 13]" not in block


def test_single_hit_at_start_of_file_clamps_to_zero(tmp_path):
    p = _csv_with_n_data_rows(tmp_path, 10)
    block = build_csv_row_window_block(str(p), [0])
    assert block is not None
    assert "[row 0 (match)]" in block
    assert "[row 1]" in block
    assert "[row 2]" in block
    # No "row -1" leaks
    assert "[row -" not in block


def test_single_hit_at_end_of_file_clamps_to_len(tmp_path):
    p = _csv_with_n_data_rows(tmp_path, 10)
    # Last data row index in the parsed dict is 9 (zero-indexed, 10 rows total).
    block = build_csv_row_window_block(str(p), [9])
    assert block is not None
    assert "[row 9 (match)]" in block
    # Should clamp at the end — no row 10/11.
    assert "[row 10]" not in block


# ---------------------------------------------------------------------------
# multi-hit merging
# ---------------------------------------------------------------------------

def test_overlapping_windows_merge(tmp_path):
    """Hits at rows 5 and 6: windows [3..7] and [4..8] overlap, merge to [3..8]."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [5, 6])
    assert block is not None
    # Both matches present.
    assert "[row 5 (match)]" in block
    assert "[row 6 (match)]" in block
    # Single merged window should include 3..8 inclusive.
    for i in range(3, 9):
        assert f"[row {i}" in block
    # Should NOT have a section divider since it's one window.
    assert "\n\n---\n\n" not in block


def test_disjoint_windows_stay_separate(tmp_path):
    """Hits at rows 5 and 47: ranges 3..7 and 45..49 stay as two windows
    separated by a divider."""
    p = _csv_with_n_data_rows(tmp_path, 100)
    block = build_csv_row_window_block(str(p), [5, 47])
    assert block is not None
    # Both matches.
    assert "[row 5 (match)]" in block
    assert "[row 47 (match)]" in block
    # Divider between disjoint windows.
    assert "\n\n---\n\n" in block
    # Rows in between should NOT be present.
    assert "[row 20]" not in block
    assert "[row 30]" not in block


def test_three_hits_with_two_overlapping(tmp_path):
    """[5, 6, 47]: 5+6 merge into [3..8]; 47 stays as [45..49]. Two windows."""
    p = _csv_with_n_data_rows(tmp_path, 100)
    block = build_csv_row_window_block(str(p), [5, 6, 47])
    assert block is not None
    sections = block.split("\n\n---\n\n")
    assert len(sections) == 2
    # First section spans rows 3..8.
    assert "[row 3]" in sections[0]
    assert "[row 8]" in sections[0]
    assert "[row 5 (match)]" in sections[0]
    assert "[row 6 (match)]" in sections[0]
    # Second section spans rows 45..49.
    assert "[row 45]" in sections[1]
    assert "[row 47 (match)]" in sections[1]
    assert "[row 49]" in sections[1]


def test_adjacent_windows_merge(tmp_path):
    """Hits at rows 5 and 9: windows [3..7] and [7..11] touch at row 7
    — merge into one window [3..11]."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [5, 9])
    assert block is not None
    # No divider.
    assert "\n\n---\n\n" not in block
    # Row 7 appears once (no duplicate from the merge).
    assert block.count("[row 7]") == 1


def test_duplicate_indexes_dedup(tmp_path):
    """Same row hit twice should not double-print."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [10, 10, 10])
    assert block is not None
    assert block.count("[row 10 (match)]") == 1


# ---------------------------------------------------------------------------
# error cases
# ---------------------------------------------------------------------------

def test_unreadable_csv_returns_none(tmp_path):
    block = build_csv_row_window_block(str(tmp_path / "missing.csv"), [0])
    assert block is None


def test_empty_indexes_returns_none(tmp_path):
    p = _csv_with_n_data_rows(tmp_path, 10)
    block = build_csv_row_window_block(str(p), [])
    assert block is None


def test_default_window_matches_constant(tmp_path):
    """Sanity: the default `window=` arg uses CSV_NEIGHBOR_WINDOW."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block_default = build_csv_row_window_block(str(p), [10])
    block_explicit = build_csv_row_window_block(
        str(p), [10], window=CSV_NEIGHBOR_WINDOW
    )
    assert block_default == block_explicit
