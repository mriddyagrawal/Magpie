# QuestionCard

The persistent top bar of the Magpie window — search input, logo, shortcut
hint, and settings gear. It is always visible: in the compact idle state, during
indexing, and while results are shown.

Component: [frontend/src/components/QuestionCard.tsx](../frontend/src/components/QuestionCard.tsx)

---

## What it shows

**Search mode** (no query submitted yet):

```
┌─────────────────────────────────────────────────────────────────────┐
│  [logo]  Ask magpie                          Alt+Space   ⚙          │
└─────────────────────────────────────────────────────────────────────┘
```

**Active mode** (query submitted, results showing):

```
┌─────────────────────────────────────────────────────────────────────┐
│  [logo]  What room is Dr. Brown in?          Alt+Space   ⚙          │
└─────────────────────────────────────────────────────────────────────┘
```

In active mode the input is replaced by a `<div>` showing the submitted
question as static text. The user cannot edit mid-query.

---

## Two display modes

The component derives its mode from `submittedQuestion`:

```ts
const isActive = submittedQuestion !== null;
const display = submittedQuestion ?? value;
```

| Mode | `isActive` | What renders in the middle |
|---|---|---|
| Search | `false` | `<input>` — editable, receives key events |
| Active | `true` | `<div class="question-card__title">` — shows submitted text, not editable |

The `is-active` CSS class is applied to the outer `<div>` when `isActive` is
true, allowing CSS to adjust layout or style.

---

## Logo

```ts
<picture>
  <source srcSet={magpieLogoLight} media="(prefers-color-scheme: light)" />
  <img src={magpieLogoDark} alt="Magpie" className={`question-card__logo ${value || isActive ? "is-active" : ""}`} />
</picture>
```

Two transparent PNG assets:
- `magpie-logo-dark.png` — default (dark-mode vibrancy background)
- `magpie-logo-light.png` — swapped in by the `<picture>` media query when
  the system is in light mode

The `is-active` class on the `<img>` fires when the user has typed anything
(`value`) or submitted a query (`isActive`). CSS uses this for a colour or
opacity transition.

---

## Input behaviour

| Property | Value |
|---|---|
| Placeholder | `"Starting Magpie…"` while `booting`, otherwise `"Ask magpie"` |
| Disabled | while `loading === true` OR `booting === true` |
| Submit trigger | `Enter` (without `Shift`) |
| `spellCheck` | `false` |
| `autoComplete` | `"off"` |

The input ref is forwarded from `MagpieWindow` via `forwardRef`. MagpieWindow
manages focus programmatically (on boot, on re-summon) through this ref.

---

## Drag behaviour

Clicking anywhere on the card that is **not** an interactive element starts a
Tauri window drag:

```ts
const INTERACTIVE = "input, textarea, button, [role=button], [contenteditable]";

function startDragOnMouseDown(e: React.MouseEvent) {
  if (e.button !== 0) return;
  const target = e.target as HTMLElement;
  if (target.closest(INTERACTIVE)) return;
  getCurrentWindow().startDragging();
}
```

The card also carries `data-tauri-drag-region` as a fallback, but the explicit
`startDragging()` call is used because `data-tauri-drag-region` can fail to
pick up events through the macOS backdrop-filter / vibrancy layer.

Interactive elements (input, settings button) are explicitly excluded so clicks
on them don't accidentally start a drag.

---

## Settings gear

```ts
<button
  className="question-card__settings-btn"
  onClick={onOpenSettings}
  tabIndex={-1}
  aria-label="Open settings"
>
  ⚙
</button>
```

`tabIndex={-1}` keeps the button out of the tab order — the user is expected
to reach it via mouse or touch. Clicking it invokes `open_settings` Tauri
command, which opens the `SettingsWindow` as a separate webview.

---

## Shortcut label

```ts
<kbd className="question-card__hint">
  {shortcutLabel}
</kbd>
```

`shortcutLabel` is loaded from `GET /settings/shortcut` at boot time and
stored in MagpieWindow state. It shows the currently registered shortcut
string (e.g. `Alt+Space`, `Ctrl+Space`). It is display-only — clicking the
`<kbd>` does nothing.

---

## Props

| Prop | Type | Purpose |
|---|---|---|
| `ref` (forwarded) | `RefObject<HTMLInputElement>` | MagpieWindow focuses the input programmatically |
| `value` | `string` | Current input content (controlled) |
| `onChange` | `(v: string) => void` | Updates query state in MagpieWindow |
| `onSubmit` | `() => void` | Fires the query |
| `loading` | `boolean` | Disables input while request is in-flight |
| `booting` | `boolean` | Disables input and shows "Starting Magpie…" |
| `submittedQuestion` | `string \| null` | Non-null → active mode, shows this string |
| `onOpenSettings` | `() => void` | Settings gear click handler |
| `shortcutLabel` | `string` | Shortcut string shown in `<kbd>` |

---

## Code references

| Symbol | File | Line |
|---|---|---|
| `QuestionCard` component | [QuestionCard.tsx](../frontend/src/components/QuestionCard.tsx) | L38 |
| `startDragOnMouseDown` | [QuestionCard.tsx](../frontend/src/components/QuestionCard.tsx) | L27 |
| logo `<picture>` | [QuestionCard.tsx](../frontend/src/components/QuestionCard.tsx) | L54 |
| input element | [QuestionCard.tsx](../frontend/src/components/QuestionCard.tsx) | L68 |
| settings button | [QuestionCard.tsx](../frontend/src/components/QuestionCard.tsx) | L88 |
| shortcut `<kbd>` | [QuestionCard.tsx](../frontend/src/components/QuestionCard.tsx) | L85 |
| `shortcutLabel` state | [MagpieWindow.tsx](../frontend/src/components/MagpieWindow.tsx) | L40 |
| `handleOpenSettings` | [MagpieWindow.tsx](../frontend/src/components/MagpieWindow.tsx) | L122 |
