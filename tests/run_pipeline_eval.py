"""End-to-end pipeline eval: pick N random questions at a given difficulty and run
the full retrieve -> answer flow through src.pipeline.ask.

Assumes Qdrant is already populated (`python -m src.stage2 ingest`). This script
does NOT re-ingest.

For each question, the markdown report captures:
- The question + expected answer + expected source files
- Kimi's rewritten search query (the string + keywords actually used for retrieval)
- The top-k retrieved files from Qdrant (path + score + summary snippet)
- Kimi's final answer
- The sources Kimi cited
- A verdict on whether every expected file was in the top-k (retrieval recall)
  and whether every expected file was cited in sources_used (citation recall).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv

from src.pipeline import PipelineResult, ask


QUESTIONS_FILE = REPO_ROOT / "Test Questions" / "questions.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "tests" / "pipeline_eval_results.md"
DEFAULT_N = 3
DEFAULT_DIFFICULTY = "medium"
DEFAULT_TOP_K = 5
DEFAULT_SEED = 42


def load_questions() -> list[dict]:
    rows: list[dict] = []
    with QUESTIONS_FILE.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


async def run_one(q: dict, top_k: int) -> dict:
    t0 = time.monotonic()
    try:
        result: PipelineResult = await ask(q["question"], top_k=top_k)
        return {
            "ok": True,
            "id": q["id"],
            "difficulty": q["difficulty"],
            "question": q["question"],
            "expected_answer": q["expected_answer"],
            "expected_files": list(q["source_files"]),
            "search_query": {
                "query": result.search_query.query,
                "keywords": result.search_query.keywords,
            },
            "retrieved": [asdict(r) for r in result.retrieved],
            "answer": result.answer,
            "sources_used": list(result.sources_used),
            "elapsed_s": time.monotonic() - t0,
        }
    except Exception as e:
        return {
            "ok": False,
            "id": q["id"],
            "difficulty": q["difficulty"],
            "question": q["question"],
            "expected_answer": q["expected_answer"],
            "expected_files": list(q["source_files"]),
            "error": f"{type(e).__name__}: {e}",
            "elapsed_s": time.monotonic() - t0,
        }


def _fmt_set(items: list[str]) -> str:
    return "\n".join(f"- `{p}`" for p in items) if items else "- (none)"


def write_markdown(results: list[dict], output_file: Path, model_name: str, top_k: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    output_file.parent.mkdir(exist_ok=True)

    with output_file.open("w", encoding="utf-8") as f:
        f.write("# Pipeline Eval Results (stages 3 + 4, end-to-end)\n\n")
        f.write(f"- Run: {now}\n")
        f.write(f"- Model: {model_name} via Moonshot\n")
        f.write(f"- Top-k (Qdrant): {top_k}\n")
        f.write(f"- Questions: {len(results)}\n\n")

        f.write("## Summary\n\n")
        f.write("| ID | Difficulty | Retrieval recall | Citation recall | Elapsed (s) |\n")
        f.write("|---|---|---|---|---|\n")
        for r in results:
            if not r["ok"]:
                f.write(f"| {r['id']} | {r['difficulty']} | — | — | {r['elapsed_s']:.1f} (ERROR) |\n")
                continue
            expected = set(r["expected_files"])
            retrieved_paths = {d["path"] for d in r["retrieved"]}
            cited = set(r["sources_used"])
            ret_recall = f"{len(expected & retrieved_paths)}/{len(expected)}"
            cit_recall = f"{len(expected & cited)}/{len(expected)}"
            f.write(f"| {r['id']} | {r['difficulty']} | {ret_recall} | {cit_recall} | {r['elapsed_s']:.1f} |\n")
        f.write("\n")

        f.write("## Per-question\n\n")
        for r in results:
            f.write(f"### {r['id']} — {r['difficulty']}\n\n")
            f.write(f"**Question:** {r['question']}\n\n")
            f.write(f"**Expected answer:** {r['expected_answer']}\n\n")
            f.write("**Expected source files:**\n")
            f.write(_fmt_set(r["expected_files"]))
            f.write("\n\n")

            if not r["ok"]:
                f.write(f"**ERROR:** {r['error']}\n\n")
                f.write(f"*Elapsed: {r['elapsed_s']:.1f}s*\n\n---\n\n")
                continue

            sq = r["search_query"]
            f.write("**Kimi-rewritten search query** (what actually hit Qdrant):\n\n")
            f.write(f"- `query`: *{sq['query']}*\n")
            f.write(f"- `keywords`: {', '.join(f'`{k}`' for k in sq['keywords']) if sq['keywords'] else '(none)'}\n\n")

            expected = set(r["expected_files"])
            f.write(f"**Retrieved from Qdrant (top-{top_k}):**\n\n")
            if r["retrieved"]:
                f.write("| Rank | Score | Path | Match? |\n")
                f.write("|---|---|---|---|\n")
                for i, d in enumerate(r["retrieved"], 1):
                    match = "expected" if d["path"] in expected else ""
                    f.write(f"| {i} | {d['score']:.4f} | `{d['path']}` | {match} |\n")
                f.write("\n")
            else:
                f.write("- (none)\n\n")

            f.write("**Kimi's answer:**\n\n")
            f.write(f"{r['answer']}\n\n")

            f.write("**Sources Kimi cited:**\n")
            f.write(_fmt_set(r["sources_used"]))
            f.write("\n\n")

            f.write(f"*Elapsed: {r['elapsed_s']:.1f}s*\n\n---\n\n")


async def main_async(args: argparse.Namespace) -> None:
    questions = [q for q in load_questions() if q["difficulty"] == args.difficulty]
    if len(questions) < args.n:
        raise SystemExit(
            f"only {len(questions)} {args.difficulty} questions available; cannot sample {args.n}"
        )

    rng = random.Random(args.seed)
    sampled = rng.sample(questions, args.n)
    print(f"selected {args.n} {args.difficulty} questions: {[q['id'] for q in sampled]}")

    results = []
    for q in sampled:
        print(f"  running {q['id']}...")
        results.append(await run_one(q, top_k=args.top_k))

    import os
    model_name = os.environ.get("MOONSHOT_MODEL", "kimi-k2.5")
    write_markdown(results, args.out, model_name=model_name, top_k=args.top_k)
    print(f"wrote: {args.out.relative_to(REPO_ROOT) if args.out.is_relative_to(REPO_ROOT) else args.out}")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Pipeline eval: run N random questions end-to-end.")
    parser.add_argument("--n", type=int, default=DEFAULT_N,
                        help=f"How many questions to sample (default: {DEFAULT_N}).")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"], default=DEFAULT_DIFFICULTY,
                        help=f"Difficulty to sample from (default: {DEFAULT_DIFFICULTY}).")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                        help=f"Qdrant top-k (default: {DEFAULT_TOP_K}).")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"RNG seed for reproducible sampling (default: {DEFAULT_SEED}).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Output markdown file (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)}).")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
