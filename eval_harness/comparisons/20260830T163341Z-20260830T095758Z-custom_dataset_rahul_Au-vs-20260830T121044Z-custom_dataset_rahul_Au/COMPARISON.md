# Comparison: 20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite  vs  20260830T121044Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-rewrite

- Generated: 20260830T163341Z  ·  pairing mode: **full** (coverage 100%, n=120)
- Changed axes: **config** (knobs: rewrite)
- Params diff: `rewrite`: False → True

## Paired outcomes (A = baseline)

| Metric | A | B | Δ | discordant | McNemar p |
|---|---|---|---|---|---|
| answer good (authoritative) (judge) | 0.1167 | 0.1917 | +0.075 | 3A / 12B | 0.03516 |
| answer good (deterministic) | 0.0917 | 0.1083 | +0.0167 | 4A / 6B | 0.75391 |  *(not decision-grade: p >= 0.05 - split is coin-consistent)*
| answer good (judge) | 0.1167 | 0.1917 | +0.075 | 3A / 12B | 0.03516 |
| retrieval hit@1 (end_to_end+ranked_pre_gate) | 0.9327 | 0.8558 | -0.0769 | 9A / 1B | 0.02148 |
| abstained | 0.4333 | 0.4583 | +0.025 | 9A / 12B | 0.66362 |  *(not decision-grade: p >= 0.05 - split is coin-consistent)*

## Verdict transitions (A → B)

- wrong -> false_abstain: 5
- wrong -> correct: 5
- false_answer -> correct_abstain: 4
- wrong -> partial: 4
- false_abstain -> wrong: 4
- partial -> correct: 3
- partial -> false_abstain: 3
- partial -> wrong: 3
- correct_abstain -> false_answer: 2
- false_abstain -> partial: 2
- correct -> wrong: 1

## Slices

| Slice | A | B | Δ | discordant | McNemar p |
|---|---|---|---|---|---|
| phrasing=full | 0.1667 | 0.25 | +0.0833 | 0A / 5B | 0.0625 |  *(not decision-grade: p >= 0.05 - split is coin-consistent)*
| phrasing=typed | 0.0667 | 0.1333 | +0.0667 | 3A / 7B | 0.34375 |  *(not decision-grade: p >= 0.05 - split is coin-consistent)*
| answer_type=enumeration | 0.0833 | 0.0833 | +0.0 | 0A / 0B | 1.0 |  *(not decision-grade: < 5 discordant)*
| answer_type=extractive | 0.0571 | 0.1571 | +0.1 | 1A / 8B | 0.03906 |
| answer_type=not_found | 0.5625 | 0.6875 | +0.125 | 2A / 4B | 0.6875 |  *(not decision-grade: p >= 0.05 - split is coin-consistent)*
| answer_type=synthesis | 0.0 | 0.0 | +0.0 | 0A / 0B | 1.0 |  *(not decision-grade: < 5 discordant)*

## Latency (paired): mean Δ -3.11s, median Δ -0.75s over n=120

## Answer regressions (good in A → bad in B) — 3

- **nf-01-typed** (typed) — correct_abstain → false_answer: 'passport scan'
    - gold: 'No - there is no passport, driving licence, or national ID document anywhere in these files.' · A: '' · B: '31.00'
- **nf-05-typed** (typed) — correct_abstain → false_answer: 'transcript'
    - gold: 'No - there is no academic transcript, exam result slip, or degree certificate in these files.' · A: '' · B: '31.00'
- **viz-01-typed** (typed) — correct → wrong: 'food commodity price index chart cheapest one'
    - gold: "Cocoa, at 18.81. In the Our World in Data chart 'Long-term price index in food commodities, 1850-2015', cocoa has the lowest index value of the fourteen commodities shown; lamb is highest at 103.7." · A: 'The cheapest commodity is Cocoa at 18.81' · B: 'Cheerios cereal'

## Answer wins (bad in A → good in B) — 12

