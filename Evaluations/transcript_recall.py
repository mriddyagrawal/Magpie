"""Eyes-only scoring: can the answer be found in the transcript at all?

The reader is the known bottleneck (450M end-to-end and the transcript spike
both showed it), so comparing transcribers by running the full pipeline
confounds the eyes with the brain. This script skips the reader entirely: for
every question whose key files are pixels-only, it concatenates those files'
transcripts from each transcripts folder and applies the question's
pre-registered criteria regexes to that text. A pass means the facts a
correct answer needs are present in the transcript — the ceiling any reader
can reach with that backend. A fail is a transcription loss, full stop.

It also prints each folder's per-page cost from `_timings.jsonl`.

Two columns per folder: `strict` applies the criteria as written; `loose`
lets every literal space in a pattern match zero or one whitespace
character. Classical OCR recognizers routinely drop word spaces
('APRIL6,2026', 'RINKER253') — the fact is there for a reader but not for
an exact-phrase check, and the gap between the columns is that rate. The
loose column is the eyes ceiling; the strict one is what BM25 / ripgrep
would see if the transcript were indexed as-is.

    uv run python Evaluations/transcript_recall.py \\
        --questions Evaluations/sem6/eval_sem6_vision.json \\
        --criteria  Evaluations/sem6/criteria_vision.json \\
        --corpus    /mnt/hardisk/sem6 \\
        ocr=/data/transcripts_ocr vlm3b=/data/transcripts_vlm3b vlm450m=/data/transcripts_vlm450m
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "Evaluations"))

from score_criteria import grade  # noqa: E402


def loosen(rule: dict) -> dict:
    """The same rule with literal spaces in every pattern made optional."""
    out = {}
    for k, v in rule.items():
        if k == "all" or k == "none":
            out[k] = [p.replace(" ", r"\s?") for p in v]
        elif re.fullmatch(r"any\d*", k):
            out[k] = [[p.replace(" ", r"\s?") for p in group] for group in v]
        else:
            out[k] = v
    return out


def transcript_text(tdir: Path, path: Path) -> str | None:
    # same key derivation as src.content.transcript_path_for, without
    # touching the env var this script is iterating over
    import hashlib

    key = hashlib.sha256(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:16]
    f = tdir / f"{key}.md"
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8")
    return text if "## Page" in text else ""


def timing_summary(tdir: Path) -> str:
    f = tdir / "_timings.jsonl"
    if not f.exists():
        return "no timings"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        return "no timings"
    per_page = [r["seconds"] / max(r["pages"], 1) for r in rows]
    return (f"{len(rows)} files, {sum(r['pages'] for r in rows)} pages, "
            f"median {statistics.median(per_page):.2f} s/page, "
            f"p90 {sorted(per_page)[int(0.9 * (len(per_page) - 1))]:.2f} s/page, "
            f"median {statistics.median(r['chars'] for r in rows):.0f} chars/file")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--questions", required=True)
    ap.add_argument("--criteria", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("folders", nargs="+", help="name=/path/to/transcripts ...")
    args = ap.parse_args()

    questions = json.load(open(args.questions, encoding="utf-8"))
    criteria = json.load(open(args.criteria, encoding="utf-8"))
    corpus = Path(args.corpus)
    folders = [(f.split("=", 1)[0], Path(f.split("=", 1)[1])) for f in args.folders]

    print(f"{'id':<5}" + "".join(f"{name + ' strict':>14}{'loose':>8}" for name, _ in folders) + "   key files")
    totals = {name: [0, 0] for name, _ in folders}
    detail: dict[str, list[str]] = {name: [] for name, _ in folders}
    graded = 0
    for q in questions:
        rule = criteria.get(q["id"])
        if rule is None:
            continue
        graded += 1
        cells = []
        for name, tdir in folders:
            texts = [transcript_text(tdir, corpus / k) for k in q["key_files"]]
            if any(t is None for t in texts):
                cells.append(f"{'missing':>14}{'':>8}")
                detail[name].append(f"{q['id']}: no transcript for "
                                    + ", ".join(k for k, t in zip(q["key_files"], texts) if t is None))
                continue
            text = "\n\n".join(texts)
            ok, why = grade(text, rule)
            ok_loose, why_loose = grade(text, loosen(rule))
            totals[name][0] += ok
            totals[name][1] += ok_loose
            cells.append(f"{'PASS' if ok else 'fail':>14}{'PASS' if ok_loose else 'fail':>8}")
            if not ok_loose:
                detail[name].append(f"{q['id']}: {why_loose}")
            elif not ok:
                detail[name].append(f"{q['id']}: spaces only — {why}")
        print(f"{q['id']:<5}" + "".join(cells) + "   " + "; ".join(q["key_files"]))
    print(f"{'total':<5}" + "".join(f"{totals[n][0]:>11}/{graded:<3}{totals[n][1]:>5}/{graded:<3}" for n, _ in folders))
    for name, tdir in folders:
        print(f"\n{name}: {timing_summary(tdir)}")
        for line in detail[name]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
