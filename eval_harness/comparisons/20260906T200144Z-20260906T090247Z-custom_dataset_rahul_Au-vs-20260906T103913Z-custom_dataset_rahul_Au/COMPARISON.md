# Comparison: 20260906T090247Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite  vs  20260906T103913Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

- Generated: 20260906T200144Z  ·  pairing mode: **full** (coverage 100%, n=120)
- Changed axes: **code** (knobs: <code>)
- src/ commits between: 4 (first: 03ba954 prompt: images go under their file header on the local transport, not after all the text)

## Paired outcomes (A = baseline)

| Metric | A | B | Δ | discordant | McNemar p |
|---|---|---|---|---|---|
| answer good (authoritative) (judge) | 0.125 | 0.275 | +0.15 | 2A / 20B | 0.00012 |
| answer good (deterministic) | 0.1 | 0.25 | +0.15 | 2A / 20B | 0.00012 |
| answer good (judge) | 0.125 | 0.275 | +0.15 | 2A / 20B | 0.00012 |
| retrieval hit@1 (end_to_end) | 0.9327 | 0.9327 | +0.0 | 0A / 0B | 1.0 |  *(not decision-grade: < 5 discordant)*
| abstained | 0.4417 | 0.4167 | -0.025 | 19A / 16B | 0.73588 |  *(not decision-grade: p >= 0.05 - split is coin-consistent)*

## Verdict transitions (A → B)

- wrong -> partial: 10
- false_abstain -> wrong: 9
- wrong -> false_abstain: 9
- wrong -> correct: 8
- false_answer -> correct_abstain: 6
- false_abstain -> partial: 5
- false_abstain -> correct: 4
- partial -> wrong: 3
- partial -> correct: 2
- correct_abstain -> false_answer: 1
- correct -> partial: 1

## Slices

| Slice | A | B | Δ | discordant | McNemar p |
|---|---|---|---|---|---|
| phrasing=full | 0.1833 | 0.35 | +0.1667 | 0A / 10B | 0.00195 |
| phrasing=typed | 0.0667 | 0.2 | +0.1333 | 2A / 10B | 0.03857 |
| answer_type=enumeration | 0.1667 | 0.5833 | +0.4167 | 0A / 5B | 0.0625 |  *(not decision-grade: p >= 0.05 - split is coin-consistent)*
| answer_type=extractive | 0.0571 | 0.1714 | +0.1143 | 1A / 9B | 0.02148 |
| answer_type=not_found | 0.5625 | 0.875 | +0.3125 | 1A / 6B | 0.125 |  *(not decision-grade: p >= 0.05 - split is coin-consistent)*
| answer_type=synthesis | 0.0 | 0.0 | +0.0 | 0A / 0B | 1.0 |  *(not decision-grade: < 5 discordant)*

## Latency (paired): mean Δ +0.99s, median Δ +0.92s over n=120

## Answer regressions (good in A → bad in B) — 2

- **nf-03-typed** (typed) — correct_abstain → false_answer: 'lease agreement'
    - gold: 'No - there is no lease, rental, or tenancy agreement in these files.' · A: '' · B: 'R.J. Reynolds Tobacco Company Growers Questionnaire'
- **viz-01-typed** (typed) — correct → partial: 'food commodity price index chart cheapest one'
    - gold: "Cocoa, at 18.81. In the Our World in Data chart 'Long-term price index in food commodities, 1850-2015', cocoa has the lowest index value of the fourteen commodities shown; lamb is highest at 103.7." · A: 'The cheapest commodity is Cocoa at 18.81' · B: 'Cocoa'

## Answer wins (bad in A → good in B) — 20

- **nf-02-typed** (typed) — false_answer → correct_abstain: 'wedding invitation'
    - gold: 'No - there is no wedding or party invitation card in these files.' · A: 'wedding invitation' · B: ''
- **nf-04-full** (full) — false_answer → correct_abstain: 'Pull up my Python notes from last semester.'
    - gold: 'No - there are no Python notes. The handwritten programming notes are C++ only (the other handwritten series is physics/electrostatics).' · A: 'C++ Tutorials [1], C++ Tutorials [2]' · B: ''
- **nf-04-typed** (typed) — false_answer → correct_abstain: 'python notes'
    - gold: 'No - there are no Python notes. The handwritten programming notes are C++ only (the other handwritten series is physics/electrostatics).' · A: 'CseGyan-Cpp-Notes-11.pdf' · B: ''
