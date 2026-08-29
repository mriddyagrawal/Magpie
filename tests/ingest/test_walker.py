"""Tests for src/ingest/walker.py — router-driven batch ingest.

Exercises the end-to-end non-LLM path: files that route to T0/T1/T2 should
run through the walker without any agent (agent is only built lazily when
T3/T4 is needed). Manifest audit fields are populated per file.

T3 and T4 paths are NOT covered here — T3 needs an LLM, T4 needs a GPU +
heavy model. Those are exercised via separate integration / smoke tests.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src import manifest as manifest_mod
from src.ingest import walker as walker_mod
from src.ingest.walker import _choose_primary_tier, find_candidates, run_batch
from src.manifest import Manifest
from src.router import RouteDecision


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect manifest path and summaries dir to a tmp location."""
    mpath = tmp_path / "_manifest.json"
    sdir = tmp_path / "summaries"
    sdir.mkdir()
    monkeypatch.setattr(manifest_mod, "DEFAULT_MANIFEST_PATH", mpath)
    monkeypatch.setattr("src.ingest.common.SUMMARIES_DIR", sdir)
    # `Manifest.__init__(self, path=DEFAULT_MANIFEST_PATH)` bound the default
    # at class-def time, so replacing the module constant is not enough.
    # Patch __defaults__ directly.
    monkeypatch.setattr(Manifest.__init__, "__defaults__", (mpath,))
    # Keep each tier's output_path under our tmp summaries dir.
    import src.ingest.tier0 as t0
    import src.ingest.tier1 as t1
    import src.ingest.tier2 as t2
    for mod in (t0, t1, t2):
        monkeypatch.setattr(
            mod, "summary_output_path",
            lambda path, tier, sdir=sdir: sdir / f"{path.stem}_{tier}.md",
        )
    return tmp_path, mpath, sdir


def test_choose_primary_tier_priority():
    """Priority: T3 > T2 > T4 > T1 > T0."""
    assert _choose_primary_tier(_mock_decision(["T3", "T2"])) == "T3"
    assert _choose_primary_tier(_mock_decision(["T2"])) == "T2"
    assert _choose_primary_tier(_mock_decision(["T4"])) == "T4"
    assert _choose_primary_tier(_mock_decision(["T1"])) == "T1"
    assert _choose_primary_tier(_mock_decision(["T0"])) == "T0"
    assert _choose_primary_tier(_mock_decision([])) is None


def _mock_decision(routes: list[str]) -> RouteDecision:
    return RouteDecision(
        routes=routes,
        visual_score=0,
        sensitivity_score=0,
        t4_cost_mb=0.0,
        t4_cost_s=0.0,
        criticality="normal",
        criticality_source="default",
    )


