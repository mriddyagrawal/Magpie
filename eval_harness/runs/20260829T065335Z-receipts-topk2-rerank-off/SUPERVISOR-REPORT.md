# Supervisor report — 20260829T065335Z-receipts-topk2-rerank-off

**Config.** `lfm-local` (LFM2.5-VL-3B Q6_K), `top_k=2`, rerank **off**, solo gate
structurally off, temp 0, `n_ctx` 16384, rewrite on, fast/ColPali tier only.
**Dataset.** `receipts`, 148 scanned JPEGs (deduped from 150 this session),
golden v3 regenerated from the images — 120 items / 60 pairs, `golden_sha`
a3b05ea95c052a65. **Backend** c823a44. **Provenance verified**: status
`complete`, both isolation checks true, `env_snapshot` matches the requested
config on every swept axis.

**Headline.** 3 correct / 4 partial / 56 wrong / 43 false-abstain (judge, n=120).
That 2.5% is **not** a model-capability result and must not be quoted as one.
Retrieval put a gold file into the prompt on 87.5% of extractive questions; two
post-generation code paths then destroyed or misdirected almost every answer.
The run's value is that it isolated both, with mechanism and line numbers.

---

## Findings, ranked

### 1. The groundedness guard silently deletes correct answers on image corpora — BLOCKER

`src/answer.py:887-903` builds its evidence text as
`[b for _d, blocks in per_file_blocks for b in blocks if isinstance(b, str)]`
— **text blocks only; image blocks are excluded by construction.** On this
corpus 97-100% of text blocks are empty (see finding 6), so `context_text` is
effectively `""`. `looks_fabricated()` (`src/grounding.py`) then returns True
whenever *every* number in the answer is absent from that empty string, and
`MIN_INTERESTING = 100` (`grounding.py:31`) exempts numbers below 100. The guard
therefore reduces, on any image-only corpus, to:

> **delete any answer containing a number ≥ 100, and replace it with "not found".**

Evidence (answers report, independently reproduced): re-running the guard
predicts the run's `not_found` flag with **accuracy 1.000** — 41 TP, 0 FP, 0 FN,
75 TN. **The model never abstained once in 120 calls**: zero `not_found:true`
from the model, zero empty generations, zero JSON parse failures. All 41
abstentions were manufactured after generation. It destroyed **7 fully correct
answers** — `rcpt-d-07-typed/-full` had produced the exact invoice number
`KNG01-1032303`, plus `rcpt-e-06-typed`, `rcpt-b-06-full`, `rcpt-b-08-full`,
`rcpt-c-02-typed` — and 4 partials. It caught **0 of the 10 actual
fabrications**, because invented amounts on this corpus are mostly < 100.

The guard is well-designed for its original text-corpus case (the sem6 dorm-room
probe). It has simply never been valid on a path where the evidence is pixels.

### 2. The prompt-order reversal is backwards for the vision path — BLOCKER

`src/answer.py:832` does `ordered_blocks = list(reversed(per_file_blocks))`, so
the best-ranked file is presented **last**. The rationale is explicit and
reasonable — Liu et al. 2023 "Lost in the Middle", small decoders are
recency-biased — but it was calibrated on **text** with Gemma 4 E4B, and it is
wrong for LFM2.5-VL-3B reading **images**.

Measured three independent ways, all agreeing:
- Of 39 answers quoting a decimal amount, **25 (64%) match the total of the file
  presented FIRST (the worst-ranked); ZERO match the best-ranked file presented
  last.**
- Gold in prompt slot 1 → 5/22 good; gold in the "recency" slot → **0/63**
  (Fisher exact p = 0.0008).
- The model cites slot 1 over the last slot **91:10**.

The perverse consequence: `hit@1 = 1` yields 4.8% answer accuracy while
`hit@1 = 0` yields 13.0% — **better retrieval produces worse answers**, because
ranking well means being placed where this model does not look. `rcpt-a-04` is a
natural controlled A/B: identical two files, order flipped between phrasings,
wrong → correct.

Findings 1 and 2 compound: the guard preferentially kills answers with large
numbers (receipt totals), and the ordering feeds the model the wrong receipt.

### 3. The query rewriter injects wall-clock time into search queries — MAJOR

