# Judge report — 20260830T121044Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-rewrite

Of 120 answered questions, 12 are `correct`, 13 `partial`, 33 `wrong`, 46 `false_abstain`, plus 11 `correct_abstain` and 5 `false_answer` on the 16 `not_found` probes. Excluding the not-found probes, 12 of 104 answerable questions were fully right — 11.5%. The dominant failure is not retrieval and it is not reading: it is **refusal on top of a correct retrieval**. In 38 of the 46 false abstentions the gold source was sitting in the retrieved set, usually at rank 1, and Magpie returned a structured `not_found` anyway. The second-largest bucket is **wrong-file answering**: 33 `wrong` verdicts, of which roughly half quote text that is verifiably present in some *other* retrieved file (a receipt total answering a chart question, a period-tracker popup answering a bus-app question). Only the abstention discipline on the `not_found` set looks healthy (11/16 handled correctly). I opened 24 source files to adjudicate; **every one confirmed the golden answer** — no gold item was contradicted by its file. Typed phrasing is much worse than full phrasing (3/60 vs 9/60 correct, 22 wrong vs 11), and the query rewriter is a large part of why: 15 rewritten queries open with a "current date and time" lookup, and in 12 of those the user's actual topic is erased from the query entirely.

## Scoreboard

| Verdict | Overall | typed | full |
|---|---|---|---|
| `correct` | 12 | 3 | 9 |
| `partial` | 13 | 2 | 11 |
| `wrong` | 33 | 22 | 11 |
| `false_abstain` | 46 | 25 | 21 |
| `correct_abstain` | 11 | 5 | 6 |
| `false_answer` | 5 | 3 | 2 |
| **Total** | **120** | **60** | **60** |

Answerable questions only (excludes the 16 `not_found` probes): 104 total, 12 correct (11.5%), 25 correct-or-partial (24.0%). Split by phrasing: typed 3/52 correct (5.8%), full 9/52 correct (17.3%).

`not_found` probes only: 16 total, 11 `correct_abstain` (68.8%), 5 `false_answer` — typed 5/8 handled correctly, full 6/8.

Citation health on the 63 substantive (non-abstaining) answers: 21 cite the gold source or a declared acceptable source, 42 do not — 26 of those cite nothing at all, and 16 cite a file that is not the gold source.

## Failure patterns

**1. Abstention on a correct retrieval (46 items — the single biggest bucket).**
This is mostly not a retrieval failure. The gold file was retrieved on 38 of these 46 and Magpie still declined.
- `arch-07-typed` / `arch-07-full` — both gold KLM Cargo tables (`table_fr_011.jpg`, `table_fr_009.jpg`) came back at ranks 1 and 2 on both phrasings; both returned `not_found`.
- `arch-02-full` — `table_fr_001.jpg` at rank 1. The file's last two rows are bold, full-width, and read `BÉNÉFICE NET COURANT PAR ACTION … 4,58 … 4,54`. Declined anyway.
- `phone-08-typed` — `screen_24243.jpg` at rank 1. The screen is two bullets: "Get a free* one-way ticket for every 8 trips traveled" and "Get priority (Group A) boarding". Declined anyway.
- `rcpt-06-full` — `receipt_021.jpg` at rank 1, printing every requested line including `TOTAL: Rp224,908` in the largest type on the receipt. Declined anyway.
The whole `arch` family is the extreme case: 17 of 20 archive questions ended in `false_abstain`, and the gold document was in the retrieved set for all but one of them. The eight abstentions where the gold genuinely was *not* retrieved are `viz-07-typed`, `arch-05-typed`, `study-04-typed`, `phone-09-typed` (all four rewriter-hijacked), `rcpt-07-full`, and the three HTTP-400 rows below.

**2. Answering from a neighbouring retrieved file (≈16 of the 33 `wrong`).**
Top-k is 2 with rerank off, so rank-2 is frequently an unrelated document, and the answer is drawn from it.
- `phone-08-full` — answered "5 stars". That string is on `screen_24479.jpg`, the period-tracker popup that came back at rank 2. `screen_24243.jpg` (rank 1) says 8 trips and Group A.
- `study-09-full` — answered with Res2Net/PVT backbones, IC loss and pseudo masks. All of that is on `arxiv_027.png` (rank 2). The asked figure, `arxiv_029.png` (rank 1), shows `A × V` rewritten as `Q' × (K')ᵀ × V` with `φ(u) = ReLU(Wu + b)` and an outer-product prefix sum.
- `phone-03-typed` — answered "order, tip well, walk away", text from the `info_021.jpg` infographic at rank 2. The hat in `1007129816.jpg` is crocheted around Blitz Weinhard cartons.
- `study-08-full` — "MEMS and microfluidics at 40%". `deck_027.pdf` does contain a "MEMs and microfluidics" box, but on the *system-integration* slide; the food-industry pie on a later slide reads Biosensors 8%, LC/MS 38%, ELISA 18%, LC/UV 18%, other screening 12%, electrophoresis 6%.

