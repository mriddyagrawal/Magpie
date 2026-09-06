# ANSWERS report — 20260906T090247Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

> SILVER golden set (0/120 human-verified). Every rate below is provisional.
> This report explains **why** answers succeeded or failed. It is not a rescoring of the run;
> where I disagree with the judge or the deterministic matcher I say so and give the reason.

Config under test: `top_k=2`, rerank OFF, rewrite OFF, `solo_margin=0` (gate structurally dead),
temperature 0, `local_n_ctx=16384`, LFM2.5-VL-3B Q6_K local, ColQwen2.5 visual retrieval,
`MAGPIE_GROUNDING_GUARD=1`, `MAGPIE_STRICT_GROUNDING=1`. 545-file all-visual corpus,
120 golden items in 60 typed/full pairs (104 answerable, 16 `not_found` probes).

Headline as recorded: correct 0.038, partial 0.163, wrong 0.365, false_abstain 0.433 (deterministic);
judge: 6 correct, 17 partial, 36 wrong, 45 false_abstain, 9 correct_abstain, 7 false_answer.

---

## 0. The one-paragraph answer

**This run's dominant failure is not the model and not retrieval — it is a deterministic
post-processing rule.** Retrieval put a gold file into the prompt on 97 of 104 answerable
questions. The model then produced text on 90 of them. But 53 answers were converted to
`not_found` before they reached the scorer, and **31 of those 53 were killed by the numeral
grounding guard in `src/answer.py:_apply_grounding_guard`** — a rule that, on an all-image
corpus, reduces to *"if the answer contains any number >= 100, return not-found."* I replicated
its firing condition exactly: 31 true positives, 0 false positives, 0 false negatives across all
120 rows. Re-scoring the 31 suppressed texts against their own golden items turns
**4 into `correct`, 18 into `partial`, and only 9 into `wrong`.** The guard is therefore
destroying roughly 3 good answers for every 1 fabrication it catches on this corpus, and it
accounts for 69% of every "false abstention" in the headline metric.

---

## 1. Failure clusters, ranked by size, with mechanism

Sizes are over the 104 answerable items. Clusters 1 and 5 are `false_abstain` (silence);
clusters 2-4 and 6 are `wrong`/`partial` (bad content). They have different causes and
different fixes.

### Cluster 1 — Grounding-guard numeral suppression (31 items, 30% of answerable, 69% of all false abstentions)

**Mechanism, exactly.** `_apply_grounding_guard` builds its support text from
`[b for _d, blocks in per_file_blocks for b in blocks if isinstance(b, str)]` — *text* blocks
only. Image blocks contribute nothing. `MAGPIE_STRICT_GROUNDING=1` then strips index-time
summaries. On this corpus that leaves an empty or near-empty support string: I measured the
text between the `--- File N: <path> ---` headers in all 120 prompts —
**71 prompts contain literally zero characters of text, 40 contain only the 62/129-byte
banner `Content type: pdf (scanned / image-only — N page(s) as images)`, and 9 contain a real
text layer.** `looks_fabricated` then fires whenever the answer contains at least one numeral
that `src/grounding.py:numerals` considers interesting, i.e. `abs(value) >= 100`
(`MIN_INTERESTING = 100`).

**Verification.** Re-running the shipped `looks_fabricated` against each row's own raw model
output and its own prompt text reproduces the guard perfectly: TP 31, FP 0, FN 0, TN 89.
The converse also holds — **of the 67 answers that survived to the user, exactly zero contain a
numeral >= 100.** The guard is not "conservative" here; it is a total filter on large numbers.

Guard-fired qa_ids (31): `arch-02-full`, `arch-03-full`, `arch-03-typed`, `arch-06-full`,
`arch-07-full`, `arch-07-typed`, `arch-09-full`, `arch-09-typed`, `arch-10-full`,
`arch-10-typed`, `phone-04-full`, `phone-04-typed`, `rcpt-01-full`, `rcpt-01-typed`,
`rcpt-02-full`, `rcpt-03-full`, `rcpt-03-typed`, `rcpt-06-full`, `rcpt-06-typed`,
`rcpt-07-full`, `rcpt-07-typed`, `rcpt-09-full`, `study-01-full`, `study-01-typed`,
`study-03-full`, `study-03-typed`, `study-11-full`, `study-11-typed`, `viz-04-typed`,
`viz-05-full`, `viz-08-full`.

**What was destroyed.** Re-scoring the suppressed texts with the harness's own
`fact_in_text`/`deterministic_verdict`:

