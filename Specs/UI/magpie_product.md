# Magpie — Product Description

> A self-contained brief for designers and product collaborators. No prior
> context on the codebase needed. Pair this with `settings_window.md` when
> designing the settings surface.

## One-line pitch

**Magpie is a personal memory layer for your computer.** It quietly indexes
the folders you point it at — your notes, PDFs, course materials, contact
lists, code, screenshots — and lets you ask natural-language questions
about any of it. Answers come back with the actual source files cited, one
click away.

## What problem it solves

People accumulate hundreds of gigabytes of files across their lives:
class notes, work documents, downloaded PDFs, scanned receipts, CSVs of
every kind. The information is *yours* and it's *right there*, but
finding it is painful. Spotlight searches filenames; full-text search
returns walls of unranked matches; nothing answers a real question like
*"what time does the chemistry final start?"* or *"who is the chair of
the math department?"* or *"how many of my course CSVs have a
prerequisites column?"*

Magpie sits between you and that pile. You ask a question; it retrieves
the few documents most likely to contain the answer; it reads them; it
gives you a short, cited reply.

## Who it's for

- **Students and researchers** with messy folders of class materials,
  papers, and notes.
- **Knowledge workers** with directories of contracts, reports, meeting
  notes, and reference docs they need to search semantically.
- **Small teams** who want a private "team brain" without uploading
  everything to a third-party SaaS.
- **Anyone privacy-conscious** who wants the search-and-ask layer of ChatGPT
  but pointed at their own files, with their data staying on their
  machine.

## How it works (the mental model)

Magpie has three steps the user thinks about:

1. **Tell Magpie which folders to index.** Add `~/Documents/School` or
   `~/Work/Contracts` or wherever your stuff lives. You can add multiple
   folders. You can pause or remove folders later.

2. **Magpie indexes in the background.** It walks the folders, makes a
   searchable representation of every file (text extraction, OCR for
   scanned PDFs, CSV row parsing, image understanding), and stores the
   results in a local search database. You see live progress; you can
   cancel anytime; it's resumable.

3. **Press the global shortcut. Ask. Get a cited answer.**
   `Alt+Space` (or your chosen shortcut) summons a small spotlight-style
   window from anywhere on your computer. You type your question. A few
   seconds later you have an answer plus the list of files it pulled
   from. Click a source to open it in your default app, or reveal it in
   Finder/Explorer.

That's the whole product loop.

## The two surfaces

### Spotlight window (the primary UX)

A small floating window — roughly 800px wide, very short by default —
that appears when the user hits the global shortcut. Spotlight-inspired
aesthetic: rounded corners, translucent background (vibrancy/blur on
macOS), minimal chrome, no title bar. It anchors near the top of the
screen. It hides instantly on Esc or when it loses focus.

The user types a question. As the answer streams in:
- The window grows to fit an answer card showing Magpie's reply.
- A sources card lists the files used, with filename, snippet preview,
  and an "open" / "reveal" affordance.
- Some sources render an inline preview (image thumbnail, PDF page,
  highlighted text excerpt).

The spotlight is meant to disappear when you're done. It's a tool you
pull out, use, dismiss.

### Settings window (the focus of the companion spec)

A separate, conventional native window. Resizable. Has standard window
chrome. This is where the user manages everything that *isn't* asking a
question: which folders are indexed, which AI model answers, API keys,
shortcut, index health.

See `settings_window.md` for the full spec.

### System tray icon

In the macOS menu bar / Windows notification area / Linux system tray.
Left-click toggles the spotlight; right-click → "Quit Magpie." Quiet
presence. Same icon as the app.

## What Magpie can read

- **Plain text and markdown** — direct.
- **PDFs** — both text-native and scanned (OCR for scanned and
  handwritten, where the AI can read the page like an image).
