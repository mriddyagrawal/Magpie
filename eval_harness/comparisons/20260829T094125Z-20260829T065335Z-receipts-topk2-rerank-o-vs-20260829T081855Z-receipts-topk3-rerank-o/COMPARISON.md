# Comparison: 20260829T065335Z-receipts-topk2-rerank-off  vs  20260829T081855Z-receipts-topk3-rerank-off-norewrite

- Generated: 20260829T094125Z  ·  pairing mode: **full** (coverage 100%, n=120)
- Changed axes: **config**
- Params diff: `rewrite`: True → False, `top_k`: 2 → 3

## Paired outcomes (A = baseline)

| Metric | A | B | Δ | discordant | McNemar p |
|---|---|---|---|---|---|
| answer good (authoritative) (judge) | 0.0583 | 0.0833 | +0.025 | 4A / 7B | 0.54883 |
| answer good (deterministic) | 0.025 | 0.0667 | +0.0417 | 2A / 7B | 0.17969 |
| answer good (judge) | 0.0583 | 0.0833 | +0.025 | 4A / 7B | 0.54883 |
| retrieval hit@1 (ranked_pre_gate) | 0.783 | 0.7925 | +0.0094 | 9A / 10B | 1.0 |
| abstained | 0.3833 | 0.3417 | -0.0417 | 21A / 16B | 0.51138 |

## Verdict transitions (A → B)

- false_abstain -> wrong: 18
- wrong -> false_abstain: 11
- false_answer -> correct_abstain: 6
- wrong -> partial: 5
- correct -> wrong: 3
- partial -> wrong: 2
- wrong -> correct: 1
- false_abstain -> partial: 1
- correct_abstain -> false_answer: 1

## Slices

| Slice | A | B | Δ | discordant | McNemar p |
|---|---|---|---|---|---|
| phrasing=full | 0.0667 | 0.0667 | +0.0 | 2A / 2B | 1.0 |  *(< 5 discordant - not credibly non-noise)*
| phrasing=typed | 0.05 | 0.1 | +0.05 | 2A / 5B | 0.45312 |
| answer_type=enumeration | 0.0 | 0.0 | +0.0 | 0A / 0B | 1.0 |  *(< 5 discordant - not credibly non-noise)*
| answer_type=extractive | 0.0375 | 0.0125 | -0.025 | 3A / 1B | 0.625 |  *(< 5 discordant - not credibly non-noise)*
| answer_type=not_found | 0.2857 | 0.6429 | +0.3571 | 1A / 6B | 0.125 |
| answer_type=synthesis | 0.0 | 0.0 | +0.0 | 0A / 0B | 1.0 |  *(< 5 discordant - not credibly non-noise)*

## Answer regressions (good in A → bad in B) — 4

- **rcpt-a-04-full** (full) — correct → wrong: 'Did I pay cash or card for the 193.00 invoice from OJC Marketing?'
    - gold: 'That one went on the card — the OJC Marketing tax invoice of 15/01/2019 for 193.00 was settled by VISA CARD, card ending 4318.' · A: 'Card (VISA)' · B: 'Cash'
- **rcpt-e-04-full** (full) — correct → wrong: 'Which card did I pay with on that big Super Seven shop, the four-hundred-odd ringgit one?'
    - gold: 'That Super Seven Cash & Carry tax invoice dated 01-03-2018 for RM408.45 shows the payment method as MASTER CARD.' · A: 'Master Card' · B: 'VISA CARD'
- **rcpt-e-04-typed** (typed) — correct → wrong: 'super seven 408 paid by what card'
    - gold: 'That Super Seven Cash & Carry tax invoice dated 01-03-2018 for RM408.45 shows the payment method as MASTER CARD.' · A: 'Master Card' · B: 'VISA CARD'
- **rcpt-nf-06-typed** (typed) — correct_abstain → false_answer: 'tanjongmas bookcentre'
    - gold: 'There is no Tanjongmas Bookcentre receipt in this collection. (There are receipts from other bookshops and stationers, including Popular Book Co. and Kedai Buku New Acheivers.)' · A: '' · B: 'Tanjongmas Book Centre'

## Answer wins (bad in A → good in B) — 7

- **rcpt-b-05-typed** (typed) — wrong → correct: 'vivopac gst amout sept'
    - gold: 'The 13/09/2017 Vivopac Marketing invoice charged RM 2.97 of GST at 6% on a RM 49.50 sub-total, for a rounded total of RM 52.45.' · A: '49.50' · B: 'Vivopac GST amount: RM 2.97'
- **rcpt-nf-01-full** (full) — false_answer → correct_abstain: 'How much did I spend at PappaRich?'
    - gold: 'There is no PappaRich receipt in this collection.' · A: 'You spent 44.00ZR on Anchor Flour and 15.40SR on Diamond Foil 7, for a total of 59.40ZR [1].' · B: ''
