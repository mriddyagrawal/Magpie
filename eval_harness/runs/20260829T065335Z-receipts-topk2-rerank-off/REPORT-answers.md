# REPORT — answers analysis
**Run:** `20260829T065335Z-receipts-topk2-rerank-off`
**Config:** lfm-local LFM2.5-VL-3B Q6_K · top_k=2 · rerank OFF · solo gate structurally off · temp 0 · ctx 16384
**Sources:** `answers_enriched.json`, `judge_verdicts.json`, `raw/answers.jsonl`, `raw/appdata/logs/llm-2026-08-29T07-03-31Z.log` (240 records: 120 rewrite + 120 answer), `eval_harness/datasets/receipts/golden.json`
**Method:** all 120 questions joined 1:1 to their answer-stage LLM request/response pair by verbatim question text (120/120 matched, 0 leftover log records). Every claim below is reproducible from that join.

---

## 0. Headline: the judge's central finding is wrong, and the run's most important number is not in `metrics.json`

The judge report reads the 43 `false_abstain` as Magpie declining to answer, and diagnoses "identifier-shaped questions decline as a class." **The model never declined once.** Across all 120 answer-stage calls the LLM emitted `not_found: true` **zero times** and emitted an empty `answer` string **zero times**. All 41 structured abstentions in `answers_enriched.json` were manufactured after generation by a post-processing guard in `src/answer.py`, which deleted an answer the model had already produced.

| | count |
|---|---|
| answer-stage LLM calls | 120 |
| responses that failed to parse as JSON | **0** |
| responses with `not_found: true` from the model | **0** |
| responses with empty `answer` from the model | **0** |
| responses where the backend errored (no content) | 4 |
| answers **deleted by the harness** after generation | **41** |
| answers that reached the user | 75 |

This is not a parse failure and not a grammar failure. It is a deliberate product guard misfiring on 100% of a category. Sections 1 and 2 establish the two mechanisms that produce essentially the entire scoreboard.

---

## 1. Cluster C1 — the groundedness guard deletes 41 answers (34% of the run), and the rule it actually applies is "the answer contains a number ≥ 100"

### 1.1 The mechanism

`src/answer.py:869-905` runs `looks_fabricated(ans.answer, context_text)` and, when it fires, sets `not_found=True`, `answer=""`, `sources_used=[]` and returns. `context_text` is built at `src/answer.py:888-893` from `per_file_blocks`, filtered to `isinstance(b, str)` — **text blocks only, images excluded**.

In this corpus there are no text blocks. 268 of 275 file blocks in the 120 prompts are empty; the 7 non-empty ones are not receipt content at all — they are the harness's own boilerplate ("*(Context note: 5 lower-ranked source file(s) were omitted to fit the local model's context window: …)*"). So the supervisor's "97% of file TEXT blocks are empty" is correct as measured but understates it: **100% of blocks contain zero document text.** `context_text` is always empty or harness boilerplate.

`src/grounding.py` sets `MIN_INTERESTING = 100`; `numerals()` discards every token below 100, and `looks_fabricated` returns True iff at least one numeral survives that filter and none is found in context. With context permanently empty, the guard collapses to a single deterministic rule:

> **If the answer contains any number ≥ 100, delete the answer and report not-found. Otherwise ship it unchecked.**

### 1.2 Verification

I re-ran `looks_fabricated(llm_answer, "")` over all 116 non-errored items and compared it to the harness's recorded `not_found`:

```
TP=41  FP=0  FN=0  TN=75   accuracy = 1.000
41/41 deleted answers contain a numeral >= 100
 0/75 shipped answers contain a numeral >= 100
```

Perfect separation. The abstention rate in this run is a pure function of the magnitude of the digits in the answer string. It carries no information about model confidence, retrieval quality, or question type.

### 1.3 What was destroyed

Reading the raw log content for the deleted items: **7 answers were fully correct** (every gold `key_fact` present) and **4 were partially correct**. The guard converted them into false abstentions.

