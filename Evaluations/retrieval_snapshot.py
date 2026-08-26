"""Retrieval snapshot: product-config search for every eval question,
top-12 paths + scores + margin recorded. No LLM, deterministic, ~2 min.

Run BEFORE and AFTER an index change; diff the two files to judge a
retrieval experiment without any answer-stage noise.

Usage (repo root):
    uv run python Evaluations/retrieval_snapshot.py \
        --questions Evaluations/college_data/eval_college_data_40.json \
        --out Evaluations/college_data/retrieval_snapshot__baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    import os

    os.environ["MAGPIE_FORCE_PROVIDER"] = "local"

    from src.stage2.search import SearchQuery, run_search

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    out = []
    for q in questions:
        res = run_search(SearchQuery(query=q["question"], keywords=[]), 5,
                         question=q["question"], skip_fast=True, rerank=True)
        margin = (res[0].score - res[1].score) if len(res) >= 2 else None
        out.append({
            "id": q["id"],
            "question": q["question"],
            "key_files": q.get("key_files", []),
            "margin_top1": margin,
            "retrieved": [{"path": r.path, "score": round(r.score, 4)}
                          for r in res[:12]],
        })
        print(f"{q['id']}: {len(res)} results, margin "
              f"{margin if margin is None else round(margin, 3)}", flush=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
