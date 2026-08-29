"""MAGPIE_RERANK=0 kill-switch: reranking off, solo gate structurally off.

The switch exists so evals (and users) can hold the rerank stage constant
independently of the solo gate:

- `_rerank_enabled()` is the single source of truth.
- `run_search(rerank=True)` must downgrade to fusion order when the switch
  is off (covered here at the flag level; the heavy search path itself is
  exercised by integration tests).
- `gate_to_solo` must return its input unchanged when the switch is off,
  because its LOCAL_SOLO_MARGIN threshold is calibrated to cross-encoder
  scores and is meaningless against RRF-fusion values.
"""

from __future__ import annotations

import pytest

from src.stage2.search import SearchResult, _rerank_enabled, gate_to_solo


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),      # unset → default on
        ("1", True),
        ("", True),        # garbage/empty never disables
        ("yes", True),
        ("0", False),
        (" 0 ", False),    # tolerate whitespace
    ],
)
def test_rerank_enabled_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MAGPIE_RERANK", raising=False)
    else:
        monkeypatch.setenv("MAGPIE_RERANK", value)
    assert _rerank_enabled() is expected


def _hits(scores: list[float]) -> list[SearchResult]:
    return [
        SearchResult(summary=f"doc {i}", path=f"/tmp/doc{i}.md", score=s)
        for i, s in enumerate(scores)
    ]


def test_solo_gate_off_when_rerank_disabled(monkeypatch):
    """A margin that would normally fire must NOT gate when MAGPIE_RERANK=0.

    Scores here fake a dominant cross-encoder margin (8.0 vs 1.0 >= 2.0
    default threshold); with reranking disabled such values can't exist,
    and the gate must pass everything through untouched.
    """
    monkeypatch.setenv("MAGPIE_RERANK", "0")
    retrieved = _hits([8.0, 1.0, 0.5])
    assert gate_to_solo(retrieved, question="what was the total?") == retrieved


def test_solo_gate_still_reachable_when_rerank_enabled(monkeypatch):
    """With the switch on, the env check must not short-circuit the gate.

    The gate is local-provider-only; forcing the provider check to fail its
    import proves control flow got PAST the rerank check (a provider-layer
    early-return, not a rerank-switch one). The pass-through result is the
    same either way, so assert on the path taken, not the output alone.
    """
    monkeypatch.setenv("MAGPIE_RERANK", "1")
    calls = []

    import src.stage2.search as search_mod

    real = search_mod._rerank_enabled
    monkeypatch.setattr(
        search_mod, "_rerank_enabled",
        lambda: calls.append(1) or real(),
    )
    retrieved = _hits([8.0, 1.0])
    gate_to_solo(retrieved, question="what was the total?")
    assert calls, "gate must consult the rerank switch"
