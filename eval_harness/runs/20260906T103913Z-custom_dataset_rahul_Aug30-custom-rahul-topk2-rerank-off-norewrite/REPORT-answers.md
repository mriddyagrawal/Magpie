# ANSWERS report — 20260906T103913Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

> SILVER golden set (0/120 human-verified). Every rate below is provisional.
> This report explains **why** answers succeeded or failed and **what caused each of the 58 flips**
> against the baseline. It is not a rescoring of the run; where I disagree with the judge, the
> deterministic matcher, or the brief I say so and give the reason.

Subject: backend `4ce90a8` (branch `prompt-image-order`).
Baseline: `20260906T090247Z-…`, backend `92f9ba9`.
Identical golden_sha `0ebcdcbcdf109adb`, mounted index `66974090bdcd62e6`, judge `claude-opus-5`,
rubric `47e93a279e70cef9`, provenance fingerprint `2bd85ac1c6a9fd99`. **Only the code axis differs.**

Config: `top_k=2`, rerank OFF, rewrite OFF, temperature 0, `local_n_ctx=16384`,
LFM2.5-VL-3B Q6_K local, ColQwen2.5 visual retrieval, `MAGPIE_GROUNDING_GUARD=1`,
`MAGPIE_STRICT_GROUNDING=1`. 545-file all-visual corpus, 120 golden items in 60 typed/full pairs
(104 answerable, 16 `not_found` probes).

---

## 0. The one-paragraph answer

**The prompt change worked, and the grounding guard ate most of the win.** Putting each image
inline under its own `--- File N ---` header (03ba954/14cd9c9) fixed the baseline's single largest
content failure — the model reading its answer out of the *wrong* picture — and dropping the
duplicate top copy of the question (dab1867/4ce90a8) eliminated query-echo answers outright,
**5 → 0**. Judged correct rose 6 → 19 and false answers on the absence probes fell 7 → 2. But the
numeral guard in `src/answer.py:_apply_grounding_guard`, which on an all-image corpus reduces to
*"if the answer contains any integer >= 100, return not-found"*, now accounts for **33 of the 36
false abstentions (92%, up from 31 of 45 = 69%)** — and because the new prompt makes the model
actually read printed numbers, **the answers it destroys are now three times more likely to be
fully correct: 12 correct / 13 partial / 8 wrong, against the baseline's 4 / 18 / 9.** Re-scored
with the guard disabled, this run is `correct 0.269, partial 0.433, wrong 0.269, false_abstain
0.029` versus the baseline's guard-off `0.077 / 0.337 / 0.452 / 0.135`. That is a 3.5x improvement
in strict correctness, and the shipped headline shows less than half of it. On attribution: all 58
flips are causally prompt-driven — the judge-noise channel (byte-identical text) is empty by
construction at 0/58, and the temperature-0 nondeterminism channel is empty too, because the user
turn was restructured on **120/120** rows, so there is no row where the model received an unchanged
input. **48 flips are mechanistically explained by change (a) or (b); 10 are incidental re-rolls I
will not claim a mechanism for; 0 are noise.**

---

## 1. Failure clusters in THIS run

Sizes over the 104 answerable items. Judge verdicts are the authority.

| verdict | n | share of answerable |
|---|---:|---:|
| correct | 19 | 18.3% |
| partial | 28 | 26.9% |
| wrong | 21 | 20.2% |
| false_abstain | 36 | 34.6% |

### Cluster 1 — Grounding-guard numeral suppression (33 items; 92% of all false abstentions)

**This is now almost the entire silence bucket, and it is the run's dominant failure.**

I block-parsed `raw/worker_answer.log` on the `[eval] qa_id=X begin/end` markers (120/120 blocks
recovered) and counted 33 `note: every figure in the answer is absent from the files read` and 17
`note: not_found=true but answer/sources_used were non-empty`. The 50 `not_found` rows in
`answers_enriched.json` partition **33 guard + 17 model-set, zero overlap, zero unexplained**.
Of the 17 model-set, 14 are the correct declines on the absence probes and **only 3 are false
abstentions** (`study-08-typed`, `study-08-full`, `study-10-full`).

I replicated the shipped predicate exactly: re-running `src.grounding.looks_fabricated` on each
row's own raw model output against that row's own inter-header prompt text gives **TP 33, FP 0,
FN 0, TN 87** for this run (baseline: TP 31, FP 1, FN 0, TN 88; the single FP is `viz-07-full`,
where a malformed decode set the flag before the guard could run).

**The guard's input did not change.** The support-text distribution is identical across the two
runs — **71 prompts with zero characters between the file headers, 40 with only the
`Content type: pdf (scanned / image-only — N page(s) as images)` banner, 9 with a real text layer.**
Change (a) added `[File N, image k of n]` captions to 40 prompts, but every digit in those captions
is below `MIN_INTERESTING = 100`, so the predicate is untouched. **The fire count moved 31 -> 33
purely because the answer text changed.**

**What is being destroyed, and it is much worse than in the baseline.** Re-scoring the 33
suppressed raw texts with the harness's own `eval_harness.harness.enrich.fact_in_text` against
their own `key_facts`:

| counterfactual | this run | baseline | examples from this run |
|---|---:|---:|---|
| correct | **12** | 4 | `arch-02-*` "4,58" (the gold EPS figure, both phrasings); `arch-03-*` "849"; `arch-05-*` a near-verbatim transcription of the leaflet — *"a six-fluid ounce serving of tomato juice processed with added salt has 660 milligrams of sodium, while the same size serving of diet Coke has 35 milligrams or less"*, 2/2 facts; `arch-07-*` 4/4 both phrasings; `arch-09-full` "216.00 / 318.40"; `rcpt-06-typed` 4/4; `viz-07-full` "7,298 in 1806 to 7,099 in 2009", 4/4; `arch-01-full` "$2,496,000" |
| partial | 13 | 18 | `viz-04-full` 3/4; `rcpt-03-full` 3/4; `study-03-full` 3/5; `phone-04-full` 2/3 |
| wrong | 8 | 9 | `arch-06-*` "1256.4" (gold 1506.0); `rcpt-06-full`; `study-06-typed` "CSC-105" |

Whole-run counterfactual with the guard off, deterministic matcher, n = 104 answerable:

| | correct | partial | wrong | false_abstain |
|---|---:|---:|---:|---:|
| this run, as shipped | 0.154 | 0.308 | 0.192 | **0.346** |
| this run, guard OFF | **0.269** | **0.433** | 0.269 | **0.029** |
| baseline, as shipped | 0.038 | 0.163 | 0.365 | 0.433 |
| baseline, guard OFF | 0.077 | 0.337 | 0.452 | 0.135 |

The like-for-like comparison of the two code states is the guard-off row: **correct 0.077 -> 0.269,
wrong 0.452 -> 0.269.** The shipped headline (0.038 -> 0.154) understates the change by more than
half, because the guard's tax grew with the improvement it was taxing.

