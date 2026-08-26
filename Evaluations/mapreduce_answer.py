"""Map-reduce answering spike for the LOCAL model (owner's design,
2026-08-26): instead of one call holding all retrieved files, read ONE
file per call (ladder conditions every time), store a timestamped
candidate answer per file, then a small REDUCE call synthesizes the
final answer from the candidates.

Rationale (measured): the local 3B reads a single file near-perfectly
and collapses in crowds; it is fast per call, so N small calls beat one
big one. Product code untouched — standalone spike.

Usage:
    uv run python Evaluations/mapreduce_answer.py \
        --questions Evaluations/college_data/eval_college_data_poc5.json \
        --answers   Evaluations/college_data/eval_answer_poc5__mapreduce.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

MAP_CHARS_PER_FILE = 9000
TOP_K = 5

# v3 (2026-08-26): the map must NEVER see the user's question as a
# question — a 3B reads "across my files" / "compare X vs Y" literally,
# decides one document can't answer it, and denies (measured: identical
# content answered perfectly when asked as "list every professor
# mentioned"). So the map is framed as topic-fact EXTRACTION; only the
# reduce step ever sees the actual question.
MAP_PROMPT = """TOPIC: {question}

DOCUMENT ({name}):
{content}

List every fact in this document related to the topic above — every
relevant name, number, date, amount, or title, each with a few words of
context. Copy names and numbers exactly as written. This document is one
of several being read; facts covering only part of the topic are exactly
what is wanted. Short bullet lines. If the document contains nothing
related to the topic, reply exactly: NOT_HERE
"""

REDUCE_PROMPT = """A question was researched across several documents, read one at a time.
Below are the per-document findings (file + read timestamp).

QUESTION: {question}

FINDINGS:
{findings}

Write the final answer by COMBINING the findings — different documents
cover different parts, and that is expected. Use ONLY findings that
actually address the question; silently ignore findings about other
topics even if a document reported them. If relevant findings overlap or
conflict, mention both versions. Name every document that contributed.
Copy names and numbers exactly; be concise; plain prose (no timestamps,
no bullet-list of documents). Reply NOT_FOUND only when every finding is
NOT_HERE.
"""


def answer_one(llm, question: str, *, temperature: float = 0.2,
               map_k: int | None = None) -> dict:
    """map_k: how many retrieved files to map over (default TOP_K).
    run_search may return MORE than asked for list_all-class questions
    (top_k 5->12 expansion); v1 sliced back to 5 and measurably threw
    away enumeration answers sitting at ranks 6-12 (q14/q40, 2026-08-26).
    """
    from src.content import build_content_blocks
    from src.stage2.search import SearchQuery, run_search

    t0 = time.time()
    retrieved = run_search(
        SearchQuery(query=question, keywords=[]), TOP_K,
        question=question, skip_fast=True, rerank=True,
    )
    candidates = []
    for r in retrieved[:(map_k or TOP_K)]:
        path = Path(r.path)
        try:
            blocks = build_content_blocks(path, max_chars=MAP_CHARS_PER_FILE, max_pdf_pages=4)
            content = " ".join(b for b in blocks if isinstance(b, str)).strip()
            if not content:
                continue
            finding = llm.complete_sync(
                [{"role": "user", "content": MAP_PROMPT.format(
                    name=path.name, content=content[:MAP_CHARS_PER_FILE],
                    question=question)}],
                temperature=temperature, max_tokens=220,
            ).strip()
        except Exception as e:  # noqa: BLE001 — a bad file must not sink the question
            finding = f"NOT_HERE (read error: {type(e).__name__})"
        candidates.append({
            "file": path.name,
            "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "finding": finding[:800],
        })
    findings_text = "\n\n".join(
        f"[{c['read_at']}] {c['file']}:\n{c['finding']}" for c in candidates
    ) or "NOT_HERE"
    final = llm.complete_sync(
        [{"role": "user", "content": REDUCE_PROMPT.format(
            question=question, findings=findings_text)}],
        temperature=temperature, max_tokens=350,
    ).strip()
    return {
        "magpie_answer": "" if final.strip().upper().startswith("NOT_FOUND") else final,
        "map_candidates": candidates,
        "magpie_retrieved": [{"path": r.path, "score": r.score} for r in retrieved],
        "latency_seconds": round(time.time() - t0, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--answers", required=True, type=Path)
    args = ap.parse_args()

    import os

    os.environ["MAGPIE_FORCE_PROVIDER"] = "local"

    from src.inference.local_llm import get_local_llm

    llm = get_local_llm()
    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    done = []
    if args.answers.exists():
        done = json.loads(args.answers.read_text(encoding="utf-8"))
    done_ids = {d["id"] for d in done}
    for i, q in enumerate(questions, 1):
        if q["id"] in done_ids:
            continue
        print(f"[{i}/{len(questions)}] {q['id']}: {q['question'][:70]}", flush=True)
        entry = {"id": q["id"], "question": q["question"],
                 "ground_truth": q.get("ground_truth", ""), "provider": "local-mapreduce"}
        try:
            entry.update(answer_one(llm, q["question"]))
        except Exception as e:  # noqa: BLE001
            entry["error"] = f"{type(e).__name__}: {e}"
        done.append(entry)
        args.answers.write_text(
            json.dumps(done, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
