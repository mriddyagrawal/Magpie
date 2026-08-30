"""DEPRECATED — superseded by `src.config.indexing_rules.IndexingRules`.

This module used to own:
  - `IgnoreRules` class (cascading `.gitignore` + `.magpieignore` (legacy `.nasignore`) + built-ins)
  - `DEFAULT_IGNORE_PATTERNS` (the OS-junk / build-cache safety net)
  - `IGNORE_FILENAMES` constant

Everything moved to:
  - Cascade discovery: `src/config/indexing_rules.py:_get_cascade()` (also
    handles new `.magpieinclude` / `.magpieexclude` files)
  - Defaults: `src/config/magpie_defaults.json` (declaratively, instead of
    a Python tuple)
  - Public gateway: `IndexingRules.should_index(path) -> (bool, str)`

What's left in this module is a thin deprecation crutch:
  - `DEFAULT_IGNORE_PATTERNS` is preserved as a re-export so any external
    code that imported it (test fixtures, tools, plugins) keeps working.
    It is no longer the source of truth — that's the JSON.
  - Importing `IgnoreRules` raises `AttributeError` immediately so the
    failure surfaces at import time, not deep inside a walker.

See `Plans/Ingestion Rules/Implementation Plan.md` §6 for the migration
context and removal timeline (one release cycle, then deletion).
"""

from __future__ import annotations

import warnings


# Preserved for one release as a back-compat crutch. Identical to the
# patterns now expressed declaratively in `src/config/magpie_defaults.json`
# (split into `exclude_dirs` / `exclude_globs` / `exclude_extensions`).
# New code should NOT import this — read the JSON via
# `src.config.load_magpie_defaults()` instead.
DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    ".git/", ".hg/", ".svn/",
    "__pycache__/", "*.pyc", "*.pyo",
    ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", ".tox/",
    ".venv/", "venv/", "env/",
    "site-packages/", "*.egg-info/", "*.dist-info/",
    "node_modules/", ".next/", ".nuxt/",
    "target/", "bin/", "obj/",
    "build/", "dist/", "out/",
    ".idea/", ".vscode/", ".vs/",
    ".DS_Store", "Thumbs.db", "desktop.ini",
    "tmp/", ".cache/",
    "$RECYCLE.BIN/", "System Volume Information/",
    "WindowsApps/", "Program Files/", "Program Files (x86)/",
    "lost+found/",
    ".env", ".env.*",
    "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*",
    "Test Summaries/",
    ".ipynb_checkpoints/",
    "package-lock.json", "yarn.lock", "uv.lock", "Cargo.lock",
)


# Sentinel error that fires the moment any caller tries to import
# IgnoreRules. We don't silently shim because the API surface (from_root,
# is_ignored, is_default_ignored_dir) was non-trivial — silently routing
# old callers through IndexingRules would mask real integration bugs.
def __getattr__(name: str):
    if name == "IgnoreRules":
        raise AttributeError(
            "IgnoreRules has been removed. Use "
            "`from src.config import IndexingRules, load_indexing_rules` "
            "and call `rules.should_index(path)` / `rules.is_pruneable_dir(dir)`. "
            "See Plans/Ingestion Rules/Implementation Plan.md."
        )
    if name == "IGNORE_FILENAMES":
        warnings.warn(
            "IGNORE_FILENAMES has moved into IndexingRules cascade discovery. "
            "Use `src.config.indexing_rules._ALL_INLINE_FILENAMES` if you need "
            "the list (now includes .magpieinclude / .magpieexclude).",
            DeprecationWarning,
            stacklevel=2,
        )
        return (
            ".gitignore", ".magpieignore", ".nasignore",
            ".magpieexclude", ".magpieinclude",
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
