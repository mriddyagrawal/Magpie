"""Tier 0 — register + on-demand ripgrep: file is too big / too rowy to embed.

Used for: huge text/code files (>100 KB / >500 KB), log files, huge CSVs
(>100k rows), giant JSON dumps.

We do NOT read the whole file. We write a small summary-markdown with:
  - filename + size as the title
  - first 2 KB of the file OR the first 100 CSV rows as the body (for BM25)
  - identifiers include the filename and file size

At query time, the answer agent has `ripgrep_file(path, pattern)` to pull
specific rows/lines on demand. No LLM call during ingest.
"""

from __future__ import annotations

import csv as csv_mod
from pathlib import Path

from src.content import CSV_EXTS
from src.ingest.common import (
    TierOutcome,
    render_summary_markdown,
    summary_output_path,
    summary_rel_path,
    title_from_path,
    write_summary,
)


T0_PREVIEW_BYTES = 2 * 1024           # 2 KB of content preview for BM25
T0_CSV_PREVIEW_ROWS = 100


def _head_text(path: Path) -> str:
    """Return the first T0_PREVIEW_BYTES of a file, lossy-decoded."""
    try:
        with path.open("rb") as f:
            data = f.read(T0_PREVIEW_BYTES)
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _csv_preview(path: Path) -> tuple[str, int]:
    """Return (preview_text, total_rows) — streams header + first 100 rows."""
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            reader = csv_mod.reader(f)
            rows: list[list[str]] = []
            total = 0
            try:
                header = next(reader)
                rows.append(header)
            except StopIteration:
                return "", 0
            for row in reader:
                total += 1
                if len(rows) <= T0_CSV_PREVIEW_ROWS:
                    rows.append(row)
            text = "\n".join(",".join(r) for r in rows)
            return text, total
    except (OSError, csv_mod.Error):
        return "", 0


def run(path: Path, source_rel: str) -> TierOutcome:
    ext = path.suffix.lower()
    size_bytes = path.stat().st_size

    if ext in CSV_EXTS:
        body, total_rows = _csv_preview(path)
        content_type = "csv"
        identifiers = [path.name, f"{total_rows} rows", f"{size_bytes} bytes"]
        keywords = [path.name, "csv", "large"]
        title = f"{title_from_path(path)} — CSV, {total_rows} rows"
    else:
        body = _head_text(path)
        content_type = "text-large"
        identifiers = [path.name, f"{size_bytes} bytes"]
        keywords = [path.name, "large", "preview-only"]
        title = f"{title_from_path(path)} — {size_bytes // 1024} KB preview"

    if not body.strip():
        body = f"(could not preview; file is {size_bytes} bytes — use ripgrep at query time)"

    md = render_summary_markdown(
        source_rel=source_rel,
        title=title,
        body=body,
        content_type=content_type,
        keywords=keywords,
        entities=[],
        identifiers=identifiers,
    )

    out = summary_output_path(path, "t0")
    write_summary(out, md)
    return TierOutcome(
        summary_file_rel=summary_rel_path(out),
        body_chars=len(body),
    )
