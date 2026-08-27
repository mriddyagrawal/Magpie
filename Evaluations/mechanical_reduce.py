"""Mechanical reduce (routed v3, 2026-08-26): replay the SAVED map
findings from the routed v2 run through a pure-code reduce — no LLM
anywhere in the reduce.

Why: routed v1/v2 (both 14/40) proved the maps extract good facts and
the 3B LLM reduce is the bottleneck — it dilutes (drops found answers as
findings grow), leaks out-of-scope items, and fabricates merges. Code
cannot dilute and cannot fabricate: every surviving bullet is verbatim
from a map, attributed to its file.

Reduce steps (all deterministic):
1. drop NOT_HERE and read-error findings;
2. strip markdown/bullet decoration, split findings into bullet lines;
3. dedup bullets that normalize to the same text (keep first file's);
4. emit "From <file>: ..." groups — the assembly IS the answer.

Zero model calls: reads eval_answer_40__routed2.json, writes
eval_answer_40__routed3.json (product-lane entries copied through).

Usage (repo root):
    uv run python Evaluations/mechanical_reduce.py \
        --v2 Evaluations/college_data/eval_answer_40__routed2.json \
        --answers Evaluations/college_data/eval_answer_40__routed3.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_DECOR_RE = re.compile(r"^[\s*\-•·]+|[\s*]+$")
_WS_RE = re.compile(r"\s+")


def _bullets(finding: str) -> list[str]:
    out = []
    for line in finding.splitlines():
        line = _DECOR_RE.sub("", line).strip()
        if not line or line.upper().startswith("NOT_HERE"):
            continue
        out.append(line)
    return out


def _norm(bullet: str) -> str:
    return _WS_RE.sub(" ", re.sub(r"[^a-z0-9 ]", "", bullet.lower())).strip()


def reduce_mechanical(map_candidates: list[dict]) -> str:
    seen: set[str] = set()
    groups: list[tuple[str, list[str]]] = []
    for c in map_candidates:
        finding = c.get("finding", "")
        if finding.upper().startswith("NOT_HERE"):
            continue
        kept = []
        for b in _bullets(finding):
            key = _norm(b)
            if not key or key in seen:
                continue
            seen.add(key)
            kept.append(b)
        if kept:
            groups.append((c["file"], kept))
    if not groups:
        return ""
    parts = []
    for fname, kept in groups:
        parts.append(f"From {fname}:\n" + "\n".join(f"- {b}" for b in kept))
    return "\n\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--v2", required=True, type=Path)
    ap.add_argument("--answers", required=True, type=Path)
    args = ap.parse_args()

    data = json.loads(args.v2.read_text(encoding="utf-8"))
    out = []
    for e in data:
        e = dict(e)
        if e.get("route") == "mapreduce":
            e["route"] = "mapreduce-mechanical"
            e["provider"] = "local-routed-v3"
            e["magpie_answer"] = reduce_mechanical(e.get("map_candidates", []))
            e.pop("correctness", None)
            e.pop("correctness_notes", None)
        out.append(e)
    args.answers.write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    n = sum(1 for e in out if e["route"] == "mapreduce-mechanical")
    print(f"wrote {args.answers} — {n} mechanical-reduce entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
