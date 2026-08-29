# Judge report — 20260829T081855Z-receipts-topk3-rerank-off-norewrite

Across 120 answered questions this configuration produced **1 fully correct answer** (`rcpt-b-05-typed`, "Vivopac GST amount: RM 2.97") and 8 partials, against 62 wrong, 35 false abstentions, 9 correct abstentions and 5 false answers on the not-found set. The single most important pattern is that **this is not a retrieval failure**: the gold receipt was inside the top-3 for 94 of the 106 answerable questions (hit@3 = 88.7%, recall@3 = 83.0%), and it was at rank 1 for the overwhelming majority — yet the reader either declined outright (35 times), or emitted a number lifted from one of the *other two* files in the same prompt (the dominant wrong-answer mode). With `top_k=3`, `rerank=false` and `rewrite=false`, the pipeline is putting the right page in front of the model and the model is failing to read it. Two secondary findings matter for interpretation: 4 of the 35 "abstentions" are actually HTTP 400 errors from the local LFM server on widened enumeration prompts (a context-length crash, not model behaviour, exactly as the run notes predicted), and 2 of the 7 deterministic `false_answer` verdicts on the not-found set are in fact *correct* declines — the model answered the yes/no phrasing with the word "No", which the flag-based matcher cannot see.

## Scoreboard

| Verdict | Overall | Typed | Full |
|---|---:|---:|---:|
| correct | 1 | 1 | 0 |
| partial | 8 | 3 | 5 |
| wrong | 62 | 30 | 32 |
| false_abstain | 35 | 19 | 16 |
| correct_abstain | 9 | 5 | 4 |
| false_answer | 5 | 2 | 3 |
| **n** | **120** | **60** | **60** |

Answerable items only (n = 106): correct 1 (0.9%), partial 8 (7.5%), wrong 62 (58.5%), false_abstain 35 (33.0%).
Not-found items only (n = 14): correct_abstain 9 (64.3%), false_answer 5 (35.7%).
Phrasing made almost no difference to quality; the only signal is that typed queries abstain slightly more (19 vs 16) and full-sentence queries hallucinate slightly more (32 wrong vs 30).

## Failure patterns

### 1. Cross-contamination inside the top-3 prompt — the largest bucket (~30 of 62 wrong)
The model receives 3 receipts and answers from the wrong one. This is not a retrieval miss; the gold file is usually rank 1 and sometimes even cited correctly.
- `rcpt-a-01-full` — answered "RM 77.40". The Tony Roma's receipt (`X51005442322`, rank 1) prints `Subtotal 231.06 / 10% Srv Chg 23.10 / GST @6% 15.25 / **Total 269.40**`. 77.40 is the Sen Lee Heong total, which sat at rank 3 in the same prompt.
- `rcpt-d-01-full` — answered "RM 63.90". The Rocku Yakiniku receipt was rank 1; 63.90 is the Burger King KLIA total at rank 3.
- `rcpt-e-05-full` — answered "GST was $0.46". Great Zone's GST is 20.79; 0.46 is the Saint Heart Pastry GST from a different question's receipt.
- `rcpt-d-03-full` — cited the correct Kaison receipt (which reads "MyTOWN Shopping Centre") and then answered "AEON CO. (M) BHD".

### 2. Right file, wrong field (~15 of 62 wrong)
The reader lands on the correct receipt and picks the wrong line off it.
- `rcpt-c-06-typed` — answered 36.04. `X51005676535` shows `2 × CEMENT (50KG) @ 18.02 = **36.04**` as a line item, while `Total GST : 5.04`. It returned the line amount instead of the tax line.
- `rcpt-b-03-typed` — answered "30.00" to "how many litres". `X51005587261` reads `11.54 litre Pump # 01 / V-Power 97 RM 30.00 / 2.600 RM / litre`. It returned the ringgit figure as the litre count.
- `rcpt-d-09-typed` — answered 68.90 to "both bills together". The two 21/03/2018 Kedai Papan invoices are `CS00011014 = 68.90` (pasir halus) and `CS00011043 = 144.16` (besi Y 10); the sum is 213.06, and the second invoice even carries a handwritten "213.06" on its face.
- `rcpt-en-02-full` — called RM 68.90 "the largest" Kedai Papan invoice. It is the *smallest*; the retrieved trio was 68.90 / 84.80 / 144.16 and never contained the 312.70 one, but the model asserted a superlative over a 3-file window anyway.

### 3. False abstention with the answer on screen (35 items, 27 of them genuine model declines)
- `rcpt-a-01-typed` — `not_found: true`, empty answer, with `X51005442322` retrieved at rank 1 and "Total 269.40" printed in 30-point type.
- `rcpt-c-08-typed` / `rcpt-c-08-full` — both declined; the TS Tools receipt was rank 1 on both variants.
- `rcpt-e-06-typed` / `rcpt-e-06-full` — both declined; the Subang Bestari 99 Speed Mart receipt was rank 1 on both.
Of the 31 genuine declines, **27 had a gold source in the retrieved set**; only 4 (`rcpt-a-05-typed`, `rcpt-d-04-typed`, `rcpt-e-02-typed`, `rcpt-e-10-typed`) are excusable as retrieval misses.

