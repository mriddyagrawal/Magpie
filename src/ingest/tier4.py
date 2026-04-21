"""Tier 4 — ColPali multi-vector visual embeddings.

Used for: scanned PDFs, standalone images, figure-heavy DOCX (pending support).
Delegates to the existing `src/stage1_fast/` pipeline which:

  - Renders each page (PDF via pymupdf, images via PIL)
  - Encodes with the auto-selected ColPali-family model (ColQwen2.5 on GPU,
    ColSmol-500M on CPU)
  - Upserts patches into Qdrant's `fast_tier` multi-vector collection
    (int8-quantized by default, see `src/stage2/fast_db.py`)
  - Records `fast_indexed_at` + `fast_pages` in the manifest

Unlike T0/T1/T2/T3, T4 does NOT produce a summary markdown — its output is
patch vectors in a separate Qdrant collection. The walker records this by
leaving `summary_file=None` on the manifest row and relying on the router
audit fields + existing `fast_indexed_at` bookkeeping.
"""

from __future__ import annotations

from pathlib import Path

from src.ingest.common import TierOutcome
from src.manifest import Manifest


def run(path: Path, source_rel: str, manifest: Manifest) -> TierOutcome:
    """Run the ColPali pipeline for a single file. Returns an outcome whose
    `summary_file_rel` is None — the T4 artifacts live in Qdrant, not on disk.
    """
    # Local import keeps the rest of the walker snappy — pulls in torch+colpali.
    from src.stage1_fast.index import index_file
    from src.stage2.fast_db import ensure_fast_collection

    ensure_fast_collection()
    pages, _was_skipped = index_file(path, manifest)
    return TierOutcome(summary_file_rel=None, body_chars=pages)
