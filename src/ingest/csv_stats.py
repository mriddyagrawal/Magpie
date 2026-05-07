"""Deterministic minimum-stats block for T1 CSV summaries.

The T1 CSV summarizer (`src/ingest/tier1.py`) asks an LLM to describe what
a CSV is *about* — that's good for retrieval (semantic match on "course
catalog", "people directory", etc.) but the LLM is unreliable on
counting tasks. The benchmarks (`benchmarks/course_information/REPORT.md`)
showed Magpie undercounting on questions like "how many courses?"
because it was counting top-k retrieved rows, not the file.

This module appends the minimum deterministic information to fix that:
just **row count + column names**. Both are universally useful (no
domain assumptions), tiny (~2 lines), and don't leak per-cell content
into the summary.

We deliberately do NOT include per-column distributions / numeric
ranges / value samples here. Those are useful for some datasets but
noisy / leaky for others, and Magpie is a general product. If a
specific corpus needs richer stats, that's a per-deployment override,
not a default.
"""

from __future__ import annotations

import csv
from pathlib import Path


def compute_csv_stats_markdown(path: Path) -> str:
    """Return a markdown stats block to append to a CSV's T1 summary.

    Best-effort: malformed CSVs and encoding errors degrade to a
    one-line diagnostic rather than raising. Always returns a string.
    """
    try:
        rows, cols = _read_csv(path)
    except Exception as e:  # noqa: BLE001 — defensive, never raise from here
        return (
            "\n## File statistics\n\n"
            f"_could not compute statistics: {type(e).__name__}: {e}_\n"
        )

    if not cols:
        return "\n## File statistics\n\n_CSV has no header row_\n"

    columns_line = (
        f"- **Columns ({len(cols)}):** {', '.join(cols)}"
        if cols
        else "- **Columns:** 0"
    )
    return (
        "\n## File statistics\n\n"
        f"- **Rows:** {len(rows)}\n"
        f"{columns_line}\n"
    )


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
