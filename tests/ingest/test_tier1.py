"""Tests for src/ingest/tier1.py — direct-embed path for text / code / config.

Core invariants:
  * No LLM call (run() is a pure file read + markdown render)
  * Raw bytes appear verbatim in the embedded body (this is the whole point
    of T1 — BM25 should hit exact tokens)
  * Filename always reaches identifiers, even on empty files
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest import tier1
from src.ingest.common import DEFAULT_BODY_MAX_CHARS, REPO_ROOT
from src.stage2.parser import parse_summary_file


@pytest.fixture
def isolate_summaries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect `SUMMARIES_DIR` so tests don't leak into the repo's real dir."""
    sdir = tmp_path / "summaries"
    sdir.mkdir()
    monkeypatch.setattr("src.ingest.common.SUMMARIES_DIR", sdir)
    monkeypatch.setattr("src.ingest.tier1.summary_output_path",
                        lambda path, tier: sdir / f"{path.stem}_{tier}.md")
    return sdir


def test_tier1_markdown_contains_raw_content_verbatim(isolate_summaries: Path, tmp_path: Path):
    src = tmp_path / "notes.md"
    src.write_text("# Project\n\nThe invoice total was $170.45.\n", encoding="utf-8")
    outcome = tier1.run(src, "notes.md")
    md_path = Path(outcome.summary_file_rel) if outcome.summary_file_rel else None
    assert md_path is not None
    if not md_path.is_absolute():
        md_path = REPO_ROOT / md_path
    if not md_path.exists():
        # Fixture may have redirected output; fall back to files in the isolated dir
        matches = list(isolate_summaries.glob("*_t1.md"))
        assert matches, "no T1 markdown written"
        md_path = matches[0]
    body = md_path.read_text(encoding="utf-8")
    assert "$170.45" in body, "raw discriminator must reach BM25 verbatim"
    assert "The invoice total" in body


def test_tier1_output_parses_as_stage2_summary(isolate_summaries: Path, tmp_path: Path):
    src = tmp_path / "app.py"
    src.write_text(
        "def get_qdrant_client():\n    import qdrant_client\n    return None\n",
        encoding="utf-8",
    )
    outcome = tier1.run(src, "app.py")
    md_path = isolate_summaries / f"{src.stem}_t1.md"
    assert md_path.exists()
    parsed = parse_summary_file(md_path)
    assert parsed.source_path == "app.py"
    assert "qdrant_client" in parsed.summary
    assert "app.py" in parsed.identifiers


def test_tier1_caps_body_at_max_chars(isolate_summaries: Path, tmp_path: Path):
    src = tmp_path / "big.txt"
    content = "abcdefghij" * 5_000   # 50k chars >> DEFAULT_BODY_MAX_CHARS (8k)
    src.write_text(content, encoding="utf-8")
    outcome = tier1.run(src, "big.txt")
    assert outcome.body_chars <= DEFAULT_BODY_MAX_CHARS


def test_tier1_handles_empty_file_gracefully(isolate_summaries: Path, tmp_path: Path):
    src = tmp_path / "empty.txt"
    src.write_text("", encoding="utf-8")
    outcome = tier1.run(src, "empty.txt")
    md_path = isolate_summaries / f"{src.stem}_t1.md"
    assert md_path.exists()
    body = md_path.read_text(encoding="utf-8")
    assert "empty file" in body.lower()


def test_tier1_handles_non_utf8_bytes(isolate_summaries: Path, tmp_path: Path):
    src = tmp_path / "binary.txt"
    src.write_bytes(b"hello \xff\xfe world")
    # Must not raise
    outcome = tier1.run(src, "binary.txt")
    md_path = isolate_summaries / f"{src.stem}_t1.md"
    assert md_path.exists()
    body = md_path.read_text(encoding="utf-8")
    assert "hello" in body and "world" in body


def test_tier1_content_type_detection(isolate_summaries: Path, tmp_path: Path):
    for ext, expected in [
        (".py", "code"),
        (".js", "code"),
        (".md", "markdown"),
        (".txt", "text"),
        (".json", "config"),
        (".yaml", "config"),
    ]:
        src = tmp_path / f"f{ext}"
        src.write_text("content", encoding="utf-8")
        tier1.run(src, f"f{ext}")
        md_path = isolate_summaries / f"{src.stem}_t1.md"
        parsed = parse_summary_file(md_path)
        assert parsed.content_type == expected, f"{ext} → expected {expected}, got {parsed.content_type}"
