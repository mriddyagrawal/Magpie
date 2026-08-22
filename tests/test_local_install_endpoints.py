"""Tests for src.local_install + the /local/* endpoints.

Everything network- and subprocess-shaped is patched out: `_execute` never
spawns a real child, presence checks never touch the HF cache layout, and
`_visual_spec` never calls detect_device (whose torch probe and device.json
cache belong to the dev machine, not the test).

Fixture shape follows tests/test_index_endpoints.py: MAGPIE_DATA_DIR is
pointed at tmp_path and the capturing modules are reloaded, then restored.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


VIS = {"adapter": "vidore/colqwen2.5-v0.2", "base": "vidore/colqwen2.5-base",
       "total_gb": 7.25}


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(tmp_path))
    for var in ("LOCAL_MODEL", "LOCAL_QUANT", "LLAMA_SERVER_TEXT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    import src.manifest
    importlib.reload(src.manifest)
    import src.local_install as li
    importlib.reload(li)
    # Never probe hardware or the network from tests.
    monkeypatch.setattr(li, "_visual_spec", lambda: dict(VIS))
    monkeypatch.setattr(li, "_remote_size", lambda repo, fn: 1000)
    try:
        yield li
    finally:
        # A still-running worker would outlive the monkeypatches.
        li.cancel_install()
        deadline = time.time() + 5
        while li._state["running"] and time.time() < deadline:
            time.sleep(0.02)
        monkeypatch.undo()
        importlib.reload(src.manifest)
        importlib.reload(li)


def _wait_idle(li, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while li._state["running"] and time.time() < deadline:
        time.sleep(0.02)
    assert not li._state["running"], "worker did not finish in time"


def _all_missing(monkeypatch, li) -> None:
    monkeypatch.setattr(li, "_binary_status",
                        lambda: {"present": False, "version": None})
    monkeypatch.setattr(li, "_hf_file_present", lambda repo, fn: False)
    monkeypatch.setattr(li, "_hf_repo_present", lambda repo: False)


def _all_present(monkeypatch, li) -> None:
    monkeypatch.setattr(li, "_binary_status",
                        lambda: {"present": True, "version": 10502})
    monkeypatch.setattr(li, "_hf_file_present", lambda repo, fn: True)
    monkeypatch.setattr(li, "_hf_repo_present", lambda repo: True)


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------

def test_status_not_installed_when_everything_missing(isolated, monkeypatch):
    li = isolated
    _all_missing(monkeypatch, li)
    s = li.status()
    assert s["state"] == "not_installed"
    assert s["llm"]["ready"] is False
    assert s["visual"]["ready"] is False
    # The card needs real names/sizes to render "Download (N GB)".
    assert s["llm"]["repo"] == "LiquidAI/LFM2.5-VL-3B-GGUF"
    assert s["llm"]["quant"] == "Q6_K"
    assert s["visual"]["bytes_total"] == int(7.25 * 1024**3)


def test_status_ready_when_everything_present(isolated, monkeypatch):
    li = isolated
    _all_present(monkeypatch, li)
    s = li.status()
    assert s["state"] == "ready"
    assert s["llm"]["ready"] is True and s["visual"]["ready"] is True
    assert li.is_llm_ready() is True


def test_llm_ready_excludes_visual_tier(isolated, monkeypatch):
    """The Local provider toggle must not be held hostage by the 7 GB
    visual model — T4 uses that regardless of provider."""
    li = isolated
    monkeypatch.setattr(li, "_binary_status",
                        lambda: {"present": True, "version": 10502})
    monkeypatch.setattr(li, "_hf_file_present", lambda repo, fn: True)
    monkeypatch.setattr(li, "_hf_repo_present", lambda repo: False)  # visual missing
    assert li.is_llm_ready() is True
    s = li.status()
    assert s["llm"]["ready"] is True
    assert s["visual"]["ready"] is False
    assert s["state"] == "not_installed"  # overall still wants the visual half


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------

def test_install_runs_every_missing_step_in_order(isolated, monkeypatch):
    li = isolated
    _all_missing(monkeypatch, li)
    ran: list[str] = []
    monkeypatch.setattr(li, "_execute",
                        lambda target, *a: (ran.append(li._state["phase"]), None)[1])
    monkeypatch.setattr(li, "_preflight_disk", lambda n: None)
    ok, _ = li.start_install()
    assert ok
    _wait_idle(li)
    assert ran == ["binary", "llm_weights", "mmproj", "visual_adapter", "visual_base"]
    assert li._state["error"] is None and li._state["cancelled"] is False


def test_install_skips_present_artifacts(isolated, monkeypatch):
    li = isolated
    monkeypatch.setattr(li, "_binary_status",
                        lambda: {"present": True, "version": 10502})
    monkeypatch.setattr(li, "_hf_file_present", lambda repo, fn: True)
    monkeypatch.setattr(li, "_hf_repo_present", lambda repo: False)
    ran: list[str] = []
    monkeypatch.setattr(li, "_execute",
                        lambda target, *a: (ran.append(li._state["phase"]), None)[1])
    monkeypatch.setattr(li, "_preflight_disk", lambda n: None)
    li.start_install()
    _wait_idle(li)
    assert ran == ["visual_adapter", "visual_base"]


def test_double_start_refused(isolated, monkeypatch):
    li = isolated
    _all_missing(monkeypatch, li)
    monkeypatch.setattr(li, "_preflight_disk", lambda n: None)

    def _slow(target, *a):
        while not li._state["cancel_requested"]:
            time.sleep(0.01)
        return "cancelled"

    monkeypatch.setattr(li, "_execute", _slow)
    ok1, _ = li.start_install()
    ok2, msg = li.start_install()
    assert ok1 and not ok2 and "already" in msg
    li.cancel_install()
    _wait_idle(li)
    assert li._state["cancelled"] is True


def test_cancel_preserves_partials_and_state(isolated, monkeypatch):
    li = isolated
    _all_missing(monkeypatch, li)
    monkeypatch.setattr(li, "_preflight_disk", lambda n: None)

    def _blocks_until_cancel(target, *a):
        while not li._state["cancel_requested"]:
            time.sleep(0.01)
        return "cancelled"

    monkeypatch.setattr(li, "_execute", _blocks_until_cancel)
    li.start_install()
    ok, _ = li.cancel_install()
    assert ok
    _wait_idle(li)
    assert li._state["cancelled"] is True
    assert li._state["error"] is None  # cancel is not an error


def test_disk_preflight_blocks_before_any_download(isolated, monkeypatch):
    li = isolated
    _all_missing(monkeypatch, li)
    ran: list[str] = []
    monkeypatch.setattr(li, "_execute",
                        lambda target, *a: (ran.append("x"), None)[1])
    monkeypatch.setattr(li, "_preflight_disk",
                        lambda n: "Not enough disk space: need 10.0 GB")
    li.start_install()
    _wait_idle(li)
    assert ran == []
    assert "disk space" in li._state["error"]


def test_child_failure_surfaces_with_phase(isolated, monkeypatch):
    li = isolated
    _all_missing(monkeypatch, li)
    monkeypatch.setattr(li, "_preflight_disk", lambda n: None)
    monkeypatch.setattr(li, "_execute",
                        lambda target, *a: "download subprocess exited with code 1")
    li.start_install()
    _wait_idle(li)
    assert "exited with code 1" in li._state["error"]
    assert li._state["phase"] == "binary"  # died on the first step, and says so


# ---------------------------------------------------------------------------
# delete_models
# ---------------------------------------------------------------------------

def test_delete_refused_while_running(isolated, monkeypatch):
    li = isolated
    _all_missing(monkeypatch, li)
    monkeypatch.setattr(li, "_preflight_disk", lambda n: None)

    def _slow(target, *a):
        while not li._state["cancel_requested"]:
            time.sleep(0.01)
        return "cancelled"

    monkeypatch.setattr(li, "_execute", _slow)
    li.start_install()
    out = li.delete_models("all")
    assert out["error"] and "cancel" in out["error"]
    li.cancel_install()
    _wait_idle(li)


def test_delete_llm_removes_only_the_llm_repo(isolated):
    li = isolated
    llm_dir = li._repo_cache_dir("LiquidAI/LFM2.5-VL-3B-GGUF")
    vis_dir = li._repo_cache_dir(VIS["adapter"])
    for d in (llm_dir, vis_dir):
        (d / "blobs").mkdir(parents=True)
        (d / "blobs" / "x").write_text("weights")
    out = li.delete_models("llm")
    assert out["deleted"] == ["LiquidAI/LFM2.5-VL-3B-GGUF"]
    assert not llm_dir.exists()
    assert vis_dir.exists()  # visual untouched


def test_bytes_on_disk_counts_partials(isolated):
    """Progress must include HuggingFace's *.incomplete blobs — that is the
    whole point of read-side accounting during a download."""
    li = isolated
    d = li._repo_cache_dir("LiquidAI/LFM2.5-VL-3B-GGUF") / "blobs"
    d.mkdir(parents=True)
    (d / "abc123").write_bytes(b"x" * 100)
    (d / "def456.incomplete").write_bytes(b"y" * 50)
    assert li._bytes_on_disk("LiquidAI/LFM2.5-VL-3B-GGUF") == 150


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture
def client(isolated, monkeypatch) -> Iterator[TestClient]:
    import src.server as server
    importlib.reload(server)
    with TestClient(server.app) as c:
        yield c
    importlib.reload(server)


def test_endpoints_roundtrip(client, isolated, monkeypatch):
    li = isolated
    _all_present(monkeypatch, li)
    r = client.get("/local/status")
    assert r.status_code == 200
    assert r.json()["state"] == "ready"

    # ready → install still 202s (worker no-ops on an empty plan)
    monkeypatch.setattr(li, "_preflight_disk", lambda n: None)
    r = client.post("/local/install")
    assert r.status_code == 202
    _wait_idle(li)

    r = client.post("/local/install/cancel")
    assert r.status_code == 409  # nothing running

    r = client.delete("/local/model", params={"component": "bogus"})
    assert r.status_code == 422

    r = client.delete("/local/model", params={"component": "llm"})
    assert r.status_code == 200


def test_providers_endpoint_reports_real_downloaded_flag(client, isolated, monkeypatch):
    """The `downloaded: True  # v1 assumption` stub is gone — the Settings
    card's flag must now track reality."""
    li = isolated
    _all_missing(monkeypatch, li)
    r = client.get("/settings/search/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["local"]["downloaded"] is False
    assert "LFM2.5" in body["local"]["model"]

    _all_present(monkeypatch, li)
    r = client.get("/settings/search/providers")
    assert r.json()["local"]["downloaded"] is True
