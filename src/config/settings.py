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

    `cloud_provider` and `cloud_model` live here (not in UserSettings)
    because in v1 the user is not allowed to edit them — they're a
    deployment-time choice baked into the bundle. The user only
    chooses Local-vs-Cloud via the `provider` field.
    """

    model_config = ConfigDict(extra="ignore")

    version: int = 1

    # Provider selection (binary user-facing choice)
    provider: str = "local"  # "local" | "cloud"

    # Cloud routing config — not user-editable in v1
    cloud_provider: str = "openrouter"
    cloud_model: str = "google/gemma-4-26b-a4b-it:free"

    # Search / retrieval knobs
    top_k: int = Field(default=5, ge=1, le=20)
    rewrite_default: bool = False
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # App appearance + behavior
    theme: str = "system"  # "system" | "light" | "dark"
    accent: str = "ink"  # "ink" | "amber" | "jade" | "rose"
    default_action: str = "empty"  # "empty" | "last"
    launch_at_login: bool = False
    show_in_tray: bool = True


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

    theme: Optional[str] = None
    accent: Optional[str] = None
    default_action: Optional[str] = None
    launch_at_login: Optional[bool] = None
    show_in_tray: Optional[bool] = None


class EffectiveSettings(BaseModel):
    """Merged view: env > user > defaults, every field populated.
    What the rest of the app reads when it needs to act on a setting.
    """

    provider: str
    cloud_provider: str
    cloud_model: str
    top_k: int
    rewrite_default: bool
    temperature: float
    theme: str
    accent: str
    default_action: str
    launch_at_login: bool
    show_in_tray: bool


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
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}
    return AppDefaults.model_validate(raw)


def load_user_settings(path: Optional[Path] = None) -> UserSettings:
    """Read the user's `settings.json`. Creates an empty default file
    on first call so the GUI can watch a real file."""
    p = path or _settings_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        s = UserSettings()
        save_user_settings(s, p)
        return s
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    return UserSettings.model_validate(raw)


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
    """Per-key env-var overrides. Opt-in: only the keys we explicitly
    care about route through env. Bulk-overriding everything via env
    makes settings.json behavior surprising."""
    out: dict[str, Any] = {}

    # LLM_PROVIDER → maps to the binary "local"/"cloud" choice. Any of
    # the cloud provider names (openrouter, moonshot, magpie-cloud) maps
    # to "cloud"; "local" maps to "local"; anything else is left alone
    # (active_provider() handles the dispatch).
    raw_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if raw_provider == "local":
        out["provider"] = "local"
    elif raw_provider in {"openrouter", "moonshot", "ollama", "magpie-cloud"}:
        out["provider"] = "cloud"

    return out


def effective_settings(
    *,
    user_path: Optional[Path] = None,
    defaults_path: Optional[Path] = None,
) -> EffectiveSettings:
    """Merged settings view. env > user > defaults. Resolved fresh
    per-call — settings reads are infrequent and we want the GUI's
    PATCH to take effect on the next request without reload."""
    defaults = load_app_defaults(defaults_path)
    user = load_user_settings(user_path)
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
