# Windows (and cross-platform) shipping fix

## What broke and why

The installed `magpie.exe` in `C:\Program Files\Magpie` crashed on launch with:

```
Failed to setup app: error encountered during setup hook: program not found
```

**Root cause**: `spawn_sidecar()` in `lib.rs` called `Command::new("uv")` — the Python
package manager — to start the FastAPI backend. On an end-user's machine `uv` is not
installed, so Windows returned "program not found" before the app could show any UI.

Secondary issues found at the same time:

| File | Problem |
|---|---|
| `lib.rs` | `python3` command doesn't exist on Windows (it's `python`) |
| `server.py` `/open`, `/reveal` | Used `open` / `open -R` — macOS-only shell commands |
| `tauri.conf.json` | Targets were `["app", "dmg"]` — macOS only, no Windows installer |
| `Cargo.toml` | `window-vibrancy` compiled on all platforms, only needed on macOS |

---

## The fix: PyInstaller sidecar

Instead of requiring `uv` + Python + all ML deps on the user's machine, we compile
the entire Python backend into a self-contained binary using PyInstaller.

```
User installs magpie-setup.exe
  └─ C:\Program Files\Magpie\
       ├─ magpie.exe               ← Tauri shell (Rust)
       └─ magpie-sidecar.exe       ← PyInstaller bundle (Python + FastAPI + all deps)
```

No Python. No uv. No source code. Just two executables.

---

## Files changed

### `frontend/src-tauri/src/lib.rs`

`spawn_sidecar()` now takes `&tauri::AppHandle` so it can resolve the resource dir.

- **Dev builds** (`debug_assertions`): still uses `uv run python -m src.server` so
  Python changes don't require a Tauri rebuild. `python` (not `python3`) works on
  all platforms with uv.
- **Release builds**: resolves `magpie-sidecar[.exe]` from Tauri's resource directory
  (where `externalBin` files land after bundling) and spawns it directly.

### `src/server.py`

`/open` and `/reveal` endpoints now branch on `sys.platform`:

| Platform | `/open` | `/reveal` |
|---|---|---|
| `win32` | `os.startfile()` | `explorer /select,<path>` |
| `darwin` | `open <path>` | `open -R <path>` |
| Linux | `xdg-open <path>` | `xdg-open <parent>` |

### `frontend/src-tauri/tauri.conf.json`

- `"targets": "all"` — Tauri picks the right installer format per OS automatically
  (NSIS on Windows, DMG/app on macOS, deb/AppImage on Linux)
- `"externalBin": ["binaries/magpie-sidecar"]` — tells Tauri to bundle the sidecar.
  At build time Tauri looks for the file with the current target triple appended:
  `binaries/magpie-sidecar-x86_64-pc-windows-msvc.exe` etc.
- Added `icons/icon.ico` for Windows installer

### `frontend/src-tauri/Cargo.toml`

`window-vibrancy` moved to `[target.'cfg(target_os = "macos")'.dependencies]`.
The code was already guarded with `#[cfg(target_os = "macos")]`; now the crate
isn't even compiled on Windows/Linux.

### `pyproject.toml`

`pyinstaller>=6.0` added to `dev` dependency group — only needed by developers
building the app, not by end users or the Python library.

---

## How to build a release

PyInstaller **cannot cross-compile** — you must run the sidecar build on the target OS.

### Step 1 — build the sidecar (on the target machine)

```bash
uv run python scripts/build_sidecar.py
# or: just build-sidecar
```

This produces (in `frontend/src-tauri/binaries/`):

| OS | File |
|---|---|
| Windows | `magpie-sidecar-x86_64-pc-windows-msvc.exe` |
| macOS ARM | `magpie-sidecar-aarch64-apple-darwin` |
| macOS x86 | `magpie-sidecar-x86_64-apple-darwin` |
| Linux | `magpie-sidecar-x86_64-unknown-linux-gnu` |

### Step 2 — build the Tauri installer

```bash
cd frontend && pnpm tauri build
# or from project root: just build-app
```

