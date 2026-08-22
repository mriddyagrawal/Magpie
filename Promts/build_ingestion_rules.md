# Claude Code Prompt: Implement Magpie IndexingRules System

## Context

Magpie is a RAG-over-local-filesystem desktop app (Tauri frontend, Python backend, Qdrant vectors). It indexes local files by summarizing them with a vision LLM, embedding summaries into Qdrant, and answering natural-language queries with cited sources. The filesystem is the single source of truth — no shadow copies.

The current ingest pipeline works like this:

1. The user manually runs `just walk <path>` or `python -m src.ingest <path>`.
2. `src/ingest/walker.py` discovers files under that path using `os.walk`, filtered by `src/ingest/ignore.py` (which reads `.gitignore`, `.nasignore`, and hardcoded `DEFAULT_IGNORE_PATTERNS`).
3. `src/router.py` classifies each file into tiers (T0–T4) based on extension and size.
4. `src/stage1/summarize.py` produces structured markdown summaries per file.
5. `src/stage2/` embeds summaries into Qdrant (hybrid dense + BM25).
6. `src/manifest.py` tracks the state of every file (size, mtime, summary path, ingestion timestamps, skip reasons).

**The problem:** Indexing is entirely manual and CLI-driven. Users must know which paths to walk, must re-run commands when files change, and file filtering is spread across three unrelated systems (`.gitignore`, `.nasignore`, hardcoded patterns in `ignore.py`). This needs to become a single, unified, JSON-driven config that the app reacts to automatically.

---

## What You Are Building

A two-layer JSON configuration system that replaces all existing file-filtering logic and becomes the single source of truth for "what should Magpie index." This system has three major components:

### Component 1: The Two JSON Files

#### `magpie_defaults.json` — Developer-controlled safety rails

- **Location during development:** `src/config/magpie_defaults.json` (checked into the repo).
- **Location in production:** Bundled as a Tauri resource, read-only.
- **Purpose:** Contains patterns that prevent the app from indexing system junk, caches, build artifacts, and other noise. Users never edit this directly.
- **Updated by:** Magpie developers, shipped with app updates.

