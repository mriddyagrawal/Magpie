"""Tests for src/ingest/ripgrep.py — answer-time line lookup for T0 files."""

from __future__ import annotations

from pathlib import Path

from src.ingest.ripgrep import (
    _build_pattern,
    _python_fallback_hits,
    _tokens_for_pattern,
    format_hits_block,
    search_file,
)


def test_tokens_strip_stop_words_and_short_tokens():
    toks = _tokens_for_pattern("what is the total amount on May 4 2026")
    # stopwords (`what`, `is`, `the`, `on`) dropped; short single-letter gone.
    assert "total" in toks
    assert "amount" in toks
    assert "May" in toks
    assert "2026" in toks
    for stop in {"what", "is", "the", "on"}:
        assert stop not in toks


def test_tokens_keep_exact_ids():
    toks = _tokens_for_pattern("invoice R2NDSL paid $170.45")
    assert "R2NDSL" in toks
    assert "$170.45" in toks


def test_build_pattern_empty_question_returns_none():
    assert _build_pattern("the a of") is None  # all stopwords


def test_build_pattern_escapes_metacharacters():
    p = _build_pattern("find $170.45")
    assert p is not None
    assert r"\$170\.45" in p


def test_python_fallback_finds_lines(tmp_path: Path):
    log = tmp_path / "bank.log"
    log.write_text(
        "2026-03-02 Whole Foods $127.43\n"
        "2026-03-05 Shell Gas $52.19\n"
        "2026-03-10 Netflix $15.99\n",
        encoding="utf-8",
    )
    hits = _python_fallback_hits(log, r"Shell|Netflix", max_hits=5)
    assert len(hits) == 2
    assert any("Shell" in h.text for h in hits)
    assert any("Netflix" in h.text for h in hits)


def test_python_fallback_respects_max_hits(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("match\n" * 100, encoding="utf-8")
    hits = _python_fallback_hits(f, r"match", max_hits=7)
    assert len(hits) == 7


def test_python_fallback_returns_line_numbers(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("line one\nmatch line two\nline three\nmatch line four\n", encoding="utf-8")
    hits = _python_fallback_hits(f, r"match", max_hits=5)
    assert hits[0].line_number == 2
    assert hits[1].line_number == 4


def test_python_fallback_handles_bad_regex(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("hello", encoding="utf-8")
    # Unterminated group — re.compile raises — should yield empty list, not crash.
    assert _python_fallback_hits(f, r"(?P<", max_hits=5) == []


def test_search_file_returns_empty_when_no_tokens(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("content", encoding="utf-8")
    assert search_file(f, "the a of") == []


def test_format_hits_block_is_human_readable(tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("alpha\nbravo match\n", encoding="utf-8")
    hits = _python_fallback_hits(f, r"bravo", max_hits=5)
    block = format_hits_block(f, hits)
    assert "notes.txt" in block
    assert "bravo" in block
    assert "2:" in block  # line number 2 rendered


def test_format_hits_block_empty_for_no_hits(tmp_path: Path):
    f = tmp_path / "x.txt"
    assert format_hits_block(f, []) == ""


def test_search_file_end_to_end_uses_either_backend(tmp_path: Path):
    """Whichever backend is available, search_file should find matches."""
    f = tmp_path / "tx.csv"
    f.write_text(
        "date,vendor,amount\n"
        "2026-03-02,Breeze Airways,170.45\n"
        "2026-03-05,Shell,52.19\n",
        encoding="utf-8",
    )
    hits = search_file(f, "Breeze amount")
    assert any("Breeze" in h.text for h in hits)
