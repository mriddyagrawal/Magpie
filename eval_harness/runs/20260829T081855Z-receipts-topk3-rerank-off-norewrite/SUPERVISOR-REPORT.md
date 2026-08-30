# Supervisor report — 20260829T081855Z-receipts-topk3-rerank-off-norewrite

**Config.** `lfm-local` (LFM2.5-VL-3B Q6_K), `top_k=3`, **`rewrite=false`**,
rerank off, solo gate structurally off, temp 0, `n_ctx` 16384, fast/ColPali
tier only. **Dataset.** `receipts`, 148 scanned JPEGs, golden
`a3b05ea95c052a65` (120 items / 60 pairs, SILVER — `human_verified: false`).
**Backend** `c823a44`; `src/` byte-identical to the previous run's backend.
**Provenance verified**: `status: complete`, both isolation flags true,
`env_snapshot` matches the requested config on every swept axis. Index was a
store **HIT** (`5ff3e0adf0448de6`, built under the same SHA); mount 0.24 s
against a 428.1 s rebuild.

**Owner's framing.** The requested change was `rewrite` off. The owner also
chose `top_k=3`, having been told before launch that this moves two axes and
costs attributability on the answer path. That caveat held, and it cost us
exactly one thing — the cause of the citation collapse (finding 4). It cost us
nothing on retrieval, for a reason discovered after launch and worth recording:
the retrieval sweep runs at `top_k_retrieval_max`=12 in both configs
(`worker.py:380`), so **`top_k` cannot touch it and the retrieval delta is
attributable to `rewrite` alone.**

---

## Headline

Answer quality is unchanged at the floor: **1 correct / 8 partial / 62 wrong /
35 false-abstain / 9 correct-abstain / 5 false-answer** (judge, n=120). As with
the previous run this is **not a model-capability result** and must not be
quoted as one — two post-generation code paths still destroy or misdirect
almost every answer, and this run pins both with more precision than before.

What genuinely moved is **retrieval**, and by more than the published number
admits:

| end-to-end hit@1 (what a user experiences) | prev | this run |
|---|---|---|
| answered rows (n=102) | 0.755 | **0.794** |
| errors counted as misses (denom 106) | 0.726 | **0.764** |
| *published sweep figure* | *0.783* | *0.792* |

**The real product gain is +3.8 points, four times the +0.9 the published
metric shows** — because the previous run's sweep figure was inflated by a path
the product never runs, and this run's is not.

---

## Findings, ranked

### 1. The groundedness guard deletes every numeric answer on image corpora — BLOCKER, reproduced at accuracy 1.000

Confirmed twice independently this run. The indexing report ran
`build_content_blocks` over all 148 files: **148/148 return one `BinaryContent`
and zero string blocks — 0 characters of text, total.** The previous run's
"97-100% empty" was an understatement; it is **100% and structural**. So
`context_text` at `answer.py:892` is `""` on all 120 questions, always, because
`answer.py:888` builds it from `isinstance(b, str)` blocks and image blocks are
excluded by construction.

`looks_fabricated()` then flags any answer whose numerals are all absent from
that empty string, with `MIN_INTERESTING = 100` (`grounding.py:31`) exempting
smaller numbers. The guard therefore reduces, on any image-only corpus, to:

> **delete any answer containing a numeral ≥ 100, and replace it with "not found".**

The answers report re-derived the confusion matrix: **accuracy 1.000 — TP 37,
FP 0, FN 0, TN 79.** The reduced rule "contains a numeral ≥ 100" alone predicts
all 32 guard firings perfectly, and **zero of the 79 surviving answers contain
a number ≥ 100.** It destroyed **5 correct answers** (`rcpt-b-01-typed` 110.00,
`rcpt-b-06-full` SS3-154439, `rcpt-c-02-typed` 04/12/2017, `rcpt-d-01-typed`
181.55, `rcpt-e-06-typed` 18291/102/T0380) plus 1 partial, and caught 4 of 9
fabrications on the not-found probes. It imposes a hard ceiling: **50 of 106
answerable questions cannot be answered correctly under it.**

This is a well-designed guard for its original text-corpus case. It has never
been valid on a path where the evidence is pixels.

