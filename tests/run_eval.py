"""Run every question in `Test Questions/questions.jsonl` through the stage-4 answerer
and write a markdown eval report to `tests/eval_results.md`.

Each test mixes the ground-truth source files with a few distractors and feeds them
to Kimi. The output file lets a human see whether Kimi (a) got the answer right
and (b) cited only the correct files out of the mixed set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
from tqdm import tqdm  # noqa: E402

from answer import answer_question, build_answer_agent  # noqa: E402


QUESTIONS_FILE = REPO_ROOT / "Test Questions" / "questions.jsonl"
DEFAULT_OUTPUT_FILE = REPO_ROOT / "tests" / "eval_results.md"
DEFAULT_CONCURRENCY = 6
SHUFFLE_SEED = 42
VALID_DIFFICULTIES = {"easy", "medium", "hard", "all"}


def load_questions() -> list[dict]:
    rows: list[dict] = []
    with QUESTIONS_FILE.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


async def run_question(agent, sem: asyncio.Semaphore, q: dict) -> dict:
    rng = random.Random(SHUFFLE_SEED + sum(ord(c) for c in q["id"]))
    inputs = list(q["source_files"]) + list(q["distractor_files"])
    rng.shuffle(inputs)

    async with sem:
        t0 = time.monotonic()
        try:
            ans = await answer_question(agent, q["question"], inputs)
            return {
                "id": q["id"],
                "ok": True,
                "difficulty": q["difficulty"],
                "question": q["question"],
                "expected_answer": q["expected_answer"],
                "expected_files": list(q["source_files"]),
                "distractor_files": list(q["distractor_files"]),
                "input_order": inputs,
                "files_used": list(ans.sources_used),
                "answer": ans.answer,
                "elapsed_s": time.monotonic() - t0,
            }
        except Exception as e:
            return {
                "id": q["id"],
                "ok": False,
                "difficulty": q["difficulty"],
                "question": q["question"],
                "expected_answer": q["expected_answer"],
                "expected_files": list(q["source_files"]),
                "distractor_files": list(q["distractor_files"]),
                "error": f"{type(e).__name__}: {e}",
                "elapsed_s": time.monotonic() - t0,
            }


def compute_scores(r: dict) -> dict:
    if not r["ok"]:
        return {"recall": "—", "precision": "—", "distractors_cited": "—"}
    expected = set(r["expected_files"])
    used = set(r["files_used"])
    distractors = set(r["distractor_files"])
    correct = expected & used
    recall = f"{len(correct)}/{len(expected)}"
    precision = f"{len(correct)}/{len(used)}" if used else "0/0"
    return {
        "recall": recall,
        "precision": precision,
        "distractors_cited": len(used & distractors),
    }


def annotate_file(p: str, expected: set[str], distractors: set[str]) -> str:
    if p in expected:
        return "(expected)"
    if p in distractors:
        return "(DISTRACTOR cited - model was fooled)"
    return "(hallucinated - should not reach here)"


def write_markdown(results: list[dict], output_file: Path, model_name: str, difficulty_filter: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    total = len(results)
    ok = sum(1 for r in results if r["ok"])

    by_diff: dict[str, list[dict]] = {}
    for r in results:
        by_diff.setdefault(r["difficulty"], []).append(r)

    output_file.parent.mkdir(exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        f.write("# Stage 4 Eval Results\n\n")
        f.write(f"- Run: {now}\n")
        f.write(f"- Model: {model_name} via Moonshot\n")
        f.write(f"- Difficulty filter: {difficulty_filter}\n")
        f.write(f"- Total: {total} ({ok} succeeded, {total - ok} errored)\n")
        for diff in ("easy", "medium", "hard"):
            if diff in by_diff:
                f.write(f"- {diff}: {len(by_diff[diff])}\n")
        f.write("\n")

        # Aggregate scoring
        total_distractors_cited = sum(
            compute_scores(r)["distractors_cited"] if r["ok"] else 0 for r in results
        )
        perfect_recall = sum(
            1 for r in results
            if r["ok"] and set(r["expected_files"]).issubset(set(r["files_used"]))
        )
        no_distractors = sum(
            1 for r in results
            if r["ok"] and not (set(r["files_used"]) & set(r["distractor_files"]))
        )
        f.write("## Aggregate\n\n")
        f.write(f"- Questions with **perfect source recall** (all expected files cited): {perfect_recall}/{total}\n")
        f.write(f"- Questions that **cited no distractors**: {no_distractors}/{total}\n")
        f.write(f"- Total distractor citations across all questions: {total_distractors_cited}\n\n")

        f.write("## Summary table\n\n")
        f.write("| ID | Difficulty | Source recall | Source precision | Distractors cited | Elapsed (s) |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in results:
            s = compute_scores(r)
            f.write(
                f"| {r['id']} | {r['difficulty']} | {s['recall']} | {s['precision']} | "
                f"{s['distractors_cited']} | {r['elapsed_s']:.1f} |\n"
            )
        f.write("\n")

        f.write("## Per-question results\n\n")
        for r in results:
            expected = set(r["expected_files"])
            distractors = set(r["distractor_files"])

            f.write(f"### {r['id']} — {r['difficulty']}\n\n")
            f.write(f"**Question:** {r['question']}\n\n")
            f.write(f"**Expected answer:** {r['expected_answer']}\n\n")

            f.write("**Expected source files:**\n")
            for p in r["expected_files"]:
                f.write(f"- `{p}`\n")
            f.write("\n")

            f.write("**Distractor files (fed to Kimi but should NOT be cited):**\n")
            for p in r["distractor_files"]:
                f.write(f"- `{p}`\n")
            f.write("\n")

            if r["ok"]:
                f.write("**Files Kimi cited as sources:**\n")
                if r["files_used"]:
                    for p in r["files_used"]:
                        f.write(f"- `{p}` {annotate_file(p, expected, distractors)}\n")
                else:
                    f.write("- (none)\n")
                f.write("\n")
                f.write(f"**Kimi's answer:**\n\n{r['answer']}\n\n")
            else:
                f.write(f"**ERROR:** {r['error']}\n\n")

            f.write(f"*Elapsed: {r['elapsed_s']:.1f}s*\n\n")
            f.write("---\n\n")


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the stage-4 eval suite.")
    parser.add_argument("--difficulty", choices=sorted(VALID_DIFFICULTIES), default="all",
                        help="Only run questions of this difficulty (default: all).")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"Parallel Kimi calls (default: {DEFAULT_CONCURRENCY}).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_FILE,
                        help=f"Output markdown file (default: {DEFAULT_OUTPUT_FILE.relative_to(REPO_ROOT)}).")
    args = parser.parse_args()

    questions = load_questions()
    if args.difficulty != "all":
        questions = [q for q in questions if q["difficulty"] == args.difficulty]
    if not questions:
        sys.exit(f"no questions match difficulty={args.difficulty!r}")

    model_name = os.environ.get("MOONSHOT_MODEL", "kimi-k2.5")
    agent = build_answer_agent()
    sem = asyncio.Semaphore(args.concurrency)
    bar = tqdm(total=len(questions), desc=f"eval ({args.difficulty})", unit="q")

    async def wrapped(q: dict) -> dict:
        r = await run_question(agent, sem, q)
        bar.set_postfix_str(r["id"][:20])
        bar.update(1)
        return r

    results = await asyncio.gather(*(wrapped(q) for q in questions))
    bar.close()

    diff_order = {"easy": 0, "medium": 1, "hard": 2}
    results.sort(key=lambda r: (diff_order.get(r["difficulty"], 3), r["id"]))

    write_markdown(results, args.out, model_name=model_name, difficulty_filter=args.difficulty)
    print(f"wrote: {args.out.relative_to(REPO_ROOT) if args.out.is_relative_to(REPO_ROOT) else args.out}")


if __name__ == "__main__":
    asyncio.run(main())