| counterfactual verdict | n | examples (suppressed text -> gold) |
|---|---:|---|
| correct | 4 | `arch-03-full` "849" -> gold 849; `arch-06-full` "Total dissolved solids at 105C: 1506.0; pH: 7.8" -> gold 1506.0 / 7.8; `arch-07-full` "1,271m vs 1,695m ... 42.9% to 41.2%" -> all four gold facts; `arch-09-full` "216.00 / 318.40" |
| partial | 18 | `phone-04-typed` "4863"; `rcpt-01-typed` "45,500"; `rcpt-06-typed` "Rp224,908"; `rcpt-03-full` "280,000 ... BCA Card"; `study-03-typed` "$3,000 per kW ... 67.5 MWh per year"; `study-01-full` "C++; 1979; Bell Labs" |
| wrong | 9 | `study-11-typed` "7,000,000"; `rcpt-07-full` "50,000 cash"; `viz-05-full` "Egypt: 93.45%, Tunisia: 89.89%"; `rcpt-01-full` "16,500" |

Whole-run counterfactual with the guard off, deterministic matcher, n=104:

| | correct | partial | wrong | false_abstain |
|---|---:|---:|---:|---:|
| as run | 0.038 | 0.163 | 0.365 | **0.433** |
| guard OFF | **0.077** | **0.337** | 0.452 | **0.135** |

Two sub-bugs worth separating from the main one:

- **Years trip the guard.** `MIN_INTERESTING = 100` does not exclude 4-digit years, and a year
  is never in an image prompt's text. Four fires have *no other* large numeral: `viz-04-typed`
  ("42% in 1979"), `viz-05-full` ("(2002) ... (2009)"), `study-01-typed` and `study-01-full`
  ("1979"). Two of those (`study-01-*`) were otherwise good answers about Bjarne Stroustrup's
  C++ that died on the token "1979".
- **`arch-03-typed` was killed for regurgitating the system prompt.** Its suppressed text is
  `"CSC-105 has 4 credit hours and is offered every fall"` — verbatim the citation-format
  example in Magpie's own system prompt. The guard fired on "105". Here the guard did the right
  thing for the wrong reason; the real defect is prompt regurgitation (see section 7).

### Cluster 2 — Wrong cell / wrong series / wrong subject inside the *correct* file (~12 wrong plus most of the 17 partials)

The gold file was in the prompt, the model looked at it, and read the neighbouring value.
This is the model-capability failure, and it is what the run would mostly be measuring if the
guard were off.

- `viz-04-full` — "In 2014, 29% ... in 1979, 7%". I opened `chart_037.jpg`: the 2014 row reads
  7 / 25 / 9 / **29** / **20** / 7 left-to-right. 29% is the *center-right* segment immediately
  left of the correct 20% right-to-far-right value. 1979's 7% is right.
- `phone-08-typed` / `phone-08-full` — "0 trips". I opened `screen_24243.jpg`: "Get a free*
  one-way ticket for every **8 trips** traveled." The "priority (Group A) boarding" half is
  verbatim correct. A digit was invented next to a correctly copied phrase.
- `arch-05-typed` — "Coca-Cola and Diet Coke ... both containing about 35 milligrams". I opened
  `doc_357.jpg`. The leaflet's right column reads "a six-fluid ounce serving of tomato juice
  processed with added salt has 660 milligrams of sodium, while the same size serving of diet
  Coke has 35 milligrams or less", and its left column separately says Coca-Cola USA products
  have "less than 35 milligrams". The model substituted the *subject* of the comparison
  (Coca-Cola for tomato juice), keeping a number that is individually grounded.
- `study-08-full` — right deck `deck_027.pdf`, wrong page (the "MEMS and microfluidics" box is
  on slide 1, the pie chart is on the last slide).
- `study-09-typed` — "outer product of the query matrix V and key matrix K" for `arxiv_029.png`:
  right figure, transposed symbol roles.

### Cluster 3 — Neighbour-document bleed: the answer comes from the rank-2 file (9 wrong)

With `top_k=2` and rerank off, exactly one unfiltered distractor is half of every prompt.

- `phone-03-typed` and `phone-09-full` both answer **"ORDER, TIP WELL, WALK AWAY"**. The judge
  guessed this came from "some third bar photo". It did not: **`info_021.jpg` was the other
  prompt file on both rows.** I opened it — it is the "HOW TO ORDER A BEER WITHOUT BEING A
  DOUCHEBAG" GUY CODE flowchart, and "ORDER, TIP WELL, WALK AWAY." is printed in its
  bottom-left beer glass. Both rows' raw `sources_used` was literally `["GUY CODE"]`, the
  infographic's logo — which the path filter then dropped, hiding the provenance from the judge.
- `viz-01-full` "Denmark, 0.81" <- `chart_030.jpg` (rank 2), while `viz-01-typed` read
  `chart_001.jpg` correctly ("Cocoa at 18.81"). Same retrieval set, opposite file chosen.
