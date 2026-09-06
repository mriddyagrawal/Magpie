# Judge report — 20260906T090247Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

Of the 120 answered questions, 6 are `correct`, 17 `partial`, 36 `wrong` and 45 `false_abstain`; on the 16 `not_found` probes Magpie declined correctly 9 times and invented an answer 7 times. That is a 5.8% strict-correct rate on the 104 answerable items. The single dominant pattern is **abstention on evidence that was already in hand**: in 45 of 104 answerable questions (43%) Magpie set the structured `not_found` flag while the gold source sat at retrieval rank 1 — arch-03, arch-07, arch-08, arch-09 and arch-10 abstained on both phrasings with the correct scan retrieved first every time. The archive and receipt tiers are effectively non-functional in this configuration (15/20 and 12/18 abstains). Where Magpie does answer, the second failure mode is that the rank-2 neighbour document supplies the content: with `topk2` and reranking off, an unfiltered distractor is half the context, and answers such as "Denmark, 0.81" (viz-01-full, from chart_030) or "MEMS and microfluidics at 40%" (study-08-full, from the wrong slide of the right deck) are read out of it. Full phrasing beats typed phrasing on strict correctness 5 to 1, but mostly by abstaining more politely rather than by answering better. I opened 18 source files to settle disputed items; every gold fact I checked held, so the errors are Magpie's, not the golden set's.

## Scoreboard

| Verdict | Overall | Typed (n=60) | Full (n=60) |
|---|---|---|---|
| correct | 6 | 1 | 5 |
| partial | 17 | 8 | 9 |
| wrong | 36 | 22 | 14 |
| false_abstain | 45 | 21 | 24 |
| correct_abstain | 9 | 3 | 6 |
| false_answer | 7 | 5 | 2 |
| **total** | **120** | **60** | **60** |

Answerable items only (104: 52 typed, 52 full):

| Metric | Overall | Typed | Full |
|---|---|---|---|
| strict correct | 6 (5.8%) | 1 (1.9%) | 5 (9.6%) |
| correct + partial | 23 (22.1%) | 9 (17.3%) | 14 (26.9%) |
| abstention rate | 45 (43.3%) | 21 (40.4%) | 24 (46.2%) |
| wrong rate | 36 (34.6%) | 22 (42.3%) | 14 (26.9%) |

`not_found` items only (16: 8 typed, 8 full): 9 `correct_abstain` (56.3%), 7 `false_answer`. Typed splits 3/5, full splits 6/2 — the terse one-word probes ("chem notes", "python notes") are far more likely to pull a plausible-looking file out of the corpus than the conversational ones.

By category (answerable only): charts + infographics + diagrams 3 correct / 4 partial / 8 wrong / 7 abstain (22); archive scans, documents and French tables 0 / 2 / 3 / 15 (20); study material — notes, decks, arXiv figures 0 / 2 / 13 / 7 (22); receipts 0 / 2 / 4 / 12 (18); phone photos, screenshots and scene text 3 / 7 / 8 / 4 (22).

## Failure patterns

**1. Abstention with the answer at rank 1 (45 items — the largest bucket).** Magpie set `not_found: true` while the gold document was the top retrieval hit. `arch-03-typed` / `arch-03-full`: `scan_fybg0227.pdf` was retrieved at rank 1 and the letter's own summary line gives total attendance at the 25th annual meeting as 849. `arch-08-typed` / `arch-08-full`: `scan_psjf0226.pdf` at rank 1, which is where the 2.64 hazard ratio and the 1.11–6.31 interval are printed. `viz-05-full`: both gold charts (`chart_002.jpg`, `chart_036.jpg`) were retrieved at ranks 1 and 2 — I opened both and Madagascar is plainly the only country on both, at 0.21% and 58.09% — yet the run declined. The pattern is not a retrieval failure; it is a read-or-answer failure downstream of retrieval.

