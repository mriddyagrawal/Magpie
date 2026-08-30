"""Retrieval-only scoring on a ViDoRe-style corpus: text tier vs ColPali vs fused.

For every question the key page is known. Each tier is queried on its own
(the summary/text tier through the product's hybrid dense+BM25 search, the
fast tier through ColPali MaxSim) and then fused exactly as `run_search`
fuses them (RRF). The score is where the key page lands: top-1, top-5,
MRR — no LLM, no answering, so this is ColPali's own game measured on its
own benchmark pages. Also records per-query latency per tier.

    MAGPIE_DATA_DIR=... QDRANT_CLUSTER_ENDPOINT=... \\
        uv run python Evaluations/vidore_retrieval.py \\
            --questions /mnt/astavaknew/vidore/infovqa/eval_infovqa.json \\
            --out Evaluations/vidore/retrieval__infovqa.json [--limit 500]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")


def rank_of(key_names: set[str], hits) -> int | None:
    for i, h in enumerate(hits, 1):
        if Path(h.path).name in key_names:
            return i
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--k", type=int, default=10)
    a = ap.parse_args()

    from src.stage2.search import _rrf_merge, _search_fast_tier, _search_summary_tier, raw_query

    qs = json.loads(a.questions.read_text(encoding="utf-8"))
    if a.limit:
        qs = qs[: a.limit]
    arms = ("text", "colpali", "fused")
    ranks = {arm: [] for arm in arms}
    lat = {arm: [] for arm in arms}
    records = []
    for i, q in enumerate(qs, 1):
        keys = {Path(k).name for k in q["key_files"]}
        sq = raw_query(q["question"])
        t = time.perf_counter(); text_hits = _search_summary_tier(sq, a.k); lat["text"].append(time.perf_counter() - t)
        t = time.perf_counter(); fast_hits = _search_fast_tier(q["question"], a.k); lat["colpali"].append(time.perf_counter() - t)
        t = time.perf_counter(); fused = _rrf_merge(text_hits, fast_hits, a.k); lat["fused"].append(time.perf_counter() - t)
        r = {"text": rank_of(keys, text_hits), "colpali": rank_of(keys, fast_hits), "fused": rank_of(keys, fused)}
        for arm in arms:
            ranks[arm].append(r[arm])
        records.append({"id": q["id"], "question": q["question"], "key": sorted(keys), "rank": r,
                        "top3": {"text": [Path(h.path).name for h in text_hits[:3]],
                                 "colpali": [Path(h.path).name for h in fast_hits[:3]]}})
        if i % 50 == 0:
            print(f"  {i}/{len(qs)}", flush=True)

    n = len(qs)
    print(f"\n{a.questions.name}: {n} queries, k={a.k}")
    print("| arm | top-1 | top-5 | top-10 | MRR | median s/query |")
    print("|---|---|---|---|---|---|")
    summary = {}
    for arm in arms:
        rs = ranks[arm]
        top1 = sum(1 for r in rs if r == 1); top5 = sum(1 for r in rs if r and r <= 5); top10 = sum(1 for r in rs if r)
        mrr = sum(1 / r for r in rs if r) / n
        med = statistics.median(lat[arm])
        summary[arm] = {"top1": top1, "top5": top5, "top10": top10, "mrr": round(mrr, 3), "median_s": round(med, 3), "n": n}
        print(f"| {arm} | {top1} | {top5} | {top10} | {mrr:.3f} | {med:.2f} |")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"summary": summary, "records": records}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