- `phone-01-typed` "Scoutdoors" <- `screen_24626.jpg`; `phone-02-typed`/`phone-02-full` "palm"
  <- `scene_52b557c0cff76f70.jpg`; `study-06-typed` (DES / GZ_notrain / GZ_train distributions)
  <- `arxiv_018.png`; `study-09-full` mixes "phi(q) = integral of E.dS" — that is the *physics*
  neighbour `electric-charge-and-field-14.pdf` — into a description of an attention figure.

**Prompt-order note (new).** In all 104 two-file rows the prompt presents the **retrieval rank-2
file as "File 1"** and rank-1 as "File 2" — the order is reversed, without exception. The gold
file is therefore the *last* file in 82 of the 89 two-file rows where gold was present. This
does not obviously hurt (recency favours gold), but it does mean every `[1]` marker the model
writes points at the distractor, and every "File 1" it echoes names the distractor. Worth a
deliberate decision rather than an accident.

### Cluster 4 — Degenerate echo: the question, a heading, or a brand returned as the answer (9 wrong)

`viz-06-typed` returns the literal query string "diabetes australia infographic annual cost"
while citing the correct `info_024.jpg`; `arch-06-typed` returns "Fort Morgan Sugar Factory"
(the question's subject); `study-02-typed`/`study-02-full` return "C++ features" (the page
heading); `study-04-typed` and `study-10-typed` return "C++ Tutorials [1]"; `rcpt-02-typed`
returns "McDonalds"; `viz-08-typed` returns "7"; `rcpt-09-typed` returns "Original brewed tea
was pricier".

**Mechanism: answer length collapses under terse prompts.** Median answer length is
**3 words for typed phrasings and 11 words for full phrasings**; 30 of the 59 non-abstain
answerable answers are <= 4 words, and 8 of the 9 degenerate echoes are typed. A 3B VL model
given a 9-word keyword string and told "be concise" emits the most salient string on the page.
This is a prompt-interaction failure, not a vision failure — the model demonstrably read the
right file (it cited it) and just did not produce a proposition.

### Cluster 5 — Model-initiated literalist abstention (14 items, the other 31% of false abstentions)

These 53 abstentions partition perfectly: 31 guard, 22 model-set (`note: not_found=true but
answer/sources_used were non-empty; clearing them`), **zero overlap, zero unexplained.**
Of the 22 model-set, 8 are the correct declines on `not_found` probes; 14 are false abstentions
on answerable items: `arch-01-typed/full`, `arch-05-full`, `arch-08-typed/full`,
`phone-07-typed`, `phone-09-typed`, `rcpt-08-typed/full`, `study-08-typed`, `viz-03-full`,
`viz-07-typed/full`, `viz-11-typed`.

Two sub-mechanisms:

- **Title literalism.** `viz-11-typed`'s cleared text says outright: *"The provided files contain
  an Antarctic food web diagram but do not include a specific diagram titled 'antarctic food
  web'..."* — the exact failure the system prompt's terminology rule was written to prevent.
  `arch-05-full` and `viz-07-full` are the same shape.
- **The contract-clearing rule eats good content (2 of 14).** `viz-03-full` produced
  `"Amused 88% [1]"` *and* set `not_found=true`; `arch-08-full` produced `"Hazard ratio 2Q2002,
  confidence interval not found"`. `src/answer.py` then blanks both because the not-found
  contract has no slot for an answer. In `viz-03-full`'s case the accompanying `sources_used`
  was ``":[1]]}```json``` The answer is Amused, 88%. ..."``, i.e. the grammar-constrained JSON
  had degraded, and the flag was set by a malformed decode rather than by a decision to decline.

### Cluster 6 — Page-level corpus fragmentation: gold page never retrieved (7 items)

Only 7 of 104 answerable rows had **no** gold file in the prompt: `rcpt-05-typed`,
`rcpt-07-typed`, `rcpt-07-full`, `study-05-typed`, `study-05-full`, `study-10-typed`,
`study-10-full` (5 wrong, 2 false_abstain). Five of the seven are the same structural problem:
`notes_handwritten/` is one study document exploded into 20 near-identical single-page PDFs
(`CseGyan-Cpp-Notes-1..20.pdf`, plus 17 `electric-charge-and-field-*.pdf`). ColQwen cannot
discriminate between 20 pages of the same handwriting, and `top_k=2` gives it two tries.
`study-10` wanted pages 17/18/19 and got 14/15; `study-05` wanted page 9 and got 7/10.
When retrieval *does* land gold the outcome distribution is barely better
(43 abstain / 31 wrong / 17 partial / 6 correct over 97), so this cluster is real but small —
it is not the reason the run scores 3.8%.

