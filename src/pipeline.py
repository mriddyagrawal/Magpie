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
from dataclasses import dataclass, field

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
    answer: str                         # Kimi's final answer ("" if not_found)
    sources_used: list[str]             # Subset of retrieved paths Kimi cited
    # Spans the model quoted as its evidence (evidence grounding mode); empty
    # in numerals/off mode and on providers that cannot be asked for quotes.
    evidence: list[str] = field(default_factory=list)
    # Not-found state. When True, `answer` and `sources_used` are empty and the
    # ask bar renders State 5 with the single "Add folder" CTA. The model sets
    # these via the `not_found` / `not_found_topic` fields on Answer; see
    # Specs/UI/ask_bar.md and Plan #25 in Plans/Future Plans.md.
    not_found: bool = False
    not_found_topic: str = ""
    # Wall-clock per stage, seconds. Populated by `ask()` so an eval harness
    # can record where a query's time actually went instead of only its total
    # — the difference between "the model is slow" and "we read 12 files".
    timings: dict[str, float] = field(default_factory=dict)


def _answer_temperature(effective: float) -> float | None:
    """Answer-step temperature, provider-aware.

    The app default (0.7) is a cloud number. The local model is
    LFM2.5-VL-3B, whose card asks for 0.1, and the local answer step is
    extraction rather than prose — 0.7 there bought us ~8 of 40 eval
    questions flipping between runs on identical prompts. So on the local
    provider, a temperature the user never explicitly chose falls through
    to the model profile's own value (None = "use the profile default"),
    while an explicit choice is still honored. Cloud is untouched.

    Same shape as `server._rewrite_for_provider`: one knob, two providers,
    the difference decided here rather than pushed onto the user.
    """
    try:
        from src.config.settings import load_user_settings
        from src.llm import active_provider

        if load_user_settings().temperature is not None:
            return effective  # the user pinned it; honor it on both paths
        if active_provider().name == "local":
            return None
    except Exception:  # noqa: BLE001 — never block a query on settings
        pass
    return effective


