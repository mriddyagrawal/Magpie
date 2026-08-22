# Magpie window lifecycle

The reference for *when does the main window hide vs close vs destroy?*,
*when is `anchor_spotlight()` allowed to fire?*, and *what's preserved
across hide/show vs Cmd-Q?* — written so future changes don't re-litigate
decisions Magpie's already paid for in commits-and-reverts.

The contents here are normative for the `main` (ask-bar) window. The
`settings` window is a normal app window and not covered.

---

## Goals

The `main` window is a **Spotlight-style accessory window**:

- No Dock icon (`ActivationPolicy::Accessory` on macOS).
- Summoned by global shortcut, tray click, macOS Spotlight reopen, or
  `Cmd-Tab`-equivalent paths.
- Hidden — not destroyed — when dismissed.
- Always-on-top while visible.
- Centered horizontally near the top of the active monitor on first show
  (the "Spotlight anchor"); preserves user-dragged position thereafter.

Tauri's defaults assume a normal windowed app (visible by default, lifecycle
tied to window-close, dock icon present). Every behavior below is the cost
of fighting those defaults to get a Spotlight-style UX.

---

## Window states

| State | Definition | OS observable? |
|---|---|---|
| **Hidden** | Window object exists; React + WebView keep running; user can't see or focus it. | No |
| **Visible** | Window is on screen and (usually) focused. | Yes |
| **Destroyed** | Window object freed. Only happens at app quit. | No (app is gone) |

There is **no** "minimized" state for the main window. Minimize is mapped
to hide at the OS level.

The window is **created hidden during `setup()`** (anchored to the
Spotlight position during creation but never shown). The first user
trigger shows it.

---

## Transitions

### Show

The window goes hidden → visible on **any** of these triggers:

1. Global shortcut press
2. Tray icon click
3. macOS `Cmd-Space → Magpie` (`RunEvent::Reopen` event)
4. macOS Dock menu "Open Magpie" (when applicable)
5. macOS menu accelerator (`Cmd+,` for settings opens settings, not main)
6. CLI `open -a Magpie` (also fires `RunEvent::Reopen`)

Every show path runs the same logic:

```
anchor_spotlight_once(&window);   // see §Position below
window.show();
window.set_focus();
```

### Hide

The window goes visible → hidden on **any** of these triggers:

1. `Esc` key while view is `resting` (frontend `MagpieWindow.tsx`)
2. Window loses focus / blur (PR 4 fix #1 — currently active on macOS)
3. The same trigger that toggled it open, if `is_visible() == true`
   (global shortcut acts as a toggle — same key both summons and dismisses)
4. Frontend `hideWindow()` invocation from any view-state handler that
   needs to dismiss

`hideWindow()` MUST NOT call `setSize()` before hiding. An earlier version
shrank the window to `HEIGHT_RESTING_EMPTY` for a "next summon appears
compact" effect. This broke state preservation on re-summon — the
`useEffect` resize hook saw no dep change across hide/show, so the window
stayed at 96px with the answering body clipped. The fix and explanation
live in the comment at `MagpieWindow.tsx:hideWindow()`.

### Destroy

The window is destroyed only when:

1. App receives `RunEvent::Exit` (Cmd-Q, Quit menu, system shutdown).
2. `WindowEvent::CloseRequested` is intercepted (`lib.rs:on_window_event`)
   and explicitly hides instead of closing — so a user clicking a close
   button never destroys.

There is **no** code path where the main window is destroyed and re-created
during normal operation. Destroying and re-creating loses React state,
defeats hide-to-preserve, and would require persistence machinery we
don't currently have.

---

## Position

### `anchor_spotlight()` — when it runs

The `anchor_spotlight()` function sets the window position to:
- `x` = horizontally centered on the current (or primary) monitor
- `y` = 22% of the screen height from the top

This is the visual position users associate with macOS Spotlight.

**Anchor is process-scoped, not call-scoped.** The function is gated by
a session-lifetime `AtomicBool` and only runs *the first time* it's
invoked per process — implemented as `anchor_spotlight_once()`. All
existing call sites (setup, every show path) use the gated wrapper.

| Scenario | Anchor fires? |
|---|---|
| First launch, first show | ✅ Yes (atomic flips to true) |
| Subsequent show in same session | ❌ Skipped — Tauri's `hide()` preserves the last position |
| User drags the window, then summons again | ❌ Skipped — user position preserved |
| Cmd-Q → relaunch | ✅ Yes — process-scoped flag re-initializes to false |
| Crash → relaunch | ✅ Yes — same as above |

There is intentionally **no cross-launch persistence** of window position.
A fresh launch always centers; that's a UX choice, not a missing feature.
If users start asking for it, the path is `tauri-plugin-window-state` —
add the plugin, decide on conflict resolution between saved position and
`anchor_spotlight_once` (likely: only anchor if no saved position exists).

### Why we still need `anchor_spotlight()` at all

`hide()` preserves position only after the window has been positioned at
least once. On first launch the window has no position; Tauri uses
`tauri.conf.json`'s default (typically OS-determined → not where users
expect a Spotlight-style window). So the function can't be deleted; it
can only be gated.