**3. Reading the wrong row or column of the right file (5 items).**
The retrieval and the file are correct; the extraction lands one band over.
- `viz-04-full` — gave 29% for the 2014 right-to-far-right share. On `chart_037.jpg` the 2014 row is `7 | 25 | 9 | 29 | 20 | 7`; 29 is the **center-right** band and 20 is the right-to-far-right band. 1979's 7% was read correctly, so this is a column-alignment error, not a hallucination.
- `viz-05-typed` / `viz-05-full` — `chart_002.jpg` has exactly three bars: Mauritania 0.48%, Fiji 0.38%, Madagascar 0.21%. The typed variant returned the top bar (Mauritania), the full variant returned "The United States" and then read back all three values. Only Madagascar also appears in `chart_036.jpg` (58.09%).
- `viz-09-full` — `info_013.jpg` prints four candidate figures. Magpie took `$43.4 BILLION` (direct GVA) where the question asks for total contribution, which the file's "TOTAL CONTRIBUTION" panel gives as `$98 BILLION`.
- `study-05-full` — `electric-charge-and-field-9.pdf` writes `if θ=0 → τ=0 {stable}`, `if θ=180° {unstable}`, `if θ=90 → τmax = PE`. Magpie reported "Unstable when 90°", collapsing the last two lines.

**4. Negation inversion (1 item, but a notable class).**
`phone-11-typed` reported that the popup "wanted to ask for a donation". `screen_24479.jpg` reads, in full: *"We aren't asking you for a donation, but if you like our apps, please take the time to give them 5 stars and leave a supportive comment!"* The cycle interval (30 days) was read correctly off the same pair of screenshots, so the file was legible — the negation was dropped.

**5. Query-rewriter hijack (15 rows, 12 with the topic erased) — the typed-phrasing killer.**
On short typed queries the rewriter substitutes a clock lookup. `viz-10-typed` ("leaf diagram cordate obcordate what ob means") became `current date and time Sunday 2026-08-30 08:15 EDT`, which retrieved two degraded receipts; the answer was "ob means outer". Same mechanism on `viz-07-typed`, `viz-08-typed`, `arch-05-typed`, `study-04-typed`, `study-10-typed` (answered with a receipt line: *"item 'Plastic', quantity 2, RM 15.50 each, RM 31.00"*), `phone-09-typed`, and four of the eight `nf-*-typed` probes. This is the clearest single lever in the run: 22 of 60 typed rows are `wrong` versus 11 of 60 full rows, and the rewriter accounts for most of the gap.

**6. Echo and non-answer (3 items).**
`rcpt-02-typed` returned the query string itself ("mcdonalds breakfast mcmuffin porridge") as the answer. `arch-06-typed` returned "Fort Morgan Sugar Factory" — the subject of the question, not the dissolved-solids or pH values. `rcpt-09-typed` returned "Original brewed tea was pricier", naming the line item the two receipts share instead of either visit total.

## Golden-set issues

**No golden answer was contradicted by its source file.** All 24 files I opened confirmed the gold text, including every value the run disputed (cocoa 18.81; 20% in 2014; Madagascar 0.21%/58.09%; 4,58; ASIA MART / RM 32.70; Rp224,908; Champaign, IL; 8 trips / Group A; Biosensors 8% / LC/MS 38%; Kay C "The FIRST for THIRST"; DOS EQUIS; the eight OOPs branches; θ=180° unstable). The issues below are all about how the golden items are *specified*, not about what they claim — they matter for the silver→gold review because they distort automated scoring.

1. **Over-specified `key_facts` — facts the question never asks for (9 items).** `viz-02-typed/full` require "72%" though both phrasings ask only which country was lowest. `viz-06-typed` requires "1.7 million" though the typed query asks only for the annual cost. `arch-04-typed/full` require the invoice number "A-3088" though both ask only for the balance due. `phone-02-typed/full` require "Intel", which is redundant with "NUC5i7RYH". `phone-06-typed/full` require "Pure Running", the timing company's logo, when the question asks for the race name. These nine drive most of my `partial → correct` upgrades over the deterministic matcher; the fix is to trim `key_facts` to what the question actually demands, or to add a `required_facts` vs `context_facts` split.

