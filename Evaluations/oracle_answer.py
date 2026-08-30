"""Reading ceiling: hand the model exactly the key file(s) and nothing else.

Every eval question names its `key_files`. Skipping retrieval and giving the
answer step only those files measures how often the reader gets it right
when retrieval is perfect — the number all the retrieval work is chasing.
Output has the same shape as run_eval.py's answers file (magpie_retrieved =
the key files), so score_criteria.py and retrieval_recall.py work unchanged.

    uv run python Evaluations/oracle_answer.py --dataset sem4 --corpus /mnt/hardisk/sem_4 \\
        --answers Evaluations/sem4/eval_answer_sem4__oracle.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")


def _passage_files(dataset: str, q: dict, files: list[str], n: int) -> list[str]:
    # pick the windows of each key file that match the question's criteria
    # patterns (and its words) best, write them to scratch .md files, and hand
    # those over instead. Images keep their pixels/transcripts — no passages.
    import re
    from src.content import build_content_blocks

    crit_path = REPO_ROOT / "Evaluations" / dataset / ("criteria_v2.json" if (REPO_ROOT / "Evaluations" / dataset / "criteria_v2.json").exists() else "criteria.json")
    rule = json.load(open(crit_path)).get(q["id"], {})
    patterns = list(rule.get("all", [])) + [p for k, v in rule.items() if re.fullmatch(r"any\d*", k) for group in v for p in group]
    words = {w for w in re.findall(r"[a-z0-9]{4,}", q["question"].lower())}
    out_dir = Path("/tmp/claude-1001/-mnt-hardisk-NotAnotherSpotlight/1a32ad72-3360-45db-9a4c-c4a351520f9b/scratchpad/passages") / dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        if Path(f).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            out.append(f)
            continue
        blocks = [b for b in build_content_blocks(Path(f), max_chars=25_000, max_pdf_pages=5) if isinstance(b, str)]
        text = "\n".join(blocks)
        windows = [text[i:i + 1500] for i in range(0, max(1, len(text)), 1200)]
        def score(w):
            low = w.lower()
            return sum(3 for pat in patterns if re.search(pat, w, re.IGNORECASE)) + sum(1 for x in words if x in low)
        best = sorted(windows, key=score, reverse=True)[:n]
        dst = out_dir / (q["id"] + "_" + Path(f).name + ".md")
        dst.write_text(f"(excerpt of {Path(f).name})\n\n" + "\n\n[...]\n\n".join(best), encoding="utf-8")
        out.append(str(dst))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--passages", type=int, default=0,
                    help="instead of whole files, hand over this many ~1500-char windows per key file — "
                         "the ones that match the question's own criteria best. An upper bound for "
                         "passage-level context: the model reads one screen, not the whole document.")
    args = ap.parse_args()

    from src.answer import answer_question, build_answer_agent
    from src.stage2.search import raw_query

    questions = json.load(open(REPO_ROOT / "Evaluations" / args.dataset / f"eval_{args.dataset}.json"))
    done = {r["id"] for r in json.load(open(args.answers))} if args.answers.exists() else set()
    results = json.load(open(args.answers)) if args.answers.exists() else []
    agent = build_answer_agent()
    for q in questions:
        if q["id"] in done:
            continue
        files = [str(args.corpus / kf) for kf in q.get("key_files", [])]
        files = [f for f in files if Path(f).is_file()]
        if args.passages and files:
            files = _passage_files(args.dataset, q, files, args.passages)
        t0 = time.time()
        entry = {"id": q["id"], "question": q["question"], "ground_truth": q.get("ground_truth", ""), "provider": "local",
                 "magpie_retrieved": [{"path": f, "score": 1.0} for f in files]}
        if not files:
            # absence probe (or a missing key file): the model sees nothing, answers nothing
            entry.update(magpie_answer="", magpie_sources_used=[], latency_seconds=0.0)
        else:
            try:
                ans = asyncio.run(answer_question(agent, q["question"], files, search_query=raw_query(q["question"])))
                entry.update(magpie_answer=ans.answer, magpie_sources_used=ans.sources_used,
                             latency_seconds=round(time.time() - t0, 2))
            except Exception as e:  # noqa: BLE001
                entry.update(error=f"{type(e).__name__}: {e}", latency_seconds=round(time.time() - t0, 2))
        results.append(entry)
        args.answers.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{q['id']}: {len(files)} file(s) -> {repr(entry.get('magpie_answer', entry.get('error')))[:70]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
