# Retrieval analysis — `20260829T081855Z-receipts-topk3-rerank-off-norewrite`

Corpus: 148 receipt JPEGs. Golden `a3b05ea95c052a65`: 120 items, **106 with qrels**,
14 `not_found` probes with no gold source.
Config: `top_k=3` (retrieval **and** generator fan-out), `top_k_retrieval_max=12`,
**`rewrite=false`**, `rerank=false` (`MAGPIE_RERANK=0`), `solo_margin=0`,
`fast_search=true`, temp 0, LFM2.5-VL-3B local, `n_ctx=16384`.
Backend `c823a44`, index `5ff3e0adf0448de6` (same index as the prior run).
Contrast run: `20260829T065335Z-receipts-topk2-rerank-off` — `top_k=2`, **`rewrite=true`**,
everything else identical.

> **Every metric in this report is labelled [A], [B] or [C].** Never quote one without
> the label. See §1. Independent recomputation of all three views from the raw JSONL is
> in §1.4; it reproduces `metrics.json` to the last digit and reproduces every figure
> the owner supplied. **I disagree with none of them.** Two of the owner's *framings* —
> the rerank hardcode and the 29-point date cost — need correction, in §3 and §4.3.

---

## 0. Headline

**The published retrieval numbers are not the ones the product produced, and this
time that hid a change of sign.** In the prior run the end-to-end path was 4–6
points *worse* than the published sweep. In this run it is *better* than the sweep on
the rows that ran. The reason is not that retrieval got more stable — it is that
turning the rewriter off removed the only source of disagreement between the two paths.

- **[A] harness sweep, n=106:** hit@1 **0.792**, hit@3 **0.887**, MRR **0.851** — this
  is what `metrics.json` publishes, and it comes from a `run_search()` call
  (`worker.py:391-396`) that `ask()` never makes.
- **[B] end-to-end, answered rows only, n=102:** hit@1 **0.794**, hit@3 **0.892**,
  MRR **0.840** — the real ranked list the generator was handed
  (`answers.jsonl.retrieved`, from `ask()` at `worker.py:288`).
- **[C] end-to-end with the 4 errored rows counted as misses, denominator 106:**
  hit@1 **0.764**, hit@3 **0.858**, MRR **0.808** — what a user actually experienced.

**[C] is the honest headline: hit@1 0.764, up from 0.726.** The published +0.9-point
sweep improvement understates a +3.8-point real improvement, because the prior run's
published number was inflated by a path that never ran and this run's is not.

Four findings develop that:

1. **The two paths now agree exactly.** Query text differed on 33/102 rows in the prior
   run and on **0/102** here. Truncate the sweep to the depth the product actually used
   and the two rankings are **identical on all 102 rows, on every metric, to full float
   precision** (§2.2). The prior run had 2 rows of irreducible rewrite drift. The
   retrieval stack is now deterministic and replayable; it was not before.
2. **The sweep's +0.9-point hit@1 gain is a net of 19 flips, not a small uniform lift.**
   Decontamination bought +3.8 points on 45 rows; losing the rewriter's expansion,
   case-correction and spell-correction cost −2.8 points on the 61 clean rows (§4).
3. **The sparse tier is not underfed — it does not exist.** The `summaries` collection
   was never created (only `fast_tier` is on disk). `raw_query()`'s empty keyword lists
   are irrelevant to BM25 because there is no BM25 (§5).
4. **The phrasing gap widened because the rewriter was a spell-checker and a
   case-normaliser, and terse lowercase misspelled queries were the only thing it was
   load-bearing for** (§6). Three questions fell out of the top 12 entirely, and all
   three contain a typo.

Two harness issues to log: the sweep/product split itself (§1), and the `rerank=True`
hardcode at `worker.py:393` (§3) — which is a real latent hazard but not the mechanism
the brief describes.

---

## 1. Three metric views, and why the harness publishes the wrong one

### 1.1 The split

| | who computes it | source | what ran |
|---|---|---|---|
| **[A]** | `enrich.py:276` → `:314-317` | `raw/retrieve.jsonl` | `run_search()` at `worker.py:391-396`, `k_max=12`, `rerank=True` hardcoded |
| **[B]/[C]** | this report | `raw/answers.jsonl` `retrieved` | `ask()` at `worker.py:288` → `pipeline.py:147-151`, `top_k=3` |

`enrich.py:276` builds `ranked_by_id` from `retrieve_rows` and `:314` reads it back per
question; `out["retrieval"]` — the sole input to `metrics.json`'s `retrieval` block and
to `by_phrasing.retrieval_hit@1` — is computed from a list the generator never saw.
`worker.py:288` is the only call that touches `ask()`, and its ranking lands in
`answers.jsonl` under `retrieved`. The two never share a code path.

`ranked_pre_gate` is also derived from the sweep (`enrich.py:318`), which is why it
reads **12 on all 120 rows** in `answers_enriched.json` even though the product path
returned 3 on 113 of them. It is a sweep artefact, not an observation of the product.

### 1.2 All three views, this run

n=106 for [A] and [C]; n=102 for [B] (the 4 HTTP-400 rows carry no ranking).
End-to-end depths: **3 on 99 rows, 12 on 3 rows** (the LIST_ALL widener), 0 on the 4
errors. Sweep depth: **12 on all 106**.

| metric | **[A]** sweep (published) | **[B]** e2e answered | **[C]** e2e, errors = miss |
|---|---|---|---|
| hit@1 | 0.7925 | **0.7941** | **0.7642** |
| hit@2 | 0.8585 | 0.8627 | 0.8302 |
| hit@3 | 0.8868 | **0.8922** | **0.8585** |
| hit@5 | 0.9434 | 0.9020 ¹ | 0.8679 ¹ |
| hit@12 | 0.9623 | 0.9020 ¹ | 0.8679 ¹ |
| recall@1 | 0.6807 | 0.6943 | 0.6681 |
| recall@2 | 0.8047 | 0.8101 | 0.7796 |
| recall@3 | 0.8580 | **0.8623** | **0.8297** |
| recall@5 | 0.9080 | 0.8655 ¹ | 0.8329 ¹ |
| recall@12 | 0.9517 | 0.8721 ¹ | 0.8392 ¹ |
| MRR | 0.8509 | **0.8402** | **0.8085** |
| nDCG@5 | 0.8605 | 0.8353 | 0.8037 |
| mean first-gold-rank (found only) | 1.441 | 1.185 | 1.185 |

¹ **`@5` and `@12` are not comparable across columns.** 99 of 102 end-to-end rows
returned exactly 3 files, so `hit@5` and `hit@12` in [B]/[C] are `hit@3` plus the 3
widened rows. They are not evidence that deep ranking is worse — only that it does not
exist below rank 3. **`hit@1`, `hit@2`, `hit@3`, MRR and nDCG@5 are the honest
comparisons.**

### 1.3 The same three views, prior run — and the sign flip

| metric | prior [A] | prior [B] | prior [C] | this [A] | this [B] | this [C] |
|---|---|---|---|---|---|---|
| hit@1 | 0.7830 | 0.7549 | **0.7264** | 0.7925 | 0.7941 | **0.7642** |
| hit@2 | 0.8585 | 0.8529 | 0.8208 | 0.8585 | 0.8627 | 0.8302 |
| hit@3 | 0.8679 | 0.8529 | 0.8208 | 0.8868 | 0.8922 | 0.8585 |
| MRR | 0.8377 | 0.8064 | 0.7759 | 0.8509 | 0.8402 | 0.8085 |
| nDCG@5 | 0.8469 | 0.7839 | 0.7543 | 0.8605 | 0.8353 | 0.8037 |
| **[B] − [A]** on hit@1 | | **−0.028** | | | **+0.002** | |

