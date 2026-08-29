"""Check every number in an answer against the files that answer was read from.

A deterministic groundedness metric — no model, no judge, no API. For each
entry in an `eval_answer_*.json`, it re-reads the files listed in
`magpie_retrieved`, pulls every numeral out of the answer text, and asks the
only question a computer can answer with certainty: *does this number appear
in what the model was shown?*

Why numerals: they are the failure class our evals keep recording — right
file, wrong figure ('total vs taxable income', 83,229.50 vs 83,285, a
professor's name attached to the wrong school). A number the model emitted
that appears nowhere in its context is either arithmetic it performed or
something it invented, and those two are worth separating.

The output is a rate, not a verdict. `unsupported` counts numerals absent
from the context; `arithmetic_ok` counts the subset that are exactly the sum
of other numerals present (a legitimate derivation, not a fabrication). What
is left over — `suspicious` — is the fabrication signal.

Usage:

    uv run python Evaluations/grounding_audit.py \\
        Evaluations/sem6/eval_answer_sem6__full.json

Multiple files can be passed at once; each gets its own row so runs can be
compared side by side.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.content import build_content_blocks  # noqa: E402
from src.grounding import (  # noqa: E402
    is_sum_of,
    normalize as _normalize,
    numerals as _numerals,
    unsupported_numerals,
)

# How much of each retrieved file to read back. Matches the answer step's
# own per-file cap so the audit sees what the model saw, not more.
MAX_CHARS_PER_FILE = 25_000
MAX_PDF_PAGES = 5

# Citation markers ([1], [2]) are ours, not the model's claims about the
# world — strip them before looking for numerals.
_CITATION = re.compile(r"\[\d{1,2}\]")

# A numeral is a run of digits that may carry thousands separators and a
# decimal part. Leading currency symbols and trailing percent signs are left
# out of the token deliberately: '$51.32' and '51.32' should compare equal.
_NUMERAL = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Numbers this small are almost always list indices, years in prose, or
# counts the model narrates ('two professors'), and they collide with
# everything. Auditing them produces noise, not signal.
_MIN_INTERESTING = 100




def _context_for(entry: dict) -> str:
    """Re-read the files this answer was produced from. Missing or
    unreadable files are skipped — they make the audit more forgiving, never
    less, which is the right direction for a fabrication detector."""
    chunks: list[str] = []
    for hit in entry.get("magpie_retrieved") or []:
        path = Path(str(hit.get("path", "")).split("#", 1)[0])
        if not path.is_file():
            continue
        try:
            for block in build_content_blocks(
                path, max_chars=MAX_CHARS_PER_FILE, max_pdf_pages=MAX_PDF_PAGES
            ):
                if isinstance(block, str):
                    chunks.append(block)
        except Exception:  # noqa: BLE001 — an unreadable file is not a finding
            continue
    return _normalize("\n".join(chunks))



def audit_entry(entry: dict) -> dict:
    answer = entry.get("magpie_answer") or ""
    if not isinstance(answer, str):
        answer = str(answer)
    context = _context_for(entry)
    found = _numerals(answer)
    missing = unsupported_numerals(answer, context)
    context_numbers = _numerals(context)
    # `unsupported_numerals` already filters out derivable sums; recover the
    # count of those for the report, since "the model did arithmetic" and
    # "the model invented a figure" deserve different columns.
    absent = [t for t in found if t not in context and t not in re.sub(r"\s+", "", context)]
    arithmetic = [t for t in absent if t not in missing and is_sum_of(t, context_numbers)]
    return {
        "id": entry.get("id"),
        "numerals": len(found),
        "supported": len(found) - len(absent),
        "arithmetic_ok": len(arithmetic),
        "suspicious": missing,
    }


def audit_file(path: Path) -> dict:
    entries = json.loads(path.read_text(encoding="utf-8"))
    rows = [audit_entry(e) for e in entries if not e.get("error")]
    total = sum(r["numerals"] for r in rows)
    supported = sum(r["supported"] for r in rows)
    arithmetic = sum(r["arithmetic_ok"] for r in rows)
    suspicious = sum(len(r["suspicious"]) for r in rows)
    dirty = [r for r in rows if r["suspicious"]]
    return {
        "file": path.name,
        "answers": len(rows),
        "numerals": total,
        "supported": supported,
        "arithmetic_ok": arithmetic,
        "suspicious": suspicious,
        "answers_with_suspicious": len(dirty),
        "detail": dirty,
    }


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: grounding_audit.py <eval_answer_*.json> [...]", file=sys.stderr)
        return 2

    print(f"{'run':<40} {'ans':>4} {'nums':>5} {'ok':>5} {'calc':>5} {'susp':>5} {'dirty':>6}")
    reports = []
    for p in paths:
        r = audit_file(p)
        reports.append(r)
        print(
            f"{r['file']:<40} {r['answers']:>4} {r['numerals']:>5} "
            f"{r['supported']:>5} {r['arithmetic_ok']:>5} {r['suspicious']:>5} "
            f"{r['answers_with_suspicious']:>6}"
        )

    for r in reports:
        if not r["detail"]:
            continue
        print(f"\n--- {r['file']}: numbers found in no retrieved file ---")
        for d in r["detail"]:
            print(f"  {d['id']}: {', '.join(d['suspicious'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