Contents (this is the starting point — examine `src/ingest/ignore.py`'s `DEFAULT_IGNORE_PATTERNS` and migrate everything here):

```json
{
  "version": 1,
  "exclude_dirs": [
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".nuxt", "dist", "build", ".svn", ".hg",
    ".DS_Store", "Thumbs.db", "$RECYCLE.BIN",
    ".Spotlight-V100", ".fseventsd", ".Trashes",
    "System Volume Information", "Recovery",
    ".cache", ".tmp", "tmp"
  ],
  "exclude_globs": [
    "**/*.pyc", "**/*.pyo", "**/*.o", "**/*.so", "**/*.dylib",
    "**/*.class", "**/*.jar",
    "**/package-lock.json", "**/yarn.lock", "**/Cargo.lock",
    "**/.env", "**/.env.*"
  ],
  "exclude_extensions": [
    ".DS_Store", ".thumbs.db"
  ],
  "ignore_hidden": true
}
```

**Important:** Look at what `src/ingest/ignore.py` currently blocks and make sure every pattern is migrated here. Do NOT leave any hardcoded filtering logic in `ignore.py` — this JSON replaces it entirely.

#### `indexing_rules.json` — User-controlled preferences

- **Location:** `APP_DATA_DIR/indexing_rules.json` (resolve APP_DATA_DIR from `src/manifest.py` — it's already defined there as `~/.local/share/Magpie` on Linux, `~/Library/Application Support/Magpie` on macOS).
- **Created:** On first launch with empty roots and sensible defaults.
- **Edited by:** The Tauri GUI (future) and by hand (now, during development). The daemon watches this file for changes.

```json
{
  "version": 1,
  "roots": [
    {
      "path": "/home/user/Documents",
      "enabled": true,
      "rules": {
        "exclude_dirs": [],
        "exclude_globs": [],
        "include_globs": [],
        "exclude_extensions": [],
        "include_extensions": [],
        "exclude_categories": [],
        "include_categories": [], 
      }
    }
  ],
  "global_rules": {
    "exclude_dirs": [],
    "exclude_globs": [],
    "include_globs": [],
    "exclude_extensions": [],
    "include_extensions": [],
  },
  "respect_gitignore": true,
  "ignore_hidden": true,
  "max_file_size_mb": 200,
  "categories_enabled": {
    "text": true,
    "document": true,
    "image": true,
    "data": false,
    "code": true,
    "archive": false
  }
}
```

### Component 2: The Pydantic Models and Filter Chain

Create a new file `src/config/indexing_rules.py` (or similar — find the right place in the existing project structure).

#### Models

```python
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional

class RuleSet(BaseModel):
    exclude_dirs: list[str] = []
    exclude_globs: list[str] = []
    include_globs: list[str] = []
    exclude_extensions: list[str] = []
    include_extensions: list[str] = []

class RootConfig(BaseModel):
    path: str
    enabled: bool = True
    rules: RuleSet = Field(default_factory=RuleSet)

class MagpieDefaults(BaseModel):
    version: int = 1
    exclude_dirs: list[str] = []
    exclude_globs: list[str] = []
    exclude_extensions: list[str] = []
    ignore_hidden: bool = True

class IndexingRules(BaseModel):
    version: int = 1
    roots: list[RootConfig] = []
    global_rules: RuleSet = Field(default_factory=RuleSet)
    respect_gitignore: bool = True
    ignore_hidden: bool = True
    max_file_size_mb: float = 100.0
    categories_enabled: dict[str, bool] = {
        "text": True, "document": True, "image": True,
        "data": False, "code": True, "archive": False,
    }
```

#### The CATEGORY_MAP

In `src/router.py`, create (or find and unify) a `CATEGORY_MAP` dictionary that maps category names to extension sets:

```python
CATEGORY_MAP: dict[str, set[str]] = {
    "text": {".txt", ".md", ".rst", ".log", ".rtf", ...},
    "document": {".pdf", ".docx", ".pptx", ".odt", ".xlsx", ...},
    "image": {".png", ".jpg", ".jpeg", ".webp", ".heic", ".tiff", ...},
    "data": {".csv", ".json", ".xml", ".yaml", ".yml", ".parquet", ".dat", ...},
    "code": {".py", ".js", ".ts", ".rs", ".c", ".cpp", ".java", ".go", ...},
    "archive": {".zip", ".tar", ".gz", ".7z", ".rar", ...},
}
```

**Critical:** Do NOT hardcode these sets in the Pydantic model or in the JSON. The JSON stores category names ("text": true/false). The code resolves those names to extensions via `CATEGORY_MAP` at runtime. The router is the single source of truth for what extensions belong to what category. If `router.py` already has these extension sets defined (look at the routing logic — it almost certainly does), unify them into this one dict rather than duplicating.

#### The Filter Chain: `should_index()`

This is the core logic. It takes a filepath and returns `(bool, str)` — whether to index and why/why not. The `str` reason powers the explain/dry-run CLI and will power the future GUI status view.

**Precedence rules (this is critical — get this right):**

The system has three layers, from most specific to least specific: Root-specific rules → Global user rules → Magpie defaults. Within each layer, **exclude is checked before include.** A more specific layer can override a less specific one. Specifically:

1. **Is the file under an enabled root?** No → `(False, "not under any indexed root")`
2. **Root-specific exclude_dirs / exclude_globs match?** Yes → `(False, "root exclude: <pattern>")`
3. **Root-specific include_globs / include_extensions match?** Yes → `(True, "root include: <pattern>")` — this is how a user force-includes something that would otherwise be blocked by global rules or defaults
4. **Global user exclude_dirs / exclude_globs match?** Yes → `(False, "global exclude: <pattern>")`
5. **Global user include_globs / include_extensions match?** Yes → `(True, "global include: <pattern>")`
6. **Magpie defaults exclude_dirs / exclude_globs match?** Yes → `(False, "default exclude: <pattern>")` — but note: if the user already passed steps 2-5 without matching, the defaults act as the safety net
7. **respect_gitignore is true AND file matches a .gitignore rule?** Yes → `(False, "gitignore: <pattern>")`
8. **Is it a hidden file/dir (starts with `.`) and ignore_hidden is true?** Yes → `(False, "hidden file")`
9. **Does the extension belong to a disabled category in categories_enabled?** Yes → `(False, "category disabled: <category>")`. Unknown extensions (not in any category) should be **allowed** by default — the router will handle them downstream.
10. **Is file size > max_file_size_mb?** Yes → `(False, "exceeds max file size")`
11. **All checks passed** → `(True, "ok")`

**Important detail about step 3 and 5 (include rules):** An include at the root level can override global excludes and Magpie defaults. This is how a user says "I know `node_modules` is excluded by default, but I want `node_modules/my-config.json` specifically." A *file-specific* include (an exact path or narrow glob) overrides a *directory-level* exclude. However, a root-level *exclude* still wins over a root-level *include* within the same root — because if a user explicitly excludes something in the same scope where they're including it, the exclude is the more cautious and likely more intentional action.

### Component 3: Integration with the Existing Pipeline

#### Replace `src/ingest/ignore.py`

The `IgnoreRules` class in `src/ingest/ignore.py` currently handles `.gitignore`, `.nasignore`, and `DEFAULT_IGNORE_PATTERNS`. This needs to be **replaced** by the new `IndexingRules.should_index()` method. Do not keep both systems running in parallel.

Steps:
1. Read `src/ingest/ignore.py` thoroughly. Understand every pattern it blocks.
2. Migrate all patterns from `DEFAULT_IGNORE_PATTERNS` into `magpie_defaults.json`.
3. The `.gitignore` reading logic should be preserved but gated behind the `respect_gitignore` boolean in `indexing_rules.json`.
4. Remove `.nasignore` support entirely. Any patterns previously in `.nasignore` files should be expressible via the user's `indexing_rules.json` exclude rules.
5. Update `src/ingest/walker.py` to call `IndexingRules.should_index()` instead of `IgnoreRules`.

#### Update `src/ingest/walker.py`

The walker currently takes a `path` argument and walks it. It needs to change:

- **When called with a specific path** (CLI mode, e.g., `just walk <path>`): Walk that path, but filter every file through `should_index()`. If the path isn't under an enabled root, warn and exit.
- **When called without a path** (daemon/app mode): Iterate over all enabled roots in `indexing_rules.json` and walk each one.

The **root cache optimization**: When walking a root, resolve the `RootConfig` once at the start of the walk. Thread it through the `os.walk` recursion so you don't re-match every file against all roots. During `os.walk`, you already know which root you're under.

#### Update the Justfile

The following commands should continue to work but now respect `indexing_rules.json`:
- `just walk <path>` — walks that specific path, filtered by rules
- `just walk-force <path>` — re-summarizes everything under that path (bypasses "already summarized" checks, but still respects indexing rules for which files to include)
- `just walk-explain <path>` — now powered by the `should_index()` reason strings
- `just walk-rebuild <path>` — drops collections + manifest for that root, re-ingests

Add new commands:
- `just sync` or `just index` (name TBD) — the "do everything" command. Reads `indexing_rules.json`, walks all enabled roots, processes the queues. This is the replacement for manually running `just walk <path>` for each directory.

**Do NOT remove the existing `just walk <path>` commands.** They remain as power-user escape hatches. But the primary workflow shifts to: edit `indexing_rules.json` → the system reacts.

---

## Daemon Integration (Wire the Plumbing)

The existing daemon (`src/daemon/`) keeps search models hot. It needs to be extended to also manage the indexing lifecycle. The daemon becomes the single long-running process.

### File Watcher

Add a filesystem watcher (use Python's `watchdog` library) to the daemon. It watches all enabled roots from `indexing_rules.json`.

**Behavior:**
- On file created/modified: Check against `should_index()`. If allowed, add to the **ingest queue** (details below).
- On file deleted: If the file is in the manifest, mark its manifest entry as orphaned (clear summary pointer, mark for Qdrant cleanup).
- On file renamed/moved: Treat as delete + create.
- **Debouncing:** Batch filesystem events. Don't react to every individual event. Accumulate events for 5–10 seconds, deduplicate by path, then process the batch. A single file save can fire 3–5 OS events.

**Also watch `indexing_rules.json` itself.** When the user edits it (by hand or via future GUI), the daemon detects the change, reloads the config, and re-evaluates:
- New root added → queue a full walk of that root.
- Root removed → mark all its manifest entries as orphaned.
- Root disabled → same as removed (but keep entries, don't delete — re-enable should bring them back without re-summarizing).
- Category toggled off → find all manifest entries with extensions in that category, mark for removal from Qdrant (but keep summaries on disk — they're cheap and re-enabling is instant).
- Category toggled on → find all files on disk matching that category under enabled roots, queue for ingestion.
- Exclude/include rules changed → re-evaluate all manifest entries against current rules, queue additions/removals.

**How to re-evaluate on rules change:** Don't try to diff old rules vs new rules. Instead:
1. Load new rules.
2. For every entry in the manifest: run `should_index(path)`. If it returns False but the entry is currently indexed → queue for removal.
3. For every file on disk under enabled roots (requires a walk): run `should_index(path)`. If it returns True but the file is NOT in the manifest → queue for ingestion.

This is O(manifest_size + disk_files) but happens rarely (only on config change) and can be done incrementally.

### The Two Queues

The daemon maintains two queues:

#### Fast Queue (Cleanup) — runs every 15 minutes
- Processes: file deletions, orphan cleanup, stale manifest entries.
- Operations: remove Qdrant points, clear manifest entries, delete orphaned summary markdowns.
- Cost: cheap — no LLM calls, just manifest I/O and Qdrant deletes.
- Also runs at startup (the "catch-up" pass).

#### Slow Queue (Ingestion) — runs every 30 minutes (or on idle)
- Processes: new files, modified files, files whose summaries need regeneration.
- Operations: route → summarize → embed → upsert to Qdrant → update manifest.
- Cost: expensive — LLM calls for summarization.
- **Backpressure:** Process in batches of 20–50 files per cycle. Check system memory/CPU before starting a batch. On an 8GB Mac, don't start a summarization batch if available memory is below ~1GB.
- Should yield to user queries — if a search is in progress, pause ingestion.

#### Startup Reconciliation (the "Catch-Up" Pass)

When the daemon starts:
1. Load `indexing_rules.json`.
2. For every entry in the manifest:
   - `stat()` the source file. If it's gone → add to fast queue (orphan cleanup).
   - Compare mtime and size against manifest. If changed → add to slow queue (re-summarize).
   - Run `should_index()`. If it now returns False (rules changed while daemon was off) → add to fast queue.
3. For every enabled root, do a quick `os.walk` and check for files that pass `should_index()` but aren't in the manifest → add to slow queue.
4. Process fast queue immediately.
5. Process slow queue on the normal 30-minute cycle (or immediately if the queue is small, say <20 files).

### Daemon Idle Behavior

Currently the daemon shuts down after 15 minutes of idle. Change this:
- The daemon process stays running as long as there are enabled roots (it's always watching).
- **Models** are unloaded after 15 minutes of no queries (configurable via `NS_DAEMON_IDLE_MINUTES`). This frees the ~250MB–3GB of RAM from search models while keeping the watcher and queues active.
- The daemon only fully shuts down when explicitly stopped (`just daemon-stop`) or when there are zero enabled roots.

---

## Migration Plan

When implementing, handle the transition from the old system to the new one:

1. On first run with the new code, if `indexing_rules.json` doesn't exist, create it with defaults. If there are existing manifest entries, infer the roots from them (group manifest paths by their top-level directories) and add them as roots — the user shouldn't lose their existing index.
2. If `.nasignore` files exist in any watched directories, log a deprecation warning: "`.nasignore` files are no longer used. Please add your exclude rules to Magpie's indexing settings."
3. Keep `src/ingest/ignore.py` around but deprecated for one release cycle, then remove.

---

## Testing

Add tests in `tests/` for:

1. **`should_index()` precedence tests** — the most critical tests. Cover:
   - File under no root → rejected
   - File matching root exclude → rejected even if it matches global include
   - File matching root include → accepted even if it matches Magpie default exclude
   - Root include does NOT override root exclude in the same root
   - Hidden file rejected when `ignore_hidden=True`, accepted when `False`
   - Disabled category rejects matching extensions
   - Unknown extensions (not in any category) are allowed through
   - `max_file_size_mb` enforcement
   - `respect_gitignore` toggle
2. **Config loading** — malformed JSON, missing fields (Pydantic defaults kick in), version migration.
3. **CATEGORY_MAP consistency** — every extension in `router.py`'s routing logic appears in exactly one category.
4. **Queue behavior** — files added to correct queue based on event type.

---

## Files to Read First

Before writing any code, read and understand these files in order:

1. `src/manifest.py` — understand the Manifest class, `APP_DATA_DIR`, `ManifestEntry` fields (especially `size`, `summary_file`, `skip_reason`, `fast_indexed_at`, `fast_pages`). This is your integration point.
2. `src/ingest/ignore.py` — understand `IgnoreRules`, `DEFAULT_IGNORE_PATTERNS`, and how `.gitignore`/`.nasignore` are currently parsed. You're replacing this.
3. `src/ingest/walker.py` — understand `find_candidates()` and how it feeds into the pipeline. You're modifying this.
4. `src/router.py` — understand the tier system (T0–T4), the extension sets, and where `CATEGORY_MAP` should live. You're adding to this.
5. `src/pipeline.py` — understand `run_batch()` and how walker feeds into it. This is the orchestration layer.
6. `src/daemon/` — understand the daemon's lifecycle, the `--detach`/`--status`/`--stop` commands, the idle shutdown logic. You're extending this.
7. `src/server.py` — the FastAPI sidecar. You'll add a `/settings/indexing-rules` endpoint here (GET to read, PUT to write + trigger re-evaluation).
8. The Justfile at the project root — understand all the existing commands. You're modifying some and adding new ones.

---

## What NOT to Do

- Do NOT add SQLite or any database for this. JSON + Pydantic is the right tool.
- Do NOT keep `.nasignore` support. It's being replaced.
- Do NOT keep hardcoded ignore patterns in Python code. Everything goes in `magpie_defaults.json`.
- Do NOT break the existing `just walk <path>` commands. They must still work as escape hatches.
- Do NOT start the watcher on directories that aren't in the user's roots. Only watch enabled roots.
- Do NOT process the slow queue during active user queries. Yield to search.
- Do NOT load the full `indexing_rules.json` on every `should_index()` call. Load once, hold in memory, reload only when the file changes.

---

## Future Plans (Do Not Implement Now, But Design For)

These features are planned for later. The architecture you build now should not block them:

1. **Tauri GUI settings panel** — will read/write `indexing_rules.json` through the FastAPI sidecar's `/settings/indexing-rules` endpoint. The GUI will show a folder picker for adding roots, toggle switches for categories, and a list of exclude/include rules. Design the API endpoint now even if the GUI isn't built yet.

2. **"Why is this file missing?" UI** — the user clicks a file in the GUI and sees the `should_index()` reason string explaining why it was or wasn't indexed. The `(bool, reason)` return value powers this.

3. **Per-file override in the GUI** — the user right-clicks a file and says "Always index this" or "Never index this." This would add the file's exact path to `include_globs` or `exclude_globs` in the relevant root config. The data model already supports this.

4. **Rust-side file watcher** — Tauri's Rust process may eventually use the `notify` crate for more efficient file watching instead of Python's `watchdog`. The daemon should communicate via the sidecar API (`POST /events/file-changed`) so swapping the watcher implementation is just changing who calls that endpoint.

5. **Onboarding flow** — on first launch, the Tauri GUI will show a folder picker saying "What folders should Magpie watch?" and populate the first root in `indexing_rules.json`. For now, the user creates the config by hand or via CLI.

6. **"Re-index everything" button** — equivalent to `just walk-force` for all roots. Should be a single API call (`POST /actions/reindex-all`). Stub the endpoint now.

---

## Summary of Deliverables

1. `src/config/magpie_defaults.json` — migrated from `ignore.py` patterns
2. `src/config/indexing_rules.py` — Pydantic models + `should_index()` + config loading/saving
3. `CATEGORY_MAP` in `src/router.py` — unified extension-to-category mapping
4. Updated `src/ingest/walker.py` — uses `should_index()` instead of `IgnoreRules`
5. Updated `src/ingest/ignore.py` — deprecated, gutted, replaced by config system
6. Updated `src/daemon/` — file watcher, config watcher, two queues, startup reconciliation, idle model unloading (not process shutdown)
7. Updated `src/server.py` — `/settings/indexing-rules` endpoint (GET/PUT), stub endpoints for future actions
8. Updated Justfile — new `just sync`/`just index` command
9. Tests in `tests/` — precedence tests for `should_index()`, config loading, category mapping
10. A `MIGRATION.md` or similar doc explaining the transition from the old system

Read the codebase first. Understand how things work now. Then implement incrementally: config models → filter chain → walker integration → daemon extension → server endpoints → tests.