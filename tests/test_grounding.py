"""Unit tests for the deterministic groundedness guard.

The guard is the last thing between a fabricated figure and the user, and
it is deliberately conservative — these tests pin both halves of that:
what it must catch, and what it must leave alone.
"""

from __future__ import annotations

from src.grounding import (
    is_sum_of,
    looks_fabricated,
    numerals,
    unsupported_numerals,
)


def test_numerals_ignores_citation_markers_and_small_numbers():
    found = numerals("The chair is Dr. Marquez[1] and there are 3 rooms, total 1,183.87.")
    assert found == ["1183.87"]


def test_thousands_separators_match_a_bare_context_figure():
    assert unsupported_numerals("Withheld 1,183.87", "tax withheld 1183.87 usd") == []


def test_letter_spaced_pdf_text_still_counts_as_support():
    """Flyers and poster exports put a space between every glyph, so '2026'
    extracts as '2 0 2 6'. A literal search would report a fabrication that
    is sitting right there in the file."""
    assert unsupported_numerals("Friday, 19 March 2026", "1 9  M a r c h  2 0 2 6") == []


def test_a_computed_total_is_not_a_fabrication():
    context = "Trip fare 41.80 booking fee 4.97 surcharge 3.75 state 0.42 wait 0.38"
    assert unsupported_numerals("The total is 51.32", context) == []


def test_an_invented_figure_is_reported():
    assert unsupported_numerals("It cost $159.00", "no dollar figures here") == ["159.00"]


def test_looks_fabricated_only_fires_when_every_number_is_unsupported():
    """The sem6 absence probe: asked what he paid for his dorm room, the
    model answered '$159.00' — a figure in no retrieved file."""
    assert looks_fabricated("You paid $159.00", "housing handbook with no charges")


def test_one_wrong_figure_among_right_ones_passes_through():
    """A misreading is not a fabrication. The user gets the citations and
    can check; blanking the answer would cost more than it saves."""
    context = "wages 11378.50 federal 1183.87"
    answer = "Wages were 11,378.50 and state tax was 999.99"
    assert not looks_fabricated(answer, context)
    assert unsupported_numerals(answer, context) == ["999.99"]


def test_an_answer_with_no_numbers_is_never_fabricated_by_this_rule():
    assert not looks_fabricated("The employer is Furman University.", "unrelated text")


def test_is_sum_of_rejects_a_number_that_is_merely_close():
    assert not is_sum_of("100.00", ["41.80", "4.97"])
    assert is_sum_of("46.77", ["41.80", "4.97"])


def test_summaries_do_not_count_as_evidence():
    """An index-time summary is the model's own earlier output. Letting it
    ground a later answer is how a fabrication launders itself: the sem6
    invitation letter has mangled digits, its summary states a salary of
    2,500.00, and the answer step repeated that figure with the summary as
    its apparent support."""
    from src.grounding import strip_generated_blocks

    blocks = [
        "Content type: llm-summary\nMonthly salary 2,500.00 EUR",
        "Content type: pdf\nSalary line unreadable",
    ]
    kept = strip_generated_blocks(blocks)
    assert len(kept) == 1 and "2,500.00" not in kept[0]


def test_scrubber_removes_figures_absent_from_the_source(tmp_path):
    """Index-time half of the same fix: a number the summarizer invented
    never reaches the summary file in the first place."""
    from src.stage1.summarize import FileSummary, scrub_invented_numbers

    src = tmp_path / "letter.txt"
    # Padded past MIN_SOURCE_CHARS: below that the file counts as unreadable
    # and the scrubber correctly declines to check anything at all.
    src.write_text(
        "Dear Mr Sah, we invite you to Bochum. Salary redacted. " + ("filler text " * 30),
        encoding="utf-8",
    )
    s = FileSummary(
        title="letter",
        summary="Invitation to Bochum with a monthly salary of 2,500.00 EUR.",
        content_type="text",
        keywords=[],
        key_entities=[],
        identifiers=[],
    )
    assert "[unreadable]" in scrub_invented_numbers(s, src).summary