async def ask(
    question: str,
    *,
    top_k: int = 5,
    rewrite: bool = False,
    fast: bool = False,
    history: list[tuple[str, str]] | None = None,
) -> PipelineResult:
    """Run the full retrieve -> answer pipeline for one question.

    1. **Query construction.** If `rewrite=True`, Kimi expands the question
       into a keyword-rich `SearchQuery` (~20s LLM round-trip). If False
       (default), we skip the rewrite and send the raw question to the
       embedders — faster, and usually fine for question sets that already
       contain good entity names / document terms.
    2. `run_search(sq, top_k)` — Qdrant hybrid search (dense + BM25 via RRF)
       over the summary index. When `fast=False` (default), the ColPali
       visual tier is skipped — saves the ~25s first-query model load and
       ~1s/query encode. Visual search is opt-in.
    3. `answer_question(agent, question, paths)` — read the retrieved files,
       send them with the question to Kimi, get a grounded answer + citations.

    `PipelineResult.search_query` always carries the query we actually sent
    to the embedders (rewritten or raw), so eval and debugging see the truth.

    Per-step timings + retrieval results are printed to stderr so the
    sidecar terminal (`just serve-dev` or under tauri-dev) shows a query
    trace. Overhead is negligible; turn off by silencing stderr if needed.
    """
    import time
    t_start = time.monotonic()
    timings: dict[str, float] = {}
    # Read the user's Settings → Search & AI knobs once per query.
    #   - enumerate_lists: off = treat every query as a regular search
    #     (no top_k widening, no rerank suppression, no ENUMERATION MODE
    #     prompt addition).
    #   - temperature: applied to the answer-step LLM call (the rewrite
    #     step keeps its own low-temp default — temperature is a
    #     creativity knob for prose, not for keyword extraction).
    try:
        from src.config.settings import effective_settings
        eff = effective_settings()
        enumerate_lists = eff.enumerate_lists
        answer_temperature = _answer_temperature(eff.temperature)
    except Exception:  # noqa: BLE001 — defensive, never block on settings
        enumerate_lists = True
        answer_temperature = None
    print(f"\n[query] question: {question!r} (top_k={top_k}, rewrite={rewrite}, "
          f"fast={fast}, enumerate_lists={enumerate_lists}, "
          f"temperature={answer_temperature})",
          file=sys.stderr, flush=True)

    if rewrite:
        t = time.monotonic()
        sq: SearchQuery = await asyncio.to_thread(rewrite_query, question)
        timings["rewrite"] = time.monotonic() - t
        print(f"[query] rewrite ({timings['rewrite']:.2f}s): "
              f"query={sq.query!r} keywords={sq.keywords}",
              file=sys.stderr, flush=True)
    else:
        sq = raw_query(question)
        print(f"[query] rewrite: skipped (using raw question)",
              file=sys.stderr, flush=True)

    t = time.monotonic()
    retrieved = await asyncio.to_thread(
        run_search, sq, top_k,
        question=question, skip_fast=not fast, rerank=True,
        enumerate_lists=enumerate_lists,
    )
    # Confident-retrieval solo gate (local only) — see search.gate_to_solo.
    from src.stage2.search import gate_to_solo
    retrieved = gate_to_solo(retrieved, question=question)
    timings["retrieval"] = time.monotonic() - t
    try:
        from src.stage2.search import LAST_SUBTIMINGS
        timings.update({f"retr_{k}": v for k, v in LAST_SUBTIMINGS.items()})
    except Exception:  # noqa: BLE001 — instrumentation must never break a query
        pass
    print(f"[query] retrieval ({timings['retrieval']:.2f}s): {len(retrieved)} hits",
          file=sys.stderr, flush=True)
    for i, r in enumerate(retrieved, 1):
        # `summary` is the snippet text; truncate to avoid wall-of-text spam.
        snippet = (r.summary or "").replace("\n", " ")[:120]
        print(f"  [{i}] tier={r.tier} score={r.score:.3f} {r.path}\n      └ {snippet}",
              file=sys.stderr, flush=True)

    if not retrieved:
        # Empty retrieval is a special not-found shape: we never even reached
        # the answer model. Synthesize a not_found result so the ask bar
        # renders State 5 (the "Add folder" CTA) consistently with the case
        # where the model did read sources but couldn't answer.
        print(f"[query] no hits — emitting not_found "
              f"(total {time.monotonic()-t_start:.2f}s)",
              file=sys.stderr, flush=True)
        return PipelineResult(
            question=question,
            search_query=sq,
            retrieved=[],
            answer="",
            sources_used=[],
            not_found=True,
            not_found_topic=question.strip().rstrip("?").strip(),
        )

    paths = list(dict.fromkeys(r.path for r in retrieved if r.path))

    # Group CSV chunk (row) hits per path so the answer step can substitute
    # row-window blocks for the file-prefix dump (Plan #17 Part B).
    # Non-chunked hits have chunk_index=None and don't appear here.
    # Future PDF chunk hits will populate this same structure but with
    # different downstream handling in the answer step.
    csv_row_hits: dict[str, list[int]] = {}
    for r in retrieved:
        if r.path and r.chunk_index is not None:
            csv_row_hits.setdefault(r.path, []).append(int(r.chunk_index))
    if csv_row_hits:
        rows_summary = ", ".join(
            f"{p.rsplit('/', 1)[-1]}={sorted(set(idxs))}"
            for p, idxs in csv_row_hits.items()
        )
        print(f"[query] csv row hits: {rows_summary}",
              file=sys.stderr, flush=True)
    print(f"[query] reading {len(paths)} unique file(s) for answer step",
          file=sys.stderr, flush=True)

    agent = build_answer_agent()
    t = time.monotonic()
    ans: Answer = await answer_question(
        agent, question, paths, search_query=sq,
        csv_row_hits=csv_row_hits or None,
        enumerate_lists=enumerate_lists,
        temperature=answer_temperature,
    )
    timings["answer"] = time.monotonic() - t
    try:
        from src.answer import LAST_ROUTE, LAST_SUBTIMINGS as _ANS_SUB
        timings["answer_extractive"] = float(LAST_ROUTE.get("extractive", 0.0))
        timings["answer_files_first"] = float(LAST_ROUTE.get("files_first", 0.0))
        timings["answer_grounding_flagged"] = float(LAST_ROUTE.get("grounding_flagged", 0.0))
        timings.update({f"ans_{k}": v for k, v in _ANS_SUB.items()})
    except Exception:  # noqa: BLE001 — instrumentation must never break a query
        pass
    print(f"[query] answer ({timings['answer']:.2f}s): "
          f"{len(ans.answer)} chars, sources_used={ans.sources_used}",
          file=sys.stderr, flush=True)
    print(f"[query] total {time.monotonic()-t_start:.2f}s",
          file=sys.stderr, flush=True)

    timings["total"] = time.monotonic() - t_start
    timings["files_read"] = float(len(paths))
    return PipelineResult(
        question=question,
        search_query=sq,
        retrieved=retrieved,
        answer=ans.answer,
        sources_used=ans.sources_used,
        evidence=list(getattr(ans, "evidence", []) or []),
        not_found=ans.not_found,
        not_found_topic=ans.not_found_topic,
        timings=timings,
    )


def ask_sync(
    question: str,
    *,
    top_k: int = 5,
    rewrite: bool = False,
    fast: bool = False,
) -> PipelineResult:
    return asyncio.run(ask(question, top_k=top_k, rewrite=rewrite, fast=fast))


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
    from src.manifest import DEFAULT_MANIFEST_PATH, SUMMARIES_DIR
    from src.stage2.db import COLLECTION_NAME, get_qdrant_client

    summaries_dir = SUMMARIES_DIR

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

    # Drop the Qdrant `summaries` collection. Don't fail the reset if
    # Qdrant is down — local cleanup already happened.
    collection_dropped = False
    fast_tier_dropped = False
    qdrant_error: str | None = None
    try:
        client = get_qdrant_client()
        if client.collection_exists(COLLECTION_NAME):
            client.delete_collection(COLLECTION_NAME)
            collection_dropped = True
        # Drop the fast_tier (ColPali multi-vector) collection too.
        # Hardcoded name since fast_db.py exposes it via a function rather
        # than a constant; this is the canonical collection name in code.
        if client.collection_exists("fast_tier"):
            client.delete_collection("fast_tier")
            fast_tier_dropped = True
    except Exception as e:
        qdrant_error = f"{type(e).__name__}: {e}"

    return {
        "summaries_deleted": deleted_summaries,
        "manifest_removed": manifest_removed,
        "collection_dropped": collection_dropped,
        "fast_tier_dropped": fast_tier_dropped,
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
