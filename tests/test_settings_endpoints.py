"""Endpoint tests for the new Settings surface in src/server.py.

Uses FastAPI's TestClient. Each test isolates `APP_DATA_DIR` via the
`MAGPIE_DATA_DIR` env var (honored by `src.manifest._resolve_app_data_dir`)
so we don't pollute the user's real config files.

Covers:
  - GET/PATCH roundtrip on /settings/search and /settings/app
  - 400 on out-of-range PATCH values (Pydantic Field validation)
  - /settings/folders PATCH toggle (existing folder + 404)
  - /settings/exclusions: GET, POST add path / glob, DELETE by type+value
  - /settings/search/providers reports cloud configured iff secrets has key
  - PUT /settings/shortcut writes shortcut.json atomically
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_app_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Point APP_DATA_DIR at a tmp dir for the duration of the test.

    `src.manifest` resolves APP_DATA_DIR at import time. We need to
    re-import the modules that read from it after the env var is set,
    AND undo the reload after the test so we don't pollute module
    state for tests that run later in the session (specifically: tests
    that use APP_DATA_DIR-dependent paths captured at their own import
    time, which would now point at our deleted tmp dir).
    """
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    # Re-import modules that captured APP_DATA_DIR at import time.
    import src.manifest
    importlib.reload(src.manifest)
    import src.config.indexing_rules as ir
    importlib.reload(ir)
    import src.config.settings as st
    importlib.reload(st)
    import src.config.secrets as sec
    importlib.reload(sec)
    # Stub out dotenv so the tests don't pull OPENROUTER_API_KEY from
    # the project's `.env` and surprise the cloud-key assertions.
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    try:
        yield tmp_path
    finally:
        # Restore module state to point at the real APP_DATA_DIR.
        # monkeypatch unsets MAGPIE_DATA_DIR before this finally runs,
        # so the reload re-resolves to the user's real data dir.
        monkeypatch.undo()
        importlib.reload(src.manifest)
        importlib.reload(ir)
        importlib.reload(st)
        importlib.reload(sec)


@pytest.fixture
def client(isolated_app_data: Path) -> TestClient:
    """A TestClient with isolated config. Importing src.server after
    isolation so its module-level constants resolve to the tmp dir."""
    import src.server as server
    importlib.reload(server)
    return TestClient(server.app)


# ---------------------------------------------------------------------------
# /settings/search
# ---------------------------------------------------------------------------


def test_get_settings_search_returns_defaults(client: TestClient) -> None:
    r = client.get("/settings/search")
    assert r.status_code == 200
    body = r.json()
    # Default provider in magpie_defaults.json is "local".
    assert body["provider"] == "local"
    assert 1 <= body["top_k"] <= 20
    assert isinstance(body["rewrite"], bool)
    assert isinstance(body["temperature"], float)
    assert "model" in body


def test_patch_settings_search_persists(client: TestClient) -> None:
    r = client.patch("/settings/search", json={"top_k": 10, "rewrite": True})
    assert r.status_code == 200
    body = r.json()
    assert body["top_k"] == 10
    assert body["rewrite"] is True
    # Verify GET sees the change.
    body2 = client.get("/settings/search").json()
    assert body2["top_k"] == 10
    assert body2["rewrite"] is True


def test_patch_settings_search_provider_switch(client: TestClient) -> None:
    r = client.patch("/settings/search", json={"provider": "cloud"})
    assert r.status_code == 200
    assert r.json()["provider"] == "cloud"


