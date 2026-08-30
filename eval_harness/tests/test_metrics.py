"""Hand-computed fixtures for harness/metrics.py (PLAN.md §5: fixture-tested
pure-Python replaces pytrec_eval)."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))

import metrics  # noqa: E402

Q = {"receipts/costco.pdf": 2, "receipts/extra.pdf": 1}  # gold=2, acceptable=1
ABS = "/Users/x/corpus/receipts/costco.pdf"


def test_path_matching_relative_vs_absolute():
    assert metrics.path_matches("receipts/costco.pdf", ABS)
    assert metrics.path_matches("costco.pdf", ABS)
    assert metrics.path_matches("Receipts/Costco.PDF", ABS.replace("/", "\\"))
    assert not metrics.path_matches("receipts/other.pdf", ABS)
    # bare-filename gold must not match a different file that merely contains it
    assert not metrics.path_matches("costco.pdf", "/x/notcostco.pdf.bak")


def test_hit_and_recall_hand_computed():
    ranked = ["/c/a.pdf", ABS, "/c/b.pdf", "/c/receipts/extra.pdf"]
    # gold costco at rank 2, acceptable extra at rank 4; 2 relevant total
    assert metrics.hit_at_k(ranked, Q, 1) == 0.0
    assert metrics.hit_at_k(ranked, Q, 2) == 1.0
    assert metrics.recall_at_k(ranked, Q, 2) == 0.5    # 1 of 2 relevant
    assert metrics.recall_at_k(ranked, Q, 4) == 1.0
    assert metrics.mrr(ranked, Q) == 0.5               # first relevant at rank 2


def test_mrr_zero_when_absent():
    assert metrics.mrr(["/c/a.pdf", "/c/b.pdf"], Q) == 0.0


def test_ndcg_hand_computed():
    ranked = ["/c/a.pdf", ABS, "/c/receipts/extra.pdf"]
    # grades at ranks 1..3: [0, 2, 1]
    dcg = 2 / math.log2(3) + 1 / math.log2(4)
    # ideal grades [2, 1] -> idcg
    idcg = 2 / math.log2(2) + 1 / math.log2(3)
    assert abs(metrics.ndcg_at_k(ranked, Q, 5) - dcg / idcg) < 1e-12
    # perfect ordering scores 1.0
    perfect = [ABS, "/c/receipts/extra.pdf"]
    assert abs(metrics.ndcg_at_k(perfect, Q, 5) - 1.0) < 1e-12


def test_duplicate_retrieval_not_double_counted():
    ranked = [ABS, ABS, ABS]
    assert metrics.recall_at_k(ranked, Q, 3) == 0.5    # still only 1 of 2
    grades = metrics.graded_ranking(ranked, Q)
    assert grades == [2, 0, 0]


def test_citation_scores():
    cited = [ABS, "/c/wrong.pdf"]
    s = metrics.citation_scores(cited, Q)
    assert s["citation_precision"] == 0.5              # 1 of 2 cited relevant
    assert s["citation_recall"] == 0.5                 # 1 of 2 relevant cited
    assert s["hallucinated_citations"] == 1

    s2 = metrics.citation_scores([], Q)
    assert s2["citation_precision"] == 0.0 and s2["citation_recall"] == 0.0


def test_retrieval_row_and_aggregate():
    ranked = [ABS, "/c/b.pdf"]
    row = metrics.retrieval_row(ranked, Q)
    assert row["hit@1"] == 1.0 and row["first_gold_rank"] == 1
    agg = metrics.aggregate([{"hit@1": 1.0}, {"hit@1": 0.0}, {"hit@1": None}])
    assert agg["hit@1"] == 0.5 and agg["n"] == 3
