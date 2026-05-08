"""Secret storage: cloud API keys (and any other future secrets).

Lives at `<APP_DATA_DIR>/secrets.json` with mode 0600 so casual
filesystem access can't read it. Distinct from `settings.json`
because (a) different perms, (b) different access pattern (rare
read, never logged, never echoed to UI), (c) different bootstrap
story (env-seeded on first launch).

v1 stores only `cloud_api_key`. The user is NOT allowed to edit it
from the UI in v1 — Settings → Search & AI shows "Cloud" as a
binary opt-in, not a key-management surface. Bring-your-own keys is
a parked Plan #19 / "Advanced" sidebar concern.

Bootstrap on first load:
  1. Look for `<APP_DATA_DIR>/secrets.json`. If present, return.
  2. Call `load_dotenv()` (idempotent), read `OPENROUTER_API_KEY`.
  3. Fall back to `_bundled_key()` (from `src/config/bundled_key.txt`,
     only present in shipped builds; empty in dev checkouts).
  4. Always write the result, even if empty — a present-but-empty
     file means "we tried to bootstrap, no key was available";
     subsequent loads skip bootstrap and the user gets a friendly
     error if they pick Cloud.

After bootstrap, `.env` is dead to runtime — `secrets.json` is the
authoritative store. To re-bootstrap, delete `secrets.json`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

_USER_SECRETS_FILENAME = "secrets.json"
_BUNDLED_KEY_FILENAME = "bundled_key.txt"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class Secrets(BaseModel):
    """The on-disk secrets file. Pydantic `extra="ignore"` for
    forward-compat: a future Magpie release might add `moonshot_api_key`
    etc.; older code reading the same file should drop unknown keys."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1
    cloud_api_key: str = ""


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
    """Read `secrets.json`. If missing, run the bootstrap flow.
    Always returns a valid Secrets — never raises for missing files."""
    p = path or _secrets_path()
    if not p.exists():
        return _bootstrap_secrets(p)
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    return Secrets.model_validate(raw)


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
    """First-launch flow: pull `cloud_api_key` from `.env` (dev) or a
    bundled default (production). Always writes the result so subsequent
    loads short-circuit."""

    # `dotenv` is already a project dep; load_dotenv is idempotent.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        # Dotenv not installed — only happens in degenerate test envs.
        pass

    # Order: dev's existing OPENROUTER_API_KEY first, then any bundled
    # key shipped with the binary. Empty string is a valid result and
    # means "no Cloud available" — the UI surfaces this as Cloud being
    # un-configured.
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        key = _bundled_key().strip()

    s = Secrets(cloud_api_key=key)
    save_secrets(s, path)
    if not key:
        print(
            "[secrets] no cloud key found in .env or bundle; "
            "Cloud will be unavailable until configured",
            file=sys.stderr,
        )
    return s


def _bundled_key() -> str:
    """Read the build-time-baked cloud key from
    `src/config/bundled_key.txt` if present, empty otherwise.

    Production builds ship this file (Plan #10 packaging concern);
    dev checkouts don't have it (`.gitignore`'d). The file is ASCII —
    one line, the API key, no JSON wrapping — so a build script
    doesn't need a JSON parser."""
    p = _config_dir() / _BUNDLED_KEY_FILENAME
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
