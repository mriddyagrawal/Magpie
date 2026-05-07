"""Unit tests for the deterministic CSV stats block appended to T1 summaries.

Pure-function tests: write a small CSV to tmp_path, call
`compute_csv_stats_markdown`, assert structural facts about the output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.csv_stats import (
    LOW_CARDINALITY_THRESHOLD,
    compute_csv_stats_markdown,
)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Helper: write a CSV file with the given header + rows."""
    import csv

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Basic shape
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


def test_per_column_section_present(tmp_path):
    p = tmp_path / "x.csv"
    write_csv(p, ["a", "b"], [["1", "x"], ["2", "y"]])
    out = compute_csv_stats_markdown(p)
    assert "Per-column statistics" in out
    assert "**a**" in out
    assert "**b**" in out


# ---------------------------------------------------------------------------
# Numeric columns
# ---------------------------------------------------------------------------

def test_numeric_column_renders_range_and_mean(tmp_path):
    """For a fully-numeric column, surface min/max/mean so questions like
    'what's the credit range?' can be answered without reading the file."""
    p = tmp_path / "x.csv"
    write_csv(p, ["credits"], [["4"], ["2"], ["0"], ["4"], ["8"]])
    out = compute_csv_stats_markdown(p)
    assert "numeric range: 0 – 8" in out
    assert "mean: 3.60" in out


def test_numeric_with_units_still_parses(tmp_path):
    """'4 credits' or '$1,234.56' shouldn't be detected as numeric — those
    are categorical strings. Only bare numbers parse."""
    p = tmp_path / "x.csv"
    write_csv(p, ["credits"], [["4 credits"], ["2 credits"], ["0 credits"]])
    out = compute_csv_stats_markdown(p)
    # Should NOT have a numeric-range line since "4 credits" isn't a bare number.
    assert "numeric range:" not in out


def test_numeric_column_with_commas_and_percent(tmp_path):
    """Common cleanings — commas in 1,234 and trailing %. These should parse."""
    p = tmp_path / "x.csv"
    write_csv(p, ["pct"], [["50%"], ["75%"], ["12.5%"]])
    out = compute_csv_stats_markdown(p)
    assert "numeric range: 12.50 – 75" in out


def test_numeric_column_with_dollar_sign(tmp_path):
    p = tmp_path / "x.csv"
    write_csv(p, ["amount"], [["$1,000"], ["$2,500.50"]])
    out = compute_csv_stats_markdown(p)
    assert "numeric range: 1000 – 2500.50" in out


# ---------------------------------------------------------------------------
# Categorical / low-cardinality
# ---------------------------------------------------------------------------

def test_low_cardinality_column_renders_full_distribution(tmp_path):
    """A column with <=12 distinct values gets its full value distribution
    rendered. This is what answers 'how many courses are 4-credit?' from
    the summary."""
    p = tmp_path / "x.csv"
    write_csv(
        p,
        ["credits"],
        [
            ["4 credits"],
            ["4 credits"],
            ["4 credits"],
            ["2 credits"],
            ["0 credits"],
        ],
    )
    out = compute_csv_stats_markdown(p)
    assert "`4 credits` (3)" in out
    assert "`2 credits` (1)" in out
    assert "`0 credits` (1)" in out


def test_high_cardinality_column_renders_sample_not_full(tmp_path):
    """A title column with 100 unique values shouldn't dump all 100 — sample
    a few. This keeps the summary bounded."""
    p = tmp_path / "x.csv"
    rows = [[f"Title-{i}"] for i in range(LOW_CARDINALITY_THRESHOLD + 5)]
    write_csv(p, ["title"], rows)
    out = compute_csv_stats_markdown(p)
    # Should have a "sample:" line, not full distribution
    assert "sample:" in out
    # Should not enumerate every single value
    full_dist_lines = [
        line for line in out.split("\n") if line.strip().startswith("- `Title-")
    ]
    assert len(full_dist_lines) == 0


def test_empty_count_reported(tmp_path):
    """When some rows have empty values for a column, count them — useful for
    questions like 'how many CSC courses have empty prereqs?'"""
    p = tmp_path / "x.csv"
    write_csv(
        p,
        ["prereq"],
        [["CSC-121"], [""], ["CSC-122"], [""], [""]],
    )
    out = compute_csv_stats_markdown(p)
    assert "3 empty" in out


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_csv_returns_zero_rows(tmp_path):
    """Header-only CSV: render Rows: 0 + the columns line, no per-column section."""
    p = tmp_path / "empty.csv"
    write_csv(p, ["a", "b"], [])
    out = compute_csv_stats_markdown(p)
    assert "**Rows:** 0" in out
    assert "Per-column statistics" not in out


def test_no_header_returns_diagnostic_message(tmp_path):
    """A truly empty CSV (no header row at all) shouldn't crash — surface
    a one-line diagnostic instead."""
    p = tmp_path / "really_empty.csv"
    p.write_text("")
    out = compute_csv_stats_markdown(p)
    assert "no header row" in out


def test_malformed_csv_returns_diagnostic(tmp_path):
    """Defensive: garbage input should never raise from this helper."""
    p = tmp_path / "binary.csv"
    p.write_bytes(b"\x00\x01\x02\x03\xff\xfe")  # not text
    out = compute_csv_stats_markdown(p)
    # Either succeeds (DictReader is tolerant) or returns the diagnostic.
    # Either way: never raises.
    assert isinstance(out, str)
    assert len(out) > 0


def test_long_value_truncated(tmp_path):
    """Description columns can be paragraph-length; we truncate so the
    summary stays bounded."""
    p = tmp_path / "x.csv"
    long_value = "x" * 200
    write_csv(p, ["desc"], [[long_value], [long_value]])  # low-cardinality
    out = compute_csv_stats_markdown(p)
    # The full 200-char string should NOT appear verbatim in the rendered output.
    assert "x" * 200 not in out
    # But the truncated version (with ellipsis) should.
    assert "…" in out


def test_latin1_fallback_for_non_utf8(tmp_path):
    """Some Excel exports ship as Latin-1. Don't crash on UnicodeDecodeError."""
    p = tmp_path / "latin.csv"
    # Mix of ASCII header + Latin-1 row content
    p.write_bytes(b"name,note\nfoo,caf\xe9\nbar,na\xefve\n")
    out = compute_csv_stats_markdown(p)
    # Should successfully render the row count
    assert "**Rows:** 2" in out


# ---------------------------------------------------------------------------
# Realistic shape: regression for the exact eval failure mode
# ---------------------------------------------------------------------------

def test_realistic_course_catalog_shape(tmp_path):
    """Mirrors the structure of csc.csv from the eval corpus. Asserts the
    things that would have rescued course_information q07 / q08 / q21 / q23
    in the eval if this had been in the summary at retrieval time."""
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

    # Row count present
    assert "**Rows:** 4" in out
    # Column names enumerated
    assert "code" in out and "credits" in out
    # Distribution of low-cardinality values: 0-credit courses are visible
    assert "`0 credits` (1)" in out
    # 4-credit total visible
    assert "`4 credits` (3)" in out
    # Empty-prereq count visible (would help "courses with no prereqs" queries)
    assert "2 empty" in out  # 2 of 4 rows have empty prereqs
