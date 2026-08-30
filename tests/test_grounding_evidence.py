"""Evidence grounding mode (src/grounding.py, MAGPIE_GROUNDING=evidence).

The numerals check compares a number against the whole context, which is why
it needs a magnitude floor — small integers are everywhere and would rescue an
invented figure beside them. The evidence check compares the model's own quote
against the files and the answer's numbers against the quote, so there is no
floor: a $20 receipt is checked as hard as a $2,000 one.
"""

from __future__ import annotations

import pytest

from src import grounding
from src.grounding import (
    check,
    derivable,
    span_supported,
    unsupported_answer_numerals,
)


@pytest.fixture
def evidence_mode(monkeypatch):
    monkeypatch.setenv("MAGPIE_GROUNDING", "evidence")
    monkeypatch.setenv("MAGPIE_GROUNDING_ACTION", "refuse")


def test_default_mode_is_the_numerals_check(monkeypatch):
    monkeypatch.delenv("MAGPIE_GROUNDING", raising=False)
    assert grounding.mode() == "numerals"
    assert grounding.action() == "refuse"


def test_unknown_mode_falls_back_to_numerals(monkeypatch):
    monkeypatch.setenv("MAGPIE_GROUNDING", "whatever")
    assert grounding.mode() == "numerals"


def test_exact_quote_is_supported():
    ctx = "Cursor Pro · Jan 5, 2026 · Total $20.00\nThank you for your purchase."
    assert span_supported("Cursor Pro · Jan 5, 2026 · Total $20.00", ctx)


def test_quote_survives_case_punctuation_and_thousands_separators():
    ctx = "Wages, tips, other compensation 11378.50"
    assert span_supported("wages tips other compensation 11,378.50", ctx)


def test_letter_spaced_pdf_text_still_supports_a_quote():
    assert span_supported("19 March 2026", "1 9  M a r c h  2 0 2 6")


def test_a_quote_with_a_wrong_digit_is_not_supported():
    ctx = "Total $20.00 charged on Jan 5"
    assert not span_supported("Total $29.00 charged on Jan 5", ctx)


def test_imperfect_copy_of_words_is_tolerated_up_to_the_overlap_knob(monkeypatch):
    ctx = "The department chair is Dr. Elena Marquez, office Riley 214."
    span = "department chair Dr Elena Marquez office Riley 214"
    assert span_supported(span, ctx)
    monkeypatch.setenv("MAGPIE_EVIDENCE_MIN_OVERLAP", "1.0")
    assert span_supported("chair Dr Elena Marquez", ctx)  # exact substring still fine
    assert not span_supported("chair Dr Elena Marquez said hello", ctx)


def test_invented_quote_is_not_supported():
    assert not span_supported("Dorm room charge $159.00", "housing handbook with no charges")


def test_small_numbers_are_checked_in_evidence_mode():
    """The whole point: nothing below 100 slips through."""
    spans = ["Cursor Pro · Jan 5, 2026 · Total $20.00"]
    assert unsupported_answer_numerals("$20.00 on Jan 5", spans) == []
    assert unsupported_answer_numerals("$25.00 on Jan 5", spans) == ["25.00"]
    assert unsupported_answer_numerals("$20.00 on Jan 7", spans) == ["7"]


def test_numbers_echoed_from_the_question_are_not_claims():
    spans = ["Fall 2025 term GPA 3.86"]
    assert unsupported_answer_numerals("Your Fall 2025 GPA was 3.86", spans, "What was my GPA in Fall 2025?") == []


def test_arithmetic_over_quoted_numbers_is_allowed():
    spans = ["Flight GSP-BDL $170.18", "Flight HVN-GSP $214.90"]
    assert unsupported_answer_numerals("Total $385.08 for the two flights", spans) == []
    assert unsupported_answer_numerals("The second cost $44.72 more", spans) == []
    assert unsupported_answer_numerals("Two flights", spans) == []


def test_arithmetic_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("MAGPIE_EVIDENCE_ARITHMETIC", "0")
    assert not derivable("44.72", ["170.18", "214.90"])
    assert derivable("385.08", ["170.18", "214.90"])  # sums stay (the numerals-mode rule)


def test_check_refuses_when_no_span_is_in_the_files(evidence_mode):
    v = check("You paid $159.00", "housing handbook with no charges",
              evidence=["Dorm room: $159.00 per semester"], question="dorm room?")
    assert not v.ok and "no quoted span" in v.reason


def test_check_refuses_when_nothing_was_quoted(evidence_mode):
    v = check("You paid $159.00", "housing handbook", evidence=[], question="dorm room?")
    assert not v.ok and v.reason == "no evidence quoted"


def test_missing_quote_can_fall_back_to_numerals_when_not_required(evidence_mode, monkeypatch):
    monkeypatch.setenv("MAGPIE_EVIDENCE_REQUIRED", "0")
    assert check("The employer is Furman University.", "Employer: Furman University", evidence=[]).ok
    assert not check("You paid $159.00", "no figures here", evidence=[]).ok