**Where the guard bites is exactly where the gold answer is a printed number.** By category, the
two tiers that are wiped out are precisely the numeric ones: `tables_fr` **6 false_abstain of 6,
all 6 guard**; `receipts_phone` **9 false_abstain of 10, all 9 guard**; `scans_multipage` 4 of 8,
all 4 guard; `documents` 4 of 6, all 4 guard. Meanwhile `screenshots` (5 correct / 3 partial, 0
guard), `diagrams` (3 correct / 1 partial, 0 guard) and `receipts_degraded` (0 guard) are
untouched. This reproduces the baseline's discriminator finding — *"does the gold answer require
reading a printed multi-digit number"* — with the effect now concentrated harder, because the
model's willingness to emit the number went up.

**A real bug in the predicate, new this report.** `src/grounding.py:numerals` tokenises with
`_NUMERAL = r"\d[\d,]*(?:\.\d+)?"`. The comma is *inside* the character class, so an integer
followed by a comma is captured **with the comma attached**; `float("2014,")` then raises and the
`except ValueError: continue` silently discards it. Verified directly:

```
numerals("849, attendance")           -> []          # comma swallowed, token dropped
numerals("attendance 849")            -> ['849']
numerals("In 2014, 29% ...")          -> []
numerals("in 2014 compared to 1979")  -> ['2014', '1979']
```

Decimals are safe (`"316.00,"` tokenises cleanly) — only bare integers are affected. Across the two
runs this punctuation accident single-handedly decided three rows: it exempted `viz-04-full` and
`arch-08-full` in the baseline, and `study-01-full` in this run. `study-01-full` is the pure case:
both runs' answers are correct reads of the C++ notes, the baseline's `"C++; 1979; Bell Labs"` used
semicolons so `1979` was caught and the guard fired, this run's `"Bjarne Stroustrup, 1979, Bell
Labs."` used commas so it was not. **A flip from `false_abstain` to `partial` decided by
punctuation.** Whether the guard fires currently depends on English comma placement, which is not a
property anyone intended it to have.

### Cluster 2 — Right file, wrong cell / wrong series (10 of the 21 wrong)

This is now the largest *content* failure, and it is the genuine model-capability ceiling. These
rows read the correct image and landed on a neighbouring value.

- `arch-01-typed` — "73". `doc_10877.jpg` labels the 1960 local-health-department bar
  **$2,496,000**; 73 is the circled percent-of-total marker printed *inside* that bar. Note this row
  moved *up* the ladder from `false_abstain`: in the baseline the model declined outright, here it
  reads the right bar and picks the wrong glyph from inside it.
- `viz-04-typed` — "7%" for a 2014 question; 7% is the 1979 cell of the same column of
  `chart_037.jpg` (2014 is 20%).
- `viz-08-typed` — "40%"; `info_020.jpg` prints "over 90% own a smartphone" under Myth 5, and 40%
  is the volunteering figure under Myth 1 at the top of the same infographic.
- `viz-09-typed` / `viz-09-full` — "$9 billion" for the **$98 BILLION** printed in the TOTAL box of
  `info_013.jpg`. A digit-dropping misread, not a neighbouring cell.
- `rcpt-05-full` — "15.25 (Total Sales)"; on `bad_receipt_014.jpg` 15.25 is the amount column for
  the Delicia Chocolate line, and the total is 32.70.
- `study-05-typed`, `study-06-full`, `study-09-full`, `study-11-full` — figure descriptions that get
  the figure right and the reading wrong.

### Cluster 3 — Multi-file synthesis starved by top-k = 2 (18 items, 0 correct)

All 18 `multi_file: true` items scored partial (4), wrong (8) or false_abstain (6) — none correct,
in either run. The failure is structural, not prompt-related: `rcpt-08` needs three Mr D.I.Y.
receipts and got one (`33.90` is `bad_receipt_002.jpg`'s real total, offered as the RM 101.90
aggregate); `study-10` needs `CseGyan-Cpp-Notes-17/18/19` and got 14/15. Two slots cannot hold three
documents. The baseline's 10 rows that retrieved **12** candidates via the LIST_ALL widener are
byte-identical here (`arch-06-full`, `nf-06-full`, `phone-05-full`, `phone-05-typed`,
`phone-07-typed`, `phone-11-full`, `rcpt-01-full`, `rcpt-08-full`, `rcpt-08-typed`,
`study-03-full`), and so is the images-per-prompt distribution (85 rows at 2 images, tail out to 12,
identical counts in both runs).

### Cluster 4 — Answers from the wrong file (4 items, down from ~9)

`viz-07-typed` ("Reims (51)" from `table_fr_017.jpg` while the gold `info_001.jpg` sat at rank 1),
`rcpt-05-typed` ("Hallmark", gold never retrieved), `rcpt-07-typed` / `rcpt-07-full` (gold
`receipt_040.jpg` never retrieved). Only `viz-07-typed` is a genuine mis-binding with the gold in
the prompt; the other three are retrieval misses. **The baseline's "Cluster 3 — neighbour-document
bleed (9 wrong)" has largely collapsed** — see section 2.

### Cluster 5 — Degenerate generation (4 items)

`rcpt-07-typed` emits `[{`; `study-09-typed` emits `File 2` while citing the right figure;
`study-10-typed` dumps a raw page transcript; and `phone-07-full` names the four gold sponsors and
then repeats "Bud Light" for **7,467 characters**. All four are answer-formatting failures, with the
right file open in two of them.

### Cluster 6 — Model-initiated literalist abstention has almost vanished (3 items, from 14)

Only three false abstentions are the model's own decision, and two of them are arguably the *best
available* behaviour: `study-08-full` says "Not enough information provided in the image to
determine the percentage or the largest method", and `study-10-full` says *"CseGyan-Cpp-Notes-15
and CseGyan-Cpp-Notes-14 discuss assignment operators, conditional operators, and logical operators
but do not address type casting"* — a **correct** description of what top-k = 2 actually handed it.
The baseline's title-literalism failures (`viz-11-typed`'s *"the files contain an Antarctic food web
diagram but do not include a specific diagram titled 'antarctic food web'"*) are gone.

---

## 2. The 58 flips, attributed

### 2.1 Why the noise channels are empty

The owner's flip-noise floor came from a paired run at the same config with a different backend sha:
10 flips / 120, decomposed as 3 judge noise (byte-identical answer text, different verdict), 2
temperature-0 nondeterminism, 5 code axis. Neither noise channel can operate here:

1. **Judge noise requires byte-identical answer text. 0 of 58 flips qualify** — confirmed against
   `answers_enriched.json`. The mechanism is empty by construction.
2. **Temperature-0 nondeterminism requires an unchanged prompt.** The user turn was restructured on
   **120/120** rows. The baseline sends a single text string with *empty* file headers and images
   appended out-of-band via the legacy `images=` kwarg; this run sends typed content parts with each
   image inline. There is no row in this comparison where the model received the same input, so
   there is no row where the sampler could have re-rolled on its own.
