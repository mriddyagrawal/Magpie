"""Deterministic CSV statistics for inclusion in T1 CSV summaries.

The T1 CSV summarizer (`src/ingest/tier1.py`) asks an LLM to describe what
a CSV is *about* — that's good for retrieval (semantic match on "course
catalog", "people directory", etc.) but the LLM is unreliable on
counting tasks. The benchmarks in `benchmarks/course_information/`
showed Magpie consistently undercounting on questions like "how many
courses are in the SUS major?" because it was counting only the top-5
retrieved rows, not the file.

This module computes a deterministic stats block that gets appended to
the LLM-generated summary so retrieval-time aggregation queries can be
answered straight from the summary's text. The block contains:

- Row count
- Column count + names
- Per-column: distinct value count, empty-count
- For numeric columns: min, max, mean
- For low-cardinality string columns (<=12 distinct values): full
  value distribution
- For high-cardinality columns: 3 sample values

The block is markdown so it renders alongside the LLM prose and embeds
well as text. The numbers are exact — small models still won't count
the 56 rows of vp.csv from a sample, but they don't have to: they read
"Rows: 56" from the summary.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

# Beyond this threshold, render samples instead of full distribution so
# the summary stays bounded for catalogs of 100s of distinct titles /
# descriptions etc.
LOW_CARDINALITY_THRESHOLD = 12

# Truncate individual cell values when rendered in the distribution / samples.
# Description columns can be paragraph-length; we don't need the full text
# (the row-level points already embed it).
CELL_PREVIEW_MAX_CHARS = 80


def compute_csv_stats_markdown(path: Path) -> str:
    """Return a markdown stats block to append to a CSV's T1 summary.

    Best-effort: malformed CSVs and encoding errors degrade gracefully to
    a one-line note rather than raising. Always returns a string (never
    raises), so the caller can append unconditionally.
    """
    try:
        rows, cols = _read_csv(path)
    except Exception as e:  # noqa: BLE001 — defensive
        return (
            "\n## File statistics\n\n"
            f"_could not compute statistics for this CSV: {type(e).__name__}: {e}_\n"
        )

    if not cols:
        return "\n## File statistics\n\n_CSV has no header row_\n"
    if not rows:
        return (
            "\n## File statistics\n\n"
            f"- **Rows:** 0\n"
            f"- **Columns ({len(cols)}):** {', '.join(cols)}\n"
        )

    lines: list[str] = [
        "",
        "## File statistics",
        "",
        f"- **Rows:** {len(rows)}",
        f"- **Columns ({len(cols)}):** {', '.join(cols)}",
        "",
        "### Per-column statistics",
        "",
    ]

    for col in cols:
        values = [str(r.get(col, "") or "").strip() for r in rows]
        non_empty = [v for v in values if v]
        empty_count = len(values) - len(non_empty)
        distinct = sorted(set(non_empty))

        lines.append(f"**{col}**")
        lines.append(
            f"- {len(distinct)} distinct value(s), {empty_count} empty"
        )

        # Numeric column? Compute range + mean.
        nums = _try_parse_numeric_column(non_empty)
        if nums is not None:
            lines.append(
                f"- numeric range: {_fmt(min(nums))} – {_fmt(max(nums))}, "
                f"mean: {_fmt(sum(nums) / len(nums))}"
            )

        # Distribution vs sample.
        if 0 < len(distinct) <= LOW_CARDINALITY_THRESHOLD:
            counts = Counter(non_empty).most_common()
            for v, n in counts:
                lines.append(f"  - `{_truncate(v)}` ({n})")
        elif distinct:
            sample = distinct[:3]
            lines.append(
                f"- sample: {', '.join(repr(_truncate(s)) for s in sample)}"
            )

        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read a CSV, falling back to latin-1 on UTF-8 decode errors."""
    try:
        with path.open("r", encoding="utf-8", errors="strict", newline="") as f:
            reader = csv.DictReader(f)
            cols = list(reader.fieldnames or [])
            rows = list(reader)
    except UnicodeDecodeError:
        with path.open("r", encoding="latin-1", newline="") as f:
            reader = csv.DictReader(f)
            cols = list(reader.fieldnames or [])
            rows = list(reader)
    return rows, cols


def _try_parse_numeric_column(non_empty: list[str]) -> list[float] | None:
    """If every non-empty value parses as a number (allowing commas, %, $),
    return the list of floats. Otherwise return None — column is treated as
    categorical / text."""
    if not non_empty:
        return None
    out: list[float] = []
    for v in non_empty:
        cleaned = v.strip().lstrip("$").rstrip("%").replace(",", "")
        try:
            out.append(float(cleaned))
        except ValueError:
            return None
    return out


def _fmt(x: float) -> str:
    """Render a number cleanly: integers without trailing zeros, others to 2dp."""
    if x == int(x):
        return f"{int(x)}"
    return f"{x:.2f}"


def _truncate(s: str) -> str:
    """Cap a single rendered value so the summary stays bounded."""
    if len(s) <= CELL_PREVIEW_MAX_CHARS:
        return s
    return s[: CELL_PREVIEW_MAX_CHARS - 1] + "…"