### 2. The prompt-order reversal is ANTI-RECENCY, not primacy — BLOCKER, and k=3 sharpened it

`answer.py:832` does `ordered_blocks = list(reversed(per_file_blocks))`,
deliberately placing the best-ranked file **last**, in the recency zone. The
in-code rationale (`answer.py:826-831`) cites a position effect "up to 20 points
… worse-than-closed-book in the worst case" — calibrated on text with a
different model.

The 2-file design could not distinguish "first slot wins" from "last slot
loses". Three slots can, and the answer is unambiguous. Judge verdicts on
single-gold 3-file prompts (I verified this table myself, independently of the
agent):

| prompt slot | contains | correct+partial |
|---|---|---|
| slot 1 | worst-ranked (rank 3) | 1/3 (0.333) |
| slot 2 | rank 2 | 2/7 (0.286) |
| **slot 3 (last)** | **best-ranked (rank 1)** | **1/64 (0.016)** |

Not-last 3/10 (0.300) vs last 1/64 (0.016), Fisher **p = 0.0069**; slot 1 vs
slot 2 **p = 1.0**. There is no primacy gradient — there is a cliff at the last
position. **This is strictly worse for the code than the previous reading**,
because `answer.py:832` exists precisely to move the best file into the slot
that turns out to be fatal.

The retrieval paradox reproduces: `hit@1=1` yields 7.1% while `hit@1=0` yields
13.6%; by gold rank, 1/2/3 → 7.1%/28.6%/33.3%. **Better retrieval still
produces worse answers.** The judge, working independently, named the same
mechanism as its largest bucket — ~30 of 62 wrong answers are cross-
contamination inside the top-3 prompt, e.g. `rcpt-a-01-full` answering RM 77.40
(the rank-3 Sen Lee Heong total) when the rank-1 Tony Roma's receipt prints
Total 269.40, and `rcpt-d-01-full` answering RM 63.90 from rank 3 when Rocku
Yakiniku was rank 1.

**One component of the prior finding is retired.** The previous report's
"model cites slot 1 over the last slot 91:10" does **not** reproduce: on
single-file citations this run gives 9:4:**13**, favouring the last slot. That
line should not be cited again. The finding stands on the other three measures,
which are stronger than before.

### 3. Retrieval improved, and the harness's own metric understated it — MAJOR (good news)

Removing the rewriter eliminated the wall-clock contamination completely:
**55/120 queries carried `2026-08-29`/`EDT`/`03:00` → 0/120.** Retrieve wall
time fell 166.8 s → 33.2 s.

More important is what it did to the harness's credibility. `enrich.py:276`
computes every published retrieval number from `retrieve.jsonl`, produced by a
**separate** `run_search()` at `worker.py:391` that bypasses `ask()`. Query text
differed between the two paths on **33/102** questions last run and **0/102**
this run, because `raw_query()` (`search.py:1013`) makes no LLM call and is
deterministic. The retrieval report then closed it completely: **truncate the
sweep to the depth the product actually used and the sweep equals the
end-to-end path identically on all 102 rows, every metric, zero residual.** The
entire divergence was rewriter nondeterminism plus depth, and this also
empirically kills the latent `fetch_k` hazard (Qdrant at limit 6 vs 24 returned
the same top 3 on all 99 non-widened rows).

**Report end-to-end numbers, not sweep numbers, from here on.** The sweep's
`@5`/`@12` describe a depth no user receives.

Two corrections to figures previously circulated, both mine to own:
- The "29 points of hit@1" cost of a date in the query string was
  cross-sectional and selection-confounded. Paired (same 16 questions, rewriter
  on/off) it is **+18.8 points**. Those questions were intrinsically harder —
  even decontaminated they reach 0.750 vs 0.869 for never-contaminated rows.
- I described `worker.py:393`'s hardcoded `rerank=True` as an asymmetry where
  the sweep ignores config and the product honours it. **Wrong.** `ask()` has
  no `rerank` parameter at all (`pipeline.py:82-88`) and `pipeline.py:149`
  hardcodes `rerank=True` too. Both paths request it unconditionally; the sole
  control is the `MAGPIE_RERANK` kill-switch at `envctl.py:244`. The paths are
  in sync today. The hazard is latent and fires the moment someone plumbs a
  real `rerank=` through `ask()` — at which point a rerank A/B would publish
  **identical retrieval metrics in both arms**, a confidently null result.