**2. Rank-2 contamination — right question, neighbour's document (about 10 items).** `viz-01-full` answers "Denmark, 0.81" and cites `chart_030.jpg`, the rank-2 hit, while the rank-1 `chart_001.jpg` (the food-commodity index, cocoa 18.81) is the file the typed twin read correctly. `study-06-typed` describes "normalized frequency distributions for magnitude (mag) and redshift (z) across DES, GZ_notrain, GZ_train" — that is `arxiv_018.png`, the rank-1 neighbour, not the fold-split figure. `study-08-full` gives "biosensors 30%, MEMS and microfluidics 40%": I opened `deck_027.pdf` and the pie chart on its final page reads Biosensors 8%, LC/MS 38%, ELISA 18%, LC/UV 18%, other screening 12%, electrophoresis 6% — "MEMs and microfluidics" is a box on the *first* slide of the same deck, so the deck was right and the page was wrong.

**3. Adjacent-cell and adjacent-series misreads inside the correct file (about 6 items).** `viz-04-full` reports 29% for right-wing to far-right in 2014; `chart_037.jpg` shows the 2014 row as 7 / 25 / 9 / **29** / **20** / 7, so 29% is the center-right segment sitting immediately to the left of the correct 20%. `arch-05-typed` claims Coca-Cola and diet Coke both hold "about 35 milligrams"; `doc_357.jpg` says in one sentence that six fluid ounces of salted tomato juice has 660 mg "while the same size serving of diet Coke has 35 milligrams or less" — the second half of the sentence was carried over onto the first subject. `phone-08-typed` / `phone-08-full` answer "0 trips"; `screen_24243.jpg` reads "Get a free* one-way ticket for every 8 trips traveled".

**4. Degenerate non-answers — the query or a document title returned as the answer (8 items).** `viz-06-typed` returns the literal string "diabetes australia infographic annual cost" while citing the correct `info_024.jpg`, which prints $6 BILLION in 40-point type. `arch-06-typed` returns "Fort Morgan Sugar Factory", the subject of the question. `study-02-typed` / `study-02-full` return "C++ features", the heading of the rank-1 page. `study-04-typed` and `study-10-typed` return "C++ Tutorials [1]". These are graded `wrong` rather than `partial` because no fact is asserted at all.

**5. Enumeration collapse (5 items).** `viz-11-full` names "leopard seal and penguins"; the food-web figure labels leopard seal, elephant seal and other seals, and penguins are a separate node — one of three targets found, plus a category error. `viz-05-typed` runs the opposite way and over-lists: it returns all three countries from `chart_002.jpg` ("Mauritania, Fiji, Madagascar") when only Madagascar appears in `chart_036.jpg` as well, turning a set intersection into a copy of one operand. `phone-05-typed` returns a list of turkey call names from an unrelated screenshot while `phone-05-full`, the same question in prose, returns all seven exercises perfectly.

**6. `not_found` lexical traps caught exactly the distractors the golden set predicted (7 false answers).** `nf-06-typed` cites `arxiv_027.png` — the "CE loss + Dice loss" diagram the golden item names as its known distractor. `nf-04-typed` / `nf-04-full` return C++ notes for a Python request. `nf-08-full` answers "Yes, there are two PDF files named electric-charge-and-field-12.pdf and CseGyan-Cpp-Notes-11.pdf" for handwritten chemistry notes — the physics and C++ series, exactly the two the golden answer rules out.

**7. Cross-photo bleed.** `phone-03-typed` (beer-carton hat) and `phone-09-full` (neon beer sign) both return "ORDER, TIP WELL, WALK AWAY" — the same string from some third bar photo, surfacing on two unrelated questions.

## Golden-set issues

Every golden fact I checked against the file held: `chart_010`, `chart_037`, `chart_002`, `chart_036`, `info_024`, `info_013`, `diagram_003`/`diagram_011`, `arxiv_017`, `arxiv_004`, `doc_357`, `deck_027`, `electric-charge-and-field-9`, `bad_receipt_014`, `screen_24243`, `scene_40882a42d8d66b36`, `scene_4952cc3277229b18` and `1007129816` all match their golden answers exactly, despite every item carrying `human_verified: false`. The problems below are scoring-surface problems, not factual errors.