55 of 120 rewrites carry `2026-08-29` / `EDT` in their keywords. Four typed
rewrites are *nothing but* the injected timestamp; `rcpt-a-02-typed`
("f&p phamacy what date") became a search for "Farmers Drug Pharmacy store
opening date". The retrieval report isolates the cost: when the date lands in
the **query string** it costs **29 points of hit@1** (0.878 → 0.588); in
keywords only it is near-harmless. The vendor token survives the rewrite 44/44
for `full` phrasings but only 36/43 for `typed`.

This also fully explains the apparent phrasing gap. Typed vs full is **not** a
phrasing-robustness result on this run — it is slot assignment plus rewriter
damage. Any H2′ reading of these numbers would be measuring the wrong thing.

### 4. The LIST_ALL widener fires on the wrong questions and overflows the context — MAJOR

7 `LIST_ALL` firings, all on 2-3-file synthesis questions, **none on the 3
genuine enumeration pairs** that needed widening. 4 of the 7 overflowed `n_ctx`
(18.6-21.0K against 16384) and are precisely the run's 4 HTTP 400s
(`rcpt-b-09-typed/-full`, `rcpt-c-10-full`, `rcpt-d-09-full`) — questions whose
retrieval was perfect. All 4 had 7 images attached; 4 of 7 such calls failed
versus 0 of 113 two-image calls.

**This resolves a disagreement.** The judge classed the 400s as a harness fault
to be discounted. They are not — they are a product-side interaction between the
widener and the vision context budget, and they belong in the product findings.

### 5. The harness measures retrieval off a path the product never runs — MAJOR (harness)

`enrich.py:276` computes every `hit@k`, `recall@k`, `MRR` and `nDCG@5` from
`retrieve.jsonl`, produced by a **separate** `run_search()` call
(`worker.py:391`) that bypasses `ask()`. The end-to-end truth from
`answers.jsonl` (populated from the real `ask()` at `worker.py:288`):

| | metrics.json (separate pass) | true end-to-end |
|---|---|---|
| hit@1 | 0.783 | **0.726** |
| hit@2 (= what is fed) | 0.858 | **0.821** |

Reported figures are optimistic by 4-6 points and the two paths disagree on
17/106 questions — every divergent row had a different rewrite, and zero
diverged when the rewrite was identical, so the cause is rewriter
nondeterminism (finding 3), not the `fetch_k` asymmetry.

Worse for future runs: that pass hardcodes `rerank=True` (`worker.py:393`)
regardless of config. This run escaped only because `MAGPIE_RERANK=0` overrides
it inside `_rerank_enabled()`. A run that sets `rerank` by config alone would
silently measure the wrong system — exactly the "recorded config not in force"
failure this project has already shipped twice.

Also note `@5`/`@12` are meaningless end-to-end here: 113/120 rows returned
exactly 2 files.

### 6. No summary tier on image corpora — BY DESIGN, not a bug

`index_summary_tier: true` is a **no-op** on an all-image corpus. `.jpg` is
supported (`src/content.py:24`), but `src/stage1_fast/router.py:110-111` routes
images to the fast tier and `src/pipeline.py:312` passes `skip_fast_tier=True`,
which strips them at `src/stage1/summarize.py:790-794`, leaving an empty list and
a `sys.exit` at `:796`. The "no supported files found" message is misleading —
it is a route filter, not an extension filter — and using `sys.exit` as control
flow forces the harness to string-match it (`worker.py:186`).

Indexing itself was clean: **148/148 files**, set-identical to the manifest, 148
Qdrant upserts, zero errors, flat 2.78s/file. This is not where the run failed.

### 7. Citations are decorative and partly recoverable — MAJOR

`citation_precision` 0.18, `hallucinated_citations` 0.44, and 49% of answers
cite nothing while still asserting a value. The harness **discards 36% of
emitted citations, 39 of which are recoverable** by stripping a `File N:`
prefix the model emits. `rcpt-e-04-typed` gives the correct answer
("Master Card") while citing a receipt whose payment line reads `VISA CARD` —
right answer, contradicting evidence. Note `cited: 0.75` in metrics.json is a
mean count, not a rate; it reads as a pass rate and is not one.

### 8. k=2 genuinely caps multi-file work — real, but secondary

