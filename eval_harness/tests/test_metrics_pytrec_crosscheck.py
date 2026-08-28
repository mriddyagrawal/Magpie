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