- **rcpt-nf-01-typed** (typed) — false_answer → correct_abstain: 'papparich receipt'
    - gold: 'There is no PappaRich receipt in this collection.' · A: 'POPULAR BOOK CO. (M) SDN BHD' · B: ''
- **rcpt-nf-02-typed** (typed) — false_answer → correct_abstain: 'secret recipe total'
    - gold: 'There is no Secret Recipe receipt in this collection.' · A: '25.80' · B: ''
- **rcpt-nf-04-full** (full) — false_answer → correct_abstain: 'Can you find the Moonlight Cake House receipt?'
    - gold: 'There is no Moonlight Cake House receipt in this collection.' · A: 'Yes, the Moonlight Cake House receipt is available [1].' · B: ''
- **rcpt-nf-05-typed** (typed) — false_answer → correct_abstain: 'golden key maker bill'
    - gold: 'There is no Golden Key Maker receipt in this collection.' · A: 'golden key maker bill: 56.80' · B: ''
- **rcpt-nf-07-typed** (typed) — false_answer → correct_abstain: 'platinum racking sdn bhd'
    - gold: 'There is no Platinum Racking receipt in this collection.' · A: 'Platinum Racking Sdn BHD' · B: ''

## Retrieval hit@1 regressions — 9

- **rcpt-a-05-typed** (typed) — false_abstain → false_abstain: 'zheng hui gst amout'
    - gold: 'The Perniagaan Zheng Hui bill of 09/02/2018 carried 24.69 in GST — RM411.50 excluding GST, RM436.20 paid in cash.' · A: '' · B: ''
- **rcpt-a-06-typed** (typed) — wrong → wrong: 'yong tat hardware what did i buy'
    - gold: 'One sheet only — a 0.8MM X 50" X 60" AR RED GASKET at 72.00 (RM67.92 before GST), on 13/03/2018.' · A: 'Yong Tat Hardware Trading, 1 item (3/4" ALUMINIUM ROD), RM 19.60' · B: '5.30'
- **rcpt-b-01-typed** (typed) — wrong → false_abstain: 'jiawei dinner total'
    - gold: 'The Restaurant Jiawei bill (23/2/2018, Table 13) came to RM 110.00, with no service charge added.' · A: 'RM 63.90' · B: ''
- **rcpt-b-09-typed** (typed) — false_abstain → false_abstain: 'hon hwa hardware how much altogether'
    - gold: 'The three Hon Hwa Hardware Trading receipts add up to RM 31.80 — RM 5.00 on 05/01/2017, RM 19.60 on 11/02/2017 and RM 7.20 on 28/04/2017.' · A: '' · B: ''
- **rcpt-d-03-full** (full) — wrong → wrong: 'Which shopping centre was that Kaison receipt from?'
    - gold: 'That Kaison Furnishing slip is from the MyTOWN Shopping Centre outlet — Lot No. L3-012, Level 3, No. 6 Jalan Cochrane, 55100 Kuala Lumpur — dated 25-03-18.' · A: 'AEON CO. (M) BHD' · B: 'AEON CO. (M) BHD'
- **rcpt-e-02-typed** (typed) — wrong → false_abstain: 'mei let restarant when'
    - gold: 'The Mei Let Restaurant bill is dated 03/02/2017, 09:26:48 PM — table 13, net total RM68.90.' · A: 'Mei Let Restaurant' · B: ''
- **rcpt-e-05-typed** (typed) — false_abstain → false_abstain: 'great zone kluang gst amount'
    - gold: 'GST at 6% on the Great Zone Household Centre invoice of 18/02/2018 was RM20.79, on a sub total of RM346.51, giving a rounded total of RM367.30.' · A: '' · B: ''
- **rcpt-e-07-full** (full) — wrong → wrong: 'Which Guardian branch did I buy that Freeman face mask at?'
    - gold: 'The Freeman BK/CH 6OZ was bought at Guardian Solaris Mount Kiara (No.8 & 10, GF Solaris Mount Kuara, Jln Solaris 5) on 01/01/18, RM22.45 on a Visa card.' · A: 'Guardian Health And Beauty Sdn Bhd' · B: 'BANDINGKAN HARGA KAMI'
- **rcpt-en-03-typed** (typed) — false_abstain → wrong: 'gin kee january dates'
    - gold: 'There are 6 Syarikat Perniagaan Gin Kee receipts from January 2018: the 3rd, 4th, 15th, 25th, 27th and 31st.' · A: '' · B: 'CEDA APAN YEW CH JAN'

## Retrieval hit@1 wins — 10

