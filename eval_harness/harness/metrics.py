"""Pure-Python retrieval + citation metrics (PLAN.md §5).

No pytrec_eval dependency (C extension, Windows-compiler pain) — these are
~40 lines of math, unit-tested against hand-computed fixtures in
tests/test_metrics.py. The qrels TSV the runner emits stays
pytrec_eval-compatible so anyone can cross-check externally.

Definitions (binary-or-graded relevance from qrels; gold_sources rel=2,
acceptable_sources rel=1; recall/hit binarize at rel>=1, nDCG uses the grade):

  hit@k      any relevant file in the top k                     (binary)
  recall@k   |relevant in top k| / |relevant|                   (BEIR)
  MRR        1 / rank of the first relevant file                (0 if absent)
  nDCG@k     DCG with gain=rel, log2 discount, over ideal       (ViDoRe conv.)

Path matching is corpus-relative-vs-absolute robust: ported by copy from the
legacy Evaluations/metrics.py matcher (suffix match, case- and
separator-insensitive), which survived real Windows/macOS runs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def norm_path(p: str) -> str:
    return str(p).replace("\\", "/").strip().lower()


def path_matches(gold: str, candidate: str) -> bool:
    """True when `candidate` (usually absolute) refers to `gold` (usually
    corpus-relative). Suffix-based, separator/case-insensitive."""
    g, c = norm_path(gold), norm_path(candidate)
    if not g or not c:
        return False
    return c == g or c.endswith("/" + g) or (("/" not in g) and c.rsplit("/", 1)[-1] == g)


def _relevance_of(candidate: str, qrels: Mapping[str, int]) -> int:
    """Highest qrels grade this candidate path matches (0 = not relevant)."""
    best = 0
    for gold, rel in qrels.items():
        if rel > best and path_matches(gold, candidate):
            best = rel
    return best


def graded_ranking(ranked_paths: Sequence[str], qrels: Mapping[str, int]) -> list[int]:
    """The ranked list translated to relevance grades, deduplicating gold
    matches: a gold file matched at rank i contributes 0 at every later rank
    (double-counting a re-retrieved duplicate would inflate every metric)."""
    remaining = dict(qrels)
    grades: list[int] = []
    for cand in ranked_paths:
        matched_key = None
        best = 0
        for gold, rel in remaining.items():
            if rel > best and path_matches(gold, cand):
                best, matched_key = rel, gold
        if matched_key is not None:
            del remaining[matched_key]
        grades.append(best)
    return grades


def hit_at_k(ranked_paths: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    return 1.0 if any(g >= 1 for g in graded_ranking(ranked_paths[:k], qrels)) else 0.0


def recall_at_k(ranked_paths: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    n_rel = sum(1 for r in qrels.values() if r >= 1)
    if n_rel == 0:
        return 0.0
    found = sum(1 for g in graded_ranking(ranked_paths[:k], qrels) if g >= 1)
    return found / n_rel


def mrr(ranked_paths: Sequence[str], qrels: Mapping[str, int]) -> float:
    for i, g in enumerate(graded_ranking(ranked_paths, qrels), 1):
        if g >= 1:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked_paths: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    grades = graded_ranking(ranked_paths[:k], qrels)
    dcg = sum(g / math.log2(i + 1) for i, g in enumerate(grades, 1))
    ideal = sorted((r for r in qrels.values() if r >= 1), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return dcg / idcg if idcg > 0 else 0.0


def citation_scores(
    cited_paths: Sequence[str], qrels: Mapping[str, int]
) -> dict[str, float | int]:
    """ALCE-style at file granularity, deterministic (PLAN.md §5).

    precision: cited files that are relevant / all cited files (1.0 if none
    cited and nothing relevant was needed - vacuous truth avoided by callers
    on not_found rows). recall: relevant files cited / relevant files."""
    relevant = {g for g, r in qrels.items() if r >= 1}
    n_cited = len(cited_paths)
    good = sum(1 for c in cited_paths if _relevance_of(c, qrels) >= 1)
    covered = sum(1 for g in relevant if any(path_matches(g, c) for c in cited_paths))
    precision = good / n_cited if n_cited else 0.0
    recall = covered / len(relevant) if relevant else 0.0
    return {
        "cited": n_cited,
        "citation_precision": precision,
        "citation_recall": recall,
        "hallucinated_citations": n_cited - good,
    }


def retrieval_row(
    ranked_paths: Sequence[str],
    qrels: Mapping[str, int],
    ks: Sequence[int] = (1, 3, 5, 12),
) -> dict:
    row: dict = {
        "mrr": mrr(ranked_paths, qrels),
        "first_gold_rank": next(
            (i for i, g in enumerate(graded_ranking(ranked_paths, qrels), 1) if g >= 1),
            None,
        ),
    }
    for k in ks:
        row[f"hit@{k}"] = hit_at_k(ranked_paths, qrels, k)
        row[f"recall@{k}"] = recall_at_k(ranked_paths, qrels, k)
    row["ndcg@5"] = ndcg_at_k(ranked_paths, qrels, 5)
    return row


def aggregate(rows: Sequence[Mapping[str, float | None]]) -> dict:
    """Mean of every numeric key across per-question rows (None skipped)."""
    if not rows:
        return {}
    out: dict = {"n": len(rows)}
    keys = {k for r in rows for k, v in r.items() if isinstance(v, (int, float))}
    for k in sorted(keys):
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        if vals:
            out[k] = sum(vals) / len(vals)
    return out
