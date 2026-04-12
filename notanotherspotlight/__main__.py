"""CLI entrypoint: python -m notanotherspotlight <command>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


def cmd_ingest(args: argparse.Namespace) -> None:
    """Parse summaries, embed, and upsert into Qdrant."""
    from notanotherspotlight.db import create_collection, upsert_summaries
    from notanotherspotlight.parser import load_all_summaries

    summaries_dir = Path(args.summaries_dir)
    summaries = load_all_summaries(summaries_dir)
    if not summaries:
        sys.exit(f"no summary files found in {summaries_dir}")

    print(f"found {len(summaries)} summaries")

    create_collection(recreate=args.force)
    count = upsert_summaries(summaries)
    print(f"upserted {count} points into Qdrant")


def cmd_search(args: argparse.Namespace) -> None:
    """Rewrite question via Kimi, then hybrid search Qdrant."""
    from notanotherspotlight.search import search_summaries

    results = search_summaries(args.question, top_k=args.top_k)

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
    ingest_p = sub.add_parser("ingest", help="Embed and store summaries in Qdrant.")
    ingest_p.add_argument(
        "--summaries-dir",
        default="Summaries",
        help="Path to the summaries directory (default: Summaries).",
    )
    ingest_p.add_argument(
        "--force",
        action="store_true",
        help="Drop and recreate the collection before ingesting.",
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

    args = parser.parse_args()

    if args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "search":
        cmd_search(args)


if __name__ == "__main__":
    main()
