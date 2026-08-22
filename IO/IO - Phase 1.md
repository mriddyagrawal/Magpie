# Phase 1 — Portable paths

> **What this doc is.** A frozen-in-time record of the path-portability
> work done 2026-04-27. Replaces hardcoded `<repo>/Test Summaries/` data
> paths with a `platformdirs`-driven `APP_DATA_DIR` so the same code runs
> correctly on the dev's repo, on a Linux user's `~/.local/share/`, on
> a Windows user's `%LOCALAPPDATA%`, and on a macOS user's
> `~/Library/Application Support/`.
>
> Read this when: you need to understand where Magpie keeps its data,
> why we don't ship the repo to users, or before changing any
> filesystem path constant in `src/`.

---

## The single core change

```python
# src/manifest.py — BEFORE
REPO_ROOT = Path(__file__).resolve().parent.parent      # /mnt/.../NotAnotherSpotlight
DEFAULT_MANIFEST_PATH = REPO_ROOT / "Test Summaries" / "_manifest.json"

# src/manifest.py — AFTER
from platformdirs import user_data_dir

APP_DATA_DIR = Path(user_data_dir("Magpie", "magpie", roaming=False))
SUMMARIES_DIR = APP_DATA_DIR / "summaries"
DEFAULT_MANIFEST_PATH = APP_DATA_DIR / "manifest.json"

# Backward-compat alias so existing imports keep working
REPO_ROOT = APP_DATA_DIR
```

Plus an env-var override for tests / CI:

```python
def _resolve_app_data_dir() -> Path:
    override = os.environ.get("MAGPIE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_dir("Magpie", "magpie", roaming=False))
```

That's the entirety of the substantive change. Five other files were
edited to import `APP_DATA_DIR` from `manifest.py` instead of redefining
their own `REPO_ROOT = Path(__file__).resolve().parent.parent`. Identical
runtime behavior, single source of truth.

## What APP_DATA_DIR resolves to per OS

| OS | Default path | Set by |
|---|---|---|
| Linux | `~/.local/share/Magpie/` | XDG Base Directory spec |
| Windows | `%LOCALAPPDATA%\magpie\Magpie\` | Windows app-data convention |
| macOS | `~/Library/Application Support/Magpie/` | Apple's File System Programming Guide |
| any | whatever `$MAGPIE_DATA_DIR` is set to | env-var override |

Three files live under `APP_DATA_DIR`:

```
<APP_DATA_DIR>/
├── manifest.json           ← per-file metadata
├── summaries/              ← T1/T2/T3 summary markdowns
│   ├── 4f0e1c8a2b9d3e7c_t2.md
│   └── 9f4a23c10b7d8e6f_t3.md
└── (eventually: qdrant_data/, hf-cache/, logs/)
```

## End-to-end with a real session

### On the dev's repo (Linux)

```bash
$ uv run python -c "from src.manifest import APP_DATA_DIR; print(APP_DATA_DIR)"
/home/astavak/.local/share/Magpie

$ ls /home/astavak/.local/share/Magpie/
manifest.json  summaries/
```

The repo's `Test Summaries/` directory is no longer touched by the
running code. It still exists on disk (until you delete it), but the
app reads/writes only from `~/.local/share/Magpie/`.

### On a fresh Windows user's machine (after install)

```
C:\Users\jdoe\AppData\Local\magpie\Magpie\
├── manifest.json
└── summaries\
    └── 9f4a23c10b7d8e6f_t3.md
```

The user never sees this. The desktop app indexes their Documents folder,
writes here, queries here.

### On macOS

```
/Users/jdoe/Library/Application Support/Magpie/
├── manifest.json
└── summaries/
```

Same code, different default path — `platformdirs` handles the per-OS
convention automatically.

### Override for tests

```bash
$ MAGPIE_DATA_DIR=/tmp/magpie-isolated uv run pytest
# All test data lands under /tmp/magpie-isolated/, easy to clean up
```

## Migration: moving existing data into the new location

When you upgrade past v0.1.0-cli, your existing `<repo>/Test Summaries/`
data needs to move once. The script does it:

```bash
$ uv run python scripts/migrate_data.py
legacy data:  /mnt/hardisk/NotAnotherSpotlight/Test Summaries
  - manifest: yes
  - summaries: 19355 .md file(s)

