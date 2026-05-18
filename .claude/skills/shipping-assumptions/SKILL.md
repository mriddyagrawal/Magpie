---
name: shipping-assumptions
description: Before writing or recommending any code that will be distributed or run on another person's machine, audit every external dependency, label dev-only solutions, and apply correct cross-platform rules for Windows, macOS, and Linux. Prevents "works on my machine" bugs from reaching end users.
use_when: Any time code, a binary, or an installer will be shipped or run on a machine other than the developer's; any time an external binary or runtime is invoked; any time a build or packaging task targets Windows, macOS, or Linux
user-invocable: false
platforms: windows, macos, linux
---
# Shipping Assumptions

Never build or recommend a solution that only works because of the developer's local environment. Every external binary, runtime, and system dependency the code relies on must be identified, declared, and handled before the work is considered shippable.

## The Core Question

Before writing any code that shells out to an external tool, imports a runtime, or depends on a system service, ask:

> **"Will this work on a clean machine belonging to someone who has never heard of this tool?"**

If the answer is "no" or "maybe" — that dependency must be declared and handled, not assumed.

---

## Step 1: Dependency Surface Audit

When any of the following appear in code being written, flag them immediately as undeclared runtime dependencies:

| Dependency type | Examples | Risk if unhandled |
|---|---|---|
| External binaries | `uv`, `ffmpeg`, `qdrant`, `git`, `curl`, `docker` | "program not found" crash on end-user machines |
| Language runtimes | Python, Node.js, Ruby, Java, .NET | Import errors or silent failures |
| Package managers | `pip`, `npm`, `cargo`, `brew` | Build or install failures |
| System services | PostgreSQL, Redis, Nginx | Connection refused at runtime |
| Native libraries | MSVC Redistributable, libssl, CUDA | Cryptic DLL / `.so` not found errors |
| OS-specific tools | `bash`, `powershell`, `wsl` | Wrong shell or missing interpreter |

For each dependency found, emit:

```
⚠️ UNDECLARED DEPENDENCY: [name]
Used for:            [what the code uses it for]
Bundled?:            [yes | no | partial]
User impact if missing: [exact error they would see]
Resolution:          [bundle it | add installer check | document as prerequisite | use cross-platform alternative]
```

---

## Step 2: Dev vs. Ship Label

Any solution that requires the developer's local setup must be marked in comments before it goes anywhere near a release branch:

```python
# DEV ONLY — requires `uv` installed locally. Not shippable.
# For release: compile to standalone binary with PyInstaller first.
subprocess.run(["uv", "run", "python3", "-m", "src.server"])
```

```rust
// DEV ONLY — assumes Python env is set up in project dir. Not shippable.
// For release: use Command::new_sidecar("magpie-sidecar") with a bundled binary.
Command::new("uv").args(["run", "python3", "-m", "src.server"]).spawn()?;
```

Never leave dev-only code unmarked in a codebase that will be distributed.

---

## Step 3: Cross-Platform Rules

Apply these rules without exception when a task targets more than one OS.

### Path Separators

| Platform | Separator | Home dir |
|---|---|---|
| Windows | `\` | `%USERPROFILE%` / `$env:USERPROFILE` |
| macOS / Linux | `/` | `$HOME` |

Never hardcode a path separator. Use the language's path library:

```python
# ❌ Wrong — breaks on Windows
path = home + "/config/app.json"

# ✅ Right
from pathlib import Path
path = Path.home() / "config" / "app.json"
```

```javascript
// ❌ Wrong
const p = home + '/config/app.json'

