"""Endpoint tests for POST /index/sync and POST /index/reindex.

Covers:
  - 409 when another indexing job is already running
  - Reindex calls `pipeline.reset()` before sync
  - Sync's drift-cleanup branch drops manifest rows for disabled roots
  - Both spawn a background thread (we mock the workers so tests are fast)
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures (same shape as test_settings_endpoints)
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_app_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    import src.manifest
    importlib.reload(src.manifest)
    import src.config.indexing_rules as ir
    importlib.reload(ir)
    import src.config.settings as st
    importlib.reload(st)
    import src.config.secrets as sec
    importlib.reload(sec)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    try:
        yield tmp_path
    finally:
        # Restore: undo monkeypatch so MAGPIE_DATA_DIR drops back to
        # whatever it was, then reload modules so they re-capture the
        # real APP_DATA_DIR. Without this, tests that run after ours
        # see APP_DATA_DIR pointing at our (now-deleted) tmp dir.
        monkeypatch.undo()
        importlib.reload(src.manifest)
        importlib.reload(ir)
        importlib.reload(st)
        importlib.reload(sec)


@pytest.fixture
def server_module(isolated_app_data: Path):
    import src.server as server
    importlib.reload(server)
    return server


@pytest.fixture
def client(server_module) -> TestClient:
    return TestClient(server_module.app)


# ---------------------------------------------------------------------------
# 409 conflict when something is already running
# ---------------------------------------------------------------------------


def test_sync_returns_409_when_running(client: TestClient, server_module) -> None:
    server_module._ingest_state["running"] = True
    try:
        r = client.post("/index/sync")
        assert r.status_code == 409
        assert "in progress" in r.json()["detail"].lower()
    finally:
        server_module._ingest_state["running"] = False


def test_reindex_returns_409_when_running(client: TestClient, server_module) -> None:
    server_module._ingest_state["running"] = True
    try:
        r = client.post("/index/reindex")
        assert r.status_code == 409
    finally:
        server_module._ingest_state["running"] = False


# ---------------------------------------------------------------------------
# Sync starts a background job + returns 200
# ---------------------------------------------------------------------------


def test_sync_starts_background_job(
    client: TestClient, server_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stub out the worker so the test is fast and doesn't actually
    walk anything. Just verifies the wiring: POST returns 200, the
    state initializes, the thread runs to completion."""
    called: list[bool] = []

    def fake_do_sync() -> None:
        called.append(True)
        # Mirror the real worker's finally clause.
        server_module._ingest_state["running"] = False
        server_module._ingest_state["done"] = True

    monkeypatch.setattr(server_module, "_do_sync", fake_do_sync)

    r = client.post("/index/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["kind"] == "sync"

    # Wait briefly for the daemon thread to fire.
    for _ in range(50):
        if called:
            break
        time.sleep(0.02)
    assert called == [True]


def test_reindex_calls_reset_then_sync(
    client: TestClient, server_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reindex worker must call `pipeline.reset()` BEFORE syncing.
    Mock both and assert order."""
    call_order: list[str] = []

    import src.pipeline as pipeline_module

    def fake_reset() -> dict:
        call_order.append("reset")
        return {"summaries_deleted": 0, "manifest_removed": False,
                "collection_dropped": False}

    def fake_do_sync() -> None:
        call_order.append("sync")
        server_module._ingest_state["running"] = False
        server_module._ingest_state["done"] = True

    monkeypatch.setattr(pipeline_module, "reset", fake_reset)
    monkeypatch.setattr(server_module, "_do_sync", fake_do_sync)

    r = client.post("/index/reindex")
    assert r.status_code == 200
    assert r.json()["kind"] == "reindex"

    for _ in range(50):
        if "sync" in call_order:
            break
        time.sleep(0.02)
    assert call_order == ["reset", "sync"]


# ---------------------------------------------------------------------------
# Drift cleanup unit (the only new logic)
# ---------------------------------------------------------------------------


def test_drift_cleanup_drops_rows_outside_enabled_prefixes(
    server_module, isolated_app_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_drop_manifest_rows_outside_enabled_roots` is the only new piece
    of pipeline logic in this PR. Verify it drops rows whose path does
    NOT start with any enabled prefix, and leaves matching rows alone."""
    # Construct a fake manifest with three rows. Use unique paths under
    # tmp_path that we control.
    docs = isolated_app_data / "Docs"
    docs.mkdir()
    file_a = docs / "a.txt"
    file_a.write_text("a")
    archived = isolated_app_data / "Archived"
    archived.mkdir()
    file_b = archived / "b.txt"
    file_b.write_text("b")

    # Bootstrap a manifest with both rows. `mark_summarized` is the
    # cheapest public method that creates a row with a summary_file
    # (the helper we're testing also wants to delete the summary file
    # if any — `_delete_if_exists` is a no-op for missing files).
    from src.manifest import Manifest
    m = Manifest()
    m.mark_summarized(str(file_a.resolve()), size=1, summary_file=None)
    m.mark_summarized(str(file_b.resolve()), size=1, summary_file=None)
    m.save()

    # Only `Docs` is enabled. Run the helper.
    enabled_prefixes = [str(docs.resolve())]
    dropped = server_module._drop_manifest_rows_outside_enabled_roots(enabled_prefixes)

    assert dropped == 1

    m_after = Manifest()
    paths_after = list(m_after.paths())
    assert str(file_a.resolve()) in paths_after
    assert str(file_b.resolve()) not in paths_after
