"""Tests for `build_csv_row_window_block` + `build_csv_sample_block`
(Plan #17 Part B + the 2026-05 file-level summary follow-up).

Validates the row-window construction + merging logic, and the case-A
sample block, without any Qdrant / LLM dependencies.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.stage2.search import (
    CSV_NEIGHBOR_WINDOW,
    _csv_rows_cache,
    build_csv_row_window_block,
    build_csv_sample_block,
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


# Marker text expected on matched rows. Pinned here so a typo elsewhere
# can't drift the format.
MATCH_MARKER = "(this row matched the question)"


# ---------------------------------------------------------------------------
# Format basics
# ---------------------------------------------------------------------------

def test_block_has_header_at_top(tmp_path):
    """Each window block leads with a CSV header line."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [10])
    assert block is not None
    assert block.splitlines()[0] == "id,name"


def test_data_rows_are_raw_csv_not_key_value(tmp_path):
    """Rows in the prompt block are raw CSV. The key-value `k: v | k: v`
    format is for INDEX-time embedding only, not query-time prompts."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [10])
    assert block is not None
    # Find the matched row's line.
    for line in block.splitlines():
        if "r10" in line:
            # Raw CSV: starts with the integer id, comma, name.
            assert line.startswith("10,r10")
            # Should NOT use the key-value index-time format.
            assert "id:" not in line
            assert " | " not in line
            break
    else:
        pytest.fail("matched row not found in block output")


def test_no_row_n_prefix(tmp_path):
    """Old format had `[row N]` at the start of every line. New format drops it."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [5])
    assert block is not None
    assert "[row " not in block


def test_match_marker_is_ascii_parenthetical(tmp_path):
    """Matched rows tagged with `(this row matched the question)` —
    plain ASCII, no unicode arrows that small models might tokenize poorly."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [10])
    assert block is not None
    assert MATCH_MARKER in block
    # No unicode arrow.
    assert "→" not in block
    assert "←" not in block


def test_only_matched_rows_get_marker(tmp_path):
    """Neighbors should NOT carry the matched marker — only the row
    actually retrieved."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [10])
    assert block is not None
    # Only one match in this test → marker appears exactly once.
    assert block.count(MATCH_MARKER) == 1
    # The line carrying the marker is the row 10 line specifically.
    matched_line = next(
        line for line in block.splitlines() if MATCH_MARKER in line
    )
    assert matched_line.startswith("10,r10")


# ---------------------------------------------------------------------------
# Single-hit window
# ---------------------------------------------------------------------------

def test_single_hit_includes_neighbors(tmp_path):
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [10])
    assert block is not None
    # Header + 5 rows = 6 lines (rows 8, 9, 10, 11, 12).
    lines = block.splitlines()
    assert lines[0] == "id,name"  # header
    assert lines[1].startswith("8,r8")
    assert lines[2].startswith("9,r9")
    assert lines[3].startswith("10,r10")
    assert MATCH_MARKER in lines[3]
    assert lines[4].startswith("11,r11")
    assert lines[5].startswith("12,r12")
    # No row outside the window.
    assert "r7" not in block
    assert "r13" not in block


def test_single_hit_at_start_of_file_clamps_to_zero(tmp_path):
    p = _csv_with_n_data_rows(tmp_path, 10)
    block = build_csv_row_window_block(str(p), [0])
    assert block is not None
    # Window can't go below 0; first data row is r0.
    lines = block.splitlines()
    assert lines[0] == "id,name"
    assert lines[1].startswith("0,r0")
    assert MATCH_MARKER in lines[1]


def test_single_hit_at_end_of_file_clamps_to_len(tmp_path):
    p = _csv_with_n_data_rows(tmp_path, 10)
    # Last data row index in DictReader output is 9 (zero-indexed).
    block = build_csv_row_window_block(str(p), [9])
    assert block is not None
    # Should clamp at end — no row 10/11.
    assert "r10" not in block
    # The matched row is r9.
    assert any(MATCH_MARKER in line and line.startswith("9,r9")
               for line in block.splitlines())


# ---------------------------------------------------------------------------
# Multi-hit merging
# ---------------------------------------------------------------------------

