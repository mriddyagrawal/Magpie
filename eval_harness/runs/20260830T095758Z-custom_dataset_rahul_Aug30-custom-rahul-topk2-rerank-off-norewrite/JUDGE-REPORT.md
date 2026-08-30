# Judge report — 20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

Of the 104 answerable questions, 5 are correct (4.8%), 16 partial, 39 wrong and 44 false abstentions; of the 16 not_found probes, 9 are correct abstentions and 7 false answers. The single dominant pattern is that **retrieval works and reading does not**: the harness measures hit@1 = 0.93, and in nearly every failure I checked the gold file was sitting at rank 1 when Magpie either declined it (44 false abstains, 42% of answerable items) or answered from the rank-2 distractor instead (viz-01-full reads a Denmark value off chart_030.jpg, study-06-typed describes arxiv_018.png, phone-09-full quotes an infographic slogan at a neon beer sign). A third failure mode compounds both: 29 answers cite nothing at all and several of the rest cite a file they demonstrably did not read — viz-06-full states the right numbers from info_024.jpg while citing info_015.jpg, and study-07-full attaches receipt_025.jpg to a claim about an arXiv NMI plot. Three items (study-03-full, phone-05-typed, phone-11-full) are empty because the local model server returned HTTP 400; they are scored `false_abstain` but are infrastructure failures, not model behaviour.

## Scoreboard

| Verdict | Overall | Typed | Full |
|---|---|---|---|
| correct | 5 | 1 | 4 |
| partial | 16 | 8 | 8 |
| wrong | 39 | 23 | 16 |
| false_abstain | 44 | 20 | 24 |
| **answerable subtotal** | **104** | **52** | **52** |
| correct_abstain | 9 | 3 | 6 |
| false_answer | 7 | 5 | 2 |
| **not_found subtotal** | **16** | **8** | **8** |
| **total** | **120** | **60** | **60** |

Accuracy on answerable items: 4.8% correct, 20.2% correct-or-partial. Typed 1/52 correct, full 4/52 — the phrasing gap is within noise at these counts, though typed phrasings skew toward `wrong` (23 vs 16) and full phrasings toward `false_abstain` (24 vs 20). Abstention discipline on not_found probes: 9/16 correct.

## Failure patterns

**1. Abstention on a rank-1 gold file (44 items, the largest bucket).** Magpie sets `not_found` while the gold document is the top retrieval result. arch-07-typed and arch-07-full both decline with the two gold KLM tables at ranks 1 and 2; study-03-typed declines with deck_022.pdf as the *only* retrieved file; rcpt-01-full declines after a 12-result sweep led by the gold receipt_014.jpg. Whole categories collapse this way — 14 of 20 archive-scan items and 11 of 18 receipt items are false abstains. The retrieval stage is not the constraint here.

**2. Answering from the rank-2 distractor.** With top-k = 2 and reranking off, the second result is frequently unrelated, and the answerer often reads it instead of the gold. viz-01-full answers "Denmark, 0.81" — a value from chart_030.jpg, not the food-commodity chart it also retrieved, which shows cocoa lowest at 18.81. study-06-typed describes "normalized frequency distributions for magnitude and redshift" — that is arxiv_018.png at rank 2; arxiv_017.png at rank 1 is the fold schematic whose brackets read train / validation / test under columns 1+ to 3-, 4+/4-, 5+/5-. phone-09-full answers "ORDER, TIP WELL, WALK AWAY." from info_021.jpg when 1167908324.jpg shows a Dos Equis neon sign. phone-03-typed does the same thing with the same infographic.

**3. Adjacent-value misreads inside the correct file.** These are the most dangerous failures because they look like answers. viz-04-full reports 29% for the 2014 right-wing/far-right share; chart_037.jpg shows 20% in that band and 29% in the adjacent center-right band, so the model read one column across. phone-08-typed/full answer "0 trips" where screen_24243.jpg reads "free one-way ticket for every 8 trips traveled". study-08-full gives biosensors 30% and "MEMS and microfluidics at 40%" where the deck_027.pdf pie chart reads biosensors 8% and LC/MS 38%, with "MEMs and microfluidics" being a box on an entirely different slide.

**4. Query-echo and title-echo non-answers.** viz-06-typed returns the query string verbatim; arch-06-typed returns "Fort Morgan Sugar Factory"; study-02-typed and -full both return "C++ features"; study-04-typed and study-10-typed return "C++ Tutorials [1]". These state no key fact at all and are scored `wrong`. study-10-full is the extreme case: it dumps the raw OCR of the C++ operators pages (notes 14/15) when the type-casting content lives on notes 17/18/19, which retrieval never reached.

**5. Enumeration truncation.** Where a list is asked for, Magpie returns the first element or the wrong kind of element. viz-11-full answers "leopard seal and penguins" — diagram_011.jpg labels leopard seal, elephant seal and other seals, and penguins are a separate node. phone-05-full lists Universal Studios attractions instead of the seven exercises on screen_24509.jpg. phone-07-full is the one clean enumeration success: Crocs, Bud Light, Herbalife, Nautica and a genuinely-present "Lift Off" banner, all verified against 1080230428.jpg.

**6. Synthesis is at zero.** Every multi-file question either abstained or produced a single-file answer: viz-05-typed lists all three countries from chart_002.jpg as though they all appeared in chart_036.jpg (only Madagascar does), viz-09-full substitutes tourism's $43.4bn direct GVA for the $98bn total contribution, and arch-07, arch-09, rcpt-08, rcpt-09, study-11 and phone-11-full all abstained on at least one phrasing.

## Golden-set issues

