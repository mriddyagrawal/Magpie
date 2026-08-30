"""Pass/fail gate for `just eval-smoke` - a tripwire, not a benchmark.

Reads a finished smoke run and asserts LOOSE floors. Ordinary code changes
move scores a few points and sail through; this exists to catch the
catastrophic class (unindexable corpus, empty index, 100% abstention,
retrieval collapse, majority infra errors). When a deliberate change
legitimately moves a floor, re-baseline HERE in the same commit and say why.

Usage: python eval_harness/scripts/smoke_check.py <run_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FLOORS = {
    # calibrated 2026-08-30 on the frozen 10-question smoke fixture
    "max_infra_errors": 2,        # of 10
    "min_hit_at_3": 0.5,          # pre-gate retrieval, answerable questions
    "max_abstention": 0.9,        # 100% abstention = guard/pipeline broken
    "min_answered_nonempty": 3,   # of 9 answerable
}


def fail(msg: str) -> None:
    print(f"SMOKE FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    run_dir = Path(sys.argv[1])
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

    if run.get("status") != "complete":
        fail(f"status={run.get('status')!r}")
    iso = run.get("isolation", {})
    if not (iso.get("real_appdata_untouched") and iso.get("cache_model_blobs_unchanged")):
        fail(f"isolation violated: {iso}")

    n = metrics.get("n_questions", 0)
    errors = metrics.get("errors", 99)
    if errors > FLOORS["max_infra_errors"]:
        fail(f"{errors}/{n} infra errors (floor {FLOORS['max_infra_errors']})")

    hit3 = (metrics.get("retrieval") or {}).get("hit@3")
    if hit3 is None or hit3 < FLOORS["min_hit_at_3"]:
        fail(f"retrieval hit@3={hit3} (floor {FLOORS['min_hit_at_3']}) - "
             "retrieval collapsed or index is empty")

    rows = json.loads((run_dir / "answers_enriched.json").read_text(encoding="utf-8"))
    answerable = [r for r in rows if r.get("answer_type") != "not_found"]
    abstained = sum(1 for r in rows if r.get("abstained"))
    if rows and abstained / len(rows) > FLOORS["max_abstention"]:
        fail(f"{abstained}/{len(rows)} abstained (floor {FLOORS['max_abstention']:.0%})")
    nonempty = sum(1 for r in answerable if (r.get("magpie_answer") or "").strip())
    if nonempty < FLOORS["min_answered_nonempty"]:
        fail(f"only {nonempty}/{len(answerable)} answerable questions produced "
             f"an answer (floor {FLOORS['min_answered_nonempty']})")

    correct_floor_note = (metrics.get("answer") or {}).get("correct")
    print(f"SMOKE OK: {n} questions, errors={errors}, hit@3={hit3}, "
          f"abstained={abstained}/{len(rows)}, nonempty={nonempty}, "
          f"deterministic-correct={correct_floor_note} "
          f"(informational, no floor)")


if __name__ == "__main__":
    main()
