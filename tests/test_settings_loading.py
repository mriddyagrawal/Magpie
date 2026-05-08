"""Config load/save tests for the user-facing app settings.

Mirrors the shape of `tests/test_indexing_rules_loading.py`. Covers:
  - Roundtrip (write → read, equal)
  - Missing file → empty defaults written + returned
  - Malformed JSON → clear failure
  - Effective merge order: env > user > defaults
  - Unknown extra fields ignored on both AppDefaults and UserSettings
  - patch_user_settings sets only the keys passed and persists
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.settings import (
    AppDefaults,
    UserSettings,
    effective_settings,
    load_app_defaults,
    load_user_settings,
    patch_user_settings,
    save_user_settings,
)


# ---------------------------------------------------------------------------
# Roundtrip + first-call
# ---------------------------------------------------------------------------


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    s = UserSettings(provider="cloud", top_k=10, theme="dark", accent="jade")
    save_user_settings(s, p)
    loaded = load_user_settings(p)
    assert loaded.provider == "cloud"
    assert loaded.top_k == 10
    assert loaded.theme == "dark"
    assert loaded.accent == "jade"
    # Untouched fields stay None — none of "fallthrough to defaults" semantics
    assert loaded.temperature is None
    assert loaded.launch_at_login is None


def test_load_creates_default_file_when_missing(tmp_path: Path) -> None:
    """First-launch creates settings.json populated with the bundled
    AppDefaults (provider='local', top_k=5, theme='system', etc.) so
    the user can inspect the file and immediately see what they're
    starting with — instead of a wall of nulls. Subsequent edits via
    PATCH endpoints replace these values; explicitly setting a field
    to None at the API level falls through to AppDefaults at merge
    time."""
    p = tmp_path / "missing.json"
    assert not p.exists()
    s = load_user_settings(p)
    assert p.exists()
    # Seeded with the live bundled AppDefaults.
    assert s.version == 1
    assert s.provider == "local"
    assert s.top_k == 5
    assert s.theme == "system"


def test_malformed_json_raises_clearly(tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{ this is not json")
    with pytest.raises(json.JSONDecodeError):
        load_user_settings(p)


# ---------------------------------------------------------------------------
# AppDefaults — bundled file
# ---------------------------------------------------------------------------


def test_load_real_app_defaults_succeeds() -> None:
    """Bundled `magpie_defaults.json` must parse cleanly — a regression
    here breaks first-run for every new user. Same gate as the
    indexing-rules test. Cloud routing fields (cloud_provider,
    per-provider models, API keys) live in secrets.json now, not
    AppDefaults — so they're not asserted here."""
    d = load_app_defaults()
    assert d.version == 1
    assert d.provider in {"local", "cloud"}
    assert 1 <= d.top_k <= 20
    assert d.theme in {"system", "light", "dark"}


def test_app_defaults_strips_comment_fields(tmp_path: Path) -> None:
    p = tmp_path / "defaults.json"
    p.write_text(json.dumps({
        "_comment": "stripped",
        "version": 1,
        "provider": "cloud",
        "top_k": 8,
    }))
    d = load_app_defaults(p)
    assert d.provider == "cloud"
    assert d.top_k == 8


def test_app_defaults_ignores_indexing_rules_keys(tmp_path: Path) -> None:
    """The same magpie_defaults.json file is read by AppDefaults AND by
    MagpieDefaults (indexing). Each model must ignore the other's keys
    via Pydantic `extra='ignore'`. Without this, the two would
    interfere."""
    p = tmp_path / "defaults.json"
    p.write_text(json.dumps({
        "version": 1,
        "exclude_dirs": ["node_modules", ".git"],     # indexing keys
        "exclude_globs": ["*.log"],
        "exclude_extensions": [".pyc"],
        "ignore_hidden": True,
        "provider": "local",                            # app keys
        "top_k": 7,
    }))
    d = load_app_defaults(p)
    assert d.provider == "local"
    assert d.top_k == 7


# ---------------------------------------------------------------------------
# Effective merge: env > user > defaults
# ---------------------------------------------------------------------------