def test_scrubber_keeps_figures_that_are_in_the_source(tmp_path):
    from src.stage1.summarize import FileSummary, scrub_invented_numbers

    src = tmp_path / "w2.txt"
    src.write_text("wages 11378.50 federal 1183.87", encoding="utf-8")
    s = FileSummary(
        title="w2",
        summary="Wages of 11,378.50 with 1,183.87 withheld.",
        content_type="text",
        keywords=[],
        key_entities=[],
        identifiers=[],
    )
    out = scrub_invented_numbers(s, src)
    assert "[unreadable]" not in out.summary
    assert "11,378.50" in out.summary


def test_scrubber_leaves_scanned_files_alone(tmp_path, monkeypatch):
    """A scanned page has no text layer, so nothing in its summary can be
    matched — including figures a vision pass read correctly off the image.
    Scrubbing there deletes good data. Learned the hard way: a hotel folio
    lost its confirmation number, both stay dates and its total."""
    import src.stage1.summarize as sm
    from src.stage1.summarize import FileSummary, scrub_invented_numbers

    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        sm, "build_content_blocks",
        lambda *a, **k: ["Content type: pdf (scanned / image-only — 1 page(s) as images)"],
    )
    s = FileSummary(
        title="folio", summary="Total charged $1,234.56 for the stay.",
        content_type="pdf", keywords=[], key_entities=[], identifiers=[],
    )
    assert "[unreadable]" not in scrub_invented_numbers(s, src).summary


def test_scrubber_counts_the_filename_as_evidence(tmp_path, monkeypatch):
    """A year or invoice number that appears only in the path is grounded,
    not invented."""
    import src.stage1.summarize as sm
    from src.stage1.summarize import FileSummary, scrub_invented_numbers

    src = tmp_path / "W-2_Form_2025_Sah.pdf"
    src.write_text("x" * 400, encoding="utf-8")
    monkeypatch.setattr(sm, "build_content_blocks", lambda *a, **k: ["x" * 400])
    s = FileSummary(
        title="w2", summary="A W-2 statement for the year 2025.",
        content_type="pdf", keywords=[], key_entities=[], identifiers=[],
    )
    assert "2025" in scrub_invented_numbers(s, src).summary


def test_summarizer_gets_no_timestamp_but_the_answer_step_does():
    """The 'Current date and time' line lets the ANSWER step resolve 'this
    semester' or 'is this receipt recent'. At index time it is just a
    plausible date sitting in the context, and a 3B copies it: after the
    prompt-example fix, `2026-08-27` (the run date) showed up as a claimed
    document identifier in a Cursor invoice, a finance handout and a VR
    storyboard, none of which contain it."""
    from src.answer import Answer
    from src.llm import _wants_timestamp
    from src.stage1.summarize import FileSummary

    assert _wants_timestamp(FileSummary) is False
    assert _wants_timestamp(Answer) is True


def test_control_characters_are_stripped_from_extracted_text(tmp_path, monkeypatch):
    """A single NUL byte cost four eval questions. `Receipt-2794-8324.pdf`
    extracted its invoice number as "9257BD07\\x000001"; the summarizer then
    produced a content-free summary AND leaked raw chat-template tokens into
    it, and four answers came back parroting that empty summary. It was the
    only file across three corpora with NUL bytes and the only one with
    leaked tokens."""
    import src.content as content

    monkeypatch.setattr(
        content, "_build_content_blocks",
        lambda *a, **k: ["Invoice number 9257BD07\x000001\x0btail", b"not-a-str"],
    )
    out = content.build_content_blocks(
        tmp_path / "x.pdf", max_chars=100, max_pdf_pages=1
    )
    assert out[0] == "Invoice number 9257BD07 0001tail"
    assert out[1] == b"not-a-str"  # non-text blocks pass through untouched


def test_scrubber_keeps_newlines_and_tabs():
    from src.content import scrub_control_chars

    assert scrub_control_chars("a\nb\tc\r\nd") == "a\nb\tc\r\nd"
