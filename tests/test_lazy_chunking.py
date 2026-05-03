"""Tests for src/content.py:extract_pdf_relevant_pages — the lazy-chunking
primitive used at answer time for long PDFs.

Builds a synthetic PDF in-memory (pymupdf) so tests are hermetic — no fixture
files on disk, no external tooling. Each test sets up the page text it cares
about, asserts on which pages get picked.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_pdf(tmp_path: Path, pages: list[str], name: str = "synthetic.pdf") -> Path:
    """Create a tiny PDF with one paragraph per page. Returns the file path."""
    import pymupdf
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()  # default A4
        page.insert_text((50, 100), text, fontsize=12)
    out = tmp_path / name
    doc.save(str(out))
    doc.close()
    return out


# ---------------------------------------------------------------------------
# extract_pdf_relevant_pages — the page picker itself
# ---------------------------------------------------------------------------

def test_picks_page_with_most_keyword_hits(tmp_path: Path):
    from src.content import extract_pdf_relevant_pages

    pdf = _make_pdf(tmp_path, [
        "Cover page about classical mechanics",                      # page 1
        "Chapter 1 introduces Newton's laws",                         # page 2
        "Chapter 13 covers Hamiltonian mechanics in detail",          # page 3
        "Section 13.7 proves Liouville's theorem about phase space",  # page 4
        "Bibliography",                                                # page 5
    ])

    out = extract_pdf_relevant_pages(
        pdf, keywords=["liouville"], max_pages=1, context_pages=0
    )
    assert "PDF page 4" in out
    assert "Liouville" in out
    # Other pages NOT included (context_pages=0 + max_pages=1)
    assert "Cover page" not in out
    assert "Bibliography" not in out


def test_includes_context_pages(tmp_path: Path):
    from src.content import extract_pdf_relevant_pages

    pdf = _make_pdf(tmp_path, [
        "page 1 intro",
        "page 2 setup",
        "page 3 LIOUVILLE keyword here",
        "page 4 followup",
        "page 5 conclusion",
    ])

    out = extract_pdf_relevant_pages(
        pdf, keywords=["liouville"], max_pages=1, context_pages=1
    )
    # Match plus ±1 → pages 2, 3, 4
    assert "PDF page 2" in out
    assert "PDF page 3" in out
    assert "PDF page 4" in out
    # Pages outside context window NOT included
    assert "PDF page 1" not in out
    assert "PDF page 5" not in out


def test_returns_empty_when_no_match(tmp_path: Path):
    from src.content import extract_pdf_relevant_pages

    pdf = _make_pdf(tmp_path, [
        "Cover page",
        "Body text",
    ])
    out = extract_pdf_relevant_pages(pdf, keywords=["totally_absent_term"])
    assert out == ""


def test_returns_empty_when_keywords_empty(tmp_path: Path):
    from src.content import extract_pdf_relevant_pages

    pdf = _make_pdf(tmp_path, ["any text"])
    assert extract_pdf_relevant_pages(pdf, keywords=[]) == ""
    assert extract_pdf_relevant_pages(pdf, keywords=["", "  "]) == ""


def test_case_insensitive_match(tmp_path: Path):
    from src.content import extract_pdf_relevant_pages

    pdf = _make_pdf(tmp_path, [
        "Empty cover",
        "Discussion of HAMILTONIAN MECHANICS in caps",
        "More body text",
    ])
    out = extract_pdf_relevant_pages(
        pdf, keywords=["hamiltonian"], max_pages=1, context_pages=0
    )
    assert "PDF page 2" in out


def test_pages_emit_in_document_order(tmp_path: Path):
    """Top-K by score, but emitted in document order — not score order — so
    the LLM sees the PDF flowing naturally."""
    from src.content import extract_pdf_relevant_pages

    pdf = _make_pdf(tmp_path, [
        "intro mentions Hamiltonian once",     # page 1: 1 hit
        "filler",                                # page 2
        "page 3 has Hamiltonian Hamiltonian Hamiltonian",  # page 3: 3 hits
        "filler",                                # page 4
        "page 5 has Hamiltonian Hamiltonian",  # page 5: 2 hits
    ])

    out = extract_pdf_relevant_pages(
        pdf, keywords=["hamiltonian"], max_pages=3, context_pages=0
    )
    # All three matching pages, in document order: 1, 3, 5
    p1 = out.find("PDF page 1")
    p3 = out.find("PDF page 3")
    p5 = out.find("PDF page 5")
    assert p1 != -1 and p3 != -1 and p5 != -1
    assert p1 < p3 < p5


def test_respects_max_chars(tmp_path: Path):
    """Output is capped at max_chars even if more matches exist."""
    from src.content import extract_pdf_relevant_pages

    big_text = "Hamiltonian " * 200  # ~2400 chars per page
    pdf = _make_pdf(tmp_path, [big_text] * 10)  # 10 pages, all match

    out = extract_pdf_relevant_pages(
        pdf, keywords=["hamiltonian"],
        max_pages=10, context_pages=0, max_chars=3000,
    )
    # Cap fires somewhere around 3000 chars (loop breaks AFTER adding the
    # block that crosses, so total can be slightly over).
    assert len(out) <= 6000  # generous; key thing is it didn't emit all 10 pages
    assert len(out) > 0


def test_handles_missing_file_gracefully(tmp_path: Path):
    """A non-existent PDF returns empty, doesn't raise."""
    from src.content import extract_pdf_relevant_pages

    fake = tmp_path / "does_not_exist.pdf"
    out = extract_pdf_relevant_pages(fake, keywords=["anything"])
    assert out == ""


