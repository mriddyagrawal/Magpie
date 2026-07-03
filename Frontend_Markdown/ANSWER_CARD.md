# AnswerCard

The card that displays the LLM's response after a query completes.
It is a pure presentational component — no state, no fetching. All data
flows in as props from `MagpieWindow`.

Component: [frontend/src/components/AnswerCard.tsx](../frontend/src/components/AnswerCard.tsx)

---

## What it shows

```
┌─────────────────────────────────────────────────────────────┐
│ ANSWER                                                       │
│                                                              │
│  Dr. Brown teaches Physics and is located in room SC-214.   │
│  Office hours are Tuesdays 2–4 PM.                          │
│                                                              │
│  + follow up                                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## States

Three mutually exclusive states, checked in this priority order:

| Priority | Condition | What renders |
|---|---|---|
| 1 (highest) | `error !== null` | `⚠ <error message>` in `.answer-card__error` |
| 2 | `loading === true` | Three animated dots (`.answer-card__dot`) |
| 3 (default) | otherwise | Answer text through `Highlighted` |

**Loading dots:** three `<span class="answer-card__dot" />` elements inside
`.answer-card__loading`. Animation is CSS-driven — the component does not
manage timers.

**Error:** shows the raw error string from the failed `/query` fetch, prefixed
with `⚠`. The follow-up button is hidden during error state.

**Answer:** the LLM's answer string is passed through `Highlighted` with the
`highlights[]` token list. Matching tokens are wrapped in
`<mark class="magpie-highlight">`.

---

## Follow-up button

`+ follow up` appears below the answer text. Hidden during loading and error.

```ts
<button className="answer-card__followup" onClick={onFollowUp} type="button">
  + follow up
</button>
```

`onFollowUp` in `MagpieWindow` is:

```ts
onFollowUp={() => inputRef.current?.focus()}
```

Clicking it re-focuses the search input so the user can type a follow-up
question without touching the mouse.

---

## Props

| Prop | Type | Source |
|---|---|---|
| `answer` | `string` | `result.answer` from `/query` response |
| `highlights` | `string[]` | `extractHighlightTokens(result.answer)` computed in MagpieWindow |
| `loading` | `boolean` | `loading` state in MagpieWindow |
| `error` | `string \| null` | `error` state in MagpieWindow |
| `onFollowUp` | `() => void` | re-focuses the search input |

---

## Where highlights come from

`highlights` is computed once in `MagpieWindow` via `useMemo`:

```ts
const highlights = useMemo(
  () => (result ? extractHighlightTokens(result.answer) : []),
  [result]
);
```

The same `highlights[]` array is passed to `SourcesCard` (for snippet text)
and to the preview components (`CsvPreview`, `TextPreview`) for content text.
See [HIGHLIGHTED.md](./HIGHLIGHTED.md) for what patterns are extracted.

---

## StatusPill

`StatusPill` renders below the entire results grid (not inside `AnswerCard`)
whenever `active === true`:

```ts
{active && <StatusPill />}
```

It shows a readiness dot and `"N documents indexed"`. It fetches `GET /status`
once on mount, shows nothing if the fetch fails. The dot uses `.status-pill__dot--off`
when `status.ready` is false.

Component: [frontend/src/components/StatusPill.tsx](../frontend/src/components/StatusPill.tsx) · L7

---

## Code references

| Symbol | File | Line |
|---|---|---|
| `AnswerCard` component | [AnswerCard.tsx](../frontend/src/components/AnswerCard.tsx) | L13 |
| `Highlighted` in answer | [AnswerCard.tsx](../frontend/src/components/AnswerCard.tsx) | L27 |
| follow-up button | [AnswerCard.tsx](../frontend/src/components/AnswerCard.tsx) | L31 |
| highlights useMemo | [MagpieWindow.tsx](../frontend/src/components/MagpieWindow.tsx) | L132 |
| `extractHighlightTokens` | [Highlighted.tsx](../frontend/src/components/Highlighted.tsx) | L66 |
| `StatusPill` component | [StatusPill.tsx](../frontend/src/components/StatusPill.tsx) | L7 |
| StatusPill render site | [MagpieWindow.tsx](../frontend/src/components/MagpieWindow.tsx) | L314 |
