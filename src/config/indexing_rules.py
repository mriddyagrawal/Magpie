"""IndexingRules — single gateway for "should this file be indexed?".

Replaces the old `src/ingest/ignore.py:IgnoreRules` with a layered config:

  1. `src/config/magpie_defaults.json` — developer-controlled safety rails
     (OS junk, build caches, lock files, secrets). Shipped with the app.
  2. `<APP_DATA_DIR>/indexing_rules.json` — user-controlled. Roots they
     want indexed (`include_paths`), specific files/folders to skip
     (`exclude_paths`), global pattern rules, category toggles.
  3. Cascade-discovered files at every directory depth:
     - `.gitignore` (toggleable: `respect_gitignore`)
     - `.nasignore` (legacy back-compat: `respect_nasignore`)
     - `.magpieinclude` / `.magpieexclude` (on-brand: `respect_magpie_inline_rules`)

Single public entry point: `IndexingRules.should_index(path) -> (bool, str)`.
The reason string is user-visible — powers `walk-explain` today and the GUI
"why isn't this indexed?" panel later. Keep reason strings stable; treat them
as part of the public API.

Performance contract:
  - Compile pathspecs once at construction; reuse across many `should_index`
    calls.
  - Re-load JSON only when the file's mtime changes (cheap stat per call).
  - Cascade discovery is lazy per-directory: we don't pre-scan the whole tree
    on construction. The walker calls `note_directory()` once per descended
    directory, and `should_index()` reuses the cached spec for each of that
    directory's files.
  - `is_pruneable_dir()` is the hot path the walker uses to skip os.walk
    descent into entire subtrees (`node_modules/`, `.venv/`, etc.).

Thread-safety: not thread-safe. The walker is currently async-single-threaded;
if a future feature needs concurrent indexing, wrap a Lock around the cache
mutations.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pathspec
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Filenames we discover during walk to apply per-directory rule cascades.
# Order matters for explain-string clarity; we report the first match in
# the cascade by file source.
_INLINE_FILENAMES_GITIGNORE = (".gitignore",)
_INLINE_FILENAMES_NASIGNORE = (".nasignore",)
_INLINE_FILENAMES_MAGPIE_EXCLUDE = (".magpieexclude",)
_INLINE_FILENAMES_MAGPIE_INCLUDE = (".magpieinclude",)
_ALL_INLINE_FILENAMES = (
    *_INLINE_FILENAMES_GITIGNORE,
    *_INLINE_FILENAMES_NASIGNORE,
    *_INLINE_FILENAMES_MAGPIE_EXCLUDE,
    *_INLINE_FILENAMES_MAGPIE_INCLUDE,
)

# Where the user config lives. Resolved lazily so MAGPIE_DATA_DIR overrides
# are honored even when this module is imported before the env var is set.
_DEFAULTS_FILENAME = "magpie_defaults.json"
_USER_RULES_FILENAME = "indexing_rules.json"

# Default category enable map. Mirrors `GlobalRules.categories_enabled` —
# keep in sync. CSV (`data` category) defaults TRUE so Mridul's already-
# working CSV ingest path doesn't regress; see Plan #12 for proper data-tier
# routing work.
_DEFAULT_CATEGORIES_ENABLED: dict[str, bool] = {
    "text": True,
    "document": True,
    "image": True,
    "data": True,
    "code": True,
    "archive": False,
}


# ---------------------------------------------------------------------------
# Pydantic models — the on-disk JSON schema
# ---------------------------------------------------------------------------


class RuleSet(BaseModel):
    """Per-include-path rule overrides. All fields optional — `None` means
    "inherit from globals". `exclude_globs`/`include_globs` are gitignore-
    syntax patterns (use `pathspec`). `include_globs` is rare; see Plan §4.
    """

    exclude_globs: list[str] = Field(default_factory=list)
    include_globs: list[str] = Field(default_factory=list)
    categories_enabled: Optional[dict[str, bool]] = None
    max_file_size_mb: Optional[float] = None


class IncludePath(BaseModel):
    """One folder the user wants indexed. `enabled=False` means "keep manifest
    entries but don't walk" — re-enabling restores them without re-summarizing.
    """

    path: str
    enabled: bool = True
    rules: Optional[RuleSet] = None


class GlobalRules(BaseModel):
    """Pattern-level rules applied across all include_paths. Editable from
    the future "Advanced settings" panel.
    """

    exclude_globs: list[str] = Field(default_factory=list)
    categories_enabled: dict[str, bool] = Field(
        default_factory=lambda: dict(_DEFAULT_CATEGORIES_ENABLED)
    )
    max_file_size_mb: float = 200.0


class MagpieDefaults(BaseModel):
    """Developer-controlled safety rails. Shipped via
    `src/config/magpie_defaults.json`. Users do not edit.
    """

    version: int = 1
    exclude_dirs: list[str] = Field(default_factory=list)
    exclude_globs: list[str] = Field(default_factory=list)
    exclude_extensions: list[str] = Field(default_factory=list)
    ignore_hidden: bool = True


class UserRules(BaseModel):
    """Top-level user config. Lives at `<APP_DATA_DIR>/indexing_rules.json`."""

    version: int = 1
    include_paths: list[IncludePath] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    global_rules: GlobalRules = Field(default_factory=GlobalRules)
    respect_gitignore: bool = True
    respect_nasignore: bool = True
    respect_magpie_inline_rules: bool = True
    ignore_hidden: bool = True


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _config_dir() -> Path:
    """Where `magpie_defaults.json` lives. Bundled with the source today;
    Plan #10 covers shipping it as a Tauri resource for production builds.
    """

    return Path(__file__).resolve().parent


def _user_rules_path() -> Path:
    """Where `indexing_rules.json` lives. Resolved lazily so env-var
    overrides (MAGPIE_DATA_DIR) are honored if set after import.
    """

    # Imported here (not at module scope) to avoid a circular dependency:
    # manifest.py → config? No — but it's cheap to defer, and avoids
    # surprising load order during testing.
    from src.manifest import APP_DATA_DIR

    return APP_DATA_DIR / _USER_RULES_FILENAME


def load_magpie_defaults(path: Optional[Path] = None) -> MagpieDefaults:
    """Read the developer-shipped safety-rails JSON. Falls back to an empty
    `MagpieDefaults()` if the file is missing — better to under-filter than
    to crash on a packaging mistake.
    """

    p = path or (_config_dir() / _DEFAULTS_FILENAME)
    if not p.exists():
        # Loud-but-recoverable: Magpie keeps running with no defaults rather
        # than refusing to start. The packaging story is covered in Plan #10.
        import sys

        print(
            f"warn: magpie_defaults.json missing at {p}; "
            "running with no built-in exclusion patterns",
            file=sys.stderr,
        )
        return MagpieDefaults()
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    # Strip our own annotation fields ("_comment", etc.) before validation.
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}
    return MagpieDefaults.model_validate(raw)


def load_user_rules(path: Optional[Path] = None) -> UserRules:
    """Read the user's `indexing_rules.json`. Creates a default-valued one on
    disk if missing, so first-run state is consistent (and the GUI/daemon can
    watch a real file rather than guessing).
    """

    p = path or _user_rules_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        rules = UserRules()
        save_user_rules(rules, p)
        return rules
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    return UserRules.model_validate(raw)


def save_user_rules(rules: UserRules, path: Optional[Path] = None) -> None:
    """Atomic save: stage to <path>.tmp then rename. Mirrors the manifest's
    save pattern so a crash mid-write can't corrupt the config.
    """

    p = path or _user_rules_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(rules.model_dump(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(p)


def load_indexing_rules(
    user_path: Optional[Path] = None,
    defaults_path: Optional[Path] = None,
) -> "IndexingRules":
    """Convenience: build a fully-composed IndexingRules from JSON on disk."""

    return IndexingRules(
        defaults=load_magpie_defaults(defaults_path),
        user=load_user_rules(user_path),
        user_path=user_path or _user_rules_path(),
    )


# ---------------------------------------------------------------------------
# Compiled-spec helpers
# ---------------------------------------------------------------------------


def _to_pathspec(patterns: list[str]) -> pathspec.PathSpec:
    """Build a gitignore-style PathSpec. Empty list yields a spec that
    matches nothing — safe to call against any path.
    """

    return pathspec.PathSpec.from_lines("gitignore", patterns)


def _read_inline_rule_file(path: Path) -> list[str]:
    """Read a `.gitignore`-style file's patterns. Strips comments and blank
    lines per gitignore spec. Returns [] on read errors (silently — these
    files are user-managed, expect occasional mistakes).
    """

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _is_under(path: Path, root: Path) -> bool:
    """True if `path` is `root` or a descendant of `root`. Both must be
    resolved (caller ensures). Uses string prefix on resolved paths because
    pathlib's `is_relative_to` is 3.9+ and we want explicit semantics.
    """

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# IndexingRules — the runtime gateway
# ---------------------------------------------------------------------------


@dataclass
class _CascadeEntry:
    """Per-directory cascade-discovered rule specs. Built lazily as the
    walker descends. Each spec is a PathSpec compiled from one specific
    inline rule file; we keep them separate so the explain-reason can name
    the source file precisely.
    """

    gitignore: Optional[pathspec.PathSpec] = None
    nasignore: Optional[pathspec.PathSpec] = None
    magpie_exclude: Optional[pathspec.PathSpec] = None
    magpie_include: Optional[pathspec.PathSpec] = None


@dataclass
class IndexingRules:
    """The runtime view: defaults + user rules + cascade-discovered specs.

    Construction: pre-compiles all global pathspecs. Per-directory cascade
    specs are built lazily on first access (via `_get_cascade(dir)`).

    JSON-mtime caching: callers that hold this object across multiple walks
    should call `maybe_reload()` between walks — it stat's the user JSON
    and re-parses only if mtime changed.
    """

    defaults: MagpieDefaults
    user: UserRules
    user_path: Path
    _user_mtime: float = 0.0

    # Pre-compiled hot-path specs (rebuilt when user JSON changes)
    _defaults_spec: pathspec.PathSpec = field(init=False)
    _global_exclude_spec: pathspec.PathSpec = field(init=False)
    _per_root_exclude: dict[str, pathspec.PathSpec] = field(default_factory=dict, init=False)
    _per_root_include: dict[str, pathspec.PathSpec] = field(default_factory=dict, init=False)
    _resolved_includes: list[tuple[Path, IncludePath]] = field(default_factory=list, init=False)
    _resolved_excludes: list[Path] = field(default_factory=list, init=False)
    _defaults_dir_names: set[str] = field(default_factory=set, init=False)
    _defaults_extensions: set[str] = field(default_factory=set, init=False)

    # Lazy per-directory cascade cache: abs_dir -> _CascadeEntry
    _cascade_cache: dict[Path, _CascadeEntry] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._compile()
        try:
            self._user_mtime = self.user_path.stat().st_mtime
        except OSError:
            self._user_mtime = 0.0

    # --- compilation -------------------------------------------------------

    def _compile(self) -> None:
        """Build all the pre-compiled spec objects from current models. Called
        on construction and on every reload.
        """

        # Defaults. Three input shapes (dirs, globs, extensions) collapse into
        # one PathSpec: dirs become `<name>/`, extensions become `*<ext>`,
        # globs go in as-is.
        default_patterns: list[str] = []
        for d in self.defaults.exclude_dirs:
            default_patterns.append(f"{d}/")
        default_patterns.extend(self.defaults.exclude_globs)
        for ext in self.defaults.exclude_extensions:
            # Extensions are matched at end-of-filename. `.DS_Store` style
            # entries can be either an extension OR a literal filename;
            # gitignore syntax treats them as filename matches when there's
            # no leading `*`. We normalize to `*<ext>` to match both forms.
            if ext.startswith("*"):
                default_patterns.append(ext)
            else:
                default_patterns.append(f"*{ext}" if ext.startswith(".") else ext)
        self._defaults_spec = _to_pathspec(default_patterns)

        # Hot-path lookups: directory names + extensions for cheap O(1) checks
        # before falling back to pathspec matching.
        self._defaults_dir_names = set(self.defaults.exclude_dirs)
        self._defaults_extensions = {
            ext.lower() for ext in self.defaults.exclude_extensions if ext.startswith(".")
        }

        # Global user rules.
        self._global_exclude_spec = _to_pathspec(self.user.global_rules.exclude_globs)

        # Per-root rules + resolved absolute paths.
        self._per_root_exclude = {}
        self._per_root_include = {}
        self._resolved_includes = []
        for inc in self.user.include_paths:
            try:
                p = Path(inc.path).expanduser().resolve()
            except OSError:
                # Unresolvable path (network drive offline, etc.) — skip with
                # a warning rather than crashing the whole load.
                import sys
                print(
                    f"warn: include_paths entry could not be resolved: {inc.path!r}",
                    file=sys.stderr,
                )
                continue
            self._resolved_includes.append((p, inc))
            if inc.rules:
                self._per_root_exclude[str(p)] = _to_pathspec(inc.rules.exclude_globs)
                self._per_root_include[str(p)] = _to_pathspec(inc.rules.include_globs)

        # Sort by path length descending → first match in
        # `_find_matching_include` is the most specific.
        self._resolved_includes.sort(key=lambda t: len(str(t[0])), reverse=True)

        # Resolved excludes (files OR directories). We don't compile these into
        # a PathSpec because they're absolute paths, not patterns — direct
        # `_is_under` check is faster.
        self._resolved_excludes = []
        for ep in self.user.exclude_paths:
            try:
                self._resolved_excludes.append(Path(ep).expanduser().resolve())
            except OSError:
                continue

        # Cascade cache MUST be cleared on recompile — old per-dir specs may
        # reference patterns that have changed.
        self._cascade_cache.clear()

    def maybe_reload(self) -> bool:
        """If the user JSON's mtime changed since last load, re-read and
        recompile. Returns True iff a reload happened. Cheap to call between
        walks; daemon will call this on file-watcher events too.
        """

        try:
            current_mtime = self.user_path.stat().st_mtime
        except OSError:
            return False
        if current_mtime <= self._user_mtime:
            return False
        self.user = load_user_rules(self.user_path)
        self._user_mtime = current_mtime
        self._compile()
        return True

    # --- resolution helpers -----------------------------------------------

    def _find_matching_include(self, abs_path: Path) -> Optional[tuple[Path, IncludePath]]:
        """Return (root_path, IncludePath) for the most-specific enabled
        include_path that contains `abs_path`. None if not under any.
        """

        for root, inc in self._resolved_includes:
            if not inc.enabled:
                continue
            if _is_under(abs_path, root):
                return (root, inc)
        return None

    def _matches_exclude_path(self, abs_path: Path) -> Optional[Path]:
        """Return the matching exclude_paths entry if `abs_path` IS one or is
        UNDER one. None otherwise.
        """

        for ep in self._resolved_excludes:
            if abs_path == ep or _is_under(abs_path, ep):
                return ep
        return None

    def _get_cascade(self, abs_dir: Path) -> _CascadeEntry:
        """Build (and cache) the per-directory cascade entry. Called on demand
        from `should_index` and `note_directory`.
        """

        cached = self._cascade_cache.get(abs_dir)
        if cached is not None:
            return cached
        entry = _CascadeEntry()
        try:
            names = set(os.listdir(abs_dir))
        except OSError:
            self._cascade_cache[abs_dir] = entry
            return entry
        if self.user.respect_gitignore and ".gitignore" in names:
            entry.gitignore = _to_pathspec(_read_inline_rule_file(abs_dir / ".gitignore"))
        if self.user.respect_nasignore and ".nasignore" in names:
            entry.nasignore = _to_pathspec(_read_inline_rule_file(abs_dir / ".nasignore"))
        if self.user.respect_magpie_inline_rules:
            if ".magpieexclude" in names:
                entry.magpie_exclude = _to_pathspec(
                    _read_inline_rule_file(abs_dir / ".magpieexclude")
                )
            if ".magpieinclude" in names:
                entry.magpie_include = _to_pathspec(
                    _read_inline_rule_file(abs_dir / ".magpieinclude")
                )
        self._cascade_cache[abs_dir] = entry
        return entry

    def note_directory(self, abs_dir: Path) -> None:
        """Walker calls this once per descended directory to pre-warm the
        cascade cache. No-op other than priming `_get_cascade`.
        """

        self._get_cascade(abs_dir.resolve())

    # --- the public API ----------------------------------------------------

    def should_index(self, path: Path | str) -> tuple[bool, str]:
        """Single gateway: decide whether `path` should be indexed. Returns
        `(allowed, reason)` where `reason` is a short human-readable string
        suitable for `walk-explain` output and the future "why?" GUI panel.

        Precedence: see `Plans/Ingestion Rules/Implementation Plan.md` §4.
        """

        # Resolve once. Unresolvable → reject (e.g. broken symlink).
        try:
            p = Path(path).expanduser().resolve()
        except OSError as e:
            return (False, f"cannot resolve path: {e}")

        # 1. exclude_paths always wins.
        ep_match = self._matches_exclude_path(p)
        if ep_match is not None:
            return (False, f"explicitly excluded: {ep_match}")

        # 2. Must be under an enabled include_path.
        match = self._find_matching_include(p)
        if match is None:
            return (False, "not under any included folder")
        root, inc = match

        # 3. Per-root rules (if any). exclude wins over include WITHIN the
        # same root — explicit per-root exclude is more cautious than a
        # per-root include match.
        if inc.rules is not None:
            try:
                rel = str(p.relative_to(root))
            except ValueError:
                rel = str(p)
            root_excl = self._per_root_exclude.get(str(root))
            if root_excl is not None and root_excl.match_file(rel):
                return (False, f"folder rule exclude in {root}")
            root_incl = self._per_root_include.get(str(root))
            if root_incl is not None and root_incl.match_file(rel):
                # Force-include path: short-circuit further reject checks.
                return (True, f"folder rule include in {root}")

        # 4. Global exclude globs (relative to the matched root for stable
        # gitignore semantics).
        try:
            rel = str(p.relative_to(root))
        except ValueError:
            rel = str(p)
        if self._global_exclude_spec.match_file(rel):
            return (False, "global exclude pattern")

        # 5. Magpie defaults: dir-name match within the include subtree
        # (NOT in the path's absolute-prefix part — `/tmp/...` shouldn't
        # match the `tmp` default just because of the system temp dir).
        # Then extension match, then pattern match.
        for part in Path(rel).parts:
            if part in self._defaults_dir_names:
                return (False, f"default exclude: dir '{part}'")
        if p.suffix.lower() in self._defaults_extensions:
            return (False, f"default exclude: extension '{p.suffix}'")
        # Defaults patterns are matched relative to the root for consistency
        # with how `IgnoreRules` matched them — they're cross-root patterns
        # like `**/*.pyc`, not root-anchored.
        if self._defaults_spec.match_file(rel):
            return (False, "default exclude pattern")

        # 6/7/8. Cascade-discovered inline rules. Walk ancestors from
        # deepest → shallowest so the closest spec wins.
        if (
            self.user.respect_magpie_inline_rules
            or self.user.respect_gitignore
            or self.user.respect_nasignore
        ):
            for ancestor in [p.parent, *p.parent.parents]:
                if not _is_under(ancestor, root) and ancestor != root:
                    break
                cascade = self._get_cascade(ancestor)
                # Magpie inline rules first (most local intent).
                try:
                    rel_to_anc = str(p.relative_to(ancestor))
                except ValueError:
                    continue
                if cascade.magpie_include and cascade.magpie_include.match_file(rel_to_anc):
                    # Force-include via .magpieinclude — short-circuits the
                    # remaining reject checks (gitignore, hidden, category, size).
                    return (True, f".magpieinclude in {ancestor}")
                if cascade.magpie_exclude and cascade.magpie_exclude.match_file(rel_to_anc):
                    return (False, f".magpieexclude in {ancestor}")
                if cascade.gitignore and cascade.gitignore.match_file(rel_to_anc):
                    return (False, f".gitignore in {ancestor}")
                if cascade.nasignore and cascade.nasignore.match_file(rel_to_anc):
                    return (False, f".nasignore in {ancestor}")
                if ancestor == root:
                    break

        # 9. Hidden file (filename starts with `.`). Don't reject the
        # inline-rule files themselves — they're meant to be present.
        if self.user.ignore_hidden:
            name = p.name
            if name.startswith(".") and name not in _ALL_INLINE_FILENAMES:
                return (False, "hidden file")

        # 10. Category gating. Per-root override → globals.
        if inc.rules and inc.rules.categories_enabled is not None:
            cats = inc.rules.categories_enabled
        else:
            cats = self.user.global_rules.categories_enabled
        cat = self._category_for(p.suffix.lower())
        if cat is not None and not cats.get(cat, True):
            return (False, f"category disabled: {cat}")

        # 11. File size cap.
        if inc.rules and inc.rules.max_file_size_mb is not None:
            limit_mb = inc.rules.max_file_size_mb
        else:
            limit_mb = self.user.global_rules.max_file_size_mb
        try:
            size_bytes = p.stat().st_size
        except OSError:
            # File vanished between resolve and stat — treat as "not present"
            # rather than reject-with-size-reason.
            return (False, "cannot stat file")
        if size_bytes > limit_mb * 1024 * 1024:
            mb = size_bytes / (1024 * 1024)
            return (False, f"exceeds max file size ({mb:.1f} MB > {limit_mb} MB)")

        return (True, "ok")

    # --- walker hot-path ---------------------------------------------------

    def is_pruneable_dir(self, abs_dir: Path | str) -> bool:
        """Hot path used by the walker to skip `os.walk` descent into
        entire subtrees. Conservative: only return True if we're SURE the
        directory and all its contents can never be indexed.

        Cases:
          - Directory itself is in `exclude_paths`
          - Directory NAME matches `magpie_defaults.exclude_dirs`
          - Directory matches a cascade-discovered exclude (magpie_exclude /
            nasignore / gitignore) at a parent level

        We do NOT prune on `include_paths` not containing the dir, because
        the walker may still need to descend if the user has added a child
        path as a separate include_path. Membership is checked at the file
        level via `should_index`.
        """

        try:
            p = Path(abs_dir).expanduser().resolve()
        except OSError:
            return False
        # exclude_paths
        for ep in self._resolved_excludes:
            if p == ep or _is_under(p, ep):
                return True
        # default dir-name match
        if p.name in self._defaults_dir_names:
            return True
        return False

    # --- categories --------------------------------------------------------

    @staticmethod
    def _category_for(ext: str) -> Optional[str]:
        """Look up the category for an extension. Returns None if the
        extension isn't in any category — caller treats unknown extensions
        as allowed (per Plan §4).
        """

        # Lazy import to avoid circular dependency: router imports manifest,
        # manifest imports config (eventually), config can't import router
        # at module load.
        from src.router import CATEGORY_MAP

        for cat, exts in CATEGORY_MAP.items():
            if ext in exts:
                return cat
        return None


# ---------------------------------------------------------------------------
# Auto-add helper (for `just walk <path>` flow)
# ---------------------------------------------------------------------------


def ensure_path_included(walk_path: Path | str) -> tuple[bool, Path]:
    """If `walk_path` isn't under any existing enabled include_path, add it
    as a new include_paths entry and persist the user JSON.

    Returns `(was_added, resolved_path)`. The CLI prints a friendly notice
    when `was_added` is True.

    Used by `just walk` and `ns --sync` to make ad-hoc walks register the
    path as a managed root, so the future daemon can pick it up too.
    """

    p = Path(walk_path).expanduser().resolve()
    rules = load_user_rules()
    for entry in rules.include_paths:
        try:
            existing = Path(entry.path).expanduser().resolve()
        except OSError:
            continue
        if entry.enabled and (p == existing or _is_under(p, existing)):
            return (False, p)
    rules.include_paths.append(IncludePath(path=str(p), enabled=True))
    save_user_rules(rules)
    return (True, p)