### 4. Citations collapsed — MAJOR, and this is the one thing the two-axis choice cost us

Zero-citation answers went 9 → 45; the rate among graded answers went
**14.3% → 62.5%**; citation precision 0.184 → 0.060. `sources_used` is emitted
by the model inside the grammar-constrained JSON (`answer.py:208`), so this is
generation behaviour, not plumbing.

Mechanism found: **10 responses ran to `LOCAL_MAX_TOKENS=2048` emitting junk
array elements** (the previous run's longest response was 474 chars, with zero
truncations) — 755 bare-index plus 1989 junk entries, against 20 and 29 before.
Answer text itself is unchanged (median 14 → 13 chars); only the citation field
broke. This also explains p95 latency 20 s → 58 s. `rcpt-b-03-full` is resolved:
identical answer "4.62" both runs, but `sources_used` went from a bare path to
`"File 1: /Users/.../X51005587261.jpg"`, which `_normalize_path_for_match`
drops. **28 of the 45 are recoverable by parsing that prefix.**

Attribution is **formally confounded**. The best available discriminator: on
the 31 items where both runs retrieved an identical top-2 in the same order,
verbatim-path emission still fell 26/31 → 12/31 — the same magnitude as
elsewhere, which points at `top_k` rather than `rewrite`. I record it as
*probably `top_k`, not established*. **The decisive experiment is a
`top_k=2, rewrite=false` arm**, which would also complete the 2×2.

### 5. The index cache key is insufficient — MAJOR (harness), first exercised by this run

The cached index itself is **sound**, verified four ways: an LZ4-block decode
of the Qdrant payload pages gives exactly 148 points, 148 distinct source
paths, zero duplicates, set-identical to both manifests; all 148 sha256s
recomputed with 0 mismatches; `qdrant.log` shows 240 queries and 480 existence
probes and **zero writes**; the 12-deep sweep surfaced all 148 files including
all 74 gold sources. Isolation independently re-verified. This is a clean
verification and I am recording it as such.

But `index_params_hash()` (`run.py:49-51`) keys on dataset *name* +
`model_config` + both tier flags + `local_n_ctx`, and misses:

1. **Corpus content.** Per-file sha256s are loaded at `run.py:67` and used only
   for a basename-uniqueness check; on a cache hit the corpus is never read.
   `datasets/receipts/manifest.json` documents the exact trigger in its own
   `selection` note — re-running `prepare_receipts.py` restores the two dropped
   twins (150 files) **with the key unchanged**. Undetected in both directions.
2. **The visual encoder.** `detect_device()` selects ColQwen2.5 vs ColSmol from
   `~/.cache/notspotlight/device.json`, a path outside every isolation
   fingerprint the harness has. `device.py:8-11` states a switch "would
   invalidate the whole fast_tier collection"; nothing enforces it, and because
   both are 128-dim the switch fails **silently**.
3. `dataset_dir` override (`run.py:104` passes it, `run.py:118` drops it) and
   `corpus_root.local.json`.

Meanwhile `model_config` and `local_n_ctx` are **inert** for an all-image
corpus. The key varies on what cannot matter and is constant across what can.
A `built_under_sha` mismatch prints a stderr warning (`run.py:180-186`) and
nothing else — no run.json field, no failure, not captured in any committed
artifact. Weaker than this codebase's own precedents.

### 6. There is no sparse tier on this corpus at all — MAJOR, reframes an old assumption

`raw/qdrant/collections/` contains only `fast_tier`; the `summaries` collection
**does not exist**, so `_search_summary_tier` returns `[]` at `search.py:370`.
All 1815 hits across both runs are `tier:"fast"`, and every score equals
`1/(60+rank)` **exactly**. The earlier framing — including mine — that "the
sparse tier is running with empty keywords" was too generous: the sparse tier
is not underfed, it is absent. `raw_query()`'s `extract_rare_tokens()` returning
empty on 116/120 questions is therefore a non-event; the 4 non-empty lists
merely duplicate a token already in the query.

