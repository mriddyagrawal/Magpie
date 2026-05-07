"""CLI entrypoint: python -m src.stage2 <command>.

`ingest` walks the manifest (not the Test Summaries/ directory) and upserts
only rows where `ingested_at` is absent — i.e. new summaries the router
just wrote (or rows the router re-summarized, which clears ingested_at).
After upserting, orphan Qdrant points (IDs not in the manifest) are
hard-deleted.

This module never opens source files. The router (`src.router` →
`src.ingest.walker`) is the single sanctioned entry point: it inspects each
file, picks a tier, and writes a summary markdown. Stage 2 only embeds
those markdowns. If a manifest row reaches stage 2 without a `summary_file`
and isn't fast-tier-only, that's a bug in upstream routing — we raise
loudly instead of silently falling back to a per-row CSV embedder (which
this module used to do, and which could spend hours on a 100k-row CSV).

`--force` drops the collection, clears all `ingested_at` values in the
manifest, then ingests from scratch.
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv


def _expected_point_ids(manifest) -> set[str]:
    """Compute every Qdrant point ID we expect to find in the `summaries`
    collection, given the current manifest.

    Different tiers write different shapes:
      - Regular T0-T3 (one summary markdown per file): a single file-level
        point at `_point_id(rel)`.
      - T1 CSVs: BOTH N row-level points at `_row_point_id(rel, i)` for
        i in 0..row_count-1 AND a single file-level summary point at
        `_point_id(rel)` (since the 2026-05 follow-up). Only the
        file-level point exists when `summary_file` is set; if for some
        reason the summary failed to write but rows did, only rows are
        expected.
      - Other chunked types (T0/T2 CSVs without a summary, etc.): file-
        level only, like regular T0-T3.

    Future chunked formats (PDF sections, audio segments, long-doc windows)
    plug in here — add a count field to the Entry, write the chunk-id helper
    in its tier module, then add another branch below. The orphan cleanup is
    the one place that needs to know the full set.
    """
    from src.stage2.csv_ingest import _row_point_id
    from src.stage2.db import _point_id

    expected: set[str] = set()
    for rel in manifest.paths():
        entry = manifest.get(rel)
        if entry is None:
            continue
        if entry.row_count and entry.row_count > 0:
            expected.update(_row_point_id(rel, i) for i in range(entry.row_count))
            # T1 CSVs ALSO have a file-level summary point alongside the
            # row points (Plan #17 follow-up). Only expect it when the
            # entry actually has a summary_file pointer — otherwise the
            # row-level ingest happened standalone (legacy / pre-#17
            # data, or a summary-write failure).
            if entry.summary_file:
                expected.add(_point_id(rel))
        else:
            expected.add(_point_id(rel))
    return expected


def ingest_from_manifest(
    *, force: bool = False, skip_orphan_cleanup: bool = False, verbose: bool = False,
) -> dict:
    """Run the manifest-driven incremental ingest. Prints progress.

    Returns a small stats dict: {"upserted", "orphans_deleted", "total_points"}.
    Callable from the CLI (via cmd_ingest) and from `src.pipeline`.

    `skip_orphan_cleanup=True` is for **intermediate** flushes from the walker
    (every N files mid-walk). Orphan cleanup scrolls the entire collection,
    which is wasteful to do per-chunk; the walker's end-of-run flush re-calls
    this function with the default (cleanup on) to do the sweep once.
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
            "manifest is empty — run `python -m src.ingest <path>` first."
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
        # Single contract: every todo row is one of three things —
        #   (a) router-skipped         → mark ingested, no Qdrant work
        #   (b) fast-tier-only         → lives in fast_tier collection, skip here
        #   (c) has a summary markdown → embed + upsert into the summary collection
        # Anything else means upstream routing is broken; we raise instead of
        # silently invoking a per-row fallback (the old `upsert_csv_rows` path
        # lived in this branch and could spend 13+ hours on a single CSV).
        regular_paths: list[str] = []
        csv_row_paths: list[str] = []
        skip_only_rels: list[str] = []
        pending_resummarize: list[str] = []
        for rel in todo_paths:
            entry = manifest.get(rel)
            assert entry is not None

            if entry.skip_reason is not None:
                skip_only_rels.append(rel)
                continue

            # T1 CSVs get TWO Qdrant representations (Plan #17 follow-up,
            # 2026-05): row-level points (one per row, for "which row
            # matches the question") AND a file-level summary point
            # embedded from the LLM-generated summary markdown (so
            # "what is this CSV?" semantic queries can find the file by
            # its identity, not just its rows). The two have distinct
            # point IDs (`_row_point_id(rel, i)` vs `_point_id(rel)`)
            # so they don't collide. `_expected_point_ids` knows about
            # both shapes so orphan cleanup expects all of them.
            if rel.lower().endswith(".csv") and entry.routes and "T1" in entry.routes:
                csv_row_paths.append(rel)
                if entry.summary_file:
                    regular_paths.append(rel)
                continue

            if entry.summary_file is None:
                if entry.fast_indexed_at is not None:
                    # Fast-tier-only file — its vectors live in the fast_tier
                    # collection (handled by `src.stage1_fast.index`).
                    skip_only_rels.append(rel)
                    continue
                # Row is in "needs re-summarization" intermediate state —
                # produced by `just clean-stale-summaries` after the on-disk
                # markdown went missing. Skip it here; the walker
                # (`python -m src.ingest <root>`) will pick it up and
                # re-summarize. We log a single rollup at the end rather
                # than per-row spam — could be hundreds.
                pending_resummarize.append(rel)
                continue

            regular_paths.append(rel)

        if pending_resummarize:
            sample = ", ".join(pending_resummarize[:3])
            more = (
                f" (plus {len(pending_resummarize) - 3} more)"
                if len(pending_resummarize) > 3 else ""
            )
            print(
                f"  warn: {len(pending_resummarize)} manifest row(s) pending "
                f"re-summarization — these were cleared by "
                f"`just clean-stale-summaries` and need the walker to "
                f"re-summarize them. Run "
                f"`python -m src.ingest <your-corpus-root>` to fix.\n"
                f"        first few: {sample}{more}",
                file=sys.stderr,
            )

        if regular_paths or csv_row_paths:
            import time
            last_save_t = [time.monotonic()]
            SAVE_INTERVAL_S = 30.0

            def _on_batch_complete(batch_indices: list[int], rels: list[str]) -> None:
                for idx in batch_indices:
                    if idx < len(rels):
                        manifest.mark_ingested(rels[idx])
                if time.monotonic() - last_save_t[0] >= SAVE_INTERVAL_S:
                    manifest.save()
                    last_save_t[0] = time.monotonic()

            if regular_paths:
                parsed = []
                parsed_rels: list[str] = []
                for rel in regular_paths:
                    entry = manifest.get(rel)
                    assert entry is not None
                    summary_path = REPO_ROOT / entry.summary_file
                    if not summary_path.exists():
                        print(f"  warn: summary missing, skipping: {entry.summary_file}", file=sys.stderr)
                        continue
                    parsed.append(parse_summary_file(summary_path))
                    parsed_rels.append(rel)

                upserted += upsert_summaries(
                    parsed, 
                    on_batch_complete=lambda idxs: _on_batch_complete(idxs, parsed_rels), 
                    verbose=verbose,
                )

            if csv_row_paths:
                from src.stage2.csv_ingest import ingest_csv_rows
                for rel in csv_row_paths:
                    source_path = REPO_ROOT / rel
                    if verbose:
                        print(f"  indexing csv rows: {rel}")
                    rows_indexed = ingest_csv_rows(source_path, rel)
                    upserted += rows_indexed
                    # Record how many row-points we wrote so orphan cleanup
                    # knows to expect them. Without this, every row point
                    # gets deleted on the next sweep (1-point-per-file
                    # assumption, see _expected_point_ids_for below).
                    entry = manifest.get(rel)
                    if entry is not None:
                        entry.row_count = rows_indexed
                    manifest.mark_ingested(rel)
                    if time.monotonic() - last_save_t[0] >= SAVE_INTERVAL_S:
                        manifest.save()
                        last_save_t[0] = time.monotonic()

        for rel in skip_only_rels:
            manifest.mark_ingested(rel)

        manifest.save()
        print(f"upserted {upserted} points into Qdrant")
    else:
        print("manifest says nothing needs ingestion.")

    # Orphan cleanup: points in Qdrant whose source is no longer in the manifest.
    # Skipped during intermediate mid-walk flushes — the scroll over the whole
    # collection is wasteful per-chunk; the end-of-walk call does the sweep.
    orphans_deleted = 0
    if not skip_orphan_cleanup:
        expected_ids = _expected_point_ids(manifest)
        actual_ids = get_all_point_ids()
        orphans = actual_ids - expected_ids
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
        ingest_from_manifest(force=args.force, verbose=args.verbose)
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
    ingest_p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print each source path as its summary is upserted into Qdrant. "
             "Useful for debugging slow runs or confirming specific files made it in.",
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
