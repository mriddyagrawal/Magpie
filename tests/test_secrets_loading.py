"""Secret-store tests for src/config/secrets.py.

Covers:
  - Bootstrap reads per-provider keys + models from env (dev path)
  - LLM_PROVIDER in env seeds cloud_provider (constrained to v1 set)
  - Bootstrap with empty env writes baseline defaults
  - Subsequent loads skip bootstrap (non-empty values never mutated)
  - Healing: EMPTY credential fields re-seed from env / bundle on load
    and persist (the "stale first-launch bootstrap" self-heal)
  - Atomic save with mode 0600 (POSIX only)
  - Forward-compat: unknown extra fields ignored
  - cloud_credentials_for() returns the correct (key, model) tuple
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from src.config.secrets import (
    Secrets,
    _bootstrap_secrets,
    cloud_credentials_for,
    load_secrets,
    save_secrets,
)


# ---------------------------------------------------------------------------
# Bootstrap — reads per-provider env vars
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_dev_machine_credentials(monkeypatch):
    """These tests assert empty-credential behavior; on a dev machine a real
    src/config/bundled_key.txt (gitignored, production-build artifact) and
    .env-loaded keys leak in and every assert sees a real key (test-suite
    triage 2026-08-30). Neutralize both - a fresh clone is the contract."""
    from src.config import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "_bundled_key", lambda: "")
    # ...and the dev machine's real <app-data>/secrets.json - endpoints load
    # through _secrets_path(), which must resolve to a per-test tmp file.
    import tempfile as _tf
    _tmp = Path(_tf.mkdtemp(prefix="magpie-test-secrets-")) / "secrets.json"
    monkeypatch.setattr(secrets_mod, "_secrets_path", lambda: _tmp)
    # heal path calls load_dotenv on every load - the repo's real .env
    # would refill the key straight after we cleared it
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    for v in ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", "MOONSHOT_API_KEY",
              "MOONSHOT_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(v, raising=False)


def test_bootstrap_reads_openrouter_credentials_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dev path: with `.env` populated, first load seeds secrets.json
    with the openrouter key + model."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-1234")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemma-2-27b-it:free")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    secrets_path = tmp_path / "secrets.json"
    s = load_secrets(secrets_path)

    assert s.openrouter_api_key == "sk-or-test-1234"
    assert s.openrouter_model == "google/gemma-2-27b-it:free"
    raw = json.loads(secrets_path.read_text(encoding="utf-8"))
    assert raw["openrouter_api_key"] == "sk-or-test-1234"


def test_bootstrap_reads_moonshot_credentials_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-ms-abc")
    monkeypatch.setenv("MOONSHOT_MODEL", "kimi-custom-1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    secrets_path = tmp_path / "secrets.json"
    s = load_secrets(secrets_path)

    assert s.moonshot_api_key == "sk-ms-abc"
    assert s.moonshot_model == "kimi-custom-1"


def test_bootstrap_llm_provider_env_seeds_cloud_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM_PROVIDER=moonshot in .env should set cloud_provider in
    secrets.json so the user's deployment intent persists."""
    monkeypatch.setenv("LLM_PROVIDER", "moonshot")
    monkeypatch.chdir(tmp_path)
    s = load_secrets(tmp_path / "secrets.json")
    assert s.cloud_provider == "moonshot"


