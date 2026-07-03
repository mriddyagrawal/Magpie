"""Tests for src/ingest/tier0.py — register + on-demand ripgrep for huge files.

Invariants:
  * No LLM call
  * CSVs yield a preview of ~100 rows + header with row count in identifiers
  * Non-CSV huge files yield a first-N-bytes preview (UTF-8 safe)
  * Empty / unreadable files still produce a valid summary (with a clear hint)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest import tier0
from src.stage2.parser import parse_summary_file


@pytest.fixture
def isolate_summaries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    sdir = tmp_path / "summaries"
    sdir.mkdir()
    monkeypatch.setattr("src.ingest.common.SUMMARIES_DIR", sdir)
    monkeypatch.setattr(
        "src.ingest.tier0.summary_output_path",
        lambda path, tier: sdir / f"{path.stem}_{tier}.md",
    )
    return sdir


def test_tier0_csv_preview_and_rowcount(isolate_summaries: Path, tmp_path: Path):
    # Build a 250-row CSV (>T0_CSV_PREVIEW_ROWS=100). Preview should truncate
    # to ~100 rows but identifiers must carry the FULL count.
    lines = ["id,name,amount"]
    for i in range(250):
        lines.append(f"{i},name{i},{i*10}")
    csv = tmp_path / "huge.csv"
    csv.write_text("\n".join(lines), encoding="utf-8")

    tier0.run(csv, "huge.csv")
    md_path = isolate_summaries / f"{csv.stem}_t0.md"
    assert md_path.exists()
    parsed = parse_summary_file(md_path)

    # Preview contains early rows
    assert "name0" in parsed.summary
    # Full count goes into identifiers
    assert any("250" in i for i in parsed.identifiers)
    assert parsed.content_type == "csv"


def test_tier0_non_csv_preview(isolate_summaries: Path, tmp_path: Path):
    # 50 KB log file — T0 preview should grab the first 2 KB.
    log = tmp_path / "big.log"
    log.write_text("ERROR xyz\n" * 5_000, encoding="utf-8")

    tier0.run(log, "big.log")
    md_path = isolate_summaries / f"{log.stem}_t0.md"
    parsed = parse_summary_file(md_path)
    assert "ERROR xyz" in parsed.summary
    assert parsed.content_type == "text-large"


def test_tier0_includes_filename_and_size_in_identifiers(isolate_summaries: Path, tmp_path: Path):
    big = tmp_path / "payload.txt"
    big.write_text("a" * 200_000, encoding="utf-8")
    tier0.run(big, "payload.txt")
    md_path = isolate_summaries / f"{big.stem}_t0.md"
    parsed = parse_summary_file(md_path)
    assert "payload.txt" in parsed.identifiers
    assert any("bytes" in i for i in parsed.identifiers)


def test_tier0_empty_file_still_produces_summary(isolate_summaries: Path, tmp_path: Path):
    empty = tmp_path / "zero.txt"
    empty.write_bytes(b"")
    tier0.run(empty, "zero.txt")
    md_path = isolate_summaries / f"{empty.stem}_t0.md"
    parsed = parse_summary_file(md_path)
    # Body should mention the hint about ripgrep fallback.
    assert "ripgrep" in parsed.summary.lower() or "preview" in parsed.summary.lower()
