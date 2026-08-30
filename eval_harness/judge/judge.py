"""Full-context judge (rubric v2.0) — one instance grades an entire run.

Owner decision 2026-08-28: a single pinned high-tier Claude instance sees
EVERYTHING — every question, gold answer, Magpie answer, and the source files
themselves (it Reads the gold-source images) — and writes judge_verdicts.json
(strict schema) + JUDGE-REPORT.md (fixed sections) into the run folder.
Deterministic verdicts from enrich.py remain in metrics.json as a free
cross-check; THIS is the verdict authority.

Engine: headless `claude -p` (agentic — has Read access to the run dir and
corpus). The judge model + rubric sha are stamped; a verdicts file from a
different judge/rubric is set aside, never merged.

Privacy: full-context mode sends document content to the API — public corpora
only unless the owner explicitly OKs a personal dataset (PLAN §9.4).

Usage:
  uv run python eval_harness/judge/judge.py --run-dir eval_harness/runs/<id> \
      [--model claude-opus-5] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
RUBRIC_PATH = HERE / "rubric.md"

JUDGE_MODEL_DEFAULT = "claude-opus-5"
VERDICTS = {"correct", "partial", "wrong", "false_abstain",
            "correct_abstain", "false_answer"}


def rubric_sha() -> str:
    return hashlib.sha256(RUBRIC_PATH.read_bytes()).hexdigest()[:16]


def build_prompt(run_dir: Path, ds_dir: Path, corpus_root: Path, n_questions: int) -> str:
    return f"""You are the FULL-CONTEXT JUDGE for one Magpie eval run (rubric v2.0).

Read, in this order:
1. {RUBRIC_PATH} — the rubric; your two output artifacts must match its formats EXACTLY.
2. {ds_dir / 'golden.json'} — all golden items (id, question, golden_answer, key_facts, gold_sources, answer_type, phrasing, pair_id).
3. {run_dir / 'raw/answers.jsonl'} — Magpie's answers (qa_id, magpie_answer — older runs say 'answer', magpie_cited/'cited', not_found, error).
4. {run_dir / 'answers_enriched.json'} — the deterministic verdicts (field "verdict"), for the disagreement count and §5 of the report. They are NOT your verdicts — grade independently first.
5. Source files: for any question where the gold answer and Magpie's answer disagree, or the gold looks doubtful, Read the actual image at {corpus_root}/<gold_source> and let the FILE settle it. You do not need to open files for clear-cut agreements.

Then write EXACTLY two files (create/overwrite):
- {run_dir / 'judge_verdicts.json'} — the rubric's Artifact 1 schema, verbatim field names. Every one of the {n_questions} answered qa_ids MUST appear. Set "judge_model" to the model you are actually running as if you know it, else "claude-opus-5". Set "run_id" to "{run_dir.name}".
- {run_dir / 'JUDGE-REPORT.md'} — the rubric's Artifact 2 sections, in order.

Rules that override everything: binary verdicts from the rubric's exact vocabulary; phrasing-blind; consult files rather than guess; log golden-set problems in "golden_issues" instead of silently compensating. Your final chat message: one line — counts per verdict and how many files you consulted."""