- **rcpt-a-02-typed** (typed) — false_abstain → false_abstain: 'f&p phamacy what date'
    - gold: 'The F&P Pharmacy visit in Seri Kembangan was on 02/03/2018, at 16.46 — doc no CS00110240, RM31.90 in total.' · A: '' · B: ''
- **rcpt-a-06-full** (full) — false_abstain → wrong: 'What was the item I picked up at Yong Tat Hardware?'
    - gold: 'One sheet only — a 0.8MM X 50" X 60" AR RED GASKET at 72.00 (RM67.92 before GST), on 13/03/2018.' · A: '' · B: 'SR: EXTENSION LADDER 12" X 12"'
- **rcpt-b-06-typed** (typed) — false_abstain → false_abstain: 'premio battery invoice no'
    - gold: "It is invoice No SS3-154439, dated 20/03/2018 — one pack of Energizer Battery AA 4's for RM 13.40." · A: '' · B: ''
- **rcpt-b-08-typed** (typed) — partial → wrong: 'sunquick oren recipt which shop'
    - gold: 'The Sunquick Oren 330ML came from 99 Speed Mart (the Tmn Bkt Pandan branch) on 10-03-18, RM 5.35 inclusive of GST.' · A: '99 SPEED MART S/B' · B: 'Sunquick Oren'
- **rcpt-c-03-full** (full) — wrong → wrong: 'I paid cash at LA Stationery for the pens and glue - how much change did I get back?'
    - gold: 'You paid 100.00 cash at LA Stationery for a 56.80 bill and got 43.20 change back.' · A: '4.95' · B: '11.90'
- **rcpt-c-09-full** (full) — wrong → wrong: 'Of my two Restoran Wan Sheng drink runs in March, which one cost more and by how much?'
    - gold: 'The 17-03-2018 Wan Sheng run was the bigger one at 9.60; the 23-03-2018 one was only 6.70.' · A: 'The March 23rd receipt cost more by RM 0.33 [1] and [2].' · B: 'The first drink run cost more by 0.80 RM'
- **rcpt-c-10-typed** (typed) — wrong → wrong: 'kedai buku new acheivers both bills added up'
    - gold: 'The two Kedai Buku New Acheivers bills add up to 86.15 - 48.00 on 15/09/2017 and 38.15 on 28/12/2017.' · A: '5.00 and 4.10' · B: '30.48'
- **rcpt-d-03-typed** (typed) — wrong → wrong: 'kaison which mall'
    - gold: 'That Kaison Furnishing slip is from the MyTOWN Shopping Centre outlet — Lot No. L3-012, Level 3, No. 6 Jalan Cochrane, 55100 Kuala Lumpur — dated 25-03-18.' · A: 'Cheras Leisure Mall' · B: 'Guardian Health And Beauty Sdn Bhd'
- **rcpt-d-05-full** (full) — wrong → false_abstain: 'Did I pay cash or by card at AA Pharmacy?'
    - gold: 'That one went on the card — the AA Pharmacy receipt from 29/01/2018 shows MASTER 46.20 with 0.00 change.' · A: 'Cash' · B: '(model output could not be parsed into Answer)'
- **rcpt-d-09-typed** (typed) — wrong → wrong: 'kedai papan 21 march both bills together'
    - gold: 'Two Kedai Papan Yew Chuan invoices are dated 21/03/2018 — CS00011014 for RM68.90 (pasir halus) and CS00011043 for RM144.16 (besi Y 10) — so RM213.06 that day.' · A: '1.70' · B: '68.90'

## Caveats (auto-generated)

