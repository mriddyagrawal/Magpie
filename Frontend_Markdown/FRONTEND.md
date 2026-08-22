# Frontend documentation index

These docs live alongside the source they describe (`frontend/`). They cover
the query-time UX — what renders when a search returns results — and the
lifecycle / management surfaces. Each doc assumes the backend is up and the
index is populated.

For how files get *into* the index (ingest, embedding, Qdrant storage) see the
`Tiers/` docs at the repo root.

---

## Query-time: per file type

Each doc covers the full stack for that file type: AnswerCard, SourcesCard row,
PreviewCard, data flow, and code references.

| Doc | File types covered |
|---|---|
| [IMAGE.md](./IMAGE.md) | `.png` `.jpg` `.jpeg` `.webp` `.gif` |
| [PDF.md](./PDF.md) | `.pdf` (paginated image render via pymupdf) |
| [CSV.md](./CSV.md) | `.csv` (live 500-row table, JSON fetch) |
| [TEXT.md](./TEXT.md) | `.md` `.txt` `.py` `.ts` `.go` `.rs` `.json` `.sql` and more |
| [UNSUPPORTED.md](./UNSUPPORTED.md) | `.docx` `.xlsx` `.pptx` and anything else |

---

## Query flow

[QUERY_FLOW.md](./QUERY_FLOW.md) — complete sequence from keypress to rendered result:
input freeze → POST /query → response → AnswerCard + SourcesCard + PreviewCard mount simultaneously → highlights propagate → backspace-to-dismiss.

---

## Cross-cutting surfaces

| Doc | What it covers |
|---|---|
| [ROUTING.md](./ROUTING.md) | `previewKindFor`, `fileLabel`, `fileIcon` — how an extension maps to a preview component and badge |
| [MANAGEMENT_CARD.md](./MANAGEMENT_CARD.md) | Inline onboard card inside MagpieWindow: indexing progress, needsIndex, indexDone, indexError states |
| [SETTINGS_WINDOW.md](./SETTINGS_WINDOW.md) | Separate Tauri webview: folder list, add/remove/re-index, ingest progress, shortcut display |
| [WINDOW_LIFECYCLE.md](./WINDOW_LIFECYCLE.md) | Anchor positioning, show/hide paths, window sizes, shortcut registration, booting sequence |

## Component deep-dives

| Doc | What it covers |
|---|---|
| [QUESTION_CARD.md](./QUESTION_CARD.md) | Search input bar: two modes (search/active), drag, logo, settings gear, shortcut label |
| [ANSWER_CARD.md](./ANSWER_CARD.md) | Answer display: three states (loading dots/error/text), follow-up button, StatusPill |
| [SOURCES_CARD.md](./SOURCES_CARD.md) | Source list: keyboard nav, badges, score colours, cited rows, auto-selection |
| [PREVIEW_CARD.md](./PREVIEW_CARD.md) | Preview shell: extension routing to sub-components, header badge, open/reveal, empty state |
| [HIGHLIGHTED.md](./HIGHLIGHTED.md) | `Highlighted` render component + `extractHighlightTokens` patterns and flow |

---

## Dual-window mounting (`App.tsx`)

The Tauri app ships a **single Vite bundle** that serves both the main window
and the Settings window. `App.tsx` picks the root component at runtime:

```ts
const isSettings = window.__MAGPIE_WINDOW_TYPE__ === "settings";
return isSettings ? <SettingsWindow /> : <MagpieWindow />;
```

The Rust `open_settings` command creates a new `WebviewWindow` and injects
`window.__MAGPIE_WINDOW_TYPE__ = "settings"` via an init script before the
page loads. The main window never sets this variable, so it always mounts
`MagpieWindow`.

This means there is no React Router or separate HTML entry point — one bundle,
two render paths.

---

## Shared data types (`src/types.ts`)

TypeScript mirrors of the Python server's Pydantic schemas:

| Type | Fields | Used by |
|---|---|---|
| `Source` | `path`, `summary`, `score`, `cited` | SourcesCard, all preview docs |
| `QueryResponse` | `question`, `answer`, `sources[]`, `search_query` | MagpieWindow, AnswerCard |
| `StatusResponse` | `ready`, `indexed_count`, `version` | StatusPill, boot flow |
| `CsvPreview` | `columns`, `rows[][]`, `truncated` | CsvPreview component |

---

## Key components at a glance

| Component | File | Role |
|---|---|---|
| `MagpieWindow` | `src/components/MagpieWindow.tsx` | Root — owns all state, resize, boot poll, background ingest poll |
| `QuestionCard` | `src/components/QuestionCard.tsx` | Search input, settings gear |
| `AnswerCard` | `src/components/AnswerCard.tsx` | LLM answer text with highlight tokens |
| `SourcesCard` | `src/components/SourcesCard.tsx` | Source list, keyboard nav, badges |
| `PreviewCard` | `src/components/PreviewCard.tsx` | Preview shell — header, open/reveal, routes to sub-component |
| `ImagePreview` | `src/components/previews/ImagePreview.tsx` | Single `<img>` tag |
| `PdfPreview` | `src/components/previews/PdfPreview.tsx` | Paginated page images via sidecar |
| `CsvPreview` | `src/components/previews/CsvPreview.tsx` | 500-row scrollable table |
| `TextPreview` | `src/components/previews/TextPreview.tsx` | `<pre>` block with highlights |
| `Highlighted` | `src/components/Highlighted.tsx` | Token highlight wrapper + `extractHighlightTokens` |
| `SettingsWindow` | `src/components/SettingsWindow.tsx` | Separate webview for settings |

---

## API surface (`src/api.ts`)

| Function | Purpose |
|---|---|
| `postQuery` | `POST /query` → answer + sources |
| `previewKindFor` | extension → `"image" \| "pdf" \| "csv" \| "text" \| "unsupported"` |
| `previewImageUrl` | builds `/preview?path=…&page=N` URL for `<img src>` |
| `fetchCsvPreview` | `GET /preview` → `{ columns, rows, truncated }` |
| `fetchTextPreview` | `GET /preview` → raw text string |
| `openInOs` | `GET /open?path=…` |
| `revealInFinder` | `GET /reveal?path=…` |
| `getFolders` | `GET /settings/folders` |
| `addFolder` | `POST /settings/folders` |
| `removeFolder` | `DELETE /settings/folders?path=…` |
| `getShortcut` | `GET /settings/shortcut` |
| `startIngest` | `POST /ingest` |
| `getIngestStatus` | `GET /ingest/status` |
| `stopIngest` | `POST /ingest/stop` |
