"""Secret storage: cloud routing config + API credentials.

Lives at `<APP_DATA_DIR>/secrets.json` with mode 0600 so casual
filesystem access can't read it. Distinct from `settings.json`
because (a) different perms, (b) different access pattern (rare
read, never logged, never echoed to UI), (c) different bootstrap
story (env-seeded on first launch).

The user-facing "Local vs Cloud" binary lives in `settings.json`.
When the user picks "Cloud", `secrets.json:cloud_provider` decides
WHICH cloud — `moonshot` or `openrouter`. That choice is paired
here with the credentials for both providers, so a deployment can
swap provider without code changes.

The user is NOT allowed to edit any of this from the UI in v1 —
Settings → Search & AI surfaces "Local vs Cloud" only. Bring-your-own
key UI is a parked Plan #19 / "Advanced" sidebar concern.

Bootstrap on first load:
  1. Look for `<APP_DATA_DIR>/secrets.json`. If present, return.
  2. `load_dotenv()` (idempotent), read:
       - `LLM_PROVIDER`        → cloud_provider (only if "moonshot"/"openrouter")
       - `OPENROUTER_API_KEY`  → openrouter_api_key
       - `OPENROUTER_MODEL`    → openrouter_model (else baseline default)
       - `MOONSHOT_API_KEY`    → moonshot_api_key
       - `MOONSHOT_MODEL`      → moonshot_model (else baseline default)
  3. Empty `openrouter_api_key` falls back to `_bundled_key()` for
     production builds.
  4. Always write the result so subsequent loads skip bootstrap.

After bootstrap, `.env` is dead to runtime for any NON-EMPTY field —
`secrets.json` is the authoritative store, and an env change never
mutates a persisted key. EMPTY credential fields are the exception:
every load gives `.env` / the bundled key a second chance to fill
them (`_heal_empty_credentials`), so a first launch that ran before
the key existed can't permanently report Cloud as unconfigured.
Env vars still WIN at the dispatch site (`src/llm.py`); secrets is
the second-chance lookup. To fully re-bootstrap (provider choice,
models), delete `secrets.json`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

_USER_SECRETS_FILENAME = "secrets.json"
_BUNDLED_KEY_FILENAME = "bundled_key.txt"

# v1 cloud providers exposed via the settings UI's "Cloud" binary.
# Adding a third (e.g. "magpie-cloud" once a hosted backend exists)
# means: extend this Literal, add fields below, extend the bootstrap
# + llm.py per-provider lookup. Kept as a tuple too for runtime checks.
CLOUD_PROVIDERS: tuple[str, ...] = ("moonshot", "openrouter")
CloudProvider = Literal["moonshot", "openrouter"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class Secrets(BaseModel):
    """The on-disk secrets file. Pydantic `extra="ignore"` for
    forward-compat: a future Magpie release might add e.g.
    `magpie_cloud_api_key`; older code reading the same file should
    drop unknown keys without crashing."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1

    # Which cloud provider runs when settings.json:provider == "cloud".
    # Constrained to the v1 set (moonshot / openrouter); enforced by
    # Pydantic's Literal validation.
    cloud_provider: CloudProvider = "openrouter"

    # OpenRouter credentials + default model. Defaults match the dev-mode
    # values in .env.example so first-launch on a fresh install lands on
    # a working free-tier model.
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemma-4-26b-a4b-it:free"

    # Moonshot credentials + default model.
    moonshot_api_key: str = ""
    moonshot_model: str = "kimi-k2.5"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _config_dir() -> Path:
    """Where bundled-key fallback lives. Same as `magpie_defaults.json`."""
    return Path(__file__).resolve().parent


def _secrets_path() -> Path:
    """Where `secrets.json` lives. Lazy so MAGPIE_DATA_DIR overrides
    are honored after import."""
    from src.manifest import APP_DATA_DIR

    return APP_DATA_DIR / _USER_SECRETS_FILENAME


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_secrets(path: Optional[Path] = None) -> Secrets:
    """Read `secrets.json`. If missing, run the bootstrap flow; if
    present but a credential field is empty, try to heal it from
    `.env` / the bundle. Always returns a valid Secrets — never
    raises for missing files."""
    p = path or _secrets_path()
    if not p.exists():
        return _bootstrap_secrets(p)
    # utf-8-sig: accepts files with AND without a BOM. Windows Notepad
    # historically saves UTF-8 with one; plain utf-8 made json.load
    # raise on the very first byte, which callers swallow as
    # "unconfigured" — a hand-edited secrets.json silently killed Cloud.
    with p.open(encoding="utf-8-sig") as f:
        raw = json.load(f)
    return _heal_empty_credentials(Secrets.model_validate(raw), p)