- **nf-06-typed** (typed) — false_answer → correct_abstain: 'training loss curve'
    - gold: 'No - no figure plots loss against epoch, iteration, or training step.' · A: 'training loss curve' · B: ''
- **nf-07-typed** (typed) — false_answer → correct_abstain: 'covid vaccination certificate'
    - gold: 'No - there is no COVID-19 vaccination certificate or test result in these files.' · A: "Australia's Coverage Target is 95%" · B: ''
- **nf-08-typed** (typed) — false_answer → correct_abstain: 'chem notes'
    - gold: 'No - there are no handwritten chemistry notes; the handwritten notes are C++ and physics (electrostatics) only. Chemistry content does exist elsewhere in the files, but as scanned reports and slide decks, not as your notes.' · A: 'Electric field' · B: ''
- **phone-01-typed** (typed) — wrong → correct: 'that weather alerts settings screenshot what city was it'
    - gold: 'The Weather Notifications settings screen is set to Champaign, IL. Every toggle on it (Severe Weather Alerts, Lightning Alerts, KPLC 7 Alerts, Precipitation Alerts, Temperature Display) is switched on.' · A: 'Scoutdoors' · B: 'Champaign, IL'
- **phone-02-full** (full) — wrong → correct: "In the photo where I'm holding up a small blue Intel mini-PC box, what is the exact model number printed on it?"
    - gold: 'It\'s an Intel NUC, model NUC5i7RYH. The blue retail box has the tagline "The Shape that Fits the Future." and carries Intel Core i7 and Iris Graphics badges.' · A: 'palm' · B: 'NUC5i7RYH'
- **phone-02-typed** (typed) — wrong → correct: 'pic of the tiny intel box in its box, which model was it'
    - gold: 'It\'s an Intel NUC, model NUC5i7RYH. The blue retail box has the tagline "The Shape that Fits the Future." and carries Intel Core i7 and Iris Graphics badges.' · A: 'palm' · B: 'Intel NUC NUC5i7RYH'
- **phone-05-typed** (typed) — wrong → correct: 'workout app screenshot with the numbered exercise list, what were the exercises'
    - gold: 'The routine is called "Original" and the visible list runs: 1 Jumping Jacks, 2 Wall Sit, 3 Pushups, 4 Abdominal Crunch, 5 Step up onto chair, 6 Squat, 7 Triceps dip on chair. A teal bar at the bottom says "Slide to start workout".' · A: 'Turkey Cackle, STOP, Turkey Cluck 1, Turkey Cluck 2, Turkey Cutt 1, Turkey Cutt 2, STOP, Turkey Fighting Purr, Turkey Fly Down Cackle' · B: 'Jumping Jacks, Wall Sit, Pushups, Abdominal Crunch, Step up onto chair, Squat, Triceps dip on chair'
- **phone-08-full** (full) — wrong → correct: "On the bus app's rewards sign-up screen I saved, how many trips did you have to take to earn a free ticket, and what boarding perk did members get?"
    - gold: 'The BoltBus "My Bolt Rewards" screen says you get a free one-way ticket for every 8 trips traveled (fees and taxes may apply), plus priority Group A boarding as a rewards member.' · A: '0 trips; priority (Group A) boarding' · B: '8 trips; priority (Group A) boarding as a rewards member'
- **phone-09-full** (full) — wrong → correct: 'In the dim bar photo where a neon beer sign hangs on a purple wall above a row of three lit arcade machines, which beer brand is the neon sign advertising?'
    - gold: 'The neon sign is a Dos Equis "XX" IMPORTED BEER sign, glowing red and orange on a purple painted wall. Below it are three lit-up upright arcade / video gambling machines, with a man in a pale short-sleeved polo standing at the leftmost one.' · A: 'ORDER, TIP WELL, WALK AWAY.' · B: 'Dos Equis'
- **phone-09-typed** (typed) — false_abstain → correct: 'dark bar photo neon beer sign over the arcade machines which beer'
    - gold: 'The neon sign is a Dos Equis "XX" IMPORTED BEER sign, glowing red and orange on a purple painted wall. Below it are three lit-up upright arcade / video gambling machines, with a man in a pale short-sleeved polo standing at the leftmost one.' · A: '' · B: 'Dos Equis'