# ---------------------------------------------------------------------------
# build_content_blocks integration
# ---------------------------------------------------------------------------

def test_build_content_blocks_uses_lazy_for_long_pdf_with_keywords(tmp_path: Path):
    """Long PDF + keywords → block contains the keyword-matching pages."""
    from src.content import build_content_blocks

    # Make 100 pages, only one mentions "Liouville"
    pages = [f"page {i+1} filler content " * 50 for i in range(100)]
    pages[42] = "page 43 Liouville theorem proves volume preservation in phase space"
    pdf = _make_pdf(tmp_path, pages, name="long.pdf")

    blocks = build_content_blocks(
        pdf, max_chars=4000, max_pdf_pages=5,
        search_keywords=["liouville"],
    )
    assert len(blocks) == 1
    body = blocks[0]
    # Header indicates lazy-chunking fired
    assert "pages selected by query keywords" in body
    # The matching page is in the output
    assert "PDF page 43" in body or "Liouville" in body


def test_build_content_blocks_falls_back_when_keywords_dont_match(tmp_path: Path):
    """Long PDF + keywords that match no page → fall back to first-N-chars."""
    from src.content import build_content_blocks

    pages = [f"page {i+1} filler " * 50 for i in range(20)]
    pdf = _make_pdf(tmp_path, pages, name="long_nomatch.pdf")

    blocks = build_content_blocks(
        pdf, max_chars=2000, max_pdf_pages=5,
        search_keywords=["completely_absent_term"],
    )
    assert len(blocks) == 1
    body = blocks[0]
    # Did NOT use the lazy path (no "pages selected" header)
    assert "pages selected by query keywords" not in body
    # Did use the regular pdf header
    assert body.startswith("Content type: pdf\n\n---\n")


def test_build_content_blocks_short_pdf_ignores_keywords(tmp_path: Path):
    """A short PDF that fits in max_chars is returned whole, keywords ignored.

    Rationale: if the whole file fits in the LLM budget, sending all of it
    is strictly better than filtering — the LLM has the full context.
    """
    from src.content import build_content_blocks

    pdf = _make_pdf(tmp_path, [
        "tiny page about Hamiltonians",
        "another small page",
    ])

    blocks = build_content_blocks(
        pdf, max_chars=10_000, max_pdf_pages=5,
        search_keywords=["hamiltonian"],
    )
    body = blocks[0]
    # Regular path, NOT lazy
    assert "pages selected by query keywords" not in body
    # Both pages' content present
    assert "Hamiltonians" in body or "another small page" in body


