# Magpie — Settings Window Spec

> Companion to `magpie_product.md` and `ask_bar.md`. Visual references
> live next to this file in `Specs/UI/`: per-platform mockups
> (`macOS _ Dark.png`, `Windows 11 _ Dark.png`, `Linux _ Dark.png` and
> their Light variants) plus per-tab variants (`Search _ AI.png`,
> `Shortcut _ App.png`, etc.). Read the product description first.

## Purpose

The settings window is where users manage everything in Magpie that
isn't asking a question. It is **deliberately minimal** in v1: three
tabs covering the three things a typical user actually needs to
configure. Power-user knobs are parked behind an "Advanced" expander
inside the relevant tab — not exposed as their own tabs.

This spec describes v1. An "Advanced" sidebar entry that surfaces
additional tabs (API Keys, Index Health, Backups, …) is **out of
scope for v1** but listed at the bottom of this document for
forward planning.

## Window form factor

- **Native, separate window** with standard OS chrome (close /
  minimize / maximize). Not a panel inside the spotlight.
- **Resizable**, with a sensible minimum (~720×620). Default size is
  the designer's call.
- **Single-instance**: opening Settings while it's already open
  raises the existing window.
- **Sidebar nav** (NOT top tabs): a left rail with three entries +
  a status footer below them.

## Layout — sidebar + main + status footer

```
┌────────────────┬───────────────────────────────────────────────┐
│  Magpie        │  Magpie · Settings                ● <state>  │
│  SETTINGS      ├───────────────────────────────────────────────┤
│                │                                               │
│  ▣ Data        │  <Tab content>                                │
│    Search & AI │                                               │
│    Shortcut &  │                                               │
│       App      │                                               │
│                │                                               │
│                │                                               │
│                │                                               │
│  ──────────    │                                               │
│  understood:   │                                               │
│         4,408  │                                               │
│  size:    142  │                                               │
│  provider: …   │                                               │
└────────────────┴───────────────────────────────────────────────┘
```

### Sidebar (left rail)

- **Header.** "Magpie / SETTINGS" — small wordmark, two-line block.
- **Three nav entries** (icon + label):
  - **Data** — folder icon. Default landing tab.
  - **Search & AI** — sliders/list icon.
  - **Shortcut & App** — keyboard icon.
- **Status footer** at the bottom of the sidebar, always visible
  across all three tabs:
  ```
  understood:    4,408
  size:           142 MB
  provider:    Local · Gemma 4
  ```
  Reads from the same numbers shown in the ask bar's footer. Acts as
  a quiet "is Magpie healthy" indicator while the user is poking
  at settings.

### Header strip (top of main area)

```
Magpie · Settings                            ● Understanding
```

- Left: app/window title.
- Right: live status pill mirroring the sidebar footer's state.
  Examples: `● Ready`, `● Understanding`, `● Reconnecting…`,
  `● Idle`. The dot color matches the ask bar's status semantics
  (green / amber / red).

## Tab 1 — Data (default)

**Purpose:** manage which directories and files Magpie indexes, see
their state, and trigger re-reads.

### Tab header

```
Data
Files and folders Magpie reads to understand your work. Nothing
leaves your machine.

                                          [+ Add folder / file ▾]
```

- **Title:** "Data".
- **Subtitle (one line):** "Files and folders Magpie reads to
  understand your work. Nothing leaves your machine."
  This subtitle is load-bearing — it telegraphs the privacy promise
  on the most-trafficked tab.
