"""Question-sandwich reduce (routed v5, 2026-08-26) — owner's
hypothesis: the reduce fails because the question sits only at the TOP
of the prompt and is "forgotten" by the time the model has read the
facts. One variable vs v4: the question (and the answer instruction) is
REPEATED at the BOTTOM, immediately before generation. Everything else
identical to v4 (v3 assemblies in, one temp-0 call, max_tokens 400).

Usage (repo root):
    uv run python Evaluations/sandwich_reduce.py \
        --v3 Evaluations/college_data/eval_answer_40__routed3.json \
        --answers Evaluations/college_data/eval_answer_40__routed5.json
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

SANDWICH_PROMPT = """QUESTION: {question}

Below are facts collected from the user's documents, grouped by source
file. Some facts answer the question; many are about other topics.

FACTS:
{assembly}

Now answer this QUESTION: {question}

Rules:
- Use ONLY facts from the list above that directly answer this question.
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
            e["route"] = "mapreduce-sandwich"
            e["provider"] = "local-routed-v5"
            e["assembly"] = assembly
            e.pop("correctness", None)
            e.pop("correctness_notes", None)
            if llm is None:
                llm = get_local_llm()
            print(f"sandwiching {e['id']}: {e['question'][:60]}", flush=True)
            t0 = time.time()
            try:
                final = llm.complete_sync(
                    [{"role": "user", "content": SANDWICH_PROMPT.format(
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