| qa_id | answer the model produced (deleted) | gold key_facts |
|---|---|---|
| `rcpt-d-07-typed` | `GM RACK INVOICE NO: KNG01-1032303 [2]` | `KNG01-1032303` |
| `rcpt-d-07-full` | `KNG01-1032303` | `KNG01-1032303` |
| `rcpt-e-06-typed` | `Invoice No: 18291/102/T0380` | `18291/102/T0380` |
| `rcpt-b-06-full` | `SS3-154439` | `SS3-154439` |
| `rcpt-b-08-full` | `99 SPEED MART S/B (519537-X), 104 SUNQUICK OREN 330ML, RM 5.35` | `99 SPEED MART`, `5.35` |
| `rcpt-c-02-typed` | `The Koh Seng Ladder was purchased on 04/12/2017 for RM 848.00` | `04/12/2017` |
| `rcpt-b-10-full` | `The receipt from 18/09/2017 lists a total of RM 26.00 inclusive of GST` | `56.00`, `26.00`, `10/07/2017` (partial credit) |

`rcpt-b-08-full` is the sharpest case. It is arguably the best answer in the entire run — correct shop, correct line item, correct amount, correct citation. It was deleted because the model helpfully included the company registration number `519537-X`, the product code `104` and the bottle size `330ML`. The one number that mattered, `5.35`, is below `MIN_INTERESTING` and was never even considered.

This also fully explains the judge's failure pattern #3. `rcpt-d-07-typed`/`-full`, `rcpt-e-06-typed`, `rcpt-b-06-full` did not "decline as a class" — the model read the receipt and returned the exact invoice number. Invoice numbers parse as numerals ≥ 100 and were therefore guaranteed to be deleted. The judge's interpretation of this cluster should be withdrawn.

### 1.4 The guard's threshold is inverted for this corpus

The threshold is not merely unhelpful here, it is anti-correlated with the thing it is trying to catch. Malaysian receipt totals are mostly under RM 100, so **fabricated totals sail through** while **correct identifiers, dates and larger totals are destroyed**:

- Passed unchecked (all < 100): `rcpt-nf-01-full` "You spent 44.00ZR on Anchor Flour and 15.40SR on Diamond Foil 7, for a total of 59.40ZR" — a complete fabrication about a vendor absent from the corpus. `rcpt-nf-05-typed` "golden key maker bill: 56.80". `rcpt-nf-06-full` "12.15". `rcpt-nf-02-full` "RM 63.90".
- Deleted: every correct invoice number above.

Of the 14 `not_found` probes, the guard caught **0** of the 10 fabrications that carried a number.

### 1.5 The measurement ceiling

Applying the same rule to the golden set itself: **50 of the 106 answerable items (47%) are structurally unanswerable in this configuration.** Their `key_facts` consist solely of numbers ≥ 100, so an answer stating exactly and only the gold fact would still be deleted. `rcpt-a-01` (gold `269.40`) is one — a perfect "269.40" would have been suppressed. If the model phrased answers like the `golden_answer` prose, 82/106 would trip.

**The maximum achievable `correct` rate for this arm is ~53%, not 100%.** Every headline in `metrics.json` and `report.md` is measured against a ceiling that is not stated anywhere in them. `MAGPIE_STRICT_GROUNDING=0` does not fix this — that flag only controls `strip_generated_blocks`; the guard itself has no kill switch.

---

## 2. Cluster C2 — file order: the reversal at `src/answer.py:832` is the single largest correctness lever, and it is pointed the wrong way

### 2.1 Confirming the supervisor's claim 3

Confirmed and refined. Prompt order is the exact reverse of `ask()`'s ranking in **113/120**. The 7 exceptions are not counterexamples: 4 are the backend-error items with zero retrieval (§5) and 3 are truncated 12-candidate fan-outs where files were dropped to fit the context window. Where a full ordering exists, the reversal is universal.