---

## 2. Abstention behaviour: what actually makes this model go silent

I tested candidate discriminators against the 104 answerable rows rather than asserting one.
Outcome = `not_found` set (n=45).

| candidate discriminator | abstain rate if TRUE | if FALSE | risk diff | odds ratio | chi2 (1 df) |
|---|---|---|---:|---:|---:|
| **gold `key_facts` contain a number >= 100** | **35/44 = 0.80** | **10/60 = 0.17** | **+0.63** | **18.0** | **40.9** |
| gold *answer prose* contains a number >= 100 | 39/58 = 0.67 | 6/46 = 0.13 | +0.54 | 12.6 | 30.7 |
| gold `key_facts` contain any digit | 42/82 = 0.51 | 3/22 = 0.14 | +0.38 | 5.9 | 10.0 |
| > 2 images in the prompt | 17/28 = 0.61 | 28/76 = 0.37 | +0.24 | 2.6 | 4.8 |
| multi-file question | 10/18 = 0.56 | 35/86 = 0.41 | +0.15 | 1.8 | 1.3 |
| difficulty = hard | 16/30 = 0.53 | 29/74 = 0.39 | +0.14 | 1.8 | 1.7 |
| gold source is a PDF | 12/24 = 0.50 | 33/80 = 0.41 | +0.09 | 1.4 | 0.6 |
| >= 4 key facts | 25/52 = 0.48 | 20/52 = 0.38 | +0.10 | 1.5 | 1.0 |
| phrasing = full | 24/52 = 0.46 | 21/52 = 0.40 | +0.06 | 1.3 | 0.4 |
| answer_type = extractive | 30/70 = 0.43 | 15/34 = 0.44 | -0.01 | 1.0 | 0.0 |
| difficulty = easy | 12/28 = 0.43 | 33/76 = 0.43 | -0.01 | 1.0 | 0.0 |

**Winner, by a wide margin: "does the gold answer require reading a printed multi-digit
number".** 0.80 vs 0.17, chi2 = 40.9. Category, difficulty, `answer_type`, phrasing, key-fact
count and multi-file-ness are all at or near null — the by-category table in JUDGE-REPORT.md
("the archive and receipt tiers are effectively non-functional") is this same variable in
disguise: receipts, French financial tables and archive scans are precisely the categories whose
gold answers are large printed numbers.

Splitting the outcome shows the two mechanisms are cleanly separable:

| predictor | guard abstention (n=31) | model-initiated abstention (n=14) |
|---|---|---|
| gold key_facts contain >= 100 | 0.64 vs 0.05, OR 28.4, **chi2 41.7** | 0.16 vs 0.12, OR 1.4, chi2 0.4 |
| > 2 images in prompt | 0.32 vs 0.29, OR 1.2, chi2 0.1 | 0.29 vs 0.08, OR 4.5, **chi2 7.5** |

- The number predictor drives **only** the guard, exactly as the code predicts.
- The image-count predictor drives **only** the model's own declining, and not the guard at all.
  Abstention rises monotonically with prompt image count — 0.37 at 2 images (n=76), 0.45 at 5
  (n=11), 0.62 at 6 (n=8), and 1.00 at 7/8/9/10/12 images (n=1 each). **This is directional
  only**: the tail cells are n=1, and the 5 rows with >= 7 images (`arch-03-typed`,
  `rcpt-01-full`, `rcpt-08-full`, `rcpt-08-typed`, `phone-07-typed`) are also rows where the
  12-candidate retrieval path fired, so image count and retrieval path are confounded here. The
  honest statement is: **more images correlates with the model declining, chi2 7.5 at n=104, and
  the effect cannot be separated from the deep-retrieval path in this run.**

Everything else is noise at this n. In particular, do not report "hard questions abstain more"
(chi2 1.7) or "full phrasing abstains more" (chi2 0.4) as findings.

---

## 3. typed vs full, paired over `pair_id` (McNemar)

60 complete pairs (52 answerable, 8 `not_found`). Discordant-pair counts with exact two-sided
binomial p-values:

| success criterion (answerable pairs, n=52) | both | neither | typed-only | full-only | p |
|---|---:|---:|---:|---:|---:|
| judge = correct | 0 | 46 | 1 | 5 | **0.219** |
| judge in {correct, partial} | 8 | 37 | 1 | 6 | **0.125** |
| attempted an answer (not abstain) | 23 | 16 | 8 | 5 | 0.581 |
| deterministic = correct | 0 | 48 | 1 | 3 | 0.625 |
| deterministic in {correct, partial} | 5 | 36 | 3 | 8 | 0.227 |
| grounding guard fired | 12 | 33 | 1 | 6 | 0.125 |

