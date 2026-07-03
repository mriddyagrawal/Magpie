# Ingestion Rules — Implementation Plan

> **Status:** Locked design as of 2026-05-03. Working branch: `ingestion-rules`.
> Replaces `src/ingest/ignore.py` + `.gitignore` + `.nasignore` as scattered ignore mechanisms with a single, UI-driven, JSON-backed config system.
> Original spec: [Promts/build_ingestion_rules.md](../../Promts/build_ingestion_rules.md). This doc supersedes the spec where they conflict — see the [Design Deviations](#design-deviations-from-original-spec) section.

---

## 1. Goal & Non-Goals

### Goal
The user picks folders/files in a finder dialog. Magpie indexes what they picked, skips what they didn't. Config lives in one place. Same gateway (`should_index()`) governs every code path that decides whether a file gets indexed.

### Success criteria (concrete, testable)
1. Mridul (or any new user) installs Magpie, opens it, picks `~/Documents`. After ingestion completes, search returns hits from documents in that folder. No CLI ceremony.
2. The same user picks `~/Documents/secret.pdf` as an exclude. Search never returns that file.
3. Power user drops a `.magpieexclude` file in `~/Projects/foo/` containing `*.tmp`. Future walks skip `.tmp` files in that subtree without editing the JSON.
4. Existing user (Astavak) on Linux: existing 1721-entry manifest keeps working. `just walk-rebuild <path>` still works as a power-user escape hatch.
5. `just walk-explain <path>` prints `(skip|index, reason)` for every file. The reason strings are the same ones the future GUI shows.

### Non-goals (in this work)
- GUI implementation. We expose the API endpoints; Tauri team builds the UI.
- Auto-promotion of nested rules into sub-roots — see [Future Plan #15](../Future%20Plans.md).
- Native Rust file watcher — `watchdog` (Python) for now. See [Future Plan #4](../Future%20Plans.md).
- Self-contained packaging of `magpie_defaults.json` — see [Future Plan #10](../Future%20Plans.md).
- Replacing the count-based orphan-cleanup with point-IDs-in-manifest — see [Future Plan #11](../Future%20Plans.md).

---

## 2. Architecture

### High-level shape (3 PRs)

```
┌──────────────────────────────────────────────────────────────────┐
│                    PR1 — Config + Filter Chain                    │
│  src/config/                                                     │
│    ├─ magpie_defaults.json   (developer safety rails, shipped)   │
│    └─ indexing_rules.py      (Pydantic models, should_index,     │
│                               JSON load/save with mtime cache)   │
│  src/router.py               + CATEGORY_MAP                      │
│  src/ingest/walker.py        uses IndexingRules.should_index()   │
│  src/ingest/ignore.py        thin shim (cascade discovery only)  │
│  src/manifest.py             optional mtime + dev toggle         │
│  justfile                    sync → sync-environment, new sync   │
│  tests/                      precedence + load/save              │
│                                                                   │
│  END STATE: just walk <path>, ns --sync still work. JSON drives  │
│  filtering. .magpieinclude/.magpieexclude respected. No watcher. │
└──────────────────────────────────────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                  PR2 — Daemon + Watcher + Queues                  │
│  src/daemon/  + watchdog observer on enabled include_paths       │
│               + fast queue (cleanup) + slow queue (ingest)       │
│               + JSONL queue persistence                          │
│               + startup reconciliation                           │
│               + idle MODELS unload (process stays alive)         │
│  src/server.py + sidecar absorbs daemon (single process) OR      │
│                  daemon stays separate w/ HTTP IPC               │
│                  (decision deferred to start of PR2)             │
│                                                                   │
│  END STATE: edit indexing_rules.json → daemon reacts. New file   │
│  in watched folder → indexed within minutes. No manual walks.    │
└──────────────────────────────────────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                   PR3 — API + GUI Wiring                          │
│  src/server.py     /settings/indexing-rules    (GET, PUT)        │
│                    /settings/categories         (GET, PUT)       │
│                    /actions/reindex-all         (POST)           │
│                    /events/file-changed         (POST, future)   │
│                    /diagnostics/why-not?path=…  (GET, GUI hook)  │
│  Tauri bindings    invoke wrappers for the above                 │
│                                                                   │
│  END STATE: Tauri can read + edit rules. "Include folder" /      │
│  "Exclude file" buttons work. "Why isn't this indexed?" tells    │
│  the user the should_index reason.                               │
└──────────────────────────────────────────────────────────────────┘
```

Each PR ships independently. Each PR leaves the system in a usable state. **No PR depends on another to function — you can stop after PR1 and Mridul still has working CLI ingestion with cleaner config.**

---

## 3. Data Model — Final JSON Schema

### `magpie_defaults.json`
**Location:** `src/config/magpie_defaults.json` (in repo) → bundled as Tauri resource later (see [Future Plan #10](../Future%20Plans.md)).
**Edited by:** Magpie devs. Shipped with releases.

```json
{
  "version": 1,
  "exclude_dirs":       ["node_modules", "__pycache__", ".git", "..."],
  "exclude_globs":      ["**/Library/Caches/**", "*.pyc", "..."],
  "exclude_extensions": [".DS_Store", ".thumbs.db"],
  "ignore_hidden": true
}
```

Migrated from the ~250 patterns in `src/ingest/ignore.py:DEFAULT_IGNORE_PATTERNS`. **Nothing else** lives here — no user state, no roots.

### `indexing_rules.json`
**Location:** `<APP_DATA_DIR>/indexing_rules.json` (resolved via `src.manifest.APP_DATA_DIR`).
**Edited by:** User (manually or via future GUI). Daemon watches the file (PR2).

```json
{
  "version": 1,

  "include_paths": [
    {
      "path": "/Users/x/Documents",
      "enabled": true
    },
    {
      "path": "/Users/x/Projects/magpie",
      "enabled": true,
      "rules": {
        "exclude_globs": ["target/**"],
        "categories_enabled": { "code": false }
      }
    }
  ],

  "exclude_paths": [
    "/Users/x/Documents/secret-tax-return.pdf",
    "/Users/x/Projects/magpie/.env",
    "/Users/x/Projects/magpie/node_modules"
  ],

  "global_rules": {
    "exclude_globs": ["**/*.tmp"],
    "categories_enabled": {
      "text": true, "document": true, "image": true,
      "data": true, "code": true, "archive": false
    },
    "max_file_size_mb": 200
  },

  "respect_gitignore": true,
  "respect_nasignore": true,
  "respect_magpie_inline_rules": true,
  "ignore_hidden": true
}
```

#### Field semantics

| Field | Type | Meaning |
|---|---|---|
| `include_paths[].path` | absolute path | A directory to walk OR a single file to index. **File entries are explicit user picks and override every other rule** (exclude_paths, gitignore, hidden, category-disabled, size cap) — see [§4 row 0](#precedence-top-wins). Directory entries flow through the normal precedence chain. |
| `include_paths[].enabled` | bool | Disabled = not walked, but manifest entries kept (re-enabling restores them without re-summarizing). |
| `include_paths[].rules` | optional `RuleSet` | Per-folder overrides. **Most users won't touch this** — it's the advanced panel. |
| `exclude_paths` | list of absolute paths | Files OR directories the user clicked "exclude" on. Always wins over includes. |
| `global_rules` | `RuleSet` (no per-path) | Patterns the user wants applied everywhere. Editable from "Advanced settings" panel. |
| `respect_gitignore` | bool, default true | Honor `.gitignore` files at every depth. |
| `respect_nasignore` | bool, default true | Honor `.nasignore` files at every depth (legacy name, kept for back-compat). |
| `respect_magpie_inline_rules` | bool, default true | Honor `.magpieinclude` / `.magpieexclude` files at every depth (new — see [§5](#5-inline-rule-files-magpieinclude--magpieexclude)). |
| `ignore_hidden` | bool, default true | Skip hidden files (`.foo`). |

#### Pydantic models

```python
class RuleSet(BaseModel):
    exclude_globs: list[str] = []
    include_globs: list[str] = []        # rare; per-root force-include
    categories_enabled: dict[str, bool] | None = None  # None = inherit globals
    max_file_size_mb: float | None = None              # None = inherit globals

class IncludePath(BaseModel):
    path: str
    enabled: bool = True
    rules: RuleSet | None = None         # None = no overrides

class GlobalRules(BaseModel):
    exclude_globs: list[str] = []
    categories_enabled: dict[str, bool] = { "text": True, "document": True,
                                             "image": True, "data": True,
                                             "code": True, "archive": False }
    max_file_size_mb: float = 200.0

class MagpieDefaults(BaseModel):
    version: int = 1
    exclude_dirs: list[str] = []
    exclude_globs: list[str] = []
    exclude_extensions: list[str] = []
    ignore_hidden: bool = True

class UserRules(BaseModel):
    version: int = 1
    include_paths: list[IncludePath] = []
    exclude_paths: list[str] = []
    global_rules: GlobalRules = Field(default_factory=GlobalRules)
    respect_gitignore: bool = True
    respect_nasignore: bool = True
    respect_magpie_inline_rules: bool = True
    ignore_hidden: bool = True

class IndexingRules:
    """Composed view: defaults + user_rules + cascade discovery + category map.
    Holds compiled pathspecs in memory. Reloads when JSON mtime changes."""
    defaults: MagpieDefaults
    user: UserRules
    cascade: dict[Path, pathspec.PathSpec]   # discovered .gitignore/.nasignore/.magpie* per dir
    category_map: dict[str, set[str]]        # imported from src.router.CATEGORY_MAP
```

---

## 4. Filter Chain — `should_index(path)`

Returns `tuple[bool, str]`. The reason string powers `walk-explain` and the future GUI's "why?" panel.

### Precedence (top wins)

| # | Check | Reason string |
|---|---|---|
| **0** | **Path is itself an enabled `include_paths` entry that resolves to a FILE (not a directory).** Short-circuits every check below — the user's most specific pick beats everything. | **`"explicitly included file: <path>"`** (accept) |
| 1 | Path matches an entry in `exclude_paths` (the path itself OR an ancestor) | `"explicitly excluded: <which path>"` |
| 2 | Path is not under any **enabled** `include_paths` | `"not under any included folder"` |
| 3 | Find the **most specific (longest matching prefix) enabled** include_path. Apply its `rules` (if set): exclude_globs match → reject; include_globs match → accept | `"folder rule exclude: <pattern>"` / `"folder rule include: <pattern>"` |
| 4 | `global_rules.exclude_globs` matches | `"global exclude: <pattern>"` |
| 5 | `magpie_defaults.exclude_dirs` matches any path component, OR `exclude_globs` matches, OR `exclude_extensions` matches the suffix | `"default exclude: <pattern>"` |
| 6 | `respect_magpie_inline_rules` AND a `.magpieinclude`/`.magpieexclude` in any ancestor matches (deepest wins) | `"magpie include/exclude: <pattern> in <dir>"` |
| 7 | `respect_gitignore` AND a `.gitignore` in any ancestor matches | `"gitignore: <pattern> in <dir>"` |
| 8 | `respect_nasignore` AND a `.nasignore` in any ancestor matches | `"nasignore: <pattern> in <dir>"` |
| 9 | `ignore_hidden` AND filename starts with `.` (and isn't an inline-rule file itself) | `"hidden file"` |
| 10 | File extension belongs to a category in `categories_enabled` that's `false`. Resolve `categories_enabled` per-root override → globals. **Unknown extensions: allowed.** | `"category disabled: <category>"` |
| 11 | File size > `max_file_size_mb` (per-root override → globals) | `"exceeds max file size"` |
| 12 | All checks passed | `"ok"` |

#### Why row 0 exists

A user who has gone to the trouble of explicitly listing one specific file as an include_paths entry has made the strongest possible statement of intent: "index THIS file." The rule machinery should respect that intent above every default safety rail. Concrete cases that motivated the rule:

- A user disables the `data` category globally (CSV noise) but wants ONE specific CSV indexed → drop it in `include_paths`, done.
- A `.env.example` documentation file is hidden (starts with `.`) but the user wants it searchable → explicit file include bypasses `ignore_hidden`.
- A particular tax PDF is huge (over `max_file_size_mb`) but is critical to find → explicit file include bypasses the size cap.
- A user accidentally has the same path in both `include_paths` and `exclude_paths` (UI-edit race, hand-edited JSON) → most-specific-wins says the include side wins, so the user's most recent positive action takes precedence.

Directory-typed `include_paths` entries do NOT trigger row 0 — they flow through the normal chain so files inside an included directory still respect `exclude_paths`, gitignore, etc. Only file-typed entries bypass everything.

The behavior is implemented in [`IndexingRules._find_explicit_file_include`](../../src/config/indexing_rules.py) and tested at [tests/test_indexing_rules_should_index.py](../../tests/test_indexing_rules_should_index.py) under "Precedence row 0".

### Why this order

- **Excludes always win.** `exclude_paths` is checked first because it's the user's most explicit "no" — they clicked the exclude button on this exact thing.
- **Most-specific include rules win.** If `/Users/x` and `/Users/x/Docs` are both included, files under `/Users/x/Docs` use ITS rules, not `/Users/x`'s. (Per your decision: "deepest folder's preferences should have precedence.")
- **Defaults are the safety net.** They fire AFTER user rules, so a user's per-folder include can override a default exclude.
- **Inline rules (.magpie*, .gitignore, .nasignore) are last among reject conditions** because they're cascade-discovered at walk time and represent the most local user intent.
- **Category and size are pattern-level checks** that apply to anything that survived the path-based filtering.

### Performance: the dir-prune fast path

`should_index()` is the per-file check. For walk efficiency, expose `IndexingRules.is_pruneable_dir(abs_dir)` that returns True if a directory matches:
- An `exclude_paths` entry that's a directory
- A `magpie_defaults.exclude_dirs` name match
- A cascade-discovered exclude

The walker calls this on each subdirectory and skips `os.walk` descent. Critical for not descending into `node_modules/` (50k files per package).

---

## 5. Inline Rule Files: `.magpieinclude` / `.magpieexclude`

Per your direction. These are the MVP path-picker UX equivalent for "I'm in this folder, set rules for here."

### Behavior

- Same syntax as `.gitignore` (gitignore-syntax patterns, one per line, `#` comments, `!` negation).
- Discovered during walk traversal at every directory level (same as `.gitignore`/`.nasignore`).
- Merged with the JSON-config rules at walk time. **Not promoted into the JSON.** They live where the user put them (the file is the source of truth for that subtree).
- `.magpieexclude` ≈ `.nasignore` in semantics (kept both names: `.nasignore` for back-compat, `.magpieexclude` for on-brand).
- `.magpieinclude` is new — patterns matching here override default+global excludes (but NOT user `exclude_paths`, which always wins).
- Toggleable via `respect_magpie_inline_rules: true/false` in the JSON.

### Why files-on-disk and not "promoted into JSON"

- **Local intent stays local.** A user who drops `.magpieexclude` in a project folder shouldn't have their global config bloat with that project's specific patterns.
- **Survives moving the project around** — the file travels with the folder.
- **Mirrors the well-known `.gitignore` mental model.** Power users grok this immediately.
- **No round-trip rewriting** — user writes a file, system reads it. No surprise edits.
- The future "Include inside folder" / "Exclude inside folder" UI buttons (per your direction) write to the appropriate `.magpieinclude` / `.magpieexclude` in that folder, not back to the JSON.

### Discovery (reuses existing logic)

The current `src/ingest/ignore.py:IgnoreRules.from_root()` already does cascade discovery for `.gitignore`/`.nasignore`. We extend its `IGNORE_FILENAMES` tuple to include `.magpieinclude`/`.magpieexclude`, then surface the merged spec via `IndexingRules`. Detail in PR1 work.

---

## 6. PR Breakdown

### PR1 — Config + Filter Chain (current branch: `ingestion-rules`)

**Files created**
- `src/config/__init__.py`
- `src/config/magpie_defaults.json` ✅ (already done)
- `src/config/indexing_rules.py` — Pydantic models, `should_index()`, JSON load/save with file-mtime cache invalidation
- `tests/test_indexing_rules_should_index.py` — precedence table tests
- `tests/test_indexing_rules_loading.py` — round-trip, malformed JSON, version handling
- `tests/test_category_map.py` — every router extension constant maps to exactly one category
- `Plans/Ingestion Rules/Implementation Plan.md` ✅ (this doc)

**Files modified**
- `src/router.py` — add `CATEGORY_MAP` at the top; **leave existing constants** (`TEXT_EXTS`, `CODE_EXTS`, etc.) untouched to avoid behavior change in tier routing. `CATEGORY_MAP` is a superset for user-facing categorization, derived where overlap exists.
- `src/manifest.py` — add `mtime: float | None = None` to `Entry`. `needs_summarization()` uses size only by default; if `MAGPIE_DEV_USE_MTIME=1`, also requires `mtime <= entry.mtime`.
- `src/ingest/walker.py` — replace `IgnoreRules.from_root()` calls (4 of them) and `is_ignored()` calls with `IndexingRules.should_index()`. Preserve the dir-prune fast path via `IndexingRules.is_pruneable_dir()`.
- `src/router.py:1267` — replace the one `IgnoreRules.from_root` call there too.
- `src/ingest/ignore.py` — gut to a thin shim. The cascade discovery logic (per-dir spec building) becomes a private helper used by `IndexingRules`. Public `IgnoreRules` class is removed; module retains `DEFAULT_IGNORE_PATTERNS` only as a deprecation crutch (logs a warning if imported).
- `justfile` — rename existing `sync` → `sync-environment`. Add new `sync` that walks all enabled `include_paths`. Keep `walk`, `walk-data`, `walk-rebuild`, `walk-force`, `walk-explain` working as escape hatches but make them respect the new rules.
- `pyproject.toml` — add `psutil` dependency (memory check used in PR2; harmless to add now).
- `Plans/Future Plans.md` — append Plans #11 (cleanup unification, already added), #12 (data-tier routing), #13 (daemon as OS service), #14 (mtime toggle promotion), #15 (auto-promotion of nested rules), and an addendum to Plan #10 (packaging `magpie_defaults.json`).

**End state:** Existing CLI commands (`just walk <path>`, `just walk-rebuild`, `ns --sync`) work the same as today, but the rules they obey come from `indexing_rules.json` + `.magpieinclude`/`.magpieexclude` + `.gitignore` + `.nasignore` instead of the hardcoded `DEFAULT_IGNORE_PATTERNS`. **Mridul keeps working without changes.**

**First-run behavior:**
- If no `indexing_rules.json` exists: create one with empty `include_paths` and sensible defaults. Print: `"No indexed folders configured. Add one with: just walk <folder>  (auto-adds it to indexing_rules.json)"`.
- If user runs `just walk <path>` and `<path>` isn't under any `include_paths` entry: auto-add it as an `include_paths` entry, then walk. Print: `"Auto-added <path> to indexed folders."`.
- If `indexing_rules.json` doesn't exist AND the user has an existing manifest with entries: same as first case (don't try to auto-infer roots — see Q16 from chat). User runs `just walk <existing-corpus-root>` and it gets added.

**Validation steps before PR1 merges**
1. `uv run pytest tests/` — full suite green.
2. `just walk-explain <small-test-dir>` — prints rule-trace lines.
3. `just walk-rebuild <Mridul's CSV dir>` — same number of files indexed as before.
4. `just walk-data ~/some-other-dir` — auto-adds the dir as a root, indexes successfully.
5. Drop a `.magpieexclude` containing `*.tmp` in a test dir; re-walk; confirm `.tmp` files are skipped.
6. Cross-check: nothing imports from `src.ingest.ignore.IgnoreRules` anymore (`grep -rn IgnoreRules src/` returns only the shim file itself).

---

### PR2 — Daemon + Watcher + Queues

**Open decision deferred to start of PR2:** sidecar absorbs daemon, OR daemon stays separate. Pros/cons table in chat history; my recommended path is sidecar-absorbs-daemon for MVP simplicity.

**Files created**
- `src/daemon/watcher.py` — `watchdog.Observer` wrapper. Watches all enabled `include_paths` + the `indexing_rules.json` file itself. Debounces events (8s window).
- `src/daemon/queues.py` — fast queue (cleanup) + slow queue (ingestion). JSONL persistence at `<APP_DATA_DIR>/queues/{fast,slow}.jsonl`. Append-only, compacted on startup or every 1000 entries.
- `src/daemon/reconciler.py` — startup catch-up pass. Scans manifest vs disk vs `should_index()`.
- `src/daemon/lock.py` — `~/.local/share/Magpie/daemon.lock` file. CLI commands check this; if present, refuse to run with: `"Daemon is running (pid N). Stop it with `just daemon-stop` or run with --force."`.

**Files modified**
- `src/daemon/__main__.py` — wire up watcher + queues + reconciler on `--detach`. Idle behavior changes: process stays alive while there are enabled `include_paths`, only models unload after `NS_DAEMON_IDLE_MINUTES`.
- `src/ingest/walker.py` — accept a "dirty paths" set (from queue) for incremental walks instead of always traversing the whole root.
- Justfile — `just walk*` commands check the daemon lock and refuse if running.

**End state:** User edits `indexing_rules.json` (or future GUI does). Daemon notices, reconciles. New file dropped in a watched folder gets indexed within 5–10 minutes (slow queue cycle). Crash safety: queue items survive restart.

---

### PR3 — API + GUI Hooks

**Files modified/created**
- `src/server.py` — add endpoints:
  - `GET  /settings/indexing-rules` — returns the JSON
  - `PUT  /settings/indexing-rules` — replaces the JSON; signals daemon to reload
  - `POST /settings/include-path` — `{path: string}` adds to `include_paths`
  - `POST /settings/exclude-path` — `{path: string}` adds to `exclude_paths`
  - `DELETE /settings/include-path/{idx}` — removes by index
  - `DELETE /settings/exclude-path/{idx}` — removes by index
  - `GET  /diagnostics/why-not?path=<path>` — runs `should_index()`, returns `{indexed: bool, reason: string, chain: [...]}`
  - `POST /actions/reindex-all` — triggers `walk-force` equivalent for all enabled include_paths
- `frontend/src-tauri/src/lib.rs` — add Tauri `invoke` handlers that proxy to the sidecar for the above endpoints (so the JS frontend can call `await invoke("add_include_path", { path: "/x" })` instead of fetching the sidecar directly).

**End state:** GUI team can build the include/exclude buttons. The "Why isn't this indexed?" feature works. All pattern editing goes through the API, not direct file writes.

---

## 7. Migration

**Existing user (Astavak):**
1. First run after deploying PR1: `~/.local/share/Magpie/indexing_rules.json` is created empty. Existing manifest at the same dir is untouched. Search still works against existing Qdrant points.
2. To get the new system actually filtering on his existing corpus, he runs `just walk-rebuild <his-root>` once. The new walker uses `should_index()`. Auto-add happens. Subsequent walks honor rules from JSON + inline files.
3. His existing `.gitignore` files in his corpus continue to be respected (default `respect_gitignore: true`).
4. If he had any `.nasignore` files: still respected.

**Existing user (Mridul):**
1. After pulling PR1, runs `just walk-data <his-CSV-dir>` (which is what worked for him). The path auto-adds as a new `include_paths` entry. Same indexing behavior as today.

**Truly new user:**
1. Empty `indexing_rules.json` on first run.
2. CLI: `just walk <some-folder>` → auto-adds, walks, indexes.
3. GUI (future): clicks "Add folder," picks one. Same effect.

**Old `.nasignore` files in the wild:** still respected (no deprecation — kept as a parallel name to `.magpieexclude` for back-compat).

**`src/ingest/ignore.py` removal:** kept as deprecation shim through PR3, removed in a follow-up PR after one release cycle.

---

## 8. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `should_index()` slower than current `IgnoreRules.is_ignored()` due to more checks | Medium | Medium (slow walks on big corpora) | Pre-compile pathspecs once on load. Cache compiled spec per cascade dir. Benchmark on Astavak's 1721-entry corpus before merge — must be within 2× current. |
| Auto-adding `include_paths` on first `just walk <path>` surprises users who don't want their config rewritten | Low | Low | Print explicit message: `"Auto-added <path> to indexing_rules.json. Edit at: <full path>"`. Add `--no-add-root` flag for users who want strictly transient walks. |
| Existing `.nasignore` users see no change but think "did Magpie stop respecting this?" | Low | Low | One-line note in PR description and CHANGELOG. `.nasignore` continues to work identically. |
| Cascade discovery of `.magpieinclude`/`.magpieexclude` adds latency on huge trees | Medium | Low | Same cascade discovery the current `ignore.py` does. Adding two more filenames to `IGNORE_FILENAMES` is O(per-dir-stat), no new cost. |
| Fresh first-run: user sees `"No indexed folders configured"` and doesn't know what to do | High (most new users hit this) | Medium | Two-line CLI output: command + example. GUI (PR3) replaces this with the folder-picker dialog. |
| Mridul's CSV row-points break under new rules because `.csv` is in `categories_enabled.data: true` BUT some default exclude rule catches it | Low | High (regression of just-fixed work) | Validation step #3 above explicitly re-runs his walk and confirms 2466 row points land. |
| `mtime` field added to manifest schema breaks reading old manifests | Low | Medium | Pydantic-style optional field with default `None`. `Manifest._load` already drops unknown fields ([src/manifest.py:131](../../src/manifest.py#L131)). New field is forward+backward compatible. |
| Auto-add behavior gets out of sync with daemon (PR2): user runs `just walk <path>` while daemon is also walking | Medium | Medium | PR2 introduces daemon lockfile; CLI walks check it and refuse. Single-writer rule for the JSON. |
| `psutil` dep adds ~3 MB. PR1 doesn't need it (memory check is PR2 backpressure logic). | Low | Trivial | Add it now anyway since it's painless and PR2 will need it. |
| Schema version bump in `indexing_rules.json` someday breaks user files | Future | Medium | Pydantic `version: int` field already in schema. On load, if version mismatches, run a migration func. None needed for v1; design enables v2 later. |

---

## 9. Cross-References

### Future Plans this work touches or depends on
- [Plan #10 — Self-contained packaging](../Future%20Plans.md): need to ship `magpie_defaults.json` inside the bundled app. Will append a note when this work lands.
- [Plan #11 — Unify orphan-cleanup pattern](../Future%20Plans.md): not blocked by this work, but related — both touch the manifest as source-of-truth contract.
- [Plan #12 — Routing data files (CSV/JSON/etc.) properly through tiers](../Future%20Plans.md): TO ADD. Stems from your Q5 about CSV defaults.
- [Plan #13 — Daemon as OS service](../Future%20Plans.md): TO ADD. The "graduate from sidecar-absorbs-daemon to true launchctl/systemd" path.
- [Plan #14 — Promote `MAGPIE_DEV_USE_MTIME` to user-facing setting](../Future%20Plans.md): TO ADD. Once we know dev experience with mtime is good.
- [Plan #15 — Auto-promotion of nested exclude paths into sub-roots](../Future%20Plans.md): TO ADD. The deferred "rule normalization" idea.
- [Plan #4 — Rust-side file watcher](../Future%20Plans.md): when watchdog hits limits.

### Existing files most affected
- `src/ingest/ignore.py` ([459 lines](../../src/ingest/ignore.py)) — gutted to a shim.
- `src/ingest/walker.py` ([1035 lines](../../src/ingest/walker.py)) — 4 IgnoreRules call sites updated.
- `src/router.py` ([1354 lines](../../src/router.py)) — adds CATEGORY_MAP, updates 1 IgnoreRules call site.
- `src/manifest.py` — adds `mtime: float | None`.
- `justfile` — renames `sync`, adds new `sync`.

### Source documents (don't lose context)
- [Original spec — Promts/build_ingestion_rules.md](../../Promts/build_ingestion_rules.md) (Mridul's prompt, captures original Gemini output)
- [Future Plans.md](../Future%20Plans.md)

---

## 10. Design Deviations from Original Spec

The original spec ([Promts/build_ingestion_rules.md](../../Promts/build_ingestion_rules.md)) has been adjusted where conversation revealed simpler shapes. Tracked here so future engineers know what changed and why.

| Original spec | Plan deviation | Reason |
|---|---|---|
| `roots[]` with mandatory per-root `rules` | `include_paths[]` with optional `rules` | UI-driven thinking (file/folder picker buttons). Most users won't set per-folder rules; making them optional removes a layer of forced complexity. |
| `RuleSet.exclude_dirs` / `exclude_extensions` per-root | Removed from per-root `RuleSet` (only `exclude_globs`, `include_globs`, `categories_enabled`, `max_file_size_mb`) | The "exclude this specific thing" use case is served by top-level `exclude_paths`. Per-root only needs PATTERN rules. |
| `include_globs` / `include_extensions` as primary mechanism for force-include | Replaced by user clicking "Include this specific file" → entry in top-level `include_paths` (file-typed entries supported as of 2026-05-08; see [§4 row 0](#precedence-top-wins)) OR `.magpieinclude` for pattern-based force-include | Direct path picks are clearer than glob inversion. |
| `include_paths[].path` accepts directories only ("Files only allowed by future iteration") | File entries supported as of 2026-05-08. File-typed entries trigger the precedence-row-0 short-circuit and override every other rule (exclude_paths, gitignore, hidden, category, size). Directory entries unchanged. | Surfaced when a user added a single-file include via the future GUI's "Include file" button mockup; without it, the walker erred with "expects a directory" mid-sync, leaving the auto-backup to clobber the prior good state. |
| Drop `.nasignore` support entirely | Keep `.nasignore` for back-compat. Add `.magpieinclude`/`.magpieexclude` as on-brand alternatives | User direction: "we should respect gitignore and nasignores." |
| Auto-promotion of nested rules into sub-roots | Deferred to Future Plan #15 | Round-trip surprise + GUI doesn't exist yet to render the promoted shape. |
| Daemon process owns API endpoints | Sidecar-absorbs-daemon (provisional, decided at start of PR2) | Simpler MVP. Trade-off: file watching only happens while Tauri is open. Future plan to extract back. |
| `mtime` field assumed to exist in manifest | Add as optional, gated behind `MAGPIE_DEV_USE_MTIME=1` for dev-only initially | Non-trivial schema change for production users; toggle keeps it dev-only until proven. |
| Migrate manifest entries to auto-inferred roots on first run | Don't auto-infer; ask user to add roots (explicit > magic) | Q16 answer: prefer user explicitness over inference. |
| `just sync` (ambiguous with existing) | Rename existing → `sync-environment`; new `sync` does indexing | Q14 answer. |
