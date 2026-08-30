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

