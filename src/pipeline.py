"""End-to-end question pipeline: retrieve -> answer.

Glues stage 2/3 (search) and stage 4 (answer) together:

    question -> Kimi query rewrite -> Qdrant hybrid search (top-k)
             -> read the top-k files -> Kimi answer with source citation
             -> PipelineResult

This is the module a user-facing app (CLI, web, etc.) should import. It hides
whether retrieval is top-k over chunks or whole files, whether the answerer
has agentic fetch-more capability, etc. — it's the one stable interface.

CLI:

    uv run python3 -m src.pipeline "your question here" [--top-k 5]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

from pathlib import Path

from src.answer import Answer, answer_question, build_answer_agent
from src.stage2.search import SearchQuery, SearchResult, raw_query, rewrite_query, run_search


@dataclass
class PipelineResult:
    """What the full pipeline returns for a single question."""

    question: str
    search_query: SearchQuery          # Kimi's rewritten dense/BM25 query
    retrieved: list[SearchResult]       # Qdrant top-k (path, summary, score)
    answer: str                         # Kimi's final answer
    sources_used: list[str]             # Subset of retrieved paths Kimi cited


async def ask(question: str, *, top_k: int = 5, rewrite: bool = False) -> PipelineResult:
    """Run the full retrieve -> answer pipeline for one question.

    1. **Query construction.** If `rewrite=True`, Kimi expands the question
       into a keyword-rich `SearchQuery` (~20s LLM round-trip). If False
       (default), we skip the rewrite and send the raw question to the
       embedders — faster, and usually fine for question sets that already
       contain good entity names / document terms.
    2. `run_search(sq, top_k)` — Qdrant hybrid search (dense + BM25 via RRF)
       over the summary index.
    3. `answer_question(agent, question, paths)` — read the retrieved files,
       send them with the question to Kimi, get a grounded answer + citations.

    `PipelineResult.search_query` always carries the query we actually sent
    to the embedders (rewritten or raw), so eval and debugging see the truth.
    """
    if rewrite:
        sq: SearchQuery = await asyncio.to_thread(rewrite_query, question)
    else:
        sq = raw_query(question)
    retrieved = await asyncio.to_thread(run_search, sq, top_k)
    if not retrieved:
        return PipelineResult(
            question=question,
            search_query=sq,
            retrieved=[],
            answer="No matching documents found in the index.",
            sources_used=[],
        )

    agent = build_answer_agent()
    paths = list(dict.fromkeys(r.path for r in retrieved if r.path))
    ans: Answer = await answer_question(agent, question, paths)

    return PipelineResult(
        question=question,
        search_query=sq,
        retrieved=retrieved,
        answer=ans.answer,
        sources_used=ans.sources_used,
    )


def ask_sync(question: str, *, top_k: int = 5, rewrite: bool = False) -> PipelineResult:
    return asyncio.run(ask(question, top_k=top_k, rewrite=rewrite))


DEFAULT_SOURCE_DIR = "Test Content"


async def sync_files(
    source_dir: Path | str | None = None,
    *,
    concurrency: int = 1,
    force_summarize: bool = False,
    force_ingest: bool = False,
    do_fast: bool = True,
    do_summary: bool = True,
) -> None:
    """Bring the manifest, summaries, and both Qdrant collections in sync.

    Two-tier pipeline (see `Plans/IO - Colpali.md`):

    1. **Fast tier** (if `do_fast`): ColPali multi-vectors for PDFs ≤50 pages
       and images. GPU-bound, no LLM cost.
    2. **Summary tier** (if `do_summary`): LLM summaries for everything else
       (PDFs >50p, .docx, .xlsx, .csv, code, markdown). When both tiers run
       in the same call, the summary tier auto-skips files already covered
       by the fast tier.

    Prints per-tier wall-clock timing at the end so you can compare ColPali
    vs. LLM-summarize throughput side by side.
    """
    import time

    from src.manifest import REPO_ROOT

    if source_dir is None:
        source_dir = DEFAULT_SOURCE_DIR
    source_dir = Path(source_dir)
    if not source_dir.is_absolute():
        source_dir = REPO_ROOT / source_dir
    if not source_dir.is_dir():
        raise ValueError(f"not a directory: {source_dir}")

    timings: dict[str, float] = {}

    if do_fast:
        from src.stage1_fast.index import run_fast_batch
        print("\n━━━ Fast tier (ColPali) ━━━")
        t0 = time.monotonic()
        await asyncio.to_thread(run_fast_batch, source_dir)
        timings["fast (ColPali)"] = time.monotonic() - t0

    if do_summary:
        from src.stage1.summarize import (
            build_agent as build_summarize_agent,
            run_batch,
        )
        from src.stage2.__main__ import ingest_from_manifest

        print("\n━━━ Summary tier (LLM) ━━━")
        t0 = time.monotonic()
        summ_agent = build_summarize_agent()
        # The router is the source of truth: a file is fast-tier OR summary-tier.
        # Summary tier should never process fast-tier-routed files, regardless
        # of whether we're also running the fast batch in this same sync call.
        await run_batch(
            summ_agent,
            source_dir,
            force=force_summarize,
            concurrency=concurrency,
            skip_fast_tier=True,
        )
        timings["summary LLM summarize"] = time.monotonic() - t0

        print("\n━━━ Summary tier (Qdrant ingest) ━━━")
        t0 = time.monotonic()
        await asyncio.to_thread(ingest_from_manifest, force=force_ingest)
        timings["summary Qdrant ingest"] = time.monotonic() - t0

    if timings:
        print("\n━━━ Tier timings ━━━")
        width = max(len(k) for k in timings)
        total = 0.0
        for tier, elapsed in timings.items():
            mins, secs = divmod(elapsed, 60)
            print(f"  {tier.ljust(width)} : {int(mins):>3}m {secs:04.1f}s")
            total += elapsed
        if len(timings) > 1:
            mins, secs = divmod(total, 60)
            print(f"  {'total'.ljust(width)} : {int(mins):>3}m {secs:04.1f}s")


def sync_files_sync(
    source_dir: Path | str | None = None,
    *,
    concurrency: int = 1,
    force_summarize: bool = False,
    force_ingest: bool = False,
    do_fast: bool = True,
    do_summary: bool = True,
) -> None:
    asyncio.run(sync_files(
        source_dir,
        concurrency=concurrency,
        force_summarize=force_summarize,
        force_ingest=force_ingest,
        do_fast=do_fast,
        do_summary=do_summary,
    ))


def reset() -> dict:
    """Factory reset: remove all summaries, the manifest, and the Qdrant collection.

    Destructive. No confirmation prompt — the caller (e.g. the CLI layer) is
    responsible for asking the user first. Returns a stats dict with counts
    of what was removed so callers can log or display.

    Filesystem cleanup happens first; Qdrant failures are logged but don't
    abort the local cleanup (so a reset still works offline or when the
    cluster is unreachable).
    """
    from src.manifest import DEFAULT_MANIFEST_PATH, REPO_ROOT
    from src.stage2.db import COLLECTION_NAME, get_qdrant_client

    summaries_dir = REPO_ROOT / "Test Summaries"

    # Delete every summary .md file (keep the directory itself).
    deleted_summaries = 0
    if summaries_dir.is_dir():
        for md in summaries_dir.glob("*.md"):
            md.unlink()
            deleted_summaries += 1

    # Remove the manifest + any leftover .tmp from an interrupted save.
    manifest_removed = False
    if DEFAULT_MANIFEST_PATH.exists():
        DEFAULT_MANIFEST_PATH.unlink()
        manifest_removed = True
    tmp = DEFAULT_MANIFEST_PATH.with_suffix(DEFAULT_MANIFEST_PATH.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    # Drop the Qdrant collection. Don't fail the reset if Qdrant is down.
    collection_dropped = False
    qdrant_error: str | None = None
    try:
        client = get_qdrant_client()
        if client.collection_exists(COLLECTION_NAME):
            client.delete_collection(COLLECTION_NAME)
            collection_dropped = True
    except Exception as e:
        qdrant_error = f"{type(e).__name__}: {e}"

    return {
        "summaries_deleted": deleted_summaries,
        "manifest_removed": manifest_removed,
        "collection_dropped": collection_dropped,
        "qdrant_error": qdrant_error,
    }


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Ask a natural-language question; retrieve top-k files and answer (stages 3 + 4)."
    )
    parser.add_argument("question", help="The natural-language question.")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Number of files to retrieve from Qdrant (default: 5).")
    parser.add_argument("--rewrite", action="store_true",
                        help="Enable Kimi query rewriting (off by default — adds ~20s per call).")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of human-readable output.")
    args = parser.parse_args()

    result = ask_sync(args.question, top_k=args.top_k, rewrite=args.rewrite)

    if args.json:
        print(json.dumps({
            "question": result.question,
            "answer": result.answer,
            "sources_used": result.sources_used,
            "retrieved": [
                {"path": r.path, "score": r.score, "summary": r.summary}
                for r in result.retrieved
            ],
        }, indent=2, ensure_ascii=False))
        return

    print(f"Question: {result.question}\n")
    print("Retrieved (top-k from Qdrant):")
    for i, r in enumerate(result.retrieved, 1):
        print(f"  {i}. [{r.score:.3f}] {r.path}")
    print()
    print("Answer:")
    print(result.answer)
    print()
    if result.sources_used:
        print("Sources used:")
        for p in result.sources_used:
            print(f"  - {p}")
    else:
        print("Sources used: (none)")


if __name__ == "__main__":
    main()