### 2.2 The result

For every item I located the gold receipt's **slot in the prompt** (File 1 = presented first = worst-ranked under the reversal) and crossed it with the judge's verdict. Restricting to the clean case — 2-file prompts where gold occupies exactly one slot, n=85:

| gold slot | correct or partial | total | rate |
|---|---|---|---|
| **slot 1** (first shown, worst-ranked) | **5** | 22 | **22.7%** |
| **slot 2** (last shown, best-ranked) | **0** | 63 | **0.0%** |

Fisher exact **p = 0.0008**.

Excluding items the guard deleted, so only answers that actually shipped:

| gold slot | correct | partial | wrong | rate |
|---|---|---|---|---|
| slot 1 | 2 | 3 | 8 | **38.5%** |
| slot 2 | 0 | 0 | 37 | **0.0%** |

**Every single answer produced when the gold file was in the recency position was wrong. All 37 of them.**

The citation data says the same thing independently. Of the 101 answers where the model named a path that was actually in its prompt, **91 named the file in slot 1** and only **10** named any later slot. The model reads the first image attached and largely ignores the rest.

### 2.3 The natural A/B experiment

Four `pair_id`s happen to have both arms retrieve the *same two files in opposite order*. This is a controlled experiment on file order with the model, temperature, corpus and evidence held constant:

| pair | typed gold slot → verdict | full gold slot → verdict |
|---|---|---|
| `rcpt-a-04` | slot 2 → **wrong** (`"Cash"`) | slot 1 → **correct** (`"Card (VISA)"`) |
| `rcpt-d-10` | slot 1 & 2 → wrong (attribution inverted) | slot 1 & 2 → **partial** (`"AA Pharmacy"`) |
| `rcpt-e-02` | slot 1 → wrong (`"Mei Let Restaurant"`) | slot 2 → guard-deleted (`"2018-03-27 23:38:45"` — read off the slot-1 distractor) |
| `rcpt-b-05` | slot 1 → wrong (`49.50`) | slot 2 → wrong (`2.64`) |

`rcpt-a-04` is the cleanest single data point in the run: identical two files, order flipped, answer flips from wrong to right. The judge lists this as a typed-vs-full phrasing difference. It is not — it is a file-order difference (§6).

### 2.4 The retrieval paradox

Because retrieval success puts gold at rank 1 and the reversal then pushes rank 1 into the recency slot, **better retrieval produces worse answers**:

| retrieval outcome | correct-or-partial |
|---|---|
| `hit@1 = 1` (gold ranked first) | 4/83 = **4.8%** |
| `hit@1 = 0` (gold ranked lower) | 3/23 = **13.0%** |
| `first_gold_rank = 1` | 4/83 = 4.8% |
| `first_gold_rank = 2` | 2/8 = **25.0%** |

This inverts the judge's "the binding constraint is `topk=2` with rerank off." Raising k or re-enabling the reranker without fixing the ordering will push gold further into the recency slot and make the arm *worse*. The ordering must be fixed first; it is a one-line change.

The `src/answer.py:832` comment cites Liu et al. (2023) on recency bias in small decoder-only models. That result concerns *text* in a token stream. Here the evidence is a sequence of attached images with empty text blocks, and this model is measurably **primacy-biased on image slots** (91:10). The cited rationale does not transfer to the vision path.

### 2.5 Examples

All of these cite and answer from the slot-1 file:

| qa_id | answered | gold key_facts | slot-1 (worst-ranked) file |
|---|---|---|---|
| `rcpt-a-01-typed` | `40.80` | `269.40` | `X51005806718` |
| `rcpt-a-01-full` | `RM 77.40` | `269.40` | `X51005719863` |
| `rcpt-a-08-full` | `TRI SHAAS SDN BHD` | `TEO HENG STATIONERY & BOOKS`, `1.05` | `X51005705759` |
| `rcpt-a-05-full` | `0.60` | `24.69` | `X51005676542` |
| `rcpt-a-06-typed` | `Yong Tat Hardware Trading, 1 item (3/4" ALUMINIUM ROD)` | `AR RED GASKET`, `72.00` | `X51005568889` |

