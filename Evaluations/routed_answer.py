"""Routed answering spike for the LOCAL model (2026-08-26).

Three lanes, decided per question BEFORE answering:

1. BREADTH-shaped (answer plausibly scattered across several documents:
   enumerations, cross-corpus sweeps, version/inconsistency questions)
   -> map-reduce answering with temperature-0 maps.
2. Everything else -> the shipped product path unchanged (which itself
   solo-gates when the retrieval margin >= 2, applies SYNTHESIS MODE to
   comparative questions, and otherwise reads the top-5 stack).

Comparative DEPTH questions (compare/versus/connects/same-file) stay in
the product lane deliberately: mr10 showed q08 ("what connects my
essays") is won by the normal path and lost by map-reduce. Map-reduce is
reserved for BREADTH, where the mr10 evidence (q07, and zero baseline
wins in the lane on the 40-set) says it can only add.

Paired design: product-lane questions are copied verbatim from the
baseline answers file (same system, same inputs — re-running would only
re-roll sampling noise), so the routed scorecard differs from baseline
ONLY on the breadth lane. Pre-registered gate: routed >= 17/40 strict
(baseline 14/40 + 3).

Usage (repo root):
    uv run python Evaluations/routed_answer.py \
        --questions Evaluations/college_data/eval_college_data_40.json \
        --baseline  Evaluations/college_data/eval_answer_40__local.json \
        --answers   Evaluations/college_data/eval_answer_40__routed.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

# Breadth signals only — phrasing that implies the answer is assembled
# from SEVERAL documents. Registered before the routed run; comparative
# depth phrasing (compare/versus/connects) is intentionally absent.
BREADTH_Q_RE = re.compile(
    r"(\bacross (my|all|the)\b"
    r"|\bwhich of my (documents|files|essays|forms)\b"
    r"|\bdo i have\b"
    r"|\baccording to my (documents|files)\b"
    r"|\bseveral of my\b"
    r"|inconsisten"
    r"|\bconflicting\b"
    r"|\b(different|two) versions\b"
    r"|\blist (all|every)\b"
    r"|\b(all|every) (of )?(my|the) (documents|files|essays|forms|letters)\b)",
    re.IGNORECASE,
)


def route_for(question: str) -> str:
    return "mapreduce" if BREADTH_Q_RE.search(question) else "product"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--baseline", required=True, type=Path,
                    help="Judged baseline answers file; product-lane "
                         "entries are copied from here.")
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the lane per question and exit.")
    args = ap.parse_args()

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    if args.dry_run:
        for q in questions:
            print(f"{q['id']}: {route_for(q['question']):9s} "
                  f"{q['question'][:70]}")
        n = sum(route_for(q["question"]) == "mapreduce" for q in questions)
        print(f"\n{n}/{len(questions)} routed to map-reduce")
        return 0

    import os

    os.environ["MAGPIE_FORCE_PROVIDER"] = "local"

    from Evaluations.mapreduce_answer import answer_one
    from src.inference.local_llm import get_local_llm

    baseline = {e["id"]: e
                for e in json.loads(args.baseline.read_text(encoding="utf-8"))}
    done: list[dict] = []
    if args.answers.exists():
        done = json.loads(args.answers.read_text(encoding="utf-8"))
    done_ids = {d["id"] for d in done}

    llm = None
    for i, q in enumerate(questions, 1):
        if q["id"] in done_ids:
            continue
        lane = route_for(q["question"])
        print(f"[{i}/{len(questions)}] {q['id']} -> {lane}: "
              f"{q['question'][:70]}", flush=True)
        if lane == "product":
            entry = dict(baseline[q["id"]])
            entry["route"] = "product (copied from baseline)"
        else:
            if llm is None:
                llm = get_local_llm()
            entry = {"id": q["id"], "question": q["question"],
                     "ground_truth": q.get("ground_truth", ""),
                     "provider": "local-routed", "route": "mapreduce"}
            try:
                # map_k=99: map EVERY file run_search returned (12 for
                # list_all-class questions) — v1's top-5 slice measurably
                # discarded enumeration answers at ranks 6-12.
                entry.update(answer_one(llm, q["question"],
                                        temperature=0.0, map_k=99))
            except Exception as e:  # noqa: BLE001
                entry["error"] = f"{type(e).__name__}: {e}"
        done.append(entry)
        args.answers.write_text(
            json.dumps(done, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
