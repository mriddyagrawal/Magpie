# Phase 3 — Bundle & deploy (Windows .exe)

> **What this doc is.** Frozen-in-time record of the Phase 3 work
> (started 2026-05-03) — turning the dev-mode codebase into a single
> downloadable Windows installer your friends double-click. PyInstaller
> for the Python sidecar, the Qdrant binary as a second sidecar,
> Tauri's externalBin to spawn both, and a GitHub Actions workflow
> that builds it all on a real Windows runner.
>
> Read this when: you're touching anything in `installer/`, the Tauri
> sidecar config, or the GitHub Actions workflow. ALSO read it before
> the next time you need to ship — the iteration log below saves
> hours of "wait, why did that fail?"

---

## What ships and what doesn't

```
Magpie-Setup-0.4.0-beta1.exe   (~500-700 MB)
└── installs to %LOCALAPPDATA%\Programs\Magpie\
    ├── Magpie.exe                          ← Tauri shell
    │
    ├── magpie-sidecar.exe                  ← PyInstaller-bundled Python
    │   (containing torch, transformers, qdrant-client, FastAPI,
    │    sentence-transformers, file extractors — all ~320 MB unpacked)
    │
    ├── qdrant.exe                          ← Qdrant standalone binary
    │   (vendored from qdrant/qdrant GitHub release, ~71 MB)
    │
    └── unins000.exe                        ← uninstaller
```

**NOT in the .exe:**
- The cloud server (lives on fly.io — see [IO - Phase 2.5.md](IO%20-%20Phase%202.5.md))
- The user's documents (stay where they are)
- The local LLM (deferred to v1.1)
- ColPali model (excluded — visual tier deferred)
- ML model weights (downloaded on first run via huggingface_hub)

## Architecture

### Friend's runtime experience

```
Double-click Magpie.exe
    │
    ▼
Tauri shell (Rust) starts
    │
    ├──► spawn qdrant.exe (port 6333, storage in APP_DATA_DIR)
    │    [non-fatal if it fails — embedded fallback in python sidecar]
    │
    ├──► spawn magpie-sidecar.exe
    │    [reads MAGPIE_PORT=<n> from first stdout line]
    │    [LLM_PROVIDER=magpie-cloud baked into env]
    │
    └──► open webview → window.__MAGPIE_PORT__ = <n>
            │
            ▼
       UI sends /query, /status etc. to localhost:<n>
            │
            ▼
       Sidecar handles locally OR phones home to magpie.fly.dev
```

When the user closes the window, the sidecars die with it (OS cleanup).

### Build-time pipeline (CI)

```
push to windows-app
    │
    ▼
GitHub Actions windows-latest runner
    │
    ├──► pip install -e . (CPU-only torch)
    │
    ├──► pyinstaller installer/magpie-sidecar.spec
    │    → dist/magpie-sidecar.exe (~320 MB onefile)
    │
    ├──► download qdrant Windows zip
    │    → qdrant_dl/qdrant.exe (~71 MB)
    │
    ├──► stage both into frontend/src-tauri/binaries/
    │    with the host-triple suffix Tauri expects:
    │      magpie-sidecar-x86_64-pc-windows-msvc.exe
    │      qdrant-x86_64-pc-windows-msvc.exe
    │
    ├──► pnpm install
    │
    ├──► pnpm tauri build --target x86_64-pc-windows-msvc
    │    → bundle/msi/Magpie_0.1.0_x64_en-US.msi
    │    → bundle/nsis/Magpie_0.1.0_x64-setup.exe
    │
    └──► upload artifact "magpie-windows-<sha>"
```

## The PyInstaller spec — load-bearing decisions

Living at [installer/magpie-sidecar.spec](../installer/magpie-sidecar.spec).

### Decision: `--onefile` (single .exe) instead of directory bundle

PyInstaller has two output modes:

| Mode | Output | Runtime |
|---|---|---|
| **Directory** (`COLLECT`) | `dist/magpie-sidecar/magpie-sidecar.exe` + `_internal/` dir of DLLs | Faster startup (no extraction) |
| **Onefile** (single `EXE` with binaries embedded) | `dist/magpie-sidecar.exe` | ~5-10 sec extract on first launch; fast subsequent |

**We use onefile.** The reason: Tauri's `externalBin` config copies a SINGLE file into the bundle. Directory mode would require a separate `resources` config + custom Tauri spawn logic, plus more thought about path resolution. Onefile slots cleanly into externalBin.

The first-launch extraction is acceptable for our use case — Magpie isn't a "open hundreds of times a day" app like a code editor.

### Decision: CPU-only torch

`pip install --index-url https://download.pytorch.org/whl/cpu torch` BEFORE `pip install -e .`.

