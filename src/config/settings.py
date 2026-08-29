"""User-facing app settings: provider, top_k, theme, accent, etc.

Mirrors the load/save shape of `src/config/indexing_rules.py` — same
two-loader pattern (bundled defaults + APP_DATA_DIR user file with
atomic writes), so a future maintainer can read either file and find
the same primitives.

Storage layout:
  src/config/magpie_defaults.json    # bundled, immutable at runtime
  <APP_DATA_DIR>/settings.json       # user prefs, mutable from UI

Resolution precedence at read time:
  LLM_PROVIDER env var                  → wins absolutely
  settings.json (UserSettings)          → user's UI choice
  magpie_defaults.json (AppDefaults)    → product defaults
  hardcoded BaseModel defaults          → safety net

The `cloud_api_key` does NOT live here — it's a secret. See
`src/config/secrets.py` for that one. AppDefaults exposes
cloud_provider / cloud_model (non-secret routing config) and the
user-visible toggles only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

_DEFAULTS_FILENAME = "magpie_defaults.json"
_USER_SETTINGS_FILENAME = "settings.json"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AppDefaults(BaseModel):
    """Non-secret defaults shipped with the bundle. Read from the same
    `magpie_defaults.json` as MagpieDefaults; Pydantic's `extra="ignore"`
    lets the two models coexist in one file without conflict.

    Cloud routing (which cloud provider, per-provider models, API keys)
    does NOT live here — it lives in `secrets.json` next to the
    credentials. Settings carries only the user-facing "Local vs Cloud"
    binary; secrets carries the which-cloud + the keys."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1

    # Provider selection (binary user-facing choice). Default "cloud"
    # because (a) the bundled OpenRouter key works out of the box on
    # fresh installs, while Local requires a ~5 GB Gemma + ~900 MB
    # mmproj download on first use; (b) Cloud queries are faster
    # (~1-2s) than Local (~5-30s on consumer hardware). Users who
    # value privacy / offline flip to Local in Settings → Search & AI.
    provider: str = "cloud"  # "local" | "cloud"

    # Search / retrieval knobs
    top_k: int = Field(default=5, ge=1, le=20)
    rewrite_default: bool = True
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    # When True, the answer LLM emits inline [N] citation markers that
    # the frontend renders as numbered green pills linked to sources.
    # When False, the system prompt skips the marker instructions and
    # the model emits plain prose; sources still appear below but are
    # not anchored to specific claims. Default True (Perplexity-style).
    cite_sources_inline: bool = True
    # When True, queries that look like enumeration ("list all my X",
    # "what are every Y") get adaptive treatment: top_k widened,
    # cross-encoder rerank suppressed (it regresses list queries per
    # the rememex postmortem), and an ENUMERATION MODE prompt addition
    # tells the LLM to be exhaustive. When False, every query takes
    # the standard semantic-retrieval path with no list-shaped
    # adaptation. Default True.
    enumerate_lists: bool = True

    # App appearance + behavior
    theme: str = "system"  # "system" | "light" | "dark"
    accent: str = "ink"  # "ink" | "amber" | "jade" | "rose"
    launch_at_login: bool = False


class UserSettings(BaseModel):
    """The user's `settings.json`. All fields Optional — `None` means
    "fall through to AppDefaults." This avoids accidentally pinning a
    user to a stale value if we change a default in a future release."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1

    provider: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    rewrite_default: Optional[bool] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    cite_sources_inline: Optional[bool] = None
    enumerate_lists: Optional[bool] = None

    theme: Optional[str] = None
    accent: Optional[str] = None
    launch_at_login: Optional[bool] = None


class EffectiveSettings(BaseModel):
    """Merged view: env > user > defaults, every field populated.
    What the rest of the app reads when it needs to act on a setting.

    Cloud routing fields are NOT here — they're a Secrets concern.
    Callers that need to know which cloud provider runs should
    `load_secrets().cloud_provider` directly."""

    provider: str
    top_k: int
    rewrite_default: bool
    temperature: float
    cite_sources_inline: bool
    enumerate_lists: bool
    theme: str
    accent: str
    launch_at_login: bool


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _config_dir() -> Path:
    """Where `magpie_defaults.json` lives. Same as indexing_rules.py."""
    return Path(__file__).resolve().parent


def _settings_path() -> Path:
    """Where `settings.json` lives. Lazy so MAGPIE_DATA_DIR overrides
    are honored after import."""
    from src.manifest import APP_DATA_DIR

    return APP_DATA_DIR / _USER_SETTINGS_FILENAME


# ---------------------------------------------------------------------------
# Loaders / writers
# ---------------------------------------------------------------------------


def load_app_defaults(path: Optional[Path] = None) -> AppDefaults:
    """Read the bundled defaults. The same `magpie_defaults.json` is
    also read by `load_magpie_defaults()` — Pydantic ignores the keys
    each model doesn't recognize."""
    p = path or (_config_dir() / _DEFAULTS_FILENAME)
    if not p.exists():
        # Loud-but-recoverable: keep running with hardcoded BaseModel
        # defaults rather than refusing to start. Mirrors load_magpie_defaults.
        print(
            f"warn: magpie_defaults.json missing at {p}; "
            "running with hardcoded app defaults",
            file=sys.stderr,
        )
        return AppDefaults()
    # utf-8-sig: hand-edits from Notepad / PowerShell `Out-File` prepend a
    # BOM, and strict utf-8 turns that into a JSONDecodeError that 500s
    # every settings endpoint. Same hardening as secrets.py.
    with p.open(encoding="utf-8-sig") as f:
        raw = json.load(f)
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}
    return AppDefaults.model_validate(raw)


