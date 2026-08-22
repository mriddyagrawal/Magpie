"""Run every question in `Test Questions/questions.jsonl` through the full
retrieve + answer pipeline, using whatever provider/model is active in `.env`.

Designed to be re-run whenever you swap `LLM_PROVIDER` or `<provider>_MODEL` in
`.env` — the output filename embeds the active model name + a timestamp, so
successive runs don't clobber each other and can be diffed side-by-side.

Assumes `ns --sync` has already populated Qdrant. This script only reads.

Usage:
    # All 35 questions, sequential (safest for free-tier / rate-limited models)
    uv run python3 -m tests.run_all_questions

    # Just easy + concurrent (Kimi, paid OpenAI, etc.)
    uv run python3 -m tests.run_all_questions --difficulty easy --concurrency 4

    # Custom top-k, custom output path
    uv run python3 -m tests.run_all_questions --top-k 10 --out /tmp/report.md
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv

from tests.run_pipeline_eval import load_questions, run_one, write_markdown


DEFAULT_OUTPUT_DIR = REPO_ROOT / "tests"
DIFF_ORDER = {"easy": 0, "medium": 1, "hard": 2}


def _default_output_path(model_name: str) -> Path:
    """Build a default report path that encodes the model + a UTC timestamp."""
    safe_model = (
        model_name
        .replace("/", "_")
        .replace(":", "_")
        .replace(" ", "_")
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"eval_{safe_model}_{timestamp}.md"


async def main_async(args: argparse.Namespace) -> None:
    from src.llm import active_model_name, active_provider

    questions = load_questions()
    if args.difficulty != "all":
        questions = [q for q in questions if q["difficulty"] == args.difficulty]
    if not questions:
        sys.exit(f"no questions match difficulty={args.difficulty!r}")

    model_name = active_model_name()
    provider = active_provider().name
    out_path = args.out or _default_output_path(model_name)

    print(
        f"running {len(questions)} question(s) [{args.difficulty}] "
        f"through {model_name} (via {provider})"
    )
    print(f"concurrency={args.concurrency}, top_k={args.top_k}")
    print(f"output: {out_path}\n")

    sem = asyncio.Semaphore(args.concurrency)

    async def worker(q: dict) -> dict:
        async with sem:
            print(f"  [{q['difficulty']}] {q['id']}...")
            result = await run_one(q, top_k=args.top_k)
            ok = "ok" if result.get("ok") else f"ERROR: {result.get('error', '?')}"
            print(f"  [{q['difficulty']}] {q['id']} done ({result['elapsed_s']:.1f}s) - {ok}")
            return result

    results = await asyncio.gather(*(worker(q) for q in questions))
    results.sort(key=lambda r: (DIFF_ORDER.get(r["difficulty"], 3), r["id"]))

    write_markdown(results, out_path, model_name=model_name, top_k=args.top_k)
    rel = out_path.relative_to(REPO_ROOT) if out_path.is_relative_to(REPO_ROOT) else out_path
    print(f"\nwrote: {rel}")

    # Quick summary on stdout
    ok_count = sum(1 for r in results if r.get("ok"))
    errored = len(results) - ok_count
    print(f"summary: {ok_count}/{len(results)} succeeded, {errored} errored")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Run all questions through the retrieve + answer pipeline, current .env provider."
    )
    parser.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard", "all"],
        default="all",
        help="Filter by difficulty (default: all).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Parallel pipeline runs (default: 1). "
            "Raise to 3-6 for Kimi / paid OpenAI; keep at 1 for free-tier Gemma."
        ),
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Qdrant top-k (default: 5).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output markdown path. Defaults to "
            "tests/eval_<model>_<UTC-timestamp>.md so runs with different "
            "models don't clobber each other."
        ),
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