That is the structural finding. **[B] − [A] went from −2.8 points to +0.2 points.**
Read only the published column and you see hit@1 +0.9. Read what the product did and
you see **[C] hit@1 +3.8 points and MRR +3.3 points** — four times the published
improvement, entirely because the published prior-run number was measuring a path with
a different query on a third of its rows.

Apples-to-apples on the same 102 rows, [A] restricted to the answered set:
prior 0.7745 → this 0.7941 (+2.0pt), MRR 0.8313 → 0.8524.

### 1.4 Reproduction and validation

I reimplemented `metrics.py`'s `graded_ranking` / `hit_at_k` / `recall_at_k` / `mrr` /
`ndcg_at_k` / `path_matches` from scratch (suffix-anchored, case- and separator-
insensitive; gold dedup so a re-retrieved gold contributes 0 at later ranks) and scored
both runs from raw JSONL.

- **[A] reproduces `metrics.json` exactly**, this run and prior — `hit@1` 0.7924528…,
  `mrr` 0.8508647…, `ndcg@5` 0.8604884…, `first_gold_rank` 1.4411764…, and every
  `recall@k`, to all printed digits.
- **[B] and [C] reproduce every figure in the brief exactly**, both runs, including the
  prior report's published end-to-end 0.726/0.821/0.776.
- Errored rows: `rcpt-b-09-typed`, `rcpt-b-09-full`, `rcpt-c-10-full`, `rcpt-d-09-full`
  — the same four as the prior run, the same four `n_ctx` overflows
  (18817/18839/18636/20974 tokens against 16384 in `raw/worker_answer.log`), from the
  same 7 LIST_ALL widenings. Finding #4 of the prior supervisor report reproduced
  exactly, as the config note predicted.

**Verdict on the owner's numbers: all correct. Nothing to dispute.**

### 1.5 Recommendation

Score retrieval from `answers.jsonl.retrieved`. If a depth-12 diagnostic sweep is still
wanted, keep it — but publish it under a distinct key (`retrieval_sweep`) and publish
`retrieval` from the product path, with errored rows counted as misses. Publishing [A]
as `retrieval` is how a −2.8-point measurement error survived a whole run and a whole
report cycle. Also stop deriving `ranked_pre_gate` from the sweep (`enrich.py:318`) —
as written it can never detect a gate firing on the product path.

---

## 2. Why the two paths agreed this time

### 2.1 Query text

`raw_query()` (`search.py:1013-1028`) makes **no LLM call**: it returns
`SearchQuery(query=question, keywords=extract_rare_tokens(question))`, a pure regex
over the raw text. `rewrite_query()` is an LLM call, made **twice** — once by the sweep
at `worker.py:391`, once by `ask()` at `pipeline.py:136` — with a wall-clock timestamp
inside the prompt and 4–28 minutes between the two passes.

Measured on the 102 non-errored answerable rows, comparing `rewritten_query` in
`retrieve.jsonl` against `rewritten_query` in `answers.jsonl` (query string **and**
keyword list):

| | query text differs | ordered top-*d* prefix differs | first-gold-rank differs |
|---|---|---|---|
| prior run (rewrite ON) | **33 / 102** | 13 / 102 | 9 / 102 |
| **this run (rewrite OFF)** | **0 / 102** | **0 / 102** | **6 / 102** |

All 13 prior-run prefix divergences are inside the 33 with differing query text; zero
occurred with an identical rewrite. That confirms the prior report's §6 attribution.

### 2.2 The residual 6 are pure depth, and I can prove it

Truncate the sweep's 12-deep ranking to the depth the product actually used on that row
(3, or 12 where the widener fired) and re-score:

| | residual first-gold-rank divergence | depth-matched sweep [A′] vs [B] |
|---|---|---|
| **this run** | **0 / 102** | **identical on every metric** (hit@1 0.7941, hit@2 0.8627, hit@3 0.8922, MRR 0.8402, nDCG@5 0.8353, recall@k all equal) |
| prior run | 2 / 102 — `rcpt-a-04-full`, `rcpt-e-02-typed` | [A′] hit@1 0.7745 vs [B] 0.7549 (−0.0196 = exactly those 2 rows) |

The six divergent rows this run — `rcpt-a-06-typed` (sweep FGR 6), `rcpt-c-09-typed`
(5), `rcpt-e-02-typed` (8), `rcpt-e-04-typed` (4), `rcpt-e-04-full` (4),
`rcpt-en-03-typed` (4) — every one has an identical query on both paths and a sweep
first-gold-rank **> 3**. The product simply could not see them at `top_k=3`. That is
the entire remaining gap. **The owner's claim is confirmed, and stronger than stated:
not merely "attributable to depth" but exactly reproducible by truncation, with zero
residual.**

This also settles the `fetch_k` hazard the prior report flagged as latent. With rerank
off, `fetch_k = top_k` (`search.py:836`), so the sweep asked Qdrant for 24 ColPali
candidates (`fetch_k * 2`, `search.py:850`) and the product asked for 6 — on 99 of the
102 rows. Quantized MaxSim search at limit 6 and limit 24 returned **the same top 3 on
all 99**. The asymmetry is real in the code and produced no observable effect here.

### 2.3 The reproducibility consequence

The prior report's warning — "this run cannot be replayed; re-running at a different
wall-clock minute produces different queries" — no longer applies. Retrieval in this
configuration is a pure function of `(question, index)`. Scores confirm it: every hit in
both files satisfies `score == 1/(60+rank)` with **exactly zero residual** (1440 sweep
hits, 375 end-to-end hits), and the top1−top2 margin is `0.0002644104` on all 120 sweep
rows and all 116 end-to-end rows.

---

## 3. Harness bug: `rerank=True` hardcoded in the sweep — real, but not for the stated reason

`worker.py:393-396`:

```python
hits = run_search(
    sq, k_max, question=q["question"], skip_fast=not fast,
    rerank=True, enumerate_lists=enumerate_lists,
)
```

`rerank` is never read from `params` anywhere in `run_retrieve`. Confirmed by reading
`worker.py:378-396` in full.

**Correction to the brief.** The product path hardcodes it too. `pipeline.py:147-151`:

```python
retrieved = await asyncio.to_thread(
    run_search, sq, top_k,
    question=question, skip_fast=not fast, rerank=True,
    enumerate_lists=enumerate_lists,
)
```

and `ask()` (`pipeline.py:82`) takes no `rerank` parameter at all, so `worker.py:288`
cannot pass one. **Both paths request rerank unconditionally.** The single point of
control is `envctl.py:244`:

```python
env["MAGPIE_RERANK"] = "1" if params.get("rerank", True) else "0"
```