def test_check_passes_a_grounded_answer(evidence_mode):
    ctx = "--- File 1 ---\nCursor Pro · Jan 5, 2026 · Total $20.00"
    v = check("$20.00, charged on Jan 5", ctx, evidence=["Cursor Pro · Jan 5, 2026 · Total $20.00"])
    assert v.ok


def test_check_refuses_a_number_outside_the_quotes(evidence_mode):
    ctx = "Cursor Pro · Jan 5, 2026 · Total $20.00\nInvoice 4411 · Feb 2 · Total $45.00"
    v = check("$45.00 on Jan 5", ctx, evidence=["Cursor Pro · Jan 5, 2026 · Total $20.00"])
    assert not v.ok and "45.00" in v.reason


def test_numeral_check_inside_evidence_mode_can_be_switched_off(evidence_mode, monkeypatch):
    monkeypatch.setenv("MAGPIE_EVIDENCE_NUMERALS", "0")
    ctx = "Cursor Pro · Jan 5, 2026 · Total $20.00"
    assert check("$45.00 on Jan 5", ctx, evidence=["Cursor Pro · Jan 5, 2026 · Total $20.00"]).ok


def test_evidence_mode_without_quotes_available_uses_the_numerals_check(evidence_mode):
    """A provider that composes its own prompt (magpie-cloud) returns no
    `evidence`; the caller passes None and the old rule applies."""
    assert not check("You paid $159.00", "no figures here", evidence=None).ok
    assert check("You paid $20.00", "Total $20.00", evidence=None).ok


def test_off_mode_checks_nothing(monkeypatch):
    monkeypatch.setenv("MAGPIE_GROUNDING", "off")
    assert check("You paid $159.00", "nothing", evidence=[]).ok


def test_numerals_floor_is_a_knob(monkeypatch):
    monkeypatch.setenv("MAGPIE_GROUNDING", "numerals")
    assert check("It cost 20 dollars", "no figures").ok  # bare integer under the floor
    assert not check("It cost $20.00", "no figures").ok  # decimal: audited at any size
    monkeypatch.setenv("MAGPIE_GROUNDING_MIN_NUMERAL", "0")
    assert not check("It cost 20 dollars", "no figures").ok


def test_local_grammar_includes_evidence_only_in_evidence_mode(monkeypatch):
    from src.answer import Answer, build_answer_agent

    monkeypatch.setenv("MAGPIE_FORCE_PROVIDER", "local")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("MAGPIE_GROUNDING", "numerals")
    grammar = getattr(build_answer_agent(cite_inline=False), "_grammar", "") or ""
    assert "evidence" not in grammar
    assert "answer" in grammar and "sources_used" in grammar
    monkeypatch.setenv("MAGPIE_GROUNDING", "evidence")
    grammar = getattr(build_answer_agent(cite_inline=False), "_grammar", "") or ""
    assert grammar.index("evidence") < grammar.index("answer")  # quote first, then answer
    assert Answer(answer="x", sources_used=[], not_found=False, not_found_topic="").evidence == []


def test_answer_step_refuses_an_unsupported_quote_and_warn_lets_it_through(tmp_path, monkeypatch):
    import asyncio

    import src.answer as ans_mod
    from src.answer import Answer, answer_question

    doc = tmp_path / "handbook.txt"
    doc.write_text("Housing handbook. Quiet hours start at 11 pm. No charges are listed here.\n" * 5, encoding="utf-8")
    monkeypatch.setenv("MAGPIE_FORCE_PROVIDER", "local")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("MAGPIE_GROUNDING", "evidence")
    monkeypatch.setenv("MAGPIE_KV_CACHE", "0")

    class FakeAgent:
        _system_prompt = "sys"

        def __init__(self):
            self.messages = []

        async def run(self, message, **kw):
            self.messages.append(message)
            return Answer(evidence=["Dorm room: $159.00 per semester"], answer="$159.00",
                          sources_used=["1"], not_found=False, not_found_topic="")

    monkeypatch.setenv("MAGPIE_GROUNDING_ACTION", "refuse")
    agent = FakeAgent()
    out = asyncio.run(answer_question(agent, "How much did I pay for my dorm room?", [str(doc)]))
    assert out.not_found is True and out.answer == "" and out.evidence == []
    assert any("EVIDENCE:" in part for part in agent.messages[0] if isinstance(part, str))
    assert ans_mod.LAST_ROUTE["grounding_flagged"] == 1.0

    monkeypatch.setenv("MAGPIE_GROUNDING_ACTION", "warn")
    out = asyncio.run(answer_question(FakeAgent(), "How much did I pay for my dorm room?", [str(doc)]))
    assert out.answer == "$159.00" and out.not_found is False
    assert ans_mod.LAST_ROUTE["grounding_flagged"] == 1.0

    monkeypatch.setenv("MAGPIE_GROUNDING", "numerals")
    agent = FakeAgent()
    asyncio.run(answer_question(agent, "How much did I pay for my dorm room?", [str(doc)]))
    assert not any("EVIDENCE:" in part for part in agent.messages[0] if isinstance(part, str))
