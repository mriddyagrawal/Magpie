# IO - Frontend: Desktop GUI Layer

> **What this doc covers.** The Tauri + React desktop app — window behaviour,
> sidecar communication protocol, UX fixes, onboarding flow, and the Rust
> command layer. Read this before touching anything in `frontend/src/`,
> `frontend/src-tauri/src/lib.rs`, or `src/server.py`'s HTTP surface.

---

## Architecture

```
Tauri shell (Rust, lib.rs)
  ├─ Manages two child processes (qdrant + magpie-sidecar)
  ├─ Injects window.__MAGPIE_PORT__ into the webview at startup
  ├─ Registers global shortcut (Alt+Space) and system tray icon
  └─ Exposes Tauri commands: hide_window, show_window, pick_folder

React frontend (src/)
  ├─ api.ts          ← all HTTP calls to the sidecar + Tauri invocations
  ├─ App.tsx         ← mounts MagpieWindow
  └─ components/
       ├─ MagpieWindow.tsx   ← root state, window resize logic, all effects
       ├─ QuestionCard.tsx   ← search bar + logo
       ├─ AnswerCard.tsx     ← LLM answer display
       ├─ SourcesCard.tsx    ← retrieved sources list
       ├─ PreviewCard.tsx    ← file preview pane
       └─ StatusPill.tsx     ← indexed doc count

FastAPI sidecar (src/server.py)
  ├─ GET  /healthz        ← readiness probe
  ├─ GET  /status         ← indexed_count, ready flag
  ├─ POST /query          ← RAG query
  ├─ GET  /preview        ← file content for preview pane
  ├─ GET  /open           ← open file in OS default app
  ├─ GET  /reveal         ← reveal file in Explorer / Finder
  ├─ POST /ingest         ← start background indexing of a folder
  └─ GET  /ingest/status  ← poll indexing progress
```

---

## Startup sequence

### Old (blocking — window appeared after 5–20 s)

```
setup() → spawn qdrant → wait up to 15 s → spawn sidecar → block on stdout read
        → inject port → window appears
```

### New (non-blocking — window appears in < 1 s)

```
setup()
  ├─ pick_free_port() × 2      [instant]
  ├─ inject window.__MAGPIE_PORT__ + window.__MAGPIE_BOOTING__ = true
  ├─ create + show window      [window visible here]
  ├─ anchor window position
  ├─ register shortcut + tray
  └─ thread::spawn {
         spawn qdrant on pre-picked port
         wait_for_port(qdrant_port, 30 attempts × 500 ms)
         spawn sidecar with --port <sidecar_port>
     }

Frontend
  └─ useEffect: poll GET /healthz every 500 ms
       → on 200: setBooting(false)
       → fetch GET /status
       → if indexed_count === 0: setNeedsIndex(true) → onboarding card
```

**Port protocol change:** The sidecar no longer negotiates its port via stdout.
The Rust layer pre-picks the port with `pick_free_port()`, injects it into the
webview immediately, and passes it to the sidecar via `--port <N>`. The sidecar
still prints `MAGPIE_PORT=<N>` on stdout for CLI debugging, but Rust no longer
reads it. `stdout(Stdio::null())` in release builds.

---

## Window behaviour

### Size states

| State | Height | Trigger |
|---|---|---|
| Compact (idle) | 96 px | No query active |
| Onboarding | 210 px | Sidecar ready + `indexed_count === 0` |
| Expanded | 680 px | Query in flight, result received, or error |

`tauri.conf.json` sets the initial window size to 800 × 96. Tauri's `setSize()`
keeps the top-left corner fixed, so the window always grows downward — no jump.

### Spotlight semantics

- **Alt+Space**: global shortcut. If visible → hide. If hidden → show + anchor + focus input.
- **Esc**: always hides the window and shrinks it back to compact.
- **Click outside `.magpie-card`**: `pointerdown` handler on `document` → hide.
- **`tauri://blur`**: window loses focus to another app → hide (debounced, see below).
- **`tauri://focus`**: window regains focus → `reset()` + focus input.

### Blur debounce (Windows fix)

On Windows, pressing Alt (part of Alt+Space) briefly triggers a blur event at
the OS level before the window finishes appearing. Without debouncing, this
caused the window to appear and immediately vanish.

Fix: 150 ms debounce on the blur handler. If focus returns within 150 ms
(spurious OS blur), the pending hide is cancelled.

```typescript
const unBlur = await appWindow.listen("tauri://blur", () => {
  blurTimer.current = setTimeout(async () => {
    blurTimer.current = null;
    await appWindow.setSize(new LogicalSize(COMPACT_WIDTH, COMPACT_HEIGHT));
    await appWindow.hide();
  }, 150);
});

const unFocus = await appWindow.listen("tauri://focus", () => {
  if (blurTimer.current !== null) {
    clearTimeout(blurTimer.current);
    blurTimer.current = null;
  }
  reset();
  requestAnimationFrame(() => inputRef.current?.focus());
});
```

150 ms is tight enough that a genuine app-switch still hides promptly.

---

## State machine (`MagpieWindow.tsx`)

```
booting  →  ready (booting=false)
              ├─ indexed_count > 0  →  idle (compact bar, ready to search)
              └─ indexed_count = 0  →  onboarding (210 px, folder picker)

idle  →  [user types + Enter]  →  loading  →  result  →  expanded
                                             └─ error   →  expanded (input restored)

expanded (result)  →  [blur / Esc / click outside]  →  reset()  →  idle
expanded (error)   →  [user edits query + Enter]    →  loading again
```

