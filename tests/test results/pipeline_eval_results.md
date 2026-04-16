# Pipeline Eval Results (stages 3 + 4, end-to-end)

- Run: 2026-04-13 00:15:54 UTC
- Model: kimi-k2.5 via Moonshot
- Top-k (Qdrant): 5
- Questions: 3

## Summary

| ID | Difficulty | Retrieval recall | Citation recall | Elapsed (s) |
|---|---|---|---|---|
| medium-11 | medium | 1/1 | 1/1 | 89.0 |
| medium-02 | medium | 1/1 | 1/1 | 60.1 |
| medium-01 | medium | 1/1 | 1/1 | 57.3 |

## Per-question

### medium-11 — medium

**Question:** According to the Artwork Analysis essay, what do students who fail at understanding harmonies in their abstract form go on to become, and what about those who fail astronomy?

**Expected answer:** Those who fail harmonies become 'Harmon-ists' who make, tune, and study instruments. Those who fail astronomy (the pure-logic/math understanding of stellar motions) become Astronomers who build telescopes and study stars.

**Expected source files:**
- `Test Content/Artwork Analysis.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Artwork Analysis essay students who fail at understanding harmonies in their abstract form go on to become what careers outcomes fail astronomy*
- `keywords`: `Artwork Analysis`, `harmonies`, `abstract form`, `astronomy`, `students who fail`, `become`

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Artwork Analysis.docx` | expected |
| 2 | 0.6667 | `Test Content/Artwork Analysis.pdf` |  |
| 3 | 0.4500 | `Test Content/Book VII - Plato's Republic.pdf` |  |
| 4 | 0.4500 | `Test Content/Plato's Allegory of the Cave.docx` |  |
| 5 | 0.2500 | `Test Content/Giovannelli CV Review 2012MmSAI..83..446G.pdf` |  |

**Kimi's answer:**

According to the Artwork Analysis essay, students who fail at understanding harmonies in their true, abstract form become "Harmon-ists" who make, tune, and study instruments. Those who fail at astronomy—specifically, at understanding and inferring the motions of stars using pure logic and math—become Astronomers who make telescopes and study stars.

**Sources Kimi cited:**
- `Test Content/Artwork Analysis.docx`
- `Test Content/Artwork Analysis.pdf`

*Elapsed: 89.0s*

---

### medium-02 — medium

**Question:** According to MTH-245 Handout 0, what minimum sample size does the Central Limit Theorem generally require for a test about a population mean?

**Expected answer:** n >= 30.

**Expected source files:**
- `Test Content/MTH_245_Handout_0.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *MTH-245 Handout 0 Central Limit Theorem minimum sample size requirement population mean test generally*
- `keywords`: `MTH-245`, `Handout 0`, `Central Limit Theorem`, `minimum sample size`, `population mean`, `CLT`

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/MTH_245_Handout_0.pdf` | expected |
| 2 | 0.8333 | `Test Content/MTH_245_Handout_1.pdf` |  |
| 3 | 0.4500 | `Test Content/MTH_245_Handout_3.pdf` |  |
| 4 | 0.4500 | `Test Content/MTH_245_Handout_4.pdf` |  |
| 5 | 0.3333 | `Test Content/MTH_245_Handout_6.pdf` |  |

**Kimi's answer:**

According to MTH-245 Handout 0, the Central Limit Theorem generally requires a minimum sample size of **n ≥ 30** for a test or interval about a population mean.

**Sources Kimi cited:**
- `Test Content/MTH_245_Handout_0.pdf`

*Elapsed: 60.1s*

---

### medium-01 — medium

**Question:** What token type does the DEC tokenizer assign to the symbol ':='?

**Expected answer:** ASSIGNMENT.

**Expected source files:**
- `Test Content/Lab 3 - Tokenizer.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *DEC tokenizer token type assignment symbol colon equals := operator lexical classification documentation*
- `keywords`: `DEC`, `tokenizer`, `:=`, `token type`, `assignment operator`, `colon equals`

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Lab 3 - Tokenizer.pdf` | expected |
| 2 | 0.6667 | `Test Content/Lab 5 - Parser.pdf` |  |
| 3 | 0.4167 | `Test Content/Lab 2 - Symbol Tables.pdf` |  |
| 4 | 0.3750 | `Test Content/Lab 4 - AST.pdf` |  |
| 5 | 0.3667 | `Test Content/Lab 6 - AST Visitors.pdf` |  |

**Kimi's answer:**

ASSIGNMENT

**Sources Kimi cited:**
- `Test Content/Lab 3 - Tokenizer.pdf`

*Elapsed: 57.3s*

---