- **phone-10-full** (full) — partial → correct: 'What brand and slogan are on the label of the old empty glass soda bottle I photographed on a concrete ledge next to a brick wall?'
    - gold: 'It\'s an old empty Kay C root beer bottle sitting on a concrete ledge against a brick wall. The red-and-white paper label reads "The FIRST for THIRST — Drink Kay C — DELICIOUS ROOT BEER".' · A: 'KayC, Delicious Root Beer' · B: 'KayC, The FIRST for THIRST'
- **rcpt-02-full** (full) — false_abstain → correct: "What did I order on that McDonald's breakfast receipt with the two ChicMcMuffins, and what was the total?"
    - gold: "That McDonald's takeout (McDonald's BHP Taman Melawati, 18/01/2018) was 2 ChicMcMuffin at 11.00, 1 M Porridge at 5.60, 1 BM 2HotCakes at 10.00 and 1 L Coke. TakeOut Total incl GST was 26.60." · A: '' · B: '2 ChicMcMuffins, 11.00; 1 M Porridge, 5.60; 1 BM 2HotCakes, 10.00; 1 L Coke, 10.00; Total: 26.60'
- **study-02-full** (full) — wrong → correct: 'Which OOP concepts did I list on the mind map I drew in my C++ notes?'
    - gold: 'The OOPs concepts diagram in the C++ notes has eight branches around a "Concepts of OOPs" bubble: Object, Class, Inheritance, Message Passing, Polymorphism, Abstraction, Encapsulation and Dynamic Binding.' · A: 'C++ features' · B: 'message passing, polymorphism, abstraction, encapsulation, inheritance, dynamic binding, object, class, object is an instance of a class, class is a collection of objects, class is a "passive" entity,'
- **viz-01-full** (full) — wrong → correct: 'In that long-term food commodity price index chart, which commodity had the lowest index value, and what was it?'
    - gold: "Cocoa, at 18.81. In the Our World in Data chart 'Long-term price index in food commodities, 1850-2015', cocoa has the lowest index value of the fourteen commodities shown; lamb is highest at 103.7." · A: 'Denmark, 0.81' · B: 'Cocoa, 18.81'
- **viz-08-full** (full) — false_abstain → correct: 'In the millennials myths infographic, what share of millennials own a smartphone, and what share use it to feel connected to others?'
    - gold: "Under 'Myth 5: Millennials are always distracted by technology', the infographic says over 90% of millennials own a smartphone and 65% use it as a way to feel connected to others." · A: '' · B: '90%, 65%'
- **viz-11-full** (full) — partial → correct: 'In that Antarctic marine food web diagram, which seals are shown?'
    - gold: "Three seal labels appear in that marine food web diagram: leopard seal, elephant seal, and a general 'other seals' group. The rest of the labelled organisms are baleen whale, smaller toothed whales, penguins, birds, fish, krill, carnivorous zooplankton, other herbivorous zooplankton, and phytoplankton." · A: 'leopard seal and penguins' · B: 'leopard seal, penguins, elephant seal, other seals'
- **viz-11-typed** (typed) — false_abstain → correct: 'antarctic food web diagram which seals were on it'
    - gold: "Three seal labels appear in that marine food web diagram: leopard seal, elephant seal, and a general 'other seals' group. The rest of the labelled organisms are baleen whale, smaller toothed whales, penguins, birds, fish, krill, carnivorous zooplankton, other herbivorous zooplankton, and phytoplankton." · A: '' · B: 'baleen whale, other seals, penguins, fish, krill, leopard seal, elephant seal, smaller toothed whales'

## Retrieval hit@1 regressions — 0


## Retrieval hit@1 wins — 0


## Caveats (auto-generated)

- Retrieval per-question basis is `end_to_end` - what ask() actually returned to the answer stage.
- Discordant counts below ~5 are inside noise for this golden-set size; flagged rows say so. Do not tune on them.

<!-- magpie-compare agents append below this line -->


# Synthesis — supervisor

## 1. Verdict

**Yes, the prompt-image-order change worked, and the improvement is decision-grade.** Binding each
image to its own `--- File N ---` header moved paired answer quality from 0.125 to 0.275 (Δ +0.15)
on 22 discordant pairs (2A / 20B), McNemar p = 0.00012 — comfortably past both the ≥5-discordant
credibility floor and p < 0.05. It is decision-grade on all three counts the skill requires:
sufficient discordant pairs, a significant p, and **100% cause-attributed** (58 of 58 flips, no
unattributed residue).

