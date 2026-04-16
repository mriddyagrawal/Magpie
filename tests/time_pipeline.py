"""Run a single question through the pipeline with per-step wall-clock timing.

Breaks down where time actually goes: Kimi query rewrite, embedding, Qdrant search,
file reads + vision rendering, Kimi answer. Use this to decide whether the Qdrant
hop (the only step the cloud-vs-local choice affects) is worth optimizing.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

from src.answer import answer_question, build_answer_agent
from src.content import build_content_blocks
from src.stage2.db import get_qdrant_client
from src.stage2.embeddings import embed_dense_query, embed_sparse_query, get_dense_model, get_sparse_model
from src.stage2.search import rewrite_query, run_search


def _warm_embedding_models() -> float:
    """Force-load dense + sparse models before the real timing starts.

    First-run cost for these is model-download + Torch init (~5-15s, one-time).
    We pay it once up-front so the per-step numbers reflect steady state.
    """
    t0 = time.monotonic()
    get_dense_model()
    get_sparse_model()
    embed_dense_query("warmup")
    embed_sparse_query("warmup")
    return time.monotonic() - t0


def _qdrant_ping() -> float:
    """Cheap round-trip to Qdrant to measure network latency alone."""
    client = get_qdrant_client()
    t0 = time.monotonic()
    client.get_collections()
    return time.monotonic() - t0


async def timed_run(question: str, top_k: int = 5) -> None:
    print(f"Question: {question!r}")
    print(f"Top-k:    {top_k}\n")

    # --- Warm everything so we're measuring steady-state, not one-time setup.
    warm = _warm_embedding_models()
    print(f"  [warmup] dense+sparse embedding models loaded in {warm:.3f}s (one-time)\n")

    ping = _qdrant_ping()
    print(f"  [ping] Qdrant round-trip: {ping*1000:.1f} ms")
    print(f"  (this is the cloud vs. local difference in isolation)\n")

    print("=" * 60)
    print("PIPELINE STEPS")
    print("=" * 60)

    # --- Step 1: Kimi query rewrite
    t0 = time.monotonic()
    sq = await asyncio.to_thread(rewrite_query, question)
    t_rewrite = time.monotonic() - t0
    print(f"\n[1] Kimi query rewrite              : {t_rewrite:6.2f} s")
    print(f"    query    = {sq.query!r}")
    print(f"    keywords = {sq.keywords}")

    # --- Step 2: dense embedding of rewritten query
    dense_text = sq.query + " " + " ".join(sq.keywords)
    t0 = time.monotonic()
    dense_vec = embed_dense_query(dense_text)
    t_dense = time.monotonic() - t0
    print(f"\n[2] Dense embedding (local)         : {t_dense*1000:6.1f} ms  ({len(dense_vec)}-dim)")

    # --- Step 3: sparse embedding of rewritten query
    t0 = time.monotonic()
    sparse_idx, sparse_val = embed_sparse_query(dense_text)
    t_sparse = time.monotonic() - t0
    print(f"[3] Sparse BM25 embedding (local)   : {t_sparse*1000:6.1f} ms  ({len(sparse_idx)} nonzero)")

    # --- Step 4: Qdrant hybrid search
    t0 = time.monotonic()
    retrieved = await asyncio.to_thread(run_search, sq, top_k)
    t_qdrant = time.monotonic() - t0
    # run_search re-embeds internally (small duplicate cost). Subtract steady-state
    # embedding time to isolate the actual Qdrant query time.
    t_qdrant_net = t_qdrant - (t_dense + t_sparse)
    print(f"[4] Qdrant hybrid search (RRF)      : {t_qdrant:6.2f} s  (net Qdrant: ~{t_qdrant_net*1000:.1f} ms)")
    for i, r in enumerate(retrieved, 1):
        print(f"    {i}. [{r.score:.3f}] {r.path}")

    if not retrieved:
        print("\nNo results retrieved. Skipping answer step.")
        return

    # --- Step 5: build stage-4 Agent
    t0 = time.monotonic()
    agent = build_answer_agent()
    t_agent = time.monotonic() - t0
    print(f"\n[5] Build answer agent              : {t_agent*1000:6.1f} ms")

    # --- Step 6: file reads (blocking I/O) — pull blocks for each retrieved file
    paths = [r.path for r in retrieved if r.path]
    ANSWER_MAX_CHARS = 25_000
    ANSWER_MAX_PDF_PAGES = 5
    t0 = time.monotonic()
    _ = [
        await asyncio.to_thread(
            build_content_blocks, REPO_ROOT / p, max_chars=ANSWER_MAX_CHARS, max_pdf_pages=ANSWER_MAX_PDF_PAGES
        )
        for p in paths
    ]
    t_reads = time.monotonic() - t0
    print(f"[6] Read + extract {len(paths)} files           : {t_reads:6.2f} s")

    # --- Step 7: Kimi answer (the big one)
    t0 = time.monotonic()
    ans = await answer_question(agent, question, paths)
    t_answer = time.monotonic() - t0
    print(f"[7] Kimi answer (incl. file reads)  : {t_answer:6.2f} s")
    print(f"    answer: {ans.answer[:200]}{'...' if len(ans.answer) > 200 else ''}")
    print(f"    sources_used: {ans.sources_used}")

    total = t_rewrite + t_dense + t_sparse + t_qdrant_net + t_agent + t_answer
    print("\n" + "=" * 60)
    print("BREAKDOWN")
    print("=" * 60)
    rows = [
        ("Kimi query rewrite",    t_rewrite),
        ("Dense embed (local)",   t_dense),
        ("Sparse embed (local)",  t_sparse),
        ("Qdrant search (net)",   t_qdrant_net),
        ("Build answer agent",    t_agent),
        ("Kimi answer",           t_answer),
    ]
    for label, t in rows:
        pct = 100 * t / total if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {label:<24s} {t*1000:8.1f} ms  ({pct:5.1f}%)  {bar}")
    print(f"  {'TOTAL':<24s} {total*1000:8.1f} ms")

    print("\n" + "=" * 60)
    print("CLOUD VS LOCAL QDRANT — WHAT WOULD CHANGE?")
    print("=" * 60)
    print(f"  Current Qdrant (cloud) net latency : ~{t_qdrant_net*1000:.1f} ms")
    print(f"  Local Qdrant would save            : ~{max(t_qdrant_net*1000 - 5, 0):.1f} ms")
    print(f"  That's                             : {100 * max(t_qdrant_net - 0.005, 0) / total:.2f}% of total wall time")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Time each step of the pipeline for one question.")
    parser.add_argument(
        "question",
        nargs="?",
        default="According to MTH-245 Handout 0, what minimum sample size does the Central Limit Theorem generally require for a test about a population mean?",
        help="The question (default: a medium question from the eval set).",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(timed_run(args.question, args.top_k))


if __name__ == "__main__":
    main()
