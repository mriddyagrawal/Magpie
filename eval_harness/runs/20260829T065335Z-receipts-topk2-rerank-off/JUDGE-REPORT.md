# Judge report — 20260829T065335Z-receipts-topk2-rerank-off

Across 120 questions Magpie produced 3 `correct`, 4 `partial`, 56 `wrong` and 43 `false_abstain` on the 106 answerable items, plus 4 `correct_abstain` and 10 `false_answer` on the 14 `not_found` probes — an end-to-end correct rate of 2.5% against a retrieval stack that put a gold source in the top-2 on 78% of questions. The single dominant pattern is not retrieval: it is that the answer stage does not bind its answer to the right file. In the 60-odd `wrong` cases the value Magpie returns is almost always a real number lifted verbatim off the *other* file in the top-2 window — RM 63.90 (Burger King) is offered as the Jiawei dinner total, the Mydin total and the Secret Recipe bill; 49.70 (a Super Terminal line) is offered as both the Rocku Yakiniku and the Super Terminal motor-oil total. Where it does read the right file it frequently picks the adjacent line: on the verified Vivopac invoice it returned the 49.50 exclusive-GST sub-total for the 2.97 GST line, and on the verified Saint Heart Pastry slip it returned 7.74 (Total Sales excluding GST) for the 0.46 GST line. Abstention is the second failure mode and is nearly all spurious: 43 declines, at least 34 of them with the gold file sitting at rank 1 or 2. `topk=2` with rerank off leaves exactly one distractor in the window, and that distractor wins far too often.

## Scoreboard

| Verdict | Overall | typed | full |
|---|---|---|---|
| correct | 3 | 1 | 2 |
| partial | 4 | 2 | 2 |
| wrong | 56 | 24 | 32 |
| false_abstain | 43 | 28 | 15 |
| correct_abstain | 4 | 2 | 2 |
| false_answer | 10 | 5 | 5 |
| **n** | **120** | **60** | **60** |

Answerable items only (n=106, excluding the 14 `not_found` probes): 3 correct, 4 partial, 56 wrong, 43 false_abstain.

Abstention discipline on the 14 `not_found` probes: 4 correct_abstain / 10 false_answer.

Phrasing split (correct / n over all 60 per arm): typed 1/60, full 2/60. The two arms differ far more in *how* they fail than in how often: typed produced 28 false abstentions to full's 15, while full produced 32 wrong answers to typed's 24. Terse typed queries get mangled by query rewriting (see below) and end in a decline; conversational full queries retrieve better and then get answered off the wrong file.

## Failure patterns

**1. Wrong-file reads inside a 2-item window (the largest bucket, ~35 of the 56 wrong).** With `topk=2` the answer stage sees the gold file and exactly one distractor, and routinely answers from the distractor.
- `rcpt-a-01-typed` / `rcpt-a-01-full` — the gold Tony Roma's receipt X51005442322 was rank 1 in both. The image reads `Subtotal 231.06 / 10% Srv Chg 23.10 / GST @6% 15.25 / Total 269.40`. Magpie answered 40.80 (typed) and RM 77.40 (full); 77.40 is the Sen Lee Heong total from the rank-2 distractor.
- `rcpt-c-01-typed` — gold Mydin receipt at rank 1; the image reads `TRI SHAAS SDN BHD / MYDIN MART SRI MUDA … Total After Rounding 109.90 / Cash 150.00 / CHANGE 40.10`. Magpie answered 63.90, again the Burger King total from rank 2.
- `rcpt-d-05-typed` / `rcpt-d-05-full` — the verified AA Pharmacy receipt X51005719823 tenders `TOTAL 46.20 / MASTER 46.20 / CHANGE 0.00`. Typed answered "Visa Card" (citing Green Lane + an OJC invoice), full answered "Cash" (citing a Super Seven slip). Neither read the file the question was about.
- `rcpt-a-08-full` — answered "TRI SHAAS SDN BHD" for *where did I buy carbon paper*. That is the legal entity printed above MYDIN MART SRI MUDA on X51005705759, a stationery-and-files run containing no carbon paper; the gold shop is Teo Heng Stationery & Books, whose receipt was cited alongside but not read.

