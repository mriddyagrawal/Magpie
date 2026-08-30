# Answer-quality report

Run: `20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
Scope: answer quality only. Retrieval ranking and index defects belong to other agents and are
referenced here only where they change the denominator.
Sources: `answers_enriched.json`, `judge_verdicts.json`, `raw/answers.jsonl`,
`raw/appdata/logs/llm-2026-08-30T10-40-06Z.log` (all 120 request/response pairs, joined 120/120),
`raw/worker_answer.log`, `eval_harness/datasets/custom_dataset_rahul_Aug30/golden.json`,
plus pixel measurements of every one of the 154 distinct files that reached a prompt.

This report **quantifies** the judge's six patterns rather than restating them, tests them against the
full 120, and adds four findings the judge (who sampled 16 files) did not have the data to see.

---

## 1. Verdict breakdown and the honest denominator

The judge's headline is 5/104 correct (4.8%). Eleven of those 104 items were doomed before the model
saw a pixel and should not be charged to the answerer:

| Segregated group | Items | qa_ids | Why not an answering failure |
|---|---|---|---|
| HTTP 400 (context overflow) | 3 | study-03-full, phone-05-typed, phone-11-full | no model call completed (§7) |
| Gold never indexed (fp16 NaN) | 6 | rcpt-07-typed/full, study-05-typed/full, study-10-typed/full | gold absent from the corpus store |
| Gold beyond the 5-page render cap | 2 | study-08-typed/full | ColQwen matched `deck_027.pdf` **page 5** (0-indexed); only pages 0–4 are rendered |
| **Total segregated** | **11** | | |

I found **one item the supervisor's list misses**: `rcpt-05-typed`. Its gold `bad_receipt_014.jpg`
never entered the prompt at all (prompt was `110671448.jpg`, `scene_887bfd79f29a3fcb.jpg`) — a
retrieval miss, not an answering failure. Its `-full` twin *did* get the gold file and still failed,
so the pair is not lost, but the `typed` half must come out of the answer denominator.

| Verdict | All answerable | Adjusted (−11) | Adjusted (−12, also excl. rcpt-05-typed) |
|---|---|---|---|
| correct | 5 | 5 | 5 |
| partial | 16 | 16 | 16 |
| wrong | 39 | 34 | 33 |
| false_abstain | 44 | 38 | 38 |
| **n** | **104** | **93** | **92** |
| correct | 4.8% | 5.4% | **5.4%** |
| correct-or-partial | 20.2% | 22.6% | **22.8%** |

**The honest number is 5/92 correct (5.4%) and 21/92 correct-or-partial (22.8%).** Segregating the
structurally-doomed items moves the headline by 0.6 points. It does not rescue the run. Retrieval put
the gold file in front of the model in **91 of these 92 items**; the answerer converted 5 of them.

The 16 `not_found` probes are unaffected by any of this: 9 correct abstentions, 7 false answers.

---

## 2. The false-abstain bucket (44) — what actually separates a silent failure from a read

44 false abstains, 3 of which are the HTTP 400s. Of the remaining **41**, the gold file was in the
prompt for **39** (the 2 exceptions are the rcpt-07 pair, whose gold was never indexed), and in all
39 the gold sat at **retrieval rank 1**. So this is not a retrieval-depth problem and it is not a
"gold wasn't there" problem.

### 2.1 Hypotheses tested on the 93-item adjusted set

Abstention rate (`false_abstain` / all answerable), each factor tested marginally and then again
holding the winning factor fixed:

| Hypothesis | Marginal result | Verdict |
|---|---|---|
| **Context length** (prompt text chars, median split) | 47% vs 67% *within* number-questions; 12% vs 12% within non-number questions | **not causal** — the split disappears once content type is held fixed |
| **Number of images** | 2 img 37% (n=70), 4 img 25%, 5 img 50%, 6 img 50%, 7 img 67% (n=9) | **weak, real but secondary** — inside number-questions it moves 55%→62% |
| **Total prompt megapixels** | Q1 30% → Q4 58%; but *within* the 70 two-image prompts: 30/43/38% by tertile | **not causal** — confounded with document genre |
| **Gold-file resolution** | Q1 32% → Q4 60% marginally; contradicted by the category data (see below) | **not causal** |
| **PDF vs image-only prompt** | 46% vs 38% | **not causal** (53%/65% within number-questions, 9%/18% within others) |
| **Question type** (extractive / enumeration / synthesis) | 40% / 36% / 47% | **no signal** |
| **Difficulty label** | easy 41%, medium 37%, hard 48% | **no signal** |
| **Category** | 0% (figures, screenshots) → 88–100% (receipts_phone, slides) | **strong, but a proxy** |
| **The gold answer requires reading a printed multi-digit number** | **57% (34/60) vs 12% (4/33)** | **THIS IS THE DISCRIMINATOR** |

The discriminating variable is operationalised without judgement: a question is a *number question*
if any of its golden `key_facts` matches `\d[\d ,.]{2,}` — i.e. the fact is a printed figure of three
or more characters (a price, a total, a year-pair, a measured value), not a word.

- Marginal: 34/60 (57%) abstain vs 4/33 (12%). Fisher exact **p = 2.2 × 10⁻⁵**.
- Held fixed at exactly 2 images (n = 70, the homogeneous stratum): 24/44 (55%) vs 2/26 (8%),
  Fisher exact **p = 8.2 × 10⁻⁵**. The effect survives the control; every other candidate does not.
- Of the 41 non-400 false abstains, **36 (88%) are number questions.**

### 2.2 The natural experiment that kills the resolution hypothesis

`screenshots` and `receipts_phone` are the cleanest pair in the corpus: identical file type (JPEG),
identical typical geometry, and screenshots are the *larger* files.

| Category | Typical gold geometry | Abstain rate (2-image stratum) |
|---|---|---|
| screenshots (`screen_24184.jpg` … 1080×1920) | 1080 × 1920 | **0/5 (0%)** |
| receipts_phone (`receipt_022.jpg` 576×864, `receipt_014.jpg` 1108×1478) | *smaller* than screenshots | **6/7 (86%)** |
| receipts_degraded (`bad_receipt_004.jpg` 473×1032) | smallest of all | **1/6 (17%)** |

Same pixels, opposite behaviour. What differs is the *apparent size of the glyphs the question asks
about*: Android UI type fills a large fraction of the frame; receipt thermal print does not.
`receipts_degraded` is lower resolution than `receipts_phone` yet abstains 5× less often, which
inverts any downscale-driven story outright.

### 2.3 Why "number question" causes *silence* rather than *error*

The variable predicts the shape of the failure far better than the rate of success
(adjusted set, n = 92):

| | correct | correct-or-partial | wrong | false_abstain |
|---|---|---|---|---|
| No printed-number fact (n=33) | 3 (9%) | 10 (30%) | 19 (58%) | 4 (12%) |
| Printed-number fact (n=59) | 2 (3%) | 11 (19%) | 14 (24%) | **34 (58%)** |

When the target is a word or an object, the model attempts and is usually wrong. When the target is a
printed figure, it declines. The abstention machinery is therefore doing something *right*: LFM2.5-VL
appears to have calibrated self-knowledge that it cannot resolve fine numeric print, and it declines
instead of inventing a total. That is preferable to the alternative — but as shipped it is
indistinguishable to the user from "your file isn't there", which is the product bug.

Concrete instances, all with gold at rank 1 and gold in the prompt:
`rcpt-01-typed/full` (Bornga receipt, 45,500 total), `rcpt-03-typed/full` (308,000 on a BCA card),
`rcpt-06-typed/full` (Rp224,908), `arch-07-typed/full` (KLM Cargo 1,271 M€ vs 1,695 M€),
`arch-10-typed/full` (chiffre d'affaires 6 649 M€), `arch-01-typed/full` (Cuyahoga County
expenditure scan), `study-03-typed` ($150,000 / 67.5 MWh, gold `deck_022.pdf` the only file in the
prompt), `study-11-typed/full` (17 apps / 27 apps across two decks).

### 2.4 Secondary effects that are real but small

- **Image count**: within number-questions, 2 images → 55%, >2 images → 62%. Within
  non-number-questions, 8% → 29%. Directionally consistent, n too small to separate from noise.
- **PDF page truncation by the context trimmer** hits 6 files across 6 items
  (`arch-03-typed` scan_xqgl0226.pdf 3/4 pages, `arch-06-full` deck_015.pdf 1/2,
  `study-11-typed/full` deck_002.pdf 2/3, `rcpt-08-full` deck_023.pdf 2/3,
  `nf-05-full` scan_yjgx0227.pdf 2/3). All 6 abstained. In none of them was the *matched* page the
  one dropped, so this is correlation with prompt size, not a demonstrated cause.
- **One file reached the model as a header with zero pixels**: `study-03-full`'s `deck_002.pdf` —
  the trimmer kept its "Content type: pdf (scanned…)" line and dropped every page. That item 400'd
  anyway, so the blast radius this run is 1.

---

## 3. Typed vs full — the judge's two observations are one observation

The judge noted typed skews `wrong` (23 vs 16) and full skews `false_abstain` (24 vs 20) and called
the correctness gap noise. Both phrasings ask the *same* question of the *same* gold, so the correct
test is paired (McNemar), not the marginal counts. On the 45 pairs where both halves survive
segregation:

| Property | typed-only | full-only | exact binomial p |
|---|---|---|---|
| `wrong` | **13** | 4 | **0.049** |
| `false_abstain` | 4 | **9** | 0.267 |
| `correct` or `partial` | 2 | 6 | 0.289 |

- The `wrong` skew is real at the 5% level; the `false_abstain` skew on its own is not.
- **They are the same pairs.** The 9 full-only-abstain pairs are `viz-03, viz-05, viz-08, arch-02,
  arch-05, arch-06, rcpt-02, rcpt-08, rcpt-09`; 8 of those 9 are also in the 13 typed-only-wrong
  set. One question, one underlying failure to read the file, two different surface behaviours:
  the terse phrasing makes the model *guess*, the verbose phrasing makes it *decline*.
- **Quality is unchanged.** correct-or-partial: typed 8/45, full 12/45, p = 0.29. Phrasing changes
  the failure mode, not the capability.

### 3.1 The mechanism: on terse queries the model emits the query back

This is the concrete reason typed skews `wrong`, and it is measurable:

- **7 answers consist only of tokens already present in the question.** All 7 are `typed`
  (`viz-06-typed` "diabetes australia infographic annual cost", `arch-06-typed` "Fort Morgan Sugar
  Factory", `rcpt-02-typed` "McDonalds", `rcpt-09-typed` "Original brewed tea was pricier",
  `study-07-typed` "Attribute SBM wins", `nf-02-typed` "wedding invitation",
  `nf-06-typed` "training loss curve"). 7/7 on one phrasing arm is not a coincidence.
- **`not_found_topic` echoes the question verbatim in 33 items — 33/33 `typed`.**
- **`not_found_topic` echoes a hard-coded schema example verbatim in 12 items** ("a landlord's
  emergency phone number", the `src/answer.py:233/:285` field description) — **10/12 `full`.**

So the degenerate output is always "copy the nearest available string". Terse questions supply a
short, salient noun phrase, so it copies the query; verbose questions do not, so it copies the
example in the schema. The `not_found` probes show the same split: **5 of the 7 false answers are
`typed`** and 6 of the 9 correct abstentions are `full`.

---

## 4. Per-category answer quality — what the product can do today

Adjusted set (n = 93); the last column is items removed by segregation, so a founder can see where
the sample is thin.

| Category | n | correct | partial | wrong | false_abstain | C+P | segregated |
|---|---|---|---|---|---|---|---|
| diagrams | 4 | 1 | 2 | 0 | 1 | **75%** | 0 |
| scene_text | 8 | 0 | 4 | 2 | 2 | **50%** | 0 |
| figures (arXiv) | 6 | 0 | 2 | 4 | 0 | 33% | 0 |
| screenshots | 6 | 1 | 1 | 4 | 0 | 33% | 2 |
| infographics | 8 | 1 | 1 | 3 | 3 | 25% | 0 |
| scans_multipage | 8 | 0 | 2 | 2 | 4 | 25% | 0 |
| receipts_degraded | 8 | 0 | 2 | 4 | 2 | 25% | 0 |
| documents (UCSF scans) | 6 | 0 | 1 | 0 | 5 | 17% | 0 |
| notes_handwritten | 6 | 0 | 1 | 3 | 2 | 17% | 4 |
| photos | 6 | 1 | 0 | 4 | 1 | 17% | 0 |
| charts | 10 | 1 | 0 | 6 | 3 | 10% | 0 |
| tables_fr | 6 | 0 | 0 | 1 | 5 | **0%** | 0 |
| slides | 3 | 0 | 0 | 0 | 3 | **0%** | 3 |
| receipts_phone | 8 | 0 | 0 | 1 | 7 | **0%** | 2 |
| **all** | **93** | 5 | 16 | 34 | 38 | 23% | 11 |

Read this as three tiers, not fourteen numbers:

**Tier 1 — usable-ish for "what is this / what does it say".** diagrams, scene_text, screenshots,
figures. The model reliably identifies large, high-contrast, foreground text and named objects:
`phone-01-full` "Champaign, IL" off a settings screen; `phone-07-full` naming five sponsor banners
off a 500×333 beach-volleyball photo; `viz-10-full` reproducing both caption sentences of a leaf-shape
diagram. Failures here are *comprehension* failures, not *acuity* failures — `study-06-typed` and
`-full` both describe the wrong arXiv panel; `study-09-typed/full` invent physics for the linearised
attention figure. Zero abstentions in figures and screenshots.

**Tier 2 — reads the headline, misses the body.** receipts_degraded, documents, infographics, charts.
`rcpt-02-typed` returns "McDonalds" — the largest text on the receipt — and nothing else;
`rcpt-05-full` returns "Hallmark"; `rcpt-04-typed/full` return "2.450 RM" (the unit price) but not
the 35.10 litres asked for. On charts the model reads a value but the wrong one: `viz-04-full` gives
29% where `chart_037.jpg` shows 20% in that band and 29% in the adjacent one. The single-column
misread is the signature of this tier.

**Tier 3 — cannot be used at all.** receipts_phone (0/8, 7 abstains), tables_fr (0/6, 5 abstains),
slides (0/3). Dense small print in a photographed or scanned frame. All five `tables_fr` failures are
French annual-report tables where the answer is a figure like `4,58` or `6 649`; the model declines
every time. This is the category the founders should not ship against.

Handwriting is a special case: `notes_handwritten` shows 1 partial / 3 wrong / 2 abstain out of 6,
but 4 of its 10 items were segregated (study-05, study-10 — the NaN index loss). On what remains, the
model *can* transcribe handwritten C++ notes — `study-04-full` correctly says the conditional
operator is the ternary operator — but cannot answer from them precisely, and `study-02-typed/full`
both return the bare title "C++ features". n = 6 is too small to grade the category; it needs a rerun
after the fp16 fix.

The harness's own H1 slice agrees: 49 eligible extractive items, all on the `file_level_image` basis
(no `fact_spans` exist because no vision transcripts were produced), accuracy 0.041.

---

## 5. Citation behaviour — the judge's read is directionally right and mechanically wrong

Recomputed on the adjusted set. All figures are mine, not `metrics.json`'s, and the definitions are
stated because they differ:

| Measure | Value |
|---|---|
| Answers with zero citations (adjusted answerable, n = 93) | 65 (70%) |
| Answers with zero citations **among items where the model actually answered** (n = 55) | **27 (49%)** |
| Citations emitted in total | 45 |
| Cited files that were **not in the prompt** | **0 of 45 (0.0%)** |
| Precision over emitted citations (cited ∈ gold ∪ acceptable) | 0.62 |
| Mean per-item precision, attempted answers with ≥1 citation (n = 28) | 0.607 |
| Mean per-item recall, same set | 0.786 |
| Mean per-item precision, all adjusted answerable | 0.183 |
| Items where any gold file was cited | 23/93 (25%) |

### 5.1 Correction: nothing was hallucinated

`metrics.json` reports `hallucinated_citations: 0.202`. That field is the **mean per-item count of
cited files that are not gold** — not the rate of invented paths. **Zero of the 45 emitted citations
named a file that was absent from the prompt.** `src/answer.py:905` drops any path the model invents,
so a hallucinated *path* cannot survive to `magpie_cited` by construction. The judge's "several cite
a file they demonstrably did not read" is true only in the weaker sense that the cited file was in
the prompt but is not where the answer came from — e.g. `viz-01-typed` reads `chart_001.jpg` and
cites `arxiv_025.png`.

### 5.2 The real defect: `sources_used` is a transcription of the file headers, not a selection

Of the 35 answers carrying at least one citation (all 120 items, so this includes the `not_found` probes and the segregated items):

| Citation-list shape | n | share |
|---|---|---|
| **Exactly every file in the prompt, in prompt order** | 23 | 66% |
| Exactly prompt File 1 (the *worst*-ranked file) | 6 | 17% |
| Exactly prompt File N (the best-ranked file) | 5 | 14% |
| A genuine subset | **1** | 3% |

34 of 35 citation lists are one of three degenerate patterns. When the model cites exactly one of two
files it picks the top-ranked one 5 times out of 11 — chance. `study-07-full` cites
`receipt_025.jpg` **and** `arxiv_004.png` because both were in the prompt, not because it consulted
a receipt about an NMI plot. **`sources_used` carries no information about what was read** and should
not be surfaced to a user as provenance in its current form.

### 5.3 The judge's "citation order looks unreliable" has a prosaic cause

Prompt assembly deliberately reverses retrieval rank (`src/answer.py` ~line 714, the recency
reversal): **in all 111 checkable requests the prompt lists files in exact reverse rank order**, so
`--- File 1:` is always the *worst* hit and the best hit is last. Answers that "list the rank-2 file
first" are simply copying prompt order — 16 of the 17 multi-citation lists are in ascending prompt
order. Not a citation bug; a consequence of the intended layout, but it means any user-facing
"[1]" marker points at the least relevant file.

### 5.4 Even when Magpie is right, it usually cannot say why

Of the 21 correct-or-partial answers:
- **10 cite nothing** (`viz-10-typed`, `viz-10-full`, `arch-04-typed`, `arch-04-full`,
  `study-07-typed`, `rcpt-04-typed`, `rcpt-04-full`, `phone-06-typed`, `phone-06-full`,
  `phone-07-full`).
- **2 cite only a wrong file** (`viz-01-typed` → `arxiv_025.png`; `viz-06-full` → `info_015.jpg`).
- Only **9 of 21 (43%)** attach the gold file to a right answer.

### 5.5 A new bug: a schema-echo is silently destroying gold citations

15 `sources_used` entries in the raw LLM responses arrive with the prompt header still attached, e.g.
`"--- File 2: /…/chart_001.jpg ---"`. The hallucination guard does exact path matching, so it drops
them as invented. **9 items lost a citation this way, and in 7 of them the discarded string named the
gold file**: `viz-01-typed` (chart_001.jpg), `viz-07-full` (info_001.jpg), `rcpt-04-typed`
(bad_receipt_019.jpg), `phone-01-typed` (screen_24184.jpg), `phone-02-typed` and `phone-02-full`
(scene_0464a1dafaa33d6d.jpg), `phone-07-typed` (1080230428.jpg).

Excluding `phone-07-typed`, which sprayed 7 malformed entries, **8 of 8 malformed entries name the
*last* prompt file** — which, because of the recency reversal, is the **rank-1 gold**. The guard is
therefore preferentially deleting the one correct citation. Fixing this alone would lift
"any gold file cited" from 23/93 to roughly 30/93 (25% → 32%) with no model change.

---

## 6. The three HTTP 400s — cause confirmed, exact sizes, and the real ceiling

Confirmed from `raw/worker_answer.log`. These are not opaque 400s; llama-server states the reason:

| qa_id | llama-server message | Prompt tokens | Overflow | Images | Files in prompt |
|---|---|---|---|---|---|
| study-03-full | `request (16527 tokens) exceeds the available context size (16384 tokens)` | 16,527 | +143 | 7 | deck_002.pdf(0 pages kept), doc_5370.jpg, info_038.jpg, deck_022.pdf(5 pages) |
| phone-05-typed | `request (17785 tokens) exceeds …` | 17,785 | +1,401 | 7 | 7 screenshots/photos, five of them 1080×1920 |
| phone-11-full | `request (17598 tokens) exceeds …` | 17,598 | +1,214 | 7 | seven 1080×1920 screenshots |

**Yes, `local_n_ctx = 16384` is the binding constraint**, and the failure is entirely a
budget-estimation error inside Magpie, not a model or server problem.

The arithmetic in `src/answer.py`:
- `usable_tokens = 16384 − 3000 (reserve) = 13,384`; `_CHARS_PER_TOKEN = 3.2` → budget = **42,828 chars**.
- `_block_cost_chars` charges every image a **flat 6,000 chars ≈ 1,875 tokens**, regardless of resolution.
- 42,828 / 6,000 = 7.14 → **the trimmer will admit at most 7 images, ever.**

I reconstructed the trimmer in full (rank order, per-file blocks, mid-file truncation) and it
reproduces `extra.images` from the LLM log **exactly for all 120 requests**, so this model of the
budget is verified, not assumed.

**The break point is 7 images — necessary but not sufficient.** All 3 failures had exactly 7 images;
no request with ≤6 images failed. But 11 other 7-image requests succeeded, so image count alone does
not predict it. Nor does resolution in any simple form: `arch-06-full` sent 7 images totalling
24.1 MP and survived, while `phone-11-full` sent 7 images totalling 14.5 MP and overflowed by 1,214
tokens. Working backwards from `phone-11-full` (7 identical 1080×1920 images, ~5.4 KB of prompt text
≈ 1,300–1,400 tokens) gives roughly **2,300 tokens per screenshot** against the 1,875 the code
assumes — a ~20–25% under-estimate. I could not fit a per-image token function that reconciles all
three observations (patch-grid, tile-count and area models all fail on at least one), and with only
three observed token counts and no `usage` field on successful responses the family is
under-determined. **I state this as unresolved rather than assert a rule.**

What is safe to say:
1. The flat per-image cost is wrong in the unsafe direction. The comment at `_CHARS_PER_TOKEN` says
   the design intent is to *over*-estimate tokens; the image constant does the opposite.
2. At 7 images the estimate leaves 3,259 tokens of headroom and reality consumed 143–1,401 tokens
   more than the window. The margin is thin enough that a 5-image cap, or an image cost of
   ~8,000 chars, would have made all three succeed.
3. Every one of the 3 failures was an `enumerate_lists`-widened question (§8.1). Narrow questions
   never got near the ceiling.

---

## 7. Where I disagree with the judge

I checked all 11 deterministic-vs-judge disagreements and agree with the judge on 10. The
`golden-set` observations (viz-06 variant, phone-03 all-or-nothing fact, viz-11 duplicate set,
nf-07-full taxonomy gap) all hold up.

**One disagreement: `study-07-typed` should be `wrong`, not `partial`.** Its answer is
"Attribute SBM wins", and the question was "nmi vs pin/pout plot attribute sbm vs regular sbm which
one wins". Every token of the answer is present in the question. The judge scored the other six
query-echo answers `wrong` on exactly that reasoning (`viz-06-typed`, `arch-06-typed`,
`rcpt-02-typed`, `rcpt-09-typed`), so this is an internal inconsistency rather than a defensible
judgement call. Regrading it drops correct-or-partial on the adjusted set from 21/92 to 20/92
(22.8% → 21.7%) — it does not change any conclusion, but the rubric should be applied uniformly.

I also flag, without asking for a regrade: **`study-07-full` is `partial` largely on the strength of
naming both series and the NMI-1.00 plateau, and both of those are stated in the question or are
generic**. It is the weakest `partial` in the set.

---

## 8. What the judge missed

### 8.1 The `enumerate_lists` widener is strictly harmful, and I can say exactly how

10 questions were widened from 2 files to 12 (`arch-06-full`, `study-03-full`, `rcpt-01-full`,
`rcpt-08-typed/full`, `phone-05-typed/full`, `phone-07-typed`, `phone-11-full`, `nf-06-full`).

- 9 are answerable. **0 of 9 are correct or partial**, against 21/95 (22%) for narrow questions.
  Fisher exact p = 0.198 — suggestive, not significant at n = 9. State it as a strong prior, not a
  proven effect.
- **All 3 HTTP 400s are widened questions.**
- **The widener never delivers what it promises.** All 10 widened prompts hit the 7-image ceiling;
  between 5 and 9 of the 12 retrieved files were dropped by the trimmer in every case.
- **The dropped files were not the problem.** In 9 of 10, every gold file survived the trim
  (`rcpt-08-full` lost one of three: `bad_receipt_027.jpg`). So widening did not lose the evidence —
  it diluted the prompt with up to 6 extra distractors and pushed 3 requests over the window.

The founder-facing conclusion: at `top_k=2` on a 16K local window, `enumerate_lists` costs a 25%
crash rate and buys nothing.

### 8.2 Prompt file order is the reverse of retrieval rank, in 111/111 checkable requests

Already covered in §5.3. Worth restating as its own finding because it explains the judge's citation
anomaly and because any `[1]`/`[2]` marker the model emits points at the *least* relevant file.

### 8.3 Inline `[n]` markers are model-invented and half of them are orphaned

13 answers contain inline bracket markers. The system prompt never asks for them — the model supplies
them from its training prior. **5 of the 13 have `magpie_cited == []`**, so the marker refers to
nothing at all (`viz-04-full`, `viz-10-typed`, `study-06-full`, `rcpt-05-full`, `phone-06-typed`).
A further 3 emit `[1]`/`[2]` against a single cited file (`study-08-full` ends "MEMS and
microfluidics at 40% [1] and [2]" with one citation). The judge inferred citations were "stripped after generation"; the simpler
explanation is that the markers were never a citation mechanism, and `sources_used` is a separate,
independently-degenerate field (§5.2).

### 8.4 The `not_found_topic` leak has a shape the judge did not see

The judge found 11 items with the stuck string; there are **12** (`nf-05-typed` is the extra), and
the field is degenerate in a second way the judge did not report: it echoes the question verbatim in
**33** items. Both behaviours are strictly phrasing-conditioned — 33/33 verbatim echoes are `typed`,
10/12 schema leaks are `full`. That means the field never contains a *summarised* topic in this run;
it is always a copy of some string that was already on screen. `src/answer.py:233/:285` embed the
examples in the JSON-schema field description, which is why the copy target is available at all.

### 8.5 Two structural details that quietly reduce what the model sees

- **One file arrived as a header with zero pixels** (`study-03-full` / `deck_002.pdf`), because the
  trimmer keeps a non-empty `out_blocks` even when the only surviving block is the "Content type"
  string. The model is told the file is present and given nothing to look at.
- **Eight items have a gold PDF longer than the 5-page render cap** (`arch-06`, `study-03`,
  `study-08`, `study-11` — both phrasings each), not just `study-08`. I checked the ColQwen-matched
  page for each: only `study-08` matched a page beyond the cap (page 5). The other six matched pages
  0–2, so the cap did not bite there — but the exposure is 4× larger than it looks, and a corpus with
  longer decks would surface it.

### 8.6 Structured-output hygiene is otherwise clean

For completeness, because these are the failure modes one would expect and they did *not* occur:
`not_found=true` with a non-empty answer: **0 items**. `not_found=false` with an empty answer:
**0 items**. One of 117 responses failed JSON parse. The grammar is doing its job; the content inside
it is the problem.

---

## 9. Uncertainty and what would change these conclusions

- **The number-question discriminator (§2) is the strongest claim in this report** (p = 8 × 10⁻⁵
  after controlling for image count), but it is observational. The dataset was not designed to vary
  numeric-vs-nominal targets independently of category, and the two are correlated. The
  screenshots-vs-receipts_phone contrast (§2.2) is the best available control and it is only 12 items.
  A decisive test is cheap: re-ask 20 receipt questions for the *merchant name* instead of the total
  and see whether the abstention rate collapses.
- **The per-image token cost (§6) is unresolved.** Three observed token counts, no `usage` on
  successful responses, and no fitting family reconciled all three. Anyone acting on this should
  instrument `usage` in the local provider before choosing a new constant.
- **Category cells are small.** slides n=3, diagrams n=4; ±1 item moves those percentages by 25–33
  points. Tier assignments in §4 are directional.
- **The widener result (§8.1) is 0/9** — a strong prior with p = 0.198, not a finding.
- **Judge verdicts are model-authored against a model-authored SILVER golden set** (`human_verified:
  0`). The judge re-verified 16 files by eye and overturned no gold answer, which is reassuring but
  is not the same as a human-verified set.
- Nothing here should be compared to another arm without re-applying the same segregation: the
  11 doomed items would otherwise flatter or penalise whichever arm happens to hit them.
