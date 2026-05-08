# UI branch — Implementation Plan

> Plan-of-record for the `UI` branch. Authoritative for: what we're
> shipping, what order, where the seams are, what's *not* in scope.
> Mirrors the convention of `Plans/Ingestion Rules/Implementation Plan.md`.

## Goal

Rebuild Magpie's two user-facing surfaces — the ask bar (spotlight
window) and the settings window — to match the design captured in
`Specs/UI/`. Wire the backend changes those surfaces require: the
not-found answer state, the persistent recents store, and the
layered-config story (`magpie_defaults.json` + `settings.json` +
`secrets.json` + env-var overrides) that finally retires `.env` for
bundled-app users.

## Branch / lineage

- Branch: `UI` (off `front-back`)
- Base diff target: `origin/front-back`
- Commit style: each PR-equivalent step lands as one commit on this
  branch. Push-when-greenlit; no auto-push.

## Status snapshot

| Step | Description | Status |
|---|---|---|
| **Step 1** | Specs (product / ask bar / settings) + Plan #25 + mockups | ✅ committed (`0f5f22c`) |
| **Step 2** | Answer schema + recents backend + endpoints | ✅ committed (`6c7c1fa`) |
| **Step 3** | Layered config + settings endpoints | not started |
| **Step 4** | Ask bar full rewrite (`MagpieWindow.tsx`) | not started |
| **Step 5** | Settings window full rewrite (`SettingsWindow.tsx`) | not started |
| **Step 6** | Polish: real-corpus smoke test, light/dark, cross-platform | not started |

## PR decomposition

Each step below maps to one reviewable PR. Steps 1+2 already landed
as commits on this branch and would split cleanly in a PR-friendly
flow.

### PR 1 — Specs ✅ (`0f5f22c`)

Scope: `Specs/UI/*.md` triplet (product, ask bar, settings) + the
user's mockup PNGs + Plan #24 (batch indexing). No code changes.
Self-contained design hand-off.

**Reviewable for:** product correctness, vocabulary, what's
out-of-scope vs in-scope. The reviewer is "future me reading this in
three weeks" or a designer who has never seen the codebase.

### PR 2 — Backend: not_found schema + recents store ✅ (`6c7c1fa`)

