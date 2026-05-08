# Magpie — Ask Bar (Spotlight Window) Spec

> Companion to `magpie_product.md` and `settings_window.md`. Read the
> product description first for context. Visual references live next
> to this file in `Specs/UI/` (timestamped screenshots show resting,
> typing-with-recents, retrieval, streaming-answer, and not-found
> states).

## What it is

The ask bar is **Magpie's primary surface**. A small floating window
summoned by a global shortcut from anywhere on the user's computer.
The user types a natural-language question, hits Enter, and gets a
cited answer. It's the entire core loop in one window.

## Form factor

- **Width:** fixed at 800px. Never resizes horizontally.
- **Height:** dynamic, grows downward to fit content.
- **Position:** anchored near the top of the active monitor, roughly
  22% from the top, horizontally centered.
- **Window chrome:** none. No title bar. No min/max/close buttons.
- **Always-on-top:** yes. Other windows can't cover it while open.
- **Decorations:** transparent background; macOS uses
  `NSVisualEffectMaterial::FullScreenUI` vibrancy with rounded corners;
  Windows/Linux fall back to the platform's transparent-window
  conventions.
- **Resizable by user:** no. Height is computed from content.

## Five states

The window cycles through five states. Heights are approximate — the
designer should derive the exact values from content.

| State | Height | When |
|---|---:|---|
| **Resting** | ~96px | User has just summoned the window; input is empty and focused. |
| **Typing (with recents)** | ~280–360px | User is typing; recents appear as a list below the input. |
| **Retrieving** | ~360–420px | Question submitted; sources are being scanned. |
| **Answering** | ~480–680px | Answer is streaming; sources accumulate as cited. |
| **Not found** | ~280px | The model reports it couldn't answer from indexed files. |

Transitions animate via Tauri window resize. The width never changes.

## Universal elements (shown in every state)

### The top row — search pill + settings blob

The top of the window is a **horizontal arrangement** of two
elements, side-by-side, sharing the same vibrancy/blur background
treatment:

```
┌────────────────────────────────────────────────────┐ ┌────┐
│ 🪶  Ask Magpie about your files…                ⏎ │ │ ⚙  │
└────────────────────────────────────────────────────┘ └────┘
```

#### 1. Search pill (left, dominant)

A rounded pill containing, left to right:

1. **Magpie logo** (small, theme-aware — dark variant by default,
   light via `prefers-color-scheme: light`).
2. **Input field** — placeholder copy is **"Ask Magpie about your
   files…"** in the resting state. Disabled with "Starting Magpie…"
   during boot.
3. **Submit affordance** — a small `⏎` (return) glyph button on the
   right of the input. Visible-only-on-hover or always-visible is the
   designer's call. Enter on the keyboard does the same thing.

#### 2. Settings blob (right, separate)

A **separate circular button** to the right of the search pill,
matching macOS Spotlight's pattern of secondary-action blobs
(Spotlight ships App Store, Folders, Stacks, Files blobs to the
right of its search pill — Magpie ships exactly one: Settings).

