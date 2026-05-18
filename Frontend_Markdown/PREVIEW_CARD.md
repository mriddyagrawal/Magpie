# PreviewCard

The right-hand column of the results grid. It is a shell component — it
decides which preview sub-component to mount based on the selected file's
extension, and wraps it with a consistent header (badge, filename, open/reveal
buttons).

Component: [frontend/src/components/PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx)

---

## Layout

```
┌──────────────────────────────────────────────────┐
│  [badge] filename.ext   ~/full/path/dir           │
│                        [↗ open] [↺ reveal]       │
│──────────────────────────────────────────────────│
│                                                   │
│  <body: ImagePreview / PdfPreview / CsvPreview /  │
│         TextPreview / unsupported message>        │
│                                                   │
└──────────────────────────────────────────────────┘
```

---

## Empty state

When `path === null` (no source selected yet — which only happens briefly
before auto-selection fires):

```ts
<div className="preview-card preview-card--empty">
  Select a source to preview it here.
</div>
```

In practice the auto-selection in `MagpieWindow` sets `selectedPath` to
`sources[0].path` synchronously when results arrive, so this state is rarely
visible.

---

## Header

Always present whenever a `path` is provided.

| Element | Detail |
|---|---|
| `preview-card__icon` | `fileLabel(path)` — exact extension badge, e.g. `PDF`, `PY`, `PNG` |
| `preview-card__name` | basename of path |
| `preview-card__dir` | `~/` + full path (shows full absolute path with tilde prefix) |
| `↗ open` button | `openInOs(path)` → `GET /open?path=…` |
| `↺ reveal in finder` button | `revealInFinder(path)` → `GET /reveal?path=…` |

The `fileLabel` function ([PreviewCard.tsx:68](../frontend/src/components/PreviewCard.tsx#L68))
uses a fixed extension map plus a fallback of `ext.slice(1).toUpperCase()`.

---

## Preview routing

```ts
const kind = previewKindFor(path);  // → "image" | "pdf" | "csv" | "text" | "unsupported"
```

```ts
{kind === "image"       && <ImagePreview path={path} />}
{kind === "pdf"         && <PdfPreview path={path} />}
{kind === "csv"         && <CsvPreview path={path} highlights={highlights} />}
{kind === "text"        && <TextPreview path={path} highlights={highlights} />}
{kind === "unsupported" && <div className="preview-card__unsupported">
  No inline preview for this file type. Use "open" to view it in the default app.
</div>}
```

Note that `ImagePreview` and `PdfPreview` do **not** receive `highlights` — they
render raster content with no text layer to highlight. `CsvPreview` and
`TextPreview` do receive `highlights` and apply them via `Highlighted`.

For the full extension → kind mapping see [ROUTING.md](./ROUTING.md).

---

## Props

| Prop | Type | Source |
|---|---|---|
| `path` | `string \| null` | `selectedPath` state in MagpieWindow |
| `highlights` | `string[]` | `extractHighlightTokens(result.answer)` from MagpieWindow |

---

## `fileLabel` — header badge text

Defined at [PreviewCard.tsx:68](../frontend/src/components/PreviewCard.tsx#L68).

| Extension(s) | Badge |
|---|---|
| `.png` | `PNG` |
| `.jpg` `.jpeg` | `JPG` |
| `.webp` | `WEBP` |
| `.gif` | `GIF` |
| `.pdf` | `PDF` |
| `.csv` | `CSV` |
| `.md` `.markdown` | `MD` |
| `.docx` | `DOCX` |
| `.xlsx` | `XLSX` |
| `.txt` | `TXT` |
| `.json` | `JSON` |
| anything else | `ext.slice(1).toUpperCase()` (e.g. `.py` → `PY`) |

Fallback of `"FILE"` only if extension is absent entirely.

**Contrast with `fileIcon` in SourcesCard:** `fileLabel` uses exact extensions;
`fileIcon` groups all code/text files under `TXT`. They are intentionally
different — the header badge is more specific than the sources list badge.

---

## Code references

| Symbol | File | Line |
|---|---|---|
| `PreviewCard` component | [PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx) | L14 |
| empty state | [PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx) | L15 |
| `kind = previewKindFor(path)` | [PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx) | L25 |
| header | [PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx) | L30 |
| body routing | [PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx) | L53 |
| `fileLabel` | [PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx) | L68 |
| `previewKindFor` | [api.ts](../frontend/src/api.ts) | L161 |
| `openInOs` | [api.ts](../frontend/src/api.ts) | L66 |
| `revealInFinder` | [api.ts](../frontend/src/api.ts) | L71 |