def test_bootstrap_llm_provider_local_falls_through_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM_PROVIDER=local doesn't seed cloud_provider (local isn't a
    cloud); fall back to the BaseModel default ("openrouter")."""
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.chdir(tmp_path)
    s = load_secrets(tmp_path / "secrets.json")
    assert s.cloud_provider == "openrouter"


def test_bootstrap_llm_provider_unknown_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM_PROVIDER=ollama or some unsupported v1 cloud value should
    fall back to the default rather than fail validation."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.chdir(tmp_path)
    s = load_secrets(tmp_path / "secrets.json")
    assert s.cloud_provider == "openrouter"


def test_bootstrap_with_empty_env_writes_baseline_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bundled-app path with no keys configured: load returns Secrets
    with the BaseModel defaults (empty keys, default models)."""
    for v in ("LLM_PROVIDER", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
              "MOONSHOT_API_KEY", "MOONSHOT_MODEL"):
        monkeypatch.delenv(v, raising=False)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    monkeypatch.chdir(tmp_path)

    secrets_path = tmp_path / "secrets.json"
    s = load_secrets(secrets_path)

    assert s.openrouter_api_key == ""
    assert s.moonshot_api_key == ""
    assert s.cloud_provider == "openrouter"
    # Default models still populated.
    assert s.openrouter_model
    assert s.moonshot_model
    assert secrets_path.exists()


def test_subsequent_loads_skip_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once secrets.json holds a NON-EMPTY key, subsequent loads do NOT
    consult .env for it again. Otherwise an env-var change would
    silently mutate the runtime key. (Empty fields are different —
    they heal; see the healing section below.)"""
    secrets_path = tmp_path / "secrets.json"
    save_secrets(
        Secrets(openrouter_api_key="persisted-key", moonshot_api_key="ms-key"),
        secrets_path,
    )

    # Even with a different env value, the file wins.
    monkeypatch.setenv("OPENROUTER_API_KEY", "different-env-key")
    s = load_secrets(secrets_path)

    assert s.openrouter_api_key == "persisted-key"
    assert s.moonshot_api_key == "ms-key"


# ---------------------------------------------------------------------------
# Atomic save + permissions
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_save_secrets_chmod_0600(tmp_path: Path) -> None:
    """The file must be owner-only readable. A 644 leak would expose
    the cloud key to any local process."""
    p = tmp_path / "secrets.json"
    save_secrets(Secrets(openrouter_api_key="sensitive"), p)
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_save_is_atomic_via_tmp_rename(tmp_path: Path) -> None:
    """The save uses a `.tmp` staged file; verify there's no leftover
    after a successful save."""
    p = tmp_path / "secrets.json"
    save_secrets(Secrets(openrouter_api_key="x"), p)
    assert p.exists()
    assert not p.with_suffix(p.suffix + ".tmp").exists()


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_cloud_provider_only_accepts_v1_set(tmp_path: Path) -> None:
    """Pydantic Literal must reject any provider name outside the v1
    set (moonshot / openrouter). Adding a third must be a deliberate
    schema change, not a silent typo."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Secrets(cloud_provider="ollama")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Forward-compat
# ---------------------------------------------------------------------------


def _isolate_heal_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize every healing source so tests asserting EMPTY key
    fields stay deterministic: without this, `_heal_empty_credentials`
    would pull the dev machine's real key out of `.env` (and the real
    `load_dotenv()` would pollute os.environ for the whole session)."""
    for v in ("OPENROUTER_API_KEY", "MOONSHOT_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)


def test_unknown_extra_fields_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A future Magpie release might add `magpie_cloud_api_key`. Older
    code reading the same file should drop unknown keys, not crash."""
    _isolate_heal_sources(monkeypatch)
    p = tmp_path / "secrets.json"
    p.write_text(json.dumps({
        "version": 1,
        "openrouter_api_key": "sk-or-x",
        "future_field": "anything",
    }))
    s = load_secrets(p)
    assert s.openrouter_api_key == "sk-or-x"


