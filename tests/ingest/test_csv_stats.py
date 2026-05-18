"""Unit tests for the CSV stats block appended to T1 summaries.

The block is intentionally minimal: just row count + column names.
We don't include per-column distributions / numeric ranges / sample
values — those are domain-specific and Magpie ships as a general
product. The tests pin that minimum and verify graceful handling of
malformed input.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.ingest.csv_stats import compute_csv_stats_markdown


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Helper: write a CSV file with the given header + rows."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Core: row count + column names
# ---------------------------------------------------------------------------

def test_row_count_appears_in_output(tmp_path):
    """The headline number — without it the whole feature is pointless."""
    p = tmp_path / "courses.csv"
    write_csv(
        p,
        ["code", "title", "credits"],
        [["CSC-105", "Intro CS", "4"]] * 27,
    )
    out = compute_csv_stats_markdown(p)
    assert "**Rows:** 27" in out


def test_column_names_listed(tmp_path):
    p = tmp_path / "x.csv"
    write_csv(p, ["a", "b", "c"], [["1", "2", "3"]])
    out = compute_csv_stats_markdown(p)
    assert "**Columns (3):** a, b, c" in out


def test_minimal_output_is_short(tmp_path):
    """The whole block should be a handful of lines, not a wall of stats.
    Pins the design choice: keep this minimal across all CSV shapes."""
    p = tmp_path / "x.csv"
    # Even a 100-column CSV with 1000 rows shouldn't blow up the summary.
    cols = [f"c{i}" for i in range(100)]
    rows = [[str(j)] * 100 for j in range(1000)]
    write_csv(p, cols, rows)
    out = compute_csv_stats_markdown(p)
    # Five lines: blank, header, blank, rows-line, columns-line, trailing newline.
    assert out.count("\n") <= 6


# ---------------------------------------------------------------------------
# Edge cases — must never raise
# ---------------------------------------------------------------------------

def test_empty_csv_zero_rows(tmp_path):
    """Header-only CSV: render Rows: 0 + the columns line."""
    p = tmp_path / "empty.csv"
    write_csv(p, ["a", "b"], [])
    out = compute_csv_stats_markdown(p)
    assert "**Rows:** 0" in out
    assert "**Columns (2):**" in out


def test_no_header_returns_diagnostic(tmp_path):
    """A truly empty CSV (no header at all) shouldn't crash — return a
    diagnostic line so downstream code can append unconditionally."""
    p = tmp_path / "really_empty.csv"
    p.write_text("")
    out = compute_csv_stats_markdown(p)
    assert "no header row" in out


def test_malformed_csv_does_not_raise(tmp_path):
    """Defensive: this helper is called from every T1 CSV ingest. Garbage
    input must degrade gracefully, not crash the ingest worker."""
    p = tmp_path / "binary.csv"
    p.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
    out = compute_csv_stats_markdown(p)
    assert isinstance(out, str)
    assert len(out) > 0


def test_latin1_fallback_for_non_utf8(tmp_path):
    """Some Excel exports ship as Latin-1. The stats helper must not
    block ingest on UnicodeDecodeError."""
    p = tmp_path / "latin.csv"
    p.write_bytes(b"name,note\nfoo,caf\xe9\nbar,na\xefve\n")
    out = compute_csv_stats_markdown(p)
    assert "**Rows:** 2" in out


# ---------------------------------------------------------------------------
# Realistic shape: still answers the load-bearing eval questions
# ---------------------------------------------------------------------------

def test_realistic_course_catalog_shape(tmp_path):
    """csc.csv-shaped input. The minimal block still answers 'how many
    CSC courses?' from the row count alone — that's the core eval failure
    this feature exists to fix."""
    p = tmp_path / "csc.csv"
    write_csv(
        p,
        ["coid", "code", "title", "ger", "prerequisites", "description", "credits"],
        [
            ["66387", "CSC-105", "Intro to Computer Science", "GER: MR", "", "...", "4 credits"],
            ["66388", "CSC-121", "Intro to Computer Programming", "GER: MR", "", "...", "4 credits"],
            ["66389", "CSC-122", "Data Structures and Algorithms", "", "CSC-121", "...", "4 credits"],
            ["67390", "CSC-025", "Programming Workshop", "", "CSC-121", "...", "0 credits"],
        ],
    )
    out = compute_csv_stats_markdown(p)
    assert "**Rows:** 4" in out
    assert "code" in out and "credits" in out
