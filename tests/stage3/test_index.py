"""Tests for src.stage3.index — the manifest-writing walker.

Uses a temp manifest path via monkeypatching so the real repo manifest isn't
touched.
"""

from pathlib import Path

import pytest

from src import manifest as manifest_mod
from src.manifest import Manifest
from src.stage3 import index as idx_mod
from src.stage3.index import find_alt_files, index_single_alt

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "Test Videos" / "img_9556_2026-04-16.alt"
# Personal test media, never committed - skip on machines without it
# (test-suite triage 2026-08-30).
pytestmark = __import__("pytest").mark.skipif(
    not FIXTURE.exists(), reason="Test Videos/ fixture media not present")


@pytest.fixture
def isolated_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mpath = tmp_path / "_manifest.json"
    monkeypatch.setattr(manifest_mod, "DEFAULT_MANIFEST_PATH", mpath)
    # Redirect summary output to a temp dir so we don't pollute Test Summaries/.
    sdir = tmp_path / "summaries"
    sdir.mkdir()
    monkeypatch.setattr(idx_mod, "SUMMARIES_DIR", sdir)
    # index.py writes summary paths relative to REPO_ROOT. For the test, we let
    # the summary files live in sdir but record them as-is.
    return {"manifest": mpath, "summaries": sdir}


def test_find_alt_files(isolated_manifest, tmp_path: Path):
    # Put three .alt files and one distractor
    (tmp_path / "a.alt").write_text("alt_version: 1\ntype: x\nsource: {}\nsummary: {}\n")
    (tmp_path / "b.alt").write_text("alt_version: 1\ntype: x\nsource: {}\nsummary: {}\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.alt").write_text("alt_version: 1\ntype: x\nsource: {}\nsummary: {}\n")
    (tmp_path / "not_alt.md").write_text("hello")
    found = find_alt_files(tmp_path)
    assert len(found) == 3
    assert all(p.suffix == ".alt" for p in found)


def test_index_single_alt_emits_file_plus_scenes(isolated_manifest):
    manifest = Manifest()
    stats = index_single_alt(FIXTURE, manifest)
    # 1 file-level + 3 scenes in the fixture
    assert stats["emitted"] == 4
    keys = list(manifest.paths())
    assert any(k.endswith("img_9556_2026-04-16.alt") for k in keys)
    assert sum(1 for k in keys if "#scene:" in k) == 3


def test_index_skips_unchanged_alt(isolated_manifest):
    manifest = Manifest()
    first = index_single_alt(FIXTURE, manifest)
    assert first["emitted"] == 4
    second = index_single_alt(FIXTURE, manifest)
    assert second["emitted"] == 0
    assert second["skipped"] == 1


def test_index_force_reindexes(isolated_manifest):
    manifest = Manifest()
    index_single_alt(FIXTURE, manifest)
    forced = index_single_alt(FIXTURE, manifest, force=True)
    assert forced["emitted"] == 4


def test_reindex_deletes_stale_scene_rows(isolated_manifest, tmp_path: Path):
    """When an .alt is re-indexed with fewer scenes, old scene rows are pruned."""
    # Write a smaller alt file (1 scene), then overwrite with a 0-scene one.
    alt = tmp_path / "x.alt"
    alt.write_text(
        "alt_version: 1\n"
        "type: movie\n"
        "source: {filename: x.mp4, local_path: /x.mp4, file_hash_sha256: abc}\n"
        "summary: {one_line: hi, full: hi}\n"
        "scenes:\n"
        "  - timecode: '00:10'\n"
        "    description: 'first scene'\n",
        encoding="utf-8",
    )
    manifest = Manifest()
    index_single_alt(alt, manifest, force=True)
    keys_before = [k for k in manifest.paths() if str(alt) in k or k == str(alt.resolve())]
    # At least 1 scene row present
    assert any("#scene:" in k for k in keys_before)

    # Rewrite with no scenes, different bytes -> force re-index
    alt.write_text(
        "alt_version: 1\n"
        "type: movie\n"
        "source: {filename: x.mp4, local_path: /x.mp4, file_hash_sha256: abc}\n"
        "summary: {one_line: revised, full: revised}\n",
        encoding="utf-8",
    )
    index_single_alt(alt, manifest, force=True)
    keys_after = list(manifest.paths())
    assert not any("#scene:" in k for k in keys_after), (
        f"stale scene rows survived re-index: {keys_after}"
    )
