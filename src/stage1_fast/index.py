"""Stage 1-fast batch indexer: render, encode, upsert pages to `fast_tier`.

Walks a directory, routes each file via `router.route_file`, and for every
`fast` file:

    1. Renders PDF pages via pymupdf (or loads the image for PNG/JPG)
    2. Batches pages through the ColPali model (batch size from DeviceConfig)
    3. Upserts each page as a multi-vector point in Qdrant `fast_tier`
    4. Updates the manifest's `fast_indexed_at` / `fast_pages` fields

Change detection is by byte size, matching the stage 1 summarize pipeline.
Files whose size matches the manifest are skipped without re-rendering.

Deletions: any file previously in fast_tier that no longer exists on disk
has its pages removed from Qdrant and its fast_* fields cleared from the
manifest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from src.manifest import Manifest, REPO_ROOT
from src.stage1_fast.router import FAST_IMAGE_EXTS, route_file

PDF_RENDER_DPI = 150  # balance between quality and speed; ColPali trained ~150


def _iter_fast_files(root: Path) -> list[Path]:
    """Walk `root` and return sorted list of files the router tagged `fast`.

    Shares `src.ingest.walker.find_candidates` with the summary tier so both
    tiers see the same corpus: the user's `indexing_rules.json` is honored,
    dot-folders are pruned during traversal, and a directory that cannot be
    read is skipped instead of aborting the run.
    """
    from src.ingest.walker import find_candidates

    files, _ignored, _asset_skipped = find_candidates(root)
    return sorted(p for p in files if route_file(p) == "fast")


def _render_pages(path: Path) -> list:
    """Render all pages of a PDF, or return [image] for a single image file."""
    from PIL import Image
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        import pymupdf
        doc = pymupdf.open(path)
        images: list[Image.Image] = []
        try:
            for i in range(len(doc)):
                pix = doc[i].get_pixmap(dpi=PDF_RENDER_DPI)
                images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        finally:
            doc.close()
        return images

    if suffix in FAST_IMAGE_EXTS:
        return [Image.open(path).convert("RGB")]

    raise ValueError(f"unsupported file for fast tier: {path}")


def _source_rel(path: Path) -> str:
    """Repo-relative path if possible, else the absolute path (outside-repo content)."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def _batched(xs: list, size: int) -> Iterable[list]:
    for i in range(0, len(xs), size):
        yield xs[i : i + size]


def index_file(
    path: Path,
    manifest: Manifest,
    *,
    pool_factor: int = 1,
    force: bool = False,
) -> tuple[int, bool]:
    """Index one file into fast_tier. Returns (pages_upserted, was_skipped).

    Raises on any hard failure (the caller decides whether to continue the batch).

    `pool_factor` enables HierarchicalTokenPooler over the encoded multi-vectors
    before upsert. `pool_factor=1` (default) skips pooling entirely — critical
    for financial / discriminator-heavy content where patch-level fidelity is
    the whole point. `pool_factor=2` halves patch count per page at ~100% recall
    retention for general-content (see Clavié et al. 2024). The router decides
    when pooling is safe; this function trusts it.

    `force=True` re-encodes regardless of whether the manifest says the file's
    size is unchanged. Used by the walker's `--force` and `--rebuild` modes so
    a policy change (e.g. pool_factor flip, asset-library rule) actually
    rewrites the existing fast_tier points instead of leaving zombies.
    """
    from src.stage1_fast.model import encode_images, get_model
    from src.stage2.fast_db import upsert_pages_batch

    rel = _source_rel(path)
    size = path.stat().st_size

    if not force and not manifest.needs_fast_indexing(rel, size):
        return 0, True

    images = _render_pages(path)
    if not images:
        return 0, True

    pooler = None
    if pool_factor > 1:
        from colpali_engine.compression.token_pooling import HierarchicalTokenPooler
        pooler = HierarchicalTokenPooler()

    _, _, cfg = get_model()
    pages_to_upsert: list[tuple[str, int, list]] = []
    page_idx = 0

    for batch in _batched(images, cfg.batch_size):
        tensor = encode_images(batch)          # (B, n_patches, 128)
        if pooler is not None:
            # Pools the token dim from n_patches down to ~n_patches/pool_factor.
            tensor = pooler.pool_embeddings(tensor, pool_factor=pool_factor)
        # Move off-GPU, upcast to float so Qdrant receives plain Python floats.
        cpu_batch = tensor.float().cpu().tolist()
        for page_vectors in cpu_batch:
            pages_to_upsert.append((rel, page_idx, page_vectors))
            page_idx += 1

    # One upsert call per file; small + amortizes network cost vs per-page.
    upsert_pages_batch(pages_to_upsert)

    manifest.mark_fast_indexed(rel, size=size, pages=len(images))
    return len(images), False


def run_fast_batch(root: Path) -> None:
    """Walk `root`, index every fast-tier file, prune deleted ones."""
    from tqdm import tqdm

    from src.stage2.fast_db import delete_path, ensure_fast_collection

    ensure_fast_collection()
    manifest = Manifest()
    files = _iter_fast_files(root)
    if not files:
        print(f"no fast-tier files found under {root}")
        return

    # Prune manifest rows whose source files vanished from disk, within scope.
    try:
        root_rel = str(root.resolve().relative_to(REPO_ROOT))
    except ValueError:
        root_rel = str(root.resolve())
    existing_rels = {_source_rel(p) for p in files}
    pruned = 0
    for rel, entry in list(manifest.entries.items()):
        if entry.fast_indexed_at is None:
            continue
        if not rel.startswith(root_rel):
            continue
        if rel in existing_rels:
            continue
        delete_path(rel)
        entry.fast_indexed_at = None
        entry.fast_pages = None
        pruned += 1

    indexed = skipped = 0
    errors: list[tuple[Path, str]] = []
    total_pages = 0

    # Eager-load the model once before the bar starts, so the 5-10s cold
    # load doesn't look like "stuck on first file."
    print("loading fast-tier model...")
    from src.stage1_fast.model import get_model
    get_model()

    bar = tqdm(total=len(files), desc="fast-indexing", unit="file")
    for p in files:
        try:
            bar.set_postfix_str(p.name[:40])
            pages, was_skipped = index_file(p, manifest)
        except Exception as e:  # pylint: disable=broad-except
            errors.append((p, f"{type(e).__name__}: {e}"))
            tqdm.write(f"  error on {p.name}: {type(e).__name__}: {e}")
        else:
            if was_skipped:
                skipped += 1
            else:
                indexed += 1
                total_pages += pages
        finally:
            bar.update(1)
    bar.close()

    manifest.save()

    print(
        f"\nfast tier: {indexed} files indexed "
        f"({total_pages} pages), {skipped} unchanged, "
        f"{pruned} pruned, {len(errors)} errors"
    )
    if errors:
        print("errors:")
        for p, msg in errors:
            print(f"  - {_source_rel(p)}: {msg}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Index a directory into the fast tier.")
    parser.add_argument("path", help="Directory to walk.")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.is_dir():
        sys.exit(f"error: not a directory: {root}")

    from dotenv import load_dotenv
    load_dotenv()

    run_fast_batch(root)


if __name__ == "__main__":
    main()
