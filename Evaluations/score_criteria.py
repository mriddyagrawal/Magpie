"""Score an answers file against pre-registered regex criteria.

The eval judge in `Evaluations/README.md` step 3 is the assistant, which is
also the party that authored the ground truths — a caveat REPORT.md has
carried since the first run. For a question set whose answers are figures,
dates, course codes and reference numbers, that judgment call can be moved
into a file written before any arm runs: a list of regexes per question that
a correct answer must (or must not) contain.

Strict binary per house rule 1 — every required group has to match, or the
question is wrong. Partial credit is not represented on purpose.

    uv run python Evaluations/score_criteria.py \\
        --criteria Evaluations/sem6/criteria.json \\
        Evaluations/sem6/eval_answer_sem6__*.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _normalize(text: str) -> str:
    """Strip thousands separators so '1,183.87' matches a criterion written
    as '1183\\.87', and flatten whitespace so line wrapping never decides a
    verdict."""
    return re.sub(r"\s+", " ", re.sub(r"(?<=\d),(?=\d)", "", text))


def grade(answer: str, rule: dict) -> tuple[bool, str]:
    """Returns (correct, reason-if-wrong)."""
    text = _normalize(answer or "")

    if rule.get("not_found"):
        # The pipeline clears `answer` when the not-found contract fires, so
        # an empty answer IS the pass condition here.
        if text.strip():
            return False, "answered instead of declaring not-found"
        return True, ""

    if not text.strip():
        # `not_found_ok` marks a question whose ground truth accepts EITHER a
        # careful answer or an honest refusal — the mangled-salary probe is
        # the case: the figure is unreadable in the source, so "I can't read
        # it" and "not found" are both right. Without this the scorer
        # punishes exactly the behaviour the question was written to reward.
        return bool(rule.get("not_found_ok")), "empty answer"

    for pat in rule.get("all", []):
        if not re.search(pat, text, re.IGNORECASE):
            return False, f"missing {pat!r}"

    # Any number of `any` groups: any, any2, any3, ... Each group is a list of
    # alternatives and at least one alternative in EVERY group must match. A
    # fixed three used to be the limit, which silently capped how many
    # independent parts a criterion could require.
    for key in sorted(k for k in rule if re.fullmatch(r"any\d*", k)):
        for group in rule.get(key, []):
            if not any(re.search(p, text, re.IGNORECASE) for p in group):
                return False, f"none of {group!r}"

    for pat in rule.get("none", []):
        if re.search(pat, text, re.IGNORECASE):
            return False, f"contains forbidden {pat!r}"

    return True, ""


def score_file(path: Path, criteria: dict) -> dict:
    entries = json.loads(path.read_text(encoding="utf-8"))
    verdicts = {}
    for e in entries:
        qid = e.get("id")
        rule = criteria.get(qid)
        if rule is None:
            continue
        if e.get("error"):
            verdicts[qid] = (False, f"harness error: {e['error'][:60]}")
            continue
        answer = e.get("magpie_answer") or ""
        if not isinstance(answer, str):
            answer = str(answer)
        verdicts[qid] = grade(answer, rule)
    correct = sum(1 for ok, _ in verdicts.values() if ok)
    return {
        "file": path.name,
        "scored": len(verdicts),
        "correct": correct,
        "verdicts": verdicts,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--criteria", required=True, type=Path)
    p.add_argument("--detail", action="store_true", help="print per-question verdicts")
    p.add_argument("answers", nargs="+", type=Path)
    args = p.parse_args()

    criteria = {
        k: v for k, v in json.loads(args.criteria.read_text(encoding="utf-8")).items()
        if not k.startswith("_")
    }

    reports = [score_file(a, criteria) for a in args.answers]
    width = max(len(r["file"]) for r in reports)
    print(f"{'run':<{width}}  strict")
    for r in reports:
        print(f"{r['file']:<{width}}  {r['correct']}/{r['scored']}")

    if args.detail:
        qids = sorted(criteria)
        print("\n" + " " * 6 + "".join(f"{r['file'][-18:]:>20}" for r in reports))
        for qid in qids:
            row = "".join(
                f"{('OK' if r['verdicts'].get(qid, (False, ''))[0] else '.'):>20}"
                for r in reports
            )
            print(f"{qid:<6}{row}")
        for r in reports:
            print(f"\n--- {r['file']} misses ---")
            for qid in qids:
                ok, why = r["verdicts"].get(qid, (False, "not run"))
                if not ok:
                    print(f"  {qid}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