The comparison is **clean, not confounded**: `params` byte-identical, `golden_sha` identical
(`0ebcdcbcdf109adb`), same mounted index (`66974090bdcd62e6`), same judge model (`claude-opus-5`)
and rubric sha (`47e93a279e70cef9`), and an identical `provenance.fingerprint`
(`2bd85ac1c6a9fd99`). Exactly one axis moved — code, `92f9ba9` → `4ce90a8`. compare.py's own axis
detection (`axes=code`) agrees.

Three qualifications, none of which touch the verdict:

- **The headline is entirely `prompt_assembly`.** All 22 discordant pairs behind p = 0.00012 are
  attributed to prompt assembly; the 14 `guard` flips contribute **zero** to the headline binary,
  because they shuffle between `wrong` / `false_abstain` / `false_answer` — all "bad" — and never
  cross the good/bad boundary.
- **The measured gain understates the change.** The grounding guard deleted several answers the new
  prompt made *correct* (verified: `arch-02-typed` produced the gold `4,58`; `arch-05-typed` the gold
  660 mg / 35 mg contrast; `study-05-full` the gold 180°/90° torque orientations; `rcpt-09-typed` a
  correct receipt comparison).
- **The apparent citation regression is a measurement artifact and reverses when corrected** (§4.1).

`model_variance` is **structurally unmeasurable** in this pair and is claimed nowhere: the user turn
differs on 120/120 rows, so no row received identical inputs twice. All three attribution agents
reached this independently. A zero here is therefore "not assessable", not "measured as zero".

## 2. Cause table

| Cause | Count | Improve | Regress | Headline-binary contribution |
|---|---|---|---|---|
| `prompt_assembly` | **44** | 37 | 7 | **20B / 2A — the entire headline** |
| `guard` | **14** | 7 | 7 | 0 |
| `retrieval_change` | 0 | — | — | 0 |
| `model_variance` | 0 (unmeasurable) | — | — | 0 |
| `judge_disagreement` | 0 | — | — | 0 |
| `infra_error` | 0 | — | — | 0 |
| **Total** | **58** | 44 | 14 | 22 |

`judge_disagreement` at 0/58 (0%) is far below the ~20% threshold that would make this comparison
judge-limited. No stop condition is triggered.

**The single change the data points at: images must be bound to their file header.** On a corpus that
is 100% images at `top_k = 2`, arm A sent file headers with *nothing beneath them* and shipped every
image out-of-band after all the text, so the model had no way to know which picture belonged to which
`File N`. The failure signature is unmistakable and repeats across categories — arm A answering off
the *wrong* image while citing the wrong `File N` label:

- `viz-01-full` — A "Denmark, 0.81"; Denmark appears only on `chart_030.jpg`, the *other* retrieved
  file. B: "Cocoa, 18.81", correct off `chart_001.jpg`.
- `phone-02-full/typed` — A "palm" (from `scene_52b557…`, a Palm phone); B "NUC5i7RYH" (from
  `scene_0464…`, the Intel NUC box). Same two images both arms.
- `phone-01-typed` — A "Scoutdoors" (File 1); B "Champaign, IL" (File 2, the weather screen).
- `viz-02-typed` — A invented "Australia", a country printed nowhere on `chart_010.jpg`.
- `viz-06-typed` — A echoed the query verbatim; B lifted "$6 BILLION" in the poster's own capitals.

The secondary mechanism, the question-position move, is real but smaller: verbatim query echoes went
**5 → 0** (independently reproduced by the supervisor: A = `viz-06-typed`, `nf-02-typed`,
`nf-06-typed` exact plus `arch-06-typed`, `rcpt-02-typed` substring; B = none). It explains only 2 of
the 7 `nf-*` flips — the other four arm-A false answers were wrong-file over-answering, not query
copying. Because the four commits ship together, one run per arm cannot fully separate (a) from (b).

### The 14 `guard` flips are label noise, not signal

7 improvements and 7 regressions — perfectly symmetric, contributing nothing net and nothing to the
headline. Every one fails the counterfactual *"would this flip still exist with the guard off?"*: on
the merits both arms are wrong (or both acceptable), and only the guard's differential firing moved
the label. Two rows where the guard fired but the flip **survives** guard-off (`rcpt-02-full`,
`viz-08-full`) were correctly attributed `prompt_assembly` instead.

