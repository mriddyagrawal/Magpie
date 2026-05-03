"""Tests for src/answer.py path-suffix handling.

Two related concerns:
1. The whitespace-tolerant filter must accept LLM citations that include a
   trailing `[book pp. N-M / PDF pp. X-Y]` suffix — added per the dual-page
   citation system-prompt rule.
2. The matched output must PRESERVE the suffix so the user sees both page
   forms in `Sources used:`.
"""

from __future__ import annotations

from src.answer import _normalize_path_for_match


def test_normalize_strips_page_suffix():
    """`<path> [book pp. 254-258 / PDF pp. 269-273]` normalizes to bare path."""
    raw = "/home/me/textbook.pdf  [book pp. 254-258 / PDF pp. 269-273]"
    assert _normalize_path_for_match(raw) == "/home/me/textbook.pdf"


def test_normalize_strips_short_suffix():
    """A minimal `[PDF p. 7]` suffix also gets stripped."""
    raw = "/home/me/notes.pdf [PDF p. 7]"
    assert _normalize_path_for_match(raw) == "/home/me/notes.pdf"


def test_normalize_strips_suffix_with_arbitrary_content():
    """Forgive any [...] suffix — LLM phrasing varies."""
    raw = "/path.pdf  [pages around §7.3]"
    assert _normalize_path_for_match(raw) == "/path.pdf"


def test_normalize_no_suffix_unchanged():
    """A path without a suffix passes through unchanged (modulo whitespace)."""
    raw = "/home/me/file.pdf"
    assert _normalize_path_for_match(raw) == "/home/me/file.pdf"


def test_normalize_combines_suffix_strip_with_whitespace_collapse():
    """Both fixes (suffix + whitespace) work together."""
    # User's path has a literal double-space in it (corpus quirk),
    # AND the LLM appended a citation suffix.
    raw = "/home/me/101  mus/file.pdf  [book pp. 1-3]"
    # After normalize: suffix removed, whitespace collapsed
    assert _normalize_path_for_match(raw) == "/home/me/101 mus/file.pdf"


def test_normalize_handles_trailing_brackets_with_extra_whitespace():
    """Extra trailing whitespace after the bracket is also tolerated."""
    raw = "/home/me/x.pdf   [PDF p. 5]   "
    assert _normalize_path_for_match(raw) == "/home/me/x.pdf"