On `rcpt-a-08-full` the judge writes that the gold Teo Heng receipt "was cited alongside but not read." Accurate, but the reason is positional: Teo Heng was in slot 2.

---

## 3. Remaining clusters

Full taxonomy of all 120, mutually exclusive, in precedence order (guard → error → gold slot):

| cluster | n | share | typed | full |
|---|---|---|---|---|
| **C0** succeeded (correct / partial / genuine correct-abstain) | 9 | 7.5% | 3 | 6 |
| **C1** grounding-guard deletion (§1) | 41 | 34.2% | 25 | 16 |
| **C2** wrong-file read — gold in prompt but not slot 1 (§2) | 39 | 32.5% | 14 | 25 |
| **C3a** right file in slot 1, wrong field | 8 | 6.7% | 6 | 2 |
| **C3b** gold never reached the prompt (true retrieval miss) | 9 | 7.5% | 6 | 3 |
| **C4** fabrication on an absent vendor (§4) | 10 | 8.3% | 5 | 5 |
| **C5** backend 400 (§5) | 4 | 3.3% | 1 | 3 |

### C3a — right file, wrong field (8 items)

The only cluster that is genuinely a vision/OCR limitation, and the most tractable. The model has the correct receipt in the position it attends to and reads the adjacent row.

- `rcpt-b-05-typed` — returned `49.50` (Sub Total exclusive GST) for the GST line; gold `2.97`.
- `rcpt-e-09-typed` — `"popular empire has 5.99 T while aeon shah alam has …"`; `5.99` is a line item, not a total.
- `rcpt-d-10-typed` — `"aa pharmacy: 34.80, Green Lane Pharmacy: 25.80; Green Lane Pharmacy is more expensive"`. Both figures are real numbers from the wrong rows and the conclusion inverts. I agree with the judge's downgrade of this from `partial` to `wrong`.
- Enumeration (3 items): `rcpt-en-01-typed` answered `4`, `rcpt-en-01-full` answered `6 times`, gold `5`; `rcpt-en-03-full` answered `January 4th` where gold is 6 dates. All three counted a 2-file window, not the corpus. `topk=2` makes enumeration structurally impossible regardless of any other fix.

### C3b — genuine retrieval misses (9 items)

`rcpt-b-04-typed`, `rcpt-c-03-full`, `rcpt-c-10-typed`, `rcpt-d-02-typed`, `rcpt-d-03-typed`, **`rcpt-d-05-typed`**, **`rcpt-d-05-full`**, `rcpt-d-09-typed`, `rcpt-e-10-typed`.

Correction to the judge: `rcpt-d-05` is listed under "wrong-file reads inside a 2-item window" with the note "Neither read the file the question was about." The gold receipt `X51005719823` **was never in either prompt**. Both arms are retrieval failures, not answer-stage failures.

---

## 4. Abstention: 14 `not_found` probes, and only 2 genuine correct abstentions

The judge scores 4 `correct_abstain`. Checking provenance in the log, **2 of the 4 are artifacts of the guard**, not abstention behaviour:

| qa_id | judge | what the model actually produced |
|---|---|---|
| `rcpt-nf-03-typed` | correct_abstain | **`"CSC-105 has 4 credit hours[1] and is offered every fall[2]"`** — verbatim regurgitation of the citation-format *example* in the system prompt (`src/answer.py:305-309`). Deleted only because `105 >= 100`. `sources_used` was `["CSC-105 has 4 credit hours[1]", "offered every fall[2]"]`. |
| `rcpt-nf-06-typed` | correct_abstain | `"Print Expert SDN BHD (989625-A) NO 18, 20, 22, JALAN BUNGA TANJONG 2/16, 40000 SHAH ALAM… GST ID : 000886677504"` — a whole letterhead OCR'd off an unrelated receipt. Deleted because the address digits are ≥ 100. |
| `rcpt-nf-03-full` | correct_abstain | genuine: `"No, there is no receipt from Coffee Bean & Tea Leaf in the provided files"` — **prose only, `not_found=false`** |
| `rcpt-nf-07-full` | correct_abstain | genuine: `"No, there is nothing from Platinum Racking in your receipts"` — **prose only, `not_found=false`** |

