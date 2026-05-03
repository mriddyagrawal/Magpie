"""Tier 1 — direct embed: file IS the content.

Used for: small `.txt .md .json .yaml .toml`, code files, small CSVs.

No LLM call. We write a summary markdown whose body is the raw file content
(capped at DEFAULT_BODY_MAX_CHARS, except for CSVs which use a larger limit
to support row-level indexing). Filename is included in the title so
BM25 hits filename-like queries. Stage 2's parser then embeds that body
verbatim — which is the whole point: exact-token matches survive.
"""

from __future__ import annotations

from pathlib import Path

from src.ingest.common import (
    DEFAULT_BODY_MAX_CHARS,
    TierOutcome,
    render_summary_markdown,
    summary_output_path,
    summary_rel_path,
    title_from_path,
    write_summary,
)
from src.router import CSV_SIZE_T1_MAX


def run(path: Path, source_rel: str) -> TierOutcome:
    """Read the file, write a summary-markdown whose body is the raw content."""
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8", errors="ignore")

    ext = path.suffix.lower()
    is_csv = ext == ".csv"

    # CSVs get a much larger cap to support row-by-row indexing in Stage 2.
    # Non-CSVs stay at the default 8k cap to avoid drowning retrieval in noise.
    cap = CSV_SIZE_T1_MAX if is_csv else DEFAULT_BODY_MAX_CHARS
    body = raw[:cap].strip()
    if not body:
        body = "(empty file)"

    content_type = (
        "markdown" if ext in {".md", ".markdown"}
        else "code" if ext in {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
            ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".swift", ".kt",
            ".sh", ".sql",
        }
        else "config" if ext in {".json", ".yaml", ".yml", ".toml"}
        else "csv" if is_csv
        else "text"
    )

    md = render_summary_markdown(
        source_rel=source_rel,
        title=f"{title_from_path(path)} ({path.name})",
        body=body,
        content_type=content_type,
        keywords=[path.name, content_type],
        entities=[],
        identifiers=[path.name],
    )

    out = summary_output_path(path, "t1")
    write_summary(out, md)
    return TierOutcome(
        summary_file_rel=summary_rel_path(out),
        body_chars=len(body),
    )