def test_legacy_cloud_api_key_field_dropped_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Earlier PR 3 commits used a flat `cloud_api_key` field. After
    the per-provider restructure, secrets.json files written under that
    schema should load cleanly with the legacy key dropped — there's
    no migration, but no crash either."""
    _isolate_heal_sources(monkeypatch)
    p = tmp_path / "secrets.json"
    p.write_text(json.dumps({"version": 1, "cloud_api_key": "legacy-value"}))
    s = load_secrets(p)
    # Legacy key absent on the new model; new fields populated with defaults.
    assert s.openrouter_api_key == ""
    assert s.cloud_provider == "openrouter"


def test_load_returns_valid_secrets_for_missing_optional_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A minimal secrets.json (just version) should load with all
    BaseModel defaults populated."""
    _isolate_heal_sources(monkeypatch)
    p = tmp_path / "secrets.json"
    p.write_text(json.dumps({"version": 1}))
    s = load_secrets(p)
    assert s.openrouter_api_key == ""
    assert s.moonshot_api_key == ""
    assert s.cloud_provider == "openrouter"


# ---------------------------------------------------------------------------
# Healing — empty credential fields re-seed on load
# ---------------------------------------------------------------------------


def test_load_heals_empty_openrouter_key_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dev-build self-heal: a secrets.json bootstrapped BEFORE the
    key landed in .env used to stick forever (the Settings card's
    'Not configured yet' bug). An empty key must re-seed on load."""
    _isolate_heal_sources(monkeypatch)
    secrets_path = tmp_path / "secrets.json"
    save_secrets(Secrets(), secrets_path)  # stale bootstrap: empty keys

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-healed")
    s = load_secrets(secrets_path)

    assert s.openrouter_api_key == "sk-or-healed"
    # Persisted, not just in-memory — the next load short-circuits.
    raw = json.loads(secrets_path.read_text(encoding="utf-8"))
    assert raw["openrouter_api_key"] == "sk-or-healed"


def test_load_heals_empty_moonshot_key_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_heal_sources(monkeypatch)
    secrets_path = tmp_path / "secrets.json"
    save_secrets(Secrets(cloud_provider="moonshot"), secrets_path)

    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-ms-healed")
    s = load_secrets(secrets_path)

    assert s.moonshot_api_key == "sk-ms-healed"
    assert s.openrouter_api_key == ""  # no source for this one — untouched


def test_load_heals_empty_key_from_bundled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production path: an app update that ships a bundled key must
    revive a secrets.json bootstrapped by an older key-less build."""
    _isolate_heal_sources(monkeypatch)
    import src.config.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "_bundled_key", lambda: "bundled-xyz")

    secrets_path = tmp_path / "secrets.json"
    secrets_mod.save_secrets(secrets_mod.Secrets(), secrets_path)
    s = secrets_mod.load_secrets(secrets_path)

    assert s.openrouter_api_key == "bundled-xyz"


def test_load_heals_whitespace_only_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whitespace-only key is as unconfigured as an empty one —
    matches the providers endpoint's `bool(key.strip())` check."""
    _isolate_heal_sources(monkeypatch)
    secrets_path = tmp_path / "secrets.json"
    save_secrets(Secrets(openrouter_api_key="   "), secrets_path)

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-real")
    s = load_secrets(secrets_path)

    assert s.openrouter_api_key == "sk-or-real"


def test_load_heal_noop_when_no_source_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No env, no bundle: keys stay empty and the file is NOT
    rewritten (no gratuitous mtime churn on every settings read)."""
    _isolate_heal_sources(monkeypatch)
    secrets_path = tmp_path / "secrets.json"
    save_secrets(Secrets(), secrets_path)
    before = secrets_path.read_bytes()
    mtime_before = secrets_path.stat().st_mtime_ns

    s = load_secrets(secrets_path)

    assert s.openrouter_api_key == ""
    assert s.moonshot_api_key == ""
    assert secrets_path.read_bytes() == before
    assert secrets_path.stat().st_mtime_ns == mtime_before


def test_load_tolerates_utf8_bom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows Notepad historically saves UTF-8 WITH a BOM. A BOM'd
    secrets.json used to make every load_secrets() raise — which the
    providers endpoint swallows as 'unconfigured', i.e. Cloud dead
    forever with no visible error. utf-8-sig accepts both."""
    _isolate_heal_sources(monkeypatch)
    p = tmp_path / "secrets.json"
    p.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps({"version": 1, "openrouter_api_key": "sk-bom"}).encode("utf-8")
    )
    s = load_secrets(p)
    assert s.openrouter_api_key == "sk-bom"