CUDA torch wheels are ~2 GB on Windows. CPU-only is ~200 MB. Friends don't have GPUs (and even if they did, we don't use GPU acceleration on the desktop side post-Phase 2.5 — ColPali is the only GPU consumer and that's excluded).

### Decision: `colpali_engine` excluded

Deferred to v1.1 along with the local LLM. Saves ~400 MB and a ton of PyInstaller hidden-import wrangling.

### The hidden imports list

ML libraries do `importlib.import_module(...)` at runtime, which PyInstaller's static analysis can't trace. Each missing module surfaces as `ModuleNotFoundError` at sidecar startup. The `HIDDEN_IMPORTS` list grows as we discover them.

Add when you see one in CI logs. Pattern: `ModuleNotFoundError: No module named 'X'` → add `'X'` to the list, push, retry.

Categories currently covered:
- `uvicorn.*` (loops, protocols, lifespan)
- `pydantic.deprecated.*`
- `sentence_transformers.*`
- `transformers.models.bert.*` (MiniLM uses BERT architecture)
- `qdrant_client.*` (REST + gRPC paths)
- `pydantic_ai.*` (provider auto-discovery)
- File extractors (`pypdf`, `pymupdf`, `docx`, `openpyxl`, `pptx`, `trafilatura`, `fastembed`)
- `platformdirs.windows`

### The excludes list

Modules we deliberately drop to shrink the bundle:

| Excluded | Why |
|---|---|
| `torch.cuda`, `torch.distributed`, `torchvision`, `torchaudio` | GPU paths — CPU-only desktop |
| `colpali_engine` | Visual tier — deferred to v1.1 |
| `mlx`, `mlx_vlm`, `mlx_lm` | Apple Silicon-only inference — irrelevant on Windows |
| `pytest`, `ipykernel`, `jupyter`, `notebook` | Dev tools |
| `tkinter`, `matplotlib` | UI/plotting we never use; transitively imported |
| `flask`, `django` | Web frameworks; never used |

These don't *fail* if they slip in — they just bloat the binary. Each one removed shaves 5-50 MB.

### Why `upx=False`

UPX compresses executables but breaks some ML libraries' DLLs. Skip it. Our bundle is fine without it.

## Tauri config — externalBin pattern

Living at [frontend/src-tauri/tauri.conf.json](../frontend/src-tauri/tauri.conf.json).

### Critical: filename suffix

Tauri's externalBin appends the host triple to whatever name you list. So if `tauri.conf.json` says:

```json
"externalBin": ["binaries/magpie-sidecar"]
```

Tauri will look for, on a Windows x86_64 build:

```
binaries/magpie-sidecar-x86_64-pc-windows-msvc.exe
```

**Mismatch is the most common bundling error.** The CI workflow's `Stage external binaries` step renames the files to match this convention.

### NSIS install mode: `currentUser`

```json
"nsis": { "installMode": "currentUser" }
```

NOT `perUser` (invalid in Tauri 2). Valid values: `currentUser`, `perMachine`, `both`. We use `currentUser` so the install doesn't require admin privileges — friend's UAC stays out of the way.

### Targets: `msi` + `nsis` for Windows

`msi` is more reliable for enterprise machines (Windows Installer service); `nsis` is friendlier UX (custom branding, smaller). Producing both and letting friends pick is fine.

## Tauri Rust — dual-sidecar lifecycle

Living at [frontend/src-tauri/src/lib.rs](../frontend/src-tauri/src/lib.rs).

### State

```rust
struct SidecarState {
    python: Mutex<Option<Child>>,
    qdrant: Mutex<Option<Child>>,
}
```

Both children stored in app state so they CAN be killed on app exit (currently relies on OS cleanup — see "Known gaps" below).

### Dev vs release branching

```rust
fn build_python_sidecar_command(resource_dir: &PathBuf) -> Command {
    #[cfg(debug_assertions)]
    {
        Command::new("uv").args(["run", "python3", "-m", "src.server"])
    }
    #[cfg(not(debug_assertions))]
    {
        let exe = resource_dir.join("magpie-sidecar.exe");
        Command::new(exe)
    }
}
```

In dev mode, the desktop sidecar runs via `uv` against the dev environment. In release mode (the bundled .exe), it runs the PyInstaller binary that ships in the install dir.

### Cloud-mode env vars baked in

```rust
.env("LLM_PROVIDER", "magpie-cloud")
.env("MAGPIE_CLOUD_URL", "https://magpie-cloud.fly.dev")
.env("QDRANT_PROVIDER", "cloud")
.env("QDRANT_CLUSTER_ENDPOINT", "http://127.0.0.1:6333")
```

Set on every spawn. The user's invite code is NOT here — it's intended to be sent per-request from the React app's settings store (see Phase 3.10 in "Known gaps").

## GitHub Actions workflow

Living at [.github/workflows/build-windows.yml](../.github/workflows/build-windows.yml).

### Trigger

