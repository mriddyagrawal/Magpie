# IO - Dist: Distribution & Build System

> **What this doc covers.** Every change made to the PyInstaller sidecar build,
> the Qdrant binary bundling, the Tauri capability config, and the Rust process
> spawning layer — from the first Windows crash through to the current state.
> Read this before touching `scripts/build_sidecar.py`, `magpie-sidecar.spec`,
> `scripts/download_qdrant.py`, or `lib.rs`'s spawn functions.

---

## Architecture recap

```
User installs Magpie_0.1.0_x64-setup.exe (NSIS)
  └─ C:\Users\<user>\AppData\Local\Magpie\
       ├─ Magpie.exe                  ← Tauri shell (Rust, GUI subsystem)
       ├─ magpie-sidecar.exe          ← PyInstaller bundle (Python + FastAPI + ML deps)
       └─ qdrant.exe                  ← Qdrant vector DB (pre-built Rust binary)
```

On launch:
1. `Magpie.exe` pre-picks two free TCP ports (one for qdrant, one for the sidecar)
2. Both are spawned in a background thread — the window appears immediately
3. The frontend polls `/healthz` to detect when the sidecar is ready

---

## PyInstaller sidecar (`scripts/build_sidecar.py` + `magpie-sidecar.spec`)

### Problem 1 — `logfire` crashes at import time in frozen bundles

**Symptom:**
```
OSError: could not get source code
[PYI-416:ERROR] Failed to execute script 'server' due to unhandled exception!
```

**Root cause:** `pydantic-ai` pulls in `logfire` as a transitive dependency.
`logfire`'s pydantic plugin calls `inspect.getsource()` on `PluggableSchemaValidator`
when pydantic constructs its schema (i.e. when `fastapi` is first imported).
In PyInstaller frozen bundles, source files are not on disk, so
`inspect.getsource()` raises `OSError`.

The env var `LOGFIRE_PYDANTIC_PLUGIN_RECORD=off` (already in `server.py`) only
controls what logfire logs — it does NOT prevent `inspect.getsource()` from being
called during the validator patching phase.

**Fix (`src/server.py`):** Monkey-patch `inspect.getsource` before any imports
in frozen builds:

```python
os.environ.setdefault("LOGFIRE_PYDANTIC_PLUGIN_RECORD", "off")
if getattr(sys, "frozen", False):
    import inspect as _inspect
    _real_getsource = _inspect.getsource
    def _safe_getsource(obj):
        try:
            return _real_getsource(obj)
        except OSError:
            return ""
    _inspect.getsource = _safe_getsource
```

This must happen before `from fastapi import FastAPI`.

---

### Problem 2 — `genai_prices` crashes on `importlib.metadata.version()`

**Symptom:**
```
importlib.metadata.PackageNotFoundError: No package metadata was found for genai_prices
```

**Root cause:** `genai_prices/__init__.py` calls
`importlib.metadata.version('genai_prices')` at import time to read its own
package version. `genai_prices` is pulled in by `pydantic_ai` → `messages.py`.
PyInstaller strips `.dist-info` directories by default, so the metadata lookup
finds nothing.

**Fix:** Add `--copy-metadata` flags to the build command and the spec file.

`scripts/build_sidecar.py`:
```python
"--copy-metadata", "genai_prices",
"--copy-metadata", "pydantic_ai",
```

`magpie-sidecar.spec`:
```python
from PyInstaller.utils.hooks import collect_all, copy_metadata
datas += copy_metadata('genai_prices')
datas += copy_metadata('pydantic_ai')
```

`pydantic_ai` is added proactively — same pattern, same risk.

---

### Problem 3 — CMD window visible to end users

**Symptom:** Two terminal/CMD windows open alongside the app on Windows.

**Root cause:**
- The sidecar was built with `console=True` (PyInstaller default) — Windows
  allocates a console for it even though it's a background HTTP server.
- `qdrant.exe` is a native console binary and also spawns a window.

**Fix:**

`magpie-sidecar.spec`:
```python
console=False,  # was True
```

`scripts/build_sidecar.py`:
```python
"--noconsole",   # added before --noconfirm
```

`lib.rs` — suppress qdrant's window on Windows:
```rust
#[cfg(windows)]
{
    use std::os::windows::process::CommandExt;
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
}
```

`--noconsole` / `console=False` makes the sidecar a Windows GUI subsystem
binary. Stderr still flows to Tauri's own stderr in dev mode (`Stdio::inherit()`),
so logging is preserved during development.

---

### Hidden imports

Modules that are lazy-imported inside endpoint functions (i.e. not at the top
of `server.py`) must be listed explicitly, otherwise PyInstaller's static
analysis misses them and they are absent from the bundle.

Current hidden imports in `build_sidecar.py` and `magpie-sidecar.spec`:

| Module | Reason |
|---|---|
| `uvicorn.logging` | Uvicorn loads its subsystems dynamically |
| `uvicorn.loops.auto` | Same |
| `uvicorn.protocols.http.auto` | Same |
| `uvicorn.protocols.websockets.auto` | Same |
| `uvicorn.lifespan.on` | Same |
| `src.pipeline` | Lazy-imported inside `/query` handler |
| `src.content` | Lazy-imported in preview handlers |
| `src.stage2.db` | Lazy-imported in `/status` |
| `src.stage2` | Pulled in by stage2.db |
| `src.stage2.__main__` | Called by `/ingest` → `ingest_from_manifest` |
| `src.stage1` | Pulled in transitively |
| `src.manifest` | Used by multiple lazy paths |
| `src.ingest` | `/ingest` endpoint — walks a folder |
| `src.ingest.walker` | Core walk logic |
| `src.ingest.common` | Used by walker |
| `src.ingest.ignore` | Used by walker |
| `src.router` | Used by walker |