def save_secrets(secrets: Secrets, path: Optional[Path] = None) -> None:
    """Atomic save with mode 0600.

    The chmod runs on the `.tmp` BEFORE the rename so the visible file
    is never world/group-readable for an instant. On Windows, `chmod`
    is best-effort (ACLs differ from POSIX); the rename still happens.
    """
    p = path or _secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(secrets.model_dump(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        # Windows / non-POSIX: chmod is approximate. Still safer than
        # nothing; the rename is the meaningful step.
        pass
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _bootstrap_secrets(path: Optional[Path] = None) -> Secrets:
    """First-launch flow: seed every secrets field from `.env` (dev) or
    bundled defaults (production). Always writes the result so subsequent
    loads short-circuit."""

    # `dotenv` is already a project dep; load_dotenv is idempotent.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        # Dotenv not installed — only happens in degenerate test envs.
        pass

    # cloud_provider — derived from LLM_PROVIDER in .env, but only when
    # it names one of the v1 cloud providers. "local" or anything else
    # falls back to the BaseModel default ("openrouter").
    raw_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    cloud_provider: CloudProvider = (
        raw_provider if raw_provider in CLOUD_PROVIDERS else "openrouter"  # type: ignore[assignment]
    )

    # Per-provider credentials. Only override BaseModel defaults with
    # non-empty env values — empty env keeps the baseline default.
    kwargs: dict[str, str] = {"cloud_provider": cloud_provider}

    if env_or_key := os.environ.get("OPENROUTER_API_KEY", "").strip():
        kwargs["openrouter_api_key"] = env_or_key
    elif bundled := _bundled_key().strip():
        # Production-build fallback. Dev checkouts don't have this file.
        kwargs["openrouter_api_key"] = bundled
    if env_or_model := os.environ.get("OPENROUTER_MODEL", "").strip():
        kwargs["openrouter_model"] = env_or_model

    if env_ms_key := os.environ.get("MOONSHOT_API_KEY", "").strip():
        kwargs["moonshot_api_key"] = env_ms_key
    if env_ms_model := os.environ.get("MOONSHOT_MODEL", "").strip():
        kwargs["moonshot_model"] = env_ms_model

    s = Secrets(**kwargs)  # type: ignore[arg-type]
    save_secrets(s, path)

    # Diagnostic line so first-launch behavior is observable. Only print
    # when neither provider has a key — that's the "Cloud will be
    # unavailable until configured" state the UI surfaces.
    if not s.openrouter_api_key and not s.moonshot_api_key:
        print(
            "[secrets] no cloud key found in .env or bundle; "
            "Cloud will be unavailable until configured",
            file=sys.stderr,
        )
    return s


def _heal_empty_credentials(s: Secrets, path: Path) -> Secrets:
    """Fill EMPTY credential fields from env / `.env` / the bundle and
    persist the result.

    An empty key means "unconfigured" — there is nothing authoritative
    to protect, so `.env` gets a second chance on every load. This is
    the self-heal for a stale first-launch bootstrap: a `secrets.json`
    written before the key landed in `.env` (dev) or before a bundled
    key shipped (production update) must not permanently disable Cloud.
    Non-empty values are never touched — for those, `secrets.json`
    stays authoritative (see module docstring + the subsequent-loads
    test).
    """
    if s.openrouter_api_key.strip() and s.moonshot_api_key.strip():
        return s  # fully configured — skip the dotenv file I/O

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    healed: list[str] = []
    if not s.openrouter_api_key.strip():
        found = os.environ.get("OPENROUTER_API_KEY", "").strip() or _bundled_key().strip()
        if found:
            s.openrouter_api_key = found
            healed.append("openrouter_api_key")
    if not s.moonshot_api_key.strip():
        if found_ms := os.environ.get("MOONSHOT_API_KEY", "").strip():
            s.moonshot_api_key = found_ms
            healed.append("moonshot_api_key")

    if healed:
        try:
            save_secrets(s, path)
        except OSError as e:
            # Healed in memory either way; persistence just retries on
            # the next load. Loud so a broken data dir is observable.
            print(
                f"[secrets] healed {', '.join(healed)} but could not persist: {e}",
                file=sys.stderr,
            )
        else:
            print(
                f"[secrets] filled empty {', '.join(healed)} from .env/bundle",
                file=sys.stderr,
            )
    return s


def _bundled_key() -> str:
    """Read the build-time-baked OpenRouter key from
    `src/config/bundled_key.txt` if present, empty otherwise.

    Production builds ship this file (Plan #10 packaging concern);
    dev checkouts don't have it (`.gitignore`'d). The file is ASCII —
    one line, the API key, no JSON wrapping — so a build script
    doesn't need a JSON parser. Bundled key is for OpenRouter only;
    Moonshot has no bundled-key fallback."""
    p = _config_dir() / _BUNDLED_KEY_FILENAME
    if not p.exists():
        return ""
    try:
        # utf-8-sig: strip() does NOT remove a BOM, and a BOM-prefixed
        # key would 401 on every request with no visible cause.
        return p.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Convenience accessors used by `src/llm.py`
# ---------------------------------------------------------------------------


def cloud_credentials_for(provider_name: str) -> tuple[str, str]:
    """Return `(api_key, model)` for the given cloud provider. Used by
    `build_chat_model()` as the second-chance lookup when the env var
    isn't set. Empty strings for unknown providers.

    Why this lives here, not at the call site: the per-provider field
    naming (`openrouter_api_key` vs `moonshot_api_key`) is a Secrets
    schema concern. Centralizing the mapping means adding a third
    provider only touches this file (plus the Literal + bootstrap)."""
    s = load_secrets()
    if provider_name == "openrouter":
        return (s.openrouter_api_key, s.openrouter_model)
    if provider_name == "moonshot":
        return (s.moonshot_api_key, s.moonshot_model)
    return ("", "")