**Phrasing does not change the success RATE at this sample size.** The unpaired headline
("full beats typed 5 to 1 on strict correct", 9.6% vs 1.9%) rests on **6 discordant pairs**:
typed-only `viz-01`; full-only `phone-01`, `phone-05`, `phone-07`, `viz-06`, `viz-10`. Exact
p = 0.219. Directional in favour of full, not established. The same is true of
correct-or-partial (p = 0.125).

**Phrasing does change the failure MODE, strongly.** 19 of 52 answerable pairs (37%) plus 3 of
8 `not_found` pairs = 22 of 60 got different verdicts. The transition matrix:

```
typed \ full     correct  partial    wrong  false_ab
correct                0        0        1         0
partial                1        7        0         0
wrong                  3        1       10         8
false_abstain          1        1        3        16
```

The mass off the diagonal is `wrong <-> false_abstain` (8 + 3 = 11 of the 19 flips) — the same
pair flipping between *saying something bad* and *saying nothing*, with success unchanged.
Abstention itself is a coin flip across phrasings: typed-only 5, full-only 8, p = 0.581.

**Why the mode moves.** Median answer length is 3 words (typed) vs 11 words (full). A 3-word
answer either hits the single gold token or scores `wrong` with no partial credit; an 11-word
answer usually carries a second fact and lands `partial`. That is the whole of the "typed is
worse" effect: typed n(wrong) = 22 vs full 14, typed n(partial) = 8 vs full 9. The model is not
reading the images better under prose phrasing; it is writing more sentences.

`not_found` probes (n=8 pairs): full-only correct_abstain on `nf-02`, `nf-06`, `nf-07`,
typed-only zero, p = 0.250. Same story — directional, not established. The mechanism the judge
names (terse one-word probes pull a plausible file) is plausible and matches the three cases,
but 3 discordant pairs cannot carry it.

---

## 4. The grounding guard, quantified for THIS run

Already covered in section 1; the audit numbers in one place:

| quantity | value |
|---|---:|
| stderr notes `every figure in the answer is absent from the files read` in `raw/worker_answer.log` | **31** |
| stderr notes `not_found=true but answer/sources_used were non-empty` | 22 |
| total `not_found` rows in `answers_enriched.json` | 53 |
| abstentions explained by guard / by model / unexplained | 31 / 22 / **0** |
| guard fires as a share of the 45 false abstentions | **31/45 = 69%** |
| guard fires as a share of all 104 answerable items | 30% |
| independent replication of the firing predicate (`looks_fabricated` re-run on raw outputs) | TP 31, FP 0, FN 0, TN 89 |
| surviving answers containing a numeral >= 100 | **0 of 67** |
| prompts with zero text between file headers | 71 of 120 |
| prompts whose only text is the `Content type: pdf ... as images` banner | 40 of 120 |
| guard fires by phrasing | 18 full / 13 typed |
| pairs where the guard fired on **both** phrasings | 12 (`arch-03`, `arch-07`, `arch-09`, `arch-10`, `phone-04`, `rcpt-01`, `rcpt-03`, `rcpt-06`, `rcpt-07`, `study-01`, `study-03`, `study-11`) |

The count is **not** run noise: the prior identical-config run
(`20260830T095758Z-...`) logs **31** guard notes as well (and 18 contract-clears vs 22 here).
The guard is a fixed structural tax of ~30% of answerable items on any all-image corpus,
independent of the backend changes between the two runs.

