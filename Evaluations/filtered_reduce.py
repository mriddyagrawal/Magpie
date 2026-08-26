"""Two-stage reduce (routed v4, 2026-08-26): v3's mechanical assembly
(deduped, attributed, NOT_HERE-free) fed to ONE small temp-0 LLM call
that only FILTERS and PHRASES.

Hypothesis under test: the 3B failed v2's reduce because the input was
raw sprawling findings; give it clean structure ~10x smaller and it can
drop off-topic items without dropping answers. v3 proved the facts
survive assembly; v4 tests whether filtering survives the 3B.

Zero new maps: reads the mechanical answers from routed3, writes
routed4. Pre-registered gate: composed >= 17/40 strict.

Usage (repo root):
    uv run python Evaluations/filtered_reduce.py \
        --v3 Evaluations/college_data/eval_answer_40__routed3.json \
        --answers Evaluations/college_data/eval_answer_40__routed4.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

FILTER_PROMPT = """QUESTION: {question}

Below are facts collected from the user's documents, grouped by source
file. Some facts answer the question; many are about other topics.

FACTS:
{assembly}

Write the final answer to the QUESTION using ONLY facts from the list
that directly answer it. Rules:
- Ignore facts about other topics, other people, or other organizations,
  even when they sit next to relevant ones.
- If the question asks which/what/who, list EVERY item the facts
  support, each with its source file. Do not drop supported items.
- If facts conflict, present all conflicting versions with their files.
- Copy names, numbers, and dates exactly. Never invent or merge items.
- If nothing in the list answers the question, reply NOT_FOUND.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--v3", required=True, type=Path)
    ap.add_argument("--answers", required=True, type=Path)
    args = ap.parse_args()

    import os

    os.environ["MAGPIE_FORCE_PROVIDER"] = "local"

    from src.inference.local_llm import get_local_llm

    data = json.loads(args.v3.read_text(encoding="utf-8"))
    done = []
    if args.answers.exists():
        done = json.loads(args.answers.read_text(encoding="utf-8"))
    done_ids = {d["id"] for d in done}

    llm = None
    for e in data:
        if e["id"] in done_ids:
            continue
        e = dict(e)
        if e.get("route") == "mapreduce-mechanical":
            assembly = e.get("magpie_answer", "")
            e["route"] = "mapreduce-filtered"
            e["provider"] = "local-routed-v4"
            e["assembly"] = assembly
            e.pop("correctness", None)
            e.pop("correctness_notes", None)
            if llm is None:
                llm = get_local_llm()
            print(f"filtering {e['id']}: {e['question'][:60]}", flush=True)
            t0 = time.time()
            try:
                final = llm.complete_sync(
                    [{"role": "user", "content": FILTER_PROMPT.format(
                        question=e["question"], assembly=assembly)}],
                    temperature=0.0, max_tokens=400,
                ).strip()
                e["magpie_answer"] = (
                    "" if final.upper().startswith("NOT_FOUND") else final)
            except Exception as ex:  # noqa: BLE001
                e["error"] = f"{type(ex).__name__}: {ex}"
            e["latency_seconds"] = round(time.time() - t0, 2)
        done.append(e)
        args.answers.write_text(
            json.dumps(done, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
