"""CLI entrypoint: python -m src.stage2 <command>.

`ingest` walks the manifest (not the Test Summaries/ directory) and upserts
only rows where `ingested_at` is absent — i.e. new summaries plus any that
Stage 1 re-summarized (which clears ingested_at). After upserting, orphan
Qdrant points (IDs not in the manifest) are hard-deleted.

`--force` drops the collection, clears all `ingested_at` values in the
manifest, then ingests from scratch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


def ingest_from_manifest(*, force: bool = False) -> dict:
    """Run the manifest-driven incremental ingest. Prints progress.

    Returns a small stats dict: {"upserted", "orphans_deleted", "total_points"}.
    Callable from the CLI (via cmd_ingest) and from `src.pipeline`.
    """
    from src.manifest import REPO_ROOT, Manifest
    from src.stage2.db import (
        _point_id,
        create_collection,
        delete_points,
        get_all_point_ids,
        upsert_summaries,
    )
    from src.stage2.parser import parse_summary_file

    manifest = Manifest()
    if not manifest.entries:
        raise RuntimeError(
            "manifest is empty — run `python -m src.stage1.summarize \"Test Content\"` first."
        )

    if force:
        create_collection(recreate=True)
        for entry in manifest.entries.values():
            entry.ingested_at = None
        manifest.save()
    else:
        create_collection(recreate=False)

    todo_paths = [p for p in manifest.paths() if manifest.needs_ingestion(p)]

    upserted = 0
    if todo_paths:
        parsed = []
        for rel in todo_paths:
            entry = manifest.get(rel)
            assert entry is not None
            summary_path = REPO_ROOT / entry.summary_file
            if not summary_path.exists():
                print(f"  warn: summary missing, skipping: {entry.summary_file}", file=sys.stderr)
                continue
            parsed.append(parse_summary_file(summary_path))

        upserted = upsert_summaries(parsed)
        ingested_paths = {p.source_path for p in parsed}
        for rel in todo_paths:
            if rel in ingested_paths:
                manifest.mark_ingested(rel)
        manifest.save()
        print(f"upserted {upserted} points into Qdrant")
    else:
        print("manifest says nothing needs ingestion.")

    # Orphan cleanup: points in Qdrant whose source is no longer in the manifest.
    expected_ids = {_point_id(rel) for rel in manifest.paths()}
    actual_ids = get_all_point_ids()
    orphans = actual_ids - expected_ids
    orphans_deleted = 0
    if orphans:
        orphans_deleted = delete_points(list(orphans))
        print(f"deleted {orphans_deleted} orphan points from Qdrant")

    return {
        "upserted": upserted,
        "orphans_deleted": orphans_deleted,
        "total_points": len(manifest.entries),
    }


def cmd_ingest(args: argparse.Namespace) -> None:
    try:
        ingest_from_manifest(force=args.force)
    except RuntimeError as e:
        sys.exit(str(e))


def cmd_search(args: argparse.Namespace) -> None:
    """Rewrite question via Kimi (optional), then hybrid search Qdrant."""
    from src.stage2.search import search_summaries

    results = search_summaries(args.question, top_k=args.top_k, rewrite=args.rewrite)

    if not results:
        print("no results found.")
        return

    for i, r in enumerate(results, 1):
        print(f"\n--- Result {i} (score: {r.score:.4f}) ---")
        print(f"Path:    {r.path}")
        print(f"Summary: {r.summary}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="notanotherspotlight",
        description="RAG-style semantic search over local documents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- ingest ---
    ingest_p = sub.add_parser(
        "ingest",
        help="Incrementally ingest new/changed summaries into Qdrant (manifest-driven).",
    )
    ingest_p.add_argument(
        "--force",
        action="store_true",
        help="Drop + recreate the collection, clear ingested_at, then ingest everything.",
    )

    # --- search ---
    search_p = sub.add_parser("search", help="Search documents by question.")
    search_p.add_argument("question", help="Natural language question to search for.")
    search_p.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to return (default: 5).",
    )
    search_p.add_argument(
        "--rewrite",
        action="store_true",
        help="Enable Kimi query rewriting (off by default — adds ~20s per call).",
    )

    args = parser.parse_args()

    if args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "search":
        cmd_search(args)


if __name__ == "__main__":
    main()