- **arch-04-full** (full) — partial → correct: "On the invoice for mailing and labeling the Great Western '70 Magazine, what was the balance due after the advance payment was applied?"
    - gold: "On the Laman for Letters, Inc. invoice A-3088 dated 8-19-70 for mailing the Great Western '70 Magazine, charges came to 325.25; after the 270.00 advance payment received August 17, the balance due was $55.25." · A: '55.25' · B: '55.25'
- **nf-02-typed** (typed) — false_answer → correct_abstain: 'wedding invitation'
    - gold: 'No - there is no wedding or party invitation card in these files.' · A: 'wedding invitation' · B: ''
- **nf-06-typed** (typed) — false_answer → correct_abstain: 'training loss curve'
    - gold: 'No - no figure plots loss against epoch, iteration, or training step.' · A: 'training loss curve' · B: ''
- **nf-07-typed** (typed) — false_answer → correct_abstain: 'covid vaccination certificate'
    - gold: 'No - there is no COVID-19 vaccination certificate or test result in these files.' · A: "Australia's Coverage Target is 95%" · B: ''
- **nf-08-typed** (typed) — false_answer → correct_abstain: 'chem notes'
    - gold: 'No - there are no handwritten chemistry notes; the handwritten notes are C++ and physics (electrostatics) only. Chemistry content does exist elsewhere in the files, but as scanned reports and slide decks, not as your notes.' · A: 'Electric field' · B: ''
- **phone-02-full** (full) — wrong → correct: "In the photo where I'm holding up a small blue Intel mini-PC box, what is the exact model number printed on it?"
    - gold: 'It\'s an Intel NUC, model NUC5i7RYH. The blue retail box has the tagline "The Shape that Fits the Future." and carries Intel Core i7 and Iris Graphics badges.' · A: 'palm' · B: 'NUC5i7RYH'
- **phone-02-typed** (typed) — wrong → correct: 'pic of the tiny intel box in its box, which model was it'
    - gold: 'It\'s an Intel NUC, model NUC5i7RYH. The blue retail box has the tagline "The Shape that Fits the Future." and carries Intel Core i7 and Iris Graphics badges.' · A: 'palm' · B: 'NUC5i7RYH'
- **phone-06-full** (full) — partial → correct: 'What race name is printed on the bib of the runner in the yellow vest who is flexing and holding a water bottle?'
    - gold: "His race bib says LAGANSIDE 10K, with a PURE RUNNING logo on the left side of the number card. He's in a yellow and brown striped vest with a stag-head crest, holding a water bottle and flexing after the race." · A: 'Laganside 10K' · B: 'Laganside 10K'
- **phone-06-typed** (typed) — partial → correct: 'runner in the yellow vest flexing with a water bottle - what race bib'
    - gold: "His race bib says LAGANSIDE 10K, with a PURE RUNNING logo on the left side of the number card. He's in a yellow and brown striped vest with a stag-head crest, holding a water bottle and flexing after the race." · A: 'Laganside 10K" [2]' · B: 'Laganside 10K" [2]'
- **viz-01-full** (full) — wrong → correct: 'In that long-term food commodity price index chart, which commodity had the lowest index value, and what was it?'
    - gold: "Cocoa, at 18.81. In the Our World in Data chart 'Long-term price index in food commodities, 1850-2015', cocoa has the lowest index value of the fourteen commodities shown; lamb is highest at 103.7." · A: 'Denmark, 0.81' · B: 'Cocoa, 18.81'
- **viz-02-full** (full) — wrong → correct: 'In the chart showing the share of people who agree vaccines are important for children, which country had the lowest share?'
    - gold: 'South Korea, at 72%. In the 2018 Our World in Data chart of the share agreeing that vaccines are important for children, South Korea is the lowest of the five countries shown, just below Armenia at 73%; the United Arab Emirates is highest at 94%.' · A: 'Spain' · B: 'South Korea'
- **viz-06-typed** (typed) — wrong → correct: 'diabetes australia infographic annual cost'
    - gold: "The 'Diabetes in Australia' infographic puts the annual economic cost at $6 billion, and says diabetes affects 1.7 million Australians, or 1 in 10 adults." · A: 'diabetes australia infographic annual cost' · B: '6 billion'