### 4. Infrastructure crashes miscounted as abstention (4 items)
`rcpt-b-09-typed`, `rcpt-b-09-full`, `rcpt-c-10-full`, `rcpt-d-09-full` all carry `error: HTTPStatusError: 400 Bad Request` from `127.0.0.1:9400`, an empty `retrieved`, and `ranked_pre_gate` of 12. The `enumerate_lists` widener expanded these to 12 files and blew the 16384-token `local_n_ctx`. Three of the four had the gold source in the pre-gate ranking. These are graded `false_abstain` because the rubric has no error verdict, but they measure the context budget, not the reader — subtract them before quoting an abstention rate.

### 5. Non-answers: echo, fragment and hallucinated boilerplate (~10 of 62 wrong)
- `rcpt-e-01-typed` — answered with the query string itself, "florism de art total".
- `rcpt-d-07-typed` — answered "GM RACK ENTERPRISE [3] has 4 credit hours[1] and is offered every fall[2]", pure hallucinated course-catalogue text with fabricated citation markers, where invoice no. KNG01-1032303 was wanted.
- `rcpt-e-07-full` — answered "BANDINGKAN HARGA KAMI", a Malay price-comparison slogan scraped off an unrelated receipt.
- `rcpt-en-03-typed` — answered "CEDA APAN YEW CH JAN", a mangled OCR rendering of "KEDAI PAPAN YEW CHUAN", to a question about January dates.

### 6. Comparison and enumeration questions collapse (13 of 14 multi-file items missed)
Where the model does pick correctly it gives no figures (`rcpt-a-09`, `rcpt-e-09`, `rcpt-d-10-typed` — all partial). Where it must count, `top_k=3` caps it: `rcpt-en-01-typed/full` both answered "4" against a true count of 5 Wan Sheng receipts, which three retrieved files cannot support. `rcpt-c-09-full` picked the right run but invented the gap ("by 0.80 RM"; the files give 9.60 on 17-03-2018 vs 6.70 on 23-03-2018, a 2.90 gap).

### 7. Not-found lures work as designed, and the model mostly resists them (9/14 correct)
The two hard lure items were handled correctly — `rcpt-nf-03-*` (OldTown White Coffee lure) declined on both phrasings. The failures cluster on items where a lexically adjacent receipt exists: `rcpt-nf-06-typed` answered "Tanjongmas Book Centre" while citing a Kedai Buku New Acheivers receipt, and `rcpt-nf-06-full` answered "30.48" — a Popular Book Co. figure.

## Golden-set issues

Seven issues logged in `judge_verdicts.json`. Grouped:

