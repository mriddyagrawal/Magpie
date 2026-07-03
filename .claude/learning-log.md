# Magpie / NotAnotherSpotlight — Setup & Learning Log

> A running journal of what we set up, why, and what the code means.
> Rahul is the product owner and does **not** know Rust — so Rust (and any
> unfamiliar code) is explained bit by bit. After each explanation I record
> an **Understanding score (1-5)** based on Rahul's follow-up responses, so
> we can see comprehension trend over time.
>
> Scale:
> - **1** = "no idea what that means"
> - **2** = follows the what, not the why
> - **3** = gets it with the explanation in front of them
> - **4** = can restate it in their own words
> - **5** = could read a similar snippet unaided
>
> Each entry ALSO gets a **Satisfaction score (1-5)**, inferred from Rahul's
> tone/response (1 = frustrated/blocked, 3 = neutral, 5 = clearly pleased /
> momentum). Both scores are read from his *next* message after each answer.
>
> **Convention: this log is APPEND-ONLY and ever-growing.** Every assistant
> response gets a new numbered entry at the bottom; every change to a Rust
> (`.rs`) file gets its own "Rust change" entry with a before/after and a
> plain-English explanation. Old entries are never edited or deleted — we
> only add. This way the whole learning trail stays intact.

---

## Session 2026-07-02 — Windows dev environment from scratch

### Machine state at start
- ✅ `uv` (Python package manager) installed, `.venv` populated
- ✅ `frontend/node_modules` present
- ❌ git, bash, node/pnpm-on-PATH, Rust/cargo, Qdrant binary — all missing
- ❌ folder was not a git repo

### What we did (in order)
1. **Downloaded Qdrant** (the vector database, 79 MB) via the cross-platform
   `scripts/download_qdrant.py` → `frontend/src-tauri/binaries/qdrant-x86_64-pc-windows-msvc.exe`.
   (Did NOT use `just qdrant-install` — that recipe is Mac/Linux-only.)
2. **Installed Git for Windows** via winget → gives both `git` and `bash`
   (bash is required because the `justfile` runs recipes through it).
3. **Installed Node LTS + pnpm** via winget (for the Tauri desktop app).
4. **Installed Rust (`rustup`/`cargo`) + MSVC C++ Build Tools** — Tauri is a
   Rust app; the desktop shell won't compile without them.
5. **Started Qdrant** on port 6333 (matches `.env`) with an explicit
   `config.yaml` because the Windows download only extracted the `.exe`,
   not Qdrant's default config folder.
6. **Created an empty stub** `binaries/magpie-sidecar-x86_64-pc-windows-msvc.exe`
   so Tauri's build validation passes (see Rust note below for why it's safe).

### Key facts about this project's config
- `.env` → `LLM_PROVIDER=openrouter` (key present), `QDRANT_CLUSTER_ENDPOINT=http://localhost:6333`.
- `.env` is gitignored (line 4) — secrets never get committed. ✅
- The code ignores `QDRANT_PROVIDER`; only `QDRANT_CLUSTER_ENDPOINT` matters,
  and it must be a localhost URL (`src/stage2/db.py`).
- For CLI search you need **none** of node/pnpm/Rust — only Qdrant + `uv`.

---

## Rust note #1 — why the empty sidecar stub is safe

File: `frontend/src-tauri/src/lib.rs`, function `spawn_sidecar` (~line 575).

```rust
let mut cmd = if cfg!(debug_assertions) {
    // DEV build: run the Python backend straight from source
    let repo_root = concat!(env!("CARGO_MANIFEST_DIR"), "/../..");
    let mut c = Command::new("uv");
    c.current_dir(repo_root);
    c.args(["run", "python", "-m", "src.server", "--port", &port.to_string()]);
    c
} else {
    // RELEASE build: run the pre-compiled magpie-sidecar.exe instead
    ...
};
```

- `cfg!(debug_assertions)` is **true in dev** (`pnpm tauri dev`), false in a
  release build. So the `if` branch runs during development.
