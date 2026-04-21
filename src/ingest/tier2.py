"""Tier 2 — extract-then-embed: text lives inside a non-text container.

Used for: text-native PDF, DOCX, XLSX (and medium CSV).

We reuse `src/content.py`'s extractors (already handling the hard parts —
encrypted PDFs, malformed docx, etc.), trim to `DEFAULT_BODY_MAX_CHARS`,
and write a summary-markdown whose body is the extracted text verbatim.
No LLM call.
"""

from __future__ import annotations

from pathlib import Path

from src.content import (
    CSV_EXTS,
    DOCX_EXTS,
    PDF_EXTS,
    SummarizeError,
    XLSX_EXTS,
    extract_docx_text,
    extract_pdf_text,
    extract_xlsx_text,
)
from src.ingest.common import (
    DEFAULT_BODY_MAX_CHARS,
    TierOutcome,
    render_summary_markdown,
    summary_output_path,
    summary_rel_path,
    title_from_path,
    write_summary,
)


def _extract(path: Path) -> tuple[str, str]:
    """Return (body_text, content_type). Raises SummarizeError on failure."""
    ext = path.suffix.lower()

    if ext in PDF_EXTS:
        text = extract_pdf_text(path, DEFAULT_BODY_MAX_CHARS)
        return text, "pdf"

    if ext in DOCX_EXTS:
        text = extract_docx_text(path)
        return text, "docx"

    if ext in XLSX_EXTS:
        text = extract_xlsx_text(path)
        return text, "xlsx"

    if ext in CSV_EXTS:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise SummarizeError(f"csv not UTF-8: {path}: {e}") from e
        return text, "csv"

    raise SummarizeError(f"tier2 cannot handle extension {ext!r} for {path}")


def run(path: Path, source_rel: str) -> TierOutcome:
    text, content_type = _extract(path)
    body = text[:DEFAULT_BODY_MAX_CHARS].strip()
    if not body:
        raise SummarizeError(f"tier2 extracted empty text from {path}")

    md = render_summary_markdown(
        source_rel=source_rel,
        title=f"{title_from_path(path)} ({path.name})",
        body=body,
        content_type=content_type,
        keywords=[path.name, content_type],
        entities=[],
        identifiers=[path.name],
    )

    out = summary_output_path(path, "t2")
    write_summary(out, md)
    return TierOutcome(
        summary_file_rel=summary_rel_path(out),
        body_chars=len(body),
    )