Or both steps at once:
```bash
just build
```

Output:
- Windows: `frontend/src-tauri/target/release/bundle/nsis/magpie_*_x64-setup.exe`
- macOS: `frontend/src-tauri/target/release/bundle/dmg/Magpie_*.dmg`
- Linux: `frontend/src-tauri/target/release/bundle/deb/magpie_*.deb`

---

## Dev mode (no build needed)

```bash
just dev
# or: cd frontend && pnpm tauri dev
```

Tauri spawns the Python server automatically via `uv run python -m src.server`.
Requires `uv` installed and `uv sync` run from the project root.

---

## Known limitations

### PyInstaller binary size
The sidecar will be **400 MB – 1.5 GB** depending on which ML deps are active
(`sentence_transformers`, `fastembed`, `colpali_engine` pull in large torch/ONNX
weights). This is expected — all deps are baked in.

### Cold-start time (~2–5 s on first launch)
PyInstaller `--onefile` extracts itself to a temp directory on first run. Subsequent
launches reuse the extracted cache and are faster. This is a one-time penalty per
app update.

### PyInstaller hidden imports need tuning
If the sidecar crashes at runtime with `ModuleNotFoundError`, a lazy import was
missed. Add it to `scripts/build_sidecar.py` under `--hidden-import` and rebuild.

### Windows dependencies shipped by Tauri's NSIS installer
Tauri's NSIS bundler automatically handles:
- WebView2 runtime (bootstrapped on install if missing)
- MSVC redistributable (bundled)

No manual action needed.

---

## UX behaviour changes (windows-app branch)

### Window no longer auto-hides on blur
The `tauri://blur` hide handler and the `pointerdown`-outside handler were removed
because they caused the window to vanish while the native folder-picker dialog was
open (the dialog steals focus, firing a blur before the user could pick a folder).

**Current behaviour:** only `Escape` hides the window.

**Correct fix (not yet done):** suppress blur-hide with a flag while the picker is
in flight, then restore it. Removes the regression without breaking the picker flow.

### Re-summon preserves state
`tauri://focus` no longer calls `reset()`. Alt+Space brings the window back with the
previous query and answer still visible. The old `reset()` callback has been deleted.

### Backspace-to-dismiss
Clearing the input field (backspacing to empty) collapses the answer card and returns
to the management card. The answer stays visible while the user is composing a new
query; only a fully empty input counts as a dismiss.

Implemented as a `useEffect` on `query` in `MagpieWindow.tsx`:
```ts
useEffect(() => {
  if (query === "") {
    setResult(null);
    setSubmitted(null);
    setSelectedPath(null);
    setError(null);
  }
}, [query]);
```

### Global shortcut: dynamic picker + persistence
`Alt+Space` is the default. If it is already registered by another app, a dialog
offers `Alt+Q`, `Ctrl+Space`, `Ctrl+Alt+Space` in sequence. The chosen shortcut is
saved to `<APP_DATA>/shortcut.json` and reused on next launch.

### Single-instance enforcement
`tauri-plugin-single-instance` intercepts a second launch, focuses the existing
window (re-anchored to center-top), and shows a dialog that names the actual
registered shortcut (read from `shortcut.json`, not hardcoded).

### Management card always visible
The index-management card (`MagpieWindow.tsx`) is shown whenever the query result
area is not active — not only on first launch. States:

| State | Content |
|---|---|
| Indexing | Progress bar + current file + elapsed + Stop button |
| Error | Error message + Try again |
| Done / stopped | Confirmation message + Re-index button |
| Nothing indexed | Onboarding prompt + Select folder button |
| Idle (has files) | Re-index button |

**Re-index** uses the last indexed folder path if one is known; otherwise opens the
folder picker (same as first-time flow). `lastFolder` is held in React state and
resets when the app restarts.

### Qdrant flush on stop
`ingest_from_manifest` is now always called after `run_batch` completes, even when
the user hits Stop. Previously stopping skipped the final Qdrant push, leaving up
to 100 summarised files unsearchable. The `stopped` flag is still set for UI feedback.
