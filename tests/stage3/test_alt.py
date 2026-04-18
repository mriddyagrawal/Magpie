"""Tests for the .alt YAML parser.

Ground-truth fixture: Test Videos/img_9556_2026-04-16.alt
"""

from pathlib import Path

import pytest

from src.stage3.alt import AltParseError, parse_alt_file

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "Test Videos" / "img_9556_2026-04-16.alt"


def test_fixture_exists():
    assert FIXTURE.is_file(), f"missing fixture: {FIXTURE}"


def test_parse_top_level_fields():
    alt = parse_alt_file(FIXTURE)
    assert alt.alt_version == 1
    assert alt.type == "home_video"


def test_parse_source_block():
    alt = parse_alt_file(FIXTURE)
    assert alt.source_filename == "IMG_9556.MOV"
    assert alt.source_local_path.endswith("IMG_9556.MOV")
    assert alt.source_hash.startswith("9212026c")


def test_parse_summary():
    alt = parse_alt_file(FIXTURE)
    assert "dances" in alt.summary_one_line
    assert "birthday" in alt.summary_full.lower()


def test_parse_scenes():
    alt = parse_alt_file(FIXTURE)
    assert len(alt.scenes) == 3
    tcs = [s.timecode for s in alt.scenes]
    assert tcs == ["00:00", "00:20", "00:30"]
    assert "second dancer" in alt.scenes[2].description.lower()
    assert alt.scenes[0].setting != ""
    assert alt.scenes[0].mood == "festive"


def test_parse_themes_and_tokens():
    alt = parse_alt_file(FIXTURE)
    assert "birthday celebration" in alt.themes
    assert any("dancing" in t for t in alt.search_tokens)


def test_parse_missing_file():
    with pytest.raises(AltParseError):
        parse_alt_file(Path("/nonexistent/whatever.alt"))


def test_parse_malformed_yaml(tmp_path: Path):
    bad = tmp_path / "bad.alt"
    bad.write_text("key: : : : not valid\n[[[", encoding="utf-8")
    with pytest.raises(AltParseError):
        parse_alt_file(bad)


def test_parse_missing_required_field(tmp_path: Path):
    bad = tmp_path / "missing.alt"
    bad.write_text("alt_version: 1\ntype: movie\n", encoding="utf-8")
    with pytest.raises(AltParseError):
        parse_alt_file(bad)


def test_parse_no_scenes_ok(tmp_path: Path):
    doc = (
        "alt_version: 1\n"
        "type: movie\n"
        "source: {filename: x, local_path: /x}\n"
        "summary: {one_line: hi, full: hello}\n"
    )
    f = tmp_path / "noscenes.alt"
    f.write_text(doc, encoding="utf-8")
    alt = parse_alt_file(f)
    assert alt.scenes == []
    assert alt.summary_one_line == "hi"