def test_overlapping_windows_merge(tmp_path):
    """Hits at rows 5 and 6: windows [3..7] and [4..8] overlap, merge to [3..8]."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [5, 6])
    assert block is not None
    # Both matches present.
    assert block.count(MATCH_MARKER) == 2
    # Single merged window: header + 6 rows (3..8 inclusive).
    sections = block.split("\n\n---\n\n")
    assert len(sections) == 1
    # No `---` divider in single window.
    assert "\n\n---\n\n" not in block


def test_disjoint_windows_stay_separate(tmp_path):
    """Hits at rows 5 and 47: ranges 3..7 and 45..49 stay as two windows
    separated by a divider, each with its own header line at the top."""
    p = _csv_with_n_data_rows(tmp_path, 100)
    block = build_csv_row_window_block(str(p), [5, 47])
    assert block is not None
    sections = block.split("\n\n---\n\n")
    assert len(sections) == 2
    # Each section has its own header.
    assert sections[0].splitlines()[0] == "id,name"
    assert sections[1].splitlines()[0] == "id,name"
    # Each section has exactly one match marker.
    assert sections[0].count(MATCH_MARKER) == 1
    assert sections[1].count(MATCH_MARKER) == 1
    # Rows in between (e.g. r20, r30) should NOT appear.
    assert "r20" not in block
    assert "r30" not in block


def test_three_hits_with_two_overlapping(tmp_path):
    """[5, 6, 47]: 5+6 merge into [3..8]; 47 stays as [45..49]. Two windows."""
    p = _csv_with_n_data_rows(tmp_path, 100)
    block = build_csv_row_window_block(str(p), [5, 6, 47])
    assert block is not None
    sections = block.split("\n\n---\n\n")
    assert len(sections) == 2
    # First section has 2 matches, second has 1.
    assert sections[0].count(MATCH_MARKER) == 2
    assert sections[1].count(MATCH_MARKER) == 1


def test_adjacent_windows_merge(tmp_path):
    """Hits at rows 5 and 9: windows [3..7] and [7..11] touch at row 7
    — merge into one window [3..11]."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [5, 9])
    assert block is not None
    # No divider.
    assert "\n\n---\n\n" not in block
    # Row 7 appears once (no duplicate from the merge).
    # Count occurrences of the row-7 line. Header is "id,name" so
    # we look for "7,r7" prefix.
    row7_lines = [l for l in block.splitlines() if l.startswith("7,r7")]
    assert len(row7_lines) == 1


def test_duplicate_indexes_dedup(tmp_path):
    """Same row hit twice should not double-print or duplicate marker."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_row_window_block(str(p), [10, 10, 10])
    assert block is not None
    assert block.count(MATCH_MARKER) == 1


# ---------------------------------------------------------------------------
# CSV quoting / escaping
# ---------------------------------------------------------------------------

def test_values_with_commas_are_quoted(tmp_path):
    """A row value containing a comma must be CSV-quoted so the prompt
    parses unambiguously. Uses Python's csv.writer for proper escaping."""
    p = _write_csv(tmp_path, [
        ["id", "description"],
        ["1", "Hello, world"],
    ])
    block = build_csv_row_window_block(str(p), [0])
    assert block is not None
    # The comma inside the value forces the field to be quoted.
    assert '"Hello, world"' in block


# ---------------------------------------------------------------------------
# Error cases
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


# ---------------------------------------------------------------------------
# build_csv_sample_block (case A — file-level summary hit, no rows)
# ---------------------------------------------------------------------------

def test_sample_block_has_header_then_first_n_rows(tmp_path):
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_sample_block(str(p))
    assert block is not None
    lines = block.splitlines()
    assert lines[0] == "id,name"  # header
    # Default max_rows=5 → 5 data rows after header.
    assert len(lines) == 1 + 5
    assert lines[1].startswith("0,r0")
    assert lines[5].startswith("4,r4")


def test_sample_block_no_match_marker(tmp_path):
    """case-A rows weren't directly retrieved — no `(this row matched the
    question)` marker should appear."""
    p = _csv_with_n_data_rows(tmp_path, 50)
    block = build_csv_sample_block(str(p))
    assert block is not None
    assert MATCH_MARKER not in block


def test_sample_block_caps_at_file_length(tmp_path):
    """If the CSV has fewer rows than `max_rows`, return what's available
    (don't pad with empty lines)."""
    p = _csv_with_n_data_rows(tmp_path, 3)
    block = build_csv_sample_block(str(p), max_rows=10)
    assert block is not None
    lines = block.splitlines()
    assert len(lines) == 1 + 3  # header + 3 actual rows


def test_sample_block_unreadable_returns_none(tmp_path):
    block = build_csv_sample_block(str(tmp_path / "missing.csv"))
    assert block is None