## Retrieval hit@1 regressions — 9

- **arch-05-typed** (typed) — partial → false_abstain: 'coke sodium leaflet tomato juice vs diet coke mg per serving'
    - gold: "The Coca-Cola USA leaflet 'You Asked About Sodium in Soft Drinks' says a six-fluid ounce serving of tomato juice processed with added salt has 660 milligrams of sodium, while the same size serving of diet Coke has 35 milligrams or less." · A: 'Coca-Cola and Diet Coke have similar sodium levels per serving, both containing about 35 milligrams of sodium, which is less than the 40% of total daily sodium recommended by the Food and Drug Adminis' · B: 'Not found'
- **phone-09-typed** (typed) — false_abstain → false_abstain: 'dark bar photo neon beer sign over the arcade machines which beer'
    - gold: 'The neon sign is a Dos Equis "XX" IMPORTED BEER sign, glowing red and orange on a purple painted wall. Below it are three lit-up upright arcade / video gambling machines, with a man in a pale short-sleeved polo standing at the leftmost one.' · A: '' · B: ''
- **rcpt-08-full** (full) — false_abstain → wrong: 'Adding up all my Mr D.I.Y. receipts, how much did I spend there in total?'
    - gold: 'There are three Mr D.I.Y. receipts and together they come to RM 101.90: RM 33.90 at Mr DIY Tesco Terbau (12-01-19, chopping board, sprayer, windshield cleaner, BOPP tape), RM 30.90 at Mr DIY Tesco Putra Nilai (16-11-18, car wash, wax, Kleenso, handkerchief) and RM 37.10 at Mr DIY Tesco Mutiara Damansara (14-03-18, scouring pads, scissors, trailing socket).' · A: '' · B: '33.90'
- **rcpt-08-typed** (typed) — wrong → false_abstain: 'how much did i spend at mr diy altogether'
    - gold: 'There are three Mr D.I.Y. receipts and together they come to RM 101.90: RM 33.90 at Mr DIY Tesco Terbau (12-01-19, chopping board, sprayer, windshield cleaner, BOPP tape), RM 30.90 at Mr DIY Tesco Putra Nilai (16-11-18, car wash, wax, Kleenso, handkerchief) and RM 37.10 at Mr DIY Tesco Mutiara Damansara (14-03-18, scouring pads, scissors, trailing socket).' · A: '9.00' · B: ''
- **study-04-typed** (typed) — wrong → false_abstain: 'cpp notes conditional operator ternary syntax question mark colon'
    - gold: 'The notes say the conditional operator is also known as the ternary operator, symbol ( ? : ), and behaves like a shorter if-else. The syntax written down is: variable = Expression ? true statement : false statement; with the example int a = (b > c) ? b : c;' · A: 'C++ Tutorials [1]' · B: ''
- **viz-02-typed** (typed) — wrong → wrong: 'vaccines important for children chart lowest country'
    - gold: 'South Korea, at 72%. In the 2018 Our World in Data chart of the share agreeing that vaccines are important for children, South Korea is the lowest of the five countries shown, just below Armenia at 73%; the United Arab Emirates is highest at 94%.' · A: 'Australia' · B: 'Tweet #2'
- **viz-07-typed** (typed) — false_abstain → false_abstain: 'condom infographic french town population 1806'
    - gold: "The town of Condom, on the Via Podiensis in France, saw its population fall from 7,298 in 1806 to 7,099 in 2009. The same panel of that condoms infographic notes the town's Condom Cathedral was erected in 1506." · A: '' · B: ''
- **viz-08-typed** (typed) — wrong → wrong: 'millenial myths infographic smartphone percentage'
    - gold: "Under 'Myth 5: Millennials are always distracted by technology', the infographic says over 90% of millennials own a smartphone and 65% use it as a way to feel connected to others." · A: '7' · B: '31.00'
