# Answers report — rewrite arm

Run: `20260830T121044Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-rewrite` (rewrite ON)
Baseline: `20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite` (rewrite OFF)
Comparability verified: same `golden_sha 0ebcdcbcdf109adb` (120 items, 60 pairs, 16 not_found), same backend `cca67570`, same mounted index (store key `66974090bdcd62e6`, `hit: true` in this run), configs differ on exactly one knob (`rewrite`). All 120 qa_ids match one-to-one across arms.

Sources (all read, none modified):
`/Users/mriddy/Documents/GitHub/NotAnotherSpotlight/eval_harness/runs/20260830T121044Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-rewrite/answers_enriched.json`, `judge_verdicts.json`, `metrics.json`, `raw/answers.jsonl`, `raw/retrieve.jsonl`, `raw/worker_answer.log`, and the run's own LLM log `raw/appdata/logs/llm-2026-08-30T12-10-46Z.log` (240 requests: 120 SearchQuery rewrites + 120 Answer calls, joined to qa_ids 120/120) plus the 3-request retrieve-phase log `llm-2026-08-30T12-45-43Z.log`; the baseline's equivalents; `eval_harness/datasets/custom_dataset_rahul_Aug30/golden.json`; and read-only inspection of `src/stage2/search.py`, `src/llm.py`, `src/inference/local_llm.py`, `src/inference/profiles.py`.

Caution for future readers: this run's `raw/appdata/logs/` also contains `llm-2026-08-30T10-40-06Z.log`, which is the **baseline's** answer log inherited through the mounted index-store snapshot. Every subject-arm number below comes from `llm-2026-08-30T12-10-46Z.log` only.

---

## Executive summary

The headline "judge-correct jumped 5 to 12 while retrieval fell 8 points" is real arithmetic but a bad summary: **+3 of the +7 comes from the judge scoring byte-identical answers differently across the two sessions, and the remaining +4 are wrong-to-partial-grade improvements that the second judge promoted to correct under a golden-set defect it itself flagged (over-specified key_facts). Under the deterministic scorer, strict correct is exactly 3 = 3 in both arms.** The retrieval drop and the answer gain do not contradict each other because they happen on different rows: the rewriter's clock-text hijack destroyed retrieval on 12 typed questions that were already failing in the baseline (7 of the 8 lost hit@1 rows moved wrong-to-false_abstain, a mode change), while every genuine answer improvement happened on rows where the gold was retrieved in both arms and the rewrite merely re-rolled which rank-2 distractor sat next to it. Rewrite is two different products by phrasing: on verbose (full) questions it improved 8 rows and regressed 0 (p = 0.008); on terse (typed) questions it is a churn machine (7 gains, 9 losses) whose date-hijack accounts for all four of this run's manufactured false answers and abstentions. The 374 s answer-wall saving is a host-speed confound, not a rewrite benefit: on the 43 byte-identical prompts, generation alone ran 232 s faster in this run.

---

## 1. The paradox (judge-correct 5 -> 12 while hit@1 0.933 -> 0.856)

### 1.1 What actually varies between arms, mechanically

Verified from the LLM logs and `src`:

- **The rewrite call.** All 117 completed rows carry `search_query.rewritten: true`; the 3 HTTP-400 rows carry `final_query: null` (the enrichment lost their rewrite, but the answer-pass rewrites are recoverable from the LLM log — see section 6). The rewrite request user message is built by prepending `_timestamp_prefix()` (`/Users/mriddy/Documents/GitHub/NotAnotherSpotlight/src/llm.py:317-326`, "prepended to every LLM call") to the bare question: `"Current date and time: Sunday, 2026-08-30 08:10 EDT\n\n<question>"`. On terse typed questions the 3B rewriter frequently rewrites the header instead of the question — the echoed timestamps advance minute-by-minute with the run (08:11 ... 08:40 EDT), proving it is a header echo, not a constant.
- **Keywords reach the visual tier.** The rewrite emits a `keywords` list, and `src/stage2/search.py:849` concatenates it into the ColQwen query text (`query_text = (sq.query + " " + " ".join(sq.keywords)).strip()`; same pattern at :375/:668 for the empty summary tier). So retrieval changes even when `final_query` is identical to the baseline's raw question: `nf-02-typed` ("wedding invitation", same string both arms) retrieved scene photos in the baseline but `bad_receipt_013/028` here, because its keywords were `['wedding','invitation','date','time','EDT','2026-08-30','08:40']`.
- **The answer prompt embeds the original question, not the rewritten query** (verified on all 120 Answer requests). Given the same retrieved files in the same order, the answer prompts differ across arms only in the wall-clock header (06:4x EDT baseline vs 08:xx EDT here).
- **The rewrite runs at temperature 0.0** despite logging `temperature: null` — the local provider substitutes `default_temperature` = `LOCAL_TEMPERATURE` = 0.0 (`src/inference/local_llm.py:154,:367`; `src/inference/profiles.py:301`). The hijack is deterministic given the prompt; it varies run-to-run only because the embedded clock text does.