- Retrieval per-question basis is `ranked_pre_gate` (enrich.py's basis); the end-to-end `ask()` list is known to disagree on some questions - treat retrieval deltas as pre-gate ranking deltas.
- Discordant counts below ~5 are inside noise for this golden-set size; flagged rows say so. Do not tune on them.

<!-- magpie-compare agents append below this line -->


# Supervisor synthesis (agents + spot-checked)

## Verdict

**No — k=3 is not worth it on this evidence, and the modest answer improvement (5.8%→8.3%) belongs almost entirely to the OTHER knob (rewrite off), not to k.** The delta is suggestive, not decision-grade (4A/7B discordant, McNemar p=0.549). Retrieval hit@1 was flat — and structurally had to be: the pre-gate ranking never sees `top_k` (ranked at k_max=12 in both runs), and all 19 retrieval flips attribute to the rewrite knob, 0 to k. Of the 11 answer-verdict flips, `top_k` is primary in exactly 1 (low confidence) and co-primary in 2 via first-slot geometry. Meanwhile k=3 costs +7.2s mean / +40s p95 latency (driven by a new degeneration defect) and coincides with a citation collapse. Owner's question answered: stay at k=2 until the ordering fix lands, then re-measure.

## What the comparison actually found (defects > deltas)

1. **Rewriter wall-clock contamination (product bug, run A).** The rewrite LLM injects the current date/time into queries (21/120) and keywords (65/120); on 4 typed queries it REPLACED the query entirely (e.g. `rcpt-nf-05-typed` → `'2026-08-29 03:31 EDT'`, `rcpt-c-10-typed` → `'current date and time Saturday 2026-08-29 03:02 EDT'`). Most of A's "false answers on not_found questions" were temptation files retrieved by contaminated queries. The rewrite-off "abstention improvement" in B is mostly losing those temptation files, NOT a better abstention policy — B false-answered `nf-06` the moment a citable bookshop receipt landed first.
2. **Guard structural zero re-confirmed at accuracy 1.000 in BOTH runs**: no surviving answer in either run contains any number ≥ 100. Every receipt total over RM100 is unanswerable-correctly; the 29-question wrong↔false_abstain churn is coin-flipping around that threshold (same top-1 file 12/17 and 7/10; gold in-prompt unchanged).
3. **Best-ranked-last ordering bug confirmed live, both runs**: in 10 of 11 grounded wrong/false answers, content came from the FIRST-presented (worst-ranked) file. `rcpt-a-04-full` is the clean demonstration: B RANKED gold #1 (a retrieval improvement), the reversal presented it last, and the model answered "Cash" from the sibling it met first — a retrieval win converted into an answer regression by prompt assembly.
4. **NEW in B: degenerate generations** — 8 multi-thousand-token junk emissions ("dropped hallucinated source paths" up to 5.4k chars), exactly the slow tail (p95 20s→57s); zero in A. Plus 1 unparseable output. Attribution medium: 3-image prompts. Needs its own investigation before any k>2 ships.
5. **Citation collapse in B**: zero-citation answers 9→45 (12%→57% of non-abstained); precision 0.184→0.060. Unattributed (rewrite-off vs 3-image); blocks shipping norewrite as-is.
6. `rcpt-e-04-typed`'s A "correct" was a lucky fabrication (cited receipt reads VISA; answer said Master Card, matching gold by chance) — that regression is illusory, and a caveat on both judges' blind spot for lucky guesses.

## Cause table (11 answer flips, spot-checked 2/agent)

| Cause | n | qa_ids |
|---|---|---|
| retrieval_change (all rewrite-driven) | 7 | e-04-full, nf-06-typed, nf-01-full, nf-01-typed, nf-02-typed, nf-04-full, nf-05-typed |
| prompt_assembly (ordering/first-slot) | 3 | a-04-full, b-05-typed, nf-07-typed |
| model_variance | 1 | e-04-typed |
| guard / judge_disagreement / infra_error | 0 | — (churn is guard-mediated but below the flip threshold; errors identical 4/4 same qa_ids) |

Knob attribution: rewrite primary 7, both 2, top_k 1, unclear 1. Retrieval flips: rewrite 19/19.

## Slice story

Full-sentence hit@1 rose 0.868→0.906 while typed fell 0.698→0.679; the typed↔full gap WIDENED 0.170→0.226. Mechanism (from per-flip evidence): rewrite-off stops fixing typos ("phamacy", "amout", "restarant") — hurting typed — while its catastrophes (vendor-dropped queries) had been typed-concentrated too. Rewrite is high-variance on typed queries, not net-negative: depth asymmetry matters — where rewrite-off lost, gold fell shallow (6/9 within top-3); where rewrite lost, gold fell deep (5 clean misses to None). A contamination-fixed rewrite would likely be a strict win.

## Regression-hunter extras

- Errors/overflows identical (4/4, same qa_ids, widened path reads 12 files regardless of k).
- Judge not a limiter: same model+rubric, disagreement 6.7%→8.3%, 0 judge_disagreement flips.
- solo_gate fire_rate 0 both (structurally off, stamped). Index bit-identical (B mounted A's store entry — retrieval deltas are pure query effects).
- Harness bug found by this comparison: compare.py's paired-latency check expects scalar `latency_s` but runs store a dict — fixed in the commit following this synthesis.

## Recommended next run

**Fix the ordering (best-first when image blocks present — one line in `src/answer.py`), keep k=2, rewrite off, same golden set.** Single code-axis change; index store HIT (key 5ff3e0adf0448de6); ~45–60 min answer run + judge. Expected effect: the 10/11 first-slot wrong answers and the a-04 class of inverted retrieval wins flip — if answer-good doesn't move ≥5 discordant with that fix, the model, not the prompt, is the ceiling. Second in queue: strip wall-clock from the rewriter prompt and re-test rewrite on typed queries only.