- **viz-10-typed** (typed) — partial → wrong: 'leaf diagram cordate obcordate what ob means'
    - gold: "In that leaf shape diagram, 'cordate' means a heart-shaped leaf, and the prefix 'ob' in 'obcordate' refers to a blade that is widest near the apex. The diagram also labels the two parts of the leaf: the blade and the petiole." · A: 'ob means the widest part of the leaf is at the apex"[2]' · B: 'ob means outer'

## Retrieval hit@1 wins — 1

- **rcpt-05-typed** (typed) — wrong → wrong: 'that shop where i bought loads of chocolate bars total'
    - gold: 'That was Asia Mart in Taman Sentosa, Klang on 22/12/2017 — 17 Delicia Chocolate [50G] on one line (printed amount 15.25) among 25 items in total. The bill came to RM 32.70 inclusive of GST; I paid 40.00 cash and got 7.30 change.' · A: 'Hallmark' · B: 'SAM SAM TRADING CO'

## Caveats (auto-generated)

- Retrieval per-question basis is `end_to_end+ranked_pre_gate`; pre-gate ranking is known to disagree with the end-to-end ask() list on some questions - treat those deltas as pre-gate ranking deltas (old-run fallback).
- Discordant counts below ~5 are inside noise for this golden-set size; flagged rows say so. Do not tune on them.

<!-- magpie-compare agents append below this line -->


## Synthesis (supervisor, 20260830)

Owner question: **"Does the LLM query rewrite help or hurt retrieval and answer quality on this corpus at top_k=2 with rerank off?"**

### Verdict

**Rewrite, as currently implemented, decisively hurts retrieval (hit@1 0.933 -> 0.856, 9A/1B discordant, McNemar p = 0.021 — decision-grade) and produces no credible change in answer quality (the judged +7.5 pt is not decision-grade once cause-attributed; the deterministic paired basis is coin-consistent at 4A/6B, p = 0.75, and strict deterministic correct is 3 = 3) — so at top_k=2 / rerank-off the knob is a net harm; but the harm is one implementation defect, not the concept: a wall-clock line injected into every rewrite call (`src/llm.py:329`, `SearchQuery` missing from `_NO_TIMESTAMP_OUTPUTS` at `:340`) fully hijacked 12 of 60 typed queries, and the 7 answerable ones account for 7 of the 9 hit@1 losses (the other 2 are a vocabulary-dilution residual on the rcpt-08 pair), and with echo rows excluded the rewrite's retrieval effect on this corpus measures 0.0 points (86 clean paired rows: 1 fix vs 2 losses).**

Decision-grade assessment per headline metric:

| metric | discordant | p | decision-grade? | why |
|---|---|---|---|---|
| retrieval hit@1 (end_to_end basis) −7.7 pt | 9A/1B | 0.0215 | **YES** | >=5 discordant, p<0.05, all 10 flips cause-attributed at high confidence (7 date-echo hijack, 2 vocab dilution, 1 vocab fix); deterministic by construction — no judge in the loop |
| answer good (judge, authoritative) +7.5 pt | 3A/12B | 0.0352 | **NO** | fails cause attribution: 3 of the 15 boundary flips (20%) are judge_disagreement on byte-identical answers — exactly at the skill's judge-limited threshold — and the same-code deterministic basis is coin-consistent (4A/6B, p=0.754; strict correct 3=3, det good 11 -> 13). The judged gain survives only under the B-session judge's more lenient partial->correct policy, which sits on golden-set key_facts over-specification that judge itself flagged (8 of its 9 upgrades) |
| abstained +2.5 pt | 9A/12B | 0.664 | NO | coin-consistent; 22-row churn behind a net +2 (regression hunter #2) |

**Judge-limited caveat, stated plainly:** the answer-quality half of this comparison is at the ~20% judge_disagreement threshold at the good/bad boundary (3/15). The measured cross-session noise floor is 4 verdict flips on 65 byte-identical answer rows (6-10% depending on denominator), and the B judge overrode the deterministic scorer 23 times vs A's 11. **The deltas that survive deterministic-only scoring are: retrieval hit@1 −7.7 pt (real, defect-driven), deterministic correct-or-partial 19 -> 23 (+4, below the ~5-discordant credibility bar), strict correct 3 = 3 (no change).** Do not quote "correct 5 -> 12" without this caveat. Per the measured noise floor, judged-correct deltas under ~5 rows on this rubric are indistinguishable from judge noise; deterministic verdicts are the regression-detection basis going forward.

### Cause table — all 41 flips (36 judge-verdict flips + 5 hit@1-only flips)

Aggregate: **retrieval_change 36** (date_echo_hijack 11, keyword_distractor_swap 10, vocab_change 13, vocab_fix 1, rank_swap 1) · **judge_disagreement 4** · **prompt_assembly 1** (timestamp header) · guard 0 · **model_variance 0** (temp-0 determinism held: 41/43 identical-prompt rows gave byte-identical answers; the 2 divergences trace to the per-minute clock header, i.e. prompt_assembly, not sampling) · infra_error 0 (the 3 HTTP-400 rows are concordant across arms and excluded from cross-arm claims).

Every attribution verified by agents against raw artifacts (enriched rows, answers.jsonl, retrieve.jsonl, LLM request logs, corpus images); supervisor spot-checked 8 rows independently. One dominant cause: **31 of 36 verdict flips are rewrite-mediated retrieval changes, and 14 of the 15 boundary improvements happened where gold was already rank 1 in both arms — the rewrite merely re-rolled the rank-2 distractor.** The single change the data points at: stop injecting the timestamp into rewrite calls (`_NO_TIMESTAMP_OUTPUTS` + "SearchQuery", one line), then re-measure; the distractor-lottery gains argue for rerank/solo-gate work, not for rewrite-on.

| qa_id | flip (A->B) | cause | mechanism | confidence |
|---|---|---|---|---|
| nf-01-typed | correct_abstain->false_answer | retrieval_change | date_echo_hijack | high |
| nf-05-typed | correct_abstain->false_answer | retrieval_change | date_echo_hijack | high |
| viz-01-typed | correct->wrong | retrieval_change | vocab_change | high (cause) / med (mechanism) |
| arch-04-full | partial->correct | judge_disagreement | — | high |
| nf-02-typed | false_answer->correct_abstain | retrieval_change | keyword_distractor_swap | high |
| nf-06-typed | false_answer->correct_abstain | retrieval_change | vocab_change | high (cause) / med (mechanism) |
| nf-07-typed | false_answer->correct_abstain | retrieval_change | date_echo_hijack (class B) | high (cause) / med (mechanism) |
| nf-08-typed | false_answer->correct_abstain | retrieval_change | date_echo_hijack | high |
| phone-02-full | wrong->correct | retrieval_change | keyword_distractor_swap | high (cause) / med (mechanism) |
| phone-02-typed | wrong->correct | retrieval_change | vocab_change | high (cause) / med (mechanism) |
| phone-06-full | partial->correct | judge_disagreement | — | high |
| phone-06-typed | partial->correct | judge_disagreement | — | high |
| viz-01-full | wrong->correct | retrieval_change | vocab_change | high |
| viz-02-full | wrong->correct | retrieval_change | vocab_change | high (cause) / med (mechanism) |
| viz-06-typed | wrong->correct | retrieval_change | vocab_change | high |
| arch-04-typed | partial->false_abstain | retrieval_change | keyword_distractor_swap | high |
| arch-05-typed | partial->false_abstain | retrieval_change | date_echo_hijack | high |
| arch-08-full | wrong->false_abstain | prompt_assembly | timestamp_header | high |
| phone-03-full | wrong->partial | judge_disagreement | — | high |
| phone-07-typed | wrong->false_abstain | retrieval_change | keyword_distractor_swap | high |
| phone-08-typed | wrong->false_abstain | retrieval_change | keyword_distractor_swap | medium |
| phone-09-full | wrong->partial | retrieval_change | keyword_distractor_swap | high |
| phone-10-typed | partial->wrong | retrieval_change | vocab_change | high |
| phone-11-typed | partial->wrong | retrieval_change | rank_swap | high |
| rcpt-02-full | false_abstain->partial | retrieval_change | keyword_distractor_swap | high |
| rcpt-04-typed | partial->false_abstain | retrieval_change | vocab_change | high |
| rcpt-05-full | wrong->partial | retrieval_change | vocab_change | high |
| rcpt-06-typed | false_abstain->wrong | retrieval_change | keyword_distractor_swap | high |
| rcpt-07-typed | false_abstain->wrong [index-dead row] | retrieval_change | keyword_distractor_swap | high |
| rcpt-08-full | false_abstain->wrong | retrieval_change | vocab_change | high |
| rcpt-08-typed | wrong->false_abstain | retrieval_change | vocab_change | high |
| study-01-full | false_abstain->partial | retrieval_change | vocab_change | high |
| study-04-typed | wrong->false_abstain | retrieval_change | date_echo_hijack | high |
| study-06-typed | wrong->partial | retrieval_change | keyword_distractor_swap | high |
| viz-05-full | false_abstain->wrong | retrieval_change | vocab_change | high |
| viz-10-typed | partial->wrong | retrieval_change | date_echo_hijack | high |
| phone-09-typed | hit@1 1->0 (verdict false_abstain both) | retrieval_change | date_echo_hijack | high |
| viz-02-typed | hit@1 1->0 (verdict wrong both) | retrieval_change | date_echo_hijack | high |
| viz-07-typed | hit@1 1->0 (verdict false_abstain both) | retrieval_change | date_echo_hijack | high |
| viz-08-typed | hit@1 1->0 (verdict wrong both) | retrieval_change | date_echo_hijack | high |
| rcpt-05-typed | hit@1 0->1 (verdict wrong both) | retrieval_change | vocab_fix | high |

Per-flip evidence sentences are in `comparison.json` -> `synthesis.attributions`. Notable single rows: `viz-01` swapped which half of the pair wins purely on which distractor sat beside the same rank-1 gold (a wash, not a win); `rcpt-05-typed` is the one genuine ranking fix (5->1) and was wasted by the reader answering off the rank-2 receipt; `rcpt-07-typed` flipped on an index-dead row (gold never indexed in either arm — generation churn, not a rewrite effect); `study-01-full` shows the rewriter leaking the answer ("Bjarne Stroustrup") into keywords from parametric memory.

### Slice story (bases labeled; treat judge-based slices with the caveat above)

- **Full phrasing is where rewrite genuinely helps: 0A/5B on the judged good/bad boundary (p=0.0625, suggestive)**; on the wider correct-or-partial basis the cross-arm paired result is 8 up / 0 down (p=0.008, run-B answers report §3) with deterministic corroboration (correct-or-partial 19 -> 23). Mechanism is still distractor-lottery, and 5 full queries carry clock text with 8 more carrying clock keywords — full is contaminated too, it just never lost the topic.
- **Typed churns with no net rate change: 3A/7B (p=0.34)** despite 12 destroyed queries — the keyword/distractor lottery paid back elsewhere what the hijack burned. Retrieval on typed: −13.5 pt hit@1 with echo rows in, **0.0 pt with them out** (37 clean pairs); full −1.9 pt (noise band). H2-prime's >=10-pt bar is met by the defect, not the concept (run-B retrieval report §6.3).
- **answer_type=extractive +10 pt (1A/8B, p=0.039)** is nominally significant but is the same judge-lenient upgrade set (phone-02/phone-06/viz-01/viz-02/viz-06 cluster); label suggestive, not decision-grade. Enumeration and synthesis: zero discordants — untouched (synthesis is 0% in both arms).
- **not_found probes: correct_abstain 9 -> 11 is retrieval-lottery artifact, not discipline** — the entire +4 gain side (nf-02/06/07/08-typed) is hijack/keyword garbage that hid A's false-answer trigger files, while the hijack manufactured 2 brand-new false answers (nf-01/nf-05-typed, both "31.00" off the same date-dense receipt).

### Regression-hunter findings (full-diff sweep, recomputed from artifacts)

1. **Wall-clock −373 s is a host artifact, not a rewrite win** (notable): on 43 identical-retrieval rows generation ran 231.7 s faster in B with 41/43 byte-identical answers; A's answer phase ran hot after its own 2514 s index build, B mounted. Rewrite's true marginal cost: +1.22 s/question (+146.8 s total). Do not book the saving to rewrite.
2. **Abstention churn 22 rows behind a net +2** (warn): 12 in / 10 out of raw not_found; all but arch-08-full trace to changed retrieval — no threshold change.
3. **Retrieval moved silently and almost entirely downward** (notable): recall@12 changed on 9 rows, all losses (7 hijacks + rcpt-08-full 1.0->0.667 + viz-05-full 1.0->0.5 with hit@1 unchanged); mean first_gold_rank "unchanged" only via exact 3-row cancellation (rcpt-05 +4 vs rcpt-08 pair −2 each). notes_iam distractor slots top-2 1 -> 0, top-12 10 -> 6 — improvement is mechanical (the date attractor is receipts/fax covers, not handwriting).
4. **Judge-session drift is the loudest scoring mover** (notable): disagreements-with-deterministic 11 -> 23; judge correct 5 -> 12 while deterministic correct 3 = 3; 4/65 byte-identical rows flipped verdict (arch-04-full, phone-03-full, phone-06 pair). B judge also used 60/60 phrasing denominators vs A's 52/52 (nf probes included) — do not compare those summary rates raw.
5. **Unchanged defects (both arms, frozen)**: sources_used header-parse deletions (A 15 malformed entries/7 gold-deleted; B 9/4, 3 of them judge-correct rows — the parse bug now provably deletes correct citations); landlord-leak not_found_topic 12 rows in both (B's viz-05-full carries a trailing "]"); verbatim question echo 33 -> 35 (100% typed); query-echo answers 7 -> 4 (mechanism intact, trigger rows moved); solo_gate phantom fire_rate 0.05 -> 0.042 published while structurally off (set changed: arch-04-typed left — the metric tracks retrieval dedup, not gating); same 3 HTTP-400 qa_ids at ~equal token overflows; same 7 widened rows.
6. **Environment/provenance** (info): env diff limited to LANG en_US.UTF-8 -> C.UTF-8, PATH duplicates, plugin hash — no plausible result path (no locale-sensitive ops found; explicit utf-8 reads). harness_git_sha moved (2465ab7b -> 80f7c617, progress watcher, eval_harness/ only) — bounded empirically by 0 deterministic-verdict differences on byte-identical rows. B's 3 error rows lost search_query (rewrites recoverable only from LLM logs); B's appdata carries A's answer log via the mounted-store copy (do not join on it).
7. **Report errata found during verification** (warn): run-B REPORT-answers §2 names nf-03-full for `not_found_flag_missing`; the artifact flags **nf-01-full**. Its §7 "305 vs 420 chars" is not reproducible from enriched rows (direction agrees). REPORT-retrieval §3's verdict split for the 7 hijack losses uses enriched labels where the judge differs on 2 rows (arch-05-typed, rcpt-08-full). None changes a conclusion.

### Recommended next run

**Land the one-line fix — add `"SearchQuery"` to `_NO_TIMESTAMP_OUTPUTS` (`src/llm.py:340`) — plus, if cheap, the zero-content-overlap rewrite fallback (`search.py:110`), and re-run this exact config (rewrite ON, top_k=2, rerank off, same dataset/golden).** That is the true H2-prime test: clean-pair evidence predicts ~0 retrieval delta, isolating whether the genuine full-phrasing answer gain survives without the confound. Cost: index store `66974090bdcd62e6` mounts in ~1 s (cache HIT — rewrite is not an index-side param); answer+retrieve wall ~35 min (B ran 2120 s). It moves `backend_git_sha` by design (new comparability cell). Judge discipline for that run: score deterministically for the A/B call (and settle the golden v2.1 key_facts trims before the next judged arm — the correct/partial boundary currently belongs to the judge session, not the golden set). Independently valuable and orthogonal: a rerank-ON arm to turn the top-2 distractor lottery this comparison exposed into a deliberate mechanism.