**True abstention discipline is 2/14 (14%), not 4/14.** And both genuine declines set `not_found=false`, so any consumer keying off the structured flag mis-handles them. `product_findings.not_found_flag_missing: 1` undercounts this by half.

Restating §0 for this section: **model-initiated structured abstention across the whole run is 0/120.** The `not_found` contract in the schema is, on this backend, entirely unexercised.

### What it did on the other 10

All fabrication, none hedging, and the guard caught none of them because every fabricated figure was < 100:

`rcpt-nf-01-typed` "POPULAR BOOK CO. (M) SDN BHD" · `rcpt-nf-01-full` "44.00ZR on Anchor Flour and 15.40SR on Diamond Foil 7, total 59.40ZR" · `rcpt-nf-02-typed` "25.80" · `rcpt-nf-02-full` "RM 63.90" · `rcpt-nf-04-typed` "moonlight cake house" · `rcpt-nf-04-full` "Yes, the Moonlight Cake House receipt is available [1]" · `rcpt-nf-05-typed` "golden key maker bill: 56.80" · `rcpt-nf-05-full` "18.70 RM" · `rcpt-nf-06-full` "12.15" · `rcpt-nf-07-typed` "Platinum Racking Sdn BHD".

Note the shape: on terse typed probes the model echoes the vendor name back as the answer (`nf-04-typed`, `nf-07-typed`, `nf-01-typed`), which is name-completion rather than retrieval. `nf-07` is the clean pair — typed echoed the name, full declined correctly. I agree with the judge's upgrade of `rcpt-nf-07-full` to `correct_abstain`, and note the deterministic pass catches the near-identical `nf-03-full` but not `nf-07-full`, so the prose-abstention detector is inconsistent rather than absent.

The solo gate never fired (`fire_rate: 0.0`, `ranked_pre_gate: 12` on all 120) — including on all 14 absent-vendor probes, which is exactly where it would have paid.

---

## 5. Backend errors: not random — correlated with image count

`rcpt-b-09-typed`, `rcpt-b-09-full`, `rcpt-c-10-full`, `rcpt-d-09-full` returned `HTTPStatusError: 400 Bad Request` from `http://127.0.0.1:9400/v1/chat/completions` with zero retrieval recorded.

The log shows why the judge's "harness fault" label is incomplete: **all four requests attached 7 images.** Only 7 of 120 requests attached more than 2, and 4 of those 7 failed (57%) versus **0 of 113** two-image requests. This is a hard failure of the local llama.cpp endpoint above a small image count, not a flaky harness. It is a live constraint on any plan to raise `top_k` for the vision path — larger k means more images per request and this backend already breaks at 7. The three 7-image requests that did complete (`rcpt-a-09-typed`, `rcpt-a-10-full`, `rcpt-e-10-full`) all produced wrong answers.

---

## 6. Typed vs full: the arms differ by file order, not by phrasing

The judge attributes the typed/full split to query rewriting. The data supports a weaker version of that and a stronger positional story.

**Rewriting does inject wall-clock noise, and it does cost retrieval.** 56/120 rewrites carry `2026-08-29` or `EDT` as search terms — 32 typed and 24 full, so it is not a typed-only phenomenon as the judge implies. It measurably hurts:

| | hit@1 |
|---|---|
| rewrites with date injection (n=46 scored) | **0.674** |
| rewrites without (n=60) | **0.867** |

