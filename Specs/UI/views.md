# Magpie — View Catalog & Redesign Tracker

Every visual state Magpie can show, the component(s) that render it, its
current status, and its status under the in-progress UI redesign (branch
`ui-redesign-all-views`, porting Rahul's thinkpad redesign + designing any
missing states).

The state machine that decides *which* main-window view shows lives in
[`frontend/src/components/viewState.ts`](../../frontend/src/components/viewState.ts)
(the `View` union). It is **identical between `main` and the thinkpad
redesign** — so the redesign is purely presentational: same states, new looks.

## Legend

**Baseline** = does it work in the current `main`-based build?
- ✅ verified live this session
- ✔ shipped in `main` (present & working in the product; not re-verified visually this session)
- ❓ present in code but not exercised/verified

**Redesign** = state of the new-design port on `ui-redesign-all-views`:
- ⬜ not started (still main's UI) · 🚧 in progress · ✳ done (ported + builds green) · ✅ done + visually verified

> **Status 2026-07-06:** Rahul's full redesign is **ported and the production
> build is green** (`pnpm build` ✓, `tsc` clean). All views below are ✳ —
> the new design is compiled in but **not yet visually verified**.
>
> ⚠️ Visual verification is blocked for the agent: `screencapture` fails
> (Screen Recording permission not granted to the terminal). To move views
> from ✳ → ✅, either **eyeball them yourself** in the running dev build, or
> grant Screen Recording to the terminal (System Settings → Privacy & Security
> → Screen Recording) so the agent can screenshot each state.

---

## Main search window (`View` union in `viewState.ts`)

| # | View / state | Trigger | Component(s) | Baseline | Redesign |
|---|---|---|---|---|---|
| 1 | **Resting — empty bar** | Input empty & focused, corpus indexed | `MagpieWindow` (~96px) | ✅ | ✳ |
| 2 | **Resting — with recents** | Resting + prior questions exist | `MagpieWindow` + recents panel | ✔ | ✳ |
| 3 | **Resting — nothing indexed** (onboarding) | Resting + `indexed_count === 0` + sidecar ready | `WelcomeCard` | ✔ | ✳ |
| 4 | **Typing** | User typing a query | `MagpieWindow` + `QuestionCard`, recents selectable | ✔ | ✳ |
| 5 | **Retrieving** | Query sent; rewriting + searching (pre-first-token) | `RetrievingPanel` → two-column once `sources` SSE lands | ✔ | ✳ |
| 6 | **Answering** | Streaming answer chunks | `AnswerCard` (+ `SourcesCard`, `citations`) | ✔ | ✳ |
| 7 | **Not found** | Search returned nothing relevant | `NotFoundCard` (+ recents-replay fallback) | ✔ | ✳ |

## Cross-cutting states (layer on top of the above)

| # | State | Trigger | Component(s) | Baseline | Redesign |
|---|---|---|---|---|---|
| 8 | **Booting** | App just launched, sidecar not `ready` yet | `MagpieWindow` (`booting`) | ✔ | ✳ |
| 9 | **Indexing in progress** | An ingest job is running | `StatusFooter` ("scanning N docs") | ✔ | ✳ |
| 10 | **Backend down / unreachable** | Sidecar not responding / query error | error path in `MagpieWindow` / `StatusFooter` | ❓ | ✳ |
| 11 | **Preview — image** | Source is an image | `PreviewCard` → image | ✔ | ✳ |
| 12 | **Preview — PDF** | Source is a PDF | `PreviewCard` → `previews/PdfPreview` | ✔ | ✳ |
| 13 | **Preview — CSV** | Source is a CSV | `PreviewCard` → csv table | ✔ | ✳ |
| 14 | **Preview — text/code/markdown** | Source is text-like | `PreviewCard` → text | ✔ | ✳ |
| 15 | **Preview — unsupported** | Source type has no preview | `PreviewCard` fallback | ❓ | ✳ |

## Settings window

| # | View / state | Trigger | Component(s) | Baseline | Redesign |
|---|---|---|---|---|---|
| 16 | **Settings shell** | Cmd+, / tray / menu (opens dedicated `settings.html`) | `SettingsWindow`, `SettingsSidebar`, `SettingsHeader` | ✅ | ✳ |
| 17 | **Data tab — with folders** | Folders added | `settings/DataTab`, `FolderRow` | ✔ | ✳ |
| 18 | **Data tab — empty** (no folders) | No folders added yet | `settings/DataTab` empty state | ❓ | ✳ |
| 19 | **Search & AI tab** | Nav → Search & AI | `settings/SearchAITab` (provider local/cloud, model) | ✔ | ✳ |
| 20 | **Shortcut & App tab** | Nav → Shortcut & App | `settings/ShortcutAppTab` | ✔ | ✳ |
| 21 | **Confirm modal** | Destructive action (e.g. remove folder) | `settings/ConfirmModal` | ✔ | ✳ |

---

## Verified live this session (2026-07-05)

- App launches from installed `/Applications/Magpie.app`; full backend spawns
  (magpie + qdrant + sidecar). Spotlight bar renders (no white screen).
- Settings window opens via the new dedicated `settings.html` path (the Windows
  fix) and renders. macOS Dock-on-settings implemented (code; not visually confirmed).
- Backend live: `ready: true`, `indexed_count: 337`, `provider: local`.

## Redesign scope note

Rahul's "ui improve and output improve" commit reworks **both** the settings
window (views 16–21) **and** the entire answer/output surface (views 1–15):
`MagpieWindow`, `AnswerCard`, `SourcesCard`, `citations`, `PreviewCard`/`PdfPreview`,
`QuestionCard`, `NotFoundCard`, `WelcomeCard`, `StatusFooter`, plus new
`dragWindow.ts`, self-hosted **Inter** font, and design tokens
(`styles/tokens.css`, `styles/globals.css`). The port is **additive** to
`api.ts`/`types.ts` (keep every `main` consumer; only add what new components need).
States with no thinkpad design (e.g. some empty/error states) get designed to fit.
