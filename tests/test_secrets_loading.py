"""Secret-store tests for src/config/secrets.py.

Covers:
  - Bootstrap reads OPENROUTER_API_KEY from env (dev path)
  - Bootstrap with empty env writes empty key (no crash)
  - Subsequent loads skip bootstrap (env var not consulted again)
  - Atomic save with mode 0600 (POSIX only)
  - Forward-compat: unknown extra fields ignored
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from src.config.secrets import (
    Secrets,
    _bootstrap_secrets,
    load_secrets,
    save_secrets,
)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_reads_openrouter_api_key_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dev path: with `.env` populated (or env exported), first load
    seeds `secrets.json` with the cloud key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-1234")
    # Avoid leaking from any real .env file in the project root.
    monkeypatch.chdir(tmp_path)

    secrets_path = tmp_path / "secrets.json"
    s = load_secrets(secrets_path)

    assert s.cloud_api_key == "sk-or-test-1234"
    assert secrets_path.exists()
    # Persisted value matches.
    raw = json.loads(secrets_path.read_text(encoding="utf-8"))
    assert raw["cloud_api_key"] == "sk-or-test-1234"


def test_bootstrap_with_empty_env_writes_empty_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bundled-app path with no key configured: load returns an empty
    Secrets and writes the file so subsequent loads skip bootstrap.

    NB: `load_dotenv` walks up looking for a `.env` and would re-set
    OPENROUTER_API_KEY from the project root's `.env`. Stub it at the
    `dotenv` module level so the lazy-imported reference inside
    `_bootstrap_secrets` picks up the no-op."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    monkeypatch.chdir(tmp_path)

    secrets_path = tmp_path / "secrets.json"
    s = load_secrets(secrets_path)

    assert s.cloud_api_key == ""
    assert secrets_path.exists()


def test_subsequent_loads_skip_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once `secrets.json` exists, subsequent loads do NOT consult
    .env again. Otherwise an env-var change would silently mutate
    the runtime key."""
    secrets_path = tmp_path / "secrets.json"
    save_secrets(Secrets(cloud_api_key="persisted-key"), secrets_path)

    # Even with a different env value, the file wins.
    monkeypatch.setenv("OPENROUTER_API_KEY", "different-env-key")
    s = load_secrets(secrets_path)

    assert s.cloud_api_key == "persisted-key"


# ---------------------------------------------------------------------------
# Atomic save + permissions
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_save_secrets_chmod_0600(tmp_path: Path) -> None:
    """The file must be owner-only readable. A 644 leak would expose
    the cloud key to any local process."""
    p = tmp_path / "secrets.json"
    save_secrets(Secrets(cloud_api_key="sensitive"), p)
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_save_is_atomic_via_tmp_rename(tmp_path: Path) -> None:
    """The save uses a `.tmp` staged file; verify there's no leftover
    after a successful save."""
    p = tmp_path / "secrets.json"
    save_secrets(Secrets(cloud_api_key="x"), p)
    assert p.exists()
    assert not p.with_suffix(p.suffix + ".tmp").exists()


# ---------------------------------------------------------------------------
# Forward-compat
# ---------------------------------------------------------------------------


def test_unknown_extra_fields_ignored(tmp_path: Path) -> None:
    """A future Magpie release might add `moonshot_api_key`. Older
    code reading the same file should drop unknown keys, not crash."""
    p = tmp_path / "secrets.json"
    p.write_text(json.dumps({
        "version": 1,
        "cloud_api_key": "sk-or-x",
        "future_field": "anything",
    }))
    s = load_secrets(p)
    assert s.cloud_api_key == "sk-or-x"


def test_load_returns_valid_secrets_for_missing_optional_fields(tmp_path: Path) -> None:
    """A minimal secrets.json (just version) should load with defaults."""
    p = tmp_path / "secrets.json"
    p.write_text(json.dumps({"version": 1}))
    s = load_secrets(p)
    assert s.cloud_api_key == ""


# ---------------------------------------------------------------------------
# Direct bootstrap (no I/O preconditions)
# ---------------------------------------------------------------------------


def test_direct_bootstrap_returns_secrets_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_bootstrap_secrets` returns a Secrets even when no env / file
    are available — important so callers can rely on a non-None result."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    monkeypatch.chdir(tmp_path)

    p = tmp_path / "secrets.json"
    s = _bootstrap_secrets(p)
    # Structural check — the endpoint test suite calls
    # `importlib.reload(src.config.secrets)`, which makes the reloaded
    # `Secrets` class object different from the one imported at the top
    # of this file, breaking `isinstance`. Asserting on type name +
    # attribute presence is robust to reloads.
    assert type(s).__name__ == "Secrets"
    assert s.cloud_api_key == ""
    assert p.exists()