Four answers returned the wall clock *as the answer* — `rcpt-a-02-typed` `"2026-08-29 03:04 EDT"`, `rcpt-a-02-full` `"Saturday, 2026-08-29 03:04 EDT"`, `rcpt-b-02-typed`, `rcpt-c-02-full` — all four on date questions. The user message opens with `Current date and time: Saturday, 2026-08-29 03:03 EDT` with no delimiter separating it from the file blocks, so the model treats it as evidence. Two prompt-template strings likewise surface as output: `not_found_topic` is the literal example `"a landlord's emergency phone number"` on 3 items and `"current date and time"` on 4, and `rcpt-nf-03-typed`'s whole answer is the system prompt's CSC-105 example (§4).

**But the arms' fate is set by slot, not by phrasing.** The gold receipt lands in slot 1 for 12/53 typed items but only 10/53 full items, and lands in a later slot for 30 typed vs 40 full. That, plus the guard's 25-vs-16 typed/full kill split, reproduces the whole scoreboard difference: typed keeps more gold in the readable slot but writes more identifier-shaped answers that the guard deletes (28 false abstains); full retrieves better, which pushes gold into the dead recency slot, so it ships more wrong answers (32).

Of the 5 `pair_id`s where exactly one arm succeeded, **not one is explained by phrasing**:

| pair | what actually differed |
|---|---|
| `rcpt-a-04` | Same 2 files, opposite order. Gold slot 2 → "Cash" (wrong); gold slot 1 → "Card (VISA)" (correct). Pure order effect. |
| `rcpt-d-10` | Same 2 files, opposite order. Slot-1 file's vendor becomes the answer in both; only the full arm's slot-1 file is the right vendor. |
| `rcpt-b-08` | Different retrieval sets. The **full arm answered it perfectly** (`99 SPEED MART S/B … RM 5.35`) and the guard deleted it; the typed arm answered less completely and shipped. The arm that did better scored worse. |
| `rcpt-nf-06` | Typed "succeeded" only because the guard deleted a fabricated letterhead (§4). |
| `rcpt-nf-07` | Typed echoed the vendor name; full declined in prose. The one real phrasing effect in the set. |

Conclusion: **`by_phrasing` in `metrics.json` (typed 0/53, full 0/53) is measuring file-order luck and guard-trigger rate, not phrasing robustness.** It should not be used to draw conclusions about terse-vs-conversational queries until the ordering is fixed.

---

## 7. Citations: `sources_used` is populated, then 36% of it is thrown away — and `cited: 0.75` is a count, not a rate

### Reconciling "cited 0.75" against empty `magpie_cited`

`citations.cited` is the **mean number of surviving cited sources per answer**, not the fraction of answers that cite. The distribution over the 106 scored items is `{0: 52, 1: 30, 2: 23, 4: 1}`; mean = 0.755. It is not "75% of answers cite something" — **52 of 106 (49%) cite nothing.** Any reader taking 0.75 as a coverage rate is off by a factor of two in the wrong direction. `report.md` prints it without a unit; it needs renaming to `mean_cited_sources`.

Of the 54 items with empty `magpie_cited`: 41 are guard deletions (which force `sources_used = []` at `src/answer.py:867`), 4 are backend errors, and only **9 are answers that shipped a claim with no citation** — matching `product_findings.zero_citation_answers: 9`.

### The model does cite; the harness drops it

`sources_used` was non-empty on **115/120** responses. Across the 75 shipped answers the model emitted **151** entries and the path filter at `src/answer.py:906-925` kept **96** — it discarded **55 (36%)**, and on **8 answers it discarded every entry**, leaving the answer looking uncited when it was not.

Entry shapes across all 120 responses:

