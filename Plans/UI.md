# Magpie UI — Codebase Reference

> Quick reference for the `frontend/` directory and `src/server.py`. All paths relative to repo root.

---

## Tech stack

| Layer | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Bundler | Vite 5 (dev port 1420, Tauri convention) |
| Desktop shell | Tauri v2 (Rust) |
| Styling | Raw CSS + design tokens — no framework |
| Fonts | SUSE Mono (bundled variable TTF), Roboto + Roboto Slab (Google Fonts) |
| Backend | FastAPI + uvicorn (`src/server.py`), spawned as Tauri sidecar |

---

## Window behaviour

- **Resting size:** 800 × 96 px — just the search bar
- **Active size:** 800 × 680 px — bar + answer/sources/preview grid
- Transparent, no decorations, always-on-top, no dock icon (`ActivationPolicy::Accessory`)
- macOS vibrancy: `NSVisualEffectMaterial::FullScreenUI` at 18 px radius (same material as Spotlight/Raycast)
- **Spotlight anchor:** 22% from screen top, horizontally centred; re-applied on every summon so dragging never sticks
- **⌥Space** global shortcut: toggle show/hide (registered in `lib.rs`)
- `tauri://blur` → shrink to compact size, hide
- `tauri://focus` → reset state, focus input
- **Esc** → hide; **close button** → hide (not quit)

---

## Component tree

```
App
└── MagpieWindow          (MagpieWindow.tsx — all query state lives here)
    ├── QuestionCard      logo + input / submitted-question display + ⌥Space hint
    ├── [when active]
    │   ├── magpie-grid
    │   │   ├── col-left
    │   │   │   ├── AnswerCard    ANSWER label, body text, "follow up" button
    │   │   │   └── SourcesCard  list of SourceRows (icon · name · score · snippet · dir)
    │   │   └── col-right
    │   │       └── PreviewCard  header (filename, open/reveal) + preview body
    │   │           ├── ImagePreview   <img src=previewImageUrl>
    │   │           ├── PdfPreview     page-by-page PNG via /preview, prev/next buttons
    │   │           ├── CsvPreview     scrollable table, 500-row truncation, Highlighted cells
    │   │           └── TextPreview    <pre> with Highlighted text
    └── StatusPill        fixed bottom-centre: model · N indexed · provider ▸ qdrant mode
```

`Highlighted` (`Highlighted.tsx`) is a utility component used in AnswerCard, SourcesCard snippets, CsvPreview cells, and TextPreview. It wraps matched tokens in `<mark class="magpie-highlight">`. `extractHighlightTokens(answer)` extracts currencies, dates, course codes, all-caps IDs, quoted phrases, and proper nouns from the answer string.

---

## State flow (MagpieWindow)

```
user types → setQuery
user hits Enter → onSubmit(query)
  → setLoading(true)
  → postQuery(q) → POST /query
  → setResult(res)
  → setSelectedPath(res.sources[0].path)  ← top source auto-selected
  → setLoading(false)
  → Tauri: setSize(800 × 680)

user clicks source row → setSelectedPath(path)  ← PreviewCard re-renders

Esc / blur → hideWindow() → shrink to compact, hide
focus event → reset()  ← wipes result, re-focuses input
```

---

## API client (`frontend/src/api.ts`)

| Function | HTTP | Server endpoint |
|---|---|---|
| `postQuery(q, {topK, rewrite})` | POST `/query` | pipeline ask |
| `getStatus()` | GET `/status` | model info + indexed count |
| `previewImageUrl(path, page)` | — | builds GET `/preview` URL used as `<img src>` |
| `fetchCsvPreview(path)` | GET `/preview` | returns `CsvPreview` JSON |
| `fetchTextPreview(path)` | GET `/preview` | returns plain text |
| `openInOs(path)` | GET `/open` | `open <path>` |
| `revealInFinder(path)` | GET `/reveal` | `open -R <path>` |

Port is read from `window.__MAGPIE_PORT__` (injected by Tauri after the sidecar starts). Falls back to `8765` for plain-browser dev.

`previewKindFor(path)` classifies a file extension into `"image" | "pdf" | "csv" | "text" | "unsupported"` — drives which preview component renders.

---