On an all-image corpus the guard's support text is empty by construction, so `looks_fabricated`
reduces to *"does the answer contain a numeral ≥ `MIN_INTERESTING` (100)?"*. That makes it arbitrary:

- **Year tokens trigger it.** `viz-05-full` A was deleted for citing `93.45% (2002)` and
  `89.89% (2009)` — both literally printed on `chart_036.jpg`.
- **Trailing commas exempt an answer.** `numerals()` puts the comma inside `\d[\d,]*`, so
  `float("1979,")` raises and the token is silently dropped. `study-01-full` flips on nothing else:
  `"C++; 1979; Bell Labs"` → `['1979']` (deleted) vs `"Bjarne Stroustrup, 1979, Bell Labs."` → `[]`
  (survives). Verified by direct execution.
- **French decimal commas are read as thousands separators.** `numerals("4,58")` → `['458']`,
  inflating 4.58 past the threshold. This fired on `arch-02-typed`'s *correct* gold value, and it
  will mis-parse the entire `tables_fr` category systematically.
- **The threshold is a coin flip.** `study-05-full` (90 passes, 180 fires), `study-11-full/typed`
  (7,000,000 fires, 15.5 and 32.5 pass), `rcpt-09-typed` (rupiah figures destroyed) vs
  `rcpt-02-full` (ringgit figures small enough to survive). On this corpus the guard's behaviour is
  effectively a function of currency denomination.

**Two log notes must not be conflated**, or false abstentions get over-attributed to the guard:
`note: every figure in the answer is absent from the files read` (`src/answer.py:1030`) is the guard;
`note: not_found=true but answer/sources_used were non-empty; clearing them` (`src/answer.py:945`) is
the not-found-contract normaliser firing on the **model's own** `not_found=true`.

## 3. Slice story

Reporting only slices whose discordant counts make them meaningful:

| Slice | A | B | Δ | discordant | p | decision-grade? |
|---|---|---|---|---|---|---|
| `phrasing=full` | 0.1833 | 0.35 | +0.1667 | 0A / 10B | 0.00195 | **yes** |
| `phrasing=typed` | 0.0667 | 0.20 | +0.1333 | 2A / 10B | 0.03857 | **yes** |
| `answer_type=extractive` | 0.0571 | 0.1714 | +0.1143 | 1A / 9B | 0.02148 | **yes** |
| `answer_type=enumeration` | 0.1667 | 0.5833 | +0.4167 | 0A / 5B | 0.0625 | no — context only |
| `answer_type=not_found` | 0.5625 | 0.875 | +0.3125 | 1A / 6B | 0.125 | no — context only |
| `answer_type=synthesis` | 0.0 | 0.0 | 0 | 0A / 0B | 1.0 | no — nothing moved |

**Both phrasings improve significantly, and the mechanism is shared.** Inline placement fixes the
*reading* step, which is phrasing-independent — typed actually flipped more rows in absolute terms.
The residual gap is a word-budget effect at the *writing* step: typed answers stay terse, so a
corrected read lands as `partial` where full phrasing earns `correct`. `viz-01` is the controlled
demonstration — same file, same read, "Cocoa" (partial) vs "Cocoa, 18.81" (correct).

The headline enumeration (+0.4167) and not_found (+0.3125) deltas are the largest in the table and
**must not be quoted as findings** — 5 and 7 discordant pairs, p ≥ 0.05. They are consistent with the
verdict, not evidence for it. `synthesis` remains at 0.0 in both arms: this change did nothing for
cross-file reasoning, which is the one slice untouched.

## 4. Regression-hunter findings

### 4.1 The citation regression is a parsing artifact, and the direction reverses · CONFIRMED

`metrics.json` reports `cited` .471 → .279, precision .188 → .139, recall .206 → .107 and
`zero_citation_answers` 28 → 49. This is a filter bug, not behaviour. The exact-string filter at
`src/answer.py:971-987` (`_normalize_path_for_match`, `src/answer.py:1041`) collapses whitespace,
URL-decodes and strips a trailing `[...]`, but does **not** strip a `--- File N: ` / `File N: ` /
`file: ` prefix. The JSON schema instructs the model to copy the path *"verbatim from the
`--- File N: <path> ---` headers"*, and in B the header now sits directly above its image — so the
model copies the whole header and the filter discards a correct path.

