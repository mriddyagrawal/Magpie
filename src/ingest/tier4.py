"""Tier 4 — ColPali multi-vector visual embeddings.

Used for: scanned PDFs, standalone images, figure-heavy DOCX, image-heavy
PPTX (dual-route alongside T2). Delegates to the existing `src/stage1_fast/`
pipeline which:

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

## Pool-factor policy (see Plans/backlog_20Apr26.md §G4)

Patch pooling is OFF by default — financial / discriminator-heavy content
(receipts, bank statements, contracts) loses recall when patches are pooled
together (the Clavié et al. 2024 FIQA finding). We enable pooling *only*
for content classes where the argument doesn't apply: currently **`.pptx`
(educational lecture decks)**. Queries against those decks are semantic-shaped
("which slide explains sonata form"), not discriminator-shaped ("the exact
transaction amount"), so halving patch count at ~100% recall retention is
effectively free.

The whitelist is intentionally narrow. To expand: pick a content class,
measure recall on it before/after pooling, only then add to
`POOL_SAFE_EXTS`.
"""

from __future__ import annotations

from pathlib import Path

from src.ingest.common import TierOutcome
from src.manifest import Manifest

# Extensions where patch pooling is measured-safe. Start narrow.
POOL_SAFE_EXTS = {".pptx"}
POOL_FACTOR = 2


def _pool_factor_for(path: Path) -> int:
    """Return the pool_factor to apply for this file. Defaults to 1 (no pool)."""
    if path.suffix.lower() in POOL_SAFE_EXTS:
        return POOL_FACTOR
    return 1


def run(
    path: Path,
    source_rel: str,
    manifest: Manifest,
    *,
    force: bool = False,
) -> TierOutcome:
    """Run the ColPali pipeline for a single file. Returns an outcome whose
    `summary_file_rel` is None — the T4 artifacts live in Qdrant, not on disk.

    `force=True` re-encodes even if the manifest says the file's size is
    unchanged. Necessary so the walker's `--force` / `--rebuild` modes
    actually refresh existing fast_tier points after a policy change.
    """
    # Local import keeps the rest of the walker snappy — pulls in torch+colpali.
    from src.stage1_fast.index import index_file
    from src.stage2.fast_db import ensure_fast_collection

    ensure_fast_collection()
    pool_factor = _pool_factor_for(path)
    pages, _was_skipped = index_file(
        path, manifest, pool_factor=pool_factor, force=force
    )
    return TierOutcome(summary_file_rel=None, body_chars=pages)