ColQwen ranks all 5 Wan Sheng receipts at 1-5, 7 of 8 Kedai Papan at 1-7, all 6
Gin Kee at 1-6 — the embeddings find the sets; `k=2` discards them.
`recall@8 = 0.931` vs `0.328` at k=2. **Disagreement resolved:** the judge
concluded "`topk=2` with rerank off is the binding constraint... re-run at a
larger k." That is right for enumeration and multi-file items and wrong for the
run as a whole — the gold file was already in the prompt 87.5% of the time on
extractive questions, and findings 1 and 2 destroyed those answers regardless of
k. The judge wrote before the guard was identified. Raising k alone would not
have rescued this run.

---

## Golden set

Silver (0/120 human-verified). The judge read 16 source images and **overturned
no gold value**; the indexing agent spot-checked 6 more and found every asked
fact legible. Construction issues to fix before founder review:

1. `rcpt-e-09` — ambiguous referent: two Popular Book Co. AEON Shah Alam receipts
   3 minutes apart (30.70 and 12.15); the gold silently picks one.
2. `rcpt-d-05` / `rcpt-d-10` — source prints a `CASH` header *and* a
   `MASTER 46.20` tender block. Gold follows the tender line and is right, but
   needs human sign-off.
3. `rcpt-b-08`, `rcpt-a-03`, `rcpt-b-07`, `rcpt-c-05`, `rcpt-e-07` — `key_facts`
   scoped wider than the question ("which shop" carries both shop and amount),
   so a fully responsive answer scores partial.
4. `rcpt-a-09`, `rcpt-b-10`, `rcpt-c-09`, `rcpt-e-09` — comparison items list the
   two amounts rather than the selection; `rcpt-d-10` does it correctly and
   grades cleanly.
5. `rcpt-e-10` — retrieval was blamed for a golden bug: rank 1 is a genuine
   Mr D.I.Y. March receipt, just not one of the 3 chosen gold sources.
6. My own: `rcpt-en-01` / `rcpt-en-03` use single-digit `key_facts` ("5", "6")
   that string-match trivially.

Also mine to disclose: **47% of the golden set (50/106) was structurally
unanswerable under finding 1** — any question whose answer is a number ≥ 100 was
doomed before generation. The achievable ceiling for this run was ~53%, not 100%.

---

## Suggestions

Code-grounded; I have not modified `src/`.

1. **Make the groundedness guard vision-aware** (`src/answer.py:887`). Either
   skip it when a file's contribution is an image block rather than text, or
   count image-bearing files as un-verifiable and abstain from *judging* rather
   than abstaining from *answering*. As shipped it is a correctness regression
   on every scanned corpus. `MAGPIE_STRICT_GROUNDING=0` disables it and is the
   fastest way to get a clean measurement of the underlying model.
2. **Gate the reversal on modality** (`src/answer.py:832`). The Liu et al.
   argument is about text; this run is direct evidence it inverts on the VL
   image path. Cheapest decisive test: one re-run with the reversal disabled,
   nothing else changed. Predicted by finding 2 to move accuracy more than any
   retrieval change available.
3. **Stop injecting wall-clock time into rewritten queries.** Date belongs in
   keywords at most, never the query string (29 points of hit@1).
4. **Fix the widener's trigger and make it context-aware** — it fires on
   synthesis questions, misses true enumeration, and overflows `n_ctx` at 7
   images. Budget images by their real encoded cost before widening.
5. **Harness: score retrieval from `answers.jsonl.retrieved`**, not
   `retrieve.jsonl` (`enrich.py:276`), or drop the separate pass. At minimum,
   stop hardcoding `rerank=True` at `worker.py:393`.
6. **Recover the 39 `File N:`-prefixed citations** before drawing any conclusion
   about citation quality.
7. **Do not re-run this config for a model verdict** until 1 and 2 are settled.
   The informative next run is a single-axis ablation with the guard off — the
   only way to see what LFM2.5-VL-3B can actually do on receipts.

## Hypotheses

- **H1** — not assessable. Its eligible set is file-level-image basis (70/80,
  87.5%), and accuracy on it is 0.0 — but that number is produced by findings 1
  and 2, not by model sufficiency. Recording it as an H1 data point would be a
  category error.
- **H2′** — do not read this run. The typed/full split is explained by slot
  assignment and rewriter damage (finding 3), not phrasing.
- **H5** — still blocked, now over-determined: rerank off, `solo_margin=0`, and
  a constant-placeholder margin. `solo_gate_structurally_off: true`, fire rate 0.