**Clock-contamination census of the 117 completed rewrites** (my classification; full lists reproducible from `answers_enriched.json` `search_query` fields):

| Class | Definition | n | typed | full |
|---|---|---|---|---|
| A | `final_query` is clock text, topic fully erased | 12 | 12 | 0 |
| B | `final_query` contains clock text, topic survives | 23 | 18 | 5 |
| C | `final_query` clean, `keywords` carry clock tokens | 17 | 9 | 8 |
| clean | no clock text anywhere | 65 | 20 | 45 |

Class A: `arch-05-typed`, `nf-01-typed`, `nf-04-typed` ("today's date and time"), `nf-05-typed` ("August 30 2026 time"), `nf-08-typed`, `phone-09-typed`, `study-04-typed`, `study-10-typed`, `viz-02-typed`, `viz-07-typed`, `viz-08-typed`, `viz-10-typed`. Half of all completed typed queries (30/59) carry clock text in the query itself; including keywords, 44/59. This is broader than the supervisor's account — see the verdicts section.

### 1.2 Answer-text equality and generation determinism

Across the 117 rows completed in both arms:

- Retrieved set identical: 46; identical including order: 43.
- Assembled answer prompt byte-identical except the timestamp header: **43**.
- Answer text exactly identical: **62** (23 of the 56 rows where both arms answered; all 39 rows where both abstained; 22 rows abstained on one side only).
- **On the 43 identical prompts, 41 answers are byte-identical.** The 2 divergences (`arch-08-full`: garbage value -> abstain; `study-05-typed`: one wrong answer -> a different wrong answer) had no difference in their requests other than the timestamp string. Temp-0 generation is deterministic; the product's own per-minute clock header is the only residual noise source on unchanged retrievals, and it fired on 2/43 rows (5%).

### 1.3 Per-qa_id paired judge-verdict diff — all 36 flips with cause chains

36 of 117 completed rows changed judge verdict. Causes, established row-by-row from the prompt/retrieval/answer comparison above:

- **4 pure judge-variance flips** — prompt identical, answer byte-identical, verdict changed: `arch-04-full` partial->correct ("55.25"), `phone-06-full` partial->correct ("Laganside 10K"), `phone-06-typed` partial->correct, `phone-03-full` wrong->partial ("Biltz"). Both judges' `reason` fields describe the same answer property and score it differently.
- **1 timestamp-divergence flip** — prompt identical except clock, answer changed: `arch-08-full` wrong->false_abstain (baseline emitted the corrupted "Hazard ratio 2Q2002", this run abstained).
- **31 rewrite-mediated flips** — retrieved set changed (30) or same set reordered (1: `phone-11-typed`, where the rank swap of the two screenshots flipped a partial into the negation-inverting "popup wanted to ask for a donation").

Sorted by quality effect at the success boundary (correct/partial/correct_abstain vs the rest):

**15 improvements** (8 full, 7 typed; 14 answer-mediated + 1 judge-variance):

