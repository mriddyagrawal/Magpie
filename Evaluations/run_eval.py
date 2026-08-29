"""Run a Magpie evaluation: questions JSON in, answers JSON out.

This is the single, corpus-agnostic runner referenced by Step 2 of
`Evaluations/README.md`. Point it at any pair of files; it loops over
every question, calls Magpie's pipeline (`ask_sync`), and writes the
matching answers file. Resume-safe: re-running skips IDs already
present in the answers file, so a crash mid-run loses at most one
question's worth of work.

The runner can drive Magpie against either the **local** llama-server
backend or a **cloud** backend (Moonshot Kimi / OpenRouter). Pick one
with `--provider local|moonshot|openrouter`, or omit the flag and
inherit whatever `LLM_PROVIDER` `.env` already sets. The provider used
is recorded on every answer entry so cross-run comparisons stay honest.

Usage (from the repo root):

    # Local Gemma via llama-server (longer warm-up, no API cost):
    LLAMA_SERVER_STARTUP_TIMEOUT_S=180 \\
        uv run python Evaluations/run_eval.py \\
            --provider local \\
            --questions Evaluations/<dataset>/eval_<dataset>.json \\
            --answers   Evaluations/<dataset>/eval_answer_<dataset>.json

    # Cloud via Moonshot Kimi (needs MOONSHOT_API_KEY in .env):
    uv run python Evaluations/run_eval.py \\
        --provider moonshot \\
        --questions Evaluations/<dataset>/eval_<dataset>.json \\
        --answers   Evaluations/<dataset>/eval_answer_<dataset>.json

    # Cloud via OpenRouter (needs OPENROUTER_API_KEY in .env):
    uv run python Evaluations/run_eval.py --provider openrouter ...

If `--answers` is omitted, the runner writes alongside the questions
file with `eval_` swapped for `eval_answer_` in the filename.

The script does NOT run `just sync` for you — see Step 2 of the README.
The corpus must already be indexed before this script runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

# `src.pipeline` (and its transitive `src.llm` import) reads
# `LLM_PROVIDER` lazily on each call rather than at import. We still
# import it inside `main()` so any `--provider` override is in place
# before the first call site, in case future internals memoize it.

VALID_PROVIDERS = ("local", "moonshot", "openrouter")


def load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        # encoding matters: without it Windows reads/writes cp1252, which
        # mojibakes the questions and breaks any UTF-8 consumer of the
        # answers file (hit live 2026-08-24 on the first Windows eval run).
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def run_one(ask_sync, q: dict, *, provider: str, top_k: int, rewrite: bool, fast: bool) -> dict:
    qid = q["id"]
    qtext = q["question"]
    gt = q.get("ground_truth", "")
    t0 = time.time()
    try:
        r = ask_sync(qtext, top_k=top_k, rewrite=rewrite, fast=fast)
        return {
            "id": qid,
            "question": qtext,
            "ground_truth": gt,
            "provider": provider,
            "magpie_answer": r.answer,
            "magpie_sources_used": r.sources_used,
            "magpie_retrieved": [
                {"path": x.path, "score": x.score} for x in r.retrieved
            ],
            "latency_seconds": round(time.time() - t0, 2),
            # Where the seconds went, per stage, so a slow run can be diagnosed
            # from the answers file alone (retrieval vs reader vs files read).
            "stage_timings": {k: round(v, 3) for k, v in (r.timings or {}).items()},
        }
    except Exception as e:  # noqa: BLE001 — record any failure, keep going
        return {
            "id": qid,
            "question": qtext,
            "ground_truth": gt,
            "provider": provider,
            "error": f"{type(e).__name__}: {e}",
            "latency_seconds": round(time.time() - t0, 2),
        }


def default_answers_path(questions_path: Path) -> Path:
    name = questions_path.name
    if name.startswith("eval_") and not name.startswith("eval_answer_"):
        return questions_path.with_name("eval_answer_" + name[len("eval_"):])
    return questions_path.with_name(questions_path.stem + "_answers.json")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--questions", required=True, type=Path,
                   help="Path to eval_<dataset>.json")
    p.add_argument("--answers", type=Path, default=None,
                   help="Path to eval_answer_<dataset>.json "
                        "(default: alongside --questions)")
    p.add_argument("--provider", choices=VALID_PROVIDERS, default=None,
                   help="Which LLM backend to drive. Sets LLM_PROVIDER for "
                        "this run. If omitted, inherits .env / settings.")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--rewrite", action="store_true", default=True,
                   help="Enable query rewrite (default: on)")
    p.add_argument("--no-rewrite", dest="rewrite", action="store_false")
    p.add_argument("--fast", action="store_true", default=False,
                   help="Include the ColPali visual tier")
    args = p.parse_args()

    if args.provider:
        # MAGPIE_FORCE_PROVIDER beats settings.json (see src/llm.py
        # active_provider). Setting only LLM_PROVIDER (the old behavior)
        # silently did nothing once the 2026-05 precedence flip made
        # settings.json win — every "cloud" eval answered with whatever
        # provider the Settings UI had selected. Both are set so old and
        # new code paths agree.
        os.environ["MAGPIE_FORCE_PROVIDER"] = args.provider
        os.environ["LLM_PROVIDER"] = args.provider
    provider = (
        os.environ.get("LLM_PROVIDER", "").strip().lower() or "<inherited>"
    )

    if not args.questions.exists():
        print(f"questions file not found: {args.questions}", file=sys.stderr)
        return 2
    answers_path = args.answers or default_answers_path(args.questions)
    answers_path.parent.mkdir(parents=True, exist_ok=True)

    # Imported here so the LLM_PROVIDER override above is in effect when
    # the LLM client modules first read it.
    from src.pipeline import ask_sync  # noqa: PLC0415

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    results = load_existing(answers_path)
    done_ids = {r["id"] for r in results}

    todo = [q for q in questions if q["id"] not in done_ids]
    print(
        f"Plan: {len(questions)} questions; "
        f"{len(done_ids)} already done, {len(todo)} to do.",
        flush=True,
    )
    print(f"Provider:  {provider}", flush=True)
    print(f"Questions: {args.questions}", flush=True)
    print(f"Answers:   {answers_path}", flush=True)

    overall_start = time.time()
    for i, q in enumerate(questions, 1):
        if q["id"] in done_ids:
            continue
        elapsed = (time.time() - overall_start) / 60
        print(
            f"[{i}/{len(questions)}] ({elapsed:.1f}min) "
            f"{q['id']}: {q['question'][:80]}",
            flush=True,
        )
        entry = run_one(
            ask_sync, q,
            provider=provider,
            top_k=args.top_k,
            rewrite=args.rewrite,
            fast=args.fast,
        )
        results.append(entry)
        # Incremental save: any prior progress survives a crash.
        answers_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    total_min = (time.time() - overall_start) / 60
    print(
        f"\nDone in {total_min:.1f} min. "
        f"{len(results)}/{len(questions)} entries -> {answers_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