- **CSVs** — Magpie understands them as structured data: it knows how
  many rows, what columns, can find specific rows ("the entry for
  CSC-105"), and can answer aggregation questions ("how many courses
  have a prerequisite column filled in?").
- **Code files** — searchable as text, with filename-aware retrieval.
- **Images and screenshots** — described and indexed by a vision model.
- **Configuration files** — JSON, YAML, TOML.

The user does not need to know any of this. They just point Magpie at a
folder and it does the right thing per file type.

## Where the AI runs

Magpie supports multiple LLM backends:

- **Local (default)** — runs Gemma 4 (or another small model) on the
  user's own machine via a bundled `llama-server` subprocess. No API
  key needed. No data leaves the machine. Free. Slower than cloud but
  private.
- **OpenRouter / Moonshot / other providers** — bring your own API key.
  Faster. Cheaper per query at scale. Cloud-routed.
- **Magpie Cloud** (planned) — a hosted offering for teams.

The user picks their backend in Settings. The product is fully usable
in local-only mode.

## Key product principles

These are the values the design should reinforce:

1. **Local-first.** The user's files never leave their machine for
   indexing. The LLM step *can* call out to a cloud provider, but only
   when the user explicitly chooses one and provides their own key.
2. **Cited answers.** Every answer shows its sources. The user can
   verify. The product never hallucinates without consequences — it
   shows what it's reading from.
3. **Quiet by default.** Magpie is a tool that stays out of the way.
   No notifications begging for attention. No marketing chrome inside
   the app. The spotlight window is invisible until summoned.
4. **Honest about what it can't do.** If Magpie can't find a relevant
   file, it says so. It doesn't fabricate. If indexing fails on a file,
   the user can see what failed and why.
5. **Resumable, not destructive.** Indexing can be paused, resumed,
   and undone. Removing a folder doesn't delete the user's files. A
   reset-index button is destructive but always behind a confirmation.
6. **Cross-platform.** First-class on macOS, Windows, and Linux. The
   shortcut, the tray icon, the file pickers all use platform-native
   conventions.

## Visual identity (for tone matching)

- Calm. Modern. Restrained.
- The spotlight window's aesthetic: vibrancy/blur, soft shadows,
  rounded corners, monospace-tinged but not strict, generous padding,
  no decorative gradients, no animation noise.
- The product feels like a utility — closer to `1Password`, `Linear`,
  or `Raycast` than to a consumer chat app.
- Dark mode is a first-class citizen, not an afterthought. So is light
  mode. Both should feel deliberate.
- Color palette is restricted: a neutral base (whites/greys for light,
  near-blacks for dark), one accent color for primary actions, red
  reserved for destructive actions, green sparingly for "indexed /
  ready" status.

## What Magpie is NOT

To keep design decisions sharp, the things explicitly out of scope:

- Not a file manager. Magpie doesn't move, rename, or organize the
  user's files. It only reads them.
- Not a chat product. There is no conversation history, no
  multi-turn dialogue, no "ChatGPT for your files" framing. Each
  question stands alone with its sources.
- Not a cloud-sync product. Magpie indexes one machine's files at a
  time. (A team/cloud edition is on the roadmap but not part of v1.)
- Not a notes app. It indexes notes apps' export folders, but it
  doesn't replace them.
- Not a build/automation product. No workflows, no agents acting on
  files, no scheduled tasks beyond background re-indexing.

## Technical context (only what designers need)

- The app is a single native desktop install (Tauri shell with a Python
  search backend bundled inside).
- It runs entirely as a local app — no signup, no account, no telemetry
  by default.
- First launch may download a ~150MB local model if the user picks the
  local provider. That download has its own UI flow.
- Indexing speed depends on file count and types — text is fast, OCR
  on scanned PDFs is slow. The settings window must show progress
  honestly.

## Glossary (for designer reference)

- **Index / indexing** — the process of reading user files and storing
  a searchable representation. Visible to the user as a progress bar
  per folder.
- **Source** — a file that contributed to an answer, shown in the
  sources card.
- **Provider** — the AI backend that answers questions (local /
  OpenRouter / etc.).
- **Sync** — re-indexing a folder to pick up new or changed files.
- **Folder** — a top-level directory the user has chosen to index.
  A folder may have hundreds of files inside it.