**2. Adjacent-line extraction on the correct file (~8 of the wrong).** Retrieval and citation are right; the wrong row of the receipt is read. This is the most tractable failure.
- `rcpt-b-05-typed` — verified Vivopac invoice X51005568895 prints `Sub Total (Exclusive GST) : 49.50 / GST 6% : 2.97 / Rounded Total (RM): 52.45`. Magpie returned 49.50 as the GST.
- `rcpt-d-06-typed` — verified Saint Heart Pastry slip prints `Total Sales (Excluding GST) : 7.74 / Total GST : 0.46 / Total Sales (Inclusive of GST) 8.20`. Magpie returned "SR + GST @6% = 7.74". The `-full` variant returned 0.77, a figure that appears nowhere on the receipt.
- `rcpt-d-10-typed` — verified files give AA Pharmacy `TOTAL 46.20` and Green Lane `TOTAL 34.80`. Magpie reported "aa pharmacy: 34.80, Green Lane Pharmacy: 25.80" and inverted the conclusion; 25.80 is Green Lane's zero-rated (`z : 0%`) subtotal row.
- `rcpt-e-09-typed` — verified totals are AEON Shah Alam 30.70 and Empire 30.50. Magpie got AEON right but quoted Empire as 5.99, which is the `PB S/Tape 18x40 4IN1` line item on the *AEON* slip.

**3. Spurious abstention with the answer in hand (43 items).** In at least 34 of the 43, a gold source was at rank 1 or rank 2. `rcpt-a-07-typed`/`-full` (Uroko bill number), `rcpt-c-08-typed`/`-full` (TS Tools receipt no.), `rcpt-d-07-typed`/`-full` (GM Rack invoice no.) and `rcpt-e-06-typed`/`-full` (99 Speed Mart invoice no.) all declined with the gold file at rank 1 — identifier-shaped questions decline as a class. `rcpt-b-10-typed`/`-full` declined with *both* gold Evergreen Light receipts at ranks 1 and 2.

**4. Query rewriting destroys terse typed queries.** The rewriter substitutes topic and injects the wall-clock date as search terms. `rcpt-a-02-typed` ("f&p phamacy what date") became a search for "Farmers Drug Pharmacy store opening date" with `not_found_topic: "current date and time"`. `rcpt-c-09-typed` ("wan sheng march which one more expensive") became "March 2026 which is more expensive" — the vendor was dropped entirely and retrieval returned two unrelated receipts. `rcpt-c-10-typed`, `rcpt-d-09-typed` and `rcpt-nf-05-typed` were rewritten to bare timestamp queries ("current date and time Saturday 2026-08-29 03:18 EDT"). This is the mechanism behind typed's 28-vs-15 abstention gap.

**5. Enumeration is answered from the 2-item window, not the corpus (6 items).** `rcpt-en-01-typed` answered 4 and `rcpt-en-01-full` answered 6 against a gold count of 5, both from a two-file retrieval set — the counts are guesses, not counts. `rcpt-en-03-full` answered "January 4th" to *which days in January*, presenting one of six gold dates as complete. `rcpt-en-02` and `rcpt-en-03-typed` declined outright.

**6. Fabrication on absent vendors (10 of 14 `not_found` probes).** The failure is not hedging, it is confident invention. `rcpt-nf-01-full` reported a PappaRich spend of "44.00ZR on Anchor Flour and 15.40SR on Diamond Foil 7, for a total of 59.40ZR" — line items scraped off a Burger King receipt. `rcpt-nf-04-full` answered "Yes, the Moonlight Cake House receipt is available [1]." `rcpt-nf-05-typed` produced "golden key maker bill: 56.80" using the LA Stationery total. `rcpt-nf-06-full` gave 12.15 for Tanjongmas Bookcentre, which the images confirm is the total of a Popular Book Co. AEON Shah Alam slip. The 4 correct abstentions were on Coffee Bean & Tea Leaf (both arms), Tanjongmas (typed) and Platinum Racking (full) — no pattern separating them from the 10 misses.