def test_build_content_blocks_no_keywords_uses_regular_path(tmp_path: Path):
    """Without keywords (e.g., when search_keywords=None), behavior is unchanged."""
    from src.content import build_content_blocks

    pages = [f"page {i+1} content " * 30 for i in range(20)]
    pdf = _make_pdf(tmp_path, pages, name="nokw.pdf")

    blocks = build_content_blocks(
        pdf, max_chars=2000, max_pdf_pages=5,
        search_keywords=None,
    )
    body = blocks[0]
    assert "pages selected by query keywords" not in body
    assert body.startswith("Content type: pdf\n\n---\n")


def test_build_content_blocks_without_keywords_arg_at_all(tmp_path: Path):
    """Backward compat: callers that don't pass search_keywords keep working."""
    from src.content import build_content_blocks

    pdf = _make_pdf(tmp_path, ["short content"])
    blocks = build_content_blocks(pdf, max_chars=10_000, max_pdf_pages=5)
    assert len(blocks) == 1


# ---------------------------------------------------------------------------
# TOC-page filter — real-world bug (2026-04-25): TOC pages list every chapter
# heading, so they outscore actual content pages on keyword count. Without
# filtering, lazy chunking would pick the TOC and the LLM would say "I only
# see chapter titles, not content."
# ---------------------------------------------------------------------------

def test_looks_like_toc_page_detects_typical_toc():
    from src.content import _looks_like_toc_page

    toc_text = """\
Contents

CHAPTER 1 Newton's Laws of Motion 1
1.1 Classical Mechanics 2
1.2 Space and Time 4
1.3 Mass and Force 8
1.4 Newton's First and Second Laws 13
CHAPTER 2 Projectiles and Charged Particles 23
2.1 Air Resistance 23
2.2 Linear Air Resistance 24
"""
    assert _looks_like_toc_page(toc_text)


def test_looks_like_toc_page_misses_content_page():
    from src.content import _looks_like_toc_page

    content_text = """\
Newton's first law states that an object at rest stays at rest, and an
object in motion stays in motion at constant velocity, unless acted upon
by a net external force. This is also known as the law of inertia.

Mathematically, we can express this as the condition that for any
inertial frame, dp/dt = 0 when F = 0. The Lagrangian formulation, which
we will introduce in chapter 7, gives a more general view of this
principle through the action functional.
"""
    assert not _looks_like_toc_page(content_text)


def test_looks_like_toc_page_handles_chapter_opening_with_one_section():
    """A chapter-opening page that mentions ONE section number isn't a TOC."""
    from src.content import _looks_like_toc_page

    chapter_open = """\
Chapter 4

Energy

In the previous chapter we discussed momentum. Now we turn to energy.

4.1 Kinetic Energy and Work

Consider a particle of mass m subject to a net force F. The work done by
the force as the particle moves from point a to point b is defined as ...
"""
    assert not _looks_like_toc_page(chapter_open)