The docstring at `src/answer.py:933-943` already states this ("31 conversions per run on the
all-image custom_dataset_rahul evals, ~two thirds of every 'false abstention'"). This report
confirms the figure independently and adds the per-item consequences, which the docstring does
not have: **4 correct and 18 partial answers were among the 31.**

---

## 5. Citations

### 5a. Nothing was actually hallucinated

**All 56 entries across the 35 `magpie_cited` lists name a file that was in that row's prompt.
Zero exceptions.** The `hallucinated_citations = 0.183` figure in `metrics.json` (17 rows) is a
misnomer: every one of those 17 rows cites a real, in-prompt, non-gold file — the rank-2
neighbour. Examples: `viz-01-full` cites `chart_030.jpg` (in prompt, not gold);
`study-02-typed` cites `CseGyan-Cpp-Notes-7.pdf` alongside the gold `-3.pdf`; `phone-01-typed`
cites `screen_24626.jpg`. Only `study-10-typed`/`study-10-full` cite files that are neither gold
nor acceptable, and that is because gold was never retrieved. **Recommendation: rename the
metric to `non_gold_citations`, or compute genuine hallucination as "cited path not in
`in_prompt`", which is 0.000 for this run.**

The reason it is 0.000 is structural, not virtuous: `src/answer.py` already filters
`sources_used` against the input paths and logs `warn: dropped hallucinated source paths`.
Which leads to the real citation defect:

### 5b. The 32 zero-citation answers are a path-echo failure, not a refusal to cite

Of 67 non-abstain rows, only **2** had an empty `sources_used` from the model. **30 rows emitted
non-empty `sources_used` that was entirely discarded** by the path filter. Token shapes across
all raw citation tokens:

| shape | count | example |
|---|---:|---|
| exact filename present in the prompt | 88 | `receipt_022.jpg` |
| bare ordinal / "File N" / "file:2" | 24 | `"1"`, `"file 2"`, `"file:2"` |
| a string from the page, not a path | 32 | `"GUY CODE"`, `"TOURISM'S VALUE TO AUSTRALIA, 2014-15"`, `"table_fr_003.jpg"` (a file that exists but was not in this prompt), `"CSC-105"`, single letters `"N" "O" "E" "F" "K" "D"` (`arch-05-typed`) |

So "half of all answers cite nothing" (28 rows in `product_findings`, 32 by my count of
non-abstain rows) decomposes as: **a 3B model that cannot copy a 120-character absolute path
verbatim out of a `--- File N: <path> ---` header, and instead names the ordinal or something
printed on the image.** Two of the run's better answers are casualties — `phone-05-full` (a
`correct`, all seven exercises listed) and `viz-10-full` (a `correct`) both ship with no
sources. Five rows (`viz-04-full`, `viz-10-typed`, `study-06-full`, `rcpt-05-full`,
`phone-06-typed`) even carry `[1]`/`[2]` markers in prose with an empty citation list, so the UI
would render dangling references.

**Fix direction:** accept an ordinal in `sources_used` and resolve it against the prompt's file
list. That single change recovers 24 tokens across ~12 rows at zero risk (the ordinal is
unambiguous), and it is a strictly larger win than anything in the answer model.

### 5c. Citation lists *are* largely mechanical

Of the 35 answers that cited anything, **23 cite every file in their prompt** (21 of 2-of-2, 2
of 1-of-1). Only 12 are selective, and those pick a gold file 7 times out of 12 — better than
the 50% chance baseline, but on n=12 that is nothing. Mean citation precision among rows that
cited at all is 0.557, i.e. almost exactly the 0.5 you get from "cite both files when one of two
is gold". **Citation precision on this run is measuring `top_k`, not model judgement.** The
pooled 0.1875 in `metrics.json` is that 0.557 diluted by the 32 rows whose citations were
silently dropped by 5b — it is not a claim about the model's selectivity.

---

## 6. Where the judge and the deterministic matcher disagree (13 cases)

My adjudication. I opened `chart_037.jpg`, `screen_24243.jpg`, `chart_036.jpg`, `doc_357.jpg`,
`arxiv_004.png` and `info_021.jpg` to settle the load-bearing ones.

**I side with the judge on 11 of 13, and with the deterministic matcher on 2.**