```yaml
on:
  push:
    branches: [windows-app]
  workflow_dispatch:
```

Every push to the windows-app feature branch. No tags filter for now (added when v1.0 ships).

### Steps in order

1. **Checkout**
2. **Setup**: Python 3.11, Node 20, pnpm 9, Rust stable (with `x86_64-pc-windows-msvc` target)
3. **Cache** Rust build dir (significant — Rust compile is the slowest single step)
4. **`pip install -e .` + pyinstaller** — installs CPU-only torch first, then the project, then PyInstaller
5. **`pyinstaller installer/magpie-sidecar.spec`** — produces the onefile binary
6. **Download Qdrant** — GitHub release download, version pinned via `QDRANT_VERSION` env
7. **Stage external binaries** — copy + rename with host-triple suffix
8. **`pnpm install` + `pnpm tauri build`** — produces `.msi` + `.nsis` installers
9. **Upload installer artifacts** — visible in Actions tab for download

### Total wall-clock (cold cache)

~14-16 minutes per CI run. Slowest steps:
- Rust compile of Tauri + tauri-plugin-* crates: ~6 min
- PyInstaller bundle: ~6 min (much of this is torch DLL collection)
- pip install: ~2 min

See "Faster iteration" below for caching tips.

## Iteration log — failures encountered, fixes applied

When future-you (or a contributor) is debugging a build, check this list before starting from scratch:

| # | Failure | Cause | Fix |
|---|---|---|---|
| 1 | `ERR_PNPM_OUTDATED_LOCKFILE` | Added Tauri plugins to package.json without regenerating lockfile | `cd frontend && pnpm install --lockfile-only`, commit `pnpm-lock.yaml` |
| 2 | `Cargo.lock` out of sync | Same — added Rust crates without updating lockfile | `cd frontend/src-tauri && cargo update --workspace`, commit `Cargo.lock` |
| 3 | `tauri.conf.json` schema error: `installMode: "perUser"` | Wrong NSIS enum value | Changed to `"currentUser"` |
| 4 | YAML linter "Map keys must be unique" | Two `push:` keys under `on:` | Combined into one or simplified to just branches |
| 5 | TypeScript build: "Merge conflict marker encountered" | Leftover `<<<<<<<` markers from `git stash pop` | Manually resolved in MagpieWindow.tsx; pushed clean |
| 6 | Sidecar binary 91 MB instead of expected ~500 MB | PyInstaller produced dir-bundle (`exclude_binaries=True`); CI only copied the launcher .exe | Switched spec to `--onefile` (single self-contained .exe) |
| 7 | Stage step: `dist\magpie-sidecar\magpie-sidecar.exe` not found | After onefile switch, output is `dist\magpie-sidecar.exe` directly | Updated CI staging step's source path |
| 8 | Qdrant zip extracts inconsistently across versions | Some releases nest qdrant.exe in subdir | `Get-ChildItem -Recurse -Filter qdrant.exe` instead of fixed path |
| 9 | `tauri.conf.json` parser: "key must be a string at line 50" | Added `// ...` comments to the JSON file; strict JSON has no comment syntax | Strip all comments; document context in this IO doc instead |

Each entry is a single commit's worth of fix.

## Known gaps — what's NOT in v0.4.0-beta1

### 1. Per-request invite-code header (Phase 3.10 deferred)

Currently the invite code is set via env var at sidecar spawn time. If the user changes their invite code in Settings, the sidecar doesn't see the new code until app restart.

**Future fix**: thread the invite code as `Authorization: Bearer <code>` header on each `/query` request from the React frontend. The sidecar reads it per-request and passes to the cloud agent. Avoids restart UX.

Estimated work: 4 files (api.ts, server.py, pipeline.py, cloud_provider.py), ~2 hours.

### 2. Process cleanup on app exit

When the user closes Magpie, the Tauri shell exits. The Python sidecar and Qdrant child processes get cleaned up by the OS, but not gracefully — they receive SIGKILL on Windows process termination.

**Future fix**: `app.on_window_event(WindowEvent::Destroyed)` handler that calls `child.kill()` on both stored Children before letting the shell die. Lets Qdrant flush its journal cleanly, avoids zombie processes if the OS is slow.

Estimated work: ~30 lines of Rust in lib.rs.

### 3. Code signing

Unsigned binaries trigger Windows SmartScreen ("Windows protected your PC"). Friends will see this on first install — they have to click "More info" → "Run anyway."

**Future fix**: buy a code-signing cert ($200-400/yr from DigiCert / Sectigo / Comodo). Sign the .exe with `signtool sign` in CI before bundling.

Estimated work: ~2 hours of CI config + the cost of the cert.

### 4. macOS + Linux installers

Today only Windows. The codebase is cross-platform; only the build is Windows-specific.