- **`phone-06-typed`, `phone-06-full` — over-specified `key_facts`.** Both phrasings ask only for the race name on the bib. `key_facts` also requires "Pure Running", the timing sponsor's logo, which is genuinely printed on the number card but is not what the question asks. An answer that fully and correctly answers the question ("Laganside 10K") is capped at `partial`.
- **`arch-04-typed`, `arch-04-full` — over-specified `key_facts`.** Both phrasings ask for the balance due; `key_facts` also requires invoice number "A-3088". Magpie's "55.25" is the complete answer to the question asked and still scores `partial`.
- **`viz-06-full` — key fact has an equivalent printed form.** `info_024.jpg` prints "1.7 MILLION" and "1 in 10 adults" as one affected-population figure, and the golden answer itself joins them with "or". The `key_facts` entry accepts only "1.7 million", so an answer using the infographic's other phrasing reads as a miss. I graded this `correct`; the entry should accept either form.
- **`viz-11-typed`, `viz-11-full` — duplicate images in the corpus.** `gold_sources` names `diagram_003.jpg`, but `diagram_011.jpg` (listed under `acceptable_sources`) is a visually identical copy of the same Antarctic food-web figure — I opened both and they are indistinguishable. `acceptable_sources` lists eight such neighbours. Any citation metric over this item measures which duplicate the index happened to return, not correctness.
- **General note for the silver→gold review:** several `key_facts` lists mix the *answer* with *scene description* (e.g. `study-06`'s "one blue and one green highlighted bar per column, stepping down per fold"). These are unobjectionable as gold prose but make a deterministic fact matcher structurally unable to score `correct`, which is part of why the deterministic and judge counts diverge on the study tier.

## Deterministic disagreements

13 of 120 (10.8%). Four times the matcher was too lenient — it found a gold substring inside a sentence that contradicts the gold — and nine times too harsh.

Judge stricter than deterministic (4):

| qa_id | deterministic | judge | why |
|---|---|---|---|
| viz-04-full | partial | wrong | Matched "7%", "1979", "2014", but the answer's 29% for 2014 is `chart_037.jpg`'s center-right column; the right-to-far-right value is 20%. A contradiction, not an omission. |
| viz-05-typed | partial | wrong | Matched "Madagascar", but the answer also names Mauritania and Fiji as appearing in both charts, and `chart_036.jpg` contains neither. |
| arch-05-typed | partial | wrong | Matched "35 milligrams" — inside the sentence "both containing about 35 milligrams", which directly contradicts the leaflet's 660 mg for tomato juice. |
| phone-08-full | partial | wrong | Matched "Group A", but "0 trips" contradicts the "every 8 trips traveled" printed on `screen_24243.jpg`. |

Judge more lenient than deterministic (9):

| qa_id | deterministic | judge | why |
|---|---|---|---|
| viz-06-full | partial | correct | "1 in 10 adults" is the infographic's own equivalent of "1.7 million"; the golden answer states both as one fact. |
| viz-10-full | partial | correct | "the prefix 'ob' indicates the blade is widest near the apex" satisfies the "obcordate" key fact without using the literal token; phrasing-blind grading. |
| viz-09-typed | wrong | partial | No figures given, but the comparison direction (tourism far bigger) is right and contradicts nothing. |
| study-07-typed | wrong | partial | "Attribute SBM wins" is the correct conclusion for `arxiv_004.png`, just unquantified. |
| study-07-full | wrong | partial | Names both series and the saturation near NMI 1.00 correctly; only "outperforms across all Pin/Pout" is loose (the curves meet at Pin/Pout 5). |
| phone-03-full | wrong | partial | "Biltz" is a letter transposition of the "Blitz Weinhard" printed on the hat panels, not a different brand. |
| phone-10-typed | wrong | partial | "KayC root beer" gets the brand from `scene_40882a42d8d66b36.jpg`; only the "FIRST for THIRST" slogan is missing. |
| phone-10-full | wrong | partial | Same: brand plus the "Delicious Root Beer" strapline, missing only the slogan line. |
| nf-07-full | false_answer | correct_abstain | The answer is "No" — a correct decline in prose. The deterministic rule keys on the structured `not_found` flag, which was not set, so a right answer scored as a fabrication. |

Matcher-precision takeaway: substring matching on `key_facts` is unsafe when the surrounding sentence can negate or re-attribute the number (the four stricter overturns), and it under-credits paraphrase and near-miss OCR (the nine lenient ones). The `nf-07-full` case is a separate rule bug — prose declines on `not_found` items should count as `correct_abstain` the same way prose declines on answerable items already count as `false_abstain`.

## Verdict-independent observations

- **`not_found_topic` is leaking a stale value.** Twelve rows carry `not_found_topic: "a landlord's emergency phone number"`, a phrase that appears nowhere in this dataset — among them `viz-02-full`, `viz-03-full` and `arch-06-full`. On other rows the field is a sensible restatement of the question. Whatever populates it is falling back to a fixture or to a previous session's value; anything downstream that keys on `not_found_topic` (UI copy, follow-up prompts) will show a stranger's landlord to the user.
- **Half of all answers cite nothing.** 67 rows answered without setting `not_found`; 32 of those (48%) returned an empty `magpie_cited`. Several are otherwise perfect — `phone-05-full` lists all seven exercises correctly and `viz-10-full` is fully right, both with no citation. Bracket markers such as `[1]`, `[2]` still appear inside the answer text (`viz-04-full`, `viz-09-full`, `study-09-full`), so the model is generating citation references that never reach the structured field.
- **There is a deeper-retrieval path, and it does not help.** 104 rows retrieved exactly 2 candidates and 6 retrieved 1, all at the fixed scores 0.01639/0.01613, consistent with `topk2` and reranking off. But 10 rows retrieved **12**: `arch-06-full`, `study-03-full`, `rcpt-01-full`, `rcpt-08-typed`, `rcpt-08-full`, `phone-05-typed`, `phone-05-full`, `phone-07-typed`, `phone-11-full`, `nf-06-full`. Seven of those ten still ended in an abstain, and four of them are the four slowest rows in the run. Three are also the only rows where the keyword extractor fired (`["pH"]`, `["kW"]`, `["D.I"]`). This is worth pinning down before the next paired comparison: `topk` is not in fact held at 2 for every question, which weakens the one-knob-per-comparison guarantee for this run.
- **Latency does not predict quality.** The four slowest rows — `phone-11-full` 51.1 s, `phone-05-typed` 45.6 s, `phone-07-typed` 44.6 s, `phone-05-full` 42.6 s — are a partial, a wrong, an abstain and one of the run's six correct answers. The three fastest — `nf-02-full` 3.3 s, `phone-03-full` 3.8 s, `rcpt-07-full` 4.1 s — are a correct abstain, a partial and a false abstain. Time spent correlates with the 12-candidate retrieval path, not with getting it right.
- **The corpus contains duplicate images.** `diagram_003.jpg` and `diagram_011.jpg` are the same Antarctic food-web figure; the golden set lists eight further `diagram_00N.jpg` files as acceptable for the same question. Deduplicating before indexing would free retrieval slots currently spent on copies — which matters when `topk` is 2.
- **Phrasing sensitivity is real but not monotone.** 22 of the 60 pairs got different verdicts across their two phrasings. Full phrasing wins outright on `phone-05` (perfect vs turkey-call list), `phone-07` (perfect vs abstain) and `phone-01` (correct vs wrong file); typed phrasing wins on `viz-01` (correct vs wrong chart) and on `arch-05` / `rcpt-02` (an attempt vs an abstain). Single-phrasing evaluation of this system would be unstable at roughly the ±1/3 level.