| qa_id | det | judge | my call | why |
|---|---|---|---|---|
| `nf-07-full` | false_answer | correct_abstain | **judge** — unambiguous | The answer is "No". A prose decline on a `not_found` probe is a correct decline. This is a plain rule bug: `deterministic_verdict` runs `prose_abstain()` and then only consults it on the answerable branch. `prose_abstain` also fails to match a bare "No". Fix the rule, not the row. |
| `viz-06-full` | partial | correct | **judge** | `info_024.jpg` prints "1.7 MILLION" and "1 in 10 adults" as one figure and the gold prose itself joins them with "or". The `key_facts` entry should accept either. |
| `viz-10-full` | partial | correct | **judge** | "the prefix 'ob' indicates the blade is widest near the apex" is the substance of "obcordate". Substring matching on a morpheme is not a test of understanding. |
| `viz-09-typed` | wrong | partial | **judge** | Direction (tourism >> diabetes) is right and contradicts nothing; 0/2 reflects that both key facts are dollar figures the answer omitted. Partial is the right floor for a correct unquantified comparison. |
| `study-07-typed` | wrong | partial | **judge** | I opened `arxiv_004.png`: pink Attribute SBM is above teal Regular SBM from Pin/Pout ~1 to ~4. "Attribute SBM wins" is the correct answer to the typed question "which one wins". 0/5 is purely because every `key_facts` entry is a long scene-description sentence. |
| `study-07-full` | wrong | partial | **judge** | Same figure. Names both series, gets the direction and the saturation at NMI ~1 right; only "across all Pin/Pout" is loose (curves coincide at ~0.3 and ~5). |
| `phone-03-full` | wrong | partial | **judge**, weakly | "Biltz" vs printed "Blitz Weinhard" is a transposition of the right brand. I did not open `1007129816.jpg`, so I take the judge's file read here; the call is sound on the transposition argument alone. |
| `phone-10-typed` | wrong | partial | **judge** | "KayC" is the brand; the question asked for brand *and* slogan and got half. Partial is definitionally right. |
| `phone-10-full` | wrong | partial | **judge** | Brand plus "Delicious Root Beer" strapline; missing only "FIRST for THIRST". |
| `arch-05-typed` | partial | wrong | **judge, but for a different reason** | I opened `doc_357.jpg`. The judge says "35 milligrams" contradicts the leaflet's 660 mg — it does not; the leaflet independently says Coca-Cola USA products have "less than 35 milligrams". The actual defect is **subject substitution**: the question asks tomato juice vs diet Coke, the answer compares Coca-Cola vs diet Coke and drops the 660 mg entirely. It answers a different question, so `wrong` stands. |
| `viz-05-typed` | partial | wrong | **judge** | I opened `chart_036.jpg`: it contains Egypt, Tunisia, Madagascar, Mozambique — no Mauritania, no Fiji. A set-intersection question answered with a 3-element set that is 2/3 false is wrong as a set, even though "Madagascar" is inside it. |
| `viz-04-full` | partial | wrong | **deterministic direction (partial), but for the opposite reason** | I opened `chart_037.jpg`. The judge is right that 29% is the center-right cell and 20% is correct — but the answer *also* correctly states 7% for 1979, and that is an independently true, correctly attributed fact. One right fact and one wrong fact = `partial` by the rubric's own definition. **Separately, the deterministic 3/4 is bogus**: two of the three "matched" facts are the bare tokens `1979` and `2014`, which the question itself supplies. Both scores are wrong for different reasons; the verdict should be `partial` and `1979`/`2014` should be deleted from `key_facts`. |
| `phone-08-full` | partial | wrong | **deterministic (partial)** | I opened `screen_24243.jpg`. "priority (Group A) boarding" is verbatim correct and is half of what the question asked; "0 trips" is invented. One right fact, one wrong fact = `partial`. |

**The pattern behind the disagreements.** The judge applies a "a contradicted number poisons
the answer" rule to four rows. Two of those four (`arch-05-typed`, `viz-05-typed`) are genuine —
the matched token is *re-attributed* to the wrong subject, so the fact is not actually asserted.
The other two (`viz-04-full`, `phone-08-full`) are ordinary partials: the matched fact is
correctly asserted about the right subject and a *different* fact is wrong. Applying the poison
rule to those two would, if applied consistently across the run, collapse most of the 17 partials
into `wrong` — e.g. `arch-09-full`'s two correct totals with a wrong "which was larger"
conclusion, or `rcpt-04-*`. It is not applied consistently, so it should be narrowed to
re-attribution.

**Matcher-precision takeaway, sharpened.** Both directions of error have one root: `key_facts`
entries that are not atomic assertions.
- Tokens the *question* already contains (`1979`, `2014`) match for free -> false `partial`.
- Tokens that can be re-attributed inside a sentence (`35 milligrams`, `Group A`) match without
  the claim being made -> false `partial`.
