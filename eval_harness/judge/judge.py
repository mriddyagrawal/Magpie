"""Offline judge pass (PLAN §7 Phase 3) — separate from the runner by design.

Reads a finished run's artifacts, grades answers against golden truth with a
pinned high-tier Claude via the local `claude` CLI (headless `-p` mode), and
writes judge_verdicts.json + a judged section appended to the report. Re-judge
any old run at any time; runner artifacts are never modified.

Scope discipline:
  - Only rows the deterministic pass could NOT settle are judged: verdicts
    `partial`/`wrong` (prose may deserve credit exact-match missed) and all
    `enumeration` rows. `correct` and abstention verdicts are already ground
    truth; re-judging them spends tokens to learn nothing.
  - Privacy (§9.4): the judge prompt carries question, gold answer, key
    facts, the model's answer, and cited file NAMES. Never document content.
  - Every verdict records judge_model + rubric sha256, and mixed-judge
    comparisons are refused downstream by that stamp.

Usage:
  uv run python eval_harness/judge/judge.py --run-dir eval_harness/runs/<id> \
      [--model claude-opus-5] [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUBRIC_PATH = HERE / "rubric.md"

JUDGE_MODEL_DEFAULT = "claude-opus-5"


def rubric_text() -> str:
    return RUBRIC_PATH.read_text(encoding="utf-8")


def rubric_sha() -> str:
    return hashlib.sha256(rubric_text().encode()).hexdigest()[:16]


def build_prompt(item: dict, row: dict) -> str:
    facts = item.get("key_facts") or []
    facts_block = "\n".join(f"  [{i}] {f}" for i, f in enumerate(facts)) or "  (none)"
    return f"""You are grading one answer from a retrieval QA system against golden truth.
Follow this rubric exactly and output ONLY the JSON object it specifies.

{rubric_text()}

## Item under grading

question: {item["question"]}
answer_type: {item["answer_type"]}
gold_answer: {item["gold_answer"]}
key_facts:
{facts_block}

## System's answer

answer: {row.get("answer") or "(empty)"}
structured_not_found_flag: {row.get("not_found")}
cited_file_names: {[Path(c).name for c in (row.get("cited") or [])]}

Output the rubric's JSON object now."""


def call_claude(prompt: str, model: str, timeout_s: int = 120) -> dict:
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "json"],
        capture_output=True, text=True, timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr[:400]}")
    payload = json.loads(proc.stdout)
    text = payload.get("result") if isinstance(payload, dict) else None
    if not text:
        raise RuntimeError(f"no result field in claude output: {proc.stdout[:200]}")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError(f"no JSON object in judge reply: {text[:200]}")
    return json.loads(text[start : end + 1])


def derive_verdict(item: dict, judged: dict, deterministic: str) -> str:
    """Rubric §Verdict derivation, mechanically."""
    if judged.get("undecidable"):
        return deterministic  # keep the deterministic call; flag stays visible
    at = item["answer_type"]
    fp = judged.get("fact_present") or {}
    all_facts = bool(fp) and all(v is True for v in fp.values())
    some_facts = any(v is True for v in fp.values())
    noc = judged.get("no_contradiction") is True
    if at == "not_found":
        return "correct_abstain" if judged.get("abstention_correct") is True else "false_answer"
    if at == "enumeration":
        return "correct" if (judged.get("enumeration_complete") is True and noc) else (
            "partial" if some_facts and noc else "wrong")
    if all_facts and noc:
        return "correct"
    if some_facts and noc:
        return "partial"
    return "wrong"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--model", default=JUDGE_MODEL_DEFAULT)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true",
                    help="print which rows would be judged and the first prompt")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    enriched = json.loads((run_dir / "answers_enriched.json").read_text(encoding="utf-8"))
    run_record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    ds_dir = Path(__file__).resolve().parents[1] / "datasets" / run_record["dataset"]
    golden_path = ds_dir / "golden.json"
    if not golden_path.exists():
        raise SystemExit(
            f"golden.json for dataset {run_record['dataset']!r} not found at "
            f"{golden_path} (ad-hoc/smoke datasets: pass their golden via a "
            f"dataset dir symlink or judge from the primary datasets only)"
        )
    golden = {q["id"]: q for q in json.loads(golden_path.read_text(encoding="utf-8"))}

    todo = [
        r for r in enriched
        if r["qa_id"] in golden and (
            r.get("verdict") in ("partial", "wrong")
            or golden[r["qa_id"]]["answer_type"] == "enumeration"
        )
    ]
    if args.limit:
        todo = todo[: args.limit]

    print(f"judge: {len(todo)}/{len(enriched)} rows need judging "
          f"(model={args.model}, rubric={rubric_sha()})")
    if args.dry_run:
        if todo:
            print(build_prompt(golden[todo[0]["qa_id"]], todo[0]))
        return 0

    out_path = run_dir / "judge_verdicts.json"
    verdicts: dict[str, dict] = {}
    if out_path.exists():
        prior = json.loads(out_path.read_text(encoding="utf-8"))
        if prior.get("judge_model") == args.model and prior.get("rubric_sha") == rubric_sha():
            verdicts = prior.get("verdicts", {})
        else:
            print("judge: existing verdicts are from a different judge/rubric — "
                  "starting fresh (old file preserved as .old)")
            out_path.rename(out_path.with_suffix(".json.old"))

    n_err = 0
    for row in todo:
        qa_id = row["qa_id"]
        if qa_id in verdicts:
            continue
        item = golden[qa_id]
        try:
            judged = call_claude(build_prompt(item, row), args.model)
            final = derive_verdict(item, judged, row["verdict"])
            verdicts[qa_id] = {
                "criteria": judged,
                "verdict": final,
                "deterministic_verdict": row["verdict"],
                "changed": final != row["verdict"],
            }
            print(f"  {qa_id}: {row['verdict']} -> {final}"
                  + (" (changed)" if final != row["verdict"] else ""))
        except Exception as e:  # noqa: BLE001 — record and continue
            n_err += 1
            verdicts[qa_id] = {"error": f"{type(e).__name__}: {e}"}
            print(f"  {qa_id}: JUDGE ERROR {e}", file=sys.stderr)
        out_path.write_text(json.dumps({
            "judge_model": args.model,
            "rubric_sha": rubric_sha(),
            "verdicts": verdicts,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    changed = sum(1 for v in verdicts.values() if v.get("changed"))
    print(f"judge: done — {len(verdicts)} verdicts, {changed} changed from "
          f"deterministic, {n_err} errors -> {out_path}")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