which feeds `_rerank_enabled()` (`search.py:567-577`), which `run_search` consults at
`search.py:768-769` (`if rerank and not _rerank_enabled(): rerank = False`) before
anything else. So today the config *is* in force on both paths, symmetrically. Both
runs' `env_snapshot` carries `MAGPIE_RERANK: "0"`; `grep -c "solo-gate"
raw/worker_answer.log` = 0; all 1815 hits across both files are `tier: "fast"` in pure
RRF order.

**The hazard is still live, and worth fixing.** The obvious next change — plumbing a
real `rerank=` parameter through `ask()` so the product path stops hardcoding it — is
exactly the change that breaks the sweep, because `worker.py:393` would keep saying
`True` while `ask()` started honouring the config. Any of these three breaks it:

1. someone adds `rerank` to `ask()`'s signature (the natural fix);
2. someone drops or renames `envctl.py:244`;
3. someone invokes `worker.py` with a payload directly, outside `envctl`.

**Blast radius, quantified.** Under `rerank: true` with the hardcode intact and the env
plumbing removed, a rerank-ON/OFF A/B would publish **identical [A] retrieval metrics
in both arms** — both reranked — and therefore report exactly **zero** retrieval effect
for the axis under test, while the answer-side metrics moved. The failure is
maximally deceptive: not a wrong number, a confidently *null* one. Three further
distortions ride along in the ON arm:

- `fetch_k` jumps from `top_k` to `max(10, top_k*2)` (`search.py:836`) — 24 in the
  sweep at `k_max=12`, 10 in the product at `top_k=3`. The candidate pools stop
  matching, so §2.2's depth-truncation identity no longer holds and the paths become
  genuinely incomparable.
- LIST_ALL rows auto-suppress rerank (`search.py:826-833`), so 7/120 rows would be
  un-reranked inside a "reranked" population — a silently mixed metric.
- `MAGPIE_HYPE_WEIGHT` blending is gated on `rerank` (`search.py:862`), so a fourth
  behaviour would switch on with it.

**Fix (one line, do it now):**
`rerank=bool(params.get("rerank", True))` at `worker.py:395`, mirroring
`worker.py:382`'s handling of `rewrite`. Belt and braces: have `run.py` assert that
`params["rerank"]` and the resolved `MAGPIE_RERANK` agree, and stamp the *effective*
rerank state into `run.json` next to `solo_gate_structurally_off`.

**Provenance nit, same family.** `raw/worker_retrieve_result.json` `resolved_env`
contains `REWRITE: "true"` on a run whose config says `rewrite: false`. It is harmless —
`envctl.py:129` documents `REWRITE` as "not consulted by src", and I verified
empirically that every `rewritten_query.query` in both JSONLs is the raw question
verbatim — but an auditor reading `resolved_env` would reach the opposite conclusion
about this run's headline axis. Drop it from the passthrough list or stamp it `false`.

---

## 4. Q1 — where the gain came from

### 4.0 Attribution: the sweep really is single-axis. Verified.

`worker.py:381` reads `k_max = int(params.get("top_k_retrieval_max", 12))`. **Not
`top_k`.** Both configs set `top_k_retrieval_max: 12`; both differ only in `top_k`
(2 vs 3) and `rewrite` (true vs false); `rerank`, `solo_margin`, `fast_search`,
`enumerate_lists`, `temperature` and `index_params_hash` (`5ff3e0adf0448de6`) are
identical. Empirically **every one of the 240 sweep rows across both runs returned
exactly 12 results**, and the sweep's LIST_ALL log lines read
`top_k 12→12 (local backend cap; cfg wanted 30)` — the widener is a no-op at `k_max=12`.

**So [A]-vs-[A] is a clean single-axis rewrite ablation.** [B] and [C] are two-axis
(top_k 2→3 *and* rewrite) and must not be used for causal attribution about the
rewriter. Everything in §4 and §6's mechanism section is [A]-vs-[A].

### 4.1 Contamination is gone, completely

Scanning both runs' `retrieve.jsonl` for `2026-08-29` / `EDT` / `03:xx` / `Saturday`:

| | in the `query` string | in `keywords` | either |
|---|---|---|---|
| prior (rewrite ON) | **17 / 120** | **54 / 120** | **55 / 120** |
| **this run** | **0 / 120** | **0 / 120** | **0 / 120** |

Owner's figures reproduced exactly. Among the 106 answerable: 16 date-in-query,
29 date-in-keywords-only, 61 clean.

### 4.2 The decomposition

Grouping the 106 answerable rows by what the *prior* run's rewriter did to them, and
measuring the same questions under both configs (paired, depth 12 both sides):

| prior-run class | n | [A] prior hit@1 | [A] this hit@1 | Δ | contribution to the 106-row mean |
|---|---|---|---|---|---|
| **date in the query string** | 16 | 0.562 | **0.750** | **+0.188** | **+2.83 pp** |
| **date in keywords only** | 29 | 0.724 | **0.759** | +0.034 | **+0.94 pp** |
| **no date** | 61 | **0.869** | 0.820 | **−0.049** | **−2.83 pp** |
| all | 106 | 0.783 | 0.792 | +0.009 | **+0.94 pp** (= exactly +1 question) |

At other depths (questions gained/lost, out of 106):

| | date-in-query | date-in-keywords | no-date | net |
|---|---|---|---|---|
| hit@1 | **+3** | +1 | **−3** | +1 (+0.94 pp) |
| hit@3 | **+3** | +1 | −2 | +2 (+1.89 pp) |
| hit@5 | **+4** | −1 | 0 | +3 (+2.83 pp) |
| hit@12 | **+5** | −1 | −1 | +3 (+2.83 pp) |

**Answer to the question asked: removing date contamination is worth +3.8 points of
hit@1 gross; every other effect of removing the rewriter costs −2.8 points. Net
+0.9.** At hit@5 and hit@12 the picture is cleaner — decontamination is worth +4 to +5
questions and the non-contaminated population is a wash — which is why the deeper
metrics moved more than hit@1 (recall@5 0.891→0.908; hit@12 0.934→0.962).

The headline "+0.9 points" is therefore a **net of 19 hit@1 flips** (10 gains, 9 losses)
on 106 questions. Reporting it as a small uniform improvement would be wrong.

### 4.3 Correction to the "29 points" figure

The prior report measured that a date in the query string cost **29 points** of hit@1
(0.878 → 0.588, n=17). That was a **cross-sectional** comparison — contaminated rows
versus clean rows *within* the prior run — and it is confounded by selection: the
rewriter contaminated the terse, entity-poor questions preferentially, which are harder
regardless. The **paired** measurement available now (same 16 questions, rewriter on vs
off) gives the causal number: **+18.8 points**, not 29.

The confound is visible directly: after decontamination the date-in-query group reaches
hit@1 0.750, still well below the never-contaminated group's *prior* 0.869. Those
questions were intrinsically harder; ~10 of the 29 points were selection, ~19 were the
date. The prior report's directional conclusion stands; its magnitude was inflated by
about a third.

### 4.4 Which questions flipped, and why

**Rescued (miss→hit@1), 10 rows.** 8 of the 10 were date-contaminated:

| qa_id | prior contamination | prior rewritten query | prior FGR → this FGR |
|---|---|---|---|
| `rcpt-c-10-typed` | **in query** | `current date and time Saturday 2026-08-29 03:02 EDT` | miss@12 → **1** |
| `rcpt-d-09-typed` | **in query** | `current date and time Saturday 2026-08-29 03:02 EDT` | miss@12 → **1** |
| `rcpt-d-05-full` | **in query** | `AA Pharmacy payment method cash card 2026-08-29` | miss@12 → **1** |
| `rcpt-c-03-full` | **in query** | `LA Stationery cash payment change amount 2026-08-29 03:01 EDT` | miss@12 → **1** |
| `rcpt-b-06-typed` | keywords | `battery invoice current date time` (vendor "premio" dropped) | 11 → **1** |
| `rcpt-d-03-typed` | keywords | `Kaison mall current date and time` | 5 → **1** |
| `rcpt-a-06-full` | keywords | `Yong Tat Hardware pickup item` | miss@12 → **1** |
| `rcpt-b-08-typed` | keywords | `sunquick oren receipt shop` | 2 → **1** |
| `rcpt-a-02-typed` | none | `Farmers Drug Pharmacy store opening date` (**hallucinated vendor**) | 2 → **1** |
| `rcpt-c-09-full` | none | verbose paraphrase | 2 → **1** |

The four `in query` rescues are the clean demonstration. `rcpt-c-10-typed` and
`rcpt-d-09-typed` had rewritten queries that were **nothing but the timestamp** — the
user's text ("kedai buku new acheivers both bills added up", "kedai papan 21 march both
bills together") was discarded entirely. Handing ColQwen the raw question instead puts
the gold at rank 1. `rcpt-a-02-typed` is the other diagnostic: the rewriter invented
"Farmers Drug Pharmacy" from "f&p phamacy"; the raw misspelled string does better than
the fluent hallucination.

`rcpt-d-05-full`/`-typed` also settles a prior-report failure attribution. The prior
report filed AA Pharmacy under "Cause B — category match beats identity match", with a
corpus-legibility contributor (ink 0.008). Both phrasings were missed from the top 12 in
both prior passes. With the raw query, `-full` is **rank 1** and `-typed` is **rank 2**.
ColQwen could always find that receipt; the query it was given could not.

**Lost (hit@1→miss), 9 rows.** 5 of the 9 had no date contamination at all — these are
the price of the ablation:

| qa_id | raw user text | prior rewrite | prior FGR → this FGR |
|---|---|---|---|
| `rcpt-a-05-typed` | `zheng hui gst amout` | `GST amount Zheng Hui` + 9 kw | 1 → **miss@12** |
| `rcpt-e-05-typed` | `great zone kluang gst amount` | `Great Zone Kluang GST amount` + 5 kw | 1 → 2 |
| `rcpt-en-03-typed` | `gin kee january dates` | `January dates for Gin Kee` + 9 kw | 1 → 4 |
| `rcpt-b-09-typed` | `hon hwa hardware how much altogether` | `Hon Hwa Hardware total price` | 1 → 4 |
| `rcpt-b-01-typed` | `jiawei dinner total` | same query + 11 kw | 1 → 3 |
| `rcpt-a-06-typed` | `yong tat hardware what did i buy` | `Yong Tat hardware purchase history` | 1 → 6 |
| `rcpt-e-02-typed` | `mei let restarant when` | `restaurant reservation Mei … EDT` | 1 → 8 |
| `rcpt-d-03-full` | `Which shopping centre was that Kaison receipt from?` | `Kaison receipt shopping centre` | 1 → 2 |
| `rcpt-e-07-full` | `Which Guardian branch … Freeman face mask …?` | `Guardian branch where I bought Freeman face mask` | 1 → 2 |

**8 of the 9 losses are `typed`.** The pattern in the rewrite column is the same every
time: **proper-case the entity, strip the interrogative scaffolding, append 5–11
content keywords.** `rcpt-e-05-typed` is the sharpest instance — the rewrite carries
the *same tokens in the same order* as the raw question, differing essentially only in
capitalisation plus a duplicated keyword tail, and the gold moves 1 → 2.

### 4.5 The ceiling moved, and the questions that fell off it are all misspelled

`hit@12` [A] 0.934 → 0.962. Gained 6, lost 3. The 4 questions where the gold is **not
in the top 12 at all** this run:

| qa_id | raw question | prior sweep FGR | note |
|---|---|---|---|
| `rcpt-a-05-typed` | `zheng hui gst am`**ou**`t` | **1** | "amount" misspelled |
| `rcpt-c-03-typed` | `la station`**a**`ry change back` | **4** | corpus prints `LA STATIONERY`; rank 1 is `TEO HENG STATIONERY & BOOKS` |
| `rcpt-d-04-typed` | `sen lee heong re`**c**`ipt date` | **2** | "receipt" misspelled |
| `rcpt-e-10-typed` | `mr diy march total spent` | miss | **golden-set defect**, see §7 Cluster E |

**Three of the four new ceiling misses are typed queries containing a typo, and all
three were inside the top 12 under the rewriter (ranks 1, 4, 2).** That is the run's
single most actionable retrieval finding: **the rewriter's real load-bearing function
on this corpus was spell-correction and case normalisation, not semantic expansion.**
`rcpt-e-10-typed` is not a retrieval failure at all (§7).

---

## 5. Q2 — the empty-keyword problem: the sparse tier is not underfed, it is absent

### 5.1 The measurement

`raw_query()` fills `keywords` via `extract_rare_tokens()` (`search.py:985-1007`), whose
regex `_RARE_TOKEN_RE` (`search.py:973-983`) matches only camelCase, PascalCase-with-
internal-capital, snake_case, `filename.ext`, and letters-glued-to-digits.

**116 of 120** questions produced an empty keyword list, in `retrieve.jsonl` *and*
`answers.jsonl` (identical, as expected for a deterministic function). The 4 non-empty:

| qa_id | keywords | why it matched |
|---|---|---|
| `rcpt-b-03-full` | `['RM30']` | `[A-Za-z]+\d+` |
| `rcpt-b-04-full` | `['RM81']` | `[A-Za-z]+\d+` |
| `rcpt-d-02-full` | `['RM100']` | `[A-Za-z]+\d+` |
| `rcpt-nf-01-full` | `['PappaRich']` | PascalCase |

All four are `full` phrasings; **zero typed**. Typed questions are written entirely in
lowercase with no glued digits, so every alternative in the regex is structurally
unreachable. And in all four cases the extracted token is **already present verbatim in
the query string** — the fast tier concatenates `sq.query + " " + " ".join(sq.keywords)`
(`search.py:849`), so the mechanism's entire contribution this run was **one duplicated
token on 4 of 120 questions**. It is a no-op, not a partial win.

### 5.2 …and it could not have mattered anyway

The docstring at `search.py:1020-1022` — "the sparse tier gets the identifier-shaped
tokens weighted on their own" — describes a tier that **is not running on this corpus**:

- `raw/qdrant/collections/` contains exactly **one** collection: `fast_tier`. There is
  no `summaries` collection (`db.py:45`: `COLLECTION_NAME = "summaries"`).
- `_search_summary_tier` therefore returns `[]` at its first branch,
  `search.py:369-371` (`if not client.collection_exists(COLLECTION_NAME): return []`),
  **before** it ever reaches `dense_text`, `embed_sparse_query`, or the dedicated
  keyword prefetch at `search.py:410-420`.
- `appdata/manifest.json`: **148/148 entries have `summary_file: null`** and
  `fast_indexed_at` set — the summary tier indexed nothing, exactly as the prior
  supervisor report's finding #6 describes (images are routed to the fast tier at
  `stage1_fast/router.py:110-111` and stripped at `stage1/summarize.py:790-794`).

**Corroborating evidence from the `tier` field, as asked:**

| file | hits | `tier` values | `score − 1/(60+rank)` |
|---|---|---|---|
| `retrieve.jsonl` (this run) | 1440 | `fast`: 1440 | **0.0 on all 1440** |
| `answers.jsonl` (this run) | 375 | `fast`: 375 | **0.0 on all 375** |
| prior run, both files | 1702 | `fast`: 1702 | 0.0 on all |

`_rrf_merge` (`search.py:598-644`) stamps `tier="both"` when a key appears in both
input lists and sums `1/(60+rank)` per list. **Not one hit in 1815 is `both` or
`summary`, and not one score deviates from a single `1/(60+rank)` term.** RRF fused one
non-empty list with one empty list and degenerated into a rank rewrite of ColQwen's own
MaxSim ordering. Corollary: the top1−top2 margin is the constant `0.0002644104` on every
row of both files — score magnitude carries literally zero information beyond rank, so
**no absolute-score abstention threshold is constructible in this configuration.** That
is a structural contributor to the 7/14 false answers on the `not_found` probes (§8.3).

### 5.3 So what does it tell us?

**Retrieval improved by 3.8 points [C] while the lexical tier contributed exactly
nothing, in both runs.** That is not evidence that BM25 is worthless on receipts — it is
evidence that **this corpus has never had a lexical tier at all**, so the entire
148-page ranking is a single-signal system: ColQwen MaxSim over the page image, with the
query text as the only lever.

Everything in §4.4 and §6 follows from that. A lexical tier is exactly what would fix
the failures that remain:

- **§4.5's three misspelling misses.** A BM25 index over OCR'd receipt text with fuzzy
  vendor matching resolves `stationary`→`STATIONERY`, `recipt`→`RECEIPT`,
  `phamacy`→`PHARMACY` for free. A visual patch retriever has no notion of edit distance.
- **§7 Cluster A's sibling collisions.** `receipt_X51005444040` vs `…041` differ by one
  day and one amount; `…746203` vs `…746207` by an invoice number. An exact string match
  on `08/03/18` or `746203` decides them instantly. Patch-level MaxSim over a
  down-sampled page cannot.
- **§7 Cluster B's category collisions.** `AA PHARMACY` vs `F&P PHARMACY`,
  `LA STATIONERY` vs `TEO HENG STATIONERY`, `YONG TAT HARDWARE` vs `HON HWA HARDWARE` —
  in every case the shared token is the *category* and the discriminator is a short
  proper noun. That is the canonical BM25 win.

**Recommendation.** Either (a) index an OCR text tier for image corpora so
`summaries` is non-empty and the keyword prefetch has something to prefetch from, or
(b) stop shipping `extract_rare_tokens` as if it helps here and document that on
lowercase natural-language queries it returns nothing. Doing (b) alone leaves the
docstring's claim false on 97% of realistic inputs. If neither is done, at minimum have
`run.py` refuse `index_summary_tier: true` on an all-image dataset instead of recording
it as though it took effect.

---

## 6. Q3 — the phrasing gap widened, and the owner's hypothesis is right

### 6.1 The gap

| view | typed | full | gap |
|---|---|---|---|
| [A] sweep, prior | 0.698 | 0.868 | 17.0 |
| **[A] sweep, this run** | **0.679** | **0.906** | **22.6** |
| [B] e2e, prior | 0.673 | 0.840 | 16.7 |
| **[B] e2e, this run** | **0.692** | **0.900** | **20.8** |
| [C] e2e/106, prior | 0.660 | 0.792 | 13.2 |
| **[C] e2e/106, this run** | **0.679** | **0.849** | **17.0** |

(`metrics.json` `by_phrasing.retrieval_hit@1` — typed 0.679, full 0.906 — is view [A].
All six numbers the owner quoted reproduce exactly.)

The gap widened in every view. In [A] — the single-axis view — **typed actually went
down**, 0.698 → 0.679, while full went up 0.868 → 0.906.

### 6.2 Testing the hypothesis

Crossing phrasing with prior-run contamination class, [A] hit@1, paired:

| phrasing | prior class | n | prior | this run | Δ |
|---|---|---|---|---|---|
| **full** | no date | 32 | 0.938 | **0.938** | **0.000** |
| **full** | date in keywords | 14 | 0.857 | **0.857** | **0.000** |
| **full** | **date in query** | 7 | 0.571 | **0.857** | **+0.286** |
| **typed** | no date | 29 | 0.793 | **0.690** | **−0.103** |
| typed | date in keywords | 15 | 0.600 | 0.667 | +0.067 |
| typed | **date in query** | 9 | 0.556 | 0.667 | +0.111 |

**The hypothesis is confirmed, and the decomposition is unusually clean:**

- On `full` phrasings the rewriter was **purely a liability**. Where it did not
  contaminate, it changed nothing at all — 0.938 → 0.938 and 0.857 → 0.857, exact
  zeroes on 46 of 53 rows. Where it contaminated the query string, removing it bought
  **+28.6 points**. A verbose natural-language question already contains the vendor
  name properly capitalised, in context, with enough surrounding language for ColQwen;
  there was nothing left to add.
- On `typed` phrasings the rewriter was **doing real work on the clean rows**:
  −10.3 points on the 29 uncontaminated typed questions, which is by far the largest
  single effect in the table. That is the compensation being withdrawn.
- Typed queries got the smaller decontamination benefit (+11.1 vs +28.6), because a
  terse query that has *also* lost its entity to the rewriter (the prior report's 7
  vendor-drop cases, all typed) has two problems, and only one is fixed by removing the
  rewriter.

Both effects push the same way. **The gap widened because the rewriter's benefit was
concentrated entirely on terse queries while its harm was concentrated on verbose ones.**

### 6.3 What the rewriter was actually doing for terse queries

Reading the prior rewrites of the 8 typed regressions in §4.4 side by side with the raw
text, three mechanisms recur, and only the third is "semantic expansion":

1. **Spell correction.** `amout`→`amount`, `recipt`→`receipt`, `restarant`→`restaurant`,
   `stationary`→`stationery`, `phamacy`→`pharmacy`, `acheivers`→`achievers`. Six typed
   questions in the golden set carry a misspelling; the three that fell out of the top
   12 entirely (§4.5) are all in this set.
2. **Case normalisation.** `zheng hui`→`Zheng Hui`, `great zone kluang`→`Great Zone
   Kluang`, `gin kee`→`Gin Kee`, `hon hwa hardware`→`Hon Hwa Hardware`. This one has a
   plausible mechanism: **receipts are printed in UPPERCASE**, and a query token's
   surface case is part of what the ColQwen text encoder embeds.
3. **Scaffolding removal + keyword padding.** `yong tat hardware what did i buy` →
   `Yong Tat hardware purchase history`; `jiawei dinner total` + 11 appended keywords.

Case is the most interesting and the least proven. The strongest available evidence is
`rcpt-e-05-typed`, where the prior rewrite carries the same tokens in the same order and
differs essentially only in capitalisation, and the gold moves rank 1 → 2. A weaker
aggregate points the same way: among typed rows where the rewriter *added* capital
letters (n=29) removing it costs −6.9 points, while among typed rows where it did not
(n=24) removing it *gains* +4.2 points. **I flag this as a hypothesis, not a result** —
the two groups differ in more than case, and no within-run test is possible because
**all 53 typed questions are entirely lowercase**. It is cheap to settle: re-run the
sweep with `raw_query()` plus a title-casing pass, nothing else changed.

### 6.4 What would fix terse-query retrieval

In expected-value order, all deterministic, none requiring an LLM in the query path:

1. **Get a lexical tier onto image corpora** (§5.3). This is the fix that addresses
   spelling, sibling discrimination and category collision simultaneously, and it is the
   only one that addresses §7 Cluster A at all.
2. **Deterministic query normalisation before encoding**: a fuzzy match of query tokens
   against a vendor lexicon harvested from the index, plus title-casing of matched
   entities. Recovers `rcpt-a-05-typed`, `rcpt-c-03-typed`, `rcpt-d-04-typed`,
   `rcpt-e-02-typed`, `rcpt-d-05-typed` without a model call and without the timestamp,
   the hallucinated vendors, or the nondeterminism.
3. **Multi-query RRF**: encode the raw question *and* a normalised variant, fuse. Strictly
   dominates picking one — a terse query keeps its expansion and a verbose query keeps
   its uncontaminated original. This is the cheapest way to stop §6.2's two columns
   trading against each other.
4. **If the LLM rewriter comes back, constrain it**: strip the date preamble from the
   prompt; assert post-hoc that every rare token from the raw question survives into
   `query` or `keywords`, and fall back to `raw_query()` when it does not. That guard
   alone would have caught all 7 prior-run vendor drops, the `Farmers Drug Pharmacy`
   hallucination, and the two rows whose rewrite was nothing but a timestamp.

---

## 7. Q4 — where ranking still goes wrong

**25 of 106 questions do not have a gold file at rank 1 end-to-end** ([C]; 21 of them
returned a ranking, 4 errored). **17 are `typed`, 8 are `full`.**

| qa_id | ph | type | golds | [C] e2e FGR | [A] sweep FGR | prior [A] FGR | cluster |
|---|---|---|---|---|---|---|---|
| `rcpt-a-05-typed` | typed | extractive | 1 | miss | **miss@12** | 1 | **C** typo |
| `rcpt-c-03-typed` | typed | extractive | 1 | miss | **miss@12** | 4 | **C** typo + **B** |
| `rcpt-d-04-typed` | typed | extractive | 1 | miss | **miss@12** | 2 | **C** typo |
| `rcpt-e-10-typed` | typed | synthesis | 3 | miss | **miss@12** | miss | **E** golden defect |
| `rcpt-a-06-typed` | typed | extractive | 1 | miss | 6 | 1 | **B** hardware |
| `rcpt-c-09-typed` | typed | synthesis | 2 | miss | 5 | 6 | **A** Wan Sheng ×5 |
| `rcpt-e-02-typed` | typed | extractive | 1 | miss | 8 | 1 | **B** restaurant + typo |
| `rcpt-e-04-typed` | typed | extractive | 1 | miss | 4 | 4 | **A** Super Seven |
| `rcpt-e-04-full` | full | extractive | 1 | miss | 4 | 2 | **A** Super Seven |
| `rcpt-en-03-typed` | typed | enumeration | 6 | miss | 4 | 1 | **A** Gin Kee ×6 |
| `rcpt-b-09-typed` | typed | synthesis | 3 | **err** | 4 | 1 | **F** overflow |
| `rcpt-b-09-full` | full | synthesis | 3 | **err** | 1 | 1 | **F** overflow |
| `rcpt-c-10-full` | full | synthesis | 2 | **err** | 1 | 1 | **F** overflow |
| `rcpt-d-09-full` | full | synthesis | 2 | **err** | 1 | 1 | **F** overflow |
| `rcpt-b-01-typed` | typed | extractive | 1 | 3 | 3 | 1 | **B** restaurant |
| `rcpt-b-04-typed` | typed | extractive | 1 | 3 | 3 | 4 | **A** B.I.G. Δid=1 |
| `rcpt-e-09-typed` | typed | synthesis | 2 | 3 | 3 | 2 | **A** Popular ×4 |
| `rcpt-b-05-typed` | typed | extractive | 1 | 2 | 2 | 2 | **A** Δid=1 |
| `rcpt-d-02-typed` | typed | extractive | 1 | 2 | 2 | 3 | **B** |
| `rcpt-d-02-full` | full | extractive | 1 | 2 | 2 | 2 | **B** |
| `rcpt-d-03-full` | full | extractive | 1 | 2 | 2 | 1 | **D** hub |
| `rcpt-d-05-typed` | typed | extractive | 1 | 2 | 2 | **miss** | **B** pharmacy |
| `rcpt-e-05-typed` | typed | extractive | 1 | 2 | 2 | 1 | **D** hub |
| `rcpt-e-07-full` | full | extractive | 1 | 2 | 2 | 1 | **A** Gin Kee |
| `rcpt-e-10-full` | full | synthesis | 3 | 5 | 5 | 4 | **E** golden defect |

### Cluster A — near-duplicate siblings; the discriminator is a number

Five rows where the rank-1 file's scan ID is within 4 of the gold's — same store, same
scan session, same layout, same typeface:

| qa_id | rank 1 | gold | Δ id |
|---|---|---|---|
| `rcpt-b-04-typed` | `X51005444040` | `X51005444041` | **1** |
| `rcpt-b-05-typed` | `X51005568894` | `X51005568895` | **1** |
| `rcpt-e-09-typed` | `X51006008093` | `X51006008092` | **1** |
| `rcpt-e-04-typed` | `X51005746207` | `X51005746203` | **4** |
| `rcpt-e-04-full` | `X51005746207` | `X51005746203` | **4** |

The questions ask for a day-of-month (`bens grocer 8 mar cash or card`) or an amount
(`super seven 408 paid by what card`) — two-digit and three-digit glyph classes, the
worst case for a patch-level visual retriever operating on a down-sampled page. Note
`rcpt-e-04` is the row where the *full* phrasing supplied "four-hundred-odd ringgit" and
still landed the gold at rank 4: extra language does not help when the discriminator is
a numeral.

The larger vendor families behave the same way — `rcpt-c-09-typed` (5 Restoran Wan Sheng
receipts; sweep ranks 3–6 are all Wan Sheng, gold at 5), `rcpt-d-09-full` (6 consecutive
Kedai Papan invoices at ranks 1–6), `rcpt-e-09-typed` (4 Popular Book Co. receipts at
ranks 1, 2, 3, 6). **ColQwen finds the right store essentially always; it cannot pick
the right visit.**

### Cluster B — category match beats identity match

Rank 1 is a different vendor in the *same document category*, verified against the
golden set's own `vendor_as_printed` labels:

| qa_id | gold vendor | rank-1 vendor | shared token |
|---|---|---|---|
| `rcpt-a-06-typed` | YONG TAT **HARDWARE** | HON HWA **HARDWARE** TRADING | hardware |
| `rcpt-c-03-typed` | LA **STATIONERY** | TEO HENG **STATIONERY** & BOOKS | stationery |
| `rcpt-d-05-typed` | AA **PHARMACY** | F&P **PHARMACY** | pharmacy |
| `rcpt-b-01-typed` | RESTAURANT JIAWEI | ROCKU YAKINIKU | (restaurant/dinner) |
| `rcpt-e-02-typed` | MEI LET **RESTAURANT** | RESTORAN WAN SHENG | restaurant |

Every one is `typed`. In every one the *only* discriminator is a 2–8 character proper
noun — `AA`, `LA`, `Yong Tat`, `Mei Let` — set in a thin dot-matrix or thermal face at
the top of the page, while the category word is rendered large. This is the failure
class §5.3's lexical tier exists to fix, and the one the cross-encoder would normally
be positioned to correct if it could see the document (§8.2). Note `rcpt-d-05-typed`
*improved* from miss@12 to rank 2 this run — the prior report's AA Pharmacy
"identity vs category" diagnosis was over-attributed to the retriever; a third of it
was the rewritten query.

### Cluster C — misspelled terse queries fall out of the index's reach

`rcpt-a-05-typed`, `rcpt-c-03-typed`, `rcpt-d-04-typed`. New this run, covered in §4.5
and §6.3. These are the only three rows where retrieval got *categorically* worse rather
than a rank or two worse.

### Cluster D — the document-quality prior

Query-independent hub attractors persist. Over the 120 sweep queries:

| file | in top 12 | in top 3 | at rank 1 |
|---|---|---|---|
| `receipt_X51005757220.jpg` | **36 (30%)** | 0 | 0 |
| `receipt_X51006008105.jpg` | 30 | 6 | 0 |
| `receipt_X51005442322.jpg` (Tony Roma's) | 27 | 10 | 3 |
| `receipt_X51006008206.jpg` (Burger King KLIA) | 27 | 6 | 3 |
| `receipt_X51005337867.jpg` (Oldtown White Coffee) | 24 | 9 | 4 |

**Only 65 of 148 files ever take rank 1** (prior run: 64). Two rows are attributable
directly: `rcpt-e-05-typed` loses rank 1 to `X51005442322` (Tony Roma's), and
`rcpt-d-03-full` / `rcpt-d-04-typed` both lose it to `X51005806695`. The prior report's
ink-density analysis of this effect stands unchanged — it is a property of the corpus
and the encoder, not of the query, and neither knob moved this run. Worth recording that
the *shape* improved slightly: the worst attractor fell from 42/120 top-12 appearances
to 36/120, consistent with raw queries being more specific than 5-to-11-keyword
expansions.

### Cluster E — golden-set defect, not retrieval

`rcpt-e-10-typed` / `-full` ("mr diy march total spent" / "…across those March trips").
Gold is 3 specific Mr D.I.Y. receipts. `-typed` rank 1 is `X51005337867` and `-full`
rank 1 is `X51005719898`, which the prior report opened and confirmed to be
**`MR. D.I.Y.(KUCHAI) SDN BHD`, dated 19-03-18** — a genuine Mr D.I.Y. receipt from
March, simply not one of the 3 the golden set silently chose. Retrieval found the right
vendor and the right month. **This should not be scored as a retrieval miss, and it is
one of the 4 rows defining the `hit@12` ceiling.** Re-adjudicate before quoting 0.962 as
a ceiling; the honest ceiling is 0.972 with `rcpt-e-10-typed` excluded.

### Cluster F — the 4 errors are not retrieval failures

`rcpt-b-09-typed/-full`, `rcpt-c-10-full`, `rcpt-d-09-full`. Sweep first-gold-rank
1, 4, 1, 1. The LIST_ALL widener fired 7 times (`top_k 3→12`, `raw/worker_answer.log`),
handed each question 12 receipt images, and 4 overflowed the 16384-token context. **These
questions had near-perfect retrieval and the generator received nothing.** They are
counted as misses in [C] because that is what the user experienced, but the cause is the
widener's token budget, not the ranker. Identical to the prior run in every particular —
same 4 questions, same 7 widenings, same overflow token counts.

### The ceiling

[A] `hit@12` = 0.962 → 4 of 106 questions have no gold in the top 12: three Cluster C
misspellings and one Cluster E golden defect. `recall@12` = 0.952. **The ranking already
contains the evidence for 95% of questions within 12 candidates.** For multi-gold
questions specifically, sweep `recall@12` is **0.918** (prior 0.861) against an
end-to-end `recall@3` of **0.575**. The dominant multi-file loss is still the fan-out,
not the ranker — but `k=3` narrowed it substantially: the structural recall ceiling for
the 26 multi-gold questions rose from **0.794** at `k=2` to **0.883** at `k=3`, and
achieved [C] recall rose from **0.441** to **0.575**.

Enumeration remains fan-out-bound. Gold ranks in the depth-12 sweep:

| qa_id | golds | gold ranks (this run) | prior | e2e recall at k=3 |
|---|---|---|---|---|
| `rcpt-en-01-typed` / `-full` | 5 | 1,2,3,4,5 | 1,2,3,4,5 | 0.600 |
| `rcpt-en-02-typed` | 8 | 1,2,3,4,5,6,7 | same | 0.375 |
| `rcpt-en-02-full` | 8 | 1,2,3,4,5,6,7,**9** | …,11 | 0.375 |
| `rcpt-en-03-full` | 6 | 1,2,3,**4,5,7** | 1,2,3,6,8,11 | 0.500 |
| `rcpt-en-03-typed` | 6 | **4,7,12** | 1,2,3,4,5,6 | **0.000** |

Removing the rewriter **improved** enumeration clustering on `-full` (en-03-full's
6 golds tightened from ranks 1–11 to 1–7) and **destroyed** it on `rcpt-en-03-typed`
("gin kee january dates"), which fell from a perfect 1–6 to 4/7/12 — the single largest
regression in the run, and the sole reason enumeration hit@1 fell 1.000 → 0.833. Same
Cluster C mechanism: a terse lowercase query the rewriter used to proper-case.

### Slice tables (all views, paired against the prior run)

hit@1 by slice. [A] n as shown; [B] excludes that slice's errored rows; [C] denominator = [A]'s n.

| slice | n | [A] prior → this | [B] prior → this | [C] prior → this | [A] recall@12 this | [C] recall@3 this |
|---|---|---|---|---|---|---|
| extractive | 80 | 0.800 → 0.800 | 0.775 → 0.800 | 0.775 → 0.800 | 0.963 | 0.912 |
| synthesis | 20 | 0.650 → 0.750 | 0.562 → 0.750 | 0.450 → 0.600 | 0.925 | 0.625 |
| enumeration | 6 | 1.000 → 0.833 | 1.000 → 0.833 | 1.000 → 0.833 | 0.896 | 0.408 |
| easy | 40 | 0.925 → 0.925 | 0.900 → 0.925 | 0.900 → 0.925 | 1.000 | 1.000 |
| medium | 40 | 0.675 → 0.675 | 0.650 → 0.675 | 0.650 → 0.675 | 0.925 | 0.825 |
| hard | 26 | 0.731 → 0.769 | 0.682 → 0.773 | 0.577 → 0.654 | 0.918 | 0.575 |
| multi_file=false | 80 | 0.800 → 0.800 | 0.775 → 0.800 | 0.775 → 0.800 | 0.963 | 0.912 |
| multi_file=true | 26 | 0.731 → 0.769 | 0.682 → 0.773 | 0.577 → 0.654 | 0.918 | 0.575 |
| typed | 53 | 0.698 → 0.679 | 0.673 → 0.692 | 0.660 → 0.679 | 0.903 | 0.783 |
| full | 53 | 0.868 → 0.906 | 0.840 → 0.900 | 0.792 → 0.849 | 1.000 | 0.877 |

"hard" and "multi_file=true" are the same 26 rows with identical numbers — difficulty on
this golden set is a proxy for gold-source count, not question subtlety. Extractive
retrieval is flat in [A] and improves 2.5 points in [B]/[C]; synthesis improves most
(+10 [A], +15 [C]) because 4 of its 20 rows are the widener overflows and the rest
benefited from decontamination; enumeration is the one regression, and it is one
question.

---

## 8. Q5 and Q6 — gate and rerank

### 8.1 The gate never fired. This run says nothing about gate quality.

Confirmed from the data, four independent ways:

1. `answers_enriched.json`: `solo_gated` is **`False` on all 120 rows**.
2. `len(retrieved)` distribution end-to-end: **3 on 113 rows, 12 on 3 rows (widener),
   0 on the 4 errors — no row anywhere collapsed to 1.**
3. `grep -c "solo-gate" raw/worker_answer.log` = **0**. `gate_to_solo` prints on every
   firing (`search.py:955-961`).
4. `metrics.json` `solo_gate.fire_rate: 0.0`; `run.json` stamps
   `solo_gate_structurally_off: true`.

It is over-determined three times over, exactly as in the prior run:

- `gate_to_solo` early-returns when `_rerank_enabled()` is false (`search.py:923`), and
  `MAGPIE_RERANK=0` is in `env_snapshot`;
- past that, `LOCAL_SOLO_MARGIN=0` and the function returns unchanged for
  `threshold <= 0`;
- past *that*, the measured top1−top2 margin is the constant **0.0002644104** — RRF
  reciprocal scale — against a threshold calibrated on cross-encoder scale. Four orders
  of magnitude short on every one of 116 rows.

**Stated plainly: this run contains zero information about whether the solo gate is a
good idea.** `fire_rate: 0.0` is correctly reporting a deliberately disabled component,
not measuring one. H5 remains blocked.

**Caveat on the instrument.** `enrich.py:301-305` infers `solo_gated` as
`len(post_gate) == 1 and len(ranked_paths) >= 2`, where `ranked_paths` comes from the
**sweep** (`enrich.py:314-318`), not the product's pre-gate list. Under `top_k=3` a
genuine firing would still be detected (3 → 1), but the detector is reading the wrong
list, and its companion field `ranked_pre_gate` is 12 on every row regardless. Fix it
alongside §1.5.

### 8.2 Rerank is off, and product bug #1 is confirmed in the code

`rerank=false` → all rankings are ColQwen fusion order (§5.2 proves this: pure
`1/(60+rank)`, single non-empty list).

**The placeholder claim is confirmed.** `_search_fast_tier` constructs every fast-tier
result with a constant summary at **`src/stage2/search.py:553`**:

```python
SearchResult(
    summary=f"(visual match — page {page})",
    path=path, score=score, tier="fast",
)
```

`src/stage2/rerank.py:_doc_text` (line 68) returns `c.summary or c.path`, and
`rerank()` builds `pairs = [(query, _doc_text(c)) for c in candidates]` and calls
`model.predict(pairs)`. `rerank.py`'s own comment acknowledges it —
*"fast-tier-only hits show `(visual match — page N)` as their summary; that's still
informative"* — which is not true here: on a single-page-per-file corpus **every
candidate's document text is the byte-identical string `"(visual match — page 1)"`**.
The cross-encoder would therefore assign every candidate the same score, and
`scored.sort(key=..., reverse=True)` would return them in input order modulo sort
stability. Reranking a visual corpus in this configuration is not a weak signal; it is
**no signal at all**, dressed as one, with `SearchResult.score` overwritten by a number
that means nothing. Turning it off for these runs was correct.

`MAGPIE_RERANK_PATH=1` (`rerank.py:79-86`) would prepend the file path, which on this
corpus is `receipts batch_04 receipt_X51005663307.jpg` — a scan ID with no semantic
content. It does not rescue the stage.

**What it would take to make rerank meaningful on visual corpora**, in order of cost:

1. **Give the cross-encoder real text.** OCR each page at index time and store it on the
   fast-tier point, so `_doc_text` returns the receipt's actual contents. This is the
   same artefact §5.3 needs for BM25, so one indexing change fixes both the missing
   lexical tier and the dead reranker. It is also the only fix that addresses Cluster A,
   where the discriminator is a printed numeral.
2. **Or use a visual reranker** — a VLM or ColPali-style late-interaction scorer that
   takes the page image, not a text summary. Correct in principle, expensive per query,
   unproven at this latency budget.
3. **Failing either, make the stage refuse rather than pretend.** `rerank()` should
   detect that all `_doc_text` values are identical (or that every candidate is
   `tier == "fast"` with a placeholder summary), skip the forward pass, and return the
   fusion order unmodified — instead of overwriting `score` with a meaningless
   cross-encoder output. That also unblocks the solo gate honestly: today the gate is
   disabled because its margin is on a scale that does not exist, and a stage that
   declared "I could not judge these" would let the gate stay disabled *for a stated
   reason* rather than by a chain of three coincidences.

Only after (1) or (2) can a rerank-ON/OFF eval mean anything — and §3's `worker.py:393`
must be fixed first, or that eval will publish a null result whatever the truth is.

### 8.3 Footnote: the 14 `not_found` probes

Excluded from all retrieval metrics (no qrels), but relevant to §5.2. All 14 returned
3 files with the constant `0.0002644104` top-1/top-2 margin, and 7 produced a confident
false answer (`rcpt-nf-02-full` "RM 77.40", `rcpt-nf-05-full` "4.20",
`rcpt-nf-06-full` "30.48", `rcpt-nf-06-typed` "Tanjongmas Book Centre", …). With every
score a rank reciprocal, **there is no retrieval-side signal available to abstain on** —
a question about a vendor that does not exist in the corpus produces exactly the same
score profile as one about a vendor that does. Any abstention improvement has to come
from the answer stage or from a scored (non-RRF) retrieval signal.

---

## 9. What to change, in expected-value order

1. **Score `metrics.json`'s `retrieval` block from `answers.jsonl.retrieved`**, errored
   rows counted as misses; keep the depth-12 sweep under a separate key if it is still
   wanted (`enrich.py:314-318`). This run's published +0.9 points is a real +3.8.
2. **`rerank=bool(params.get("rerank", True))` at `worker.py:395`** — one line, and it
   is the difference between a future rerank A/B measuring something and measuring
   nothing (§3).
3. **Index an OCR text tier for image corpora.** One artefact unblocks the missing
   lexical tier (§5.3), the dead cross-encoder (§8.2), the misspelling cluster (§7 C),
   the category-collision cluster (§7 B) and the sibling-discrimination cluster
   (§7 A). Nothing else on this list has that reach.
4. **Deterministic query normalisation in place of the LLM rewriter** — vendor-lexicon
   fuzzy match plus entity title-casing, or dual-query RRF (§6.4). Recovers the 3
   ceiling misses and the 8 typed regressions without reintroducing the timestamp, the
   hallucinated vendors, or the nondeterminism.
5. **Fix the LIST_ALL widener's token budget.** Four questions with first-gold-rank
   1, 4, 1, 1 returned nothing, for the second run running (§7 F). This is now a
   reproduced, unfixed defect, not a one-off.
6. **Re-adjudicate `rcpt-e-10`** — it is 1 of the 4 questions defining the `hit@12`
   ceiling and it is a golden-set defect, not a retrieval miss (§7 E).
7. **Do not read anything into `solo_gate.fire_rate: 0.0`,** and fix `enrich.py`'s
   gate detector to read the product's pre-gate list rather than the sweep's (§8.1).

## 10. Hypothesis status

- **H2′ (phrasing robustness)** — now *partially* readable, with a caveat. The prior
  run was uninterpretable because typed/full was confounded with rewriter damage. That
  confound is gone: queries are verbatim user text on both paths. The [A] gap of
  **22.6 points** (typed 0.679, full 0.906) is a genuine measurement of raw-query
  phrasing robustness on a visual-only retrieval stack. But it is *not* a general
  phrasing result — §5.2 shows the stack has one signal, and §6.3 shows the gap is
  largely spelling and case, not verbosity. Report it as "phrasing robustness of
  ColQwen-only retrieval on raw queries", never as "Magpie's phrasing robustness".
- **H5 (solo gate)** — still blocked, over-determined (§8.1).
- **H1** — retrieval placed a gold file in the prompt on **91.2%** of extractive
  questions ([C] hit@3 on the 80 extractive rows, all of which are single-gold; [A]
  recall@12 on the same rows is 96.3%). Whatever the answer stage did with that is not
  a retrieval finding; see `REPORT-answers`.