## TypeScript types (`frontend/src/types.ts`)

```ts
Source          { path, summary, score: 0..1, cited: boolean }
QueryResponse   { question, answer, sources: Source[], search_query: { query, keywords[] } }
StatusResponse  { llm_provider, llm_model, qdrant_provider, indexed_count }
CsvPreview      { columns: string[], rows: string[][], truncated: boolean }
```

These mirror the Pydantic models in `src/server.py`.

---

## Python server (`src/server.py`)

FastAPI app — intended to run as a Tauri sidecar but also works standalone via `uvicorn src.server:app --port 8765`.

**Sidecar boot protocol:** picks a free port, prints `MAGPIE_PORT=<n>` as the *first* stdout line, then starts uvicorn. `lib.rs:spawn_sidecar()` blocks on that line and injects the port into the webview.

| Endpoint | What it does |
|---|---|
| `POST /query` | Calls `src.pipeline.ask()`, returns `QueryResponse` |
| `GET /preview` | Image → `FileResponse`; PDF → pymupdf render → PNG (in-memory cache by path+mtime+page); CSV → JSON; text/docx/xlsx → `PlainTextResponse` |
| `GET /status` | `{ llm_provider, llm_model, qdrant_provider, indexed_count }` — 5 s TTL cache |
| `GET /open` | `open <path>` (macOS) |
| `GET /reveal` | `open -R <path>` (Finder) |
| `GET /healthz` | `{"status":"ok"}` |

Path resolution: accepts relative-to-repo-root or absolute; rejects paths that escape the repo root.

---

## Tauri / Rust shell (`frontend/src-tauri/src/lib.rs`)

- `spawn_sidecar()` — runs `uv run python3 -m src.server`, reads `MAGPIE_PORT=N` from first stdout line, drains remaining stdout in a background thread so the pipe never stalls
- `anchor_spotlight(window)` — sets window to `(screen_w - win_w) / 2`, `screen_h * 0.22`
- `⌥Space` shortcut — on press: hide if visible, else re-anchor + show + focus
- `CloseRequested` event — intercepts and hides instead of quitting
- macOS `ActivationPolicy::Accessory` — suppresses dock icon, no ⌘-Tab entry
- `window_vibrancy::apply_vibrancy(FullScreenUI, Active, radius=18)` — native glass blur

Tauri commands exposed to JS: `hide_window`, `show_window` (used via Tauri window API, not direct invoke).

Tauri capabilities (`capabilities/default.json`): `core:window:allow-{show,hide,set-focus,close,set-size,start-dragging}`, `global-shortcut:allow-{register,unregister,is-registered}`.

---

## Design tokens (`frontend/src/styles/tokens.css`)

```
Surfaces:   --bg-card: rgba(16,18,24,0.78) + backdrop-filter blur(40px)
Accent:     --accent: #ffe97a  (warm yellow — the only non-neutral colour)
            --accent-soft: rgba(255,233,122,0.18)  (selected source bg, highlight bg)
Score:      --score-green ≥0.7 | --score-amber ≥0.4 | --score-grey <0.4
Radius:     --radius-card: 18px
Blur:       --blur-card: 40px
Fonts:      --font-mono: "SUSE Mono"  --font-body: "Roboto"  --font-slab: "Roboto Slab"
Sizes:      xs=11 sm=13 md=14 lg=16 xl=18 (px)
```

`mark.magpie-highlight` uses `--accent-soft` background + `--accent` text + 4 px border-radius.

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| Enter | Submit query |
| Esc | Hide window |
| ↑ / ↓ | Navigate source rows (when not in input) |
| Enter on selected source | Open in OS default app |
| ⌘+Enter on selected source | Reveal in Finder |
| ⌥Space | Global: summon / dismiss |

---

## Dev workflow

```bash
cd frontend
pnpm dev          # Vite only, browser at http://localhost:1420 (needs sidecar running separately)
pnpm tauri dev    # full Tauri + sidecar (spawns uv run python3 -m src.server)
pnpm build        # tsc + vite build → ../dist
pnpm tauri build  # .app + .dmg
```

Sidecar is launched by Tauri in production. For browser-only dev, start the Python server manually:
```bash
uv run uvicorn src.server:app --port 8765
```