def _write_defaults(tmp_path: Path, **kwargs) -> Path:
    p = tmp_path / "defaults.json"
    base = {"version": 1, "provider": "local", "top_k": 5, "theme": "system"}
    base.update(kwargs)
    p.write_text(json.dumps(base))
    return p


def test_effective_uses_defaults_when_user_settings_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    defaults_path = _write_defaults(tmp_path, provider="local", top_k=5, theme="dark")
    user_path = tmp_path / "settings.json"  # missing → load creates empty file
    eff = effective_settings(user_path=user_path, defaults_path=defaults_path)
    assert eff.provider == "local"
    assert eff.top_k == 5
    assert eff.theme == "dark"


def test_effective_user_settings_override_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without delenv, the project's `.env` LLM_PROVIDER would clobber the
    # user's choice via the env-override path, which is correct production
    # behavior but defeats the test's purpose.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    defaults_path = _write_defaults(tmp_path, provider="local", top_k=5)
    user_path = tmp_path / "settings.json"
    save_user_settings(UserSettings(provider="cloud", top_k=12), user_path)
    eff = effective_settings(user_path=user_path, defaults_path=defaults_path)
    assert eff.provider == "cloud"
    assert eff.top_k == 12


def test_effective_user_none_falls_through_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    defaults_path = _write_defaults(tmp_path, provider="local", top_k=5, theme="dark")
    user_path = tmp_path / "settings.json"
    # Only set top_k; provider and theme stay None.
    save_user_settings(UserSettings(top_k=15), user_path)
    eff = effective_settings(user_path=user_path, defaults_path=defaults_path)
    assert eff.provider == "local"   # default
    assert eff.top_k == 15           # user
    assert eff.theme == "dark"       # default


def test_effective_env_overrides_user(tmp_path: Path, monkeypatch) -> None:
    defaults_path = _write_defaults(tmp_path, provider="local")
    user_path = tmp_path / "settings.json"
    save_user_settings(UserSettings(provider="cloud"), user_path)
    monkeypatch.setenv("LLM_PROVIDER", "local")
    eff = effective_settings(user_path=user_path, defaults_path=defaults_path)
    # Env wins over user setting.
    assert eff.provider == "local"


def test_effective_env_cloud_provider_name_maps_to_cloud(tmp_path: Path, monkeypatch) -> None:
    """LLM_PROVIDER=openrouter from .env should map to provider='cloud'
    so the Settings UI's binary toggle reflects reality."""
    defaults_path = _write_defaults(tmp_path, provider="local")
    user_path = tmp_path / "settings.json"
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    eff = effective_settings(user_path=user_path, defaults_path=defaults_path)
    assert eff.provider == "cloud"


# ---------------------------------------------------------------------------
# Forward-compat: extra fields ignored
# ---------------------------------------------------------------------------


def test_unknown_extra_fields_in_user_json_are_ignored(tmp_path: Path) -> None:
    """A future Magpie release might add fields. Older clients reading
    the same file should drop unknown keys, not crash."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "version": 1,
        "provider": "cloud",
        "future_feature_x": "anything",
    }))
    s = load_user_settings(p)
    assert s.provider == "cloud"


# ---------------------------------------------------------------------------
# patch_user_settings
# ---------------------------------------------------------------------------


def test_patch_sets_passed_keys_and_persists(tmp_path: Path) -> None:
    user_path = tmp_path / "settings.json"
    # Bootstrap with one value.
    save_user_settings(UserSettings(provider="local", top_k=5), user_path)
    # Patch top_k only.
    new = patch_user_settings(user_path=user_path, top_k=12)
    assert new.provider == "local"
    assert new.top_k == 12
    # Verify persistence.
    reloaded = load_user_settings(user_path)
    assert reloaded.top_k == 12
    assert reloaded.provider == "local"


def test_patch_silently_drops_unknown_kwargs(tmp_path: Path) -> None:
    user_path = tmp_path / "settings.json"
    save_user_settings(UserSettings(provider="cloud"), user_path)
    new = patch_user_settings(user_path=user_path, no_such_field="ignored")
    # Provider unchanged; no exception raised.
    assert new.provider == "cloud"