def test_extract_pdf_relevant_pages_skips_toc_pages(tmp_path: Path):
    """End-to-end: TOC page is not picked even though it has many keyword hits."""
    from src.content import extract_pdf_relevant_pages

    toc_page = (
        "Contents\n"
        "CHAPTER 1 Newton's Laws 1\n"
        "1.1 Force and motion 2\n"
        "1.2 Kinetic energy basics 8\n"
        "CHAPTER 7 Lagrange's Equations 230\n"
        "7.1 Calculus of Variations 232\n"
        "7.2 The Lagrangian L = T - V 245\n"
        "7.3 Euler-Lagrange Equation 250\n"
    )
    content_page = (
        "Chapter 7 introduces the Lagrangian function L = T - V where "
        "T is the kinetic energy and V is the potential energy. The "
        "Euler-Lagrange equation gives the equations of motion."
    )

    pdf = _make_pdf(tmp_path, [
        "Cover",
        toc_page,           # page 2 — TOC, has many hits
        "filler",
        content_page,        # page 4 — real content about Lagrangian
    ])

    out = extract_pdf_relevant_pages(
        pdf,
        keywords=["Lagrangian", "Euler-Lagrange", "kinetic energy"],
        max_pages=2,
        context_pages=0,
    )
    # The content page (4) should be picked, NOT the TOC page (2)
    assert "PDF page 4" in out
    assert "PDF page 2" not in out


# ---------------------------------------------------------------------------
# Book-page label extraction (top/bottom of page) for dual-page citation
# ---------------------------------------------------------------------------

def test_extract_book_page_label_finds_top_of_page_number():
    """Taylor-style: a book's printed page number is the first line of text."""
    from src.content import _extract_book_page_label

    text = "254\nChapter 7 Lagrange's Equations\n\nThe Lagrangian L = T - U is defined..."
    assert _extract_book_page_label(text) == "254"


def test_extract_book_page_label_finds_roman_numeral():
    """Front matter usually uses lowercase roman numerals (i, ii, iii, iv...)."""
    from src.content import _extract_book_page_label

    text = "vi\nContents\n\nChapter 1 starts at..."
    assert _extract_book_page_label(text) == "vi"


def test_extract_book_page_label_finds_bottom_of_page_number():
    """Some books put the page number at the bottom (footer style)."""
    from src.content import _extract_book_page_label

    text = "Chapter 4 introduces the concept...\n\nMore text here.\n\n105"
    assert _extract_book_page_label(text) == "105"


def test_extract_book_page_label_returns_none_when_absent():
    """Pages without a clean page-number line return None."""
    from src.content import _extract_book_page_label

    text = "All text here is full sentences. No page number anywhere."
    assert _extract_book_page_label(text) is None


def test_extract_book_page_label_ignores_inline_numbers():
    """Numbers embedded in prose are not mistaken for page labels."""
    from src.content import _extract_book_page_label

    text = "Equation 7.13 introduces the variable on line 254 of the appendix."
    assert _extract_book_page_label(text) is None


def test_extract_pdf_relevant_pages_emits_dual_page_anchors(tmp_path: Path):
    """When book page labels are detectable, each anchor shows both forms."""
    from src.content import extract_pdf_relevant_pages

    # Page text where line 1 is the book's page number — Taylor's pattern.
    pdf = _make_pdf(tmp_path, [
        "Cover with no number",
        "vi\nFront Matter\n\nWelcome to the textbook",          # PDF p2 = book p vi
        "Filler",
        "254\nChapter 7\n\nLagrangian formulation introduces L=T-V",  # PDF p4 = book p 254
    ])

    out = extract_pdf_relevant_pages(
        pdf, keywords=["Lagrangian"], max_pages=1, context_pages=0
    )
    # Anchor on the matching content page shows both digital + book labels
    assert "PDF page 4 (book p. 254)" in out


def test_extract_pdf_relevant_pages_anchor_omits_book_when_absent(tmp_path: Path):
    """If a page lacks a clean page-label line, anchor falls back to PDF only."""
    from src.content import extract_pdf_relevant_pages

    pdf = _make_pdf(tmp_path, [
        "Cover with no number",
        "Just prose text, the Lagrangian is mentioned somewhere here",  # no header number
    ])

    out = extract_pdf_relevant_pages(
        pdf, keywords=["Lagrangian"], max_pages=1, context_pages=0
    )
    # No book label → just "## PDF page 2" (no parenthetical)
    assert "PDF page 2" in out
    assert "(book p." not in out
