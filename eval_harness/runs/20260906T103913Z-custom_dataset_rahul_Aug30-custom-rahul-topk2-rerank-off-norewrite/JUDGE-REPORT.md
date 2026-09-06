# Judge report — 20260906T103913Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

Of 120 answered questions, 19 are correct, 28 partial, 21 wrong, 36 false abstentions, 14 correct
abstentions and 2 false answers. The single dominant pattern is abstention on questions whose gold
source Magpie had already retrieved: of the 104 answerable questions, 36 (34.6%) were declined, and
in 34 of those 36 the gold file sat at rank 1 or rank 2 of the retrieval list — twice as many
questions were lost to "not found" as to any reading error. Where Magpie did answer, it usually
found the right file (only 4 answers came from the wrong document); its second failure mode is
reading the wrong cell of the right page, which produced 6 of the 21 wrong verdicts. Not-found
questions are handled well (14/16). I opened 18 source files to settle every case where the gold
and the answer disagreed, and overturned the deterministic verdict on 14 items.

## Scoreboard

| Verdict | Overall | typed | full |
|---|---|---|---|
| correct | 19 | 5 | 14 |
| partial | 28 | 18 | 10 |
| wrong | 21 | 13 | 8 |
| false_abstain | 36 | 16 | 20 |
| correct_abstain | 14 | 7 | 7 |
| false_answer | 2 | 1 | 1 |
| **n** | **120** | **60** | **60** |

Derived rates (answerable questions only, n = 104; the 16 `not_found` items are excluded):

| Metric | Overall | typed | full |
|---|---|---|---|
| correct | 18.3% (19/104) | 9.6% (5/52) | 26.9% (14/52) |
| correct + partial | 45.2% (47/104) | 44.2% (23/52) | 46.2% (24/52) |
| false_abstain | 34.6% (36/104) | 30.8% (16/52) | 38.5% (20/52) |
| not_found handled correctly | 87.5% (14/16) | 87.5% (7/8) | 87.5% (7/8) |

