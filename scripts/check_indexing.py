"""Dry-run the indexing rules against a path. Two modes:

  python -m scripts.check_indexing FILE     → check one file/folder, print decision + reason
  python -m scripts.check_indexing DIR --recursive  → walk the dir, print every file's decision

Powered by `IndexingRules.should_index()`. Exits 0 in both modes — this is
a diagnostic, not a gating tool.

Used by `just check` and `just check-dir` recipes. See
`Plans/Ingestion Rules/Implementation Plan.md` §4 for the precedence chain.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from src.config import load_indexing_rules


def _fmt(ok: bool, reason: str, path: str) -> str:
    marker = "✓ INDEX" if ok else "✗ SKIP "
    return f"{marker}  {path:<60s}  {reason}"


def check_one(path: Path) -> int:
    rules = load_indexing_rules()
    p = path.expanduser().resolve()
    if not p.exists():
        print(f"warning: {p} does not exist on disk", file=sys.stderr)
    ok, reason = rules.should_index(p)
    print(_fmt(ok, reason, str(p)))
    return 0


def check_dir(root: Path) -> int:
    rules = load_indexing_rules()
    root = root.expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1

    print(f"== checking files under {root} ==\n")
    indexed = 0
    skipped = 0
    pruned_dirs = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Apply the same dir-prune the real walker uses, so the output
        # matches what `just walk` would actually do.
        keep = []
        for d in dirnames:
            if rules.is_pruneable_dir(Path(dirpath) / d):
                pruned_dirs += 1
            else:
                keep.append(d)
        dirnames[:] = keep

        for fname in filenames:
            p = Path(dirpath) / fname
            ok, reason = rules.should_index(p)
            try:
                rel = str(p.relative_to(root))
            except ValueError:
                rel = str(p)
            print(_fmt(ok, reason, rel))
            if ok:
                indexed += 1
            else:
                skipped += 1

    print(
        f"\n== summary: {indexed} would be indexed, "
        f"{skipped} files skipped, {pruned_dirs} dirs pruned =="
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Dry-run the indexing rules against a file or directory."
    )
    p.add_argument("path", help="File or directory to check.")
    p.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="If path is a directory, recursively check every file inside.",
    )
    args = p.parse_args()

    target = Path(args.path)
    if args.recursive or (target.is_dir() and not target.is_file()):
        return check_dir(target)
    return check_one(target)


if __name__ == "__main__":
    sys.exit(main())