The supervisor confirmed this independently from the worker logs, which record every drop as
`warn: dropped hallucinated source paths`: 41 (A) → 50 (B), but the *character* of the drops inverts.
A drops genuine hallucinations (wrong directory `corps/`, URLs, chart titles, bare `CSC-105`);
B drops correct paths carrying a prefix (`File 2: …/chart_001.jpg`, `--- File 2: …/chart_036.jpg`,
`file: …/arxiv_025.png`).

Recomputed against `qrels.tsv` with a prefix/ordinal-tolerant filter, same n = 104:

| metric | A as-is | B as-is | A corrected | B corrected |
|---|---|---|---|---|
| citation_precision | 0.1875 | 0.1394 | 0.2885 | **0.3846** |
| citation_recall | 0.2057 | 0.1068 | 0.3307 | **0.3440** |
| zero_citation rate | 47.5% (28/59) | 72.1% (49/68) | 23.7% (14/59) | **23.5% (16/68)** |

**Corrected, B is better on precision, flat on recall, and identical on zero-citation rate** — the
raw count rose only because B has 9 more non-abstain rows to score. The judge's `citation_ok`
(25T/38F → 17T/51F) inherits the same artifact. **Do not ship a citation-regression finding.**

### 4.2 The guard is now the single largest remaining accuracy lever · CONFIRMED

| | A | B |
|---|---|---|
| false_abstain total | 45 | 36 |
| — caused by the guard | 31 (69%) | **33 (92%)** |
| — model's own `not_found` | 14 | **3** |
| guard fires landing on a *correct* abstention | 0 | 0 |

The prompt reorder cut the model's own spurious not-founds by 79% (14 → 3), leaving the guard as
essentially the only remaining source. Every guard fire in both arms lands on a false abstention;
none lands on a correct one. Fix or disable it and `false_abstain` plausibly collapses from 36 to ~3.

### 4.3 Latency: real, small, and unattributed · CONFIRMED (absence of cause)

B is genuinely slower — 78/119 rows, one-sided binomial p = 4.4e-4; +4.4% excluding the outlier. All
of it is inside the LLM call (per-request `latency_s` +128.6s while non-LLM overhead *fell* 9.5s).
Every candidate cause was tested and rejected: prompt text is *shorter* (mean 1117 → 1013 chars,
corr 0.09); image payload is byte-identical per row in both arms (0 rows differ, 251.9 MB total);
B generated 32% fewer characters; no uniform multiplicative slowdown (corr −0.05). A per-image
prefill hypothesis (5.00 → 5.26 s/image, right magnitude) does **not** survive stratification by run
position, and with no same-code repeat run the host-noise floor is unbounded. **Recorded as
unattributed.**

**The commit's stated prompt-cache rationale is provably inapplicable to this eval · CONFIRMED.**
0 of 120 prompts contain conversation history, only 20 of 119 consecutive requests present an
identical file list (the theoretical reuse ceiling), and those 20 got *slower* in B (+1.24s vs
+0.68s). No `cache_prompt` is sent in `_build_request_body`; no `--cache-reuse` in the pool argv.
The optimisation targets product follow-up turns, which this harness never exercises — so `4ce90a8`'s
cache claim is neither confirmed nor refuted here, merely untestable.

### 4.4 Degenerate generation is not a new failure mode · CONFIRMED, benign

Exactly **one runaway repetition per arm** — A `viz-10-typed` (5,274 chars, 41.6s), B `phone-07-full`
(7,479 chars, 44.0s) — and each is clean in the other arm. Crucially, `phone-07-full` already emitted
the "Bud Light" repetition in A (10 repeats); B escalated a latent bug rather than creating one.
Mild repetition is *less* common in B (2 vs 4). Its +36s is a coin-flip, not a regression.

**Judge rubric hole worth its own ticket:** the 7,467-char Bud Light loop was graded **`correct`,
4/4 facts**, with the judge's own reason noting *"the output then degenerates into hundreds of
repetitions of 'Bud Light'"*. A product-unusable answer counts as a headline win. Present in both
arms, so it does not bias this delta — but the rubric should hard-fail on degeneracy.

