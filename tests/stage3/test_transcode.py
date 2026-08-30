"""Tests for transcoding AltDocument -> summary markdown.

The emitted markdown must parse cleanly with the Stage 2 parser so no Stage 2
change is needed — that's the whole point of the transcode step.
"""

from pathlib import Path

from src.stage2.parser import parse_summary_file
from src.stage3.alt import parse_alt_file
from src.stage3.transcode import transcode

REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_DIR = REPO_ROOT / "Test Videos"
# Personal test media, never committed (size + privacy). On machines without
# it these are integration tests with no input - skip, don't fail: a red
# that fires on every clone carries no signal (test-suite triage 2026-08-30).
pytestmark = __import__("pytest").mark.skipif(
    not _FIXTURE_DIR.exists(),
    reason="Test Videos/ fixture media not present on this machine",
)
FIXTURE = REPO_ROOT / "Test Videos" / "img_9556_2026-04-16.alt"


def test_emits_one_file_plus_three_scenes():
    alt = parse_alt_file(FIXTURE)
    out = transcode(alt, "Test Videos/img_9556_2026-04-16.alt")
    assert len(out) == 4
    assert out[0].kind == "video"
    assert {o.kind for o in out[1:]} == {"s_00_00", "s_00_20", "s_00_30"}


def test_manifest_keys_are_unique():
    alt = parse_alt_file(FIXTURE)
    out = transcode(alt, "Test Videos/img_9556_2026-04-16.alt")
    keys = [o.manifest_key for o in out]
    assert len(keys) == len(set(keys)), f"duplicate manifest keys: {keys}"


def test_file_level_markdown_round_trips_through_stage2_parser(tmp_path: Path):
    alt = parse_alt_file(FIXTURE)
    out = transcode(alt, "Test Videos/img_9556_2026-04-16.alt")
    md_path = tmp_path / "file.md"
    md_path.write_text(out[0].summary_md, encoding="utf-8")
    parsed = parse_summary_file(md_path)

    assert parsed.source_path == "Test Videos/img_9556_2026-04-16.alt"
    assert parsed.title  # non-empty
    assert "dance" in parsed.summary.lower()
    # Discriminators we expect to reach BM25:
    assert alt.source_hash in parsed.identifiers
    assert "IMG_9556.MOV" in parsed.identifiers
    # Scene timecodes flattened into file-level prose (v1 BM25 fallback).
    assert "00:30" in parsed.summary


def test_scene_markdown_round_trips_and_points_at_alt(tmp_path: Path):
    alt = parse_alt_file(FIXTURE)
    out = transcode(alt, "Test Videos/img_9556_2026-04-16.alt")
    scene_second_dancer = next(o for o in out if o.kind == "s_00_30")
    md_path = tmp_path / "scene.md"
    md_path.write_text(scene_second_dancer.summary_md, encoding="utf-8")
    parsed = parse_summary_file(md_path)

    # Source points at the .alt + fragment — Stage 2 keys Qdrant on this.
    assert parsed.source_path == "Test Videos/img_9556_2026-04-16.alt#scene:00:30"
    assert "00:30" in parsed.title
    assert "second dancer" in parsed.summary.lower()
    assert parsed.content_type == "alt-scene"
    assert "00:30" in parsed.identifiers


def test_fragment_strippable_back_to_real_path():
    """answer.py._strip_fragment must yield a readable path for every scene."""
    from src.answer import _strip_fragment
    alt = parse_alt_file(FIXTURE)
    out = transcode(alt, "Test Videos/img_9556_2026-04-16.alt")
    for o in out:
        stripped = _strip_fragment(o.manifest_key)
        assert stripped == "Test Videos/img_9556_2026-04-16.alt", (
            f"fragment strip broke for {o.manifest_key!r}"
        )