| qa_id | flip | cause | mechanism |
|---|---|---|---|
| viz-01-full | wrong -> correct | distractor swap | rank-2 chart_030.jpg (source of baseline's "Denmark, 0.81") replaced by arxiv_025.png; model read the gold chart: "Cocoa, 18.81" |
| viz-02-full | wrong -> correct | distractor swap | deck_026.pdf -> info_032.jpg; "Spain" became "South Korea" |
| phone-02-full | wrong -> correct | distractor swap | second scene photo -> bad_receipt_000.jpg; "palm" became "NUC5i7RYH" |
| phone-02-typed | wrong -> correct | distractor swap | scene -> bad_receipt_013.jpg; same |
| viz-06-typed | wrong -> correct | distractor swap | deck_010.pdf -> info_015.jpg; query echo became "6 billion" |
| phone-09-full | wrong -> partial | distractor swap | rank-2 info_021.jpg (the infographic baseline quoted "ORDER, TIP WELL, WALK AWAY" from) replaced by a photo; answered "XX" off the Dos Equis sign |
| rcpt-02-full | false_abstain -> partial | distractor swap | receipt_039.jpg -> info_004.jpg; with only one receipt in the prompt it listed all four line items |
| rcpt-05-full | wrong -> partial | distractor swap | scene photo -> receipt_036.jpg; "Hallmark" became "Asia Mart" |
| study-01-full | false_abstain -> partial | distractor swap | Notes-11 -> Notes-10; produced "1979, Bell Labs" |
| study-06-typed | wrong -> partial | distractor swap | arxiv_018.png (whose histograms baseline described) -> receipt_025.jpg; described the right figure |
| nf-02-typed | false_answer -> correct_abstain | distractor swap (class C) | scenes -> receipts; the query-echo answer disappeared |
| nf-06-typed | false_answer -> correct_abstain | distractor swap (class C) | doc+arxiv -> two arxiv figures; echo disappeared |
| nf-07-typed | false_answer -> correct_abstain | class-B query change | vaccination infographic (info_032.jpg, source of baseline's false "95%") no longer retrieved |
| nf-08-typed | false_answer -> correct_abstain | class-A hijack | "chem notes" never searched; garbage retrieval -> abstain |
| phone-03-full | wrong -> partial | judge variance | identical answer "Biltz" |

**9 regressions — every one typed:**

| qa_id | flip | cause |
|---|---|---|
| viz-01-typed | correct -> wrong | distractor swap: arxiv_025.png -> diagram_001.jpg; "Cocoa at 18.81" became "Cheerios cereal" |
| viz-10-typed | partial -> wrong | class-A hijack: retrieved two receipts; answered "ob means outer" from parametric memory |
| arch-05-typed | partial -> false_abstain | class-A hijack: gold doc_357.jpg lost; answered the prose "Not found" |
| arch-04-typed | partial -> false_abstain | class-B: query kept topic, gold still rank 1, but the added distractor flipped "55.25" into abstention |
| rcpt-04-typed | partial -> false_abstain | clean rewrite; gold rank 1 both arms; distractor swap flipped answer to abstention |
| phone-10-typed | partial -> wrong | distractor swap; "KayC root beer" became "Sizzle!" while citing the gold photo |
| phone-11-typed | partial -> wrong | rank swap only; negation inversion appeared |
| nf-01-typed | correct_abstain -> false_answer | class-A hijack: "passport scan" became a clock query; answered "31.00" off bad_receipt_005.jpg |
| nf-05-typed | correct_abstain -> false_answer | class-A hijack: "transcript" became "August 30 2026 time"; answered "31.00" |

**12 mode-only flips** (wrong <-> false_abstain, or partial -> correct upgrades already counted above as judge variance): `phone-07-typed`, `phone-08-typed`, `rcpt-08-typed`, `study-04-typed`, `arch-08-full` (all wrong->FA), `rcpt-06-typed`, `rcpt-07-typed`, `rcpt-08-full`, `viz-05-full` (all FA->wrong), plus the three judge-variance partial->correct upgrades. These move failure between silence and error without changing quality.

### 1.4 Decomposing the +7 judge-correct

Gains to correct: `arch-04-full`, `phone-06-full`, `phone-06-typed` (identical answers, judge variance), `phone-02-full`, `phone-02-typed`, `viz-02-full`, `viz-06-typed` (real answer changes), `viz-01-full` (real). Loss from correct: `viz-01-typed` (real). Net +7:

- **+3 is judge run-to-run variance**: byte-identical answers ("55.25", "Laganside 10K" twice) scored partial by the baseline judge and correct by this run's judge. Both applied a defensible rule; they applied different ones.
- **+4 is genuine answer change** (phone-02 both, viz-02-full, viz-06-typed) — but at the deterministic level these are wrong->partial improvements, promoted to correct by this judge's stance that the unmatched key_facts ("Intel", "72%", "1.7 million") are not asked for by the question (its own golden_issues 1). A real improvement in every case; "correct" is the generous label for it.
- **viz-01 is a wash**: the pair swapped which half is correct, purely on which distractor accompanied the same rank-1 gold chart in each cell (baseline typed had arxiv_025 and won; this run's full had arxiv_025 and won; the other half of each got a confusable neighbor and lost).

Held to the deterministic scorer — identical code both arms — **strict correct is 3 vs 3** (`phone-01-full` and `phone-07-full` in both; third slot swaps `viz-01-typed` -> `viz-01-full`), and correct-or-partial moves 19 -> 23. The same +4 also shows up at the judge level (21 -> 25 correct-or-partial on answerable). So the true single-knob effect on answer quality is **+4 rows of partial-grade improvement, +2 rows net on not_found handling, zero change in strict correct** — and the "12 vs 5" framing is roughly half scoring artifact.

### 1.5 Why answers could improve while retrieval fell 8 points

The two motions happen on disjoint rows:

- **The retrieval loss is concentrated and hits already-dead rows.** hit@1 flipped on exactly 10 of 104 answerable rows: 9 down (7 class-A hijacks — `arch-05/phone-09/study-04/viz-02/viz-07/viz-08/viz-10-typed` — plus the `rcpt-08` pair, where a clean rewrite reordered which Mr D.I.Y. receipt led) and 1 up (`rcpt-05-typed` — the baseline's only genuine ranking failure, fixed because the rewrite added "chocolate bars"/receipt vocabulary). Of the 7 hijack losses, baseline verdicts were: 2 already false_abstain, 3 wrong (now false_abstain or still wrong), and only 2 partial (`arch-05-typed`, `viz-10-typed`) — so 8 points of hit@1 bought back only 2 previously-passing rows.
- **Every answer-mediated improvement happened with the gold retrieved in both arms.** At the answer-pass level the rewrite never recovered a document the baseline missed, with the single exception of `rcpt-05-typed` — and that rescue was squandered: with `bad_receipt_014.jpg` (ASIA MART) at rank 1, the model answered "SAM SAM TRADING CO", the header of the rank-2 receipt, and stayed wrong. All 14 answer-mediated improvement flips are **distractor-lottery effects**: at top_k=2 with rerank off, the model frequently reads the rank-2 file; replacing a confusable same-genre neighbor (another chart, another scene photo, a second receipt) with an obviously-irrelevant file redirects it to the gold.
- **The date keywords are a large part of that lottery — an accidental, degenerate solo gate.** Clock tokens embed dates, and the corpus files with the most prominent printed dates are receipts: `bad_receipt_005.jpg` is rank 1 or 2 on effectively every pure clock query (6 of 7 class-A answerable losses, plus nf-01/nf-05). On class-C rows the same pull swaps a plausible distractor for a receipt next to an intact gold — which is exactly what fixed both `phone-02` halves. The bug that destroyed 12 typed retrievals is the same mechanism that produced several of the full-side gains.

The paradox, resolved: **retrieval quality fell where answers were already failing, and answer quality rose where retrieval had never been the problem.** Neither motion is the rewrite "working" in the intended sense; the gains are a top-2 composition lottery that a rerank or solo gate would dominate deliberately.

### 1.6 How much judge noise is in any cross-run comparison

- The two judge sessions disagreed with the same deterministic verdicts 23 times here vs 11 in the baseline — this judge overrides more, mostly generously (16 upgrades: 9 partial->correct, 7 wrong->partial; 5 downgrades partial->wrong; 2 category corrections).
- On the 41 rows where both arms produced byte-identical answers, the two sessions returned different verdicts 4 times: a **~10% per-row verdict-noise floor** for cross-run judge comparisons on this rubric (`47e93a279e70cef9`, judge `claude-opus-5` both runs).
- Practical rule this implies: A/B deltas on judged `correct` smaller than ~4-5 rows are indistinguishable from judge noise; the deterministic verdicts (identical scorer both arms) are the safer paired-comparison basis, with the judge used for direction and diagnosis.

---

## 2. Abstention

Judge false_abstain 46 vs 44; correct_abstain 11 vs 9; deterministic correct_abstain 10/16 vs 8/16 (all verified against `judge_verdicts.json` / `metrics.json`).

The +2 false_abstain is churn, not a threshold shift: 8 rows entered the bucket (`arch-04-typed`, `arch-05-typed`, `arch-08-full`, `phone-07-typed`, `phone-08-typed`, `rcpt-04-typed`, `rcpt-08-typed`, `study-04-typed`) and 6 left it (`rcpt-02-full`, `rcpt-06-typed`, `rcpt-07-typed`, `rcpt-08-full`, `study-01-full`, `viz-05-full`). All but `arch-08-full` (timestamp divergence) trace to changed retrieval. Of this run's 46 false abstains, the gold (or an acceptable twin) was in the retrieved set for 38 — same disease as the baseline (38/44). Raw structured abstentions: 51 vs 49.

**Downstream of the answerable date-echo rows.** Taking the supervisor's 13 answerable echo rows: the 8 with topic erased (class A) split exactly in half — **4 abstained on the garbage** (`arch-05-typed` as the prose "Not found", `phone-09-typed`, `study-04-typed`, `viz-07-typed`) and **4 confabulated from it**: `viz-08-typed` answered "31.00" (the printed total of `bad_receipt_005.jpg`), `study-10-typed` recited a receipt line ("item 'Plastic', quantity 2, RM 15.50 each"), `viz-02-typed` answered "Tweet #2", and `viz-10-typed` answered "ob means outer" — an ungrounded parametric guess produced with two receipts as the only files in the prompt. So when retrieval is pure garbage the abstention machinery catches it only half the time; the other half the user gets a fluent wrong answer read off an unrelated receipt. The remaining 5 echo rows (class B, topic retained: `viz-05`, `study-02`, `study-06`, `study-08`, `study-09`, all typed) kept gold at rank 1 (class-B hit@1 0.857 vs 0.810 baseline) and mostly kept their baseline verdicts; `study-06-typed` actually improved to partial. **Class B is not "destroyed"; only class A is.**

**The not_found probes (16): correct_abstain 9 -> 11 is a measurement artifact of retrieval churn, not improved discipline.** Six probes flipped, all via changed retrieval:

- Gains: `nf-08-typed` (class A: "chem notes" was never searched — the clock query retrieved `deck_013.pdf` + `info_034.jpg`, so irrelevant that the model declined; the baseline searched the real topic and false-answered "Electric field"). `nf-07-typed` (class B: the date suffix pushed the vaccination infographic — the baseline's false-answer source — out of the top 2). `nf-02-typed`, `nf-06-typed` (class C: same query text as baseline, date keywords swapped the distractors, the echo answers disappeared).
- Losses: `nf-01-typed` ("passport scan" -> clock query -> answered "31.00" off `bad_receipt_005.jpg`) and `nf-05-typed` ("transcript" -> "August 30 2026 time" -> "31.00" again). The hijack manufactured two false answers that did not exist in the baseline. (`nf-04-typed`, hijacked in both arms' spirit, answered "1 January (one day off)" in this arm — a false answer in both arms, so no flip.)

On the supervisor's specific question about `nf-01/03/08-typed`: **nf-01-typed did not "correctly abstain" at all — it false-answered.** `nf-08-typed` is a correct abstain for the wrong reason and should be discounted as an artifact. `nf-03-typed` kept its correct_abstain with the topic partially surviving ("lease agreement current date and time"); same verdict as baseline, verdict unaffected. Net: I would flag `nf-08-typed`, `nf-02-typed`, `nf-06-typed`, `nf-07-typed` (the entire +4 gain side) as retrieval-lottery artifacts; abstention discipline itself did not change. Related taxonomy note: the "No"-in-prose gap moved rather than closed — the baseline's `nf-07-full` answered "No" with the flag unset; this run's `nf-03-full` did the same (this run's `metrics.json` `not_found_flag_missing: 1`), and both judges scored the prose denial correct_abstain while the matcher called it false_answer.

---

## 3. Typed vs full under rewrite

The baseline finding was: phrasing changes failure mode, not rate (their 45-pair test: typed-only success 2 vs full-only 6, p = 0.29). **That does not replicate here — typed now loses on rate, decisively.**

Paired within this run over the 60 pairs, excluding the 3 infra-error pairs (`phone-05`, `phone-11`, `study-03`):

| Test (judge verdicts) | This run | Baseline |
|---|---|---|
| Answerable pairs (n=49), success = correct-or-partial, discordant | typed-only **1** vs full-only **16**, p = 0.0003 | 2 vs 6, p = 0.289 |
| All 57 pairs incl. not_found (success = C/P/CA) | 2 vs 18, p = 0.0004 | 2 vs 9, p = 0.065 |
| `wrong` discordant | typed 16 vs full 5, p = 0.027 | 13 vs 5, p = 0.096 |
| `false_abstain` discordant | typed 11 vs full 7, p = 0.48 | 5 vs 9, p = 0.42 |

Per-arm totals show it is a two-sided motion — rewrite hurt typed and helped full simultaneously. Judge success (C/P/CA): typed 14 -> 10, full 16 -> 26. Cross-arm paired per half (n = 59/58 completed): **full improved on 8 rows and regressed on 0 (p = 0.008)** — the cleanest positive result in this run — while **typed churned 7 up / 9 down (p = 0.80)**, i.e. no net rate change on typed versus its own baseline, despite 12 destroyed queries; the keyword/distractor lottery paid back elsewhere what the hijack burned.

The subset split inside this run is the surprising part:

| Typed-half contamination | pairs | typed-only success | full-only success | p |
|---|---|---|---|---|
| A (query replaced) | 12 | 1 | 6 | 0.125 |
| A+B (any clock text in query) | 30 | 2 | 9 | 0.065 |
| C+clean typed | 27 | 0 | 9 | 0.004 |

The typed-vs-full gap is **not** concentrated in the hijacked pairs — clean-typed pairs show the sharpest full advantage, because the full halves are where rewrite's improvements landed. So the honest statement is not "the echo destroyed typed"; it is: **rewrite turns one product into two — a genuinely better one for verbose questions and a coin-flip generator for terse ones** — and the typed-vs-full rate gap this run shows is mostly rewrite lifting full, plus the hijack truncating typed's upside.

---

## 4. Failure clusters, and the printed-number replication

**Baseline finding 2 replicates.** Same operationalization as the baseline report (a question is a number question if any golden `key_facts` entry matches `\d[\d ,.]{2,}`; denominator = the 93 answerable items surviving the baseline's structural segregation of 11: 3 HTTP-400, 6 never-indexed golds, 2 `study-08` page-cap — identical row sets in both arms):

- This run: number questions abstain **34/60 (57%)** vs non-number **7/33 (21%)**, Fisher two-sided p = 1.1e-3 (deterministic verdicts: 55% vs 21%, p = 2.1e-3).
- Baseline recomputed identically: 34/60 (57%) vs 4/33 (12%), p = 2.2e-5 — matching their published numbers exactly.
- The number-side rate is not just equal in aggregate but nearly frozen row-for-row (34 both arms). The ratio compressed from ~5x to ~3x only because the hijack added abstains to three non-number rows; removing the 7 hijack-retrieval-doomed rows gives 55% vs 18% (p = 1.1e-3). **The reading limitation is untouched by the rewrite knob, as it should be — it lives in the answer stage.**

Cluster map of this run's failures (judge verdicts, with section 1/2 doing the causal work):

1. **Silent refusal over a correct retrieval — still the biggest bucket.** 46 false abstains, 38 with gold retrieved, dominated by printed-number targets (`arch` family 17/20; `tables_fr`, `receipts_phone` unchanged from baseline).
2. **Neighbor-file answering.** About half the 33 wrongs quote text verifiably present in the other retrieved file (the judge's estimate of ~16, consistent with my spot checks: `phone-08-full` "5 stars" from the rank-2 period-tracker popup, `study-09-full` Res2Net/PVT from `arxiv_027.png`). This is the same disease as the distractor lottery of section 1.5 seen from the losing side.
3. **Hijack garbage rows** (new, this arm only): 12 class-A rows, split half abstain / half confabulate (section 2).
4. **Degenerate echo answers** shrank 7 -> 4 (section 5) — three of the baseline's echoes were cured by luck (distractor swaps), not by any fix.

---

## 5. Reporting-bug replication (baseline section 5/8 claims, recounted on this run)

All five reproduce, with drift in magnitude only:

- **Query-echo answers** (non-empty answer whose token set is a subset of the question's): **4, all typed** (`arch-06-typed` "Fort Morgan Sugar Factory", `rcpt-02-typed`, `rcpt-09-typed`, `study-07-typed` "Attribute SBM"), vs 7/7-typed in the baseline. `viz-06-typed`, `nf-02-typed`, `nf-06-typed` stopped echoing because their retrieval changed — the echo mechanism is intact, three of its trigger rows moved.
- **`not_found_topic` schema-example leak**: **12 rows carry "a landlord's emergency phone number"** (`arch-01-full`, `arch-03-typed`, `arch-06-full`, `rcpt-07-full`, `rcpt-09-full`, `study-06-full`, `study-06-typed`, `study-08-full`, `viz-01-full`, `viz-02-full`, `viz-03-full`, `viz-05-full`) — 10 full / 2 typed; baseline had 12 (10 full). The `src/answer.py:233/:285` example strings remain user-visible output.
- **`not_found_topic` verbatim question echo**: **35 rows, 100% typed** (baseline 33, 100% typed). The field still never contains an actual summarized topic.
- **Citation degeneracy, not hallucination**: 38 answers carry 57 citations; **0 of 57 name a file absent from the prompt** (checked against each row's assembled prompt in the LLM log). Shapes: 20 lists are the whole prompt file list in prompt order, 11 are exactly prompt File 1 (the worst-ranked file, given the reverse-rank prompt layout), 6 are exactly File N (the rank-1 file), **1 of 38 is a genuine subset**. `metrics.json`'s `hallucinated_citations: 0.240` is again the mean count of non-gold citations, not invented paths.
- **`sources_used` header-echo destroying citations**: **9 entries across 9 items** arrive as `"--- File N: <path> ---"` and are dropped by the exact-match guard (`arch-02-typed`, `nf-05-typed`, `phone-01-typed`, `phone-02-full`, `phone-02-typed`, `phone-09-typed`, `study-06-full`, `viz-01-full`, `viz-07-typed`); **4 of the 9 named the gold file** (`phone-01-typed`, `phone-02-full`, `phone-02-typed`, `viz-01-full`). The last three of those are judge-**correct** answers that the judge then dinged for citing the wrong file (`viz-01-full` "only citation is arxiv_025.png"; both `phone-02` rows "cites bad_receipt... instead of the gold photo") — **the model actually cited the gold in all three; the parse bug deleted it.** A quarter of this run's correct answers look citation-broken because of a string-strip bug.
- Also re-confirmed: `solo_gate.fire_rate: 0.042` is published in `metrics.json` although `run.json` stamps `solo_gate_structurally_off: true` — the same phantom-gating inference bug the baseline documented.

---

## 6. The three HTTP 400s — same rows, and why the rewrite could never have saved them

`study-03-full`, `phone-05-typed`, `phone-11-full` — identical qa_ids to the baseline, each `400 Bad Request` from `http://127.0.0.1:9400/v1/chat/completions`. From this run's `raw/worker_answer.log`: llama-server rejected **16,551 / 17,761 / 17,596 tokens** against the 16,384 window (baseline: 16,527 / 17,785 / 17,598 — within ~25 tokens of each other on two rows despite different queries).

The query-independence is now demonstrated, not assumed:

- The widening trigger never sees the query: `classify_and_config(question)` at `src/stage2/search.py:771-781` classifies the **raw question**, identical across arms, and widens LIST_ALL rows to `LOCAL_MAX_TOP_K = 12`. The 7 widened-and-completed rows are the same qa_ids in both arms (`arch-06-full`, `nf-06-full`, `phone-05-full`, `phone-07-typed`, `rcpt-01-full`, `rcpt-08-typed/full`), and the retrieve-phase sweep confirms 12-deep retrieval for the 3 crashed rows.
- The answer-pass rewrites for the 3 rows (recovered from `llm-2026-08-30T12-10-46Z.log`, since the enriched rows lost them) were clean, on-topic, and different from the baseline's raw questions ("solar slide deck 50 kW system cost annual energy output", "workout app screenshot numbered exercise list exercises", "pink bunny period tracker app cycle interval period duration pop up request").
- `phone-05-typed` even assembled a **different 7-file prompt** than the baseline's (5 of 7 files differ) — and still overflowed by ~1.4k tokens. `phone-11-full` had the same 7 screenshots in a different order; `study-03-full` the same 4 files / 7 images.

Root cause unchanged from the baseline's report: the trimmer's flat 6,000-char image cost admits at most 7 images, and 7 real images of these types cost 16.5-17.8k tokens. Any query wording that retrieves 12 image files for these enumeration questions produces a 7-image prompt that exceeds 16,384. The supervisor's expectation is confirmed, with one precision upgrade: it is not that "the same 12 files" arrive — for `phone-05-typed` they demonstrably do not — it is that the question-classifier plus the image-cost underestimate make the crash a property of the question, not of the retrieval.

One footnote: the retrieve-phase re-rewrite of `phone-11-full` (in `llm-2026-08-30T12-45-43Z.log`, 08:45 EDT) emitted keywords containing `"EDT"` and `"2026-08-30 08:45"` — an independent, later reproduction of the clock leak within the same run.

---

## 7. Ops: where the 374 s went

Answer wall 2073.8 s vs 2447.5 s (run.json phases), a 373.7 s saving **despite** rewrite adding one LLM call per question. Per-stage, from `latency_s` on all 120 rows:

| Stage | This run (sum / p50 / p95) | Baseline (sum / p50 / p95) |
|---|---|---|
| rewrite | 146.8 s / 1.17 / 1.62 (max 3.09) | — |
| retrieval | 51.7 s / 0.33 / 0.48 | 63.8 s / 0.36 / 0.64 |
| generation | 1873.1 s / 12.57 / 38.64 | 2381.1 s / 14.95 / 50.69 |
| total | 2071.6 s / 14.29 / 39.94 | 2444.9 s / 15.41 / 51.10 |

`metrics.json` agrees (p50 14.4 vs 15.5; p95 41.0 vs 52.2). The entire saving sits in generation (-508 s). Decomposition using the natural control from section 1.2:

- **On the 43 byte-identical prompts, generation ran 231.8 s faster in this run (706.6 vs 938.4 s; paired per-row delta mean 5.4 s, median 2.2 s).** Same model, same server flags, same machine, identical inputs — this is host-level speed variance, not the rewrite. The obvious candidate: the baseline's answer phase started immediately after its own 2,514 s ColQwen indexing burn on the same M1 Max (its `index_store.hit` is false; this run mounted the store and did no indexing), so it ran hotter/contended. Extrapolated to all 117 rows, this confound alone spans roughly 260-630 s (median- vs mean-based), bracketing the whole observed saving.
- On the 74 changed prompts the saving is 275.0 s, i.e. *less* per-row than on identical work — any genuine rewrite-side effect (more abstentions: mean response 305 vs 420 chars on those rows; smaller hijacked-receipt prompts) is second-order against the host effect.

**Founder-facing conclusion: do not book the wall-clock win to rewrite.** Rewrite's true marginal cost is +1.2 s per question (+147 s per 120), and its true marginal generation effect is small and mixed; the observed speedup is an artifact of run scheduling. If latency comparisons matter in future arms, either interleave arms or record a per-run thermal/load baseline.

---

## 8. The 14 golden-set issues

From this run's `judge_verdicts.json` `golden_issues` (recorded, **not** applied — `golden.json` is untouched, `golden_sha` unchanged):

**Repeats of the baseline's 4 known amendments (2 of 4):**
- `viz-06-typed` — over-specified "1.7 million": same defect as the baseline's viz-06 amendment (baseline flagged the full half via the "1 in 10 adults" variant).
- `viz-11-typed` — gold `diagram_003.jpg` with 8 byte-identical acceptable twins; per-file citation/recall scoring uninformative. Same as baseline.
- Not re-flagged, but silently *applied in verdicts*: the `phone-03` near-miss ("Biltz" scored partial here, wrong in the baseline — one of the 4 judge-variance flips) and the `nf-07-full`-style prose-"No" taxonomy fix (this judge scored `nf-03-full`'s "No" correct_abstain over the matcher's false_answer). This is worth pausing on: **unadopted golden amendments do not stay neutral — each judge session adopts them or not, unpredictably, and that choice moved verdicts in both runs.**

**New (12):**
- Over-specified `key_facts` — facts the question never asks for (9 rows): `viz-02-typed/full` ("72%"), `viz-06-typed`, `arch-04-typed/full` ("A-3088"), `phone-02-typed/full` ("Intel"), `phone-06-typed/full` ("Pure Running").
- Compound, unscorable descriptive facts (3): `study-06-typed`, `study-07-typed`, `study-09-typed`.
- `viz-09-typed` — "$98 billion total contribution" should pin which of the file's four printed figures counts; flagged as clarification, not error.

**Does any of this change a headline conclusion? Yes — the over-specification set is load-bearing for this run's headline.** 8 of the judge's 9 partial->correct upgrades are exactly rows in that set (the ninth, `viz-10-full`, is phrasing-equivalence). Strip the upgrade policy and "12 correct" deflates to roughly the deterministic picture (3 strict correct, +4 partial-grade gains). No gold *answer* was overturned — this judge opened 24 source files and confirmed every gold value, as the baseline's judge did with 16 — so the defect is specification, not truth. Recommendation for the silver->gold review: decide the `key_facts` trims (or a required/context split) **before** the next arm is judged, because until then the correct-vs-partial boundary belongs to the judge session, not the golden set.

---

## Verdicts on supervisor claims

1. **"Rewrite replaced the ENTIRE final_query with the literal string 'current date and time Sunday 2026-08-30 HH:MM EDT' on 16/60 typed (0/60 full)", with the 16-item list.** MODIFIED. The 16 listed rows are precisely those whose `final_query` *contains* the literal "current date and time" — but only 10 of them are full replacements; `nf-03`, `study-02`, `study-06`, `study-08`, `study-09`, `viz-05` (typed) retain topic text alongside the clock string and mostly kept gold at rank 1. Conversely the list misses two genuine full replacements phrased differently (`nf-04-typed` "today's date and time", `nf-05-typed` "August 30 2026 time"): the correct full-replacement set is 12, all typed. And "0/60 full" is true only for full replacement — 5 full queries carry clock text (`phone-09-full`, `rcpt-02-full`, `rcpt-04-full`, `rcpt-07-full`, `rcpt-09-full`) and 8 more carry clock keywords, which demonstrably changed full-side retrieval (section 1.1). Total clock contamination: 52 of 117 completed rows.
2. **"Retrieval hit@1 dropped 0.933 -> 0.856."** CONFIRMED (0.9327 -> 0.8558, n=104). Decomposition: 9 rows down (7 class-A hijacks + the 2 `rcpt-08` rows on a clean rewrite), 1 row up (`rcpt-05-typed`, the baseline's one genuine ranking failure, fixed by the rewrite and then wasted by the reader).
3. **"Same 3 HTTP-400 casualties in both arms: study-03-full, phone-05-typed, phone-11-full."** CONFIRMED, and the expected mechanism is verified with a sharpening: the enumerate widening keys off the raw question (identical across arms), and the overflow is query-independent to the point that `phone-05-typed` crashed at ~the same token count with 5 of 7 prompt files different (section 6).
4. **Judge scoreboards (12/13/33/46/11/5 vs 5/16/39/44/9/7; 23 vs 11 disagreements; 14 golden issues).** CONFIRMED against both `judge_verdicts.json` files.
5. **Deterministic metrics (correct 0.029 both; partial 0.192 vs 0.154; wrong 0.346 vs 0.394; false_abstain 0.433 vs 0.423; correct_abstain 10/16 vs 8/16).** CONFIRMED against both `metrics.json` files.
6. **Implied framing "rewrite ON improved judge-correct 5 -> 12".** MODIFIED, and this is the report's central correction: +3 of the +7 is judge variance on byte-identical answers, +4 is real but partial-grade improvement amplified by judge leniency tied to flagged golden-set defects; strict deterministic correct is 3 = 3. The defensible positive claim for this arm is narrower and different: **rewrite helped full-phrasing questions (8 up, 0 down, p = 0.008) and not_found handling (net +2, itself retrieval-lottery), while adding a systematic clock-hijack failure on terse queries that destroyed 12 of 59 typed searches and manufactured 2 false answers.** The single highest-leverage fix is removing (or fencing) the `_timestamp_prefix()` injection at `src/llm.py:317` for the rewrite call, which would keep the full-side gains and delete the entire class-A failure mode.

## What this comparison can and cannot support

It supports: the rewrite knob's effect on this corpus at top_k=2/rerank-off/16K-local, measured pairwise on identical questions, indexes, and rubric. It cannot support: any claim about strict-correct improvement (judge-noise floor ~10% of identical-answer rows; use deterministic verdicts for regressions), latency effects (host confound, section 7), or category-level shifts smaller than the golden-set specification issues (section 8). The three 400 rows should stay excluded from any cross-arm answer-quality claim, as both judges advised.
