"""Stage 3 indexer: walk `.alt` files and register them in the Stage 2 pipeline.

For each `.alt` we discover:
    1. Parse it -> AltDocument (via `src.stage3.alt.parse_alt_file`)
    2. Transcode -> N+1 EmittedSummary blobs (file-level + per-scene)
    3. Write each blob to `Test Summaries/<digest>_<kind>.md`
    4. Mark each manifest key (`<alt rel>` and `<alt rel>#scene:<tc>`) as
       summarized. Stage 2's existing ingest picks them up on the next run.

Change detection uses the `.alt` file's byte size. If the `.alt` hasn't
changed since last run, all its emitted summaries are skipped. When the
`.alt` changes, every scene entry is re-marked so Stage 2 re-ingests the
whole set atomically.

`.alt` files found anywhere under the scanned root are indexed — they don't
have to live in `Test Videos/`. Missing `.alt` files (relative to the
manifest) are hard-deleted on the next scan of the same root.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.manifest import REPO_ROOT, Manifest
from src.stage3.alt import AltParseError, parse_alt_file
from src.stage3.transcode import EmittedSummary, transcode

SUMMARIES_DIR = REPO_ROOT / "Test Summaries"
HASH_CHUNK = 1 << 20


def _alt_source_rel(path: Path) -> str:
    """Repo-relative path if under the repo, otherwise absolute.

    Matches `src.stage1.summarize.source_rel_path` — kept here to avoid a
    cross-stage import.
    """
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def _alt_digest(path: Path) -> str:
    """Short content-addressed digest for filename uniqueness."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _summary_filename(digest: str, kind: str) -> str:
    return f"{digest}_{kind}.md"


def _delete_if_exists(rel: str | None) -> None:
    if rel is None:
        return
    p = REPO_ROOT / rel
    if p.exists():
        p.unlink()


def find_alt_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.alt")
        if p.is_file() and not p.name.startswith(".")
    )


def index_single_alt(
    alt_path: Path,
    manifest: Manifest,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Transcode one `.alt` into summary markdowns and register manifest rows.

    Returns a stats dict: {"emitted", "skipped"}.
    """
    SUMMARIES_DIR.mkdir(exist_ok=True)

    size = alt_path.stat().st_size
    alt_rel = _alt_source_rel(alt_path)

    # If the .alt itself hasn't changed size, every emitted summary already
    # in the manifest can be skipped. Scene-level keys share the parent
    # .alt's size (they're slices of the same file).
    if not force:
        parent = manifest.get(alt_rel)
        if parent is not None and parent.size == size:
            return {"emitted": 0, "skipped": 1}

    try:
        alt_doc = parse_alt_file(alt_path)
    except AltParseError as e:
        print(f"  skip: {e}", file=sys.stderr)
        return {"emitted": 0, "skipped": 0}

    emitted: list[EmittedSummary] = transcode(alt_doc, alt_rel)
    digest = _alt_digest(alt_path)

    # Write summaries and (re-)register. If this .alt was previously indexed,
    # wipe its old summary files first so we don't leave stale scene markdowns
    # when scene count drops.
    existing_keys = [
        k for k in manifest.paths()
        if k == alt_rel or k.startswith(alt_rel + "#scene:")
    ]
    for k in existing_keys:
        old = manifest.get(k)
        if old is not None:
            _delete_if_exists(old.summary_file)
        manifest.drop(k)

    for e in emitted:
        out_path = SUMMARIES_DIR / _summary_filename(digest, e.kind)
        out_path.write_text(e.summary_md, encoding="utf-8")
        try:
            rel = str(out_path.relative_to(REPO_ROOT))
        except ValueError:
            rel = str(out_path.resolve())
        manifest.mark_summarized(e.manifest_key, size, rel)

    return {"emitted": len(emitted), "skipped": 0}


def run_batch(root: Path, *, force: bool = False) -> None:
    manifest = Manifest()
    alts = find_alt_files(root)
    if not alts:
        print(f"no .alt files found under {root}")
        return

    # Prune manifest rows for .alt sources under this root that no longer exist.
    try:
        root_rel = _alt_source_rel(root) + os.sep
    except ValueError:
        root_rel = None
    existing_rels = {_alt_source_rel(p) for p in alts}
    pruned = 0
    if root_rel is not None:
        for rel in list(manifest.paths()):
            # A manifest key like 'a.alt#scene:00:20' should match its parent
            # when we check 'a.alt' against existing_rels.
            parent_rel = rel.split("#", 1)[0]
            if parent_rel.startswith(root_rel) and parent_rel not in existing_rels:
                entry = manifest.drop(rel)
                if entry:
                    _delete_if_exists(entry.summary_file)
                    pruned += 1

    total_emitted = 0
    total_skipped = 0
    for alt in alts:
        stats = index_single_alt(alt, manifest, force=force)
        total_emitted += stats["emitted"]
        total_skipped += stats["skipped"]
        if stats["emitted"]:
            print(f"  indexed: {alt.name} ({stats['emitted']} summaries)")

    manifest.save()
    print(
        f"\ndone: {total_emitted} summaries written, "
        f"{total_skipped} .alt files unchanged, {pruned} pruned"
    )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=(
            "Stage 3: walk a directory, find `.alt` sidecar files, and register "
            "them (plus per-scene entries) in the Stage 2 manifest. "
            "Run `python -m src.stage2 ingest` afterward to push them into Qdrant."
        ),
    )
    parser.add_argument("path", help="Directory to scan for .alt files.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-index every .alt, even if its size hasn't changed.",
    )
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        sys.exit(f"error: no such path: {root}")
    if root.is_file():
        if root.suffix.lower() != ".alt":
            sys.exit(f"error: not a .alt file: {root}")
        manifest = Manifest()
        stats = index_single_alt(root, manifest, force=args.force)
        manifest.save()
        if stats["emitted"]:
            print(f"indexed: {root.name} ({stats['emitted']} summaries)")
        else:
            print(f"unchanged: {root.name}")
        return
    run_batch(root, force=args.force)


if __name__ == "__main__":
    main()
