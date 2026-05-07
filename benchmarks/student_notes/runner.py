"""Re-run the student_notes eval against the current Magpie index.

Same script shape as run_all_evals.py but scoped to one eval file and
writes its output into a benchmarks subfolder (so we can compare runs
across different document representations of the same content).

Usage:
    LLM_PROVIDER=local LLAMA_SERVER_STARTUP_TIMEOUT_S=180 \\
        uv run python ".../benchmarks/run_student_notes_only.py" \\
        --out-dir ".../benchmarks/run2_handwritten_font"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/mriddy/Documents/GitHub/NotAnotherSpotlight")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from src.pipeline import ask_sync  # noqa: E402

EVAL_PATH = Path("/Users/mriddy/Desktop/Magpie testing/eval_student_notes.json")


def load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def run_one(q: dict) -> dict:
    qid = q["id"]
    qtext = q["question"]
    expert_gt = q.get("expert_ground_truth", q.get("ground_truth", ""))
    t0 = time.time()
    try:
        r = ask_sync(qtext, top_k=5, rewrite=True)
        return {
            "id": qid,
            "question": qtext,
            "expert_ground_truth": expert_gt,
            "magpie_answer": r.answer,
            "magpie_sources_used": r.sources_used,
            "magpie_retrieved": [
                {"path": x.path, "score": x.score} for x in r.retrieved
            ],
            "latency_seconds": round(time.time() - t0, 2),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "id": qid,
            "question": qtext,
            "expert_ground_truth": expert_gt,
            "error": f"{type(e).__name__}: {e}",
            "latency_seconds": round(time.time() - t0, 2),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / "eval_answer_student_notes.json"

    questions = json.loads(EVAL_PATH.read_text())
    results = load_existing(out_path)
    done_ids = {r["id"] for r in results}

    print(
        f"Plan: {len(questions)} questions; "
        f"{len(done_ids)} already done, {len(questions) - len(done_ids)} to do.",
        flush=True,
    )
    print(f"Output: {out_path}", flush=True)

    overall_start = time.time()
    for i, q in enumerate(questions, 1):
        if q["id"] in done_ids:
            continue
        elapsed = time.time() - overall_start
        print(
            f"[{i}/{len(questions)}] ({elapsed/60:.1f}min) "
            f"{q['id']}: {q['question'][:80]}",
            flush=True,
        )
        entry = run_one(q)
        results.append(entry)
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    print(f"\nDone in {(time.time()-overall_start)/60:.1f} min. "
          f"{len(results)} entries → {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
