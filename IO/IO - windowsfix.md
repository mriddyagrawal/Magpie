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