// ✅ Right
const p = require('path').join(os.homedir(), 'config', 'app.json')
```

### Shell and Script Differences

| Need | Windows | macOS / Linux |
|---|---|---|
| Run a script | `powershell.exe` or `cmd.exe` | `bash` or `sh` |
| Set env var | `$env:VAR = "value"` | `export VAR=value` |
| Check binary exists | `where.exe ffmpeg` | `which ffmpeg` |
| Kill a process by PID | `taskkill /F /PID [n]` | `kill -9 [n]` |
| List running processes | `tasklist` | `ps aux` |

Write separate commands per platform or use a cross-platform abstraction (`shutil.which` in Python, `execa` in Node).

### Binary Naming and Target Triples

| Platform | Extension | Tauri sidecar suffix example |
|---|---|---|
| Windows x64 | `.exe` | `-x86_64-pc-windows-msvc.exe` |
| macOS Intel | (none) | `-x86_64-apple-darwin` |
| macOS Apple Silicon | (none) | `-aarch64-apple-darwin` |
| Linux x64 | (none) | `-x86_64-unknown-linux-gnu` |

Always include the target triple in distributed binary names. Never assume the build platform matches the target platform.

### Installer and Packaging Formats

| Platform | Preferred format | Tooling |
|---|---|---|
| Windows | NSIS `.exe` or `.msi` | Tauri NSIS, WiX |
| macOS | `.dmg` or `.pkg` | Tauri DMG, `pkgbuild` |
| Linux | `.AppImage`, `.deb`, or `.rpm` | Tauri AppImage, `dpkg`, `rpmbuild` |

Never use a single `"targets": ["app"]` and assume it covers every platform. Declare targets explicitly.

### Runtime Availability Matrix

The safe assumption for any distributed app: **bundle everything you need, or fail gracefully with a clear install prompt.**

| Dependency | Windows | macOS | Linux |
|---|---|---|---|
| Python | ❌ Not present | ⚠️ System Python unreliable | ⚠️ May be 2.x or absent |
| Node.js | ❌ Not present | ❌ Not present | ❌ Not present |
| WebView2 | ⚠️ Pre-installed Win10/11+, absent older | ✅ WKWebView built in | ❌ Must install separately |
| MSVC Redistributable | ⚠️ Usually present Win10/11 | N/A | N/A |
| `bash` | ❌ Not available natively | ✅ | ✅ |
| `curl` | ✅ Win10 1803+ | ✅ | ✅ |
| `git` | ❌ Not bundled | ⚠️ Requires Xcode CLT prompt | ⚠️ Usually present |

---

## Pre-Ship Checklist

Run through this before any code is packaged or distributed:

- [ ] Has a dependency surface audit been run? Are all external binaries and runtimes declared?
- [ ] Is every dev-only code path labeled `# DEV ONLY` with a release alternative noted?
- [ ] Are path separators handled with `pathlib` / `path.join` rather than hardcoded `/` or `\`?
- [ ] Are shell commands written for the correct target OS, or abstracted cross-platform?
- [ ] Are distributed binaries named with the correct target triple?
- [ ] Are installer targets declared explicitly per platform (NSIS / DMG / AppImage)?
- [ ] Has the runtime availability matrix been checked for each target OS?
- [ ] Is there a graceful error or install prompt if a required dependency is missing at runtime?

---

## Anti-Pattern Reference

| Anti-pattern | Why it's harmful | Correct approach |
|---|---|---|
| Shelling out to `uv`, `ffmpeg`, etc. without bundling | "Program not found" crash on end-user machines | Bundle binary or add explicit install check |
| Leaving dev-only code unmarked | Dev solution accidentally shipped to users | Label `# DEV ONLY` with release alternative |
| Assuming Python is available on Windows | It is not — users get a silent crash | Bundle via PyInstaller or similar |
| Using `bash` syntax targeting Windows | Script fails with cryptic error | Use `powershell` or cross-platform abstraction |
| Hardcoding `/` as path separator | Breaks on Windows | Use `pathlib.Path` or `path.join()` |
| Single `"targets": ["app"]` for all platforms | Wrong installer format per OS | Declare NSIS / DMG / AppImage targets explicitly |
| Assuming WebView2 is present on Windows | Absent on older machines | Bundle via Tauri's `webviewInstallMode` |
| Treating "works on my machine" as done | Breaks the moment someone else runs it | Always ask: "does this work on a clean machine?" |