The consequence is the part that matters: **RRF scores carry zero information**
(constant 0.0002644104 margin), so **no score-based abstention threshold is
constructible**, which feeds the false-answer rate directly. Prior finding #6
("no summary tier on image corpora — by design") is confirmed as a mechanism
but now has a measured cost: 100% of retrieval rides on the visual tier, and
there is no lexical channel to correct a wrong-vendor or wrong-month hit.

### 7. The typed/full gap is not rewriter damage — the rewriter was *reducing* it — MODERATE

Both agents converge here, and it **overturns** the previous report's reading.
The gap **widened** with the rewriter off: end-to-end hit@1 full 0.840 → 0.900
(+6.0), typed 0.673 → 0.692 (+1.9); sweep by-phrasing typed 0.679 vs full
0.906. Decomposed: full/no-date 0.938 → 0.938 and full/date-in-keywords
0.857 → 0.857 (**exact zeroes**, 46 of 53 rows), full/date-in-query **+28.6**,
typed/no-date **−10.3**.

Mechanism: the rewriter was functioning as a **spell-checker and
case-normaliser**, not a semantic expander. 3 of the 4 questions where gold
falls outside the top 12 are typed queries containing a typo — `"amout"`,
`"stationary"`, `"recipt"` — which ranked 1, 4 and 2 *under* the rewriter. So
`rewrite=false` is a net win only because the contamination it introduced cost
more than the spell-correction it provided.

On the answer side there is **no phrasing signal at all** once you condition on
gold slot (gold-last: typed 0/28 vs full 1/36; gold-not-last: 2/7 vs 1/3).
Full's retrieval lead merely puts gold into the fatal last slot more often
(36 vs 28) — finding 2 swallows the phrasing axis whole.

### 8. Abstention did not really improve — MODERATE, corrects an earlier read

I reported "correct abstention doubled, 3/14 → 7/14". That decomposition is
wrong in substance. The 7 deterministic correct-abstains are **3 genuinely
model-initiated** `not_found:true` plus **4 guard artifacts**; the judge's 9
adds 2 prose declines (`rcpt-nf-03-full`, `rcpt-nf-07-full`, where the model
answered "No" to a yes/no question and the flag-based matcher scored it
`false_answer`). **True model abstention discipline is 5/14**, not 7 or 9.

The one real improvement: the previous report's "the model never abstained once
in 120 calls" no longer holds — it did, 3 times.

`not_found_flag_missing` 1 → 0 is **not** an improvement either: it is a
detector blind spot. The model shortened "No, there is no receipt from…" to
"No", which `_ABSTAIN_RE` does not match. **The product defect got worse while
the metric got better** — the most dangerous shape a metric can have.

### 9. The 4 HTTP 400s are a clean control — MODERATE

`rcpt-b-09-typed`, `rcpt-b-09-full`, `rcpt-c-10-full`, `rcpt-d-09-full` failed
identically to the previous run, same order, token counts **18817 / 18839 /
18636 / 20974** against `n_ctx` 16384. **Correction to my own launch brief:
these are 7-image calls, not 12-image** — the widener fans out to 12 candidates
and the prompt builder drops 5 to fit. Neither swept axis can reach the
widener: it classifies on the raw question (`search.py:771`, `answer.py:803`)
and only widens when `12 > top_k`. Two runs, byte-identical failures: this is
deterministic, and it is the run's cleanest control.

**Disagreement resolved (again).** The judge grades these `false_abstain`
because the rubric has no error verdict, and notes they "measure the context
budget, not the reader". Both are right about the facts; the classification is
the judge's rubric gap, and the product-side reading stands. They must be
subtracted before quoting any abstention rate.

### 10. Golden set — sound values, flawed fact selection — MODERATE

The judge opened 18 source images and **found no factual error in any golden
answer**. Every value it checked matched the files exactly. All 7 logged issues
are fact-*selection* or scorer problems, and the answers agent added 3 more:

- **Question-resident key_facts** — `rcpt-b-03-*` ("30.00" appears in "petrol 30
  ringgit"), `rcpt-d-02-*` ("100.00" in "that RM100 fill-up"). Matchable without
  reading anything.
- **Comparison items whose key_facts omit the discriminator** — `rcpt-a-09-*`,
  `rcpt-e-09-*`, `rcpt-b-10-*`: the question asks "which is bigger" and the
  key_facts list only amounts, so the correct answer matches zero key facts.
  `rcpt-d-10` does it right.
- **Yes/no phrasing on not-found items** — a scorer defect, not a golden defect.
- **Enumeration items unanswerable at `top_k=3`** — `rcpt-en-01/02/03-*` measure
  the retrieval budget, not comprehension.

**Only one moves the headline**: dropping the question-supplied "100.00" from
`rcpt-d-02` makes `rcpt-d-02-full`'s correct "40.49" a full correct — **correct
1 → 2**. Fixing `_ABSTAIN_RE` moves deterministic correct-abstain 7/14 → 9/14.
The golden remains SILVER; these numbers cannot bear weight until the founders
review it.

---

## Suggestions

Grounded in `src/`, which I read and did not edit. Ranked by expected value.

1. **Make the groundedness guard evidence-aware** (`answer.py:887-903`). It
   must not run when `context_text` is empty *because the evidence was images*.
   Minimal fix: build `_blocks` from text blocks as now, but skip the
   `looks_fabricated()` call entirely when `per_file_blocks` contains any
   non-`str` block and no `str` block survives — i.e. distinguish "no text
   found" from "text found and the answer contradicts it". Today those two are
   the same state and the guard treats both as fabrication. This alone lifts a
   ceiling that caps 50 of 106 answerable questions.

2. **Stop reversing the prompt on the vision path** (`answer.py:832`). The
   comment's own justification is a text-model position effect; the measured
   effect here is the opposite sign and larger (1/64 vs 3/10, p = 0.0069). At
   minimum make the reversal conditional on the evidence being text. Findings 1
   and 2 compound — the guard preferentially kills large numbers (receipt
   totals) while the ordering feeds the model the wrong receipt — so fix them
   together and re-measure, not one at a time.

3. **Recover the 28 salvageable citations** by teaching
   `_normalize_path_for_match` to strip a leading `"File N: "` prefix, and
   investigate the 10 responses hitting `LOCAL_MAX_TOKENS=2048`. Cheap, and it
   restores a signal we currently cannot trust in either direction.

4. **Harness — put corpus content in the cache key** (`run.py:49-51`). The
   per-file sha256s are already loaded at `run.py:67`; hash them into the key.
   Also fold in the resolved visual encoder, and promote the `built_under_sha`
   mismatch from a stderr warning to a run.json field plus a hard fail, matching
   how isolation is already treated.

5. **Harness — plumb `rerank` through `ask()`** (`pipeline.py:82-88`, `:149`)
   and have the sweep read it from config rather than hardcoding
   (`worker.py:393`). Do these two together; doing only the first creates the
   silent-null-result failure described in finding 3.

6. **Fix `_ABSTAIN_RE` to match a bare "No"**, and re-phrase the two yes/no
   not-found items as open questions. Until then `not_found_flag_missing` is
   actively misleading.

7. **Run `top_k=2, rewrite=false`** to complete the 2×2 and settle finding 4.
   It is also the cheapest run available — the index is cached, and with the
   rewriter off retrieval takes ~33 s.

---

## What this run is good for, and what it is not

**Trustworthy:** the retrieval result (single-axis, end-to-end, +3.8 points on
what the user actually sees); the guard mechanism at accuracy 1.000; the
anti-recency finding, which needed three slots to see; the index verification;
the two harness bugs.

**Not trustworthy:** the 0.8% accuracy figure as any statement about the model;
the citation collapse as a `rewrite` effect; anything about the solo gate
(structurally off — `solo_gated` False on all 120 rows, over-determined three
ways); anything about rerank quality (off, and the cross-encoder scores visual
hits against the byte-identical placeholder `"(visual match — page 1)"` at
`search.py:553` + `rerank.py:68`, so it is not weak signal but *no* signal).

**Provenance nit for the next reader:** `worker_retrieve_result.json`'s
`resolved_env` records `REWRITE: "true"` on a `rewrite: false` run. It is
harmless — `envctl.py:129` documents the field as unread, and the recorded
queries are verbatim raw questions — but it reads as the exact opposite of this
run's headline axis and should be corrected before it misleads someone.
