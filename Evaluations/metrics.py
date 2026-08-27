"""Objective (judge-free) metrics over one or more eval answer files.

Complements the LLM-judged correctness verdicts in REPORT.md with numbers
that decompose WHERE a failure happened, so tuning changes can be
attributed:

  recall@k    was any of the question's key_files in the retrieved list?
              (retrieval's fault vs the model's fault — the single most
              important split for tuning)
  MRR         mean reciprocal rank of the first key_file in the retrieved
              list (1.0 = always ranked #1; 0 = never found)
  cited@ans   did the model's sources_used include a key_file? (grounding:
              the model not only saw the right file, it used it)
  answered    non-empty answer rate (plumbing, not quality)
  latency     avg / median / max seconds

Usage:
    python Evaluations/metrics.py --questions Evaluations/<ds>/eval_<ds>.json \
        Evaluations/<ds>/eval_answer_<ds>__local.json [more answer files...]

Path matching: key_files are corpus-relative ("supplements/x.docx");
retrieved/cited paths are absolute. A key file counts as matched when its
normalized path is a suffix of the normalized candidate path
(case-insensitive, separator-insensitive) — robust to corpus roots and
Windows/Unix separators.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def _norm(p: str) -> str:
    return p.replace("\\", "/").strip().lower()


def _matches(key_file: str, candidate: str) -> bool:
    k, c = _norm(key_file), _norm(candidate)
    return c.endswith(k) or c.endswith("/" + k.split("/")[-1]) and k.split("/")[-1] in c


def _first_key_rank(key_files: list[str], retrieved: list[str]) -> int | None:
    for i, path in enumerate(retrieved, 1):
        if any(_matches(k, path) for k in key_files):
            return i
    return None


def score_run(questions: list[dict], answers: list[dict]) -> dict:
    by_id = {q["id"]: q for q in questions}
    n = 0
    hits = 0
    rr_sum = 0.0
    cited = 0
    answered = 0
    lats: list[float] = []
    per_q: list[dict] = []
    for a in answers:
        q = by_id.get(a["id"])
        if q is None:
            continue
        n += 1
        lats.append(float(a.get("latency_seconds", 0)))
        has_answer = bool(a.get("magpie_answer"))
        answered += has_answer
        retrieved = [r["path"] for r in a.get("magpie_retrieved", [])]
        rank = _first_key_rank(q["key_files"], retrieved)
        if rank is not None:
            hits += 1
            rr_sum += 1.0 / rank
        used = a.get("magpie_sources_used") or []
        was_cited = any(
            _matches(k, u) for k in q["key_files"] for u in used
        )
        cited += was_cited
        per_q.append({
            "id": a["id"],
            "retrieved_rank_of_key_file": rank,
            "key_file_cited": was_cited,
            "answered": has_answer,
            "latency_s": round(lats[-1], 1),
        })
    return {
        "n": n,
        "recall_at_k": round(hits / n, 3) if n else 0,
        "mrr": round(rr_sum / n, 3) if n else 0,
        "cited_rate": round(cited / n, 3) if n else 0,
        "answered_rate": round(answered / n, 3) if n else 0,
        "latency_avg_s": round(sum(lats) / n, 1) if n else 0,
        "latency_median_s": round(statistics.median(lats), 1) if lats else 0,
        "latency_max_s": round(max(lats), 1) if lats else 0,
        "per_question": per_q,
    }


def extra_diagnostics(questions: list[dict], answers: list[dict]) -> dict:
    """The 'wild' layer: calibration and behavior stats, still judge-free.

    refusal calibration — a refusal (empty answer) is GOOD on data_absence
    questions and BAD elsewhere; report both directions.
    wrong-source pull — answers whose cited sources contain NO key file
    even though retrieval DID deliver one: the model was handed the right
    file and read a different one (the distractor-pull failure local
    shows). Fabrication risk correlates with this.
    verbosity — answer length percentiles; degenerate outputs (<20 chars)
    flagged: grammar/looping failures produce fragments like '{' or 'yes'.
    """
    by_id = {q["id"]: q for q in questions}
    absence_ids = {
        q["id"] for q in questions if "data_absence" in q.get("reasoning_type", [])
    }
    good_refusals = bad_refusals = 0
    wrong_source_pull = 0
    degenerate = []
    lengths = []
    by_difficulty: dict[str, list[str]] = {}
    for a in answers:
        q = by_id.get(a["id"])
        if q is None:
            continue
        ans = a.get("magpie_answer") or ""
        lengths.append(len(ans))
        refused = not ans
        if refused:
            if a["id"] in absence_ids:
                good_refusals += 1
            else:
                bad_refusals += 1
        elif len(ans) < 20:
            degenerate.append(a["id"])
        retrieved = [r["path"] for r in a.get("magpie_retrieved", [])]
        delivered = any(
            _matches(k, p) for k in q["key_files"] for p in retrieved
        )
        used = a.get("magpie_sources_used") or []
        used_key = any(_matches(k, u) for k in q["key_files"] for u in used)
        if not refused and delivered and used and not used_key:
            wrong_source_pull += 1
        by_difficulty.setdefault(q["difficulty"], []).append(
            a.get("correctness", "?")
        )
    diff_summary = {
        d: {v: vs.count(v) for v in set(vs)} for d, vs in sorted(by_difficulty.items())
    }
    lengths.sort()
    return {
        "good_refusals(absence)": good_refusals,
        "bad_refusals(info existed)": bad_refusals,
        "wrong_source_pull(right file delivered, wrong file cited)": wrong_source_pull,
        "degenerate_outputs(<20 chars)": degenerate,
        "answer_len_median": lengths[len(lengths) // 2] if lengths else 0,
        "by_difficulty": diff_summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("answers", nargs="+", type=Path)
    ap.add_argument("--per-question", action="store_true",
                    help="Also print the per-question breakdown")
    ap.add_argument("--diagnostics", action="store_true",
                    help="Also print refusal calibration, wrong-source pull, "
                         "degenerate outputs, and per-difficulty verdicts")
    args = ap.parse_args()

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    for ans_path in args.answers:
        answers = json.loads(ans_path.read_text(encoding="utf-8"))
        s = score_run(questions, answers)
        print(f"\n=== {ans_path.name} (n={s['n']}) ===")
        print(f"  recall@k     {s['recall_at_k']:.0%}   (key file reached the answer stage)")
        print(f"  MRR          {s['mrr']:.3f}  (1.0 = key file always ranked #1)")
        print(f"  cited rate   {s['cited_rate']:.0%}   (model actually used a key file)")
        print(f"  answered     {s['answered_rate']:.0%}")
        print(f"  latency      avg {s['latency_avg_s']}s · median {s['latency_median_s']}s · max {s['latency_max_s']}s")
        if args.per_question:
            for row in s["per_question"]:
                print(f"    {row['id']}: rank={row['retrieved_rank_of_key_file']} "
                      f"cited={row['key_file_cited']} answered={row['answered']} "
                      f"{row['latency_s']}s")
        if args.diagnostics:
            d = extra_diagnostics(questions, answers)
            for k, v in d.items():
                print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