The golden set held up well: all 16 files I opened confirmed the gold answer exactly, including the four values a wrong Magpie answer challenged (chart_037 = 20%, screen_24243 = 8 trips, deck_027 = 8% / LC-MS 38%, arxiv_017 = folds 1-3 train). No gold answer was overturned. Four items are worth the founders' attention as scoring artefacts rather than errors:

- **viz-06 (both phrasings)** — `key_facts` lists only "1.7 million", but info_024.jpg prints "1.7 MILLION" and "1 in 10 adults" as a single claim. Magpie's "1 in 10 adults" is faithful to the file and I scored it `correct`; a literal matcher scores it a miss. Add the variant.
- **phone-03 (both phrasings)** — `key_facts` is one all-or-nothing string, "Blitz Weinhard". Magpie's "Biltz" is a letter transposition that still drops "Weinhard", so it cannot earn partial credit under a single-fact item. Splitting into "Blitz" / "Weinhard" would make the near-miss visible.
- **viz-11 (both phrasings)** — gold_source is diagram_003.jpg but diagram_004 through diagram_011 are all listed as acceptable, and diagram_011.jpg is a near-identical copy carrying all three seal labels. Retrieval and citation scores for this pair depend on which duplicate surfaces. The duplicate set should be collapsed or explicitly documented as equivalent.
- **nf-07-full** — a taxonomy gap rather than a gold defect. The answer text is the word "No", which correctly declines, but the structured `not_found` flag was left unset. `false_abstain` already accepts abstaining prose; `correct_abstain` should too.

## Deterministic disagreements

11 of 120 (9.2%). Every one traces to the matcher scoring key-fact *presence* without checking whether the answer also asserts something the file contradicts, or without recognising a variant the file itself prints.

| qa_id | Deterministic | Judge | Why |
|---|---|---|---|
| viz-04-full | partial | wrong | Matcher credited "7%", "1979", "2014"; the answer also states 29% for 2014, which chart_037.jpg contradicts (20%). A contradiction outranks partial credit. |
| viz-05-typed | partial | wrong | Credited for containing "Madagascar", but the answer asserts Mauritania and Fiji also appear in both charts; chart_036.jpg lists Egypt, Tunisia, Madagascar, Mozambique. |
| phone-08-full | partial | wrong | Credited for "Group A"; "0 trips" contradicts the 8 trips printed on screen_24243.jpg. |
| viz-06-full | partial | correct | "1 in 10 adults" is the infographic's own wording for the 1.7 million key fact; the string matcher could not see the equivalence. |
| viz-10-full | partial | correct | The answer reproduces both caption sentences of diagram_018.jpg; the matcher missed "obcordate" because the answer says "the prefix 'ob'". |
| study-04-full | wrong | partial | The answer does state that the conditional operator is the ternary operator (key fact 0) before failing on syntax and example. |
| study-07-typed | wrong | partial | "Attribute SBM wins" is the correct comparative direction from arxiv_004.png, just with no numbers. |
| study-07-full | wrong | partial | Names both series, the winner, and the shared plateau at NMI 1.00 — three of five key facts — but phrases none of them as the gold strings. |
| phone-10-typed | wrong | partial | "KayC root beer" gets the brand; only the slogan is missing. |
| phone-10-full | wrong | partial | Same: brand correct, "The FIRST for THIRST" absent. |
| nf-07-full | false_answer | correct_abstain | The answer is the word "No" — an abstention in prose. Only the structured flag was missing. |

Net effect on the headline: the matcher and I agree on the shape of the run (both put correct at 3-5% and false_abstain at ~42%). The disagreements move three items out of `partial` into `wrong` and six out of `wrong`/`partial` into `partial`/`correct`, so they roughly cancel. Matcher precision is adequate for tracking; it should not be used to adjudicate individual regressions.

## Verdict-independent observations

- **Three hard errors.** study-03-full, phone-05-typed and phone-11-full returned HTTP 400 from `127.0.0.1:9400/v1/chat/completions` with zero retrieval. They are scored `false_abstain` but should be excluded from any answer-quality comparison against other arms; at 3/120 they are large enough to move a percentage point.
- **A stuck `not_found_topic` string.** Eleven items carry `not_found_topic: "a landlord's emergency phone number"` — a topic from no question in this dataset (viz-02-full, viz-03-full, arch-06-full, study-06-typed, study-06-full, study-08-full, study-09-full, rcpt-02-full, rcpt-07-full, rcpt-09-full, phone-05-full). It appears on both abstains and confident wrong answers, so it looks like leaked state in the answerer rather than a scoring field. Worth tracing before the next arm.
- **Citations are close to unusable.** 29 answers cite nothing; citation precision is 0.17 and 20% of citations are hallucinated. Several answers cite in the wrong direction — viz-06-full and viz-02-typed cite the distractor while answering (correctly or not) from the gold, and study-07-full cites a receipt photo on a question about an arXiv figure. Citation order also looks unreliable: many answers list the rank-2 file first.
- **Retrieval depth varies without an obvious trigger.** Most questions retrieved exactly 2 results, but ten retrieved 12 (arch-06-full, rcpt-01-full, rcpt-08-typed/full, phone-05-full, phone-07-typed, nf-06-full and others). The wider sweeps did not help — arch-06-full, rcpt-01-full and rcpt-08-full all abstained with the gold file in the list.
- **Inline citation markers leak into answer text.** viz-04-full ends "...in 1979, 7% did[2].", viz-10-typed ends 'at the apex"[2]', phone-06-typed answers 'Laganside 10K" [2]'. The bracket markers survive into the user-visible string while `magpie_cited` is empty, which suggests the citation list is being stripped after the text is generated rather than parsed out of it.
