"""Tests for the three ingest modes:
  * default (append, skip-unchanged)
  * --force (re-encode every file under this root, including T4 ColPali)
  * --rebuild (drop collections + clear manifest under root, then re-ingest)

Plus the fast-tier orphan cleanup that runs at the end of every ingest.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src import manifest as manifest_mod
from src.manifest import Entry, Manifest


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect manifest + summaries dir to tmp; patch Manifest defaults."""
    mpath = tmp_path / "_manifest.json"
    sdir = tmp_path / "summaries"
    sdir.mkdir()
    monkeypatch.setattr(manifest_mod, "DEFAULT_MANIFEST_PATH", mpath)
    monkeypatch.setattr("src.ingest.common.SUMMARIES_DIR", sdir)
    monkeypatch.setattr(Manifest.__init__, "__defaults__", (mpath,))
    import src.ingest.tier0 as t0
    import src.ingest.tier1 as t1
    import src.ingest.tier2 as t2
    for mod in (t0, t1, t2):
        monkeypatch.setattr(
            mod, "summary_output_path",
            lambda path, tier, sdir=sdir: sdir / f"{path.stem}_{tier}.md",
        )
    return tmp_path, mpath, sdir


# ---------------------------------------------------------------------------
# --force propagates to T4
# ---------------------------------------------------------------------------

def test_index_file_force_bypasses_size_check(tmp_path: Path):
    """`force=True` re-encodes even when the manifest says size is unchanged."""
    import torch

    from src.stage1_fast.index import index_file

    mpath = tmp_path / "_manifest.json"
    original = Manifest.__init__.__defaults__
    try:
        Manifest.__init__.__defaults__ = (mpath,)  # type: ignore[attr-defined]
        m = Manifest()
        # Pre-seed an entry that says this file is "already fast-indexed"
        rel = "fake/path.pdf"
        m.entries[rel] = Entry(
            size=100, fast_indexed_at="2026-01-01T00:00:00Z", fast_pages=2,
        )
        m.save()

        p = tmp_path / "fake_path.pdf"
        p.write_bytes(b"x" * 100)

        with patch("src.stage1_fast.index._render_pages") as mock_render, \
             patch("src.stage1_fast.model.encode_images") as mock_encode, \
             patch("src.stage1_fast.model.get_model") as mock_get_model, \
             patch("src.stage2.fast_db.upsert_pages_batch") as mock_upsert, \
             patch("src.stage1_fast.index._source_rel", return_value=rel):
            mock_render.return_value = [MagicMock()]
            mock_encode.return_value = torch.randn(1, 100, 128)
            cfg = MagicMock(); cfg.batch_size = 1
            mock_get_model.return_value = (None, None, cfg)

            # Without force: skipped (size match in manifest)
            pages, skipped = index_file(p, m, force=False)
            assert skipped is True
            mock_upsert.assert_not_called()

            # With force: re-encodes despite size match
            pages, skipped = index_file(p, m, force=True)
            assert skipped is False
            mock_upsert.assert_called_once()
    finally:
        Manifest.__init__.__defaults__ = original  # type: ignore[attr-defined]


def test_walker_passes_force_through_to_tier4(isolated, tmp_path: Path):
    """End-to-end: walker --force → tier4.run(force=True) → index_file(force=True)."""
    from src.ingest.walker import _run_tier
    from src.router import RouteDecision

    p = tmp_path / "x.png"
    p.write_bytes(b"\x89PNG fake")

    with patch("src.ingest.tier4.run") as mock_t4_run:
        mock_t4_run.return_value = MagicMock(summary_file_rel=None, body_chars=0)
        m = Manifest()
        asyncio.run(_run_tier("T4", p, "x.png", agent=None, manifest=m, force=True))
        # tier4.run was called with force=True
        assert mock_t4_run.call_args.kwargs.get("force") is True


# ---------------------------------------------------------------------------
# --rebuild clean slate
# ---------------------------------------------------------------------------