- The dev branch runs `uv run python -m src.server` — i.e. the **real Python
  backend from source**. It never touches the `magpie-sidecar.exe` file.
- The bundled `.exe` is only used in the `else` (release) branch.
- ⇒ The stub file only needs to *exist* so Tauri's build check passes; it is
  never executed in dev. Hence an empty file is fine.

**Understanding score:** _(pending Rahul's response)_

---

## Entry log (append-only)

### Entry #1 — 2026-07-02 — "where do I run the stub command?"
- **Context:** Rahul unsure where to paste the `$stub = ...` PowerShell command.
- **Answer given:** It uses an **absolute path** (`c:\...`), so it can be run
  from any folder — no `cd` needed. Use the terminal where `pnpm tauri dev`
  failed, then re-run `pnpm tauri dev`.
- **Taught (bit by bit):** PowerShell `$variable`, `Test-Path`, `-not`,
  `New-Item -ItemType File`, the `|` pipe, `Out-Null`. Plain English:
  "if the stub file isn't there, make an empty one, quietly."
- **Requested from Rahul:** understanding score for (a) the PowerShell
  breakdown and (b) the Rust `cfg!(debug_assertions)` idea.
- **Understanding score:** _(pending)_

### Entry #2 — 2026-07-02 — log format changed to append-only
- **Change:** Rahul asked for an ever-growing log — one entry per response and
  per Rust-file change, never overwritten. Added the "APPEND-ONLY" convention
  note at the top of this file. No code/`.rs` changes this entry.
- **Understanding score:** n/a (process change, not a lesson).

### Entry #3 — 2026-07-02 — Rust compiled; Vite watcher crash (EBUSY)
- **Result:** Rust build succeeded (reached `467/469: magpie`) → the stub +
  MSVC + cargo all work. New failure was NOT Rust.
- **Error:** `EBUSY: resource busy or locked, watch '...target\debug\deps\magpie_lib.dll'`
- **Cause:** Tauri's `beforeDevCommand` starts Vite, which watches files for
  hot-reload. Its watcher recursed into `src-tauri/target/` (the Rust build
  output). Windows locks a `.dll` while the linker is still writing it, so
  Vite's watcher hit a locked file and crashed the whole process.
- **Fix (code change, `frontend/vite.config.ts`):** added
  `server.watch.ignored: ["**/src-tauri/**"]` so Vite never watches the Rust
  build output.
  ```ts
  // before
  server: { port: 1420, strictPort: false, host: "127.0.0.1" },
  // after
  server: {
    port: 1420, strictPort: false, host: "127.0.0.1",
    watch: { ignored: ["**/src-tauri/**"] },
  },
  ```
- **Also answered:** the sidecar stub is NOT recreated every run — it's a real
  file that persists. You only recreate it if `frontend/src-tauri/binaries/`
  gets wiped (it's gitignored, so a fresh `git clone` won't have it).
- **Understanding score:** _(pending)_

### Entry #4 — 2026-07-02 — added Satisfaction score to the rubric
- **Change:** Rahul asked that each entry also carry a **Satisfaction score**
  inferred from his next message, alongside the Understanding score. Updated
  the rubric at the top of this file. From here on both scores are filled in
  based on his response following each answer.
- **Read from his message:** he is engaged and directing the process actively
  (asking for scoring, wanting to learn) — no frustration signals, steady
  momentum. Prior technical answers not yet explicitly rated by him.
- **Understanding score:** n/a (process change)
- **Satisfaction score:** 4/5 (engaged, giving clear process direction; not a
  raw "this is great" but no friction — inferred, will refine on next reply)

### Entry #5 — 2026-07-02 — settings white screen: diagnose before forking
- **Rahul's request:** settings window is a white screen in the Tauri app
  (works in browser); he proposed writing a **completely separate Windows base**
  for settings, leaving macOS as-is.
- **Pushback (co-founder):** There is NO separate Mac/Windows settings code.
  Both windows load the SAME `index.html` (`WebviewUrl::default()`); the only
  difference is an injected JS flag `window.__MAGPIE_WINDOW_TYPE__='settings'`
  (`lib.rs:638`) that `App.tsx:11` reads to render `<SettingsWindow>` vs
  `<MagpieWindow>`. So the white screen = `<SettingsWindow>` **throwing during
  render** inside WebView2 (no React error boundary ⇒ one throw blanks the
  whole window). Forking would duplicate code forever and NOT fix the bug.
- **Rust change (`lib.rs`, `open_settings_internal`):** capture the built
  window and, in **debug only**, open its DevTools so we can read the console
  error. Cross-platform, compiled out of release. macOS behavior unchanged.
  ```rust
  // before
  let _ = WebviewWindowBuilder::new(app, "settings", WebviewUrl::default())
      ...
      .build();
  // after
  let built = WebviewWindowBuilder::new(app, "settings", WebviewUrl::default())
      ...
      .build();
  #[cfg(debug_assertions)]
  if let Ok(win) = &built { win.open_devtools(); }
  ```
- **Next:** rebuild (tauri dev auto-recompiles on .rs change), open Settings,
  read the red console error, paste it back → then we fix the real throw.
- **Understanding score:** _(pending)_
- **Satisfaction score:** _(pending — watching for frustration vs. relief that
  we avoided a big rewrite)_

### Entry #6 — 2026-07-02 — dedicated settings entry point (Rahul's "fork", done clean)
- **New info from Rahul:** bug has persisted a while; DevTools/Inspect shows
  NOTHING (no console error). He is **very frustrated** and leaning toward a
  full fork. → A white screen with no thrown error means the shared
  `index.html` + injected-global (`__MAGPIE_WINDOW_TYPE__`) pattern is failing
  to render anything in the 2nd WebView2 webview — a fragile pattern, not a
  Mac/Windows logic split.
- **Decision:** honor the "fork" instinct but done right — a **separate HTML
  entry point** for Settings that renders the EXISTING `SettingsWindow`
  component directly. Zero React-logic duplication, cross-platform, and it
  removes the init-script race. Bonus: settings UI now openable in a browser
  at `localhost:1420/settings.html`.
- **Changes:**
  1. NEW `frontend/src/settings-main.tsx` — mounts `<SettingsWindow>` directly.
  2. NEW `frontend/settings.html` — loads `/src/settings-main.tsx`.
  3. `frontend/vite.config.ts` — added `build.rollupOptions.input` with `main`
     + `settings` HTML entries.
  4. **Rust (`lib.rs`)** — settings window URL changed:
     ```rust
     // before
     WebviewWindowBuilder::new(app, "settings", WebviewUrl::default())
     // after
     WebviewWindowBuilder::new(app, "settings", WebviewUrl::App("settings.html".into()))
     ```
     `WebviewUrl::App(path)` loads a specific frontend page (dev: devUrl +
     `/settings.html`; prod: bundled `settings.html`) instead of the shared root.
- **Next:** restart `pnpm tauri dev` (frontend HMR won't pick up a new HTML
  entry or vite.config change — needs a full restart), open Settings.
- **Understanding score:** _(pending)_
- **Satisfaction score:** _(pending)_

### Entry #7 — 2026-07-02 — settings.html works in browser; localhost theory DISPROVEN by Rahul
- **Evidence from Rahul:** browser renders BOTH `127.0.0.1:1420/settings` and
  `localhost:1420/settings.html` correctly (skeleton loaders + "Starting…" —
  expected, browser has no sidecar port injected). Tauri settings window still
  pure white. He rejected my `devUrl → 127.0.0.1` edit — correctly, since
  localhost resolves fine in the browser.
- **What this proves:** the new settings.html entry point is GOOD (renders in
  browser). The failure is specific to the **WebView2 webview**, not the React
  code, not the URL path. Remaining suspects: (a) app didn't actually rebuild
  with the new Rust (devtools should have auto-opened — did they?), (b) WebView2
  GPU/hardware-acceleration rendering blankness (common on RDP/VMs/some Intel
  drivers — window chrome native, web content white), (c) webview loading a
  different URL than we think.
- **Understanding score:** 4/5 — he independently tested both hostnames and
  used the result to reject a hypothesis with evidence. That's reading the
  system, not just following steps.
- **Satisfaction score:** 2/5 — explicitly "very frustrated"; long-standing
  bug, two fixes haven't landed yet. Priority: facts before more edits.

### Entry #8 — 2026-07-02 — ROOT CAUSE FOUND: Windows webview-creation deadlock (wry#583)
- **Decisive facts from Rahul:** (1) DevTools never auto-opened; (2) settings
  window is white AND frozen — can't even close it without killing the app;
  (3) same failure on a SECOND Windows machine; (4) all fine on macOS;
  (5) main spotlight bar renders + is fully interactive in the app.
- **Diagnosis:** documented Tauri/Windows bug (wry#583). All settings-open
  paths (command handler, tray click) run on the MAIN thread. On Windows,
  creating a webview window there deadlocks: the native frame is created,
  but WebView2 initialization needs the main thread to pump messages — and
  the main thread is blocked inside the create call. So the webview never
  initializes → white, unclosable, no console, no devtools (nothing exists
  to inspect). Main window is unaffected because it's built during setup()
  where the pattern is safe. macOS WKWebView initializes differently → works.
- **Why NOT a separate Windows settings codebase:** the deadlock is in the
  Rust window-OPENING path. Any new UI would be opened through the same call
  and freeze identically. Fork = weeks of duplicate code, same white screen.
- **Rust change (`lib.rs`, `open_settings_internal`):** wrap the entire
  `WebviewWindowBuilder...build()` (+ debug devtools call) in
  `std::thread::spawn(move || { ... })` with a cloned `AppHandle`, so the
  window is built from a background thread and `.build()` dispatches to the
  free main event loop. Safe on both platforms; macOS behavior unchanged.
- **New Rust concepts:** `app.clone()` (cheap handle copy), `std::thread::spawn`
  (run this closure on a new OS thread), `move ||` (closure takes ownership
  of the variables it uses — required when the closure outlives the caller).
- **Understanding score:** _(pending — will read from his reply)_
- **Satisfaction score:** 2/5 at entry time (still frustrated, pushing for the
  fork) — expecting a jump if this fix lands.

### Entry #9 — 2026-07-02 — ✅ SETTINGS FIXED on Windows
- **Result:** After the `std::thread::spawn` fix, the settings window renders
  the full UI on Windows, DevTools auto-opened (proof the webview initialized),
  and the window closes normally. Root cause confirmed: main-thread webview
  creation deadlock (wry#583) — NOT a Mac-vs-Windows UI code problem. The
  "separate Windows settings base" fork is officially unnecessary.
- **Cleanup:** removed the debug DevTools auto-open; replaced with an
  `eprintln!` on window-build error (so future failures are loud in the
  terminal instead of silent).
- **New Rust taught:** `if let Err(e) = &built { ... }` — pattern-match "did
  this Result fail? if so bind the error as `e`" — Rust's version of checking
  an error code, enforced by the compiler.
- **Rahul's question:** main spotlight bar hides when settings opens; is it on
  purpose? → Yes-ish: documented behavior is "Magpie hides whenever the window
  loses focus" (Spotlight-style). Opening settings steals focus → bar hides.
  By design, but arguably wrong UX when focus went to Magpie's OWN settings
  window. Candidate polish: don't hide when focus moves to another Magpie window.
- **Understanding score:** 3/5 (followed the fix + result; scores for
  clone/thread::spawn/move still unrated by him)
- **Satisfaction score:** 4/5 — "ok now the settings work" + immediately
  moved to UX polish question = relief + forward momentum after deep frustration.