def test_patch_settings_search_rejects_out_of_range(client: TestClient) -> None:
    # Pydantic Field validation: top_k > 20 → 422.
    r = client.patch("/settings/search", json={"top_k": 99})
    assert r.status_code == 422
    r = client.patch("/settings/search", json={"temperature": 5.0})
    assert r.status_code == 422
    # Invalid provider → 422.
    r = client.patch("/settings/search", json={"provider": "pigeon"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /settings/app
# ---------------------------------------------------------------------------


def test_get_settings_app_returns_defaults(client: TestClient) -> None:
    body = client.get("/settings/app").json()
    assert body["theme"] in {"system", "light", "dark"}
    assert body["accent"] in {"ink", "amber", "jade", "rose"}
    assert isinstance(body["launch_at_login"], bool)


def test_patch_settings_app_persists(client: TestClient) -> None:
    r = client.patch("/settings/app", json={"theme": "dark", "accent": "jade"})
    assert r.status_code == 200
    assert r.json()["theme"] == "dark"
    assert r.json()["accent"] == "jade"


def test_patch_settings_app_rejects_invalid_theme(client: TestClient) -> None:
    r = client.patch("/settings/app", json={"theme": "vivid"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /settings/folders PATCH (toggle)
# ---------------------------------------------------------------------------


def test_patch_folder_toggle_existing(client: TestClient, tmp_path: Path) -> None:
    # First add a folder.
    folder = tmp_path / "Docs"
    folder.mkdir()
    r = client.post("/settings/folders", json={"path": str(folder)})
    assert r.status_code == 200

    # Toggle it off.
    r = client.patch(
        "/settings/folders",
        json={"path": str(folder), "enabled": False},
    )
    assert r.status_code == 200

    # GET reflects the change.
    folders = client.get("/settings/folders").json()["folders"]
    matching = [f for f in folders if f["path"] == str(folder.resolve())]
    assert len(matching) == 1
    assert matching[0]["enabled"] is False


def test_patch_folder_toggle_404_for_unknown_path(client: TestClient) -> None:
    r = client.patch(
        "/settings/folders",
        json={"path": "/no/such/path", "enabled": True},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /settings/exclusions
# ---------------------------------------------------------------------------


def test_get_exclusions_returns_empty_initially(client: TestClient) -> None:
    body = client.get("/settings/exclusions").json()
    assert body["paths"] == []
    # globs may be empty or have user-rule defaults; either is fine.
    assert isinstance(body["globs"], list)


def test_post_exclusion_path_then_glob(client: TestClient, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.touch()

    r = client.post("/settings/exclusions", json={"path": str(secret)})
    assert r.status_code == 200
    assert r.json()["status"] == "added"

    r = client.post("/settings/exclusions", json={"glob": "*.bak"})
    assert r.status_code == 200
    assert r.json()["status"] == "added"

    body = client.get("/settings/exclusions").json()
    assert str(secret.resolve()) in body["paths"]
    assert "*.bak" in body["globs"]


def test_post_exclusion_rejects_both_or_neither(client: TestClient) -> None:
    r = client.post("/settings/exclusions", json={})
    assert r.status_code == 400
    r = client.post("/settings/exclusions", json={"path": "/x", "glob": "*.y"})
    assert r.status_code == 400


def test_delete_exclusion_by_type_and_value(client: TestClient, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.touch()
    client.post("/settings/exclusions", json={"path": str(secret)})

    r = client.delete(
        f"/settings/exclusions?type=path&value={secret.resolve()}"
    )
    assert r.status_code == 200
    assert r.json()["status"] == "removed"

    body = client.get("/settings/exclusions").json()
    assert str(secret.resolve()) not in body["paths"]


def test_delete_exclusion_404_when_missing(client: TestClient) -> None:
    r = client.delete("/settings/exclusions?type=glob&value=*.does_not_exist")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /settings/search/providers
# ---------------------------------------------------------------------------


def test_providers_reports_cloud_unconfigured_when_no_key(
    client: TestClient,
) -> None:
    body = client.get("/settings/search/providers").json()
    assert body["local"]["available"] is True
    # No key bootstrapped (env stubbed, no .env in tmp dir).
    assert body["cloud"]["configured"] is False
    assert body["cloud"]["available"] is False


def test_providers_reports_cloud_configured_when_key_set(
    client: TestClient, isolated_app_data: Path
) -> None:
    """Cloud is configured iff the active provider's API key is set.
    Default cloud_provider is openrouter, so plant the openrouter key."""
    import src.config.secrets as secrets_mod
    secrets_mod.save_secrets(secrets_mod.Secrets(
        cloud_provider="openrouter",
        openrouter_api_key="sk-or-test",
    ))

    body = client.get("/settings/search/providers").json()
    assert body["cloud"]["configured"] is True
    assert body["cloud"]["available"] is True
    assert body["cloud"]["provider"] == "openrouter"


def test_providers_reports_unconfigured_when_only_other_provider_has_key(
    client: TestClient, isolated_app_data: Path
) -> None:
    """If cloud_provider is openrouter but only moonshot has a key,
    cloud is reported as unconfigured — matches build_chat_model()'s
    runtime behavior (it would fail to authenticate)."""
    import src.config.secrets as secrets_mod
    secrets_mod.save_secrets(secrets_mod.Secrets(
        cloud_provider="openrouter",
        moonshot_api_key="sk-ms-only",
    ))

    body = client.get("/settings/search/providers").json()
    assert body["cloud"]["configured"] is False


def test_providers_reports_moonshot_when_active(
    client: TestClient, isolated_app_data: Path
) -> None:
    import src.config.secrets as secrets_mod
    secrets_mod.save_secrets(secrets_mod.Secrets(
        cloud_provider="moonshot",
        moonshot_api_key="sk-ms-1",
        moonshot_model="kimi-test",
    ))

    body = client.get("/settings/search/providers").json()
    assert body["cloud"]["configured"] is True
    assert body["cloud"]["model"] == "kimi-test"
    assert body["cloud"]["provider"] == "moonshot"


# ---------------------------------------------------------------------------
# PUT /settings/shortcut
# ---------------------------------------------------------------------------


def test_put_shortcut_writes_atomically(
    client: TestClient, isolated_app_data: Path
) -> None:
    r = client.put("/settings/shortcut", json={"shortcut": "Ctrl+Q"})
    assert r.status_code == 200
    assert r.json()["shortcut"] == "Ctrl+Q"

    # File on disk reflects.
    p = isolated_app_data / "shortcut.json"
    assert p.exists()
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["shortcut"] == "Ctrl+Q"

    # GET round-trips.
    assert client.get("/settings/shortcut").json()["shortcut"] == "Ctrl+Q"


def test_put_shortcut_rejects_empty(client: TestClient) -> None:
    r = client.put("/settings/shortcut", json={"shortcut": ""})
    assert r.status_code == 422