**7. Infrastructure loss (4 items).** `rcpt-b-09-typed`, `rcpt-b-09-full`, `rcpt-c-10-full` and `rcpt-d-09-full` returned `HTTPStatusError: 400 Bad Request` from the local endpoint at `127.0.0.1:9400` with zero retrieval. These are graded `false_abstain` because the user received an empty answer, but they are a harness fault, not a product judgement — 4 of the 43 false abstentions should be discounted when comparing arms.

## Golden-set issues

The golden set is SILVER (114 model-authored, 0 human-verified). Sixteen source images were read for this run and every gold *value* they cover checked out — 269.40 (Tony Roma's), 193.00/VISA (OJC), 81.00/debit (Ben's), 46.20/MASTER (AA Pharmacy), 34.80 (Green Lane), 0.46 GST (Saint Heart), 30.00/31.80 Yamlube (Super Terminal), 109.90 (Mydin), 9.60 and 6.70 (Wan Sheng 17th/23rd), 2.97 GST (Vivopac), 30.70 and 30.50 (Popular AEON/Empire), 408.45/MASTER CARD (Super Seven). No gold value was overturned. The issues below are about item *construction*, and are logged in `golden_issues`.

1. **`rcpt-e-09` (both arms) — ambiguous referent.** The corpus contains two Popular Book Co. AEON Shah Alam receipts from 06/03/18 three minutes apart: X51006008092 at 18:01 for RM 30.70 and X51006008093 at 18:04 for RM 12.15. "The one at AEON Shah Alam" has two readings; the gold silently picks the 30.70 slip. Add a disambiguator or fold both into the gold answer.
2. **`rcpt-d-05` (and `rcpt-d-10`, which shares the file) — internally contradictory source.** X51005719823 prints a `CASH` mode header near the top *and* `TOTAL 46.20 / MASTER 46.20 / CHANGE 0.00` in the tender block. The gold follows the tender line and is right, but this file will produce defensible disagreement and deserves a human sign-off first.
3. **`rcpt-b-08` and kin — `key_facts` scoped wider than the question.** "sunquick oren recipt which shop" asks only for the shop, but `key_facts` carries both `99 SPEED MART` and `5.35`, so a fully responsive answer scores partial. Same shape at `rcpt-a-03`, `rcpt-b-07`, `rcpt-c-05` and `rcpt-e-07`. Scope `key_facts` to what is asked, or add an `optional_facts` slot.
4. **`rcpt-a-09` and kin — comparison items list the wrong facts.** On "which bill bigger dec or jan" the `key_facts` are the two amounts (7.95, 6.35), not the selection, so an answer that correctly names the December bill scores zero facts and lands in a gap between the rubric's `partial` and `wrong`. Comparison golds should carry the chosen item as key fact 0 — `rcpt-d-10` already does this correctly (`AA PHARMACY` first) and grades cleanly as a result. Same fix needed for `rcpt-b-10`, `rcpt-c-09`, `rcpt-e-09`.
5. **Grading convention used here, for reproducibility.** (a) A key fact restated in the question itself is treated as established — an answer is not penalised for declining to parrot "193.00" back at a question that supplied it. This affects `rcpt-a-04-full`, `rcpt-e-04-typed`, `rcpt-e-04-full`. (b) On multi-source items `citation_ok` is true if *at least one* gold source is cited. (c) A comparison answered with the right selection but no supporting amounts is `partial`; a "how much"/"when" question answered with no amount or date at all is `wrong`, since nothing of the answer was delivered.

## Deterministic disagreements

8 of 120 (93.3% agreement). All eight are matcher-precision failures in one of three shapes; in every case the file or the question text settles it.

