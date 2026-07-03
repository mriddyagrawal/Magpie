# Magpie — Taste & Satisfaction Log

> A running record of every substantive answer/deliverable and how Rahul
> reacted to it, so future sessions can *discern his taste* — in design,
> product decisions, and code — instead of re-learning it by shipping
> things he dislikes.
>
> **Convention (same as learning-log.md): APPEND-ONLY.** Every assistant
> deliverable gets a numbered entry. Each entry records:
> - **What was delivered/decided** (one or two lines)
> - **Reaction** — Rahul's actual response, paraphrased or quoted
> - **Satisfaction (1-5)** — inferred from his NEXT message
>   (1 = disliked/frustrated, 2 = asked for rework, 3 = neutral/accepted,
>   4 = approved and built on it, 5 = explicitly pleased).
>   The newest entry stays `pending` until he replies.
> - **Taste lesson** — the transferable rule, if any
>
> Distilled rules live at the top and get amended (date-stamped) as
> evidence accumulates. Entries below are never edited.

---

## Distilled taste profile (update as evidence grows)

*As of 2026-07-03:*

1. **Apple/Spotlight native is the quality bar.** System-font typography,
   bare dot+text status, sentence-case section headers. If a treatment
   wouldn't appear in macOS System Settings, question it.
2. **Allergic to "AI-generated" tells:** colored capsule pills, labeled
   rounded-rectangle chips (accent swatches), emoji-as-icons, `label:
   value` debug tables, `·`-separator chains, placeholder junk ("0 files
   · — ·"), decorative glyphs (✦ star). Prefers bare dots, whitespace
   separation, plain sentences, SVG icons.
3. **No tech leak, ever.** Model names ("Gemma 4"), internal jargon,
   infra terms never reach user-facing surfaces.
4. **One primary action per screen;** secondary actions quiet/borderless.
5. **Cross-platform correctness is a "billion-dollar detail"** (his own
   CLAUDE.md phrase). Windows backslash paths, `Ctrl` vs `⌘`, "Show in
   folder" not "Reveal in Finder". He notices when it's wrong.
6. **Product instinct: perceived speed wins.** Deliberately keeps Qdrant
   out of dev startup so the window opens instantly. When offered
   fix-options, picked *transparency* (status naming + loud errors) over
   *convenience* (auto-start).
7. **Failures must be loud.** Silence when an action doesn't save is
   unacceptable; wants visible, plain-language error surfacing.
8. **Wants tooling used and cited** (ui-ux-pro-max, figma, frontend-design)
   and honest notes when a tool wasn't applicable.

---

## Session 2026-07-03 — Typography, icons, status UX, backend rescue

### 1. Typography overhaul (Roboto Light → SF Pro via -apple-system + bundled Inter, Apple HIG type scale, de-monoed Settings labels)
- **Reaction:** "ok cool" → immediately moved to the next refinement.
- **Satisfaction: 4** — accepted, built on it, no rework requested.
- **Taste lesson:** Spotlight/SF-style typography was exactly the ask;
  weight 400 + 13px body + no remote fonts is the baseline now.

### 2. Used ui-ux-pro-max plugin database to validate font choice (Inter/Inter top pick for the category)
- **Reaction:** Positive — he had installed it specifically wanting it used.
- **Satisfaction: 4**
- **Taste lesson:** He values seeing *which tool said what* — cite the
  plugin's recommendation vs. what we chose.

### 3. Emoji → Lucide SVG icons; "Magpie · Settings" header → active pane name; responsive wrap fixes; "…"-for-Remove replaced with Trash2
- **Reaction:** "ok cool now…" then new list of refinements (accent
  swatches, Gemma 4 leak, dots, footer font, star).
- **Satisfaction: 4** — direction confirmed, momentum continued.
- **Taste lesson:** Structural de-noising (icons, dedup header) matched
  his taste; he then hunts the next layer of detail himself.

### 4. Accent picker as labeled rounded-rect chips (pre-existing design he saw after font pass)
- **Reaction:** "the rectangle with rounded edges looks ugly we have to fix that"
- **Satisfaction: 1 (with the old design)** → rebuilt as macOS-style
  bare color circles with ring-on-selected.
- **Taste lesson:** Rule 2 above — labeled chip/pill controls read as
  template junk to him. Bare, native-style controls.

### 5. Footer said "Reconnecting… · Local · Gemma 4 · 0 documents understood" in mono font
- **Reaction:** Drop Gemma 4, drop all dots, change the font, remove ✦.
- **Satisfaction: 1 (old state) / pending (new)** — implemented: no
  model name, whitespace separation, SF/Inter font, star removed.
- **Taste lesson:** Rules 2 + 3. Mono font reads "terminal-y" to him in
  user-facing chrome.

### 6. Backend rescue: diagnosed Qdrant-down as root cause of "Reconnecting…"/no indexing/mode-not-sticking; started Qdrant, synced 7 files, verified cloud-mode query end-to-end
- **Reaction:** Engaged, explained the intentional design ("we thought
  through qdrant before, the app should open instantly — that's why
  qdrant was not added there earlier"), picked option 2 (transparent
  status + loud errors), rejected option 1 (auto-start Qdrant in dev).
- **Satisfaction: 4** — problem solved; he corrected my product framing.
- **Taste lesson:** Rule 6. Don't propose reverting his deliberate
  architecture trade-offs; work within them.

### 7. Green "ready" capsule pill on folder rows; "0 files · — · not yet read"; "understood:/provider:" sidebar table; three outlined toolbar buttons
- **Reaction:** "dont like the ready ui looks ai"; placeholders
  "whatever"; footer "changed"; boxes "look kinda odd".
- **Satisfaction: 1-2 (old designs)** → all four rebuilt (bare dot
  status, "Not read yet" sentence, plain footer sentences, quiet
  buttons + one primary).
- **Taste lesson:** Rules 1, 2, 4 — this message is the richest single
  source of his visual taste. "Looks AI" = capsule pills + placeholder
  junk + debug tables + everything-boxed.

### 8. Preview card header: full Windows path overlapping the action buttons (doubled text)
- **Reaction:** "buttons text seems overlayed and i cant read the entire
  thing… looks sort of messy"
- **Satisfaction: 1 (bug)** → root-caused: path split on `/` only;
  fixed in 4 components (PreviewCard, SourcesCard, citations, DataTab
  modal) + "Show in folder" wording.
- **Taste lesson:** Rule 5. Test every path-touching surface with
  `C:\...` backslash paths before calling it done.

### 9. This taste log (requested: running log of answers + satisfaction to learn his taste)
- **Reaction:** No comment — moved straight to next issues (footer
  provider label, window dragging).
- **Satisfaction: 3** — accepted silently.
- **Taste lesson:** He invests in meta-systems that make future
  collaboration cheaper (learning log, taste log) — offer these
  proactively when a pattern repeats.

### 10. Footer showed "Local" while Cloud was selected
- **Reaction:** "I have cloud selected it still says local why"
- **Satisfaction: 1 (bug)** → root cause: `providerLabel` was a
  hardcoded stub from before /status returned the provider. Now reads
  live from /status, same wording as the sidebar ("Cloud AI" /
  "On-device AI").
- **Taste lesson:** He cross-checks surfaces against each other —
  stale stubs that contradict another screen erode trust. Grep for
  hardcoded copy when an API starts returning the real value.

### 11. Window dragging nearly impossible (only the bar's few empty pixels dragged)
- **Reaction:** "very difficult to move… maybe double tap and moving…
  should have been more convenient and simpler"
- **Satisfaction: 2 (old behavior)** → implemented grab-anywhere:
  footer + every empty gap + the bar all drag; card content stays
  selectable. Declined the double-tap gesture (undiscoverable, no
  native precedent, conflicts with click/selection) and explained why.
- **Taste lesson:** When he proposes a mechanism ("double tap"), he's
  describing the PROBLEM (moving is hard), not mandating the solution
  — prefer the native platform pattern and say why. *Verdict on the
  call itself pending — v1 shipped broken (see #12) so taste wasn't
  actually tested.*

### 12. Drag v1 didn't work on Windows — window vanished instead of moving
- **Reaction:** "i cant still drag, double click just send it in the
  background, not draggable"
- **Satisfaction: 1 (bug)** → root cause: the ask bar hides itself on
  `tauri://blur` (Spotlight pattern), and on Windows entering the
  native window-move loop fires a blur — so every drag attempt
  triggered self-hide. Fixed: blur within 800ms of a drag start is
  swallowed; double-clicks never start drags (OS caption gesture).
- **Taste lesson (engineering):** Features developed against macOS
  assumptions must be re-verified on Windows — window
  focus/blur/drag-loop semantics differ. Test the interaction, not
  just the build.

### 13. Answering view: sources clipped with no scroll; answer rendered as flat mono text
- **Reaction:** "i can never scroll down to see citations/sources…
  the output looks kinda ugly too… think about cases of latex/katex
  and readability itself"
- **Satisfaction: 2 (old state)** → fixed: window bounded to 100vh
  with the answer+sources column scrolling; answer now renders as
  Markdown (lists, tables, code) + KaTeX math in the body font, with
  citation pills and highlights preserved via a custom rehype pass.
- **Taste lesson:** He thinks ahead to content classes we haven't hit
  yet (LaTeX from papers) — readability of the ANSWER is the product;
  it deserves real typesetting, not a text dump. Mono is for code
  only.

### 14. Citation pill [4] opened a random shell script instead of the cited paper
- **Reaction:** "i thought it was more so citing stuff, paper or
  something — is that not the case? what was the intent?"
- **Satisfaction: 1 (bug)** → his mental model was exactly the design
  contract: `[N]` indexes `sources_used` (cited docs). Frontend was
  resolving against the full retrieval list. Fixed: sources_used now
  threads through QueryResponse; pills resolve in citation order with
  a stub fallback for filtered paths.
- **Taste lesson:** When he asks "is that not the case? what was the
  intent?" he's usually right about the intent — treat user confusion
  about behavior as a bug report against the contract, not a
  misunderstanding to explain away.

### 15. Cited sources buried under uncited retrieval candidates ("cool also… i cant see the citations")
- **Reaction:** "cool" on the citation-mapping fix; then: after
  scrolling, sources "seemed a bit off", citations not visible.
- **Satisfaction: 4 (fix #14) / 2 (sources ordering)** → SourcesCard
  now shows CITED sources first, with scanned-but-uncited candidates
  folded behind "N more files scanned, not cited"; auto-expands when
  nothing is cited yet or the selected file is folded.
- **Taste lesson:** Rank information by user value, not by internal
  pipeline order (retrieval score). What the answer USED matters;
  what was merely scanned is a detail on request.

### 16. Sources card collapsed to header-only; wants evidence highlighted ON the paper
- **Reaction:** "i cant scroll past source it say 1/5 but i dont see
  the citation and doesnt highlight where the words it answered are
  exactly on the paper"
- **Satisfaction: 1 (bug) + feature ask** → bug: leftover `flex: 1 +
  overflow: hidden` on .sources-card computed to ~0 height inside the
  new scrolling column — regression from my own scroll fix. Fixed
  (flex: none). Feature: PDF preview got a Page/Text toggle; Text view
  shows extracted text with answer terms highlighted (backend
  /preview?mode=text added). True on-page highlight boxes = v2.
- **Taste lesson:** He wants provenance end-to-end: answer → citation
  → the exact words in the document. Each hop must be visible. Also:
  when changing a layout's scroll model, audit every descendant with
  flex/overflow assumptions from the old model.