**Future fix**: parallel `build-macos.yml` and `build-linux.yml` workflows. macOS additionally requires Apple Developer Program ($99/yr) for notarization.

Estimated work: ~1 day per platform after Windows is stable.

### 5. Auto-update

Today the user must manually re-download and re-install for updates. Tauri has built-in auto-update support; needs a hosted JSON manifest.

**Future fix**: `tauri-plugin-updater` + a static JSON file on a CDN (could be GitHub Releases). When the app launches, it fetches the manifest, sees a newer version, prompts to update.

Estimated work: ~1 day. Important once we have >20 testers.

### 6. ColPali / visual tier

Excluded from the bundle. The desktop CLI's `.fast on` toggle would crash on the bundled .exe because `colpali_engine` isn't there.

**Future fix**: when v1.1 ships local mode, re-add ColPali to the bundle (will roughly double the installer size to ~1.5 GB). OR offer a separate "advanced installer" with vision support.

## Faster iteration — caching wins

CI cold-cache: 14-16 min. With caching applied, can drop to ~4-6 min:

```yaml
# Cache pip wheels
- name: Cache pip
  uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: pip-${{ runner.os }}-${{ hashFiles('pyproject.toml') }}

# Cache Qdrant download
- name: Cache Qdrant binary
  uses: actions/cache@v4
  with:
    path: qdrant_dl
    key: qdrant-${{ env.QDRANT_VERSION }}-windows

# Cache PyInstaller intermediate analysis
- name: Cache PyInstaller build dir
  uses: actions/cache@v4
  with:
    path: build
    key: pyi-${{ hashFiles('installer/magpie-sidecar.spec', 'pyproject.toml', 'src/**') }}
```

For iteration, also use Tauri debug profile:

```yaml
- name: Build Tauri (debug — fast iteration)
  run: pnpm tauri build --debug
```

Saves ~3-8 minutes per build (skips LTO + opt-level 3 + strip). Switch back to release for actual ship.

## Local pre-flight (catches errors in seconds, not minutes)

Run PyInstaller locally on Linux to catch hidden-import errors before the CI round-trip:

```bash
pip install pyinstaller
pyinstaller installer/magpie-sidecar.spec --noconfirm --clean
# Watch for ModuleNotFoundError → add to spec → re-run
```

Run the Tauri compile locally to catch Rust errors:

```bash
cd frontend
pnpm tauri build --debug
# Catches lib.rs compile errors in ~2 min vs 15 min on CI
```

The Linux .AppImage produced isn't usable visually (no display on TTY), but the build success/failure signal is what matters during iteration.

## Distribution path (Phase 4)

Once the .exe builds clean:

1. **Download artifact** from GitHub Actions run (`magpie-windows-<sha>.zip`)
2. **Test via Wine** on Linux (or a friend's Windows machine, or a Windows VM)
3. **Generate invite codes** — one per friend
4. **Upload .exe** to private GitHub Release OR send via Discord / WeTransfer / Drive
5. **DM each friend** the download link + their unique invite code

Friend's experience:

```
1. Click download link
2. Run Magpie-Setup.exe
3. Click through SmartScreen "Run anyway" (until we get code-signing)
4. Install completes (~30 sec, no admin)
5. Magpie window opens → Settings panel
6. Paste invite code, pick documents folder
7. Wait for indexing
8. Ask questions
```

## Cross-references

- [installer/magpie-sidecar.spec](../installer/magpie-sidecar.spec) — PyInstaller spec
- [.github/workflows/build-windows.yml](../.github/workflows/build-windows.yml) — CI workflow
- [frontend/src-tauri/tauri.conf.json](../frontend/src-tauri/tauri.conf.json) — externalBin + NSIS config
- [frontend/src-tauri/src/lib.rs](../frontend/src-tauri/src/lib.rs) — dual-sidecar lifecycle
- [frontend/src-tauri/Cargo.toml](../frontend/src-tauri/Cargo.toml) — Rust deps (`dirs`, `tauri-plugin-store`, `tauri-plugin-dialog`)
- [frontend/src/components/Settings.tsx](../frontend/src/components/Settings.tsx) — invite code + folder picker UI
- [frontend/src/settings.ts](../frontend/src/settings.ts) — settings persistence
- [IO - Phase 1.md](IO%20-%20Phase%201.md) — portable APP_DATA_DIR (foundation that lets the .exe install anywhere)
- [IO - Phase 2.md](IO%20-%20Phase%202.md) — backend leak-scrub (no tech leaks visible to bundle inspectors)
- [IO - Phase 2.5.md](IO%20-%20Phase%202.5.md) — cloud server (the .exe phones home to it)
- [IO - Repo Structure.md](IO%20-%20Repo%20Structure.md) — why the bundle code lives in the monorepo
- [IO - Privacy.md](IO%20-%20Privacy.md) — what the .exe sends to the cloud and what stays local