def test_rebuild_clean_slate_clears_manifest_under_root(isolated, tmp_path: Path):
    from src.ingest.walker import _rebuild_clean_slate

    _, mpath, _ = isolated
    m = Manifest()
    # Two roots' worth of entries
    m.entries["/some/other/place/file.txt"] = Entry(size=1, summary_file="x.md")
    root = tmp_path / "corpus"
    root.mkdir()
    m.entries[f"{root.resolve()}/a.py"] = Entry(size=10, summary_file="y.md")
    m.entries[f"{root.resolve()}/b.md"] = Entry(size=20, summary_file="z.md")
    m.save()

    # Mock the Qdrant drops so we don't touch a real cluster
    with patch("src.stage2.db.get_qdrant_client") as mock_client, \
         patch("src.stage2.fast_db.ensure_fast_collection") as mock_ensure_fast:
        mock_client.return_value.collection_exists.return_value = True
        _rebuild_clean_slate(root)
        # Both Qdrant calls fired
        mock_client.return_value.delete_collection.assert_called_once()
        mock_ensure_fast.assert_called_once_with(recreate=True)

    # Manifest now has only the unrelated entry; root's entries are gone
    m2 = Manifest()
    assert "/some/other/place/file.txt" in m2.entries
    assert not any(str(root.resolve()) in k for k in m2.entries)


def test_rebuild_skips_qdrant_gracefully_when_creds_missing(isolated, tmp_path: Path):
    """If Qdrant creds are missing, _rebuild_clean_slate logs and continues."""
    from src.ingest.walker import _rebuild_clean_slate

    root = tmp_path / "corpus"
    root.mkdir()

    # get_qdrant_client raises SystemExit on missing creds
    with patch("src.stage2.db.get_qdrant_client", side_effect=SystemExit("no creds")):
        # Should NOT raise — should log and continue
        _rebuild_clean_slate(root)


# ---------------------------------------------------------------------------
# Fast-tier orphan cleanup
# ---------------------------------------------------------------------------

def test_fast_tier_orphan_cleanup_removes_vanished_files(isolated, tmp_path: Path):
    from src.ingest.walker import _fast_tier_orphan_cleanup

    m = Manifest()
    m.entries["/keeps/me.pdf"] = Entry(size=1, summary_file="kept.md")
    m.save()

    # Fast tier has TWO paths: one in manifest, one not.
    with patch("src.stage2.fast_db.get_indexed_paths") as mock_indexed, \
         patch("src.stage2.fast_db.delete_path") as mock_delete:
        mock_indexed.return_value = {"/keeps/me.pdf", "/orphan/dropped.pdf"}
        deleted = _fast_tier_orphan_cleanup(m)
        # Only the orphan got deleted
        assert deleted == 1
        mock_delete.assert_called_once_with("/orphan/dropped.pdf")


def test_fast_tier_orphan_cleanup_handles_missing_module(isolated):
    """If src.stage2.fast_db can't be imported (e.g. dep missing), return 0."""
    from src.ingest.walker import _fast_tier_orphan_cleanup
    import builtins
    real_import = builtins.__import__

    def boom(name, *args, **kwargs):
        if "fast_db" in name:
            raise ImportError("fake")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=boom):
        m = Manifest()
        assert _fast_tier_orphan_cleanup(m) == 0


# ---------------------------------------------------------------------------
# Mode mutual exclusion
# ---------------------------------------------------------------------------

def test_force_and_rebuild_are_mutually_exclusive(monkeypatch, capsys):
    """argparse should reject `--force --rebuild` together."""
    from src.ingest.walker import main
    monkeypatch.setattr("sys.argv", ["nas-ingest", "/tmp", "--force", "--rebuild"])
    with pytest.raises(SystemExit):
        main()
    err = capsys.readouterr().err
    assert "not allowed with" in err or "mutually exclusive" in err