| shape | n | survives matching? |
|---|---|---|
| verbatim path `/Users/…jpg` | 131 | yes |
| `"--- File 2: /Users/…jpg"` (full header echoed) | 23 | **no** |
| `"File 1: /Users/…jpg"` (header prefix retained) | 16 | **no** |
| bare index — `"1"`, `"file:2"`, `"file_2"`, `"File 2"` | 14 | **no** |
| invented URL (e.g. `https://files.keadibuku.com/receipts/2026-08-29_03:06_EDT.pdf`) | 10 | no (correctly) |
| vendor names, prose, receipt numbers | ~14 | no (correctly) |

**39 of the 55 drops are recoverable with a regex.** The system prompt says "each path copied verbatim from its `--- File N: <path> ---` header" and the model does exactly that — it copies the header. `_normalize_path_for_match` handles whitespace, URL-encoding and page suffixes but not a `File N:` prefix or a `--- File N:` prefix. Stripping a leading `(---)? File <n> :` before matching, and resolving a bare integer to the corresponding slot, would restore ~26% of all emitted citations at zero risk — these are not hallucinations, they are the model following the instruction slightly too literally.

### Why precision is low even after filtering

On the 96 surviving citations, precision against gold sources is **33/96 = 0.344** — better than the headline `0.184`, which is diluted by the 41 guard-zeroed items. It is still bad, and for the reason established in §2: the model cites slot 1 (91 of 101 in-prompt path citations), and under the reversal slot 1 is the worst-ranked file. **Citation precision is a direct readout of the ordering bug**, not an independent defect.

The judge's `hallucinated_citations: 0.44` is therefore double-counting two different things: genuine invention (the 10 fabricated URLs, the vendor-name entries) and correct-but-off-target citations of the distractor the model was steered to read.

I agree with the judge's recommendation that citation display should not ship. `rcpt-e-04-typed` remains the sharpest illustration: the answer "Master Card" is correct and the cited receipt's payment line reads `VISA CARD`.

---

## 8. Verification of the supervisor's context

| # | claim | verdict |
|---|---|---|
| 1 | 0/120 prompts contain any `golden_answer` verbatim | **Confirmed.** No prompt contains a `golden_answer`. A naive key-fact scan flags 4 items (`rcpt-en-01-*`, `rcpt-en-03-*`) but those golds are the bare counts `"5"` and `"6"`, which match incidental digits in file paths. No leakage. |
| 2 | Images attached (2-7/request); 97% of file text blocks empty | **Confirmed and strengthened.** 113 requests × 2 images, 7 × 7 images. 268/275 blocks empty (97.5%) — and the 7 non-empty blocks are harness "Context note" boilerplate, so **0/275 contain document text**. This is what makes §1 unconditional. |
| 3 | `src/answer.py:832` reverses file order; reverse in 113/120 | **Confirmed.** The 7 non-reversed are 4 backend errors (no retrieval) + 3 truncated fan-outs. |
| 4 | Of 39 answers quoting a decimal, 25 match the first-presented (worst-ranked) file and 0 match the best-ranked | **Independently corroborated by a stronger test.** I could not re-OCR the images, but the structural equivalent is unambiguous: of 37 shipped answers with gold in the last/best slot, **0 were correct or partial**, versus 5/13 when gold was in slot 1 (Fisher p=0.0008), and 91:10 citation preference for slot 1. |

**Where I disagree with the supervisor's framing:** the run brief treats the ~40% empty answers as an open question ("model failure or parse/grammar failure"). It is neither — it is a post-generation product guard (§1), and the answers were correct in 7 cases and partially correct in 4.

---

## 9. Golden-set issues raised by the judge — my assessment

