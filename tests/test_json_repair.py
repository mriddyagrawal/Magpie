"""Unit tests for `parse_json_with_repair` in src.llm — focuses on the
field-name-drift rescue added 2026-05-07.

Why this matters: small local models (Gemma 4 E4B) reliably get the
structural field (`sources_used`) right but rename the prose field to
match the question's verb — `courses_mentioned`, `result`, `findings`,
etc. The rescue pass coerces those into the schema's `answer` field
so `LocalAgent.run` doesn't fall back to the placeholder string for an
otherwise-correct model response.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from src.llm import (
    JSONParseError,
    _coerce_field_name_drift,
    parse_json_with_repair,
)


class _Answer(BaseModel):
    """Mirrors src.answer.Answer's shape for these tests without
    importing it (avoids dragging the long SYSTEM_PROMPT etc. into
    a unit-test file)."""

    answer: str
    sources_used: list[str]


# ---------------------------------------------------------------------------
# _coerce_field_name_drift — the load-bearing rescue helper
# ---------------------------------------------------------------------------

def test_coerce_drift_rescues_misnamed_string_field():
    """The exact failure mode I caught against Gemma 4: model wrote
    `courses_mentioned` instead of `answer`. Rescue must map that to
    the schema's `answer` field without losing sources_used."""
    raw = '{"courses_mentioned": "CS 301, BIO 222, LNG 210", "sources_used": ["a.csv"]}'
    out = _coerce_field_name_drift(raw)
    assert out == {
        "answer": "CS 301, BIO 222, LNG 210",
        "sources_used": ["a.csv"],
    }


def test_coerce_drift_joins_list_values_with_bullets():
    """When the model emits a JSON list as the prose field (very common
    on 'list every X' questions), join it into bulleted prose so the
    `answer: str` schema validates."""
    raw = (
        '{"findings": ["First item", "Second item", "Third item"], '
        '"sources_used": ["doc.md"]}'
    )
    out = _coerce_field_name_drift(raw)
    assert out["answer"] == "- First item\n- Second item\n- Third item"
    assert out["sources_used"] == ["doc.md"]


def test_coerce_drift_returns_none_when_multiple_extra_keys():
    """Ambiguous payload — model wrote two unknown keys. We can't pick
    safely; bail to the fallback path rather than guess."""
    raw = (
        '{"summary": "...", "details": "...", '
        '"sources_used": ["a.md"]}'
    )
    assert _coerce_field_name_drift(raw) is None


def test_coerce_drift_returns_none_when_no_sources_used():
    """The structural anchor for the rescue is `sources_used` being
    present and correctly named. Without it, we have no signal that
    this is even an Answer-shaped payload."""
    raw = '{"courses_mentioned": "..."}'
    assert _coerce_field_name_drift(raw) is None


def test_coerce_drift_returns_none_on_invalid_json():
    """Malformed JSON skips this rescue entirely so the diagnostic
    path can log the raw output."""
    assert _coerce_field_name_drift("{malformed") is None


def test_coerce_drift_returns_none_when_value_is_dict():
    """Nested object as the answer field — too ambiguous to flatten
    automatically; let the diagnostic path handle it."""
    raw = (
        '{"nested": {"key": "value"}, '
        '"sources_used": ["a.md"]}'
    )
    assert _coerce_field_name_drift(raw) is None


def test_coerce_drift_handles_numeric_value():
    """Edge case: 'how many courses?' might produce a bare number.
    Coerce to string so `answer: str` validates."""
    raw = '{"count": 42, "sources_used": []}'
    out = _coerce_field_name_drift(raw)
    assert out == {"answer": "42", "sources_used": []}


# ---------------------------------------------------------------------------
# parse_json_with_repair — end-to-end with the rescue plumbed in
# ---------------------------------------------------------------------------

def test_parse_repair_recovers_field_name_drift():
    """End-to-end: a Gemma-4-style misnamed payload reaches
    parse_json_with_repair and gets recovered into a valid _Answer
    instead of falling to the placeholder string."""
    raw = '{"courses_mentioned": "CS 301, BIO 222", "sources_used": ["a.csv"]}'
    fallback = _Answer(answer="(fallback)", sources_used=[])
    result = parse_json_with_repair(raw, _Answer, fallback)
    assert result.answer == "CS 301, BIO 222"
    assert result.sources_used == ["a.csv"]


def test_parse_repair_preserves_clean_payload():
    """When the model already obeyed the schema, the rescue must not
    interfere — the direct `model_validate_json` path wins first."""
    raw = '{"answer": "Paris.", "sources_used": ["geo.md"]}'
    result = parse_json_with_repair(raw, _Answer, None)
    assert result.answer == "Paris."
    assert result.sources_used == ["geo.md"]


def test_parse_repair_uses_fallback_on_unrescuable_payload():
    """Two extra keys → ambiguous → rescue declines → fallback returned."""
    raw = '{"a": "...", "b": "...", "sources_used": ["x.md"]}'
    fallback = _Answer(answer="(fb)", sources_used=[])
    result = parse_json_with_repair(raw, _Answer, fallback)
    assert result.answer == "(fb)"


def test_parse_repair_raises_when_no_fallback_and_unrescuable():
    raw = '{"a": "...", "b": "...", "sources_used": []}'
    with pytest.raises(JSONParseError):
        parse_json_with_repair(raw, _Answer, None)


def test_rescue_does_not_fire_for_schemas_without_answer_field():
    """A different Pydantic model (no `answer` field) shouldn't trigger
    the rescue — the rescue is `Answer`-shaped specifically. Verifies
    the schema-introspection guard in parse_json_with_repair."""

    class _OtherSchema(BaseModel):
        title: str
        keywords: list[str]

    raw = '{"different_name": "...", "sources_used": ["x.md"]}'
    fallback = _OtherSchema(title="(fb)", keywords=[])
    result = parse_json_with_repair(raw, _OtherSchema, fallback)
    # Rescue declines because schema has no `answer` field; fallback wins.
    assert result.title == "(fb)"