- Whole scene-description sentences ("y axis is NMI, x axis is Pin/Pout"; "one blue and one
  green highlighted bar per column, stepping down per fold") can never substring-match -> forced
  `wrong`, which is most of the study tier's 0/N scores.

---

## 7. Verdict-independent findings (corrections and additions to the earlier reports)

1. **`not_found_topic: "a landlord's emergency phone number"` is NOT a fixture leak or a stale
   session value.** It is copied verbatim out of Magpie's own system prompt, which reads:
   *"put a short noun phrase naming what was asked about in not_found_topic (e.g. 'a landlord's
   emergency phone number', 'the chemistry final exam time', 'who chairs the math department')."*
   Twelve rows echo the first example — and 11 of those 12 have `not_found = false`, so the model
   is filling the field with the example whenever it does not bother to write one. JUDGE-REPORT's
   "whatever populates it is falling back to a fixture" is incorrect. Fix: stop putting a
   quotable example in the field description, or clear `not_found_topic` when `not_found` is
   false.

2. **The system prompt is regurgitable as an *answer*, not just as a field value.**
   `arch-03-typed`'s (suppressed) answer was `"CSC-105 has 4 credit hours and is offered every
   fall"` — verbatim the citation-format example. Same root cause as (1): concrete examples in
   the prompt become output when the model has nothing.

3. **`top_k` is not held at 2 for every question, confirmed.** 104 rows retrieved 2 candidates,
   6 retrieved 1, and **10 retrieved 12** (`arch-06-full`, `study-03-full`, `rcpt-01-full`,
   `rcpt-08-typed`, `rcpt-08-full`, `phone-05-typed`, `phone-05-full`, `phone-07-typed`,
   `phone-11-full`, `nf-06-full`). Nine of those reached the generator with 3-12 files and 5-12
   images. Seven of the ten ended in an abstain. This is the LIST_ALL widener firing on the raw
   question, as documented in `run.json`'s `rewrite` note — expected behaviour, but it does
   mean the "one knob per comparison" guarantee is weaker than the config claims, and it is the
   confounder behind the image-count effect in section 2.

4. **Retrieval scores carry no information.** Every score in the run is a reciprocal-rank value:
   0.016393 = 1/61, 0.016129 = 1/62, down to 0.013889 = 1/72. With rerank off there is no
   quality signal to threshold on, which is exactly why `solo_gate_structurally_off` is true.
   Any future analysis that treats these as confidences is reading rank back to itself.

5. **`phone-03-typed` / `phone-09-full`'s shared "ORDER, TIP WELL, WALK AWAY" is `info_021.jpg`,
   a retrieved neighbour on both rows** — not an unexplained cross-photo bleed (section 1,
   cluster 3).

6. **Latency does not predict quality, and the guard is not the slow path.** Median total
   latency by verdict: correct 12.1 s, wrong 14.2 s, false_abstain 13.4 s, partial 13.9 s,
   correct_abstain 25.4 s. Guard-fired rows are *faster* than the rest (12.7 s vs 14.6 s median).
   The four slowest rows are all 12-candidate rows.

---

## 8. What to change, in order of measured payoff

1. **Make the guard image-aware** (`src/answer.py`, the fix the docstring already flags as
   separate). On this corpus it converts 31 items, of which 22 were partly or fully right.
   Simplest correct behaviour: skip the numeral guard entirely when a file's contribution to the
   prompt is an image block, since there is no text to check against and "absent from the text"
   carries zero evidence. Expected effect on this dataset: false_abstain 0.433 -> 0.135,
   correct 0.038 -> 0.077, partial 0.163 -> 0.337, wrong 0.365 -> 0.452. That last number is the
   honest cost: 9 fabrications become visible instead of silent, and the citations are what let
   the user check them. If a smaller step is wanted, raising `MIN_INTERESTING` above 2100 to
   exclude years recovers `study-01-typed`, `study-01-full`, `viz-04-typed` at no risk.
2. **Accept ordinals in `sources_used`.** Recovers ~12 rows' citations including two of the six
   `correct` answers, at no accuracy risk.
3. **Raise `top_k` from 2 for this corpus, or dedupe the corpus.** `diagram_003`/`diagram_011`
   are the same image, and `notes_handwritten/` is one document in 20 near-identical pages;
   with k=2 the distractor slot is often a duplicate of the gold or its sibling page.
4. **Golden-set repairs before the silver->gold review** (these change the measured score without
   changing the product): remove `1979`/`2014` from `viz-04`'s `key_facts`; accept "1 in 10
   adults" for `viz-06`'s "1.7 million"; drop the timing sponsor from `phone-06` and the invoice
   number from `arch-04` (both over-specify beyond the question asked); split `study-06`/
   `study-07`'s scene-description sentences into atomic assertions or mark them judge-only.
5. **Fix `deterministic_verdict` for prose declines on `not_found` items** (`nf-07-full`), and
   add "no"/"none"/"nothing" to `prose_abstain`.

---

### Appendix — how the numbers were produced

- Guard/contract notes: block-parsed from `raw/worker_answer.log` on the `[eval] qa_id=X begin/end`
  markers; 120/120 blocks recovered.
- Raw pre-guard model output, prompt file order, per-prompt image count and inter-header text:
  `raw/appdata/logs/llm-2026-09-06T09-03-12Z.log` (120 request/response pairs), joined to
  `answers_enriched.json` on the `Current question:` line; 0 unmatched, 1 row
  (`viz-10-typed`) had non-JSON content and is excluded from raw-answer statistics only.
- Guard replication: the shipped `src.grounding.looks_fabricated` re-run on each row's raw answer
  against that row's own prompt text.
- Counterfactual verdicts: the shipped `eval_harness.harness.enrich.fact_in_text` and the
  `deterministic_verdict` rules re-applied to the suppressed texts.
- Images opened for independent adjudication: `charts/chart_037.jpg`, `charts/chart_036.jpg`,
  `screenshots/screen_24243.jpg`, `documents/doc_357.jpg`, `figures/arxiv_004.png`,
  `infographics/info_021.jpg`.
- Contrast run cited for the guard-count stability only:
  `eval_harness/runs/20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite/`.
