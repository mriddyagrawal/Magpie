"""Cross-check harness metrics against pytrec_eval (the reference impl).

The reviewer ran 40 randomized cases against pytrec_eval-terrier and found
zero mismatches (comments.md, Review 8f531c6). This test makes that evidence
reproducible instead of anecdotal. Skipped unless pytrec_eval is installed —
it is deliberately NOT a project dependency (PLAN §5):

    uv run --with pytrec-eval-terrier pytest eval_harness/tests/test_metrics_pytrec_crosscheck.py
"""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))

import metrics  # noqa: E402

pytrec_eval = pytest.importorskip("pytrec_eval")


def test_agrees_with_pytrec_eval_on_randomized_cases():
    # seed recorded HERE, in the test, so a future edit can't drift it
    rng = random.Random(20260828)
    for case in range(40):
        n_docs = rng.randint(3, 8)
        docs = [f"d{i}.pdf" for i in range(n_docs)]
        n_rel = rng.randint(1, min(4, n_docs))
        rel_docs = rng.sample(docs, n_rel)
        qrels = {d: rng.choice([1, 2]) for d in rel_docs}
        ranking = docs[:]
        rng.shuffle(ranking)
        scores = {d: float(len(ranking) - i) for i, d in enumerate(ranking)}

        evaluator = pytrec_eval.RelevanceEvaluator(
            {"q": qrels}, {"ndcg_cut_5", "recall_5", "recip_rank"}
        )
        ref = evaluator.evaluate({"q": scores})["q"]

        ours_ndcg = metrics.ndcg_at_k(ranking, qrels, 5)
        ours_recall = metrics.recall_at_k(ranking, qrels, 5)
        ours_mrr = metrics.mrr(ranking, qrels)

        assert abs(ours_ndcg - ref["ndcg_cut_5"]) < 1e-9, f"case {case} ndcg"
        assert abs(ours_recall - ref["recall_5"]) < 1e-9, f"case {case} recall"
        assert abs(ours_mrr - ref["recip_rank"]) < 1e-9, f"case {case} mrr"


def test_tie_heavy_case_matches_pytrec_eval():
    """Equal scores across several docs — where nDCG implementations most
    often diverge (reviewer request; same territory as RRF tie instability)."""
    docs = [f"t{i}.pdf" for i in range(6)]
    qrels = {"t2.pdf": 2, "t4.pdf": 1}
    scores = {d: 1.0 for d in docs}  # all tied
    evaluator = pytrec_eval.RelevanceEvaluator(
        {"q": qrels}, {"ndcg_cut_5", "recall_5", "recip_rank"}
    )
    ref = evaluator.evaluate({"q": scores})["q"]
    # pytrec_eval breaks score ties by doc id (lexicographic desc) — feed our
    # metrics the same ordering it would use, then require exact agreement
    ranking = sorted(docs, reverse=True)
    assert abs(metrics.ndcg_at_k(ranking, qrels, 5) - ref["ndcg_cut_5"]) < 1e-9
    assert abs(metrics.recall_at_k(ranking, qrels, 5) - ref["recall_5"]) < 1e-9
    assert abs(metrics.mrr(ranking, qrels) - ref["recip_rank"]) < 1e-9
