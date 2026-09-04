"""The groundedness guard has a real off-switch (MAGPIE_GROUNDING_GUARD),
distinct from MAGPIE_STRICT_GROUNDING (summaries-as-support), and the
image blind spot it works around is pinned as a documented behaviour."""

from __future__ import annotations

import pytest

from src.answer import Answer, _apply_grounding_guard, grounding_guard_enabled


def _answer(text: str) -> Answer:
    return Answer(answer=text, sources_used=["receipt.jpg"], not_found=False, not_found_topic="")


class _Img:
    data = b"\x89PNG..."
    media_type = "image/png"


def test_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAGPIE_GROUNDING_GUARD", raising=False)
    assert grounding_guard_enabled() is True
    monkeypatch.setenv("MAGPIE_GROUNDING_GUARD", "0")
    assert grounding_guard_enabled() is False


def test_fabricated_figure_is_converted_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAGPIE_GROUNDING_GUARD", raising=False)
    blocks = [("notes.md", ["Content type: text\n\n---\nThe rent was 900 per month."])]
    ans, converted = _apply_grounding_guard(_answer("You paid $159.00."), blocks, "what did I pay?")
    assert converted is True
    assert ans.not_found is True and ans.answer == "" and ans.sources_used == []
    assert ans.not_found_topic == "what did I pay"


def test_supported_figure_passes_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAGPIE_GROUNDING_GUARD", raising=False)
    blocks = [("notes.md", ["Content type: text\n\n---\nThe rent was 900 per month."])]
    ans, converted = _apply_grounding_guard(_answer("Rent was 900."), blocks, "rent?")
    assert converted is False and ans.answer == "Rent was 900."


def test_image_only_context_kills_a_correct_answer_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented blind spot: an image block contributes no text, so a
    figure the model read correctly off the picture has no support. (The
    guard only judges numerals >= grounding.MIN_INTERESTING - prices, years,
    IDs - which is exactly what receipts and forms are made of.)"""
    monkeypatch.delenv("MAGPIE_GROUNDING_GUARD", raising=False)
    blocks = [("receipt.jpg", [_Img()])]
    ans, converted = _apply_grounding_guard(_answer("Total was $1,559.00."), blocks, "total?")
    assert converted is True and ans.not_found is True


def test_off_switch_preserves_image_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGPIE_GROUNDING_GUARD", "0")
    blocks = [("receipt.jpg", [_Img()])]
    ans, converted = _apply_grounding_guard(_answer("Total was $1,559.00."), blocks, "total?")
    assert converted is False
    assert ans.answer == "Total was $1,559.00." and ans.sources_used == ["receipt.jpg"]


def test_strict_grounding_is_not_an_off_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MAGPIE_STRICT_GROUNDING=0 only lets summaries count as support; with
    no summary in context it changes nothing - the guard still fires."""
    monkeypatch.delenv("MAGPIE_GROUNDING_GUARD", raising=False)
    monkeypatch.setenv("MAGPIE_STRICT_GROUNDING", "0")
    blocks = [("receipt.jpg", [_Img()])]
    _, converted = _apply_grounding_guard(_answer("Total was $1,559.00."), blocks, "total?")
    assert converted is True


def test_strict_grounding_off_lets_a_summary_support_a_figure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAGPIE_GROUNDING_GUARD", raising=False)
    summary = "Content type: llm-summary\n\n---\nReceipt total 1,559.00 at the deli."
    blocks = [("receipt.jpg", [summary, _Img()])]
    monkeypatch.setenv("MAGPIE_STRICT_GROUNDING", "1")
    _, converted_strict = _apply_grounding_guard(_answer("Total was $1,559.00."), blocks, "total?")
    monkeypatch.setenv("MAGPIE_STRICT_GROUNDING", "0")
    _, converted_loose = _apply_grounding_guard(_answer("Total was $1,559.00."), blocks, "total?")
    assert converted_strict is True and converted_loose is False