### 4.5 Prompt size, truncation, infra: nothing moved · CONFIRMED, benign

Prompt text fell 9.4% (134,081 → 121,512 chars) — the dropped duplicate question copy. **Zero**
`[...truncated` markers in either arm. Budget-driven file drops hit the **same 9 qa_ids** in both.
`_trim_blocks_to_budget` / `_block_cost_chars` / `_context_budget_chars` are untouched between the
SHAs; system prompt and `response_format` schema byte-identical; ENUMERATION 10/10 and SYNTHESIS
10/10 in both. `error` null on all 120 rows in both arms, one llama-server spawn per run, no
respawns, retries, timeouts or context overflows.

### 4.6 Not-found contract: a real improvement hiding under a falling count · CONFIRMED

Contract-violation normalisations fell 22 → 17, but the composition inverted: A's 22 split
14 false_abstain / 8 correct_abstain, B's 17 split **3 false_abstain / 14 correct_abstain**. A was
discarding text on *answerable* questions (`viz-03-full` had `"Amused 88% [1]"` cleared and scored
false_abstain; 3 A rows had >50% token overlap with gold, 0 in B). The residual is a product bug in
**both** arms: the grammar enforces the schema but not the cross-field invariant
`not_found=true ⇒ answer empty`, so ~1/3 of not-found emissions still need server-side normalisation.

### 4.7 Confirmed non-movers

`in_prompt` {full 277, solo_excluded 6, dropped 57} identical; `h1_basis` {file_level_image: 73} in
both with `mixed_basis: false` and eligible 49/70 — **the H1 slice is basis-comparable across these
two arms** (0.041 → 0.184); `key_fact_spans` unknown_image_block 242 vs 240; solo gate unchanged;
`not_found_topic` empty 1 → 3 but all three B rows have `not_found=false`, so the field never renders.
**Answer length did not move**: the apparent median 26 → 16 chars is composition, not behaviour — on
the 50 rows answered non-empty in *both* arms the paired delta is a median of **+0.5 chars** (18
shorter, 25 longer). The single genuine terseness casualty is `viz-01-typed`.

## 5. Recommended next run

**Re-run this exact arm with `MAGPIE_GROUNDING_GUARD=0`, changing nothing else.**

It is the single change that best answers the owner's question, because the guard is the only thing
standing between the measured +0.15 and the change's true effect. It causes 92% of B's remaining
false abstentions, it deleted at least four answers this change made *correct*, and its firing rule
on an all-image corpus reduces to "contains a numeral ≥ 100" — with three verified parsing defects
(trailing-comma drop, French decimal comma read as a thousands separator, and a `MIN_INTERESTING`
threshold that admits or destroys answers by currency denomination). Projected effect: `false_abstain`
36 → ~3, `correct` roughly 19 → 32.

**Cost: low.** The index mounts from the store (`66974090bdcd62e6`, HIT, ~0.2s — no rebuild, since
no index-side param changes); answer-phase wall clock ≈ 2,300-2,400s, so ~40 minutes end to end plus
the judge. Per CLAUDE.md the knob is already threaded through `envctl.build_env` and defaulted in
`compare.py`'s `PARAM_DEFAULTS`, so this is a **config-only arm on one knob** — it preserves the
one-knob-per-comparison rule (#115) and stays comparable to both runs here.

Two cheap harness fixes should land before or alongside it, because both change measured numbers
without changing product behaviour: the citation prefix filter (§4.1, ~10 lines in `src/answer.py`,
recovers 23 rows in B and 15 in A) and the `numerals()` comma handling (`src/grounding.py`). Not
recommended next: another prompt-layout arm — layout is now well-measured, and the guard dominates
everything downstream of it.

---

*Attribution provenance: 58/58 flips attributed by three batched agents, each spot-checked by the
supervisor against raw artifacts (guard-note membership derived independently from
`raw/worker_answer.log`; raw pre-guard answers recovered from the pinned `llm-*.log`; `numerals()`
re-executed directly; query-echo counts independently reproduced). One agent's `arch-05` /`viz-11`
noise call was overturned on evidence — see SUPERVISOR-REPORT.md §4 in the arm's run directory.
Golden set remains SILVER (120 model-authored items, 0 human-verified; judge flagged 7 golden issues
in each arm), so absolute rates are uncalibrated — the arm-vs-arm delta is what this comparison
establishes.*