| # | issue | agree? | notes |
|---|---|---|---|
| 1 | `rcpt-e-09` ambiguous referent — two Popular Book Co. AEON Shah Alam receipts on 06/03/18 (X51006008092 @ 30.70, X51006008093 @ 12.15) | **Agree** | Independently corroborated: `rcpt-nf-06-full` retrieved X51006008093 and returned `12.15`, so a second AEON Shah Alam slip with that total does exist. `gold_sources` silently picks X51006008092. Add a disambiguator (time or item) or accept both. |
| 2 | `rcpt-d-05` / `rcpt-d-10` — source file X51005719823 prints a `CASH` header and a `MASTER 46.20` tender block | **Agree, with a caveat** | I could not verify the image myself; the judge read it. Worth a human sign-off. But note this item is moot for *this* run: §3 shows the gold file never reached either `rcpt-d-05` prompt, so the divergent "Visa Card"/"Cash" answers are retrieval misses, not evidence of source ambiguity. |
| 3 | `key_facts` scoped wider than the question (`rcpt-b-08`, `rcpt-a-03`, `rcpt-b-07`, `rcpt-c-05`, `rcpt-e-07`) | **Strongly agree** | Verifiable from `golden.json` alone, and the set is internally inconsistent: `rcpt-c-05` ("12mm plywood which shop") has exactly one key fact, while `rcpt-b-08` ("sunquick oren recipt which shop") has two. 56/120 items carry >1 key fact. An `optional_facts` slot is the right fix. Note the judge cites `rcpt-c-05` as an instance of the problem — it is actually the correct exemplar. |
| 4 | Comparison items list the amounts but not the selection | **Strongly agree** | Directly verifiable: `rcpt-a-09` `['7.95','6.35']`, `rcpt-b-10` `['56.00','26.00','10/07/2017']`, `rcpt-c-09` `['9.60','6.70','17-03-2018']` — none names the winner; `rcpt-d-10` `['AA PHARMACY','46.20','34.80']` does and grades cleanly. Put the selection at index 0 on all comparison golds. |
| 5 | Grading conventions (question-supplied facts treated as established; ≥1 gold source satisfies `citation_ok`; comparison-with-no-amounts is `partial`) | **Agree on substance, disagree on placement** | Not a golden-set issue — it is an un-versioned judge-side convention, so a re-judge with a different model will not reproduce these grades. Convention (a) especially should be encoded in the data (a `supplied_facts` field on `rcpt-a-04`, `rcpt-e-04`) rather than applied at grading time. |

**Issue I would add (6):** the golden set cannot measure what it was built to measure in this configuration. 50/106 answerable items have `key_facts` consisting solely of numbers ≥ 100 and are therefore unanswerable regardless of model quality (§1.5). Any arm run with the groundedness guard active against an image-only corpus should be reported with that ceiling stated, or the guard should be disabled for the arm.

---

## 10. What to fix, in order

1. **Do not reverse file order on the vision path** (`src/answer.py:832`). Largest single lever: 0/37 vs 5/13 on shipped answers, p=0.0008. The Liu et al. rationale is about text position and does not transfer to attached images, where this model is primacy-biased 91:10.
2. **Make the groundedness guard aware of empty context** (`src/answer.py:869`). When `context_text` has no extractable text — as it does for every image-only file — the guard has no evidence to check against and must not fire. As shipped it deletes 34% of all answers, including 7 fully correct ones, and catches 0/10 of the fabrications it exists to catch. Give it a kill switch; `MAGPIE_STRICT_GROUNDING=0` does not disable it.
3. **Strip `File N:` prefixes before path matching** (`_normalize_path_for_match`). Recovers 39 of 55 dropped citations at no risk.
4. **Separate the wall-clock header from the evidence blocks** in the answer prompt, and stop feeding `2026-08-29`/`EDT` into rewriter keywords (costs ~19 points of hit@1). Replace the `not_found_topic` and citation examples in the system prompt with placeholders the model cannot copy verbatim — it is copying both today.
5. **Do not raise `top_k` for the vision path until the endpoint is fixed.** 4/7 seven-image requests returned HTTP 400 versus 0/113 two-image requests.
6. **Re-run before drawing any conclusion about model quality.** With fixes 1 and 2 alone the recoverable floor is 10 correct + 8 partial from answers this run already produced and then discarded — 3.3× the reported correct count, before the model gets any better at reading receipts.
