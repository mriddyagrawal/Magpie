"""Retrieval eval over `tests/retrieval_questions.json`.

For each hand-crafted question, run the full pipeline (stage 3 retrieve + stage
4 answer) and score whether the *expected* receipt appeared in the top-k. This
is what tells us if retrieval is actually doing its job — unlike the raw
ReceiptQA questions, each entry here contains a disambiguator (merchant+date,
unique item combo, order number) so the right receipt is identifiable from the
question alone.

Assumes Qdrant is already populated for `Test Content/`. Run `ns --sync` first.

Usage:
    uv run python3 -m tests.retrieval_eval                 # top-k 5, no rewrite
    uv run python3 -m tests.retrieval_eval --top-k 10
    uv run python3 -m tests.retrieval_eval --rewrite       # enable Kimi rewrite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.llm import active_model_name, active_provider
from src.pipeline import ask


REPO_ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_FILE = REPO_ROOT / "tests" / "retrieval_questions.json"
OUTPUT_DIR = REPO_ROOT / "tests"


def expected_path(receipt_id: int) -> str:
    return f"Test Content/{receipt_id}.jpg"


async def run_one(q: dict, top_k: int, rewrite: bool) -> dict[str, Any]:
    t0 = time.monotonic()
    expected = expected_path(q["expected_receipt_id"])
    try:
        result = await ask(q["question"], top_k=top_k, rewrite=rewrite)
        retrieved_paths = [r.path for r in result.retrieved]
        # Rank is 1-based; None = miss.
        hit_rank = None
        for i, p in enumerate(retrieved_paths, 1):
            if p == expected:
                hit_rank = i
                break
        return {
            "ok": True,
            "question": q["question"],
            "expected_receipt_id": q["expected_receipt_id"],
            "expected_path": expected,
            "ground_truth": q.get("answer"),
            "search_query": {
                "query": result.search_query.query,
                "keywords": result.search_query.keywords,
            },
            "retrieved": [
                {"path": r.path, "score": r.score, "summary": r.summary}
                for r in result.retrieved
            ],
            "hit_rank": hit_rank,
            "predicted_answer": result.answer,
            "sources_used": list(result.sources_used),
            "elapsed_s": time.monotonic() - t0,
        }
    except Exception as e:
        return {
            "ok": False,
            "question": q["question"],
            "expected_receipt_id": q["expected_receipt_id"],
            "expected_path": expected,
            "ground_truth": q.get("answer"),
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
            "elapsed_s": time.monotonic() - t0,
        }


def write_markdown(
    results: list[dict[str, Any]],
    output_file: Path,
    *,
    model: str,
    provider: str,
    top_k: int,
    rewrite: bool,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []
    lines.append("# Retrieval eval (stages 3 + 4)")
    lines.append("")
    lines.append(f"- Run: {now}")
    lines.append(f"- Model: `{model}` (via {provider})")
    lines.append(f"- Top-k: {top_k}")
    lines.append(f"- Query rewrite: {'on' if rewrite else 'off'}")
    lines.append(f"- Questions: {len(results)}")
    lines.append("")

    total = len(results)
    hits = sum(1 for r in results if r.get("ok") and r.get("hit_rank") is not None)
    top1 = sum(1 for r in results if r.get("ok") and r.get("hit_rank") == 1)
    errors = sum(1 for r in results if not r.get("ok"))
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Retrieval recall @ top-{top_k}: **{hits}/{total}** ({hits / total * 100:.0f}%)")
    lines.append(f"- Retrieval recall @ top-1:     **{top1}/{total}** ({top1 / total * 100:.0f}%)")
    if errors:
        lines.append(f"- Errors: {errors}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| # | Expected | Hit rank | Elapsed | Question |")
    lines.append("|---|---|---|---|---|")
    for i, r in enumerate(results, 1):
        if not r.get("ok"):
            lines.append(
                f"| {i} | {r['expected_receipt_id']} | ERROR | {r['elapsed_s']:.1f}s | {r['question'][:60]} |"
            )
            continue
        rank = r["hit_rank"]
        rank_cell = f"#{rank}" if rank else "**MISS**"
        lines.append(
            f"| {i} | {r['expected_receipt_id']} | {rank_cell} | {r['elapsed_s']:.1f}s | {r['question'][:60]} |"
        )
    lines.append("")

    lines.append("## Per-question")
    lines.append("")
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. Expected receipt {r['expected_receipt_id']}")
        lines.append("")
        lines.append(f"**Q:** {r['question']}")
        lines.append("")
        if r.get("ground_truth") is not None:
            lines.append(f"**Ground truth:** {r['ground_truth']}")
            lines.append("")

        if not r.get("ok"):
            lines.append(f"**ERROR:** `{r['error']}`")
            lines.append("")
            lines.append("```")
            lines.append(r.get("traceback", ""))
            lines.append("```")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue

        sq = r["search_query"]
        lines.append("**Search query sent to embedders:**")
        lines.append("")
        lines.append(f"- `query`: *{sq['query']}*")
        kws = sq.get("keywords") or []
        lines.append(
            "- `keywords`: "
            + (", ".join(f"`{k}`" for k in kws) if kws else "_(none)_")
        )
        lines.append("")

        rank = r["hit_rank"]
        lines.append(
            f"**Retrieval:** {'HIT at rank ' + str(rank) if rank else '**MISS** (expected path not in top-k)'}"
        )
        lines.append("")
        if r["retrieved"]:
            lines.append(f"**Top-{top_k} retrieved:**")
            lines.append("")
            lines.append("| Rank | Score | Path | Match? |")
            lines.append("|---|---|---|---|")
            for j, d in enumerate(r["retrieved"], 1):
                match = "EXPECTED" if d["path"] == r["expected_path"] else ""
                lines.append(f"| {j} | {d['score']:.4f} | `{d['path']}` | {match} |")
            lines.append("")
        else:
            lines.append("**Top-k retrieved:** _(none)_")
            lines.append("")

        lines.append("**Predicted answer:**")
        lines.append("")
        lines.append(r["predicted_answer"])
        lines.append("")
        lines.append(f"**sources_used:** `{r['sources_used']}`")
        lines.append("")
        lines.append(f"*Elapsed: {r['elapsed_s']:.1f}s*")
        lines.append("")
        lines.append("---")
        lines.append("")

    output_file.write_text("\n".join(lines), encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    load_dotenv()
    provider = active_provider().name
    model = active_model_name()

    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(questions)} retrieval questions from {QUESTIONS_FILE.name}")
    print(f"Model: {model} (via {provider}); top-k={args.top_k}; rewrite={args.rewrite}")

    results: list[dict[str, Any]] = []
    for i, q in enumerate(questions, 1):
        preview = q["question"][:60] + ("…" if len(q["question"]) > 60 else "")
        print(f"  [{i}/{len(questions)}] expect r{q['expected_receipt_id']}: {preview}")
        r = await run_one(q, top_k=args.top_k, rewrite=args.rewrite)
        results.append(r)
        if r.get("ok"):
            rank = r["hit_rank"]
            tag = f"HIT @{rank}" if rank else "MISS"
            print(f"    {tag} ({r['elapsed_s']:.1f}s)")
        else:
            print(f"    ERROR: {r['error']}")

    safe_model = model.replace("/", "_").replace(":", "_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = args.out or (OUTPUT_DIR / f"retrieval_{safe_model}_{ts}.md")
    write_markdown(
        results,
        output_path,
        model=model,
        provider=provider,
        top_k=args.top_k,
        rewrite=args.rewrite,
    )
    print(f"\nWrote {output_path.relative_to(REPO_ROOT)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=5, help="Qdrant top-k (default 5).")
    parser.add_argument(
        "--rewrite",
        action="store_true",
        help="Enable Kimi query rewrite (off by default; adds ~20s/question).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output markdown path (default: tests/retrieval_<model>_<ts>.md).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