3. **Retrieval is not a third channel.** 118/120 rows are byte-identical. The two movers,
   `viz-11-typed` and `viz-11-full`, differ *only* by a rank swap between `diagram_006.jpg` and
   `diagram_011.jpg` — two byte-duplicate copies of the same Antarctic food-web figure at identical
   scores. The same two pictures reach the prompt either way, so even those two flips cannot be
   retrieval-caused in any content sense.

Therefore every flip is causally downstream of the prompt change. That is not the same as saying
every flip is *explained* by it, and I separate the two below.

A caveat worth stating plainly: only **7** of the 41 byte-identical rows have identical *non-empty*
text (`arch-04-typed` "55.25", `study-02-typed` "C++ features", `study-07-typed` "Attribute SBM
wins", `rcpt-05-typed` "Hallmark", `phone-01-full` "Champaign, IL", `phone-03-full` "Biltz",
`phone-06-full` "Laganside 10K"). The other 34 are identical because both runs are silent. The
"41/120 unchanged" figure mostly measures shared abstention, not shared answers.

### 2.2 The dominant mechanism: change (a) rebinds content to files

The baseline report's Cluster 3 — *"the answer comes from the rank-2 file"* — is the cluster this
change was aimed at, and it is the cluster that moved. Of the 8 rows the baseline named:

| qa_id | baseline answer (source) | this run | verdict |
|---|---|---|---|
| `phone-01-typed` | "Scoutdoors" <- `screen_24626.jpg` | **"Champaign, IL"** <- gold | wrong -> **correct** |
| `phone-02-typed` | "palm" <- `scene_52b557c0cff76f70.jpg` | **"Intel NUC NUC5i7RYH"** | wrong -> **correct** |
| `phone-02-full` | "palm" <- same | **"NUC5i7RYH"** | wrong -> **correct** |
| `phone-03-typed` | "order, tip well, walk away" <- `info_021.jpg` | **"Biltz"** <- the hat photo | wrong -> partial |
| `phone-09-full` | "ORDER, TIP WELL, WALK AWAY." <- `info_021.jpg` | **"Dos Equis"** <- gold | wrong -> **correct** |
| `viz-01-full` | "Denmark, 0.81" <- `chart_030.jpg` | **"Cocoa, 18.81"** <- `chart_001.jpg` | wrong -> **correct** |
| `study-06-typed` | mag/redshift distributions <- `arxiv_018.png` | "CSC-105" (system-prompt echo) | wrong -> false_abstain |
| `study-09-full` | physics-neighbour bleed into an attention figure | convolutional-layer description | wrong -> wrong |

**6 of 8 fixed, 2 not.** Three more rows fit the same shape and also flipped: `phone-05-typed`
(turkey-call names from the wrong screenshot -> all seven exercises, in order, from
`screen_24509.jpg`), `viz-03-typed` ("Tweet #2" from an unrelated file -> "Amused"), and
`rcpt-02-full` ("Two ChicMcMuffins and Gojek Chicken; Total 379,500", where 379,500 belongs to an
Indonesian receipt, -> a complete correct itemisation of `bad_receipt_009.jpg` with the 26.60 total).

The mechanism is exactly what 03ba954/14cd9c9 predicts. Compare the two prompts for `viz-01-typed`,
verbatim from the llm logs:

```
BASELINE (single text string; images appended out-of-band via images=):
  Current date and time: Sunday, 2026-09-06 05:03 EDT
  Current question: food commodity price index chart cheapest one
  Answer the current question from the files below. ...
  --- File 1: .../figures/arxiv_025.png ---
  --- File 2: .../charts/chart_001.jpg ---
  Now answer this question: food commodity price index chart cheapest one
```

```
THIS RUN (typed content parts):
  [text]  --- File 1: .../figures/arxiv_025.png ---
  [image] arxiv_025.png
  [text]  --- File 2: .../charts/chart_001.jpg ---
  [image] chart_001.jpg
  [text]  Answer the question below from the files above. ...
          Today: Sunday, 2026-09-06 06:39 EDT
          Now answer this question: food commodity price index chart cheapest one
```

In the baseline the model saw two file headers with **nothing under them** and then an unlabelled
pile of pictures. It had no way to know which picture was `chart_001.jpg`, so it answered from
whichever image dominated. That is a complete and sufficient explanation for "Denmark, 0.81",
"palm", "Scoutdoors" and the turkey calls, and it is why they all resolve at once.

### 2.3 The second mechanism: change (b) kills the query echo

The baseline opened every turn with `Current question: <Q>` and closed it with `Now answer this
question: <Q>`, with only empty headers in between. For a two-word typed query the model's entire
textual context was *the query, twice*. The most probable continuation for the `answer` field was a
copy of it, and that is what happened.

**Verbatim query-echo answers: 5 in the baseline (`arch-06-typed`, `nf-02-typed`, `nf-06-typed`,
`rcpt-02-typed`, `viz-06-typed`), 0 in this run.** The wider degenerate-echo cluster the baseline
counted at 9 wrong resolves like this:

| qa_id | baseline | this run |
|---|---|---|
| `viz-06-typed` | "diabetes australia infographic annual cost" (the query) | **"$6 BILLION"** -> partial |
| `rcpt-02-typed` | "McDonalds" (the question's subject) | four order lines -> partial |
| `study-02-full` | "C++ features" (a page heading) | **all eight OOP mind-map branches** -> correct |
| `study-04-typed` | "C++ Tutorials [1]" (a document title) | symbol + syntax line -> partial |
| `arch-06-typed` | "Fort Morgan Sugar Factory" (the subject) | "1256.4" — a number read off the scan |
| `arch-03-typed` | "CSC-105 has 4 credit hours…" (the **system prompt's own example**) | **"849"** — the gold value |
| `study-02-typed` | "C++ features" | unchanged, still "C++ features" |
| `study-10-typed` | "C++ Tutorials[1], C++ Tutorials[2]" | a raw page transcript |
| `viz-08-typed` | "7" | "40%" |

`arch-03-typed` is the sharpest single case: the baseline regurgitated the citation-format example
from Magpie's own system prompt, this run produced the gold figure — and the guard killed it, so the
row shows as `false_abstain` in both and never appears in the flip list.

The direction is not uniformly good: system-prompt regurgitation did not disappear, it moved.
`study-06-typed` now emits `CSC-105`, the same system-prompt example, where it previously emitted
wrong-file content.

### 2.4 Full attribution of all 58

`A` = image binding (change a). `B` = question de-duplication / echo removal (change b).
`C` = the flip is *realised* by the numeral guard, downstream of A or B changing the answer's
numerals. `D` = incidental — the answer changed in a way I cannot trace to (a) or (b); a chaotic
re-roll under a perturbed context. **All are prompt_assembly; none are noise.**

| # | qa_id | flip | call | evidence |
|---:|---|---|---|---|
| 1 | arch-01-typed | fa -> wrong | **A** | "not found" -> "73", the marker printed inside the gold bar of `doc_10877.jpg`. Now reads the image. |
| 2 | arch-02-typed | wrong -> fa | **A+C** | "Bouygues Telecom" -> **"4,58"**, the gold EPS. Guard fired on 458. |
| 3 | arch-05-typed | wrong -> fa | **A+C** | Subject-substituted sentence -> near-verbatim leaflet transcription incl. 660 mg (2/2 gold facts). Guard fired on 660. |
| 4 | arch-06-typed | wrong -> fa | **A+B+C** | Query-subject echo -> "1256.4" read off the scan (gold 1506.0). Guard fired. |
| 5 | arch-08-full | fa -> partial | **A** | "Hazard ratio 2Q2002, confidence interval not found" -> "1.11-6.31, 0.029", 2 gold facts. |
| 6 | arch-08-typed | fa -> partial | **A** | "Not found" -> "1.11-6.31, P=0.029". |
| 7 | arch-09-typed | fa -> partial | **C** | Guard-killed "318.40 vs 300.00" -> "Expense report total was bigger" — no numerals, so it survives. Same conclusion, fewer facts. |
| 8 | nf-02-typed | fa_ans -> ca | **B** | "wedding invitation" (query echo) -> "not found". |
| 9 | nf-03-typed | ca -> fa_ans | **A** (adverse) | "not_found" -> "R.J. Reynolds Tobacco Company Growers Questionnaire" — it now *sees* `scan_hzjg0224.pdf` and names it. |
| 10 | nf-04-full | fa_ans -> ca | **B** | "C++ Tutorials [1], C++ Tutorials [2]" (title echo) -> "not found". |
| 11 | nf-04-typed | fa_ans -> ca | **B** | "CseGyan-Cpp-Notes-11.pdf" (filename echo) -> "not found". |
| 12 | nf-06-typed | fa_ans -> ca | **B** | "training loss curve" (query echo) -> "not found". |
| 13 | nf-07-typed | fa_ans -> ca | **A** | "Australia's Coverage Target is 95%", content lifted off an unbound distractor image -> "not found". |
| 14 | nf-08-typed | fa_ans -> ca | **B** | "Electric field" (heading echo) -> "Not found". |
| 15 | phone-01-typed | wrong -> correct | **A** (textbook) | `screen_24626.jpg` -> gold. Lands on "Champaign, IL", byte-identical to what `phone-01-full` already got right in both runs. |
| 16 | phone-02-full | wrong -> correct | **A** (textbook) | "palm" <- `scene_52b…` -> "NUC5i7RYH". |
| 17 | phone-02-typed | wrong -> correct | **A** (textbook) | Same, -> "Intel NUC NUC5i7RYH". |
| 18 | phone-03-typed | wrong -> partial | **A** (textbook) | `info_021.jpg` bar sign -> "Biltz" off `1007129816.jpg`. Converges on `phone-03-full`'s answer. |
| 19 | phone-05-typed | wrong -> correct | **A** (textbook) | Turkey-call list -> all seven exercises in order. |
| 20 | phone-08-full | wrong -> correct | **A** (read quality) | Same file both runs; "0 trips" -> "8 trips". Not a file swap — a read that landed once the image sat under its header. |
| 21 | phone-08-typed | wrong -> partial | **A** (read quality) | "0" -> "8 trips traveled". Same mechanism as #20. |
| 22 | phone-09-full | wrong -> correct | **A** (textbook) | `info_021.jpg` -> "Dos Equis" off the gold photo. |
| 23 | phone-09-typed | fa -> correct | **A** | Model-set decline -> "Dos Equis". |
| 24 | phone-10-full | partial -> correct | **D** | "KayC, Delicious Root Beer" -> "KayC, The FIRST for THIRST". Both straplines are on the same label; the new pick happens to be the gold key fact. No mechanism to claim. |
| 25 | rcpt-02-full | fa -> correct | **A** (textbook) | Guard-killed cross-receipt confabulation ("Total 379,500") -> the full correct `bad_receipt_009.jpg` itemisation. It also escapes the guard because the corrected figures (11.00, 5.60, 26.60) are all below 100. |
| 26 | rcpt-02-typed | wrong -> partial | **A+B** | "McDonalds" (subject echo) -> the four order lines. |
| 27 | rcpt-07-typed | fa -> wrong | **D** | Guard-killed text -> the degenerate string `[{`. Gold never retrieved in either run. A decode failure. |
| 28 | rcpt-08-full | fa -> wrong | **D** | "Not found" -> "46.91", matching no receipt and no combination. Fabricated arithmetic. |
| 29 | rcpt-08-typed | fa -> wrong | **A** | "Not found" -> "33.90", the *real* total of `bad_receipt_002.jpg`. It read a retrieved receipt correctly; top-k = 2 could not supply the other two. |
| 30 | rcpt-09-typed | wrong -> fa | **A+C** | Line-item echo -> "receipt_034: $243,000 vs receipt_032: $46,000". Guard fired. |
| 31 | study-01-full | fa -> partial | **D — punctuation** | Guard-killed `"C++; 1979; Bell Labs"` -> `"Bjarne Stroustrup, 1979, Bell Labs."`. Both correct reads; the flip is decided by the comma bug in `numerals()` (section 1). |
| 32 | study-02-full | wrong -> correct | **A+B** (textbook) | "C++ features" -> all eight branches of the `CseGyan-Cpp-Notes-3.pdf` mind map. |
| 33 | study-04-full | wrong -> partial | **A** | Reproduced Notes-14's relational/logical operator text (wrong page of the right document) -> the ternary example from Notes-15. |
| 34 | study-04-typed | wrong -> partial | **A+B** | "C++ Tutorials [1]" -> the `( ? : )` symbol and syntax shape. |
| 35 | study-05-full | wrong -> fa | **A+C** | Garbled OCR with "Unstable when 90 deg" -> **"Stable at 0 deg, Unstable at 180 deg, Maximum torque at 90 deg"**, which is the gold. Guard fired on 180. |
| 36 | study-06-typed | wrong -> fa | **D** | Wrong-file description -> `CSC-105`, the system prompt's own example. Guard fired on 105. Regurgitation moved rather than resolved. |
| 37 | study-07-full | partial -> wrong | **D** | "both plateauing at 1.00" -> "Regular SBM plateaus around 0.9". A new, specific, false claim. Prompt-caused, not prompt-explained. |
| 38 | study-08-full | wrong -> fa | **A** | Confabulation from slide 1 of the right deck -> an honest "Not enough information provided in the image". Behaviourally better; the ladder scores it worse. |
| 39 | study-10-full | wrong -> fa | **A** | Operator-page dump -> a *correct* statement of what was actually retrieved and why it cannot answer. Best available behaviour at top-k = 2; the ladder scores it worse. |
| 40 | study-11-full | fa -> wrong | **A+C** | Guard-killed "7,000,000 / 1,250,000" -> "15.5, 3 hours"; 15.5 is a real tablet figure from one deck, and the numbers now fall under 100 so the guard passes. |
| 41 | study-11-typed | fa -> wrong | **C+D** | Guard-killed "7,000,000" -> "32.5", which matches nothing. |
| 42 | viz-01-full | wrong -> correct | **A** (textbook) | "Denmark, 0.81" <- `chart_030.jpg` -> "Cocoa, 18.81" <- `chart_001.jpg`. |
| 43 | viz-01-typed | correct -> partial | **D** | "The cheapest commodity is Cocoa at 18.81" -> "Cocoa". Right file both times; the answer just got terser. |
| 44 | viz-02-full | wrong -> partial | **A** (read quality) | "Spain" (the third-highest bar) -> "South Korea" (the lowest). |
| 45 | viz-02-typed | wrong -> partial | **A** (textbook) | "Australia", which is not on `chart_010.jpg` at all -> "South Korea". |
| 46 | viz-03-full | fa -> partial | **B** | Baseline produced `"Amused 88% [1]"` *and* set `not_found`, with a corrupted `sources_used` — a malformed grammar-constrained decode under the degenerate two-copies-of-a-short-question context. This run decodes cleanly to "Amused, 88%". |
| 47 | viz-03-typed | wrong -> partial | **A** (textbook) | "Tweet #2" from an unrelated file -> "Amused" off `chart_005.jpg`. |
| 48 | viz-04-full | wrong -> fa | **A** (adverse) **+C** | Read degraded ("29% in 2014" -> "7% in 2014, 1% in 1979") *and* the guard fired, because the baseline wrote "In 2014," with a comma and this run wrote "in 2014 compared to". Both the content and the punctuation moved against it. |
| 49 | viz-04-typed | fa -> wrong | **C+A** | Guard-killed "42% in 1979" -> "7%", which survives (no numeral >= 100) but is the 1979 value for a 2014 question. |
| 50 | viz-05-full | fa -> wrong | **C+A** (adverse) | Guard-killed "Egypt 93.45% (2002), Tunisia 89.89% (2009)" -> an answer that survives the guard but actively *denies* Madagascar is in `chart_036.jpg`, where it sits at 58.09%. |
| 51 | viz-05-typed | wrong -> partial | **A** | "Mauritania, Fiji, Madagascar" (2 of 3 false) -> "Madagascar", the correct intersection. |
| 52 | viz-06-typed | wrong -> partial | **A+B** (textbook) | Verbatim query echo -> "$6 BILLION" off `info_024.jpg`. |
| 53 | viz-07-typed | fa -> wrong | **A** (adverse) | "not found" -> "Reims (51)" cited from `table_fr_017.jpg`, the rank-2 neighbour, while the gold `info_001.jpg` sat at rank 1. Inline binding did not help here; it bound to the wrong file. |
| 54 | viz-08-full | fa -> correct | **A+C** (textbook) | Guard-killed garbage ("7.0%, 1,250,000") -> "90%, 65%", both gold facts from the Myth-5 panel. |
| 55 | viz-09-full | partial -> wrong | **D** (judge boundary) | "$43.4 billion" (a real but re-attributed line on `info_013.jpg`) -> "$9 billion" (an invented truncation of $98 billion). Both answers are wrong about the same quantity; the judge distinguishes re-attribution from invention. Defensible, but this is the one flip where the two answers are of near-equal quality. |
| 56 | viz-09-typed | partial -> wrong | **D** | "tourism bigger" with no figures -> the same direction plus a fabricated "$9 billion". Adding a wrong number is a real degradation. |
| 57 | viz-11-full | partial -> correct | **A** | "leopard seal and penguins" -> all three seal labels (plus penguins). Retrieval swapped two byte-duplicate diagrams; the pictures in the prompt are the same. |
| 58 | viz-11-typed | fa -> correct | **A** | Title-literalism decline -> the full organism list including all three seals. |

### 2.5 The count

| attribution | n | share |
|---|---:|---:|
| **prompt_assembly — mechanistic** (A and/or B, with or without C) | **48** | 83% |
| — of which the guard (C) is what realises the verdict change | 15 | |
| **prompt_assembly — incidental** (D: chaotic re-roll, no mechanism claimed) | **10** | 17% |
| — `phone-10-full`, `rcpt-07-typed`, `rcpt-08-full`, `study-01-full`, `study-06-typed`, `study-07-full`, `study-11-typed`, `viz-01-typed`, `viz-09-full`, `viz-09-typed` | | |
| **noise** (judge noise or temperature-0 nondeterminism) | **0** | 0% |

**Final answer: 58 prompt_assembly, 0 noise.** Within prompt_assembly, 48 mechanistic and 10
incidental.

**Confidence.** *High* that the noise count is 0: it follows from two structural facts, not from
judgement — the judge-noise channel needs byte-identical text (0/58) and the nondeterminism channel
needs an unchanged prompt (0/120). *High* on the 48/10 split for the clearly-traceable rows —
I screened every flip for semantic equivalence (same `key_facts` matched, both answers non-empty,
`difflib` similarity > 0.35) and only three rows qualified (`study-07-full`, `viz-05-typed`,
`viz-09-full`); inspecting each, `viz-05-typed` is a real improvement (dropping two false entries)
and `study-07-full` introduces a new false claim, leaving `viz-09-full` as the sole judge-boundary
case. *Moderate* on the boundary between "mechanistic" and "incidental": rows 20/21 (`phone-08-*`,
same file, better read) and 46 (`viz-03-full`, decode cleanliness) are the weakest mechanistic
calls, and rows 31, 43 and 55 are the strongest incidental ones. Moving all six would shift the
split to 42/16 and would not change any conclusion.

---

## 3. The 14 regressions

Nine of the fourteen are `wrong -> false_abstain`; three are `partial -> wrong`; one is
`correct -> partial`; one is `correct_abstain -> false_answer`.

### 3.1 Seven of the fourteen are the guard destroying a *better* answer

`arch-02-typed`, `arch-05-typed`, `arch-06-typed`, `rcpt-09-typed`, `study-05-full`,
`study-06-typed` and `viz-04-full` are all new guard fires. On five of them the underlying answer
**improved**:

- `arch-02-typed`: "Bouygues Telecom" -> **"4,58"**, the gold `benefice net courant par action` for
  2017. 1/1 facts.
- `arch-05-typed`: a sentence that mis-attributed diet Coke's 35 mg to Coca-Cola -> a near-verbatim
  transcription of the leaflet containing both gold facts. 2/2.
- `study-05-full`: unstable at 90 deg (contradicting the page) -> **stable 0 deg, unstable 180 deg,
  max torque 90 deg**, which is exactly what `electric-charge-and-field-9.pdf` marks.
- `arch-06-typed`: the query subject echoed back -> a real number read off the scan (1256.4, gold
  1506.0 — wrong, but an attempt).
- `rcpt-09-typed`: a line-item comparison -> two receipt totals with an explicit conclusion.

**Three answers that would have scored `correct` and one that would have scored `partial` were
converted to silence.** The prompt change did not make these rows worse; it made them numeric, and
numeric is what the guard deletes.

`viz-04-full` is the one guard regression where the content genuinely degraded too: the baseline's
"29% in 2014" was the adjacent centre-right cell, this run's "7% in 2014 compared to 1% in 1979"
gets both years wrong. And it was only exempt in the baseline because of the comma bug.
`study-06-typed` is the other genuine content regression: wrong-file content -> system-prompt
regurgitation.

### 3.2 Two are honest declines the ladder punishes (study-08-full, study-10-full)

Both are model-set. `study-08-full` replaced a confabulation ("biosensors 30%, MEMS and
microfluidics 40%" — figures from the deck's *first* slide, where the gold pie chart on the last
slide reads Biosensors 8% / LC/MS 38%) with "Not enough information provided in the image".
`study-10-full` replaced a page-dump with a correct account of what retrieval actually returned.
**Both moved from asserting something false to saying nothing false.** The ladder scores
`wrong (2) -> false_abstain (1)` as a regression; by any product standard these are improvements.
I would not count them against the change.

### 3.3 The study-* and viz-* content regressions — what the new prompt does worse

Four rows are genuine content losses with no guard involvement:

- **`viz-01-typed` (correct -> partial)** — the cleanest illustration of the new layout's one real
  cost. Baseline: "The cheapest commodity is Cocoa at 18.81". This run: **"Cocoa"**. Same file, same
  correct read, one word instead of seven. In the baseline the model saw the question twice with
  nothing but empty headers between and padded; here the question appears once, at the end of a long
  multimodal context, and the model answers it minimally. Median typed answer length fell from 16
  characters to 10.
- **`viz-09-typed` / `viz-09-full` (partial -> wrong)** — the baseline hedged ("tourism is bigger",
  no figures; or "$43.4 billion", a real line on the infographic, misassigned). This run commits to
  **"$9 billion"**, a digit-dropped read of the **$98 BILLION** in the TOTAL box. The new prompt
  makes the model *quantify*, and when the vision read is wrong, quantifying converts a survivable
  hedge into a contradiction. This is the same coin as 3.1: more numbers, better when the read is
  right, worse when it is not.
- **`study-07-full` (partial -> wrong)** — "both plateauing at the same NMI level of 1.00" (true) ->
  "Regular SBM plateaus around 0.9" (false). A gratuitous new specific claim about `arxiv_004.png`.

**The pattern across all the study-* and viz-* regressions is one thing: the new prompt makes the
model more assertive and more numeric.** That is a net win — it is what drove correct 6 -> 19 — but
it converts three failure modes that were previously scored leniently (silence, hedging,
unquantified direction) into failure modes that are scored strictly (a wrong number, a false
specific claim). Combined with the guard, which punishes assertiveness with a blanket veto on large
integers, the run pays for its own improvement twice.

### 3.4 The one absence-probe regression

`nf-03-typed` ("lease agreement") went `correct_abstain -> false_answer`: "not_found" ->
"R.J. Reynolds Tobacco Company Growers Questionnaire". That is `scan_hzjg0224.pdf`'s actual title,
read off the now-visible image. It is the direct adverse consequence of change (a): a model that can
finally see what a document *is* becomes more willing to offer it. Six other absence probes moved
the other way (section 5), so the trade is 6:1 in favour.

---

## 4. The citation collapse — a parsing loss, not honest uncertainty and not a real regression

Recorded: `cited 0.471 -> 0.279`, `citation_precision 0.188 -> 0.139`, `citation_recall 0.206 ->
0.107`, `zero_citation_answers 28 -> 49`, `hallucinated_citations 0.183 -> 0.077`.

### 4.1 The model did not stop citing

I parsed the raw `sources_used` out of every response in both llm logs (119/120 parse cleanly in
each; one row per run has non-JSON content).

| | baseline | this run |
|---|---:|---:|
| rows emitting a non-empty raw `sources_used` | **102 / 120** | **101 / 120** |
| total citation tokens | 203 | 147 |

**The model is still citing on the same number of rows.** What changed is the *shape* of the token:

| raw token shape | baseline | this run | survives the path filter? |
|---|---:|---:|---|
| bare `/Users/…/corpus/x.jpg` | **101** | **39** | yes |
| `File 2: /Users/…/x.jpg` | 22 | 28 | no — dropped |
| `file: /Users/…/x.jpg` | 3 | 8 | no — dropped |
| `--- File 1: /Users/…/x.jpg` | 8 | 1 | no — dropped |
| bare ordinal (`"1"`, `"file:2"`, `"File 2"`) | 42 | 43 | no — dropped |
| a string off the page, or JSON debris | 27 | 28 | no — dropped |

Bare paths — the only shape `src/answer.py`'s input-path filter accepts — collapsed **101 -> 39**,
while header-prefixed paths *rose* **33 -> 37**. The model is copying **more** of the header line,
not less. Change (a) turned each `--- File N: <path> ---` header into its own standalone content
part, immediately followed by an image; the header now reads as a single visual unit, and the model
copies the unit — label and all — instead of the substring inside it. `_normalize_path_for_match`
collapses whitespace and URL-decodes, but does not strip a `File 2: ` prefix, so those tokens are
logged as `warn: dropped hallucinated source paths` and discarded.

### 4.2 Recovering them

Applying two trivial normalisations to the raw tokens — strip a leading `(--- )?[Ff]ile ?\d*:?` and
resolve a bare ordinal against the prompt's own file list:

| | answered rows | currently cited | + strip header prefix | + resolve ordinal | zero-citation would be |
|---|---:|---:|---:|---:|---:|
| baseline | 67 | 35 | +10 | +9 | 32 -> **13** |
| this run | 70 | 20 | **+22** | **+17** | 50 -> **11** |

**With the header prefix stripped, this run carries *more* recoverable provenance than the baseline
— 59 of 70 answered rows (84%) versus 54 of 67 (81%) — and would have a *lower* zero-citation count,
11 against 13.** The measured collapse is entirely an artifact of the strict path filter meeting a
changed token shape. It is a parsing loss.

### 4.3 It is not honest uncertainty — the uncited answers are the *better* ones

If the model were declining to cite because it was unsure which file a fact came from, uncited
answers would be worse than cited ones. The opposite holds:

| | cited rows | correct+partial | uncited answered rows | correct+partial |
|---|---:|---:|---:|---:|
| baseline | 35 | 10 (29%) | 32 | 13 (41%) |
| this run | 20 | 12 (60%) | **50** | **35 (70%)** |

70% of this run's uncited answers are correct or partial. `viz-01-full` ("Cocoa, 18.81", correct),
`phone-01-typed` ("Champaign, IL", correct), `phone-02-full` ("NUC5i7RYH", correct),
`phone-09-full` ("Dos Equis", correct) and `viz-08-full` ("90%, 65%", correct) all ship with an
empty `magpie_cited` and a raw `sources_used` of `["file:2"]` or a `File N:`-prefixed path. The
model knows exactly which file it read. The harness throws the answer to that question away.

### 4.4 Why hallucinated citations fell at the same time

`hallucinated_citations` on this corpus means "cited a real, in-prompt, non-gold file" — the
baseline established that every cited path was in-prompt, so genuine hallucination is 0.000 in both
runs. The baseline's high figure was driven by a *mechanical* reflex: **21 of its 35 citing rows
cited every file in the prompt**, so with top-k = 2 and one gold, half of every such list was
non-gold by construction. In this run only **10 of 20** citing rows cite everything.

So the two metrics moved together for one reason: the reflex that produced them both — "copy both
header paths verbatim into `sources_used`" — is exactly the behaviour the new header formatting
broke. `cited` fell, `hallucinated_citations` fell, and `citation_precision` fell, all from the same
cause. **None of the three is measuring model judgement in either run.**

**Verdict: not a real regression, and not honest uncertainty. A one-line prefix strip in
`src/answer.py` recovers it, and would leave this run ahead of the baseline on citation coverage.**

---

## 5. Abstention behaviour on the 16 `not_found` probes

`false_answer 7 -> 2`, `correct_abstain 9 -> 14`. Seven rows flipped: six up, one down. **Six of the
seven are typed phrasings.**

| qa_id | baseline answer | this run | flip |
|---|---|---|---|
| `nf-02-typed` "wedding invitation" | **"wedding invitation"** — the query, echoed | "not found" | fa -> **ca** |
| `nf-04-typed` "python notes" | "CseGyan-Cpp-Notes-11.pdf" — a filename | "not found" | fa -> **ca** |
| `nf-04-full` "Pull up my Python notes…" | "C++ Tutorials [1], C++ Tutorials [2]" | "not found" | fa -> **ca** |
| `nf-06-typed` "training loss curve" | **"training loss curve"** — the query, echoed | "not found" | fa -> **ca** |
| `nf-07-typed` "covid vaccination certificate" | "Australia's Coverage Target is 95%" | "not found" | fa -> **ca** |
| `nf-08-typed` "chem notes" | "Electric field" — the physics notes' heading | "Not found" | fa -> **ca** |
| `nf-03-typed` "lease agreement" | "not_found" | "R.J. Reynolds Tobacco Company Growers Questionnaire" | ca -> **fa** |

**The mechanism is change (b), and it is unusually clean.** The baseline's user turn for
`nf-06-typed` was, in its entirety: a clock line, `Current question: training loss curve`, one line
of guidance, two file headers with nothing under them, and `Now answer this question: training loss
curve`. The only content-bearing tokens in the whole turn were the three words of the query, present
twice. A 3B model filling a required `answer` string against that context emits the string it can
see. Five such verbatim echoes existed in the baseline and **zero exist now**. Removing the
duplicate top copy and putting real image content between the headers and the question destroyed the
echo attractor.

Two of the six (`nf-04-*`, `nf-08-typed`) are the lexical-distractor traps the golden set was built
around — C++ notes returned for a Python request, physics notes for chemistry. Those did not need
the echo mechanism; they needed the model to look at the pictures and conclude they were not what
was asked for, which is change (a).

The single regression, `nf-03-typed`, is the price of (a): the model can now read
`scan_hzjg0224.pdf` and reports its actual title. `nf-08-full` remains a `false_answer` in both runs
(it answers "yes" to a chemistry-notes question), so the residual failure is one row per phrasing.

---

## 6. typed vs full

Deterministic strict-correct: typed **1/52 -> 5/52**, full **3/52 -> 11/52**. Judged: typed 1 -> 5,
full 5 -> 14.

| | typed (n=52 answerable) | full (n=52 answerable) |
|---|---|---|
| baseline judged | 1 correct / 8 partial / 22 wrong / 21 fa | 5 / 9 / 14 / 24 |
| this run judged | 5 / 18 / 13 / 16 | 14 / 10 / 8 / 20 |
| flips | 28 (21 up, 7 down) | 23 (17 up, 6 down) |
| dominant transition | **wrong -> partial (8)** | **wrong -> correct (5)** |
| guard fires | 13 -> 15 | 18 -> 18 |
| median raw answer | 2 words (unchanged) | 7 -> 5 words |

### Does the new layout help full more than typed?

**No — it helps both equally at the reading step, and only full converts the gain into full credit.**
Typed actually flipped *more* rows (28 vs 23) and improved on more (21 vs 17). But typed's mass lands
on `wrong -> partial` while full's lands on `wrong -> correct`.

The reason is a word budget, and the paired items prove it directly — same question, same file, same
retrieval, same corrected read, different verdict purely because of length:

| pair | typed answer | verdict | full answer | verdict |
|---|---|---|---|---|
| `viz-01` | "Cocoa" | partial | "Cocoa, 18.81" | **correct** |
| `viz-02` | "South Korea" | partial | "South Korea" | partial (both miss 72%) |
| `phone-08` | "8 trips traveled" | partial | "8 trips; priority (Group A) boarding as a rewards member" | **correct** |
| `phone-02` | "Intel NUC NUC5i7RYH" | **correct** | "NUC5i7RYH" | **correct** |

Change (a) fixed *which image the model looks at* — a file-binding effect that is entirely
phrasing-independent, and the typed column shows it working: `phone-01-typed`, `phone-02-typed`,
`phone-03-typed`, `phone-05-typed`, `viz-02-typed`, `viz-03-typed`, `viz-05-typed`, `viz-06-typed`
and `rcpt-02-typed` all moved off wrong-file or echo answers. But the median typed answer is still
**2 words in both runs**. A two-word answer can name the right thing (partial) and almost never
satisfies a multi-fact `key_facts` list (correct). The full phrasing writes enough words to carry
the second fact, so its corrected reads land as `correct`.

Change (b) is where full gave something back: its median answer fell from 7 words to 5, because the
question now appears once instead of twice and the model answers it more tersely. `viz-01-typed`'s
`correct -> partial` is that effect biting on the typed side. So the honest statement is: **(a)
helps both phrasings equally; (b) helps typed — by killing the echo — and very slightly hurts both
by making answers terser.** The `full > typed` gap on strict correctness is a verbosity artifact of
the golden set's multi-fact `key_facts`, not a difference in what the model read, and it is
unchanged in character from the baseline: 22 of 60 pairs disagree across phrasings in both runs.

On the absence probes the picture inverts — typed was the weak side (3/8 correct_abstain) and is now
level with full (7/8 each), because the echo mechanism that broke typed is precisely what (b)
removed.

---

## 7. Corrections and verdict-independent findings

1. **"Answer text got longer" is wrong — it got shorter.** The brief's `total 5,136 -> 11,566 chars,
   mean 77 -> 165` is produced by **one row**. `phone-07-full` degenerated into a **7,467-character**
   repetition of "Bud Light" (the baseline's version of the same row is 106 characters and also
   scored `correct`). Excluding that single row, total answer text fell **5,039 -> 4,099 (-19%)** and
   mean non-abstain length fell **76 -> 59**. Median raw answer length fell **25 -> 13** characters;
   median typed answer is 2 words in both runs. The correct characterisation is that this run's
   answers are **shorter, denser and more numeric** — which is precisely why the numeral guard's
   catch rate rose.

2. **"41/120 byte-identical" mostly measures shared silence.** 34 of the 41 are identical because
   both runs returned an empty string. Only 7 rows have identical non-empty answers.

3. **The `numerals()` trailing-comma bug** (section 1) — an integer followed by a comma is invisible
   to the guard. It decided three rows across the two runs and makes guard behaviour depend on
   punctuation. Separate from, and easier to fix than, the image-awareness problem.

4. **The `[File N, image k of n]` captions expose a silent per-file image truncation.** On
   `arch-03-typed` the banner reads `5 page(s) as images` for File 1 but the captions read
   `[File 1, image 1 of 3]…[3 of 3]` — three of five pages actually reached the model. Total images
   (7) matches the baseline exactly, so the truncation is pre-existing, not new; change (a) simply
   made it visible in the log for the first time. Worth confirming the budget is intentional.

5. **`not_found_topic` is still leaking the system prompt's own example.** The string
   `"a landlord's emergency phone number"` and other prompt debris still appear. The baseline report
   correctly identified this as the field description's quotable example being echoed, not a fixture
   leak; nothing in this change addressed it.

6. **System-prompt regurgitation as an *answer* survives.** `arch-03-typed` stopped emitting
   `"CSC-105 has 4 credit hours…"` (it now emits the gold "849"), but `study-06-typed` started.
   Concrete examples inside the system prompt remain reachable as output.

7. **Retrieval, image counts and the widener path are byte-stable.** 118/120 identical retrieval; the
   images-per-prompt histogram is identical (85 rows at 2 images, tail to 12); the same 10 rows fire
   the LIST_ALL widener in both runs. The one-knob guarantee holds on everything except that widener,
   which is common to both arms.

---

## 8. What to change, in order of measured payoff

1. **Make the numeral guard image-aware.** On this run it converts 33 answerable items, **25 of which
   are partly or fully right, 12 of them fully right**. Skipping the guard when a file's contribution
   to the prompt is an image block would move this run to `correct 0.269 / partial 0.433 / wrong
   0.269 / false_abstain 0.029`. This is now the single largest lever in the system by a wide margin,
   and the prompt change made it larger, not smaller.
2. **Fix `numerals()`'s trailing comma** (`rstrip(",.")` before the `float`, or move the comma out of
   the character class). Two lines. Removes a punctuation dependency from a correctness guard. If a
   smaller step than (1) is wanted, raising `MIN_INTERESTING` above 2100 to exclude years
   additionally recovers `study-01-typed`, `viz-04-full` and `viz-04-typed`.
3. **Strip a `(--- )?[Ff]ile ?\d*:?` prefix and resolve bare ordinals in `sources_used`.** Recovers
   **39 of this run's 50 zero-citation answers** at zero accuracy risk, and reverses the entire
   measured citation regression — leaving this run ahead of the baseline on citation coverage.
4. **Keep the prompt change.** Every measure that is not mediated by the guard or the path filter
   moved in its favour: query echoes 5 -> 0, wrong-file answers 9 -> 4, false answers on absence
   probes 7 -> 2, judged correct 6 -> 19, guard-off strict correct 0.077 -> 0.269.
5. **Raise `top_k` above 2 or dedupe the corpus.** Unchanged from the baseline's recommendation:
   0 of 18 multi-file items are correct in either run, `diagram_003`/`diagram_011` are the same
   image, and `notes_handwritten/` is one document in 20 near-identical pages.
6. **Consider a minimum-completeness nudge for terse queries.** `viz-01-typed`'s `correct -> partial`
   and the typed column's 18 partials are one-word answers to multi-fact questions. The reading is
   already right; only the writing is short.

---

### Appendix — how the numbers were produced

- **Guard / contract attribution**: block-parsed from `raw/worker_answer.log` on the
  `[eval] qa_id=X begin/end` markers; 120/120 blocks recovered in both runs. Guard notes 33 (this
  run) / 31 (baseline); contract-clear notes 17 / 22. Zero overlap, zero unexplained abstentions in
  either run.
- **Raw pre-guard model output, prompt structure, per-prompt image count, inter-header support
  text**: `raw/appdata/logs/llm-2026-09-06T10-39-33Z.log` (this run, the file named in
  `run.json:phases.answer.llm_log`) and `llm-2026-09-06T09-03-12Z.log` (baseline). 120 request /
  120 response pairs each. Joined to `answers_enriched.json` on the `Now answer this question:` line
  — **120/120 matched in both runs, 0 unmatched, 0 ambiguous** (no two golden items share a question
  string). The mounted index's `llm-2026-08-30T10-40-06Z.log` was not read.
- **Guard replication**: the shipped `src.grounding.looks_fabricated` re-run on each row's raw answer
  against that row's own inter-header prompt text. This run TP 33 / FP 0 / FN 0 / TN 87; baseline
  TP 31 / FP 1 / FN 0 / TN 88 (the FP is `viz-07-full`, where the model's own flag pre-empted the
  guard).
- **Counterfactual verdicts**: the shipped `eval_harness.harness.enrich.fact_in_text` re-applied to
  the suppressed texts against each item's own `key_facts` from
  `eval_harness/datasets/custom_dataset_rahul_Aug30/golden.json`.
- **Citation token shapes**: raw `sources_used` arrays parsed out of every logged response and
  classified against the `--- File N: <path> ---` headers extracted from that row's own prompt.
- **Flip ladder**: `false_answer 0 < false_abstain 1 < wrong 2 < partial 3 < correct / correct_abstain 4`.
  Reproduces the brief's 44 improvements / 14 regressions exactly.
- **Semantic-equivalence screen**: for each flip, `key_facts` matched by the old and new final
  answers, plus a `difflib.SequenceMatcher` ratio; candidates required equal fact counts, both
  answers non-empty, and similarity > 0.35. Three rows qualified; all three inspected individually
  in section 2.4.
- **Prompt excerpts** in section 2.2 are verbatim from the two llm logs for `viz-01-typed`.
- **No source file under `src/` was modified.** `src/answer.py` and `src/grounding.py` were read
  only, to establish the guard's exact predicate.