def test_load_heals_bom_file_with_empty_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The combined case seen in live verification: BOM'd file AND an
    empty key. Both fixes must compose — parse past the BOM, then heal
    the empty key from env."""
    _isolate_heal_sources(monkeypatch)
    p = tmp_path / "secrets.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"version": 1}).encode("utf-8"))

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-after-bom")
    s = load_secrets(p)

    assert s.openrouter_api_key == "sk-or-after-bom"
    # The healed rewrite goes through save_secrets, which writes clean
    # UTF-8 — the BOM is gone after the first successful load.
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")


def test_load_heal_never_touches_nonempty_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both keys populated → healing early-exits entirely: env is not
    consulted and the persisted values win (authoritative-store rule)."""
    _isolate_heal_sources(monkeypatch)
    secrets_path = tmp_path / "secrets.json"
    save_secrets(
        Secrets(openrouter_api_key="persisted-or", moonshot_api_key="persisted-ms"),
        secrets_path,
    )

    monkeypatch.setenv("OPENROUTER_API_KEY", "env-should-lose")
    monkeypatch.setenv("MOONSHOT_API_KEY", "env-should-lose-too")
    s = load_secrets(secrets_path)

    assert s.openrouter_api_key == "persisted-or"
    assert s.moonshot_api_key == "persisted-ms"


# ---------------------------------------------------------------------------
# Direct bootstrap (no I/O preconditions)
# ---------------------------------------------------------------------------


def test_direct_bootstrap_returns_secrets_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_bootstrap_secrets` returns a Secrets even when no env / file
    are available — important so callers can rely on a non-None result.

    Use a structural check (not `isinstance`) because the endpoint test
    suite reloads `src.config.secrets`, which gives a different class
    object than the one imported here at module top."""
    for v in ("LLM_PROVIDER", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
              "MOONSHOT_API_KEY", "MOONSHOT_MODEL"):
        monkeypatch.delenv(v, raising=False)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    monkeypatch.chdir(tmp_path)

    p = tmp_path / "secrets.json"
    s = _bootstrap_secrets(p)
    assert type(s).__name__ == "Secrets"
    assert s.openrouter_api_key == ""
    assert s.moonshot_api_key == ""
    assert s.cloud_provider == "openrouter"
    assert p.exists()


# ---------------------------------------------------------------------------
# cloud_credentials_for() helper
# ---------------------------------------------------------------------------


def test_cloud_credentials_for_returns_active_provider_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helper used by `build_chat_model()` must return the per-
    provider tuple regardless of which provider is currently active —
    the caller in llm.py chooses based on `cfg.name`."""
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(tmp_path))
    # Force re-import so APP_DATA_DIR captures tmp_path.
    import importlib
    import src.manifest as manifest_mod
    importlib.reload(manifest_mod)
    import src.config.secrets as secrets_mod
    importlib.reload(secrets_mod)

    s = secrets_mod.Secrets(
        openrouter_api_key="or-key",
        openrouter_model="or-model",
        moonshot_api_key="ms-key",
        moonshot_model="ms-model",
    )
    secrets_mod.save_secrets(s)

    assert secrets_mod.cloud_credentials_for("openrouter") == ("or-key", "or-model")
    assert secrets_mod.cloud_credentials_for("moonshot") == ("ms-key", "ms-model")
    # Unknown provider — empty tuple.
    assert secrets_mod.cloud_credentials_for("ollama") == ("", "")

    # Restore module state so later tests don't see the tmp dir.
    monkeypatch.undo()
    importlib.reload(manifest_mod)
    importlib.reload(secrets_mod)
