"""fastembed cache pinning + one-time migration (src/manifest.py).

fastembed ignores HF_HOME and defaults its cache to
`<tempdir>/fastembed_cache`, which put the always-loaded MiniLM + BM25
models in a directory the OS purges on its own schedule. `src.manifest`
pins `FASTEMBED_CACHE_PATH` under APP_DATA_DIR and migrates any pre-fix
temp cache across on first import.

These tests reload `src.manifest` so the module-level env writes re-run
against a tmp_path data dir — the same idiom `tests/ingest/test_tier1_csv.py`
uses for APP_DATA_DIR.
"""

from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_tempdir(tmp_path, monkeypatch) -> Path:
    """Give every test in this file its own `tempfile.gettempdir()`.

    The code under test reads `tempfile.gettempdir()` to find the legacy
    cache. Without this fixture, any test that reloads `src.manifest` with
    an unpinned FASTEMBED_CACHE_PATH would find the *developer's real*
    `<tempdir>/fastembed_cache` and migrate it into a pytest tmp dir that
    gets garbage-collected — silently destroying ~90 MB of real model
    weights. Autouse so no future test can reintroduce that.
    """
    fake_tmp = tmp_path / "systmp"
    fake_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(fake_tmp))
    return fake_tmp


@pytest.fixture(autouse=True, scope="module")
def _restore_manifest_after_module():
    """Leave `src.manifest` bound to the real environment for later tests.

    Runs after every function-scoped monkeypatch in this file has undone
    its env changes, so the final reload re-reads the true values.
    """
    yield
    import src.manifest

    importlib.reload(src.manifest)


def _reload_manifest(data_dir: Path, monkeypatch, *, pinned: str | None = None):
    """Point APP_DATA_DIR at `data_dir` and re-run manifest's import-time env
    writes. `pinned` simulates a user who set FASTEMBED_CACHE_PATH already."""
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(data_dir))
    if pinned is None:
        monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    else:
        monkeypatch.setenv("FASTEMBED_CACHE_PATH", pinned)
    import src.manifest

    return importlib.reload(src.manifest)


def _make_legacy_cache(fake_tmp: Path) -> Path:
    """Populate `<tempdir>/fastembed_cache` the way pre-fix installs left it."""
    legacy = fake_tmp / "fastembed_cache"
    (legacy / "models--Qdrant--bm25").mkdir(parents=True)
    (legacy / "models--Qdrant--bm25" / "model.onnx").write_text("weights")
    return legacy


def test_cache_path_defaults_under_app_data_dir(tmp_path, monkeypatch):
    """Unset FASTEMBED_CACHE_PATH resolves to <APP_DATA_DIR>/cache/fastembed."""
    m = _reload_manifest(tmp_path / "data", monkeypatch)

    assert os.environ["FASTEMBED_CACHE_PATH"] == str(
        m.APP_DATA_DIR / "cache" / "fastembed"
    )
    # And it sits alongside the HF weights, not in a temp dir.
    assert Path(os.environ["FASTEMBED_CACHE_PATH"]).parent == m.APP_DATA_DIR / "cache"
    assert tempfile.gettempdir() not in os.environ["FASTEMBED_CACHE_PATH"]


def test_user_pinned_cache_path_is_respected(tmp_path, monkeypatch):
    """setdefault semantics: an explicit FASTEMBED_CACHE_PATH wins."""
    custom = str(tmp_path / "my-own-cache")
    _reload_manifest(tmp_path / "data", monkeypatch, pinned=custom)

    assert os.environ["FASTEMBED_CACHE_PATH"] == custom


def test_legacy_temp_cache_is_migrated(tmp_path, monkeypatch, _isolate_tempdir):
    """A pre-fix temp cache moves into APP_DATA_DIR on first import."""
    legacy = _make_legacy_cache(_isolate_tempdir)
    m = _reload_manifest(tmp_path / "data", monkeypatch)

    dest = m.APP_DATA_DIR / "cache" / "fastembed"
    assert dest.is_dir(), "legacy cache should have been moved into APP_DATA_DIR"
    assert (dest / "models--Qdrant--bm25" / "model.onnx").read_text() == "weights"
    assert not legacy.exists(), "legacy temp cache should be gone after the move"


def test_migration_is_idempotent_when_dest_exists(tmp_path, monkeypatch, _isolate_tempdir):
    """An existing destination is never overwritten by the legacy copy."""
    legacy = _make_legacy_cache(_isolate_tempdir)
    data_dir = tmp_path / "data"
    dest = data_dir / "cache" / "fastembed"
    dest.mkdir(parents=True)
    (dest / "sentinel").write_text("keep me")

    _reload_manifest(data_dir, monkeypatch)

    assert (dest / "sentinel").read_text() == "keep me"
    assert legacy.is_dir(), "legacy cache should be left alone when dest exists"


def test_no_migration_when_user_pinned_path(tmp_path, monkeypatch, _isolate_tempdir):
    """We only migrate into the location we chose, never a user's own."""
    legacy = _make_legacy_cache(_isolate_tempdir)
    custom = str(tmp_path / "my-own-cache")

    _reload_manifest(tmp_path / "data", monkeypatch, pinned=custom)

    assert legacy.is_dir(), "user-pinned path must not trigger a migration"
    assert not Path(custom).exists()


def test_missing_legacy_cache_is_a_noop(tmp_path, monkeypatch):
    """Fresh install: nothing to migrate, nothing created, no crash."""
    m = _reload_manifest(tmp_path / "data", monkeypatch)

    assert not (m.APP_DATA_DIR / "cache" / "fastembed").exists()