### Error handling fix

Previously: on a failed query, `submitted` (the question text) remained non-null.
`QuestionCard` replaced the `<input>` with a static `<div>` when `submitted !== null`,
locking the user out until they dismissed and re-summoned the window.

Fix: `setSubmitted(null)` in the catch block restores the input immediately.
The error card stays visible (`error !== null` keeps `active = true`), and the
previous query text remains in the input so the user can edit and retry.

```typescript
} catch (e) {
  setError((e as Error).message);
  setResult(null);
  setSubmitted(null); // restore input on error
}
```

---

## Booting state (`QuestionCard.tsx`)

`QuestionCard` accepts a `booting: boolean` prop. When true:
- Input is disabled
- Placeholder shows "Starting Magpie…" instead of "Ask magpie"

This gives visual feedback while the sidecar initialises (typically 2–4 s).

---

## Onboarding flow

Triggered when: sidecar is ready AND `GET /status` returns `indexed_count === 0`.

```
needsIndex=true
  └─ window expands to 210 px
  └─ renders <div class="onboard-card"> below QuestionCard

User clicks "Select folder to index"
  └─ invoke("pick_folder")        ← native OS folder picker via Tauri command
  └─ POST /ingest { path }        ← starts background indexing on sidecar
  └─ poll GET /ingest/status every 1 s
       → running=true : show "Indexing your files…"
       → running=false, done=true : setNeedsIndex(false) → window collapses
       → running=false, error: show error + "Try again" button
```

`needsIndex` is also cleared on the first successful `/query` response, in case
the user indexed via CLI while the app was open.

### Tauri command: `pick_folder`

Added to `lib.rs`. Uses `tauri-plugin-dialog` (already registered) to open a
native folder picker. Returns the selected path as `Option<String>`, or `null`
if the user cancelled.

```rust
#[tauri::command]
async fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    let (tx, rx) = std::sync::mpsc::channel::<Option<tauri_plugin_dialog::FilePath>>();
    app.dialog()
        .file()
        .set_title("Select folder to index")
        .pick_folder(move |folder| { let _ = tx.send(folder); });
    tauri::async_runtime::spawn_blocking(move || {
        rx.recv().ok().flatten().and_then(|p| match p {
            tauri_plugin_dialog::FilePath::Path(path) =>
                Some(path.to_string_lossy().into_owned()),
            _ => None,
        })
    })
    .await
    .unwrap_or(None)
}
```

`tauri::async_runtime::spawn_blocking` bridges the blocking `mpsc::recv()` to
Tauri's async executor without adding `tokio` as an explicit dependency.

---

## Sidecar HTTP API additions

### `POST /ingest`

Starts a background indexing job for a folder. Returns immediately.

```json
Request:  { "path": "C:\\Users\\rahul\\Documents" }
Response: { "status": "started", "path": "C:\\Users\\rahul\\Documents" }
```

Errors: 409 if already running, 400 if path invalid.

Internally: runs `src.ingest.walker.run_batch(folder, push_to_qdrant=True)` in a
`threading.Thread`, then calls `src.stage2.__main__.ingest_from_manifest()`.
`asyncio.run()` is used inside the thread since `run_batch` is an async function.

### `GET /ingest/status`

```json
{
  "running": false,
  "done": true,
  "error": null,
  "path": "C:\\Users\\rahul\\Documents"
}
```

Frontend polls this every 1 s while `running=true`.

---

## API layer (`src/api.ts`)

New functions added:

| Function | Purpose |
|---|---|
| `pickFolder()` | Calls `invoke("pick_folder")` → native folder picker |
| `startIngest(path)` | `POST /ingest` |
| `getIngestStatus()` | `GET /ingest/status` |

Existing functions unchanged: `postQuery`, `getStatus`, `previewImageUrl`,
`fetchCsvPreview`, `fetchTextPreview`, `openInOs`, `revealInFinder`.

---

## CSS additions (`MagpieWindow.css`)

`.onboard-card` — centres content vertically in the 210 px onboarding panel.
`.onboard-card__message` — secondary text colour, centered.
`.onboard-card__btn` — ghost button matching the app's dark glass aesthetic;
hover lightens the background slightly.

---

## Tauri capabilities (`capabilities/default.json`)

`"dialog:allow-open"` added alongside `"dialog:default"`. The default permission
set does not grant file/folder picker access; it must be explicit.

---

## Known issues / future work

| Issue | Status | Notes |
|---|---|---|
| Cold query latency (ML model load) | Open | Models load on first `/query`. Could be warmed up in a background task after boot. |
| No indexing progress bar | Open | `/ingest/status` only reports running/done, not per-file progress. Walker prints to stdout; would need stdout capture + SSE to stream to UI. |
| Onboarding doesn't re-check after CLI index | Partial | `needsIndex` clears on first successful query. A periodic `/status` poll would catch CLI-indexed corpora without requiring a query. |
| Alt+Space shows ⌥Space on Windows | Cosmetic | `QuestionCard` hardcodes `⌥ Space` hint glyph. Should be `Alt+Space` on Windows. |
| StatusPill only shown when `active` | Open | Could be shown always (in compact mode too) once layout allows. |