def load_user_settings(
    path: Optional[Path] = None,
    defaults_path: Optional[Path] = None,
) -> UserSettings:
    """Read the user's `settings.json`. Creates a defaults-populated
    file on first call so the user can see what the bundled defaults
    are without having to derive them from another file.

    The created file mirrors the values of `AppDefaults` exactly —
    every field gets a non-None value. Subsequent edits (via the
    Settings UI's PATCH endpoints) replace those values; setting a
    field back to None means "fall through to whatever AppDefaults
    says at read time", which is the original lazy semantics.

    `defaults_path`, when provided, is forwarded to `load_app_defaults`
    so the seed reflects the same defaults file the caller intends to
    use at merge time. (Tests inject a custom defaults file via this
    arg; production passes None and reads the bundled file.)"""
    p = path or _settings_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        # Seed the new file with the current bundled defaults so the
        # user can inspect/edit and immediately see meaningful values
        # rather than a wall of nulls.
        defaults = load_app_defaults(defaults_path)
        s = UserSettings(
            version=SETTINGS_VERSION,
            provider=defaults.provider,
            top_k=defaults.top_k,
            rewrite_default=defaults.rewrite_default,
            temperature=defaults.temperature,
            cite_sources_inline=defaults.cite_sources_inline,
            enumerate_lists=defaults.enumerate_lists,
            theme=defaults.theme,
            accent=defaults.accent,
            launch_at_login=defaults.launch_at_login,
        )
        save_user_settings(s, p)
        return s
    with p.open(encoding="utf-8-sig") as f:
        raw = json.load(f)
    raw = _migrate(raw, p)
    return UserSettings.model_validate(raw)


# The settings schema version. Bump it together with a `_migrate` branch.
SETTINGS_VERSION = 2


def _migrate(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    """Bring an on-disk settings.json up to `SETTINGS_VERSION`.

    v1 -> v2 (2026-08-27): unpin a temperature that was never chosen.
    `load_user_settings` seeds a fresh file with every default written out
    explicitly, so a stored 0.7 is indistinguishable from a deliberate
    0.7 — and that defeats the whole Optional-means-fall-through design
    the moment a default moves. The local answer path now wants Liquid's
    recommended 0.1 (see inference/profiles.DEFAULT_TEMPERATURE), so a
    seeded 0.7 is cleared back to None. A user who actually picked 0.7
    loses one non-default setting once; a user who never touched it stops
    being pinned to a value they never chose.
    """
    if raw.get("version", 1) >= SETTINGS_VERSION:
        return raw
    if raw.get("temperature") == 0.7:
        raw["temperature"] = None
    raw["version"] = SETTINGS_VERSION
    try:
        save_user_settings(UserSettings.model_validate(raw), path)
    except Exception:  # noqa: BLE001 — a read-only config dir must not break startup
        pass
    return raw


def save_user_settings(settings: UserSettings, path: Optional[Path] = None) -> None:
    """Atomic save: stage to `<path>.tmp` then rename. Mirrors
    save_user_rules in indexing_rules.py."""
    p = path or _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(settings.model_dump(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Effective merge
# ---------------------------------------------------------------------------


def _env_overrides() -> dict[str, Any]:
    """Per-key env-var overrides. Currently empty: `LLM_PROVIDER` was
    removed on 2026-05-08 because it silently overrode the user's
    Settings → Search & AI choice. Settings.json is now the sole
    source of truth for provider routing. See `active_provider()` in
    src/llm.py for the per-provider credential lookup, which still
    honors `OPENROUTER_API_KEY` etc. from env (those are credentials,
    not routing)."""
    return {}


def effective_settings(
    *,
    user_path: Optional[Path] = None,
    defaults_path: Optional[Path] = None,
) -> EffectiveSettings:
    """Merged settings view. env > user > defaults. Resolved fresh
    per-call — settings reads are infrequent and we want the GUI's
    PATCH to take effect on the next request without reload."""
    defaults = load_app_defaults(defaults_path)
    user = load_user_settings(user_path, defaults_path)
    env = _env_overrides()

    # Start from the defaults, overlay non-None user fields, overlay env.
    merged = defaults.model_dump()
    for key, value in user.model_dump().items():
        if value is not None and key in merged:
            merged[key] = value
    merged.update(env)
    return EffectiveSettings.model_validate(merged)


def patch_user_settings(
    *,
    user_path: Optional[Path] = None,
    **kwargs: Any,
) -> UserSettings:
    """Load → set non-None kwargs → save. Used by `PATCH /settings/*`
    handlers. Unknown kwargs are silently dropped via `extra="ignore"`."""
    s = load_user_settings(user_path)
    data = s.model_dump()
    for key, value in kwargs.items():
        if key in data:
            data[key] = value
    new = UserSettings.model_validate(data)
    save_user_settings(new, user_path)
    return new