**Rule:** If the sidecar crashes at runtime with `ModuleNotFoundError: No module
named 'src.X'`, a new hidden import is needed. Add it to both `build_sidecar.py`
and `magpie-sidecar.spec` and rebuild.

---

### `collect_all` packages

These packages use dynamic imports, C extensions, or carry non-Python assets
(ONNX models, tokenizer configs) that PyInstaller's static analysis can't
discover automatically:

```python
collect_all('sentence_transformers')
collect_all('fastembed')
collect_all('qdrant_client')
collect_all('pymupdf')
```

`collect_all(pkg)` is equivalent to `--collect-all pkg` on the command line and
pulls in data files, binaries, and hidden imports for the package.

---

## Qdrant sidecar (`scripts/download_qdrant.py`)

Qdrant is a pre-built Rust binary downloaded from GitHub Releases at build time.
It is NOT compiled from source.

```
scripts/download_qdrant.py  →  frontend/src-tauri/binaries/qdrant-<triple>[.exe]
```

Tauri's `externalBin` in `tauri.conf.json` bundles it into the installer:
```json
"externalBin": ["binaries/magpie-sidecar", "binaries/qdrant"]
```

At runtime `lib.rs` resolves the binary from the app's resource directory:
```rust
let bin = resource_dir.join(if cfg!(windows) { "qdrant.exe" } else { "qdrant" });
```

**Installer file-lock issue:** The NSIS installer cannot overwrite `qdrant.exe`
while it is running. The fix is to kill the process before re-installing.
From PowerShell: `taskkill /f /im qdrant.exe`. The app should also be closed
from the system tray first.

---

## Tauri Rust spawn layer (`frontend/src-tauri/src/lib.rs`)

### Old design (blocking)

```
setup() {
    spawn_qdrant()     ← blocks up to 15 s waiting for port
    spawn_sidecar()    ← blocks on read_line() for "MAGPIE_PORT="
    create_window()    ← window finally appears
}
```

Total blocking time before window: **5–20 seconds**.

### New design (async startup)

```
setup() {
    pick_free_port() × 2    ← instant (just binds + releases sockets)
    create_window()          ← window appears immediately
    thread::spawn {
        spawn_qdrant()       ← background: start + wait for port
        spawn_sidecar()      ← background: start on pre-picked port
    }
}
```

**Key change:** ports are pre-picked before either process starts.
`window.__MAGPIE_PORT__` is injected into the webview at window creation time,
so the frontend has the correct port immediately. The sidecar receives its port
via `--port <N>` CLI arg and starts listening on it. The frontend polls
`/healthz` every 500 ms to know when the sidecar is ready.

### Spawn function signatures (changed)

Old:
```rust
fn spawn_qdrant(app: &AppHandle, state: State<'_, QdrantState>) -> Result<u16, Box<dyn Error>>
fn spawn_sidecar(app: &AppHandle, state: State<'_, SidecarState>, qdrant_port: Option<u16>) -> Result<u16, Box<dyn Error>>
```

New (no State params, no stdout blocking):
```rust
fn spawn_qdrant(app: &AppHandle, port: u16) -> Result<Child, String>
fn spawn_sidecar(app: &AppHandle, port: u16, qdrant_port: Option<u16>) -> Result<Child, String>
```

Children are stored in managed state directly from the background thread via
`bg.state::<SidecarState>().0.lock().unwrap() = Some(child)`.

The old design read the port from the sidecar's stdout (`read_line()` blocking
on `MAGPIE_PORT=<N>`). The new design passes `--port <N>` to the sidecar so no
stdout protocol is needed. `server.py` still prints `MAGPIE_PORT=` for
compatibility but it is no longer read by Rust.

---

## Tauri capabilities (`frontend/src-tauri/capabilities/default.json`)

Added `"dialog:allow-open"` to enable the native folder picker used by the
onboarding flow. `"dialog:default"` was already present but does not cover
`file().pick_folder()`.

---

## Build commands

```bash
# Download Qdrant binary for current platform (skip if already present)
just download-qdrant

# Compile sidecar (must run on target OS — PyInstaller cannot cross-compile)
just build-sidecar

# Build Tauri installer
just build-app

# All three in sequence
just build
```

Output locations:
| OS | File |
|---|---|
| Windows | `frontend/src-tauri/target/release/bundle/nsis/Magpie_*_x64-setup.exe` |
| macOS | `frontend/src-tauri/target/release/bundle/dmg/Magpie_*.dmg` |
| Linux | `frontend/src-tauri/target/release/bundle/deb/magpie_*.deb` |

---

## Known failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'src.X'` | Missing hidden import | Add to `build_sidecar.py` + spec, rebuild |
| `PackageNotFoundError: No package metadata for X` | Package calls `importlib.metadata.version()` on itself | Add `--copy-metadata X` to build script + spec |
| `OSError: could not get source code` | logfire/pydantic + frozen bundle | The `inspect.getsource` patch in `server.py` covers this; if it recurs for a different package, extend the patch |
| `opened file for writing` (NSIS installer) | `qdrant.exe` or `Magpie.exe` still running | Kill with `taskkill /f /im qdrant.exe` + close app from tray |
| Two CMD windows on launch | Console mode sidecar or qdrant | Covered: `console=False` + `CREATE_NO_WINDOW` |
| Sidecar binary is 400 MB – 1.5 GB | All ML deps baked in by PyInstaller | Expected; no fix without removing deps |