Scope:
- `Answer` model gains `not_found: bool` + `not_found_topic: str`
  (flat-with-discriminator shape, not a discriminated union — see
  Plan #25 for the small-model rationale).
- System prompt teaches the model when to set them; also requires
  inline `[1]`-style citation markers in prose.
- `PipelineResult.not_found` / `not_found_topic` surface through.
  Empty-retrieval branch synthesizes `not_found=True` for UX
  consistency.
- `QueryResponse` exposes the new fields + `sources_scanned_count`
  + `recent_id`.
- `/query` persists each ask to `recents.json`. `GET /recents`
  lists; `GET /recents/{id}` replays.
- `src/recents.py` (new) — load/save/append, capped at 10, atomic
  writes.

**Reviewable for:** schema correctness, prompt cleanliness, recents
persistence semantics (atomic write, malformed-entry skipping,
non-fatal failure mode). Frontend untouched — this PR is shipped
soft because the new response fields default safely and existing
clients ignore them.

### PR 3 — Layered config + settings endpoints + Sync/Reindex

Scope:
- `src/config/settings.py` (new) — load/save `settings.json` with
  env-var override:
  ```
  env var > settings.json > magpie_defaults.json > hardcoded
  ```
- Extend `magpie_defaults.json` with the keys the UI exposes
  (provider, top_k, rewrite_default, temperature, theme, accent,
  launch_at_login, default_action).
- New endpoints (per `Specs/UI/settings_window.md`):
  - `GET /settings/search` / `PATCH /settings/search`
  - `GET /settings/search/providers`
  - `POST /settings/search/local/download` + `GET /settings/search/local/download`
  - `GET /settings/app` / `PATCH /settings/app`
  - `PUT /settings/shortcut` (writes shortcut.json from the UI)
  - `PATCH /settings/folders/{id}` — toggle, rename
  - `GET /settings/exclusions` + the four mutation endpoints
- **Sync vs Reindex (the two-button design — see "Indexing
  triggers" section below):**
  - `POST /index/sync` — apply current indexing rules: pick up new
    files, drop files that no longer match (per indexing_rules.json's
    exclusions / removed include_paths), update changed files. Does
    NOT re-summarize unchanged files. The everyday button.
  - `POST /index/reindex` — drop the entire index, then sync. The
    nuclear button. Same as `just reset-index && just sync` today.
- Plumb the provider switch (Local vs Cloud) into `src/llm.py`'s
  `get_llm()` so the answer pipeline picks up `settings.json`.
  `LLM_PROVIDER` env still wins. Cloud routes through the
  env-backed `CLOUD_PROVIDER` / `CLOUD_API_KEY` / `CLOUD_MODEL` —
  see the Cloud-in-v1 decision above.

**NOT in this PR:**
- `secrets.json` and the API Keys tab — parked behind the future
  "Advanced" sidebar (see `Specs/UI/settings_window.md`'s out-of-scope).
- Per-folder `sync` / `pause` / `cancel` endpoints — replaced by the
  global Sync/Reindex buttons for v1. Per-folder controls land when
  we ship the file-watcher (see Indexing triggers section).
- OS keychain integration from Plan #19 — parked further still.

**Risk:** touches the provider-selection seam. Smoke-test `just sync`
and `just chat` after to confirm dev mode unchanged.

### PR 4 — Ask bar full rewrite

Scope: full rewrite of `frontend/src/components/MagpieWindow.tsx`
to the five-state model in `Specs/UI/ask_bar.md`.

- New components (split out of MagpieWindow):
  - `<RecentsPanel>` — fetches `GET /recents`, ↑/↓ navigation, ⏎ to
    replay (rehydrate from cached `result` payload, no LLM call),
    persists across renders.
  - `<StatusFooter>` — universal "● Ready · Local · Gemma 4 ·
    4,408 documents understood" + per-state keyboard hints.
  - `<NotFoundCard>` — single "Add folder where this knowledge
    might live" CTA that calls a Tauri command to deep-link into
    Settings → Data → folder picker.
  - `<RetrievingPanel>` — skeleton list of source rows with live
    "▷ reading… / ✓ used / ○ skipped" transitions.
  - `<AnswerCard>` — citation pill rendering: parse `[N]` markers
    in answer prose, render as styled spans linked to source rows.
- Preserved from current build:
  - The two-column answering layout (left: answer + sources;
    right: preview pane). Cloud Design's no-preview alternative
    explicitly rejected per user direction.
  - The indexing-progress onboard card from Rahul's build (which
    we keep — it's the "Magpie is reading new files" surface) —
    extracted into its own component but functionally unchanged.
- Removed:
  - The "SUGGESTIONS" / completions section (per user direction).
  - The needs-index empty state — folded into `<NotFoundCard>`'s
    CTA (no folders is just a special case of "Magpie can't answer
    because nothing's indexed").
- New API client surface in `frontend/src/api.ts`:
  - `getRecents()`, `getRecent(id)` — recents
  - QueryResponse type extended with `not_found`,
    `not_found_topic`, `sources_scanned_count`, `recent_id`

**Tauri command to add:** `open_settings_with_action({ action:
"add-folder" })` — opens the settings window with a query param
that the SettingsWindow reads on mount and immediately invokes the
folder picker. (Per user direction: "use the easiest way possible.")

**Risk:** the existing MagpieWindow is ~330 LOC and is one of the
most-touched files. A full rewrite is ~600 LOC of new code.
Smoke-test ALL ask-bar flows: warm boot, cold boot, indexing in
progress, real ask, not-found ask, recents replay, esc-from-each-
state.

### PR 5 — Settings window full rewrite

Scope: full rewrite of `frontend/src/components/SettingsWindow.tsx`
to match `Specs/UI/settings_window.md` and the mockups.

- Layout: sidebar nav (3 entries + status footer) + main content +
  header strip with status pill.
- Per-tab implementations:
  - **Data** — folder/file rows with status pills, in-progress
    sub-state with pause/cancel, add-folder/file dropdown,
    exclusions sub-panel.
  - **Search & AI** — binary Local/Cloud cards, advanced expander
    (top_k, rewrite, temperature), local-model download flow,
    Cloud first-pick confirm.
  - **Shortcut & App** — shortcut chips + inline recorder, theme
    segmented control, accent radio (Ink/Amber/Jade/Rose), launch
    toggles, default-action dropdown, version/About card.
- Reads on mount: `?action=add-folder` query param triggers folder
  picker immediately (the deep-link from PR 4's NotFoundCard).
- Vocabulary changes throughout: "Data" not "Folders", "read /
  understand / understood" instead of "ingest / index / indexed".
- Cross-platform: relies on Tauri's native chrome (already fine).

**Replaces:** Rahul's `SettingsWindow.tsx` and CSS in full. The user
has authorized purging.

### PR 6 — Polish + smoke-test

Scope: nothing structural; just the verification pass.

- Run real corpus end-to-end through every ask-bar state:
  - Resting → typing → recents
  - Recents replay → cached render
  - Fresh ask → retrieving → answering with citations
  - Not-found ask → CTA → Settings deep-link → folder added →
    re-ask
- Theme correctness: dark + light, both windows, all tabs.
- Cross-platform smoke: verify Windows + Linux mockup look matches
  on real OS (or at least Windows; we don't have a Linux test box).
- Update CLAUDE.md or `Specs/UI/*.md` if anything drifted during
  implementation.

## Order of operations

PR 1 ✅ → PR 2 ✅ → **PR 3** → **PR 4** (parallel with PR 3) → **PR 5** → PR 6

PR 4 (ask bar) only needs PR 2's response shape. It can ship before
the settings window rewrite if we leave the deep-link CTA stubbed
(opens settings to first tab; user navigates manually).

PR 5 (settings) needs PR 3's endpoints to do anything beyond what
exists today.

## Resolved design decisions

These were open questions; recording the resolutions so reviewers
can see why we picked each option.

### "Cloud" in v1 — implicit, env-backed (option (b) per the original menu)

User direction: "Cloud in V1 should be implicit. The user is not
allowed to edit the API keys and stuff. Maybe in the [secrets/env]
file, write something as default provider and then default API
key."

Implementation:
- Two new vars in `.env.example` (and the runtime `.env` for dev):
  ```
  # The provider invoked when the user picks "Cloud" in Settings.
  # User cannot override these from the UI in v1. Bundled-app users
  # get whatever values ship in magpie_defaults.json (PR 3 bakes a
  # subsidized key in if/when we have one); dev users keep their
  # .env values.
  CLOUD_PROVIDER=openrouter
  CLOUD_API_KEY=<shipped key or user's dev key>
  CLOUD_MODEL=google/gemma-4-26b-a4b-it:free
  ```
- The Search & AI tab's "Cloud" card is a *user-facing alias* for
  whatever CLOUD_PROVIDER points at. The user never sees
  "OpenRouter" or "Moonshot" in the UI — just "Cloud."
- Provider selection in `src/llm.py`: when `settings.json`'s
  provider is `"cloud"`, resolve `CLOUD_PROVIDER` / `CLOUD_API_KEY`
  / `CLOUD_MODEL` from env (or defaults), instantiate the matching
  client. When provider is `"local"`, llama-server pool path
  (today's behavior).
- API Keys tab stays parked. Bring-your-own is a future addition
  when (1) we add a second cloud provider, or (2) the bundled
  subsidy is unsustainable.

### Citation overflow — plain-text fallback

User direction: "do whatever you want."

Implementation: when the answer emits `[N]` and N > len(sources_used),
render the marker as plain text (no pill, no link). Log a console
warning. The user sees `[5]` literally in the prose; the answer
remains readable. Same fallback when N < 1.

### Recents replay — confirmed "↻ Ask again" affordance

User direction: "Yeah, I sort of like that. On the right side of
every recent question people can press the Ask Again button."

Implementation: each row in the recents panel shows a `↻ Ask again`
button on the right side (mirroring the relative-timestamp's
position; designer in PR 4 decides whether the timestamp slides up
or stacks). Click on the row body = replay cached. Click on Ask
Again = replay cached AND fire a fresh `/query` call in the
background, replacing the cached payload when it lands. The recents
entry's `id` is preserved (we update it in place — same `asked_at`,
same `id`, fresh `result`).

## Active design decisions still open

### Settings entry points — pick the surfaces

How does the user open the settings window? Five candidate surfaces;
v1 should ship at least two. Asking the user to pick.

| # | Surface | Discoverability | Cost to implement |
|---|---|---|---|
| 1 | **Gear icon in the ask bar** (top-right of the search bar — already exists in Rahul's build) | High; always on screen when the ask bar is open | None — already works |
| 2 | **`Cmd ,` / `Ctrl ,`** keyboard shortcut from the ask bar | Medium; standard OS-prefs convention | Low — one Tauri global shortcut |
| 3 | **System tray menu → "Settings…"** | High; right-click on the menu-bar icon | Low — extend `lib.rs`'s tray menu (currently just "Quit") |
| 4 | **macOS menu bar → Magpie → Settings…** (`Cmd ,` is its standard accelerator) | High on macOS; nonexistent elsewhere | Low — Tauri menu API |
| 5 | **Deep-link from Not Found state's "Add folder" CTA** | High when needed; not a general entry point | Already required for PR 4 |

Recommendation: ship **1 + 3 + 4**. Gear icon stays (cheap and
visible), tray menu adds the standard "open prefs" entry, macOS
menu bar gets the native `Cmd ,` for free. Skip 2 — it'd conflict
with the in-app input field's focus when the ask bar is showing.

(5 isn't a "settings entry point" in the menu sense; it's a
deep-linked sub-view that happens to land on Settings.)

## Indexing triggers — Sync vs Reindex (v1 design)

We have not yet landed on a long-term answer for *how* and *when*
Magpie re-indexes files (file watcher, scheduled re-sync, on-demand,
some hybrid). For v1 we deliberately punt the autonomy question
and ship two manual buttons in **Settings → Data**:

- **Sync** (primary, accent color) — runs the everyday reconciliation:
  - Walks each `include_path` per current `indexing_rules.json`.
  - Picks up files that are new since last index (added paths,
    new files in already-indexed folders, files whose mtime is
    newer than their manifest entry).
  - Drops files that should no longer be in the index because:
    - Their parent `include_path` was removed from the rules, OR
    - A new `exclude_path` / `exclude_glob` rule now matches them, OR
    - The file was deleted from disk.
  - Does NOT re-read or re-embed unchanged files. Cheap.
  - Equivalent to `just sync` today, but with the manifest-aware
    drift detection (Plan #21) doing the work.

- **Reindex** (secondary, destructive-styled) — nuclear option:
  - Drops the entire search index (Qdrant collection + manifest).
  - Then runs Sync from a clean slate.
  - Equivalent to `just reset-index && just sync` today.
  - Confirmation modal: "Reindex everything? This rebuilds Magpie's
    understanding of all your folders. It can take 10–60 minutes
    depending on how much you've added. Your files are not
    touched."

Why both buttons in v1:
- Sync handles the 99% case (you added a folder, you renamed
  some files, you deleted some files). It's safe to run anytime —
  idempotent, won't double-index.
- Reindex is the escape hatch for "Magpie is confused / I changed
  the indexing rules in a non-obvious way / I want a fresh start."
  Keeping it as a separate button (vs. a hidden CLI command) lets
  power users self-service without us having to ship a daemon-grade
  watcher just to recover from edge cases.

What we are NOT shipping in v1:
- **File watcher / FSEvents / inotify daemon.** We need it eventually
  (the "Magpie picks up new files automatically" promise from the
  product description), but designing the right backoff, batching,
  and pause-during-bulk-edits behavior is meaningful effort. Punt
  to a separate plan.
- **Scheduled re-sync** (e.g., every 6 hours). Could ship as a
  toggle in Shortcut & App, but not v1.
- **Per-folder sync controls.** Each folder in the Data tab has a
  `↻` icon button per the spec, but in v1 it's a no-op or it
  triggers a global Sync filtered to that folder's path
  (designer's call). The two top-level buttons are the primary
  surface.

The Plan #21 entry in `Plans/Future Plans.md` covers the manifest
drift-detection work that Sync depends on; that one's already
shipped (`02a0e6b` and earlier).

A future Plan entry — call it Plan #26, to be added as part of PR 3
— should capture the file-watcher decision, what triggers it, what
its UX looks like, and why we didn't ship it in v1. Track it as a
follow-up so we don't lose the context.

## What is NOT in this branch

These are deliberately out of scope. They land in their own
branches when triggers fire (see `Specs/UI/settings_window.md` for
the per-feature trigger conditions):

- **API Keys tab** — bundled-Cloud (option 1.b) sidesteps it for v1.
- **Index Health tab** — parked.
- **Backups tab** — parked.
- **Indexing rules editor** — parked.
- **LLM-server runtime knobs** — parked.
- **Plan #25 evaluation** — the doc says when to do it; doing it
  is a separate effort that needs ground-truth citations on the
  benchmark sets first.
- **Plan #24 batch-progress UI** — same; doc only.
- **OS keychain integration (Plan #19, full)** — only the
  settings.json + magpie_defaults.json layer in PR 3. Keychain
  punted with API Keys.
- **MLX backend (Plan #23)** — parallel concern; not user-facing.

## Risks / things to watch

- **Provider-switch seam (PR 3 risk).** `src/llm.py` and
  `src/inference/profiles.py` already gate provider selection on
  env vars. Layering settings.json on top of that without breaking
  dev mode (`just sync`, `just chat` from a checkout) is delicate.
  Do real CLI smoke-tests, not just unit tests.
- **Frontend rewrite churn (PR 4, 5 risk).** Rahul's
  `MagpieWindow.tsx` and `SettingsWindow.tsx` are being replaced
  wholesale. If the rewrite has bugs, we lose his working
  indexing-progress UX too. Mitigation: extract the
  indexing-progress sub-component verbatim before rewriting the
  parent; it stays a known-good island in the new file.
- **Recents replay vs. file changes.** A cached answer may be
  invalidated by index changes. v1 just shows the cached answer;
  the user can re-fire. Document this behavior clearly in the UI
  (the "↻ ask again" affordance in question 3 above).
- **Cross-platform window chrome (PR 5, 6 risk).** Tauri 2 handles
  most of this, but per-platform rendering needs a real OS test.
  We have macOS; Windows test in CI is fine; Linux is harder.

## Notes for the future implementer (or future me)

- Each PR-step's commit message should reference this plan section
  (e.g., "Phase B step 3 — layered config" → "Step 3" in the
  status table).
- If a step grows beyond a clean reviewable PR, split it. Don't
  pile non-orthogonal changes into one commit because they're
  "related."
- The ask bar's five-state model is load-bearing. Don't fold
  states together to save lines of code in the rewrite — keep the
  state machine explicit, even if it means a longer file.
- The user's directive on Rahul's code: purge what conflicts with
  the new design. Settings window confirmed for full rewrite. Ask
  bar's indexing-progress onboard card stays (extracted, not
  rewritten); everything else in MagpieWindow.tsx is rewritten.