def test_find_candidates_picks_supported_extensions(isolated, tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.py").write_text("print(1)", encoding="utf-8")
    (corpus / "b.md").write_text("hi", encoding="utf-8")
    (corpus / "c.bin").write_bytes(b"\x00\x01")   # unsupported
    (corpus / ".hidden.txt").write_text("h", encoding="utf-8")

    found, ignored, asset_skipped = find_candidates(corpus)
    names = {p.name for p in found}
    assert names == {"a.py", "b.md"}
    assert ignored == 0
    assert asset_skipped == 0


def test_find_candidates_skips_asset_library_folder(isolated, tmp_path: Path):
    """Asset-library rule REMOVED (2026-08-29): image-only folders index fully."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    # Real working folder: a few images alongside a document. NOT an asset lib.
    notes_dir = corpus / "notes"
    notes_dir.mkdir()
    (notes_dir / "chapter.md").write_text("notes", encoding="utf-8")
    for i in range(5):
        (notes_dir / f"fig{i}.png").write_bytes(b"\x89PNG")

    # Asset library: 20 images, zero documents.
    assets_dir = corpus / "weird_name_assets"
    assets_dir.mkdir()
    for i in range(20):
        (assets_dir / f"stock{i}.jpg").write_bytes(b"\xff\xd8\xff")

    found, ignored, asset_skipped = find_candidates(corpus)
    names = {p.name for p in found}

    # Notes folder images survive because chapter.md is a sibling doc.
    assert "chapter.md" in names
    assert "fig0.png" in names
    # Image-only folders are indexed like any other folder now.
    assert all(f"stock{i}.jpg" in names for i in range(20))
    assert asset_skipped == 0
    assert ignored == 0


def test_find_candidates_asset_rule_ignores_subfolder_docs(isolated, tmp_path: Path):
    """Rule removed: subfolder layout is irrelevant; everything indexes."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    assets_dir = corpus / "images"
    assets_dir.mkdir()
    for i in range(20):
        (assets_dir / f"img{i}.png").write_bytes(b"\x89PNG")

    # Doc is in a SUBFOLDER of images/, not a sibling of the images themselves.
    sub = assets_dir / "writeup"
    sub.mkdir()
    (sub / "notes.md").write_text("writeup", encoding="utf-8")

    found, ignored, asset_skipped = find_candidates(corpus)
    # Rule removed: images index regardless of sibling docs.
    assert sum(1 for p in found if p.name.startswith("img")) == 20
    assert any(p.name == "notes.md" for p in found)
    assert asset_skipped == 0


def test_walker_end_to_end_t1_only(isolated, tmp_path: Path):
    _, mpath, sdir = isolated
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "notes.md").write_text(
        "# Project notes\n\nThe invoice total was $170.45.\n",
        encoding="utf-8",
    )
    (corpus / "app.py").write_text("def hello(): return 'world'\n", encoding="utf-8")

    asyncio.run(run_batch(corpus, concurrency=2))

    assert mpath.is_file(), "manifest must be saved"
    # Both files should have T1 summaries
    t1_mds = list(sdir.glob("*_t1.md"))
    assert len(t1_mds) == 2

    # Manifest has router audit trail
    m = Manifest(path=mpath)
    assert len(m.entries) == 2
    for entry in m.entries.values():
        assert entry.routes == ["T1"]
        assert entry.criticality == "normal"
        assert entry.criticality_source == "default"
        assert entry.summary_file is not None
        assert entry.skip_reason is None


def test_walker_honors_unchanged_files(isolated, tmp_path: Path):
    _, mpath, sdir = isolated
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    f = corpus / "a.txt"
    f.write_text("hello", encoding="utf-8")

    asyncio.run(run_batch(corpus))
    first_count = len(list(sdir.glob("*_t1.md")))
    first_mtime = (list(sdir.glob("*_t1.md"))[0]).stat().st_mtime

    # Second run: file unchanged → should skip (no new markdowns produced)
    asyncio.run(run_batch(corpus))
    assert len(list(sdir.glob("*_t1.md"))) == first_count
    # mtime preserved (same file, not rewritten)
    assert (list(sdir.glob("*_t1.md"))[0]).stat().st_mtime == first_mtime


def test_walker_prunes_deleted_files(isolated, tmp_path: Path):
    _, mpath, sdir = isolated
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    keep = corpus / "keep.txt"
    keep.write_text("stays", encoding="utf-8")
    drop = corpus / "drop.txt"
    drop.write_text("goes away", encoding="utf-8")

    asyncio.run(run_batch(corpus))
    m = Manifest(path=mpath)
    assert len(m.entries) == 2

    drop.unlink()
    asyncio.run(run_batch(corpus))
    m = Manifest(path=mpath)
    assert len(m.entries) == 1
    assert all("drop.txt" not in k for k in m.entries)


def test_walker_records_skip_reason_for_thumbnails(isolated, tmp_path: Path):
    from PIL import Image
    _, mpath, _ = isolated
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # 64x64 image under the thumbnail threshold → router skips
    Image.new("RGB", (64, 64), "red").save(corpus / "thumb.png")

    asyncio.run(run_batch(corpus))
    m = Manifest(path=mpath)
    thumb = m.get("corpus/thumb.png") or m.get(str((corpus / "thumb.png").resolve()))
    assert thumb is not None
    assert thumb.skip_reason == "thumbnail"
    assert thumb.summary_file is None


def test_walker_force_reingests_unchanged_files(isolated, tmp_path: Path):
    import time
    _, mpath, sdir = isolated
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    f = corpus / "a.txt"
    f.write_text("hello", encoding="utf-8")

    asyncio.run(run_batch(corpus))
    first_md = list(sdir.glob("*_t1.md"))[0]
    first_mtime = first_md.stat().st_mtime

    time.sleep(0.05)
    asyncio.run(run_batch(corpus, force=True))
    second_md = list(sdir.glob("*_t1.md"))[0]
    # mtime should have advanced — force wrote a fresh summary
    assert second_md.stat().st_mtime >= first_mtime