target:       /home/astavak/.local/share/Magpie
  - manifest -> /home/astavak/.local/share/Magpie/manifest.json
  - summaries -> /home/astavak/.local/share/Magpie/summaries

DRY RUN — no files moved. Re-run with --apply to migrate.

$ uv run python scripts/migrate_data.py --apply
done: 19355 summary file(s) moved, manifest moved
removed empty /mnt/hardisk/NotAnotherSpotlight/Test Summaries
```

Idempotent — safe to re-run. Refuses to overwrite if the target already
has data. JSON-validates the manifest before moving so a corrupt source
file can't poison the destination.

## Files touched

| File | Change |
|---|---|
| [pyproject.toml](../pyproject.toml) | Added `platformdirs>=4.0` |
| [src/manifest.py](../src/manifest.py) | Added `APP_DATA_DIR`, kept `REPO_ROOT` as alias |
| [src/answer.py](../src/answer.py) | Imports `APP_DATA_DIR` instead of redefining |
| [src/server.py](../src/server.py) | Imports `APP_DATA_DIR` instead of redefining |
| [src/pipeline.py](../src/pipeline.py) | Uses `SUMMARIES_DIR` instead of hardcoded `"Test Summaries"` |
| [src/ingest/common.py](../src/ingest/common.py) | Imports `APP_DATA_DIR` from manifest |
| [src/stage1/summarize.py](../src/stage1/summarize.py) | Imports `APP_DATA_DIR` from manifest |
| [src/ingest/common.py:write_summary](../src/ingest/common.py) | `mkdir(parents=True, exist_ok=True)` so a fresh user with no `~/.local/share/Magpie/` directory works |
| [src/stage1/summarize.py:write_summary_at](../src/stage1/summarize.py) | Same `mkdir(parents=True)` fix |
| [src/stage3/index.py](../src/stage3/index.py) | Same `mkdir(parents=True)` fix |
| [src/manifest.py:save](../src/manifest.py) | Same `mkdir(parents=True)` fix |
| [scripts/migrate_data.py](../scripts/migrate_data.py) | New — one-shot legacy → APP_DATA_DIR mover |

Tests: 409 passing.

## What stays unchanged (deliberately)

- All public function signatures
- The CLI's behavior (`ns ask`, REPL, dot-commands, suggestions — pixel-identical)
- Test scripts that genuinely mean "the git repo" (`tests/run_pipeline_eval.py`,
  `tests/ReceiptQA_test.py` — those keep their local `REPO_ROOT = Path(__file__).resolve().parent.parent`
  for finding test fixtures like `Test Content/`)
- The contract that source-document paths in the manifest may be either
  repo-relative or absolute (already supported by the existing `if not
  rel.startswith("/")` branch)

## What this unlocks

- **Desktop packaging** (Phase 3): Windows / macOS installers can ship
  to users without assuming any repo layout. The .exe runs anywhere.
- **Multiple tools sharing one corpus**: future CLI + GUI on the same
  machine read/write the same data. Today both already do, just from
  the portable location.
- **Test isolation**: any pytest run can set `MAGPIE_DATA_DIR=/tmp/...`
  and never touch the user's real corpus. Used by 13+ test files in the
  current suite.

## What didn't change but should next

- **Qdrant collection storage** — still in `<repo>/qdrant_data/`. Should
  move to `APP_DATA_DIR/qdrant/` in a follow-up. Not blocking Phase 2/3
  because Qdrant is mostly served by an external `just qdrant-up`
  process, but cleanest to consolidate.
- **HuggingFace model cache** — currently uses HF's own default
  (`~/.cache/huggingface/hub/`). For a sealed-installer deployment,
  redirect HF cache to `APP_DATA_DIR/hf-cache/` via `HF_HOME` env var
  set at app startup.

## Cross-references

- [src/manifest.py](../src/manifest.py) — source of truth for `APP_DATA_DIR`
- [scripts/migrate_data.py](../scripts/migrate_data.py) — one-shot data migration
- [IO - Repo Structure.md](IO%20-%20Repo%20Structure.md) — why this lives in `src/manifest.py` and not in a separate config module
- [IO - Phase 2.md](IO%20-%20Phase%202.md) — the work that builds on this
- [platformdirs PyPI](https://pypi.org/project/platformdirs/) — the cross-platform path library