2. **Compound descriptive `key_facts` that cannot be scored atomically (3 items).** `study-06`, `study-07` and `study-09` use whole sentences as single facts ("ten columns labelled 1+ through 5- (plus and minus per fold)", "at Pin/Pout around 3 Attribute SBM is higher (about 0.79 vs about 0.65)"). A substantively half-right description scores zero facts, so `facts` and `verdict` diverge for these rows. Recommend splitting into atomic assertions.

3. **`viz-11` — undeterminable gold source.** `gold_sources` names `diagram_003.jpg` while eight near-duplicate Antarctic food-web diagrams (`diagram_004` … `diagram_011`) are listed as acceptable. The corpus genuinely cannot distinguish which one the user meant, so per-file citation scoring on this pair is not informative. (I counted a cited acceptable source as `citation_ok: true`.)

4. **`viz-09` — ambiguity worth pinning down.** `info_013.jpg` prints $43.4bn direct GVA, $47.5bn direct GDP, $87bn total GVA and $98bn total GDP. The gold answer's "$98 billion" is correct, but the answer would be easier to grade if the gold stated explicitly that "total contribution" means the total-GDP row — Magpie's near-miss ($43.4bn) is a real figure from the same file.

Also worth noting for the founders: four receipt items (`rcpt-03`, `rcpt-06`, `rcpt-07`, `rcpt-09`) have the merchant name blurred out of the photograph by construction. That is a legitimate hard case, but it means those questions can never be answered by merchant-name retrieval, only by line-item matching — a property the dataset card should state.

## Deterministic disagreements

The deterministic pass scored 3 `correct`, 20 `partial`, 36 `wrong`, 45 `false_abstain`, 10 `correct_abstain`, 6 `false_answer`. I differ on **23 of 120** rows: 16 upgrades, 5 downgrades, 2 category corrections. They fall into four clean groups.

**A. Substring match scored a value that does not answer the question (2 rows, judge harsher).**
- `rcpt-08-full` — deterministic `partial`, judge `wrong`. Magpie answered "33.90". That string is a gold `key_fact` (one of the three Mr D.I.Y. receipts), so the matcher scored a hit — but the question asks for the combined total, RM 101.90. Answering with a component is a wrong answer, not a partial one.
- `phone-11-typed` — deterministic `partial`, judge `wrong`. The matcher found "30 days" and stopped. It could not see that "the popup wanted to ask for a donation" is the exact inverse of the popup's own sentence, which I verified on `screen_24479.jpg`.

**B. Abstaining prose the matcher read as a content answer (1 row).**
- `arch-05-typed` — deterministic `wrong`, judge `false_abstain`. The answer text is literally `Not found`. The rubric classifies abstaining prose as `false_abstain`; the matcher treated it as a substantive answer that missed the facts. Same zero credit, but it belongs in the abstention bucket, which changes the diagnosis of this run materially — it is an abstention problem, not a reading problem.

**C. `not_found` denial read as a supplied value (1 row).**
- `nf-03-full` — deterministic `false_answer`, judge `correct_abstain`. The answer is the single word "No" to "Can you find my apartment lease agreement?". That is a correct denial, not a concrete value. The matcher appears to treat any non-empty string with `not_found: false` as a supplied answer.

**D. Key-fact over-specification (9 rows) and figure-description scoring (7 rows), judge more lenient; plus 3 substring-inside-a-contradiction rows, judge harsher.**
- `viz-02-full`, `viz-06-typed`, `viz-06-full`, `viz-10-full`, `arch-04-full`, `phone-02-typed`, `phone-02-full`, `phone-06-typed`, `phone-06-full` — deterministic `partial`, judge `correct`. In each case the answer fully answers the question as posed and the missing `key_fact` is not something the question asks for (see Golden-set issues §1). `viz-06-full` is the purest case: the matcher wanted the literal "1.7 million"; Magpie said "1 in 10 adults", which is the *same statistic in the same typeface* on `info_024.jpg`, and which the gold answer itself offers as the alternative phrasing. This is a phrasing-blindness miss by the matcher.
- `study-04-full`, `study-06-typed`, `study-07-typed`, `study-07-full`, `phone-03-full`, `phone-09-full`, `phone-10-full` — deterministic `wrong`, judge `partial`. These answers get the substance partly right but match no literal key-fact string: "Attribute SBM" (correct winner, no numbers), "Biltz" (one-letter corruption of Blitz), "XX" (the logo on a sign whose brand line reads DOS EQUIS), "KayC root beer" (brand right, slogan missing).
- `viz-04-full`, `viz-05-full`, `viz-09-typed` — deterministic `partial`, judge `wrong`. Here the matcher found true substrings ("7%", "0.21%", "$6 billion") inside answers whose central claim contradicts the file: 29% for a band that reads 20%, "The United States" for a chart containing only Mauritania/Fiji/Madagascar, and the diabetes cost attributed to tourism.