1. **key_facts that appear verbatim in the question** — `rcpt-b-03-*` ("30.00" is in "petrol 30 ringgit") and `rcpt-d-02-*` ("100.00" is in "that RM100 fill-up"). These are matchable without reading anything, inflating partial credit; and in the reverse direction `rcpt-d-02-full` gave the fully correct litre figure (40.49, verified against `X51005724609`'s gold text and the question) yet scores `partial` purely for not echoing a number the asker supplied. Recommend dropping question-resident strings from key_facts.
2. **Comparison items whose key_facts omit the discriminator** — `rcpt-a-09-*`, `rcpt-e-09-*`, `rcpt-b-10-*`. The question is "which one is bigger"; key_facts list only the two amounts. An answer of "Dec" or "AEON Shah Alam" — the exact thing asked for, and verified correct against the files — matches zero key facts. `rcpt-d-10` does it right by including "AA PHARMACY" as a key fact; the others should follow.
3. **Yes/no phrasing on not-found items** — `rcpt-nf-03-full` ("Do I have a receipt from Coffee Bean & Tea Leaf?") and `rcpt-nf-07-full` ("Is there anything from Platinum Racking in my receipts?"). The correct answer is the word "No", i.e. a non-empty answer string, so any scorer keyed on the structured `not_found` flag will call a correct decline a `false_answer`. Either re-phrase these as open questions or teach the scorer to accept negative prose.
4. **Enumeration items are unanswerable at this top_k** — `rcpt-en-01-*` (count of 5), `rcpt-en-02-*` (max over 8 invoices), `rcpt-en-03-*` (6 January dates). With `top_k=3` no reader can succeed; the widener that would fix it is the same one that produces the HTTP 400s. These items are measuring the retrieval budget, not comprehension, and should be marked as such in the dataset.

Everything else checked out. I opened 18 source images and **found no factual error in any golden answer** — 269.40 (Tony Roma's), VISA CARD/193.00 (OJC), 109.90 (Mydin), 5.04/89.04 (Gin Kee), MASTER/46.20 (AA Pharmacy), 0.46/8.20 (Saint Heart), 11.54 L/RM30.00 (Chop Yew Lian), 2.97 (Vivopac), 68.90 + 144.16 = 213.06 (Kedai Papan 21/3), 9.60 vs 6.70 (Wan Sheng), 7.95 vs 6.35 (Cross Channel), 30.70 vs 30.50 (Popular AEON vs Empire) and 7.95 SUNWAY VELOCITY (Popular rubber bands) all match the files exactly. The silver→gold review can treat the values as sound; the issues above are all about *fact selection and phrasing*, not accuracy.

## Deterministic disagreements

10 of 120 (8.3%). Every one is a matcher-precision artefact, and all 10 move in the direction of the deterministic verdict being too harsh except two.

| qa_id | Deterministic | Judge | Why |
|---|---|---|---|
| `rcpt-a-09-typed` | wrong | partial | "Dec" is the correct discriminator (7.95 > 6.35, verified); key_facts contain only the amounts, so the matcher sees nothing. |
| `rcpt-a-09-full` | wrong | partial | Same; "The 31 December bill came to more" is correct and cites both gold receipts. |
| `rcpt-e-09-typed` | wrong | partial | Selects AEON Shah Alam, verified as the larger trip (30.70 vs 30.50); predicate is garbled ("more popular") but the choice is right. |
| `rcpt-e-09-full` | wrong | partial | "AEON Shah Alam" is the correct answer to the question as asked. |
| `rcpt-en-03-full` | wrong | partial | "January 3 and January 4" are 2 of the 6 correct Gin Kee dates, with no claim of completeness — incomplete, not contradictory. |
| `rcpt-nf-03-full` | false_answer | correct_abstain | "No" is the correct answer; the matcher only inspects the `not_found` flag. |
| `rcpt-nf-07-full` | false_answer | correct_abstain | Same. |
| `rcpt-b-03-typed` | partial | wrong | Matched on "30.00", but that string is in the question and, as an answer to "how many litres", asserts a litre figure contradicting the 11.54 on the file. |
| `rcpt-d-09-typed` | partial | wrong | Matched on "68.90", but the question asks for both bills together; 68.90 is one invoice, not the 213.06 sum. |
| `rcpt-d-05-full` | wrong | false_abstain | The output is the placeholder "(model output could not be parsed into Answer)" — a grammar/parse failure, not a wrong claim. No answer was delivered. |

Net effect on the headline: the deterministic scorer under-counts `partial` by 3 and `correct_abstain` by 2, and over-counts `wrong` by 3. Correct/incorrect totals are close enough that the run's verdict does not change, but the two `false_answer`→`correct_abstain` flips matter: the not-found abstention rate is 9/14, not 7/14.

## Verdict-independent observations

- **Citations and answers are decoupled.** In several items the model cited the right file and then answered from a different one (`rcpt-d-03-full`, `rcpt-c-05-full`, `rcpt-a-08-typed`, `rcpt-en-02-full`). Conversely, `rcpt-b-05-typed` — the one correct answer in the run — cited nothing at all, and `rcpt-d-02-full` produced the correct 40.49 litres while citing the Chop Yew Lian slip rather than the Bakalima one. Citation quality is not tracking answer quality in either direction, which means `citation_ok` should not be used as a proxy for correctness in this configuration.
- **The `enumerate_lists` widener is a latent crash.** It fired on 7 items (12 candidates each). Three succeeded (`rcpt-a-09-typed`, `rcpt-a-10-full`, `rcpt-e-10-full`); four returned HTTP 400 from the local server at `n_ctx=16384`. This reproduces the prior run's finding #4 exactly as the run notes predicted, and it is deterministic, not flaky — a 12-image prompt does not fit.
- **`rewrite=false` did its job.** No answer in this run shows the wall-clock date contamination that the Kimi rewriter injected previously; `rewritten_query` is byte-identical to `question` on all 120 rows. Retrieval at hit@3 = 88.7% is healthy. The bottleneck has moved entirely downstream of retrieval.
- **A genuine lexical trap in the corpus, correctly resolved by the gold.** `X51005719823` (AA Pharmacy) prints a standalone `CASH` line as a transaction-mode header near the top, while the tender block at the bottom reads `TOTAL 46.20 / MASTER 46.20 / CHANGE 0.00`. Magpie answered "Cash" on `rcpt-d-05-typed`. The gold ("went on the card") is right, but this receipt is a good regression case for any future cash-vs-card logic.
- **Multi-vendor mash-ups.** `rcpt-a-03-typed` answered "Secure Parking Syarikat Pernigaan Gin Kee" — two unrelated vendors welded into one string. This concatenation mode appears only when several receipts share the prompt, and is a distinct failure from picking the wrong file.
- **Same question, opposite failures across phrasings.** `rcpt-b-02` declined on the full phrasing and produced a query echo on the typed one; `rcpt-c-07` did the reverse. The reader is not stably deciding whether it has enough evidence, which suggests the abstention threshold — not retrieval — is the next thing to instrument.
