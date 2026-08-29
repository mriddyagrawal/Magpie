"""Split the blame between retrieval and reading, per question.

Every answers file records what was retrieved (`magpie_retrieved`, in rank
order) alongside the question's `key_files`. That is enough to say, for each
question, whether the file holding the answer ever reached the model — and
therefore whether a wrong answer is retrieval's fault or the reader's.

Three numbers per run:

  recall@k     the key file was somewhere in the retrieved set
  rank-1       the key file was the TOP hit (what the solo gate keys off)
  reader-loss  key file retrieved, answer still wrong — the reading tax

`key_files` are corpus-relative; retrieved paths are absolute. Matching is
on the trailing path segments, so the two forms line up without either file
having to know where the corpus is mounted.

    uv run python Evaluations/retrieval_recall.py \\
        --questions Evaluations/sem6/eval_sem6.json \\
        --criteria  Evaluations/sem6/criteria.json \\
        Evaluations/sem6/eval_answer_sem6__*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Evaluations.score_criteria import grade  # noqa: E402


def _tail(path: str, n: int = 3) -> str:
    """Last n path segments, lowercased, forward-slashed. Enough to identify
    a file without agreeing on where the corpus lives."""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p]
    return "/".join(parts[-n:]).lower()


def _matches(key_file: str, retrieved_path: str) -> bool:
    key = _tail(key_file, 3)
    hit = _tail(retrieved_path.split("#", 1)[0], 6)
    return key in hit or _tail(key_file, 1) == _tail(retrieved_path, 1)


def analyse(answers: list[dict], questions: dict, criteria: dict) -> dict:
    rows = []
    for e in answers:
        qid = e.get("id")
        q = questions.get(qid) or {}
        key_files = q.get("key_files") or []
        if not key_files:
            continue  # absence probes have no key file by construction
        retrieved = [h.get("path", "") for h in (e.get("magpie_retrieved") or [])]
        ranks = []
        for kf in key_files:
            rank = next(
                (i + 1 for i, r in enumerate(retrieved) if _matches(kf, r)), None
            )
            ranks.append(rank)
        found = [r for r in ranks if r]
        rule = criteria.get(qid) or {}
        answer = e.get("magpie_answer") or ""
        correct = grade(answer if isinstance(answer, str) else str(answer), rule)[0]
        rows.append({
            "id": qid,
            "recalled": len(found) == len(key_files),
            "any_recalled": bool(found),
            "best_rank": min(found) if found else None,
            "correct": correct,
        })
    n = len(rows)
    recalled = [r for r in rows if r["recalled"]]
    rank1 = [r for r in rows if r["best_rank"] == 1]
    reader_loss = [r for r in recalled if not r["correct"]]
    retrieval_loss = [r for r in rows if not r["recalled"] and not r["correct"]]
    return {
        "n": n,
        "recall": len(recalled),
        "rank1": len(rank1),
        "reader_loss": len(reader_loss),
        "retrieval_loss": len(retrieval_loss),
        "reader_loss_ids": [r["id"] for r in reader_loss],
        "retrieval_loss_ids": [r["id"] for r in retrieval_loss],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--questions", required=True, type=Path)
    p.add_argument("--criteria", required=True, type=Path)
    p.add_argument("answers", nargs="+", type=Path)
    args = p.parse_args()

    questions = {
        q["id"]: q for q in json.loads(args.questions.read_text(encoding="utf-8"))
    }
    criteria = {
        k: v
        for k, v in json.loads(args.criteria.read_text(encoding="utf-8")).items()
        if not k.startswith("_")
    }

    print(f"{'run':<40} {'n':>3} {'recall':>7} {'rank1':>6} {'reader':>7} {'retr':>5}")
    reports = []
    for a in args.answers:
        r = analyse(json.loads(a.read_text(encoding="utf-8")), questions, criteria)
        reports.append((a.name, r))
        print(
            f"{a.name:<40} {r['n']:>3} {r['recall']:>7} {r['rank1']:>6} "
            f"{r['reader_loss']:>7} {r['retrieval_loss']:>5}"
        )

    for name, r in reports:
        print(f"\n--- {name} ---")
        print(f"  lost in the READER (file retrieved, answer wrong): {', '.join(r['reader_loss_ids']) or 'none'}")
        print(f"  lost in RETRIEVAL (key file never reached the model): {', '.join(r['retrieval_loss_ids']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