Net matcher bias on this run: it is **too generous on substring hits inside contradicting answers** and **too harsh on correct answers phrased differently from the gold**. The second effect dominates, so `correct` moved from 3 to 12 and `wrong` from 36 to 33. The overall picture of the run is unchanged — the failure is abstention and wrong-file answering either way — but the per-item signal is noisier than the aggregate suggests, and any A/B comparison built on the deterministic verdicts alone will under-count real wins.

## Verdict-independent observations

1. **A leaked placeholder string is in the pipeline.** `not_found_topic` reads `"a landlord's emergency phone number"` on 12 rows spanning every category (`viz-01-full`, `viz-02-full`, `viz-05-full`, `arch-01-full`, `arch-03-typed`, `arch-06-full`, `study-06-typed`, `study-06-full`, `study-08-full`, `rcpt-07-full`, `rcpt-09-full`, `phone-09-full`). No question in this dataset mentions a landlord. This is almost certainly a hard-coded example or a stale default in the not-found prompt template leaking into production output. It appears on rows that both abstained and answered, so it is not merely cosmetic — it suggests the not-found reasoning path is being seeded with an unrelated topic.

2. **Three rows died on a local endpoint error, not on model behaviour.** `study-03-full`, `phone-05-typed` and `phone-11-full` all returned `HTTPStatusError: 400 Bad Request` from `http://127.0.0.1:9400/v1/chat/completions`, with empty `retrieved` arrays and 1.7–3.8s latencies. They are scored `false_abstain` per the rubric (empty answer), but they are infrastructure failures and should be excluded or re-run before this run is compared against another.

3. **Retrieval depth is bimodal and unexplained.** Most rows return exactly 2 documents (top-k 2), but eight rows returned 12 (`arch-06-full`, `rcpt-01-full`, `rcpt-08-typed`, `rcpt-08-full`, `phone-05-full`, `phone-07-typed`, `nf-06-full`, `arch-04-full`'s single-doc counterpart aside). Every one of the 12-document rows still failed — five abstained, three answered from the wrong file. Widening k alone is not the fix.

4. **Retrieval itself is mostly fine.** The gold source appeared in the retrieved set on the large majority of answerable rows. The genuine retrieval misses are few: `rcpt-07` (both phrasings — `receipt_040.jpg` never surfaced), `study-10-full` (Notes-14/15 instead of Notes-17/18/19), and the rewriter-hijacked queries. Fixing the rewriter and the abstention threshold would move far more than fixing the retriever.

5. **Citation behaviour is decoupled from answer correctness.** 26 of the 63 substantive answers cite nothing at all, including several fully correct ones (`viz-10-full`, `phone-06-typed`, `phone-06-full`, `phone-07-full`). Conversely, several `wrong` answers cite the correct gold file (`arch-02-typed` cites `table_fr_001.jpg` and then answers "Bouygues Telecom"; `phone-10-typed` cites the Kay C photo and answers "Sizzle!"; `study-02-typed/full` cite the OOPs page and answer "C++ features"). The citation list is evidently being assembled from the retrieval set rather than from what the answer was actually grounded in.

6. **Two answers are raw OCR dumps, not answers.** `study-10-full` returned ~40 lines of transcribed handwriting from the operators pages verbatim, including page furniture ("Camlin", "Kailash Joshi", "14"). `study-05-full` returned garbled glyph substitutions (`χ = Pγ sinΰ`, `Stable when π = 0`). Both indicate the answer-composition step is sometimes passing the vision transcript straight through.

7. **Latency spread is wide and correlates with failure.** Successful reads clustered at 5–17s; the abstentions and the 12-document retrievals ran 24–49s (`arch-06-full` 49.4s, `phone-05-full` 44.1s, `study-11-full` 43.7s). The slowest rows are also the least useful ones.
