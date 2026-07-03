"""Regression tests for cli/notspotlight/display.py:file_link.

The bug: when the LLM appends `[book pp. N-M / PDF pp. X-Y]` to a sources_used
path (per the dual-page citation system-prompt rule), `file_link` was wrapping
the entire string inside `[link=...]...[/link]`, producing nested unbalanced
markup that crashed Rich. Fix: split the bracketed suffix off the path and
render it as plain dim text outside the link.

Tests run an actual Rich Console.print() against the output — that's the only
way to catch markup errors that the parser raises lazily.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console


_ANSI_RE = __import__("re").compile(r"\x1b\][^\x1b]*\x1b\\|\x1b\[[\d;]*m")


def _render_without_error(markup_string: str) -> str:
    """Push markup through a Rich Console — raises MarkupError on bad markup.

    Returns the rendered text with ANSI escape codes stripped, so test
    assertions can match human-visible substrings without fighting Rich's
    auto-highlighting (which colors numbers / dates / paths and inserts
    ANSI between adjacent characters).
    """
    console = Console(file=StringIO(), force_terminal=True, width=200)
    console.print(markup_string)
    raw = console.file.getvalue()
    return _ANSI_RE.sub("", raw)


def test_file_link_handles_bare_path():
    from cli.notspotlight.display import file_link

    out = _render_without_error(file_link("/home/me/file.pdf"))
    assert "/home/me/file.pdf" in out


def test_file_link_handles_path_with_book_pages_suffix():
    """The exact crash path from 2026-04-25 — must not raise MarkupError."""
    from cli.notspotlight.display import file_link

    raw = "/home/astavak/sem6/311/Taylor.pdf  [book pp. 254-258 / PDF pp. 269-273]"
    out = _render_without_error(file_link(raw))
    # Path renders + suffix renders, separately
    assert "/home/astavak/sem6/311/Taylor.pdf" in out
    assert "book pp. 254-258" in out
    assert "PDF pp. 269-273" in out


def test_file_link_handles_short_pdf_only_suffix():
    from cli.notspotlight.display import file_link

    out = _render_without_error(file_link("/home/me/notes.pdf [PDF p. 7]"))
    assert "/home/me/notes.pdf" in out
    assert "PDF p. 7" in out


def test_file_link_handles_pathological_link_close_tag_in_suffix():
    """Even if the LLM hallucinated `[/link]` literally in the suffix,
    Rich must not crash. This is the exact MarkupError shape that crashed
    the REPL on 2026-04-25 when the original error message contained a
    `[/link]` substring."""
    from cli.notspotlight.display import file_link

    # Adversarial: a [/link]-containing suffix is the worst case for
    # the link-tag wrapping bug.
    out = _render_without_error(file_link("/home/me/x.pdf [/link]"))
    assert "/home/me/x.pdf" in out


def test_print_error_with_bracketed_message_does_not_crash():
    """print_error must escape its message — otherwise an error string that
    contains `[...]` (e.g. a previous MarkupError's text) would itself crash
    inside print_error and lose the user's error feedback entirely."""
    from cli.notspotlight.display import print_error

    # Exact substring that crashed before:
    msg = "closing tag '[/link]' at position 41 doesn't match any open tag"
    # If escape isn't applied, console.print raises MarkupError. Otherwise
    # this completes normally.
    print_error(msg)


def test_print_error_with_path_suffix_in_message():
    """An error message that includes a path with bracket suffix must not crash."""
    from cli.notspotlight.display import print_error

    msg = "could not read /home/me/foo.pdf [book pp. 1-3 / PDF pp. 5-7]: Permission denied"
    print_error(msg)
