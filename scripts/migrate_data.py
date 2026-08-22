"""One-shot migration: move repo-rooted data to the portable APP_DATA_DIR.

Run this ONCE after upgrading past v0.1.0-cli. Idempotent: safe to re-run —
detects already-migrated state and exits cleanly.

What it migrates
----------------
  <repo>/Test Summaries/_manifest.json    → <APP_DATA_DIR>/manifest.json
  <repo>/Test Summaries/*.md              → <APP_DATA_DIR>/summaries/*.md

What it does NOT touch
----------------------
  - <repo>/Test Content/                  (stays — these are test fixtures, not user data)
  - <repo>/Test Questions/                (stays — eval fixtures)
  - <repo>/qdrant_data/                   (stays for now; see TODO at bottom)

Usage:
  uv run python scripts/migrate_data.py            # dry-run (default)
  uv run python scripts/migrate_data.py --apply    # actually move files
  MAGPIE_DATA_DIR=/tmp/magpie-test uv run python scripts/migrate_data.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from src.manifest import APP_DATA_DIR, DEFAULT_MANIFEST_PATH, SUMMARIES_DIR

REPO_ROOT_LEGACY = Path(__file__).resolve().parent.parent
LEGACY_SUMMARIES_DIR = REPO_ROOT_LEGACY / "Test Summaries"
LEGACY_MANIFEST_PATH = LEGACY_SUMMARIES_DIR / "_manifest.json"


def migrate(apply: bool) -> int:
    if not LEGACY_SUMMARIES_DIR.is_dir():
        print(f"no legacy data found at {LEGACY_SUMMARIES_DIR}; nothing to migrate")
        return 0

    if APP_DATA_DIR == REPO_ROOT_LEGACY:
        print(
            f"refusing to migrate: APP_DATA_DIR == legacy repo root ({APP_DATA_DIR}). "
            "Either set MAGPIE_DATA_DIR to a different path, or you've already migrated."
        )
        return 1

    md_files = list(LEGACY_SUMMARIES_DIR.glob("*.md"))
    has_manifest = LEGACY_MANIFEST_PATH.exists()

    if not md_files and not has_manifest:
        print(f"{LEGACY_SUMMARIES_DIR} exists but is empty; nothing to migrate")
        return 0

    print(f"legacy data:  {LEGACY_SUMMARIES_DIR}")
    print(f"  - manifest: {'yes' if has_manifest else 'no'}")
    print(f"  - summaries: {len(md_files)} .md file(s)")
    print()
    print(f"target:       {APP_DATA_DIR}")
    print(f"  - manifest -> {DEFAULT_MANIFEST_PATH}")
    print(f"  - summaries -> {SUMMARIES_DIR}")
    print()

    # Refuse to overwrite a non-empty target — would conflate two corpora.
    target_existing_md = list(SUMMARIES_DIR.glob("*.md")) if SUMMARIES_DIR.is_dir() else []
    if target_existing_md or DEFAULT_MANIFEST_PATH.exists():
        print(
            f"refusing to migrate: target already has data "
            f"({len(target_existing_md)} .md, manifest={DEFAULT_MANIFEST_PATH.exists()}). "
            "Move or delete it first if you really want to overwrite."
        )
        return 1

    if not apply:
        print("DRY RUN — no files moved. Re-run with --apply to migrate.")
        return 0

    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

    moved_md = 0
    for md in md_files:
        target = SUMMARIES_DIR / md.name
        shutil.move(str(md), str(target))
        moved_md += 1

    manifest_moved = False
    if has_manifest:
        # Validate JSON before moving so we don't ship a corrupt file.
        try:
            json.loads(LEGACY_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"warning: legacy manifest unreadable ({e}); skipping manifest move")
        else:
            shutil.move(str(LEGACY_MANIFEST_PATH), str(DEFAULT_MANIFEST_PATH))
            manifest_moved = True

    print()
    print(f"done: {moved_md} summary file(s) moved, "
          f"manifest {'moved' if manifest_moved else 'skipped'}")

    # Clean up the now-empty legacy dir if nothing else lives in it.
    try:
        if not any(LEGACY_SUMMARIES_DIR.iterdir()):
            LEGACY_SUMMARIES_DIR.rmdir()
            print(f"removed empty {LEGACY_SUMMARIES_DIR}")
    except OSError:
        pass

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually move files (default: dry-run, just prints what would happen)",
    )
    args = parser.parse_args()
    return migrate(apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