def validate(run_dir: Path) -> dict:
    """Schema-check the judge's output; raise with specifics on violation."""
    out = json.loads((run_dir / "judge_verdicts.json").read_text(encoding="utf-8"))
    answered = {json.loads(l)["qa_id"]
                for l in (run_dir / "raw/answers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    verdicts = out.get("verdicts", {})
    missing = answered - set(verdicts)
    if missing:
        raise ValueError(f"judge omitted {len(missing)} qa_ids, e.g. {sorted(missing)[:5]}")
    bad = {q: v.get("verdict") for q, v in verdicts.items()
           if v.get("verdict") not in VERDICTS}
    if bad:
        raise ValueError(f"invalid verdict values: {bad}")
    if not (run_dir / "JUDGE-REPORT.md").exists():
        raise ValueError("JUDGE-REPORT.md missing")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--model", default=JUDGE_MODEL_DEFAULT)
    ap.add_argument("--timeout-s", type=int, default=3600)
    ap.add_argument("--dry-run", action="store_true", help="print the prompt and exit")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    run_record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    ds_dir = EVAL / "datasets" / run_record["dataset"]
    corpus_root = Path(json.loads(
        (ds_dir / "corpus_root.local.json").read_text(encoding="utf-8"))["corpus_root"])
    n_questions = sum(1 for l in (run_dir / "raw/answers.jsonl")
                      .read_text(encoding="utf-8").splitlines() if l.strip())

    prior = run_dir / "judge_verdicts.json"
    if prior.exists() and not args.dry_run:
        old = json.loads(prior.read_text(encoding="utf-8"))
        if old.get("rubric_version") != "2.0" or old.get("judge_model") != args.model:
            prior.rename(prior.with_suffix(".json.old"))
            print("judge: prior verdicts from different judge/rubric set aside as .old")

    prompt = build_prompt(run_dir, ds_dir, corpus_root, n_questions)
    if args.dry_run:
        print(prompt)
        return 0

    # #90: the judge gets Write for its two artifacts only in spirit - verify
    # in fact that it modified nothing else it also reads.
    # #105: snapshot BYTES, not git state - these files are typically
    # untracked at judge time (the skill commits after judging), so a
    # `git checkout --` restore would silently do nothing. Restoring from
    # the in-memory snapshot works regardless of git status.
    protected = [ds_dir / "golden.json", run_dir / "answers_enriched.json",
                 run_dir / "metrics.json", run_dir / "raw" / "answers.jsonl"]
    pre_bytes = {f: f.read_bytes() for f in protected if f.exists()}

    print(f"judge: full-context grading of {n_questions} answers "
          f"(model={args.model}, rubric={rubric_sha()}) — one instance, "
          f"reads sources itself; this takes several minutes")
    # shutil.which: on Windows the npm shim is claude.cmd, which a bare
    # argv[0] does not resolve; which() honors PATHEXT everywhere.
    claude_bin = shutil.which("claude")
    if not claude_bin:
        sys.exit("judge: `claude` CLI not found on PATH - install Claude "
                 "Code and log in (the judge cannot run without it)")
    proc = subprocess.run(
        [claude_bin, "-p", "--model", args.model,
         "--allowedTools", "Read,Write,Glob,Grep"],
        input=prompt, capture_output=True, text=True, timeout=args.timeout_s,
        cwd=str(EVAL.parent),
    )
    if proc.returncode != 0:
        raise SystemExit(f"judge instance exited {proc.returncode}: {proc.stderr[:500]}")
    print(f"judge instance says: {proc.stdout.strip()[-300:]}")

    tampered = []
    for f, original in pre_bytes.items():
        current = f.read_bytes() if f.exists() else None
        if current != original:
            f.write_bytes(original)
            if f.read_bytes() != original:
                raise SystemExit(f"judge modified {f.name} and restore FAILED - "
                                 f"recover manually before trusting anything")
            tampered.append(f.name)
    if tampered:
        raise SystemExit(f"judge modified protected artifact(s) {tampered} - "
                         f"restored from byte snapshot; verdicts rejected")

    out = validate(run_dir)
    # stamp what the wrapper knows; the instance's self-report is advisory (#88)
    out["judge_model_self_report"] = out.get("judge_model")
    out["judge_model"] = args.model
    out["judge_model_source"] = "wrapper_requested (self-report advisory)"
    out["judge_model_requested"] = args.model
    out["rubric_sha"] = rubric_sha()

    # #87: matcher precision from the FULL deterministic-vs-judge matrix -
    # a tracked number, not prose. P(judge agrees | deterministic verdict).
    det = {r["qa_id"]: r.get("verdict") for r in json.loads(
        (run_dir / "answers_enriched.json").read_text(encoding="utf-8"))}
    matrix: dict = {}
    for qa_id, v in out["verdicts"].items():
        d, j = det.get(qa_id), v.get("verdict")
        if d is None or j is None:
            continue
        cell = matrix.setdefault(d, {"n": 0, "judge_agrees": 0})
        cell["n"] += 1
        cell["judge_agrees"] += (d == j)
    correct_cell = matrix.get("correct", {"n": 0, "judge_agrees": 0})
    out["matcher_audit"] = {
        "matrix": matrix,
        "matcher_precision": (correct_cell["judge_agrees"] / correct_cell["n"])
        if correct_cell["n"] else None,
        "note": "precision = P(judge also says correct | deterministic said correct)",
    }
    (run_dir / "judge_verdicts.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    s = out.get("summary", {})
    print(f"judge: VALID — {s.get('correct')}✓ {s.get('partial')}~ {s.get('wrong')}✗ "
          f"fa={s.get('false_abstain')} | golden issues: {len(out.get('golden_issues', []))} "
          f"| disagreements vs deterministic: {s.get('disagreements_with_deterministic')} "
          f"-> {run_dir / 'JUDGE-REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
