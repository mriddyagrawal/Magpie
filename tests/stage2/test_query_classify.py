"""Tests for src/stage2/query_classify.py — adaptive query router (B1)."""

from __future__ import annotations

import pytest

from src.stage2.query_classify import (
    QueryClass,
    RetrievalConfig,
    classify,
    classify_and_config,
    config_for,
)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "question",
    [
        # The smoking gun from the 2026-04-21 transcript
        "what topics did I learn in AI class",
        # Imperative list forms
        "list all my courses",
        "list my courses",
        "show me all the receipts from May",
        "enumerate every chapter in the book",
        "give me all assignments",
        # "what are all" / "what were every"
        "what are all the topics covered",
        "what were the every files I edited",
        # "what topics" / "which topics"
        "what topics are in this course",
        "which topics did we cover",
        # Implicit enumeration via "what / which X did I"
        "what classes did I take last semester",
        "which assignments did I do",
        "what notes did I read this week",
        # Plural enumerable noun after question word
        "what courses are listed",
        "which files mention Maxwell",
        "what documents reference Mozart",
        "what assignments are due",
        # "every" / "all my" / "all the"
        "every receipt I have",
        "all my notes about tempo",
        "all the chapters in part II",
        # "contents of"
        "contents of the textbook",
        "what are the contents of John Taylor classical mechanics",
        # "everything about"
        "everything about Lagrangian mechanics",
        "all about quantum mechanics",
    ],
)
def test_classify_list_all(question: str):
    """Each of these is a representative enumeration query — must classify LIST_ALL."""
    assert classify(question) is QueryClass.LIST_ALL, (
        f"expected LIST_ALL for {question!r}"
    )


@pytest.mark.parametrize(
    "question",
    [
        # Factoid / single-fact queries
        "how much did the Uber from GSP cost",
        "what is tempo",
        "when is the midterm",
        "where did I park last Tuesday",
        # Conceptual / definitional
        "explain Lagrangian mechanics",
        "what does BPM mean",
        "what is the difference between rhythm and meter",
        # Specific entity lookup
        "Mozart Idomeneo opera analysis",
        "Classical Mechanics John Taylor chapter 4",
        "find the bank statement for May 2026",
        # Empty / whitespace
        "",
        "   ",
        # Single-word query
        "tempo",
        "Mozart",
        # Question that mentions a list-y noun but doesn't ASK for a list
        "is tempo on slide 14",
        "did Mozart compose Idomeneo",
    ],
)
def test_classify_general(question: str):
    """Non-enumeration queries — must classify GENERAL (default top-k=5)."""
    assert classify(question) is QueryClass.GENERAL, (
        f"expected GENERAL for {question!r}"
    )


# ---------------------------------------------------------------------------
# Config lookup
# ---------------------------------------------------------------------------

def test_list_all_widens_top_k():
    cfg = config_for(QueryClass.LIST_ALL)
    assert cfg.top_k == 20
    assert "list" in cfg.notes.lower() or "enumeration" in cfg.notes.lower()


def test_general_keeps_default_top_k():
    cfg = config_for(QueryClass.GENERAL)
    assert cfg.top_k == 5


def test_classify_and_config_roundtrip():
    klass, cfg = classify_and_config("what topics did I learn in AI class")
    assert klass is QueryClass.LIST_ALL
    assert cfg.top_k == 20

    klass, cfg = classify_and_config("how much was the receipt")
    assert klass is QueryClass.GENERAL
    assert cfg.top_k == 5


def test_config_is_immutable():
    """RetrievalConfig is frozen — protects against accidental in-flight mutation."""
    cfg = config_for(QueryClass.GENERAL)
    with pytest.raises((AttributeError, Exception)):
        cfg.top_k = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QueryClass enum identity
# ---------------------------------------------------------------------------

def test_query_class_value_round_trips():
    """Subclassing str means the enum value serializes cleanly to logs / JSON."""
    assert QueryClass.LIST_ALL == "list_all"
    assert QueryClass.GENERAL == "general"
    # Round-trip via the string value
    assert QueryClass(str(QueryClass.LIST_ALL.value)) is QueryClass.LIST_ALL
