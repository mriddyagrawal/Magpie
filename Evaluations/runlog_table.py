"""Render `Evaluations/RUNLOG.jsonl` as a comparison table.

The ledger is append-only and machine-shaped; this is the human view. Filter
by dataset to compare arms on one corpus, or leave it open to see every run.

    uv run python Evaluations/runlog_table.py --dataset phyll
    uv run python Evaluations/runlog_table.py --last 12
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "RUNLOG.jsonl"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default=None)
    p.add_argument("--last", type=int, default=40)
    args = p.parse_args()

    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    if args.dataset:
        rows = [r for r in rows if r["dataset"] == args.dataset]
    rows = rows[-args.last:]

    hdr = f"{'dataset':7} {'strict':>7} {'recall':>8} {'rank1':>8} {'med':>6} {'p90':>6} {'<=10s':>7}  note"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        ret = r.get("retrieval") or {}
        lat = r.get("latency") or {}
        rec = f"{ret.get('recall','-')}/{ret.get('scored','-')}" if ret else "-"
        rk1 = f"{ret.get('rank1','-')}/{ret.get('scored','-')}" if ret else "-"
        print(f"{r['dataset']:7} {str(r.get('strict') or '-'):>7} {rec:>8} {rk1:>8} "
              f"{str(lat.get('median') or '-'):>6} {str(lat.get('p90') or '-'):>6} "
              f"{str(lat.get('under_10s') or '-'):>7}  {r.get('note','')[:58]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
