"""Random-sample eval over the ReceiptQA benchmark.

Pools every QA pair across `test_label/*.json`, randomly picks N, and runs each
question through stage 4 (`answer_question`) with ONLY that question's own
receipt jpg supplied as the source file. Retrieval is skipped — we're measuring
the LLM's raw ability to read a receipt image and answer a question, not RAG
recall.

Usage:
    uv run python3 -m tests.ReceiptQA_test                     # 10 random picks
    uv run python3 -m tests.ReceiptQA_test --n 25 --seed 42    # reproducible
    uv run python3 -m tests.ReceiptQA_test --source Human      # filter by source
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.answer import answer_question, build_answer_agent
from src.content import SummarizeError
from src.llm import active_model_name, active_provider


REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "Test Content"
LABELS_DIR = REPO_ROOT / "test_label"
OUTPUT_DIR = REPO_ROOT / "tests"


@dataclass
class QAItem:
    receipt_id: int
    question: str
    ground_truth: Any
    source: str  # "Human" or "GPT"


def load_pool(source_filter: str | None = None) -> list[QAItem]:
    pool: list[QAItem] = []
    for label_path in sorted(LABELS_DIR.glob("*.json"), key=lambda p: int(p.stem)):
        receipt_id = int(label_path.stem)
        try:
            data = json.loads(label_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  warn: skipping malformed {label_path.name}: {e}", file=sys.stderr)
            continue
        for qa in data:
            src = qa.get("source", "")
            if source_filter and src != source_filter:
                continue
            pool.append(
                QAItem(
                    receipt_id=receipt_id,
                    question=qa["question"],
                    ground_truth=qa.get("answer"),
                    source=src,
                )
            )
    return pool


async def run_one(agent, item: QAItem) -> dict[str, Any]:
    image_path = IMAGES_DIR / f"{item.receipt_id}.jpg"
    try:
        ans = await answer_question(agent, item.question, [image_path])
        return {
            "ok": True,
            "predicted": ans.answer,
            "sources_used": ans.sources_used,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "predicted": None,
            "sources_used": [],
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }


def _fmt_answer(a: Any) -> str:
    if isinstance(a, str):
        return a
    return "```json\n" + json.dumps(a, indent=2, ensure_ascii=False) + "\n```"


def write_markdown(
    output_path: Path,
    *,
    model: str,
    provider: str,
    seed: int | None,
    source_filter: str | None,
    pool_size: int,
    receipt_count: int,
    results: list[tuple[QAItem, dict[str, Any]]],
) -> None:
    lines: list[str] = []
    lines.append("# ReceiptQA random-sample eval")
    lines.append("")
    lines.append(f"- Model: `{model}` (via {provider})")
    lines.append(f"- Timestamp: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Pool size: {pool_size} QA pairs across {receipt_count} receipts")
    lines.append(f"- Sample size: {len(results)}")
    lines.append(f"- Seed: {seed if seed is not None else 'random'}")
    if source_filter:
        lines.append(f"- Source filter: {source_filter}")
    lines.append("")

    ok_count = sum(1 for _, r in results if r["ok"])
    lines.append(f"**{ok_count}/{len(results)} completed without error.**")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, (item, r) in enumerate(results, 1):
        lines.append(f"## {i}. Receipt {item.receipt_id} — source: {item.source}")
        lines.append("")
        lines.append(f"**Receipt:** [{item.receipt_id}.jpg](../Test%20Content/{item.receipt_id}.jpg)")
        lines.append("")
        lines.append(f"**Q:** {item.question}")
        lines.append("")
        lines.append("**Ground truth:**")
        lines.append("")
        lines.append(_fmt_answer(item.ground_truth))
        lines.append("")
        if r["ok"]:
            lines.append("**Predicted:**")
            lines.append("")
            lines.append(_fmt_answer(r["predicted"]))
            lines.append("")
            lines.append(f"**sources_used:** `{r['sources_used']}`")
        else:
            lines.append(f"**ERROR:** `{r['error']}`")
            lines.append("")
            lines.append("```")
            lines.append(r.get("traceback", ""))
            lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    load_dotenv()
    provider = active_provider().name
    model = active_model_name()

    pool = load_pool(source_filter=args.source)
    if not pool:
        print("error: empty QA pool (check test_label/ and --source)", file=sys.stderr)
        return 1

    receipt_count = len(list(LABELS_DIR.glob("*.json")))

    if args.seed is not None:
        random.seed(args.seed)
    n = min(args.n, len(pool))
    picks = random.sample(pool, n)

    print(f"Loaded {len(pool)} QA pairs across {receipt_count} receipts; sampling {n}.")
    print(f"Model: {model} (via {provider})")

    agent = build_answer_agent()
    results: list[tuple[QAItem, dict[str, Any]]] = []
    for i, item in enumerate(picks, 1):
        preview = item.question[:60] + ("…" if len(item.question) > 60 else "")
        print(f"  [{i}/{n}] receipt {item.receipt_id} ({item.source}): {preview}")
        r = await run_one(agent, item)
        results.append((item, r))
        if not r["ok"]:
            print(f"    ERROR: {r['error']}")

    safe_model = model.replace("/", "_").replace(":", "_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"receiptqa_{safe_model}_{ts}.md"
    write_markdown(
        output_path,
        model=model,
        provider=provider,
        seed=args.seed,
        source_filter=args.source,
        pool_size=len(pool),
        receipt_count=receipt_count,
        results=results,
    )
    print(f"\nWrote {output_path.relative_to(REPO_ROOT)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10, help="Number of QA pairs to sample (default 10).")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    parser.add_argument(
        "--source",
        choices=["Human", "GPT"],
        default=None,
        help="Only sample from this source subset.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