### Multi-monitor

`anchor_spotlight()` uses `window.current_monitor()` first, falling back
to `primary_monitor()`. After the first show, position is preserved by
Tauri — including across monitor disconnects. If a saved position lands
on a disconnected monitor, behavior is OS-dependent (macOS typically
clamps to the primary monitor's bounds; Windows may leave the window
off-screen). Not currently handled explicitly.

---

## State preservation

The contract for what survives each transition:

| What | Hide → show (same session) | Cmd-Q → launch |
|---|---|---|
| React state (component tree, hooks, refs) | ✅ Preserved | ❌ Lost |
| `view.kind` and its payload (question, sources, answer) | ✅ Preserved | ❌ Lost |
| In-flight `/query` request | ✅ Continues running on backend; result renders on completion regardless of window visibility | ❌ Sidecar restarts; request lost |
| Recents list (`recents.json`) | ✅ Preserved (persisted to disk) | ✅ Preserved |
| Conversation history (in-memory follow-ups) | ✅ Preserved | ❌ Lost |
| Window position | ✅ Preserved (after the anchor-once gate) | ❌ Lost (re-anchored) |
| Window size | ✅ Preserved (intentional — see hideWindow comment) | ❌ Lost |
| Cached query replays | ✅ Preserved | ✅ Preserved (manifest-keyed) |

**Why React state survives hide:** the WebView keeps running while
hidden. `getCurrentWindow().hide()` is an OS-level visibility toggle, not
a tear-down. The DOM, React tree, all timers and pending fetches stay
alive.

**Why in-flight requests are not aborted on hide:** Plan #27 (abort
in-flight on Esc / new submit) was committed (`698f832`) and reverted
(`3245586`) without a replacement. The current state is: querygen counter
(defense-in-depth) drops late responses if the user starts a new query
before the old one returns; nothing actively cancels the backend work.
See "Future considerations" below.

---

## Constraints and invariants

These should hold for every change to window lifecycle code. Violating
any of them has previously caused regressions (referenced commits).

1. **The main window is never destroyed except on app quit.** Anything
   that looks like "close" must be `hide()` instead. Owned by
   `on_window_event` intercepting `CloseRequested`.

2. **`hideWindow()` must not resize before hiding.** Resizing to a
   compact size on hide breaks state-display correlation on re-summon
   because the resize `useEffect`'s deps don't recompute across hide/show.
   See `MagpieWindow.tsx:hideWindow()` comment.

3. **Every show path must go through `anchor_spotlight_once`** (not
   bare `anchor_spotlight`). Bare calls re-anchor on every summon and
   override the user's dragged position.

4. **Window size on show must match `view.kind`.** The resize `useEffect`
   in `MagpieWindow.tsx` owns this; `HEIGHTS` map drives heights. Don't
   call `set_size()` from Rust on show — let the React-side hook do it.

5. **No new code path may set window position outside
   `anchor_spotlight*`.** All position writes flow through one function
   so the gate is the only escape valve to think about.

---

## Future considerations

These are intentionally not implemented today; documented so the next
person doesn't reach for them without a reason.

- **`tauri-plugin-window-state`** — cross-launch position/size
  persistence. Out of scope; users explicitly asked for "fresh start
  each launch is fine, just don't lose position within a session."

- **Cross-launch view-state persistence** — would require persisting
  `view` to disk (probably localStorage), rehydrating on mount, and
  reconciling in-flight `retrieving` states (the original backend job
  is gone after a quit). Large surface area; not justified by current
  use cases.

- **Plan #27 (abort in-flight queries)** — the wire to actually
  cancel backend work on Esc / new submit. Reverted previously. Will
  require: frontend `AbortController`, server-side
  `request.is_disconnected()` plumbing, asyncio cancellation
  propagation, and llama-server slot release / SSE close. Estimated
  ~200-500 LOC + careful integration with the view machine.

- **Streaming answers (local Gemma + cloud)** — would change the
  `answering` view to incrementally append tokens. Lifecycle-orthogonal
  but interacts with abort: streaming naturally surfaces "user
  abandoned" via TCP disconnect, which is a cheap-ish path to partial
  abort even without Plan #27.

---

## Code anchors

- `frontend/src-tauri/src/lib.rs:anchor_spotlight` — position function.
- `frontend/src-tauri/src/lib.rs:anchor_spotlight_once` — gated wrapper.
- `frontend/src-tauri/src/lib.rs:on_window_event` — `CloseRequested`
  interception (hide instead of destroy).
- `frontend/src-tauri/src/lib.rs:RunEvent::Reopen` handler — macOS
  re-summon path.
- `frontend/src/components/MagpieWindow.tsx:hideWindow()` — frontend
  hide (no resize before hide).
- `frontend/src/components/MagpieWindow.tsx:onKey (Escape)` — Esc
  handler dispatch.
