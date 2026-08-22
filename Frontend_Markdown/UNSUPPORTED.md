# Unsupported — query-time UI

What the user sees when Magpie returns a file whose extension has no inline
preview component. The file can still be a useful search result — the user can
open or reveal it — but nothing renders in the preview pane body.

---

## When this applies

`previewKindFor` returns `"unsupported"` for any extension that is not in the
image, PDF, CSV, or text groups. Common examples: `.docx`, `.xlsx`, `.pptx`,
`.zip`, `.mp4`, `.mp3`.

([api.ts:170](../frontend/src/api.ts#L170))

---

## What the UI shows

```
┌────────────────────────────────────────────────────────────────┐
│  ANSWER                          │  preview pane               │
│  The Q3 report is in             │  DOCX  Q3-report.docx       │
│  Q3-report.docx, slide 14.       │  ~/documents/finance        │
│                                  │  [↗ open] [↺ reveal]       │
│  + follow up                     │                             │
├──────────────────────────────────│  No inline preview for      │
│  SOURCES          1 cited / 3    │  this file type. Use        │
│  ▶ DOC  Q3-report.docx  0.77 ●  │  "open" to view it in the   │
│    Q3 financial summary…         │  default app.               │
│    /documents/finance            │                             │
└────────────────────────────────────────────────────────────────┘
```

The header (badge, filename, directory, open/reveal buttons) is always present.
Only the body is replaced with the unsupported message.

---

## PreviewCard — unsupported branch

[frontend/src/components/PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx)

```ts
{kind === "unsupported" && (
  <div className="preview-card__unsupported">
    No inline preview for this file type. Use "open" to view it in the default app.
  </div>
)}
```

No fetch, no state — this branch is a static string.

---

## SourcesCard — unsupported row

| Element | Content |
|---|---|
| Icon badge | `DOC` for `.docx` / `XLS` for `.xlsx` / `TXT` (fallback) for everything else |
| Filename | e.g. `Q3-report.docx` |
| Score chip | colour-coded: `≥ 0.7` green / `≥ 0.4` amber / `< 0.4` grey |
| Cited dot | present if this file's content contributed to the answer |
| Snippet | `source.summary` from the query response |
| Directory | directory portion of path |

`fileIcon` explicit cases: `.docx` → `"DOC"`, `.xlsx` → `"XLS"`. All other
unrecognised extensions fall back to `"TXT"`.

**Header badge (`fileLabel`):** uses the exact extension uppercased — `DOCX`,
`XLSX`, `PPTX`, etc. Falls back to `ext.slice(1).toUpperCase()` or `"FILE"`.

---

## Header actions (PreviewCard)

The open and reveal buttons work for all file types, including unsupported ones.

| Button | Action |
|---|---|
| `↗ open` | `GET /open?path=…` → OS default app (Word, Excel, etc.) |
| `↺ reveal in finder` | `GET /reveal?path=…` → Explorer / Finder |

---

## Code references

| Symbol | File | Line |
|---|---|---|
| unsupported branch (PreviewCard) | [PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx) | L58 |
| `previewKindFor` → `"unsupported"` | [api.ts](../frontend/src/api.ts) | L170 |
| `fileLabel` fallback | [PreviewCard.tsx](../frontend/src/components/PreviewCard.tsx) | L75 |
| `fileIcon` → `"DOC"` / `"XLS"` / `"TXT"` | [SourcesCard.tsx](../frontend/src/components/SourcesCard.tsx) | L113 |
