"""File routing: decide which tier a file belongs to.

See `Plans/IO - Colpali.md` for the full policy. Summary:

- PDFs > 50 pages                        → summary tier (storage budget)
- PDFs ≤ 50 pages, text-HEAVY (embedded
  text extracts cleanly)                 → summary tier (BM25+dense wins)
- PDFs ≤ 50 pages, text-SPARSE (scans,
  photos, diagram-dominant)              → fast tier (ColPali earns cost)
- PNG/JPG/JPEG/WEBP                      → fast tier (always visual)
- everything else (docx, xlsx, csv, code,
  markdown, text)                        → summary tier

The text-density peek costs ~10-50 ms per PDF but saves seconds to minutes
of ColPali forward-pass time per text-heavy document that would otherwise
go to fast tier unnecessarily. Net win starts at ~3-5 PDFs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

FAST_TIER_PDF_MAX_PAGES = 50
FAST_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Avg chars of extractable text per sampled page below which we consider
# the PDF "text-sparse" (scan, photo, or diagram-heavy) and route to fast
# tier. 100 chars ≈ one short sentence — typical OCR-free scans come in
# at <10, embedded-text receipts at 300+, lecture notes at 500+. 100 is
# a safe middle ground; can be tuned in v1.1 after we measure recall.
FAST_TIER_TEXT_CHAR_THRESHOLD = 100

# How many pages to sample for the density estimate. First + middle + last
# catches cover-sheet edge cases (blank cover, text body) without reading
# the whole document. For PDFs with ≤3 pages we just read them all.
_SAMPLE_CAP = 3

Tier = Literal["fast", "summary", "skip"]


def _pdf_routing_signal(path: Path) -> tuple[int, int]:
    """Peek at a PDF: return (n_pages, avg_chars_per_sampled_page).

    Returns (-1, -1) on any read failure so the caller can skip the file.
    Costs ~10-50 ms per PDF — pymupdf memory-maps the file and
    `page.get_text()` walks the already-parsed text stream without
    rendering or OCR.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return -1, -1
    try:
        doc = pymupdf.open(path)
    except Exception:  # pylint: disable=broad-except
        return -1, -1

    try:
        n_pages = len(doc)
        if n_pages == 0:
            return 0, 0

        # Sample first, middle, last — unique indices, capped at 3.
        if n_pages <= _SAMPLE_CAP:
            sample_idx = list(range(n_pages))
        else:
            sample_idx = sorted({0, n_pages // 2, n_pages - 1})

        total_chars = 0
        for i in sample_idx:
            try:
                total_chars += len(doc[i].get_text())
            except Exception:  # pylint: disable=broad-except
                # Malformed page — treat as zero-text, conservatively visual.
                continue

        avg_chars = total_chars // max(len(sample_idx), 1)
        return n_pages, avg_chars
    finally:
        doc.close()


def route_file(path: Path) -> Tier:
    """Return the tier this file belongs to, or "skip" if unsupported.

    For PDFs ≤50 pages, the routing decision depends on embedded-text
    density — see module docstring. Extension-only decisions cover images
    (always fast) and everything else (always summary).
    """
    if not path.is_file() or path.name.startswith("."):
        return "skip"

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        n_pages, avg_chars = _pdf_routing_signal(path)
        if n_pages < 0:
            return "skip"
        if n_pages > FAST_TIER_PDF_MAX_PAGES:
            return "summary"
        if avg_chars >= FAST_TIER_TEXT_CHAR_THRESHOLD:
            return "summary"  # text-heavy — BM25 + dense beats ColPali here
        return "fast"  # sparse/visual — ColPali's native territory

    if suffix in FAST_IMAGE_EXTS:
        return "fast"

    # docx, xlsx, csv, md, txt, code, everything else.
    return "summary"