- **Primary CTA (top right):** **"+ Add folder / file"** — accent
  color (the user's chosen accent from Shortcut & App). The chevron
  (▾) implies a small dropdown menu:
  - "Add a folder…" → folder picker
  - "Add a single file…" → file picker

### Two utility buttons (left of the primary CTA)

In the same header row as the "+ Add folder / file" CTA, two
secondary buttons sit to its left:

```
                          [ ↻ Sync ]   [ ⟳ Reindex ]   [+ Add folder / file ▾]
```

- **Sync** — neutral / outline-style button. Runs the everyday
  reconciliation: picks up new files, drops files that no longer
  match the indexing rules (removed include_paths / new
  exclusions / files deleted from disk), updates files whose mtime
  changed. Does NOT re-read unchanged files. Safe to run anytime.
  - Endpoint: `POST /index/sync` → kicks off the same job machinery
    as Add-folder, with a global progress UI (the same row-level
    progress users see on individual folders consolidates into a
    single banner across all rows).
  - Tooltip / helper: "Pick up new files and drop removed ones.
    Won't re-read what hasn't changed."

- **Reindex** — destructive-styled (subtle red border / muted
  warning color, *not* a screaming-red button — this is a power
  action, not a danger action). Wipes the entire index and runs
  Sync from scratch.
  - Click shows a confirmation modal:

    > **Reindex everything?**
    > This rebuilds Magpie's understanding of all your folders.
    > It can take 10–60 minutes depending on how much you've
    > added. Your files are not touched.
    >
    > [Cancel]  [Reindex]

  - Endpoint: `POST /index/reindex` → drops Qdrant collection +
    manifest, then runs the same job as Sync.
  - Tooltip / helper: "Rebuild from scratch. Slow but thorough —
    use only if Magpie's index seems off."

These two buttons are the v1 manual-trigger surface for indexing.
A file-watcher / scheduled-sync flow is parked for a later branch
(see `Plans/UI/Implementation Plan.md` → Indexing triggers section).

### Folder/file row (the core unit)

Each indexed source is a card. Composition (left → right):

1. **Icon** — folder or file glyph.
2. **Name + status pill** — name on top line; pill immediately
   adjacent shows current state.
3. **Path** — full path, secondary color. Tilde-collapsed when
   home-relative.
4. **Stats line** — `1,481 files · 142 MB · read 2 hours ago`
   (or for single files: `142 KB · read Yesterday`).
5. **Toggle** — enable/disable switch. Disabled rows are still
   configured but not searched.
6. **Folder action** — small folder-icon button → reveal in
   Finder/Explorer.
7. **Refresh action** — circular arrow → trigger re-read for this
   row only.
8. **Overflow** — `…` menu: rename display name, remove, copy path.

### Status pills (vocabulary)

| Pill text | When | Color |
|---|---|---|
| `● ready` | Indexed, fresh, available for search | green |
| `● understanding` | Currently being read/indexed | amber |
| `● paused` | Toggle is off; not searched | grey |
| `● error` | Last read failed | red |

Vocabulary deliberately reframes Magpie's pipeline in human terms:
- **"Read"** = file was processed (replaces "indexed" / "ingested").
- **"Understand"** = the act of processing (replaces "indexing").
- **"Understood: N"** = total documents in the searchable index.

The user never sees "ingest", "summarize", "embed", or "Qdrant".

### In-progress row (special state)

When a row is `understanding`:

```
[icon]  Work  ● understanding
        ~/Work/Contracts
        Q3-vendor-agreement.pdf · 423 of 1,812 files          23%
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        [⏸ Pause]   [✕ Cancel]
```

- Replaces the static stats line with a **live progress line**
  showing the current file + progress count + percentage.
- A horizontal progress bar sits below the file line.
- **Pause** and **Cancel** buttons appear inline. Pause keeps the
  job's state and resumes on click; Cancel discards.

### Paused row (special state)

```
[icon]  Archive  ● paused
        ~/Documents/Archive
        Paused — not searched. 2,104 files known.
```

The pill is grey; the toggle is off; the stats line is replaced by
a paused-explanation line.

### Empty state — first launch

When no folders are configured:

```
                          (large folder glyph)

           Magpie hasn't read any of your files yet.
       Add a folder to get started — Magpie will read
                     it on your machine.

                       [ + Add folder / file ]
```

Centered in the main area. The CTA is the same one as the top-right
button, just larger and centered for first-launch.

### Add folder / file flow

When the user clicks "Add folder / file":

1. Native folder/file picker opens.
2. After selection, a row appears in the list immediately with
   `● understanding` pill.
3. Indexing begins automatically. The row's progress bar updates
   live (poll `/ingest/status` every 1.5s — the same poll the ask
   bar uses).
4. When indexing finishes, the pill flips to `● ready` and the
   stats line updates.

### Remove flow

The `…` menu's "Remove" entry shows a confirmation:

> **Stop reading this folder?**
> Files inside the folder are not deleted. Magpie will forget
> what's inside it.
>
> [Cancel]   [Remove]

After confirm, the row animates out and the index entries are
dropped from the search database in the background.

### Endpoints

```
GET    /settings/folders                  → list + per-folder state
POST   /settings/folders                  → add { path, kind }
PATCH  /settings/folders/{id}             → toggle, rename
DELETE /settings/folders/{id}             → remove
POST   /settings/folders/{id}/sync        → re-read this row
POST   /settings/folders/{id}/pause       → pause running job
POST   /settings/folders/{id}/cancel      → cancel running job

GET    /ingest/status                     → live progress (poll 1.5s)
```

## Tab 2 — Search & AI

**Purpose:** pick which AI backend answers questions. v1 surfaces a
**binary choice**: Local (private, runs on your machine) or Cloud
(faster, hosted by Magpie).

### Tab header

```
Search & AI
Pick the brain that answers your questions. Switch any time.
```

### Provider — two cards, side by side

```
PROVIDER

┌─────────────────────────────┐  ┌─────────────────────────────┐
│  ◐ Local      ✓             │  │  ☁ Cloud                    │
│  Gemma 4 · 1.5 GB · runs    │  │  Our free model for faster  │
│  on your machine    private │  │  answers              fast  │
└─────────────────────────────┘  └─────────────────────────────┘

Local stays on your machine. Cloud only ever sees your question,
never your files.
```

- Two equal-width selectable cards. Selected card has accent border
  and a small `✓` mark.
- **Local card** body:
  - Title: "Local"
  - Body: `<model name> · <model size> · runs on your machine`
  - Badge (right side, neutral pill): **`private`**
- **Cloud card** body:
  - Title: "Cloud"
  - Body: "Our free model for faster answers"
  - Badge (right side, accent pill): **`fast`**
- **Tagline below both cards** (single line):
  > "Local stays on your machine. Cloud only ever sees your
  > question, never your files."

This tagline is load-bearing — it answers the privacy question for
users picking Cloud.

### Local — model availability state

When Local is selected and the model isn't downloaded yet:

```
┌─────────────────────────────────────────────────────────────┐
│  ◐ Local      Model not downloaded                          │
│  Gemma 4 · 1.5 GB                                           │
│                                                             │
│           [ Download model ]                                │
└─────────────────────────────────────────────────────────────┘
```

After clicking Download, the card shows a progress bar:

```
┌─────────────────────────────────────────────────────────────┐
│  ◐ Local                                                    │
│  Gemma 4 · 1.5 GB · downloading…                            │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  62%             │
└─────────────────────────────────────────────────────────────┘
```

### Cloud — first-pick state

The first time the user selects Cloud, a one-time micro-confirm
modal appears (or inline expand) reminding them what's sent:

> **Cloud answers**
> Magpie will send your question (and only your question) to
> Magpie Cloud. Your indexed files never leave your machine.
>
> [Cancel]   [Use Cloud]

After confirm, the choice persists; no further confirmation on
subsequent toggles.

### Advanced (collapsed by default)

Below the provider cards:

```
> Advanced  retrieval & generation knobs                  [Reset to defaults]
```

A row with a left-side `>` chevron that expands to reveal:

- **Top K** slider (1–20, default 5) — "How many sources to retrieve
  before answering."
- **Rewrite questions** toggle — "Rewrite ambiguous questions
  before searching (slightly slower, often more accurate)."
- **Temperature** slider (0.0–1.0, default 0.7).

Right side of the Advanced header has a **Reset to defaults** button
that reverts all advanced fields with one click.

### Endpoints

```
GET   /settings/search                    → { provider, model, top_k, rewrite, temperature }
PATCH /settings/search                    → partial update
GET   /settings/search/providers          → availability per provider, including local-model-downloaded state
POST  /settings/search/local/download     → start model download; poll for progress
GET   /settings/search/local/download     → download progress
```

## Tab 3 — Shortcut & App

**Purpose:** how the user summons Magpie, what it looks like, and
what it does on launch.

### Tab header

```
Shortcut & App
The global summon-key, theme, accent, and launch behavior.
```

### Global shortcut

```
GLOBAL SHORTCUT

[ Alt ] + [ Space ]    [ Change… ]   [ Use default ]

Pressed from anywhere on your computer. Must include a modifier.
```

- Two key chips (`Alt`, `Space`) showing the current binding.
- **Change…** button → opens an inline shortcut recorder.
- **Use default** button → reverts to platform default (`Alt+Space`).
- Helper text below.

### Shortcut recorder (inline state)

When the user clicks Change:

```
GLOBAL SHORTCUT

[ Press a shortcut combination… ]    [ Cancel ]

Must include Cmd/Ctrl/Alt/Shift.
```

- The chips disappear; a single recording chip captures keystrokes.
- Validation:
  - Must include at least one modifier.
  - Must not collide with a system shortcut already in use.
  - On collision, inline error: "Alt+Space is already in use by
    another app. Try a different combination."
- After a valid press → chips re-render with the new binding;
  helper line confirms "Saved."

### Theme

```
THEME

[ Match system ]  [ Light ]  [ Dark ]
```

Three-button segmented control. Selected button has accent fill.

### Accent color

```
ACCENT COLOR

(◉ Ink)   (○ Amber)   (○ Jade)   (○ Rose)

Colors highlights, the active toggle, and progress bars.
```

Four labeled color swatches as radio buttons. The currently selected
swatch has a ring around it. Default: **Ink** (a near-blue).
Helper text below explains where the accent appears.

### App-level toggles

A list of switch rows. Each row: bold label, helper line below,
toggle on the right.

```
Launch at login                                          [●○]
Start Magpie automatically when you log in.

Show in menu bar                                         [●○]
The Magpie icon stays available in the system tray.

Default action on activation                  [ Empty ask bar ▾ ]
What appears when you press the shortcut.
```

`Default action on activation` is a dropdown, not a toggle:
- "Empty ask bar" (default)
- "Show last query"

### About / version

A final card at the bottom of the tab:

```
Magpie                                              [ Check for updates ]
Version 1.0.0
```

### Endpoints

```
GET   /settings/shortcut                  → { shortcut }
PUT   /settings/shortcut                  → { shortcut }
GET   /settings/app                       → { launch_at_login, show_in_tray, theme, accent, default_action, version }
PATCH /settings/app                       → partial update
GET   /settings/app/update_check          → { current_version, latest_version, update_available }
```

## Cross-cutting interaction details

### Live updates while indexing

When any folder is indexing, several places need live updates without
manual refresh:

- The folder row's progress bar + current file (Data tab).
- The sidebar status footer's `understood:` count.
- The header strip's status pill (`● Understanding`).
- The ask bar's footer if open.

Single source of truth: `/ingest/status` polled at 1.5s. All four
locations read from this poll.

### Confirmation modals

Destructive actions use full modal dialogs:

- **Remove folder** — single-button confirm. Copy:
  "Stop reading this folder? Files inside the folder are not
  deleted. Magpie will forget what's inside it."

### Inline feedback

Successful settings saves use a tiny toast at the bottom of the
window — auto-dismiss after ~3 seconds. Errors stay inline on the
offending field.

### Loading states

Each tab fetches its data on mount. Show skeleton placeholders for
the first ~150ms; after that, real data or a "couldn't load" state
with a Retry button.

## Information architecture summary

| Tab | Default landing | Primary action | Destructive actions |
|---|---|---|---|
| **Data** | ✓ | Add folder/file | Remove folder |
| **Search & AI** | | Switch provider | None |
| **Shortcut & App** | | Change shortcut | None |

## Cross-platform notes

The mockups in `Specs/UI/` show the same window on macOS, Windows
11, and Linux in both light and dark modes. The implementation
should:

- **macOS**: native traffic-light buttons (top left), vibrancy
  background.
- **Windows 11**: native min/max/close (top right), Mica acrylic if
  available.
- **Linux**: GNOME-style window controls (varies by DE), opaque or
  translucent background per theme.

Internal layout, spacing, and component vocabulary stay identical
across platforms. Only the window chrome changes.

## What "done" looks like

A successful build of this surface has these properties:

1. A **non-technical user** can add their first folder, watch it
   index, and ask their first question without reading
   documentation.
2. **A privacy-conscious user** can pick Cloud once, read the
   confirm, and trust the choice without further interrogation
   (the privacy tagline + one-time confirm cover this).
3. The **status footer in the sidebar** stays accurate across
   sections — the user always knows Magpie's health and corpus
   size.
4. Destructive actions are **clearly destructive without being
   intimidating**.
5. The settings window feels like the **same product** as the ask
   bar — same vocabulary, same vibrancy, same accent.

## Out of scope for v1 — parked for the future "Advanced" sidebar

The following surfaces were considered for v1 and **deferred**.
The current sidebar deliberately does not expose them. A future
"Advanced" sidebar entry (icon: gear-cluster) could expand the
nav to add the tabs below — this is the planned escape hatch when
v1 simplicity outgrows specific power-user needs.

### Parked Tab — API Keys

Manages keys for cloud providers other than the bundled "Cloud"
option (OpenRouter, Moonshot, etc.). v1 hides this entirely — the
binary Local/Cloud choice in the Search & AI tab covers ~95% of
users without exposing the bring-your-own-key surface.

When this lands, it would offer:
- Per-provider rows: status (Set / Not set / Invalid), masked
  preview, Set/Replace/Remove/Test buttons.
- Storage in `<APP_DATA_DIR>/secrets.json` with mode 0600 — never
  in `.env`.
- Endpoint surface: `GET/PUT/DELETE /settings/keys/{provider}`,
  `POST /settings/keys/{provider}/test`.

### Parked Tab — Index Health

Surfaces operational state and re-index controls. v1 surfaces these
implicitly (sidebar footer for stats, per-row Refresh button on
Data tab) — full health surface is power-user territory.

When this lands:
- Stats card: documents, chunks, on-disk size, last successful
  read.
- Recent activity log (last 50 events).
- Re-index everything button (with confirmation).
- Reset index button (red, typed-`RESET` confirmation): drops the
  search database; user files are not touched.

### Parked Tab — Backups

Snapshot/restore for the index. v1 has the underlying
`src/backup.py` machinery but no UI — power users invoke via CLI.

When this lands:
- List of backups (timestamp, size, machine).
- Create / Restore / Delete per backup.
- Auto-backup-before-reindex toggle.
- Restore is destructive (typed-word confirmation; replaces current
  index).

### Parked Tab — LLM-server runtime knobs

Context length, port, RAM cap, batch sizes. These are deployment-
time knobs that touch model loading and memory — surfacing them to
non-expert users is a footgun. Power users edit `magpie_defaults.json`
directly today; this would only become a UI when there's evidence
real users need it.

### Parked Tab — Indexing rules editor

A UI to edit `exclude_paths` and `exclude_globs` (e.g., always
exclude `node_modules/`, `*.log`). v1 ships sensible defaults
baked in and doesn't expose this. Power users edit
`<APP_DATA_DIR>/indexing_rules.json` directly.

### Activation trigger for the future "Advanced" entry

When (any of) the following becomes true, add the Advanced sidebar
entry and migrate parked tabs into it:

1. A real user reports needing an exposed API-key surface for a
   provider Magpie doesn't bundle.
2. Index corruption happens in the wild often enough that the
   power-user "reset & restore" path needs a click rather than a
   CLI invocation.
3. We add a second model family to Local (e.g., Qwen2.5-VL,
   LFM2-VL) and the binary Local/Cloud choice stops being
   sufficient — Search & AI sprouts a third tier of sub-options
   that don't fit cleanly behind the current Advanced expander.

Until any of those triggers fire, the v1 three-tab surface stays.