| qa_id | deterministic | judge | why |
|---|---|---|---|
| `rcpt-a-04-full` | wrong | **correct** | "Card (VISA)" matches the verified `VISA CARD 193.00` tender line. The matcher wanted both key facts and the answer omits "193.00" — which the question itself supplied ("the 193.00 invoice from OJC Marketing"). |
| `rcpt-e-04-typed` | partial | **correct** | "Master Card" matches the verified `Payment Method MASTER CARD` on X51005746203; the 408 amount was given in the question ("super seven 408 paid by what card"). |
| `rcpt-e-04-full` | partial | **correct** | Same; the gold invoice is also cited here. |
| `rcpt-a-09-typed` | wrong | **partial** | "Dec" is the right selection and contradicts nothing; the matcher scored it wrong for missing the two supporting amounts. |
| `rcpt-a-09-full` | wrong | **partial** | "The 31 December bill came to more" is the right selection with both gold files cited. |
| `rcpt-d-10-typed` | partial | **wrong** | The matcher credited the literal string "34.80", but Magpie attributes 34.80 to AA Pharmacy (verified 46.20) and concludes Green Lane was dearer — an inverted conclusion. String presence is not fact presence when the attribution flips. |
| `rcpt-e-09-typed` | partial | **wrong** | The matcher credited "30.70", but the answer asserts Empire = 5.99 against a verified 30.50. A contradicted key fact overrides a matched one under the rubric's `partial` definition ("no contradiction"). |
| `rcpt-nf-07-full` | false_answer | **correct_abstain** | "No, there is nothing from Platinum Racking in your receipts" is a correct decline in prose. The matcher fires on `not_found=false` and misses prose abstention. Note it *does* catch the near-identical `rcpt-nf-03-full`, so the abstention detector is inconsistent, not absent. |

Net direction: the matcher is too strict on responsive short answers (4 upgrades) and too lenient on answers that contain a gold string in the wrong role (2 downgrades), plus one prose-abstention miss. The 2 downgrades are the more important defect — they mean deterministic `partial` overstates quality on comparison items.

## Verdict-independent observations

- **`topk=2` with rerank off is the binding constraint, not embedding quality.** Retrieval hit@1 is 0.78 and hit@5 would be 0.92, but only 2 candidates reach the answer stage. Every "adjacent-line" and most "wrong-file" errors are downstream of a 1-gold-1-distractor window. Before reading anything into the 0% correct rate, this arm should be re-run at a larger k; as configured it measures the window, not the model.
- **Citations are decorative.** `citation_precision` is 0.18 and `hallucinated_citations` 0.44. Concretely: `rcpt-e-04-typed` answers "Master Card" — the correct answer — while citing X51005763958, a Super Seven receipt whose payment line reads `VISA CARD`. The answer is right and the evidence contradicts it. Nine answers cite nothing at all while still asserting a value (`rcpt-a-01-typed`, `rcpt-a-09-typed`, `rcpt-c-07-full`, `rcpt-d-04-full`, `rcpt-e-07-typed`/`-full`, `rcpt-e-10-full` among them). Citation display should not ship until precision improves; today it would lend false confidence to wrong answers.
- **`not_found_topic` is frequently unrelated to the question.** `rcpt-a-10-full`, `rcpt-b-10-full` and `rcpt-c-09-typed` all carry `not_found_topic: "a landlord's emergency phone number"`; `rcpt-a-02-typed`/`-full`, `rcpt-c-02-full`, `rcpt-e-10-full` and `rcpt-nf-... ` variants carry `"current date and time"`. This looks like prompt-template leakage rather than a retrieval signal, and it lines up with the rewriter injecting `2026-08-29` and `EDT` into keyword lists on roughly a third of queries. Worth fixing before anything else here: it is cheap and it is upstream of both the abstention and rewriting failures.
- **Structured abstention and prose abstention disagree.** `rcpt-nf-03-full` and `rcpt-nf-07-full` decline correctly in prose while `not_found=false`; the run's own `product_findings.not_found_flag_missing: 1` undercounts this at 1. Any downstream consumer keying off the flag will mis-handle these.
- **Latency is not the problem.** p50 15.0s / p95 20.0s, and the two 12-candidate fan-outs (`rcpt-a-09-typed` at 48.3s, `rcpt-e-10-full` at 46.6s) both still produced wrong answers — more candidates without reranking bought time, not accuracy.
- **The solo gate never fired** (`fire_rate: 0.0`) across 120 questions, including the 14 absent-vendor probes where a gate would have been most useful. Ten of those 14 produced fabricated values instead.
