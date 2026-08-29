"""Append one provenance record per evaluation arm to `Evaluations/RUNLOG.jsonl`.

An answers file says what the model replied. It does not say which commit
produced it, which corpus it searched, what the solo gate was set to, or
whether the working tree was dirty at the time. Without those, two runs that
disagree cannot be told apart from two runs that were never comparable — a
problem this project has already hit (a leaked Qdrant endpoint made two arms
search the wrong corpus, and a pinned temperature silently differed between
sem_4 and sem6).

This records all of it in one place, computed from artifacts rather than
memory: git state, resolved config, index size, strict score against the
pre-registered criteria, retrieval recall/rank-1, and the latency
distribution including per-stage timings when the answers file carries them.

    uv run python Evaluations/runlog.py \
        --dataset phyll \
        --answers  Evaluations/phyll/eval_answer_phyll__t01.json \
        --criteria Evaluations/phyll/criteria.json \
        --note "profile temperature (0.1), summary tier only"
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

LEDGER = REPO_ROOT / "Evaluations" / "RUNLOG.jsonl"

# Env knobs that change what a run measures. Recorded verbatim (None if unset)
# so a later reader can tell whether two arms were actually comparable.
TRACKED_ENV = [
    "MAGPIE_DATA_DIR", "QDRANT_CLUSTER_ENDPOINT", "LLM_PROVIDER",
    "LOCAL_SOLO_KEEP", "LOCAL_MIN_P", "LOCAL_REPEAT_PENALTY",
    "MAGPIE_RERANK_FUSE", "MAGPIE_MULTIPART", "MAGPIE_SUMMARY_WHEN_THIN",
    "MAGPIE_HYPE_WEIGHT", "MAGPIE_FORCE_PROVIDER",
]


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT,
                              capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except Exception:  # noqa: BLE001 — provenance must never block a run
        return ""


def _index_stats() -> dict:
    """Manifest rows, summary files on disk, and live Qdrant point count."""
    stats: dict = {}
    data_dir = os.environ.get("MAGPIE_DATA_DIR", "").strip()
    if data_dir:
        d = Path(data_dir)
        try:
            stats["manifest_rows"] = len(json.loads((d / "manifest.json").read_text()))
        except Exception:  # noqa: BLE001
            stats["manifest_rows"] = None
        try:
            stats["summary_files"] = len(list((d / "summaries").glob("*.md")))
        except Exception:  # noqa: BLE001
            stats["summary_files"] = None
    endpoint = os.environ.get("QDRANT_CLUSTER_ENDPOINT", "http://127.0.0.1:6433")
    try:
        import urllib.request
        with urllib.request.urlopen(f"{endpoint}/collections/summaries", timeout=5) as r:
            stats["qdrant_points"] = json.load(r)["result"]["points_count"]
    except Exception:  # noqa: BLE001
        stats["qdrant_points"] = None
    return stats


def _retrieval_stats(answers: list[dict], questions: dict) -> dict:
    """Recall and rank-1 against each question's declared `key_files`."""
    n = recall = rank1 = 0
    for a in answers:
        q = questions.get(a["id"]) or {}
        keys = [k.rstrip("/") for k in q.get("key_files", []) if not k.endswith("/")]
        if not keys:
            continue
        n += 1
        got = [(r.get("path") if isinstance(r, dict) else r) or ""
               for r in (a.get("magpie_retrieved") or [])]
        if any(any(k in g for k in keys) for g in got):
            recall += 1
        if got and any(k in got[0] for k in keys):
            rank1 += 1
    return {"scored": n, "recall": recall, "rank1": rank1}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True)
    p.add_argument("--answers", required=True, type=Path)
    p.add_argument("--criteria", type=Path, default=None)
    p.add_argument("--note", default="")
    args = p.parse_args()

    # accept relative or absolute paths for the answers file
    args.answers = args.answers if args.answers.is_absolute() else (REPO_ROOT / args.answers)
    if args.criteria and not args.criteria.is_absolute():
        args.criteria = REPO_ROOT / args.criteria
    answers = json.loads(args.answers.read_text())

    questions: dict = {}
    qpath = args.answers.parent / f"eval_{args.dataset}.json"
    if qpath.exists():
        questions = {q["id"]: q for q in json.loads(qpath.read_text())}

    strict = None
    wrong: list[str] = []
    if args.criteria and args.criteria.exists():
        from Evaluations.score_criteria import grade
        rules = json.loads(args.criteria.read_text())
        ok = 0
        for a in answers:
            rule = rules.get(a["id"])
            if rule is None:
                continue
            passed, _ = grade(a.get("magpie_answer") or "", rule)
            ok += passed
            if not passed:
                wrong.append(a["id"])
        strict = f"{ok}/{len([a for a in answers if a['id'] in rules])}"

    lat = sorted(a["latency_seconds"] for a in answers if a.get("latency_seconds"))
    stages: dict[str, float] = {}
    for key in ("retrieval", "answer", "rewrite", "files_read"):
        vals = [a["stage_timings"][key] for a in answers
                if isinstance(a.get("stage_timings"), dict) and key in a["stage_timings"]]
        if vals:
            stages[f"median_{key}"] = round(statistics.median(vals), 2)

    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": args.dataset,
        "answers_file": str(args.answers.relative_to(REPO_ROOT)),
        "note": args.note,
        "git": {
            "sha": _git("rev-parse", "--short", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": len([l for l in _git("status", "--porcelain").splitlines() if l]),
        },
        "env": {k: os.environ.get(k) for k in TRACKED_ENV},
        "index": _index_stats(),
        "providers": sorted({a.get("provider") for a in answers if a.get("provider")}),
        "n_questions": len(answers),
        "errors": sum(1 for a in answers if a.get("error")),
        "strict": strict,
        "wrong_ids": wrong,
        "retrieval": _retrieval_stats(answers, questions) if questions else None,
        "latency": {
            "median": round(statistics.median(lat), 2) if lat else None,
            "mean": round(statistics.mean(lat), 2) if lat else None,
            "p90": round(lat[int(0.9 * len(lat)) - 1], 2) if lat else None,
            "max": round(lat[-1], 2) if lat else None,
            "under_10s": f"{sum(1 for x in lat if x <= 10)}/{len(lat)}" if lat else None,
        },
        "stage_medians": stages or None,
    }

    with LEDGER.open("a") as fh:
        fh.write(json.dumps(record) + "\n")

    print(f"logged -> {LEDGER.relative_to(REPO_ROOT)}")
    print(f"  {args.dataset}  strict={strict}  errors={record['errors']}")
    if record["retrieval"]:
        r = record["retrieval"]
        print(f"  retrieval: recall {r['recall']}/{r['scored']}  rank1 {r['rank1']}/{r['scored']}")
    print(f"  latency: median {record['latency']['median']}s  "
          f"p90 {record['latency']['p90']}s  under-10s {record['latency']['under_10s']}")
    if stages:
        print(f"  stages: {stages}")
    if record["git"]["dirty_files"]:
        print(f"  NOTE: {record['git']['dirty_files']} uncommitted files at log time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