- **Shape:** circular, ~48–64px diameter (designer's exact size).
- **Background:** same vibrancy treatment as the search pill —
  feels like a sibling element on the same translucent surface,
  not a button on top of it.
- **Icon:** the classic gear glyph (`⚙` or a designed equivalent),
  centered.
- **Behavior:** click → opens the Settings window (raises if
  already open). Tooltip "Settings" on hover.
- **Always visible** across all five states. The user can open
  Settings while typing, while reading an answer, while in the
  not-found card. Esc still hides the ask bar; clicking the blob
  opens Settings without closing the ask bar.
- **Keyboard shortcut alias:** `Cmd ,` / `Ctrl ,` from anywhere
  in the ask bar fires the same action — so the blob is the
  visible affordance and the keyboard shortcut is the power-user
  accelerator.

The total window width (still 800px) accommodates the search pill
~720px + ~16px gap + ~64px blob.

### The status footer (bottom)

A single thin line stretched across the bottom of the window. Always
visible. Format:

```
● Ready · Local · Gemma 4 · 4,408 documents understood          Esc to dismiss
```

Components, left to right:
- **Status dot** — green `●` when ready, amber while booting, red
  on error.
- **Health label** — "Ready" / "Starting Magpie…" / "Reconnecting…"
- **Provider** — "Local" or "Cloud".
- **Model** — e.g., "Gemma 4".
- **Document count** — "N documents understood" (always present
  except when the index is empty).

Right side of the footer is **context-specific keyboard hints**:

| State | Right-side hints |
|---|---|
| Resting | `Esc to dismiss` |
| Typing | `↑↓ navigate · ⏎ open · Esc close` |
| Retrieving | `Esc cancel` |
| Answering | `⌘C copy · Esc stop` |
| Not found | `Esc close` |

The status footer is the user's persistent "is Magpie healthy?"
indicator. It also doubles as Magpie's only chrome — no header bar,
no toolbar, no other meta-UI.

## State 1 — Resting

What: input is empty and focused. No content below.

Empty state. Just the input bar + status footer. The window is at its
shortest.

## State 2 — Typing, with recents

What: input has at least one character. **The window expands to show
the user's last questions as a navigable list.**

### Recents list

A panel appears below the input. Single header label:

```
RECENT
```

Each row shows the question text on the left and a relative timestamp
on the right. A small file/document icon precedes the question text.

```
RECENT
📄  what time does the chemistry final start?              12 min ago
📄  who is the chair of the math department?                yesterday
📄  how many of my course CSVs have prerequisites?          2 days ago
📄  what's my landlord's emergency phone number?            3 days ago
```

**Behavior:**

- **How many shown:** **last 4** entries.
- **Total stored:** **last 10** (older entries are evicted).
- **Filtering:** none in v1. Recents are always the last N, regardless
  of what the user is typing. (See "v2 ideas" below.)
- **Persistence:** persisted to disk. Survives restarts. Stored at
  `<APP_DATA_DIR>/recents.json`.
- **Navigation:** ↑/↓ arrow keys move a hover/selection ring through
  the list. ⏎ on a selected recent re-fires it (renders the cached
  result instantly — no LLM call). Plain ⏎ (no recent selected)
  submits the typed input as a fresh question.
- **Clicking a recent** is equivalent to ↑/↓ + ⏎.
- **Esc** dismisses the recents list and returns the window to the
  resting state (input cleared).

### Recents storage shape

The `recents.json` file is a JSON array, newest-first. Each entry
mirrors the answer pipeline's discriminated-union output, so
replaying a recent requires zero LLM cost — we just render the
cached state.

```jsonc
[
  {
    "id": "rec_abc123",
    "asked_at": "2026-05-07T22:42:00-04:00",
    "question": "who is the chair of the math department?",
    "rewritten_query": "math department chair faculty",
    "result": {
      "kind": "answered",
      "answer": "The chair of the Mathematics department is Dr. Elena Marquez …",
      "sources_used": [
        {"path": "~/Documents/School/math-dept-2024.pdf", "page": 4}
      ]
    }
  },
  {
    "id": "rec_xyz789",
    "asked_at": "2026-05-07T22:38:00-04:00",
    "question": "what's my landlord's emergency phone number?",
    "rewritten_query": null,
    "result": {
      "kind": "not_found",
      "sources_scanned_count": 5,
      "topic": "a landlord's emergency phone number"
    }
  }
]
```

**Why store the rewritten query?** Free debugging signal — we already
compute it during the original ask; persisting it lets us correlate
"this rewrite got a hit, this one didn't" later without re-running.

**Why store the answer + sources?** Re-firing a recent shouldn't pay
LLM cost. The renderer hands the stored payload to the same answer
card that handles a fresh response.

**Staleness in v1:** if the user re-fires a recent and the answer is
based on stale source files, that's accepted. The user can ask the
same question fresh by clearing input and re-typing.

## State 3 — Retrieving

What: question submitted, the pipeline is scanning candidate sources.

### Question header (replaces input)

The submitted question is rendered in place of the input field as
read-only text. A small `⏎` glyph stays on the right (greyed; visual
echo of "you submitted this").

### Body — retrieving

A status block appears below the question:

```
○  Retrieving sources…   scanning 4,408 docs
```

- A pulsing/spinning glyph (`○`) on the left.
- Bold "Retrieving sources…"
- Light-gray suffix "scanning N docs" — N = `documents_understood`,
  same number shown in the footer.

Below this, a **skeleton list** of source rows appears as files start
matching:

```
math-dept-2024.pdf      ▷ reading…
faculty-roster.csv      ▷ reading…
spring-bulletin.pdf     ▷ reading…
```

Each row is rendered the moment retrieval surfaces a candidate —
they don't all appear at once. The "▷ reading…" suffix turns into
"✓ used" / "○ skipped" once the LLM has decided per-source.

### Footer hint

```
Esc cancel
```

Pressing Esc during this state aborts the in-flight pipeline and
returns the user to State 2 (Typing, recents visible).

## State 4 — Answering

What: the LLM has begun streaming a response.

### Question header

Same as State 3.

### Status indicator

Replaces "Retrieving sources…" with a streaming indicator:

```
○  WRITING ANSWER
```

(Caps lock + spaced is the visual treatment shown in the mockup —
designer can refine.)

### Layout — two columns

The answering state uses a **two-column layout** (deliberately
preserved from the current build, not the no-preview alternative
proposed in some external design references):

- **Left column:** answer card (top) + sources list (below).
- **Right column:** preview pane.

### Left column — answer body

The model's prose, streamed token-by-token.

**Inline citations.** The model emits citation markers as numbered
references inline with the prose. The renderer styles them as small
**green pill-tags with the number inside** (matching the mockup's
"Dr. Elena Marquez ¹" treatment). Hovering a citation should
preview the source filename; clicking it should select the source
in the sources list and update the right pane's preview.

### Left column — sources list

Section header updates as sources are cited:

```
2 SOURCES SO FAR
```

Each source row, in order of first citation:

```
[icon]  math-dept-2024.pdf   p. 4                              [1]
        …the Mathematics department, currently chaired by Dr. Elena Marquez …
```

- File icon
- Filename + relevant location (page for PDFs, row for CSVs, etc.)
- Citation number on the right (matching the inline citation tags)
- A snippet preview underneath the filename — the matched span,
  trimmed to ~one line, with the answer's key tokens highlighted.

### Right column — preview

A second column appears to the right of the answer column. **The
first cited source's preview is opened by default.** Per file type:
- Text/markdown/code → text excerpt with highlights
- PDF → rendered page image around the cited page
- CSV → table excerpt around the cited row
- Image → the image itself
- Unsupported types → filename + extension + "Open file" button

Clicking a different source in the sources list updates the preview
pane in place.

### Footer hints

```
⌘C copy · Esc stop
```

`⌘C` (Cmd-C / Ctrl-C) copies the rendered answer to the clipboard.
`Esc` stops streaming and freezes the partial answer in place.

## State 5 — Not found

What: the LLM ran the pipeline and emitted a `not_found` result —
none of the retrieved sources contained the answer.

### Question header

Same as States 3 / 4.

### Body

```
○  Answer not found

I read 5 likely sources but didn't find anything about a landlord's
emergency phone number in the folders Magpie has read.

[ ➕  Add the folder where this knowledge might live           › ]
```

- Large "Answer not found" header.
- Preamble paragraph: **"I read N likely sources but didn't find
  anything about <topic> in the folders Magpie has read."** — N
  comes from the `sources_scanned_count` in the result. `<topic>`
  comes from the `topic` field on the not-found result (a short
  noun phrase emitted by the LLM as part of the structured output).
- **Exactly one** primary CTA button, full-width inside the card:

  > **➕  Add the folder where this knowledge might live**

- Clicking the button:
  1. Opens the **Settings** window.
  2. Lands on the **Data** tab.
  3. **Immediately invokes the "Add folder / file" picker** (as if
     the user had clicked the green CTA in Settings → Data). After
     the user picks, indexing kicks off; the ask bar can be
     re-summoned anytime to retry the question.

No other buttons in this state. The earlier mockup variants ("Re-read
~/Documents/Apartment", "Try a different phrasing") are dropped —
they added complexity for marginal value, and the "Add folder" path
already covers the common case (Magpie can't answer because it
hasn't read the right place yet).

### Footer hint

```
Esc close
```

## Pipeline-side schema (the LLM's output type)

The answer step's structured output is a discriminated union:

```python
class AnsweredResult(BaseModel):
    kind: Literal["answered"]
    answer: str                          # markdown-tolerant prose
    sources_used: list[SourceCitation]   # in order of first citation

class NotFoundResult(BaseModel):
    kind: Literal["not_found"]
    sources_scanned_count: int
    topic: str                           # short noun phrase, e.g.
                                         # "a landlord's emergency phone number"
                                         # — used in the not-found copy

AnswerResult = Annotated[
    Union[AnsweredResult, NotFoundResult],
    Field(discriminator="kind"),
]
```

This is what the answer pipeline returns. The frontend renders State 4
or State 5 based on the discriminator. `recents.json` stores entries
in the same shape so replays are byte-for-byte identical to fresh
runs. The system prompt instructs the model: "If none of the
retrieved sources contain the answer, return a `not_found` result
with the topic the user asked about and the number of sources you
scanned. Do not fabricate."

## Boot sequence

1. Window is visible immediately at first launch.
2. Status footer reads "● Starting Magpie… · Local · Gemma 4 · …".
3. Input is disabled, placeholder "Starting Magpie…".
4. Healthz poller (500ms) flips the footer to "● Ready · …" and
   enables the input as soon as the sidecar responds.
5. Two parallel calls fire on first ready: `/status` (drives the
   document-count in the footer) and `/settings/shortcut` (drives
   the global shortcut hint shown in the menu bar / system tray
   tooltip).

## Background polling (while window is visible)

- **Boot poll** (500ms) — `/healthz` until responsive.
- **Ingest status poll** (1.5s) — `/ingest/status` updates the
  footer's "N documents understood" counter live as new files
  are indexed in the background. If indexing is in progress, the
  status dot may switch to amber and the label to "● Understanding
  423 / 1,481 files".

## Visual language

(For tone-matching with the mockups in `Specs/UI/`.)

- **Dark by default.** Vibrancy/blur background, near-black with
  subtle translucency. Light mode swaps the logo via media query.
- **Card stack.** Every visible element is a vertically stacked
  rounded card with consistent padding.
- **Accent color.** Reserved for primary actions (submit glyph,
  Add Folder CTA) and the citation pill tags. The accent comes
  from the user's pick in Settings → Shortcut & App (Ink / Amber /
  Jade / Rose).
- **Citation tags** are small green pill shapes with the citation
  number inside. They sit inline with the prose and align with
  numbered cards in the sources list below.
- **Monospace-tinged labels.** "RECENT", "2 SOURCES SO FAR",
  "WRITING ANSWER" — these section headers feel slightly uppercase
  / spaced / mono, not full body-text.
- **No animation noise.** OS window resize handles state changes.
  Cards fade in. Spinners only spin during real pending operations.
  Streaming text appears as it arrives — no fake delays.

## Cross-platform conventions

- **Global shortcut** — registered via `tauri-plugin-global-shortcut`.
  If the default (Alt+Space) is taken, a small picker dialog offers
  fallbacks. The user's pick persists.
- **System tray icon** — macOS menu bar / Windows notification area
  / Linux tray. Left-click toggles; right-click → "Quit".
- **Single-instance** — second launch focuses the existing window.

## Keyboard summary

| Key | Resting | Typing | Retrieving | Answering | Not found |
|---|---|---|---|---|---|
| `Esc` | hide window | clear input + dismiss recents | cancel pipeline | stop streaming | close |
| `⏎` | (n/a) | submit OR fire selected recent | (n/a) | (n/a) | (n/a) |
| `↑` `↓` | (n/a) | navigate recents | (n/a) | (n/a) | (n/a) |
| `⌘C` | (n/a) | (n/a) | (n/a) | copy answer | (n/a) |
| Backspace to empty | (n/a) | collapses recents to resting | (n/a) | returns to typing state with question pre-filled | returns to typing |

## What "done" looks like

A successful build of this surface has these properties:

1. **Press shortcut → start typing in <300ms** (warm path).
2. **Recents are always one keystroke + arrow + Enter away** to
   replay a previous question instantly.
3. **The user never sees the words "Qdrant", "embedder", "RAG",
   "retrieval", "chunk"** — the surface is files + questions +
   answers + sources.
4. **The not-found state never feels like a dead-end.** The single
   "Add folder" CTA gives the user a clear next step.
5. **Esc always works** in every state.

## v2 ideas (parked, not in this build)

- Filter recents as the user types (substring match; deprioritized
  in v1 because the show-last-4 is already cheap).
- Persist a "favorites" pin on a recent.
- Inline answer previews on a recent row (one-line summary).
- Keyboard shortcut to open the most-recent answer without typing
  (e.g., `⌘↑` or `⌘↩` from resting).
- Multi-turn follow-up questions that share retrieved sources
  with the previous question. Today, each ask is fresh.

## Out of scope for v1

- Conversation history / multi-turn dialogue (each ask is fresh).
- Saved questions / bookmarks.
- Inline editing of sources.
- In-window settings panels (settings always opens its own window).
- Quick-action shortcuts that bypass the question/answer model
  (e.g., "open file by name" — Spotlight already exists).
- Suggestion completions while typing — explicitly removed in this
  iteration. Recents only.
