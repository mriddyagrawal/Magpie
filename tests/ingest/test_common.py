"""Tests for src/ingest/common.py — hashing, markdown rendering, path helpers."""

from __future__ import annotations

from pathlib import Path

from src.ingest.common import (
    DEFAULT_BODY_MAX_CHARS,
    hash_file,
    render_summary_markdown,
    summary_output_path,
    title_from_path,
)
from src.stage2.parser import parse_summary_file


def test_hash_file_is_stable(tmp_path: Path):
    """Same bytes → same digest."""
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello world")
    assert hash_file(p) == hash_file(p)


def test_hash_file_changes_on_content_change(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello")
    a = hash_file(p)
    p.write_bytes(b"hello world")
    b = hash_file(p)
    assert a != b


def test_hash_file_is_16_hex_chars(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"x")
    h = hash_file(p)
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_render_summary_markdown_round_trips_through_parser(tmp_path: Path):
    """Output must parse cleanly via the Stage 2 parser — the whole contract."""
    md = render_summary_markdown(
        source_rel="foo/bar.md",
        title="My Title",
        body="This is the body content.",
        content_type="markdown",
        keywords=["k1", "k2"],
        entities=["Alice"],
        identifiers=["ID-123"],
    )
    f = tmp_path / "out.md"
    f.write_text(md, encoding="utf-8")
    parsed = parse_summary_file(f)
    assert parsed.source_path == "foo/bar.md"
    assert parsed.title == "My Title"
    assert "body content" in parsed.summary
    assert parsed.content_type == "markdown"
    assert parsed.keywords == ["k1", "k2"]
    assert parsed.key_entities == ["Alice"]
    assert parsed.identifiers == ["ID-123"]


def test_render_summary_markdown_handles_empty_optional_fields(tmp_path: Path):
    """Missing keywords/entities/identifiers render as '—' and parse to []."""
    md = render_summary_markdown(
        source_rel="x.txt",
        title="t",
        body="b",
        content_type="text",
    )
    f = tmp_path / "out.md"
    f.write_text(md, encoding="utf-8")
    parsed = parse_summary_file(f)
    assert parsed.keywords == []
    assert parsed.key_entities == []
    assert parsed.identifiers == []


def test_summary_output_path_uses_hash_prefix(tmp_path: Path):
    p = tmp_path / "a.py"
    p.write_text("print(1)", encoding="utf-8")
    out = summary_output_path(p, "t1")
    assert out.name.endswith("_t1.md")
    # Filename prefix is the 16-char hash
    prefix = out.name.removesuffix("_t1.md")
    assert len(prefix) == 16


def test_title_from_path_prettifies():
    assert title_from_path(Path("/tmp/my_awesome-doc.pdf")) == "my awesome doc"
    assert title_from_path(Path("short.py")) == "short"


def test_title_from_path_caps_at_80_chars():
    long_name = Path("/x/" + "a_" * 60 + ".pdf")   # very long file stem
    out = title_from_path(long_name)
    assert len(out) <= 80


def test_default_body_max_chars_reasonable():
    """Sanity: if someone accidentally sets this to 0 or a huge number, tests catch it."""
    assert 1_000 <= DEFAULT_BODY_MAX_CHARS <= 50_000
