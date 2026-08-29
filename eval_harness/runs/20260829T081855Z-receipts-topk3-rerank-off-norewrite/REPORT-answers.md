# REPORT — answers analysis

**Run:** `20260829T081855Z-receipts-topk3-rerank-off-norewrite`
**Config:** lfm-local (LFM2.5-VL-3B Q6_K) · `top_k=3` · **`rewrite=false`** · rerank OFF · `solo_margin=0` (gate structurally off) · temp 0 · `n_ctx` 16384 · fast/ColPali tier only
**Dataset:** `receipts`, 148 scanned JPEGs. Golden `a3b05ea95c052a65`, 120 items / 60 pairs, **SILVER** (`human_verified: false`, 114/120 model-authored).
**Backend** `c823a44` — identical to the contrast run.
**Contrast run:** `20260829T065335Z-receipts-topk2-rerank-off` (`top_k=2`, `rewrite=TRUE`, same golden, same backend SHA).

**Sources.** `metrics.json`, `answers_enriched.json`, `judge_verdicts.json`, `run.json`, `raw/answers.jsonl`, `raw/worker_answer.log`, and the answer-stage LLM log `raw/appdata/logs/llm-2026-08-29T08-19-38Z.log` (241 records = 120 requests + 120 responses + session header; **zero rewrite records, as expected with `rewrite=false`** — the prior run's log carried 240 records of which 120 were rewrite calls).

**Method.** All 120 questions joined 1:1 to their answer-stage request/response pair by the verbatim question text recovered from the prompt's trailing `Now answer this question: …` line (120/120 matched, 0 leftover records), for **both** runs. Pre-guard generations were recovered from `response.content`; where generation ran past `LOCAL_MAX_TOKENS` (`src/llm.py:49`, 2048) and the JSON is truncated, `answer` and `sources_used` were re-extracted with a tolerant parser. The groundedness guard was re-executed by importing the shipped `src.grounding` and reconstructing `context_text` exactly as `src/answer.py:887-893` builds it. Deterministic fact matching reuses `fact_in_text` copied verbatim out of `eval_harness/harness/enrich.py`.

---

## ⚠️ Read this before any number below

**Two axes moved between the contrast run and this one: `top_k` 2→3 AND `rewrite` on→off.** No answer-side difference in this report is attributable to a single knob by the design of the run. Every comparative claim below carries an explicit attribution verdict (`top_k` / `rewrite` / **either**), and §8 collects them.

One structural fact does a lot of work in that attribution and is worth stating up front, because it narrows the space:

> **`rewrite` has no direct channel into the answer prompt.** I diffed the answer-stage user messages across runs for matched `qa_id`s. Both runs put the **raw** question into `Current question: …` and into the trailing `Now answer this question: …` — verified on 120/120 rows in *both* runs (`rewritten_query.query == question` on all 120 rows here; the prior run's rewritten query never appears anywhere in its answer prompt). The system prompt is byte-identical. The **only** ways an answer prompt differs between the two runs are (a) the `Current date and time:` line, (b) which file paths appear, (c) how many files appear.

So `rewrite` can only affect the answer stage *by changing which files were retrieved*. That does not make it innocent — a different distractor set is a real difference — but it means any effect whose mechanism is about *the number of files* is far more plausibly `top_k`. I use that reasoning explicitly and label it as inference, not proof.

**Do not quote the 0.8% correct rate as a model-capability result.** As in the prior run it is dominated by post-generation code paths (§1, §2, §3). The achievable ceiling for this arm was ~53% before the model wrote a single token (§1.5).

---

## 0. Headline: the guard reproduced exactly, the ordering bug reproduced and sharpened, and a *new* failure appeared in `sources_used`

| | prior (k=2, rewrite on) | this (k=3, rewrite off) |
|---|---|---|
| correct / partial / wrong / false_abstain (judge, n=120) | 3 / 4 / 56 / 43 | **1 / 8 / 62 / 35** |
| correct_abstain / false_answer (judge) | 4 / 10 | **9 / 5** |
| deterministic correct / partial / wrong / false_abstain | 0 / 6 / 57 / 43 | 1 / 5 / 66 / 34 |
| harness abstentions (`abstain_source='flag'`) | 45 (41 guard + 4 errors) | **41 (32 guard + 5 model + 4 errors)** |
| model emitted `not_found:true` | **0 / 116** | **5 / 116** |
| responses that ran past `max_tokens` | **0 / 116** | **10 / 116** |
| items emitting ≥1 verbatim in-prompt path | 91 / 116 | **45 / 116** |
| `zero_citation_answers` (enrich.py:534) | 9 / 63 graded = 14.3% | **45 / 72 graded = 62.5%** |
| p50 / p95 answer latency | 15.0 s / 20.0 s | 20.3 s / **58.1 s** |

Three things are true at once, and they are separable:

1. **The groundedness guard reproduced perfectly** (§1). Accuracy 1.000 again, and the reduced rule — *delete any answer containing a number ≥ 100* — again predicts every guard firing with zero errors. It destroyed 5 correct and 1 partial answer this time.
2. **The prompt-order reversal reproduced, and the 3-slot design answered the question the 2-slot design could not** (§3): the effect is **anti-recency, not pro-primacy**. Slot 2 (middle) performs like slot 1 and both crush slot 3. The model's failure is specifically with the *last-presented* file, which is exactly the best-ranked one.
3. **A new, previously absent failure mode appeared: `sources_used` generation collapses** (§2). 10 responses ran away to the 2048-token cap emitting thousands of junk array elements; a further ~25 substituted `"1"` / `"File 2:"` labels for paths. This is the whole citation collapse, it is generation behaviour, and it also explains the p95 latency blow-up (the 10 runaway generations took a median 58.2 s against 19.8 s for the rest; the prior run had **no** response longer than 474 characters).

---

## 1. Prior finding #1 — the groundedness guard: **REPRODUCED, exactly**

### 1.1 Mechanism (re-verified against source, unchanged)

`src/answer.py:887-889` builds the evidence text as

```python
_blocks = [b for _d, blocks in per_file_blocks for b in blocks if isinstance(b, str)]
```

— text blocks only; image blocks are excluded by construction. `looks_fabricated()` (`src/grounding.py:115-136`) returns True when **every** numeral in the answer is absent from that string and at least one numeral survives the `MIN_INTERESTING = 100` filter (`src/grounding.py:31`, applied in `numerals()` at `:40-50`).

**Re-measured on this run's prompts: 113 of 120 user messages contain zero characters of text between the `--- File N: … ---` headers.** The 7 exceptions are the widened `LIST_ALL` prompts (§6), and their only text is harness boilerplate — `"(Context note: 5 lower-ranked source file(s) were omitted to fit the local model's context window: …)"`. **0 of 120 prompts contain any document text.** `context_text` is empty or boilerplate on every single call, exactly as in the prior run.

The guard therefore again reduces to: **delete any answer containing a number ≥ 100.**

### 1.2 Confusion matrix — REPRODUCED at accuracy 1.000

Re-running the shipped predicate over all 116 non-errored items:

```
predicate = model_not_found OR looks_fabricated(generated_answer, reconstructed_context_text)
TP = 37   FP = 0   FN = 0   TN = 79      accuracy = 1.000
```

And the *reduced* rule, applied only to the 111 items where the model did **not** set `not_found` itself:

```
predicate = "answer contains a numeral >= 100"
TP = 32   FP = 0   FN = 0   TN = 79      accuracy = 1.000
```

Perfect separation, again. The 37 harness abstentions decompose as **32 guard deletions + 5 model-initiated `not_found:true`**; add the 4 backend errors and you get the 41 rows carrying `abstain_source='flag'`. (Note for the record: the brief's "41 abstentions, all `abstain_source='flag'`" is right about the field but 4 of the 41 are HTTP 400s, not abstentions — see §6.)

**Verdict: REPRODUCED.** Prior run 41 TP / 0 FP / 0 FN / 75 TN; this run 37 TP / 0 FP / 0 FN / 79 TN. The guard fired 9 times less often, and the reason is visible in the generations, not in the guard: 5 answers were pre-empted by the model's own `not_found` (§4) and several more were replaced by short degenerate strings (§2).

### 1.3 What it destroyed this time — 5 correct, 1 partial

Counterfactual scoring of the 32 deleted generations with the harness's own `fact_in_text`:

| outcome of the deleted text | n |
|---|---:|
| **CORRECT** (all gold `key_facts` present) | **5** |
| partial | 1 |
| wrong | 22 |
| not-found probe (guard masked a fabrication) | 4 |

The 5 correct answers the guard deleted:

| qa_id | deleted generation | gold `key_facts` |
|---|---|---|
| `rcpt-b-01-typed` | `RM 110.00` | `110.00` |
| `rcpt-b-06-full` | `SS3-154439` | `SS3-154439` |
| `rcpt-c-02-typed` | `Koh Seng Ladder Date: 04/12/2017` | `04/12/2017` |
| `rcpt-d-01-typed` | `Rocku Yakiniku Total: 181.55` | `181.55` |
| `rcpt-e-06-typed` | `Invoice No: 18291/102/T0380` | `18291/102/T0380` |

Plus one partial: `rcpt-a-10-typed` produced `170.00` against gold `['363.00','170.00','193.00']`.

**Counterfactual headline:** with the guard off and nothing else changed, deterministic correct would be **1 → 6** and partial **5 → 6**. Note `rcpt-d-01-typed` and `rcpt-e-06-typed` are also on the judge's "false abstention with the answer on screen" list — the judge attributes them to the reader declining. It did not decline; it read the receipt correctly and the guard deleted the read. That part of the judge's failure-pattern #3 should be withdrawn, as it was for the prior run.

Three of the five are the same *pairs* the guard killed last time (`rcpt-b-06`, `rcpt-c-02`, `rcpt-e-06`), which is what you would expect: the destroyed set is determined by the magnitude of the gold value, not by the config.

### 1.4 Did it catch genuine fabrications? 4 of 9 — better than prior, still for the wrong reason

On the 14 not-found probes the model produced a fabricated answer 9 times (14 minus 3 model-initiated declines minus 2 one-word "No" declines). The guard masked **4** of them: `rcpt-nf-01-typed` (a whole Bakalima letterhead OCR'd off a distractor), `rcpt-nf-03-typed` (verbatim regurgitation of the system prompt's own `CSC-105 has 4 credit hours[1]` citation example), `rcpt-nf-05-typed` (`100.00`), `rcpt-nf-07-typed` (`3-1708032 [1]`). Prior run it caught 2.

It missed the 5 fabrications whose numbers are below 100 or absent: `rcpt-nf-02-full` `RM 77.40`, `rcpt-nf-04-typed` `moonlight cake house`, `rcpt-nf-05-full` `4.20`, `rcpt-nf-06-full` `30.48`, `rcpt-nf-06-typed` `Tanjongmas Book Centre`.

As a *wrongness* filter the guard actually scores respectably on this run — 26 of 32 firings suppressed something bad (22 wrong + 4 fabrications) against 6 casualties. But it is selecting on **magnitude**, not on grounding, and that is why §1.5 holds.

### 1.5 The ceiling — REPRODUCED at 50/106

Applying the same rule to the golden set: **50 of the 106 answerable items have `key_facts` that, stated alone, contain a numeral ≥ 100** and are therefore structurally undeliverable in this configuration regardless of model quality. Identical to the prior run's figure. **The maximum achievable `correct` for this arm was ~53%, not 100%**, and nothing in `metrics.json` or `report.md` says so.

`MAGPIE_STRICT_GROUNDING=0` still does not fix this — that flag only gates `strip_generated_blocks` at `src/answer.py:892`; `looks_fabricated` at `:894` has no kill switch.

**Attribution:** none needed. This finding is config-independent — it is a property of the image-only corpus and the guard, and it reproduced across a two-axis change.

---

## 2. The citation collapse — the biggest surprise, and it is a *generation* failure in `sources_used`

`zero_citation_answers` (enrich.py:534: `not magpie_cited and verdict in (correct, partial, wrong)`) went **9 → 45**; as a rate over graded answers, **9/63 = 14.3% → 45/72 = 62.5%**. `citation_precision` 0.184 → 0.060, `citation_recall` 0.226 → 0.112, `citations.cited` (a *mean count*, not a rate — prior report's caveat still stands) 0.755 → 0.519.

### 2.1 It is not the harness filter and it is not the guard. The model stopped emitting paths.

Classifying every `sources_used` entry against the paths actually in that item's prompt:

| entry shape | prior (k=2) | this (k=3) |
|---|---:|---:|
| verbatim in-prompt path (survives `_normalize_path_for_match`) | 131 | 86 |
| path with a `File N:` / `--- File N:` prefix (dropped, **recoverable**) | 41 | 47 |
| bare index — `"1"`, `"File 2"`, `"file_3"` (dropped) | 20 | **755** |
| non-path junk | 29 | **1989** |
| **total entries emitted** | **221** | **2877** |

Per item (non-errored, n=116 each):

| | prior | this |
|---|---:|---:|
| emitted ≥1 verbatim path | **91** | **45** |
| only recoverable prefixed paths | 10 | 21 |
| nothing usable | 14 | 35 |
| empty list | 1 | 15 |

And the runaway: **10 responses hit `LOCAL_MAX_TOKENS = 2048`** (`src/llm.py:49`) mid-array, producing 3.2 KB–7.3 KB of content. The prior run's **longest** response was 474 characters and **none** was truncated. Examples of what the model emits after the opening bracket:

- `rcpt-a-06-typed` — `{"answer": "5.30", "sources_used": [ "]}</answer> 1.0]</response> 2.0]</answer> 3.0]…` (repeating to the token cap)
- `rcpt-c-09-typed` — `{"answer": "Restoran Wan Sheng is more expensive", "sources_used": [":[1], [2], [3]]} 1] 2] 3] 4] …` up to `2790]`
- `rcpt-d-05-full` — `{"answer": "Cash", "sources_used": ["1", "2", "3", … "139"…` (the only one of the 10 that `_close_truncated_json`, `src/llm.py:792`, failed to rescue — hence the `(model output could not be parsed into Answer)` placeholder the judge flagged as its 10th disagreement)
- `rcpt-e-04-typed` — `"sources_used": [":[1], [2], [3]}]}```json```" , "not_found_topic" ,"reason" ,"value" ,"message" …`

The GBNF grammar guarantees a syntactically legal `array of string`; it does not guarantee the strings are paths. The `answer` field is emitted *first* (`src/answer.py:199-207`, `sources_used` at `:208-216`), which is why the answers themselves are unaffected — mean answer length is essentially unchanged (28.5 → 25.7 chars; median 14 → 13) — and the damage is confined to the citation field.

Independent corroboration from latency: the 10 runaway generations took a **median 58.2 s** (max 62.2 s) versus 19.8 s for the other 106. That is the entire `p95_total_s` 20.0 → 58.1 regression in `metrics.json`.

### 2.2 `rcpt-b-03-full` — the identical-answer case, resolved

The brief's key exhibit. Both runs answered `4.62`. Raw responses:

```
PRIOR: {"answer": "4.62", "sources_used": ["/Users/…/receipt_X51005230605.jpg",
                                           "https://example.com/file2.txt"], …}
       -> magpie_cited = ["/Users/…/receipt_X51005230605.jpg"]

THIS:  {"answer": "4.62", "sources_used": ["File 1: /Users/…/receipt_X51005587261.jpg",
                                           "File 2: Bakalima Sdn Bhd receipt (not_found=true)"], …}
       -> magpie_cited = []
```

Nothing about the *answer* changed. The citation was lost because the emitted string acquired a `File 1: ` prefix, and `_normalize_path_for_match` (`src/answer.py:927`) handles whitespace, URL-encoding and page suffixes but not a `File N:` prefix — so the entry is dropped as a hallucinated path. Note also that the model mislabels: the path it prefixes with `File 1:` is the prompt's **File 3**. With three headers on screen it is no longer tracking the numbering.

This is the *recoverable* half of the collapse, and it was already prior finding #7 item 3.

### 2.3 Decomposition of the 28 lost citations

28 questions were cited in the prior run, graded here, and uncited here (43 lost overall; 28 once you restrict to graded rows — matching the brief). Cause per item:

| cause | n | recoverable? |
|---|---:|---|
| bare index emitted (`"1"`, `"2"`, `"file_3"`) | 11 | yes, by resolving the integer to the prompt slot |
| `File N:`-prefixed path | 7 | yes, by a regex strip |
| model emitted an empty `sources_used` | 6 | no |
| degenerate junk only | 4 | no |

Over the full 45 `zero_citation_answers`: 18 bare-index + 10 prefixed-path = **28 recoverable (62%)**, 10 emitted nothing, 7 unrecoverable junk. Caveat on the bare-index half: a lone `"1"` is genuinely ambiguous — under the system prompt's contract `[1]` indexes `sources_used`, so `"1"` as a *member* of `sources_used` is self-referential nonsense. Reading it as "File 1" is a defensible guess; count these as *plausibly* rather than certainly recoverable.

Even among the citations that did survive the filter, quality fell: precision against `gold_sources` is **17/64 = 0.266** here versus **33/96 = 0.344** prior.

### 2.4 Which axis? Evidence, and what would settle it

**Direct within-run discriminator.** 31 items retrieved **exactly the same top-2 files in the same order** in both runs — i.e. rewriting provably changed nothing about the ranking prefix — and this run simply appended a third file. On that subset:

| | prior | this |
|---|---:|---:|
| emitted ≥1 verbatim path | **26 / 31** | **12 / 31** |
| `magpie_cited` non-empty | 16 / 31 | 10 / 31 |
| response truncated at `max_tokens` | 0 / 31 | 3 / 31 |

The collapse is **the same size on the subset where the rewriter demonstrably made no difference** (26→12, −54%) as on the remaining 85 items (65→33, −49%).

**Mechanistic argument.** The number of `sources_used` entries the model attempts tracks the number of files presented: prior, 87/116 items emitted exactly 2 entries against 2 files; here, 46/116 emitted exactly 3 against 3 files. The array the model must produce grew by one ~85-character path — ~50% more path text — under a grammar that will not let it stop early. That is a direct, mechanical consequence of `top_k=3`. There is no mechanism by which swapping one distractor JPEG for another makes a model write `"1"` instead of a path — and, per the preamble, a distractor swap is the *only* thing `rewrite` can change about this prompt.

**Honest counter-evidence.** The degradation is not confined to the later array entries, which is what a pure "the array got longer" story predicts. First-entry fidelity fell too: entry 1 was a verbatim path in 91/115 prior items but only 45/111 here. Whatever changed, it changed the model's *choice of citation format* at the first token of the array, not just its stamina. I cannot explain that from prompt structure alone. There is also an unexplained clustering — 7 of the 10 runaway generations are `rcpt-c-*` items — that no config variable predicts.

**Verdict: most likely `top_k`, but formally CONFOUNDED.** I would put substantial weight on `top_k` (the same-top-2 subset plus the mechanism) and little on `rewrite` (no channel except file identity), but this run cannot prove it.

**The decisive experiment is cheap:** re-run at **`top_k=2`, `rewrite=false`**, everything else identical. That holds the file count at 2 and removes the rewriter. If `sources_used` is healthy again, it is `top_k`; if it collapses, it is `rewrite` (via distractor identity) or run-to-run instability. A `top_k=3, rewrite=on` arm would confirm from the other side.

**Also worth doing regardless of the answer:** fix `_normalize_path_for_match` to strip a leading `(---)?\s*File\s*\d+\s*:` and to resolve a bare integer to the corresponding prompt slot. That recovers 28 of the 45 zero-citation answers here and 39 of 55 dropped entries in the prior run — a win under either attribution.

---

## 3. Prior finding #2 — the prompt-order reversal: **REPRODUCED, and refined from "primacy" to "anti-recency"**

### 3.1 The reversal is still universal

`src/answer.py:832` — `ordered_blocks = list(reversed(per_file_blocks))` — unchanged. Prompt order equals exactly `reversed(retrieved)` on **113 of 116** non-errored items. The 3 exceptions (`rcpt-a-09-typed`, `rcpt-a-10-full`, `rcpt-e-10-full`) are the surviving `LIST_ALL` widenings, where 12 candidates were truncated to 7 files. So under `top_k=3`:

> **prompt slot 1 = retrieval rank 3 (worst) · slot 2 = rank 2 · slot 3 = rank 1 (best), presented last, adjacent to generation.**

### 3.2 Gold slot × verdict — the new 3-slot result

Restricting to 3-file prompts where the gold receipt occupies **exactly one** slot (n=74), judge verdicts, `correct|partial` = good:

| gold slot | good | total | rate |
|---|---:|---:|---:|
| **slot 1** (first shown, worst-ranked) | 1 | 3 | 33.3% |
| **slot 2** (middle) | 2 | 7 | 28.6% |
| **slot 3** (last shown, **best**-ranked) | **1** | **64** | **1.6%** |

Shipped answers only (excluding harness abstentions): slot 1 → 1/1, slot 2 → 2/6 (33%), slot 3 → 1/42 (2.4%).

- not-last (slots 1+2) vs last (slot 3): **3/10 vs 1/64, Fisher exact p = 0.0069**. Shipped-only: 3/7 vs 1/42, p = 0.0071.
- slot 1 vs slot 2: 1/3 vs 2/7, **Fisher p = 1.0 — indistinguishable.**

**This is the run's most valuable new evidence.** The 2-file design could not tell "the model reads the first image" from "the model ignores the last image". Three slots can, and the answer is the second one: **slot 2 performs like slot 1, and the penalty is specific to the last-presented file.** The prior report's framing — "measurably primacy-biased on image slots" — should be restated as **anti-recency on image slots**: the model does not preferentially read position 1, it fails to use the image sitting immediately before the question echo.

That is a strictly worse fact for the shipped code than primacy would have been, because the reversal at `:832` exists *precisely* to put the best file in the recency zone. Liu et al. (2023) is cited in the comment for text-token recency bias in small decoders; on this VL image path the effect is inverted, and the code is optimising for the one slot the model does not use.

Caveat on power: slot 1 and slot 2 carry n=3 and n=7. The "not-last vs last" contrast is significant; the "slot 1 vs slot 2" null is *underpowered*, not established. A run with the reversal disabled would flip the slot populations and give the comparison real n.

### 3.3 The retrieval paradox — REPRODUCED and sharpened

| | judge `correct|partial` |
|---|---|
| `hit@1 = 1` (gold ranked first → prompt slot 3) | 6/84 = **7.1%** |
| `hit@1 = 0` | 3/22 = **13.6%** |

| `first_gold_rank` | → prompt slot | good |
|---:|---|---|
| 1 | 3 (last) | 6/84 = **7.1%** |
| 2 | 2 (middle) | 2/7 = **28.6%** |
| 3 | 1 (first) | 1/3 = **33.3%** |
| 4+ / absent | not in prompt | 0/12 = 0% |

Better retrieval still produces worse answers (prior: 4.8% vs 13.0%; here 7.1% vs 13.6%), and the monotone ladder rank 1 < rank 2 < rank 3 is exactly the reversal read backwards.

### 3.4 Content attribution — which file did the answer come from?

I could not re-OCR the corpus (no text layer exists — the `.jpg`s ship without sidecars, which is *why* §1 holds). The nearest available ground truth is the golden set itself: for the 40 receipts that are the sole `gold_source` of some item, `key_facts` + `golden_answer` decimals give a partial value index per file. Taking every answer that quotes a `NN.NN` decimal, excluding decimals the question itself supplies, and keeping only cases attributable to exactly one slot:

| attributed slot | n |
|---|---:|
| slot 1 (first shown, worst-ranked) | **11** |
| slot 2 | 3 |
| slot 3 (last shown, best-ranked) | **2** |

n = 16, all unambiguous. Against a uniform-attention null of 1/3 per slot: χ² = 9.12 (df 2); P(≥11 in slot 1) = **0.004**; P(≤2 in slot 3) = 0.059.

The individual rows, with gold slot for contrast:

| qa_id | quoted | attributed slot | gold slot | judge |
|---|---|---:|---|---|
| `rcpt-a-01-full` | 77.40 | 1 | 3 | wrong |
| `rcpt-a-05-full` | 193.00 | 1 | 3 | false_abstain (guard) |
| `rcpt-a-07-full` | 68.90 | 1 | 3 | wrong |
| `rcpt-b-01-full` | 269.40 | 1 | 3 | false_abstain (guard) |
| `rcpt-c-04-full` | 15.00 | 1 | 3 | wrong |
| `rcpt-d-01-full` | 63.90 | 1 | 3 | wrong |
| `rcpt-e-03-full` | 8.20 | 1 | 3 | wrong |
| `rcpt-c-04-typed` | 346.51 | 2 | 3 | false_abstain (guard) |
| `rcpt-b-05-typed` | 2.97 | 2 | 2 | **correct** |
| `rcpt-d-02-full` | 40.49 | 2 | 2 | partial |
| `rcpt-b-03-typed` | 30.00 | 3 | 3 | wrong |
| `rcpt-d-01-typed` | 181.55 | 3 | 3 | false_abstain (guard) |

**Eight of the ten items whose gold was in the last slot answered out of slot 1 instead.** This independently corroborates the judge's hand-read attributions (`rcpt-a-01-full` "77.40 is the Sen Lee Heong total, which sat at rank 3" — rank 3 is prompt slot 1; `rcpt-d-01-full` "63.90 is the Burger King KLIA total at rank 3"), which is reassuring since the judge derived those by opening the images and I derived them from the golden index.

**Verdict: REPRODUCED** in direction and significance, at smaller n than the prior report's OCR-based 25/39 (I have 11/16). Note the prior report's headline "ZERO matched the best-ranked file presented last" does **not** hold literally here — 2 of 16 did — but 2/16 against a 1/3 null is still a suppression, not a preference.

### 3.5 One prior line of evidence **FAILED TO REPRODUCE**: the 91:10 citation preference

The prior report cited "the model names slot 1 over the last slot 91:10" as independent corroboration. Two problems, both visible now that there are three slots:

- That statistic was largely an **enumeration artifact**. In the prior run 87/116 items emitted exactly 2 entries for 2 files, listed in prompt order, so "the first path named" is slot 1 almost by construction. Here the equivalent count is 48 : 4 : 13 — still slot-1-heavy, still an ordering artifact.
- On the subset where the model names **exactly one** in-prompt file — a genuine choice — the prior run gives slot 1 : slot 2 = 22 : 10, but **this run gives slot 1 : slot 2 : slot 3 = 9 : 4 : 13.** When it picks one file, it picks the *last* one more often than any other.

So the citation channel and the answer channel point in **opposite** directions here. That matches the judge's independent observation that "citations and answers are decoupled" (`rcpt-d-03-full` cites the correct Kaison receipt and answers "AEON CO. (M) BHD"; `rcpt-b-05-typed`, the run's one correct answer, cites nothing at all).

**Consequence for the prior report:** finding #2 is still correct and still the largest lever, but **the citation evidence for it should be retired.** It rests on the accuracy data (§3.2), the retrieval ladder (§3.3) and the content attribution (§3.4), which agree; the citation data does not support it and, in this run, mildly contradicts it.

**Attribution:** the ordering effect itself is not a delta — it is a property of `src/answer.py:832` measured in both runs. The *3-slot refinement* is available only because `top_k=3`, so it is a `top_k`-enabled observation, not a `top_k` effect. The mix of gold slots shifted between runs (this run puts gold in the dead recency slot on 64/74 single-gold items because retrieval is better), and that shift **is** confounded between the two axes.

---

## 4. Abstention: the improvement is roughly half real and half guard artifact — and the `not_found_flag_missing` drop is a detector blind spot, not progress

`n_not_found = 14`. Deterministic `correct_abstain` 3/14 → **7/14**; judge 4/14 → **9/14**.

Provenance of all 14, both runs, from the raw generations:

| qa_id | this run: what the model produced | this: source of the abstention | prior: judge |
|---|---|---|---|
| `rcpt-nf-01-full` | `"Not found"` + `not_found:true` | **model** | false_answer |
| `rcpt-nf-02-typed` | `"not_found"` + `not_found:true` | **model** | false_answer |
| `rcpt-nf-04-full` | `"No receipt found"` + `not_found:true` | **model** | false_answer |
| `rcpt-nf-01-typed` | a Bakalima letterhead OCR'd off a distractor | **guard** | false_answer |
| `rcpt-nf-03-typed` | `"CSC-105 has 4 credit hours[1]…"` (system-prompt echo) | **guard** | correct_abstain (also guard) |
| `rcpt-nf-05-typed` | `"100.00"` | **guard** | false_answer |
| `rcpt-nf-07-typed` | `"3-1708032 [1]"` | **guard** | false_answer |
| `rcpt-nf-03-full` | `"No"` (flag stays false) | prose decline — **det scores false_answer**, judge overrides | correct_abstain |
| `rcpt-nf-07-full` | `"No"` (flag stays false) | prose decline — det false_answer, judge overrides | correct_abstain (judge) |
| `rcpt-nf-02-full` | `"RM 77.40"` | fabrication | false_answer |
| `rcpt-nf-04-typed` | `"moonlight cake house"` | fabrication | false_answer |
| `rcpt-nf-05-full` | `"4.20"` | fabrication | false_answer |
| `rcpt-nf-06-full` | `"30.48"` | fabrication | false_answer |
| `rcpt-nf-06-typed` | `"Tanjongmas Book Centre"` | fabrication | correct_abstain (guard) |

**Decomposition of the 3 → 7 deterministic improvement:**

- **Genuinely new not-found detection: 0/14 → 3/14.** This is real and it is the single most interesting behavioural change in the run. The prior report's §0 headline — "the model never declined once, 0 `not_found:true` in 120 calls" — **no longer holds.** The model set `not_found:true` five times here (three on nf probes, two elsewhere) and wrote a hedging string alongside it, hitting the inconsistent-state normaliser at `src/answer.py:855-868` (logged 5× in `raw/worker_answer.log` as `note: not_found=true but answer/sources_used were non-empty`). The structured `not_found` contract is exercised on this backend for the first time.
- **Guard artifacts: 2/14 → 4/14.** Four of the seven deterministic correct-abstains are the guard masking a fabrication, not the model declining. `rcpt-nf-05-typed` is the clearest: the model answered `"100.00"` and was saved by being one cent over `MIN_INTERESTING`.
- **Prose declines: 2 → 2**, but they moved from counted to uncounted (below).

**True abstention discipline is 3/14 model-initiated + 2/14 prose = 5/14 (36%)**, against the deterministic 7/14 and the judge's 9/14. Both scoreboard numbers overstate it.

### 4.1 `not_found_flag_missing` 1 → 0 is a regression in the *detector*, not an improvement in the product

`prose_abstain` (`eval_harness/harness/enrich.py:92-102`) matches a fixed pattern list including `no receipt` and `do not contain`. Prior run, `rcpt-nf-03-full` answered *"No, there is no receipt from Coffee Bean & Tea Leaf in the provided files"* → matched → counted as a prose abstention with the flag false → `not_found_flag_missing: 1`. **This run the same item answered exactly `"No"`** → no pattern match → the row is scored `false_answer` and contributes 0. `rcpt-nf-07-full` behaves identically.

So the product defect is *worse*, not better: two correct declines shipped with `not_found=false`, and the UI would render both as normal answer cards reading "No". The metric fell to 0 because the model got terser than the regex. `not_found_flag_missing` must not be read as a product improvement, and `_ABSTAIN_RE` needs a bare-negation case.

**Attribution:** the model's new willingness to set `not_found:true` arrives with a prompt that differs only in having a third image (and different distractors). **Either axis could produce it**; `top_k` is the more mechanical candidate (three receipts none of which matches the vendor is stronger disconfirming evidence than two), but three of the five firings are on absent-vendor probes where distractor identity — which `rewrite` controls — plausibly matters too. **CONFOUNDED, genuinely.**

---

## 5. Typed vs full on the answer side: **no phrasing signal survives conditioning on slot**

`metrics.json` `by_phrasing`: typed 1/53 correct, full 0/53. Judge: typed 1 correct + 3 partial; full 0 correct + 5 partial. Retrieval `hit@1` typed 0.679 vs full 0.906 — a 22.7-point gap that widened from 0.698/0.868.

The answer-side arms differ, but every difference is downstream of §1 and §3:

| | typed | full |
|---|---:|---:|
| gold in the last (dead) slot | 28 | **36** |
| gold in a not-last slot | **7** | 3 |
| gold absent from the prompt | 9 | 1 |
| guard firings | **20** | 12 |
| model-initiated `not_found` | 3 | 2 |
| runaway/truncated generations | 6 | 4 |
| judge `correct|partial` | 4 | 5 |

Full's retrieval advantage translates directly into more gold in the recency slot (36 vs 28) — under §3 that is a *penalty*, which is why a 22.7-point `hit@1` lead buys it nothing. Typed writes more identifier-shaped answers, so the guard eats more of them (20 vs 12).

**Conditioning on gold slot removes the arms entirely** (judge `correct|partial`):

| stratum | typed | full |
|---|---|---|
| gold in last slot | 0/28 | 1/36 |
| gold in a not-last slot | 2/7 | 1/3 |
| gold in several slots | 1/7 | 3/8 |
| gold absent | 0/9 | 0/1 |

Within every stratum the two arms are indistinguishable. **There is no residual phrasing signal on the answer path in this run**; it is entirely swamped by findings 1–3, exactly as in the prior run.

**One correction to the prior report, which this run's design does license.** The prior report attributed the typed/full retrieval gap primarily to rewriter damage ("typed vs full is not a phrasing-robustness result — it is slot assignment plus rewriter damage"). **`rewrite` is off here and the gap widened, 0.698/0.868 → 0.679/0.906.** The rewriter was not the cause; terse queries are simply worse in ColQwen fast-tier retrieval. That correction is single-axis-safe on the *retrieval* side (both runs sweep at depth 12), and it matters here because it removes the prior report's explanation for the answer-side arm difference and replaces it with the slot story above.

**H2′ remains unreadable from this run**, for a different reason than last time: not rewriter contamination, but the fact that the reversal converts retrieval quality into answer-slot assignment.

---

## 6. The 4 errors: **identical mechanism, identical prompts, byte-identical token counts** — with one correction to the brief

`rcpt-b-09-typed`, `rcpt-b-09-full`, `rcpt-c-10-full`, `rcpt-d-09-full` returned `Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'`, `retrieved: []`, `ranked_pre_gate: 12`.

From `raw/worker_answer.log`, the llama-server side:

```
line  643  task 6340  : request (18817 tokens) exceeds the available context size (16384 tokens)
line  675  task 6343  : request (18839 tokens) exceeds ...
line 1039  task 22340 : request (18636 tokens) exceeds ...
line 1343  task 26465 : request (20974 tokens) exceeds ...
```

The prior run's log (lines 578 / 610 / 928 / 1192) records **18817, 18839, 18636, 20974** — the same four values in the same order. Not merely the same mechanism: the same prompts, token for token.

**Correction to the brief:** these are **7-image**, not 12-image, calls. The `LIST_ALL` widener raises the fan-out to 12 candidates (`src/stage2/search.py:780`, hence `ranked_pre_gate: 12`), and the prompt builder then drops the 5 lowest-ranked to fit the window — which is what generates the `(Context note: 5 lower-ranked source file(s) were omitted…)` boilerplate that is the only text in the whole run (§1.1). Every request in this run carried either 3 images (113) or 7 (7); `extra.images` in the LLM log confirms it. **4 of 7 seven-image calls failed; 0 of 113 three-image calls did.** The three that survived (`rcpt-a-09-typed`, `rcpt-a-10-full`, `rcpt-e-10-full`) are the same three that survived last time.

Why the set is identical across a two-axis change: the widener classifies on the **raw question** in both code paths — `classify_and_config(question)` at `src/stage2/search.py:771` and `_classify_q(question)` at `src/answer.py:803` — so `rewrite` cannot reach it. And it only ever *widens* (`if klass is LIST_ALL and cfg.top_k > top_k`, `:780`), so `12 > 3` and `12 > 2` produce the same fan-out; `top_k` cannot reach it either. The run notes predicted this exactly.

**Attribution: NEITHER AXIS.** This is the cleanest control in the pair — an outcome both knobs are structurally unable to touch, and it did not move by one token. It also independently confirms the harness ran in the configuration it claims.

**Product consequence, unchanged:** this is not a harness fault to be discounted. It is a widener that ignores the vision context budget, and it is a hard ceiling on raising `top_k` for the image path.

---

## 7. Golden-set issues — 7 flagged, all real, one of them moves the headline

The golden set is **SILVER**: `human_verified: 0/120`, `model_authored: 114`. This matters. The judge opened 18 source images and overturned no gold *value*; the prior run's judge opened 16 and also overturned none. That is reassuring about accuracy and says nothing about *fact selection*, which is where all 7 issues live.

| # | issue (as logged) | real defect? | headline impact if fixed |
|---|---|---|---|
| 1 | `rcpt-b-03-*` — `key_fact "30.00"` is supplied by the question ("petrol 30 ringgit") | **Yes, with a caveat.** `"30.00"` is not *literally* in the question ("30 ringgit" is), so "matchable without reading anything" is slightly overstated — but the model answered `"30.00"` to "how many litres" and scored `partial`, which is the defect in action. The discriminating fact is `11.54`. | Deterministic `partial` 5 → 4. Judge already scores it `wrong`. **No judge-side change.** |
| 2 | `rcpt-d-02-*` — `key_fact "100.00"` is supplied by the question ("that RM100 fill-up") | **Yes, and this is the important one.** `rcpt-d-02-full` answered `"40.49"` — the fully correct litre figure, verified by the judge against `X51005724609` — and scores `partial` only for not restating a number the asker gave it. | **Correct 1 → 2** (0.9% → 1.9%) on both scorers. The one flagged issue that changes the headline. |
| 3 | `rcpt-a-09-*` — comparison item, `key_facts` are the two amounts, discriminator absent | **Yes.** `rcpt-a-09-typed` answered `"Dec"`, `-full` answered `"The 31 December bill came to more"` — both exactly what was asked, both 0/2 facts. | Deterministic `wrong` −2, `partial` +2 (the judge already overrode both). No judge-side change. |
| 4 | `rcpt-e-09-*` — same defect; `"AEON Shah Alam"` missing from `key_facts` | **Yes.** `rcpt-e-09-full` answered exactly `"AEON Shah Alam"`. | Same shape: deterministic `wrong` −2, `partial` +2. See added issue 8 below. |
| 5 | `rcpt-b-10-*` — comparison whose `key_facts` carry a date but no explicit "which visit" string, inconsistent with `rcpt-d-10` | **Yes** — the internal inconsistency is verifiable from `golden.json` alone (`rcpt-d-10` puts `"AA PHARMACY"` at index 0; `rcpt-b-10` does not). | **None.** Both `rcpt-b-10` answers are non-committal (`"Evergreen LED Stick"`, `"…for the LED sticks visit costs more"`) and stay `wrong` either way. |
| 6 | `rcpt-nf-03-full` / `rcpt-nf-07-full` — yes/no phrasing means the correct decline is the word "No", a non-empty answer | **Yes, but it is a scorer defect, not a golden defect.** The gold is fine; `deterministic_verdict` (`enrich.py:216`) keys `correct_abstain` off `flag_abstain or prose_abstain`, and `"No"` matches neither. | **Deterministic `correct_abstain` 7/14 → 9/14, `false_answer` 7 → 5** — the deterministic pass would then agree with the judge. Real headline change on the abstention block. Fix belongs in `_ABSTAIN_RE`, not the dataset. |
| 7 | `rcpt-en-01/02/03-*` — enumeration golds unanswerable at `top_k=3` | **Yes, and it is a scope defect.** `rcpt-en-01` needs 5 files, `rcpt-en-03` needs 6, `rcpt-en-02` needs the 312.70 invoice the retrieved trio never contained. The widener that would fix it is the one that produces the HTTP 400s (§6). | Marking all 6 out of scope: answerable n 106 → 100, all 6 currently `wrong`. Correct rate 0.94% → 1.00%. **Negligible.** |

### Issues I would add

**8. `rcpt-e-09` may have an ambiguous referent, and the two judges disagree about it.** The prior run's judge flagged two Popular Book Co. AEON Shah Alam receipts three minutes apart (`X51006008092` @ 30.70, `X51006008093` @ 12.15), with `gold_sources` silently picking one. This run's judge verified "30.70 vs 30.50 (Popular AEON vs Empire)" and did **not** flag ambiguity. Both can be true — the comparison against Empire is sound *and* a second AEON slip may exist — and `rcpt-nf-06-full` answering `"30.48"` here (a Popular figure, per the judge) is another hint that the Popular cluster is denser than the gold assumes. **Unresolved; needs a human to open the two files.**

**9. Restating the prior report's issue 6, which this run reproduces unchanged: 50 of 106 answerable items (47%) cannot be answered in this configuration**, because their `key_facts` consist solely of numbers ≥ 100 and the guard deletes any such answer (§1.5). No golden fix addresses this — the arm should either disable the guard or publish the ceiling alongside the accuracy number.

**10. Two items reward the golden set's own weakest facts.** `rcpt-en-01` (`key_facts: ["5"]`) and `rcpt-en-03` (`["6"]`) are single digits; they sit below `MIN_INTERESTING` and match incidental digits trivially. Flagged in the prior report, still present.

### How much weight the accuracy number can bear

Very little, for four independent reasons: (a) the gold is model-authored and unverified; (b) 47% of it is structurally undeliverable under the shipped guard; (c) the two scorers disagree on 10/120 and the judge is right on at least 9 of those; (d) the two headline-moving fixes above (`rcpt-d-02` and the yes/no scorer) would together take deterministic correct from 1 to 2 and correct-abstain from 7 to 9 — the headline is sensitive to single-item annotation choices at this scale. Report the mechanism findings; do not report the rate.

---

## 8. Attribution summary — which axis owns each delta

| finding | delta vs prior | axis |
|---|---|---|
| Groundedness guard reduces to "number ≥ 100"; accuracy 1.000 | no delta — reproduced | **neither** (property of guard + image corpus) |
| Guard firings 41 → 32; correct answers destroyed 7 → 5 | smaller | **either** — downstream of which answers got generated |
| Prompt-order reversal, 113/116 items | no delta | **neither** (`src/answer.py:832`) |
| Gold in the last (dead) slot: dominant, 64/74 single-gold items | more, because retrieval improved | **either** — `hit@1` 0.783 → 0.792, `hit@3` 0.868 → 0.887 |
| "Anti-recency, not primacy" refinement | new | **`top_k`-enabled observation**, not a `top_k` effect |
| Citation collapse: verbatim-path emission 91 → 45; zero-cite 14.3% → 62.5% | large | **probably `top_k`; formally confounded** (§2.4) |
| 10 runaway generations at `max_tokens`; p95 latency 20 s → 58 s | new | same as above — **probably `top_k`, confounded** |
| Model emits `not_found:true` 0 → 5 | new | **either**, genuinely |
| `not_found_flag_missing` 1 → 0 | detector blind spot, not improvement | **either** (model got terser) |
| Typed/full retrieval gap widened with the rewriter **off** | 0.698/0.868 → 0.679/0.906 | **rules `rewrite` OUT** as the cause of the phrasing gap |
| The 4 HTTP 400s, same items, same token counts | zero delta | **neither** — both knobs structurally cannot reach the widener (§6) |

---

## 9. What to fix, in order

Unchanged in priority from the prior report; this run adds one item and sharpens one.

1. **Do not reverse file order on the vision path** (`src/answer.py:832`). Still the largest lever, and now better characterised: the model is **anti-recency** on image slots, so the reversal aims the best evidence at the one position it does not use. 3/10 vs 1/64, p = 0.0069; content attribution 11:3:2 toward the first slot, p = 0.004 against uniform. Retire the citation-based evidence for this finding (§3.5) — it does not reproduce — and rest it on accuracy, the retrieval ladder and content attribution, which do.
2. **Give the groundedness guard an empty-context escape and a kill switch** (`src/answer.py:887-903`). It deleted 5 correct and 1 partial answer, caught 4 of 9 fabrications, and renders 47% of the golden set unanswerable. `MAGPIE_STRICT_GROUNDING=0` does not disable it.
3. **Strip `File N:` prefixes and resolve bare indices in `_normalize_path_for_match`** (`src/answer.py:927`). Recovers 28 of this run's 45 zero-citation answers and 39 of the prior run's 55 dropped entries — a win under either attribution of the collapse.
4. **Investigate the `sources_used` runaway** (`src/answer.py:208` plus the GBNF array). 10 generations burned the full 2048-token budget emitting junk array elements, tripling p95 latency; the grammar guarantees well-formed JSON and nothing about content. A per-element path constraint, or a cap on `sources_used` length, would close it. Note `_close_truncated_json` (`src/llm.py:792`) rescued 9 of the 10 and is currently load-bearing.
5. **Run `top_k=2, rewrite=false` next.** One knob against this run, and it settles §2.4 — the only open attribution question in this report. Do *not* run another two-axis config until finding 1 is fixed.
6. **Fix the widener's context budgeting** (`src/stage2/search.py:780`). Same 4 failures, same 4 token counts, two runs running. Deterministic, not flaky.
7. **Teach `prose_abstain` a bare negation** (`enrich.py:92`). Two correct declines are currently scored `false_answer`, and the product defect they represent — a decline shipped with `not_found=false` — is invisible in `metrics.json`.

## Hypotheses

- **H1** — not assessable; same category error as before. `h1_slice` reports `accuracy_by_basis.file_level_image = 0.014` on 73 eligible items; that number is produced by §1 and §3, not by evidence sufficiency.
- **H2′** — do not read this run. Newly established: the typed/full retrieval gap is **not** rewriter damage (it widened with the rewriter off), but the answer-side arm difference is fully absorbed by gold-slot assignment and guard-trigger rate (§5).
- **H5** — still blocked and still over-determined: `rerank=false`, `solo_margin=0`, `solo_gate_structurally_off: true`, fire rate 0.0.