The typed/full gap is real but narrower than the `correct` row suggests: both phrasings land
correct-or-partial on roughly the same share of questions, and the full phrasing converts more of
those into full credit mainly because it asks for every part of the answer explicitly ("what was
the total, and which was larger") where the typed phrasing asks for one thing and the gold's
`key_facts` demand several.

## Failure patterns

**1. Abstention with the answer in hand (36 items — the largest bucket).** Magpie set `not_found`
on questions whose gold file was already the top retrieval hit and whose answer is printed in plain
type on that page.

- `arch-06-typed` — declined on the Fort Morgan water report; `scan_gzyh0227.pdf` was the *only*
  file retrieved, and it is the gold source carrying 1506.0 ppm and pH 7.8.
- `arch-03-typed` / `arch-03-full` — declined on the 1953 Central Society letter; `scan_fybg0227.pdf`
  ranked 1 in both runs and states the 849 attendance figure.
- `viz-04-full` — declined although `chart_037.jpg` (rank 1) prints "7%" on the 1979 row and "20%"
  on the 2014 row of a labelled stacked bar; the typed phrasing read the same file and answered
  (wrongly, see below), so the file is legible to the pipeline.
- `arch-01-full`, `arch-05-*`, `arch-07-*`, `arch-10-*`, `rcpt-01-*`, `rcpt-03-*`, `rcpt-06-*`,
  `rcpt-09-*`, `study-03-*`, `study-08-*` follow the identical shape. The archive/table tier is worst
  hit: 14 of the 20 `arch-*` questions were declined.

**2. Right file, wrong cell (6 of the 21 wrong verdicts).** These are vision reads that landed on a
number adjacent to the one asked for.

- `arch-01-typed` — answered "73". `doc_10877.jpg` labels the 1960 local-health-department bar
  **$2,496,000**; the circled **73** is the percent-of-total marker printed *inside* that bar.
- `viz-04-typed` — answered "7%" for 2014. `chart_037.jpg` gives 20% for 2014; **7%** is the 1979
  cell in the same column of the same chart.
- `viz-08-typed` — answered "40%". `info_020.jpg` says "over 90% own a smartphone" under Myth 5;
  **40%** is the volunteering figure under Myth 1 at the top of the same infographic.
- `viz-09-typed` / `viz-09-full` — answered "$9 billion". `info_013.jpg` prints **$98 BILLION** in
  the "TOTAL" box of the total-contribution block; the diabetes $6 billion was read correctly, so
  the comparison's direction survived by luck.
- `rcpt-05-full` — answered "15.25 (Total Sales)". On `bad_receipt_014.jpg` **15.25** is the amount
  column for the 17 × Delicia Chocolate line; the receipt's "Total Sales (Inclusive of GST)" is
  **32.70**, with 40.00 cash and 7.30 change.

**3. Multi-file synthesis starved by top-k = 2.** Every multi-file question either lost a required
document or fabricated across the two it had.

- `rcpt-08-typed` — answered "33.90", which `bad_receipt_002.jpg` confirms is the Tesco Terbau
  receipt total; the other two Mr D.I.Y. receipts (30.90, 37.10) were never retrieved, so the
  "altogether" figure of 101.90 was unreachable. The full phrasing retrieved 12 files and still
  answered 46.91, which matches no receipt and no combination.
- `study-10-typed` / `study-10-full` — the three type-casting pages (`CseGyan-Cpp-Notes-17/18/19`)
  never appeared; retrieval returned Notes-14 and Notes-15, and I confirmed Notes-15 is the
  assignment/conditional-operator page. The typed run dumped that page's operator text verbatim.
- `viz-05-full` — with both gold charts retrieved, it answered "Mauritania 0.48% and Egypt 93.45%,
  Madagascar and Mozambique do not appear in the teaching time chart". `chart_036.jpg` lists
  **Madagascar at 58.09%** as its third bar; the answer read the top bar of each chart and then
  asserted the correct answer's absence.

**4. Answers from the wrong file (4 items).**

- `viz-07-typed` — "Reims (51)", cited from `table_fr_017.jpg`. `info_001.jpg` (rank 1, uncited)
  states the town of Condom fell from **7,298 in 1806 to 7,099 in 2009**.
- `rcpt-05-typed` — "Hallmark", from a scene-text photo; `bad_receipt_014.jpg` (ASIA MART) was not
  retrieved for this phrasing at all, though the full phrasing put it at rank 1.
- `rcpt-07-typed` / `rcpt-07-full` — retrieval returned `receipt_005.jpg` instead of the gold
  `receipt_040.jpg`, so the 2,352,460 Korean BBQ total was never in context.

**5. Degenerate generation (4 items).** `rcpt-07-typed` emitted `[{`; `study-09-typed` emitted
"File 2" while citing the correct figure `arxiv_029.png`; `phone-07-full` named the four gold
sponsors and then repeated "Bud Light" roughly 400 times; `study-10-typed` emitted a raw page
transcript including the note-taker's name. These are answer-formatting failures, not retrieval or
vision failures — in two of the four the model had the right file open.

**6. Confident wrong descriptions of figures (3 items).** `study-06-full` assigned fold 1 to train,
fold 2 to validation and folds 3–5 to test; `arxiv_017.png` brackets **1–3 train, 4 validation, 5
test** in large grey braces. `study-07-full` said Regular SBM "plateaus around 0.9"; on
`arxiv_004.png` the teal series reaches ~1.0 at Pin/Pout = 5 and stays there. `study-09-full`
described `arxiv_029.png` as a convolutional layer and invented a definition of phi, where the
figure explicitly boxes **phi(u) = ReLU(Wu + b)** and labels the outer product of phi(k) and v as
the "element of the prefix-sum".

## Golden-set issues

Seven items, logged in `golden_issues` rather than silently compensated for. None of them changed a
verdict except where noted.

1. **`arch-04-typed` / `arch-04-full`** — `key_facts` requires the invoice number `A-3088`, which
   neither phrasing asks for. Both answers give the correct $55.25 balance and nothing else, so both
   are forced to `partial`. Founders should decide whether identifying metadata belongs in
   `key_facts` when the question does not request it.
2. **`viz-02-full`** — the question is "which country had the lowest share?" but `key_facts` also
   demands "72%". A one-word answer that fully satisfies the question cannot reach `correct`.
3. **`phone-02-full`** — `key_fact` "Intel" is redundant beside "NUC5i7RYH" for a question asking
   for the exact model number. Graded here as entailed, which is why this item is a deterministic
   disagreement.
4. **`study-07-typed` (and the same shape in `study-06`, `study-09`, `study-10`)** — `key_facts` are
   sentence-length scene descriptions ("y axis is NMI, x axis is Pin/Pout"), not atomic facts. A
   short, correct answer matches zero of them, which makes the fact vector uninformative and pushes
   these items toward `wrong` under any string matcher.
5. **`viz-11-typed` / `viz-11-full`** — `gold_sources` lists only `diagram_003.jpg`, but
   `diagram_004`–`diagram_011` carry the same Antarctic food web and are listed as
   `acceptable_sources`. I verified `diagram_011.jpg` (which Magpie cited) shows leopard seal,
   elephant seal and other seals, and counted `acceptable_sources` toward `citation_ok`; a strict
   gold-source-only rule would score two correct answers as mis-cited.
6. **`study-04-typed`** — `key_fact` `variable = Expression ? true statement : false statement;`
   transcribes a handwritten `?` that on `CseGyan-Cpp-Notes-15.pdf` is drawn almost identically to a
   `2`. Magpie's "Expression 2, true statement: false statement" is a faithful-but-garbled read of an
   ambiguous glyph, not a fabricated value; I graded it `partial` on that basis.

Note also that the `merchant_as_printed` fields for `rcpt-03`, `rcpt-06`, `rcpt-07` and `rcpt-09`
record blurred-out merchant names. This is honest labelling, but it means those questions are
identified only by line items, which is plausibly why all eight of those answers were abstentions or
degenerate.

## Deterministic disagreements

14 of 120 (11.7%). Direction: I moved 6 items down (partial → wrong), 6 items up (wrong → partial,
partial → correct), and left the remaining 106 alone. Every downward move rests on a file I opened.

| qa_id | deterministic | judge | why |
|---|---|---|---|
| viz-04-typed | partial | wrong | Matcher credited the "7%" string; `chart_037.jpg` shows 7% is the 1979 row and the question asks for 2014 (20%). |
| viz-05-full | partial | wrong | Matcher credited "Madagascar" appearing in the text; the answer actually *denies* Madagascar is in the teaching-time chart, which `chart_036.jpg` contradicts at 58.09%. |
| viz-09-typed | partial | wrong | "$6 billion" matched; the tourism figure "$9 billion" contradicts the **$98 billion** printed on `info_013.jpg`. |
| viz-09-full | partial | wrong | Same as viz-09-typed. |
| rcpt-05-full | partial | wrong | "ASIA MART" matched; the answer labels 15.25 as Total Sales, where `bad_receipt_014.jpg` shows the total as 32.70. |
| rcpt-08-typed | partial | wrong | "33.90" matched a key fact, but `bad_receipt_002.jpg` confirms that is one receipt's total offered as the three-receipt aggregate (101.90). |
| viz-10-full | partial | correct | The answer states cordate = heart-shaped and the "ob" prefix = widest near the apex, i.e. everything the gold asserts; the matcher missed the literal token "obcordate". |
| phone-02-full | partial | correct | "NUC5i7RYH" is the exact model number asked for and entails the redundant "Intel" key fact. |
| phone-10-full | partial | correct | "KayC" vs gold "Kay C" is a whitespace variant; both brand and slogan are present. |
| arch-09-typed | wrong | partial | "Expense report total was bigger" is the gold's own conclusion with no contradicting value; it states no numbers, which is incompleteness, not error. |
| study-04-typed | wrong | partial | Recovers the ( ? : ) symbol and the syntax line's shape from a page whose handwritten "?" reads as "2"; no contradicting claim. |
| study-07-typed | wrong | partial | "Attribute SBM wins" is the correct direction for `arxiv_004.png`; the gold's key_facts are prose descriptions no short answer can match. |
| phone-03-typed | wrong | partial | The cartons in `1007129816.jpg` read Blitz Weinhard; "Biltz" is a transposition of the right brand, not a different brand. |
| phone-03-full | wrong | partial | Same as phone-03-typed. |

Matcher-precision read: the deterministic verdicts are biased *optimistic* on numeric questions —
five of the six downgrades are cases where a gold number appeared somewhere in the answer while the
number offered for the quantity actually asked was wrong. They are biased *pessimistic* on
short-form and proper-noun answers, where a whitespace, spelling or synonym variant blocked a match.
Net effect on the headline is small (deterministic: 20 correct / 30 partial / 24 wrong; judge:
19 / 28 / 21) but the per-item signal differs on one question in nine.

## Verdict-independent observations

- **`not_found_topic` is unreliable telemetry.** The string `"a landlord's emergency phone number"`
  appears in 8 rows — including rows where Magpie answered successfully (`viz-01-full`,
  `viz-03-typed`, `viz-06-full`, `rcpt-08-typed`). Other rows carry `"none"`, `""`, `"Today"`,
  `"ENUMERATION MODE"` and `"Amused"` (the answer itself). The field is picking up leaked prompt
  state and should not be trusted for abstention analysis.
- **Citations are almost never emitted.** Only 20 of 120 answers cited anything at all; 100 answers,
  including 15 of the 19 correct ones, returned an empty `magpie_cited`. Where citations did appear
  they were usually right (17 of 20 included a gold or acceptable source). The failure is coverage,
  not accuracy.
- **Retrieval is not the bottleneck at top-k = 2.** For single-file questions the gold source was at
  rank 1 in the large majority of items, including nearly every abstention. The `no-rerank`
  configuration is doing its job on rank 1; the losses are downstream, in the answer step's
  willingness to read the page it was handed.
- **Top-k = 2 is, however, fatal for multi-file questions.** All 11 `multi_file: true` questions
  scored partial, wrong or false_abstain — none correct. Several needed three documents
  (`rcpt-08`, `study-10`) which a two-slot context cannot hold.
- **Enumeration precision is poor even when recall is perfect.** `viz-11-typed` answered a
  "which seals" question with the full organism list from the diagram; `viz-11-full` listed penguins
  among the seals; `phone-07-full` looped one sponsor name hundreds of times. All three scored
  `correct` on key facts, but a user would not accept any of them as written.
- **Latency spread is wide and correlates with the 12-file retrievals.** The nine rows that returned
  12 candidates instead of 2 (e.g. `arch-06-full` 44.6 s, `phone-07-typed` 46.3 s, `rcpt-08-full`
  43.1 s) are the slowest in the run, and six of those nine still ended in an abstention or a wrong
  answer.
