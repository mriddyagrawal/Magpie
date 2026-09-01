# Research log

Measured findings that changed — or deliberately did not change — how Magpie is built.

Each entry answers one question with data, states what it changed in the codebase, and is
honest about what it doesn't establish. Entries are **dated and immutable**: superseded,
never rewritten. A finding that turned out to be wrong stays here with a note, because the
wrong turn is usually the useful part.

## Conventions

- **One directory per investigation**, named `YYYY-MM-DD-topic`.
- **`README.md`** holds the findings and what they changed. **`METHOD.md`** holds the
  configuration, the integrity gates, and the limitations.
- **Negative results are kept.** A null that bounds a later positive result is worth as
  much as the positive one — see the POPE entry below, which only became interpretable once
  the long-context run existed.
- **Per-item data is committed** where size allows, so a finding can be re-analysed without
  re-running it.
- **Papers are cited as priors to test against, not as authority.** Where our result
  disagrees with or extends a published one, that is stated plainly.

## Entries

### [2026-09-01 — Prompt ordering](2026-09-01-prompt-ordering/)

Does the order of system prompt, question, and content inside one turn change accuracy?

- On short prompts (~156 tokens): **no** — a clean null, replicating arXiv 2607.15565.
  But the same manipulation swings output capitalization from 96% to 2%.
- On long documents (up to 16k tokens): **yes, enormously** — up to **+31 points** past
  8k tokens. The effect scales with context length.
- On a different model: **the optimal ordering reverses.** What gains LFM2.5-VL-3B
  15 points costs Gemma 4 26B A4B 11.
- Magpie's GBNF grammar: **no effect on accuracy**, but it fixes JSON on 19% of responses.
- LFM **confabulates** (wrong entity on 31% of items); Gemma **abstains**. Different
  failure modes matter more than the accuracy gap for a tool answering questions about
  your own files.

**Changed:** put the question after the document. Re-measure ordering on any model swap.

*7,500 generations · LFM2.5-VL-3B Q6_K and Gemma 4 26B A4B · POPE + LongBench HotpotQA ·
all answers judged blind*
