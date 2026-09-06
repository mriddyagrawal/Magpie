# REPORT — RETRIEVAL

Run: `20260906T090247Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
Dataset: `custom_dataset_rahul_Aug30` (545 files on disk, 100% visual), golden 120 items / 60 pairs, `golden_sha 0ebcdcbcdf109adb`
Config: `top_k=2`, `top_k_retrieval_max=12`, `rerank=false`, `rewrite=false`, `solo_margin=0`, `fast_search=true`, `enumerate_lists=true`, ColQwen2.5 visual tier
Index: MOUNTED from cache, key `66974090bdcd62e6`, built 2026-08-30 under backend `cca67570` — content identical to `20260830T095758Z-…`
Scope: retrieval ranking only. Generation, citations and verdicts belong to the answers/judge reports.

Established elsewhere and taken as given (not re-derived here): the `retrieved` list is
byte-identical to `20260830T095758Z-…` on all 117 rows that completed in both; the only metric
that moved is nDCG@5 via `viz-11`. §2.4 explains *why* viz-11 is the one unstable item.

---

## 0. Headline

| | as published | honest denominator |
|---|---:|---:|
| rows scored | 104 / 120 | 98 / 120 |
| hit@1 (sweep) | 0.9327 | **0.9898** |
| hit@5 (sweep) | 0.9423 | **1.0000** |
| recall@5 (sweep) | 0.9193 | 0.9756 |
| recall@12 (sweep) | 0.9359 | 0.9932 |
| MRR (sweep) | 0.9346 | 0.9918 |
| nDCG@5 (sweep) | 0.9205 | 0.9768 |
| nDCG@5 (end-to-end) | 0.8987 | 0.9537 |

**The one-line finding: ColQwen2.5 did not fail at ranking on this corpus.** On the honest
denominator every indexed gold file is inside the top 5 on every scored question — `hit@5 = 1.000`,
98/98. Six of the seven `hit@12 = 0` rows have gold that was **never written to the index**, and
the seventh (`rcpt-08-typed`) is a partial miss on a multi-file enumeration. There is exactly
**one** genuine rank-1 ranking failure with indexed gold in the whole run: `rcpt-05-typed`.

The headline retrieval numbers in `metrics.json` are depressed almost entirely by two things that
have nothing to do with ranking quality: an index that silently dropped 25 files (§3.1), and a
`top_k=2` output budget that cannot physically carry multi-gold answers (§3.2).

---

## 1. What the two metric families measure, and why they differ

`metrics.json` publishes two blocks over the same 104 rows.

**`retrieval` (the SWEEP basis).** Computed over `raw/retrieve.jsonl` → `ranked`, a *second*
retrieval pass run at `top_k = top_k_retrieval_max = 12` with the query replayed verbatim from the
answer pass (`query_source: "replayed_from_answer_pass"`; `retrieval_query_matched` is `true` on
all 104 rows, `n_query_differs: 0`). This is the ranker's own opinion, 12 files deep, untouched by
anything downstream. `enrich.py:331` writes it.

**`retrieval_end_to_end`.** Computed over `answers_enriched.json` → `retrieved`, i.e. what `ask()`
*actually handed the generator* after `top_k` truncation and any post-processing. `enrich.py:339-341`
writes it, with the comment "recall@k beyond top_k is not measurable on this basis".

Four distinct mechanisms separate them:

1. **Truncation at `top_k=2` (dominant).** 89 of 104 scored rows carry exactly 2 files end-to-end.
   `hit@12` on the e2e basis is a misnomer: it is `hit@2`. This alone explains the whole
   `recall@12` gap (sweep 0.9359 → e2e 0.8841, −0.0518) and most of the nDCG@5 gap.
2. **`enumerate_lists` widening.** 10 rows classified `list_all` widened `top_k 2→12`
   (`raw/worker_answer.log:1853-1862`): `arch-06-full`, `study-03-full`, `rcpt-01-full`,
   `rcpt-08-typed`, `rcpt-08-full`, `phone-05-typed`, `phone-05-full`, `phone-07-typed`,
   `phone-11-full`, `nf-06-full`. On these rows the two bases see the same depth. Note the
   phrasing asymmetry: 7 full vs 3 typed (§5).
3. **Fast-tier page-collapse at small `fetch_k`.** 6 rows returned exactly **one** file
   end-to-end (§4). This is the "solo gate" that isn't.
4. **Tie-order instability in the candidate pool.** With `rerank=False`, `fetch_k = top_k`
   (`search.py:836`), so the answer pass asks ColQwen for `2×2 = 4` pages and the sweep asks for
   `12×2 = 24`. Different pool depths break ties differently when documents are byte-identical.
   This is the *only* source of `n_top1_differs: 2` — both are `viz-11` (§2.4).

Because rerank is off, `run_search` returns `fused[:top_k]` in RRF order. And here RRF is a no-op:
**every one of the 1,437 sweep hits carries `tier: "fast"`, and every score is exactly
`1/(60+rank)`** — 12 distinct values across the entire run. Only one list voted, so the fused order
*is* the raw ColQwen MaxSim order. See §6 for why the other list was empty.

---

## 2. Every genuine ranking failure, individually

Definitions used below: a row is at its **recall ceiling** when it retrieved every relevant file
it could have at that depth (`min(k, n_rel)/n_rel`). 97/104 rows sit at their `recall@1` ceiling,
94/104 at `recall@5`, 97/104 at `recall@12`.

### 2.1 `rcpt-05-typed` — the only true rank-1 failure (indexed gold)

| | |
|---|---|
| Question (typed) | *"that shop where i bought loads of chocolate bars total"* |
| Gold | `bad_receipt_014.jpg` (1 relevant, no acceptables) |
| Gold rank (sweep) | **5** — first four slots all non-relevant |
| recall@1 / recall@5 | 0.000 / 1.000 · nDCG@5 sweep 0.387, **e2e 0.000** |
| Same pair, full phrasing | gold at **rank 1**, all metrics 1.000 |

Sweep top-5: `scene_887bfd79f29a3fcb.jpg` (scene_text) · `110671448.jpg` (photos) ·
`info_008.jpg` (infographics) · `receipt_024.jpg` (receipts_phone) · `bad_receipt_014.jpg` (gold).

**Mechanism — ColQwen visual literalism on the word "shop".** I opened the two displacing files.
`scene_887bfd79f29a3fcb.jpg` is a photograph of a **Hallmark store frontage** in a shopping mall —
signage, shelves, gift displays. `110671448.jpg` is the **interior of a café/shop** with a
"CHILLER" drinks cooler and packaged goods on shelving. ColQwen2.5 is a page-image encoder: given
a query whose only concrete noun is *shop*, it retrieves pictures of shops. The user meant "which
retailer issued this receipt", which requires reading a *document*, not recognising a *scene*.
There is no lexical channel in this run (§6) to counterbalance with "total".

The full phrasing rescues it by adding `Delicia`, `chocolate bars`, and `come to` — enough
document-ish and product-ish signal to move the receipt to rank 1. `Delicia` is not
identifier-shaped, so `extract_rare_tokens` did **not** produce it (§6); the gain came purely from
extra content words concatenated into the ColQwen query text.

Cost: this is the single row responsible for `hit@1` typed 0.9231 vs full 0.9423 in `metrics.json`,
and on the honest denominator for typed hit@1 0.9796 vs full 1.0000. At `top_k=2` the generator
never saw the receipt at all (`e2e recall@12 = 0.00`).

### 2.2 `rcpt-08-typed` — genuine partial miss on multi-file enumeration

| | |
|---|---|
| Question (typed) | *"how much did i spend at mr diy altogether"* |
| Gold | `bad_receipt_002.jpg`, `bad_receipt_004.jpg`, `bad_receipt_027.jpg` |
| Sweep ranks | 1 / **not in top-12** / **not in top-12** |
| recall@12 | **0.333** — the only indexed-gold row below its `recall@12` ceiling |
| Same pair, full | ranks 1 / 2 / 8 → recall@12 **1.000**, recall@5 0.667 |

Sweep top-4 (typed): `bad_receipt_002.jpg` (gold) · `screen_24454.jpg` · `screen_24403.jpg` ·
`info_002.jpg`.

**Mechanism, part 1 — layout matching, not semantics.** `screen_24454.jpg` is an Android app
screenshot ("Near Me") that is a **vertical list of rows, each with a large bold number in a black
box**, ending in a currency ad banner reading "$ to £. Best rates." Nothing about it is a receipt
or a purchase. ColQwen matched the *shape* of "a column of numbers with currency glyphs" against a
query about spending totals. Two screenshots and an infographic take slots 2-4 on a query whose
gold class is receipts.

**Mechanism, part 2 — degradation, not relevance.** I opened the found and the missed gold.
`bad_receipt_002.jpg` is a clean, tightly-cropped, high-contrast phone photo where
`MR D.I.Y. (JOHOR) SDN BHD` is plainly legible; it ranks 1 under both phrasings.
`bad_receipt_027.jpg` is the opposite: a small, tilted, washed-out receipt occupying roughly a
fifth of a large blank grey page, with heavy bleed-through, and the merchant line degraded to
`MR. O.I.Y. (M) SDN BHD` (D→O). ColQwen encodes the **whole page** into ~750 patches; on that
image the receipt claims a small minority of them and the rest are noise. Recall here is a function
of scan quality, not of ranking logic. The full phrasing recovers it to rank 8 — the extra tokens
("Mr D.I.Y. receipts", "in total") help marginally but do not fix the underlying signal problem.

This row is the one place in the run where the `enumerate_lists` widener did its job and still
came up short: it *was* widened to 12, and 2 of 3 golds were still absent.

### 2.3 `study-02-typed` / `study-02-full` — acceptable-source shortfall only

Gold `CseGyan-Cpp-Notes-3.pdf` is at **rank 1 under both phrasings**. The shortfall
(`recall@5 = 0.75`) is in the three `acceptable_sources` (`Notes-4/5/6`): typed places 4, 5 at
ranks 3-4 and 6 at rank 7; full places 6, 5, 4 at ranks 3, 5, 6. An unlabelled sibling
(`CseGyan-Cpp-Notes-7.pdf`) takes rank 2 in both. The `n_rel = 4` denominator (1 gold + 3
acceptables) drags `recall@1` to 0.25 by construction. Not a ranking failure in any actionable
sense — the ranker put the right page first.

### 2.4 `viz-11-typed` / `viz-11-full` — a 9-way byte-identical tie, not a ranking event

`viz-11` gold is `diagram_003.jpg`, with `diagram_004…011` listed as `acceptable_sources`
(`n_rel = 9`). I hashed the corpus: **`diagram_003` through `diagram_011` are nine copies of one
identical file** (sha256 prefix `8acac741b245`). The whole `diagrams/` folder is 40 files
comprising 9 unique images — `diagram_014-017` are 4 copies, `diagram_022-027` are 6,
`diagram_028-035` are 8, `diagram_036-040` are 5.

Consequence: the sweep top-9 for both phrasings is exactly `diagram_003…011` in scrambled order.
The ranker identified the correct image perfectly. The metrics penalise it only because the golden
set assigned `rel=2` to one arbitrary member of the tie group and `rel=1` to the other eight:
`recall@1 = 0.111`, `nDCG@5` 0.856 (typed) / 0.747 (full).

This is the item the supervisor flagged as the sole nDCG mover between this run and
`20260830T095758Z-…`, and the mechanism is now explicit: **identical vectors produce identical
MaxSim scores, so the order among them is whatever Qdrant returns**, and the answer pass
(`fetch_k=2` → 4 pages requested) and the sweep (`fetch_k=12` → 24 pages requested) do not have to
agree. Both `retrieval_top1_matched: false` rows in the run are these two:

| row | sweep top-1 | e2e top-1 | nDCG@5 sweep → e2e |
|---|---|---|---|
| `viz-11-typed` | `diagram_004.jpg` | `diagram_011.jpg` | 0.856 → 0.413 |
| `viz-11-full` | `diagram_007.jpg` | `diagram_011.jpg` | 0.747 → 0.413 |

Treat every `viz-11` retrieval number as noise. Fix the dataset (deduplicate `diagrams/`, or mark
the tie group `rel=2` uniformly), not the ranker.

### 2.5 `study-04-typed` / `study-04-full` — nDCG-only, caused by `top_k=2`

Gold `CseGyan-Cpp-Notes-15.pdf` at rank 1 in both; acceptables `Notes-11`, `Notes-13` at ranks 3-4;
an unlabelled `Notes-14` at rank 2. Sweep nDCG@5 = 0.936 both. End-to-end nDCG@5 collapses to 0.639
purely because the top-2 window is `[gold, Notes-14]` and the two acceptables are cut. Ranking is
fine; the output budget is not.

### 2.6 The rest

The other 24 rows with `recall@1 < 1` are all multi-relevant items where both/all golds sit at
ranks 1 and 2 — `viz-05`, `viz-09`, `arch-07`, `arch-09`, `study-11`, `rcpt-09`, `phone-11`. Their
`recall@1` is capped at 0.5 arithmetically (§3.2). Every one is at its ceiling. `viz-05` and
`viz-09` additionally swap rank 1↔2 between phrasings with no metric consequence.

**Complete list of rows that are NOT at their `recall@12` ceiling: 7.** Six are index-drop
casualties (§3.1); the seventh is `rcpt-08-typed` (§2.2). That is the entire genuine recall failure
surface of this run.

---

## 3. Honest denominators

### 3.1 Gold that was never indexed — 6 rows, 3 pairs

The index manifest (`raw/appdata/manifest.json`) holds **520 entries against 545 files on disk**.
I diffed them: 25 files are absent, and no manifest entry carries a `skip_reason` — they were
attempted and rejected at upsert time. Root cause is established in
`runs/20260830T095758Z-…/REPORT-indexing.md` §2 (24 files produce all-NaN fp16 ColQwen embeddings,
which Qdrant rejects with `400 … did not match any variant of untagged enum VectorStruct`; 1 file,
`scan_nglg0227.pdf`, exceeds Qdrant's 32 MiB request cap). Losses by folder: `notes_handwritten`
14/37, `receipts_phone` 9/40, `scans_multipage` 2/19.

Three golden pairs have **100% of their gold** in that dropped set:

| pair | gold | rank achievable | what the ranker returned instead |
|---|---|---|---|
| `study-05` typed+full | `electric-charge-and-field-9.pdf` | **none — not in the index** | `electric-charge-and-field-10/7/4/5…` — the correct *topic* and the correct *document family*, nine sibling pages, in both phrasings |
| `study-10` typed+full | `CseGyan-Cpp-Notes-17/18/19.pdf` | **none — all three dropped** | `CseGyan-Cpp-Notes-14/15/11/4/13/16…` — again the right notebook, wrong (surviving) pages |
| `rcpt-07` typed+full | `receipt_040.jpg` | **none — dropped** | `receipt_005`, `12252043.jpg`, `receipt_014`, `receipt_021`… — the right category |

These six rows contribute `hit@k = 0`, `recall@k = 0`, `MRR = 0`, `nDCG@5 = 0` at every depth, on
both bases. They are **the entire difference** between the published and honest columns in §0. On
every one of them the ranker retrieved adjacent pages of the correct source document — it did the
right thing against the corpus it was given.

Removing them (n = 104 → 98) is the correct denominator for any statement about *ranking*:
**hit@1 0.9327 → 0.9898, hit@5 0.9423 → 1.0000, MRR 0.9346 → 0.9918.**

### 3.2 Recall capped by construction

- **`recall@1` is unreachable for 24 of 104 rows** (`n_rel > 1`). Mean ceiling is 0.8627 against
  an actual 0.8082 — so the true `recall@1` shortfall is 0.0545, not the 0.1918 the raw number
  suggests. `n_rel` distribution: 80 rows with 1, 14 with 2, 6 with 3, 2 with 4, 2 with 9 (viz-11).
- **`retrieval_end_to_end` recall is capped for 8 rows** where `n_rel` exceeds the number of files
  actually returned: `viz-11-typed/full` (9 relevant, 2 slots), `study-02-typed/full` (4 vs 2),
  `study-04-typed/full` (3 vs 2), `study-10-typed/full` (3 vs 2). Mean e2e ceiling is 0.9626
  against an actual 0.8841.
- The whole `metrics.json` `retrieval` block is computed on **104 of 120** items. The 16 `nf-*`
  not-found items carry no qrels rows and are excluded by design. Any "retrieval on this dataset"
  claim covers 104 questions, not 120.

### 3.3 The `notes_iam` distractor slice — 30 files, zero golden items

Per `run.json._notes.notes_iam_excluded`, the 30 IAM/LOB handwriting strips are indexed as
realistic distractors and carry no golden items, so **any hit on them is a false positive by
construction**. Measured:

| | count | share |
|---|---:|---:|
| `notes_iam` files in the index | 30 / 520 | 5.8% |
| slots occupied in the 12-deep sweep, all 120 rows | 10 / 1,437 | **0.7%** |
| slots occupied end-to-end, all 120 rows | 1 / 334 | **0.3%** |
| rows with any `notes_iam` file in the sweep top-12 | 10 / 120 | 8.3% |
| rows with a `notes_iam` file at sweep rank 1 | **1** (`nf-05-typed`) | 0.8% |
| rows with any `notes_iam` file reaching the generator | **1** (`nf-05-typed`) | 0.8% |

**Distractor pressure from this slice is negligible and, importantly, *sub-proportional*:**
`notes_iam` is 5.8% of the index but wins 0.7% of retrieved slots — ColQwen suppresses it roughly
8× below chance. The single rank-1 hit is `nf-05-typed`, whose entire question is the bare word
**"transcript"** — a not-found probe, correctly expected to retrieve nothing useful, and a
handwriting transcription strip is a defensible visual match for it. On the 104 scored rows,
`notes_iam` occupies **zero** end-to-end slots.

For contrast, here is where the non-relevant slots *actually* went across the 104 scored rows
(177 non-relevant end-to-end slots):

| folder | slots | share |
|---|---:|---:|
| screenshots | 29 | 16.4% |
| infographics | 20 | 11.3% |
| scene_text | 20 | 11.3% |
| receipts_phone | 19 | 10.7% |
| notes_handwritten | 17 | 9.6% |
| slides | 16 | 9.0% |
| documents | 13 | 7.3% |
| photos | 12 | 6.8% |
| receipts_degraded | 11 | 6.2% |
| tables_fr / scans_multipage / charts / figures / diagrams | 8/6/3/2/1 | 11.3% |
| **notes_iam** | **0** | **0.0%** |

The real distractor pressure is `screenshots` + `scene_text` + `photos` (52 slots, 29.4%) — the
visually rich, text-bearing, semantically-unrelated classes that §2.1 and §2.2 show ColQwen
matching on scene content and layout shape.

---

## 4. Gate behaviour: `solo_gate.fire_rate = 0.05` is an artefact. No gating occurred.

`run.json` stamps `solo_gate_structurally_off: true`, and it is correct. The margin the gate keys
on lives on the cross-encoder score scale; with `MAGPIE_RERANK` off, `score` holds RRF-fusion
values on a `~1/60` scale (`search.py:919-920` says so in a comment), and `solo_margin` is pinned
to `0` anyway. `gate_to_solo` cannot fire.

`metrics.json` nevertheless publishes `solo_gate.fire_rate: 0.05`. Read `enrich.py:369-373`:

```python
post_gate = row.get("retrieved") or []
out["solo_gated"] = (
    params.get("provider") == "local"
    and len(post_gate) == 1
    and len(ranked_paths) >= 2
)
```

**This is an inference, not an observation.** It has no access to the gate. It flags any row where
the answer pass returned exactly one file while the 12-deep sweep returned two or more. 6 of 120
rows match → 0.05.

The self-validation at `enrich.py:379-386` (`gate_inference_disagreement`) is vacuous here: it
compares the observed rank-1-minus-rank-2 margin against `params["solo_margin"]`. The observed
margin is `1/61 − 1/62 = 0.00026`, which rounds to `0.0`, and the threshold is also `0.0`, so
`0.0 < 0.0` is `False` on all six and the check reports agreement it did not earn.

**What actually happened on those six rows — fast-tier page collapse at small `fetch_k`:**

With `rerank=False`, `search.py:836` sets `fetch_k = top_k = 2`, and `search.py:850` asks the fast
tier for `fetch_k * 2 = 4` **pages**. `_search_fast_tier` (`search.py:516-560`) then collapses
those page hits to **one result per file, best page wins**. When a multipage PDF owns several of
those 4 page slots, the deduped file list is shorter than `top_k`. All six rows are exactly that:

| row | single file returned | pages in that file | gold | recall@1 | verdict |
|---|---|---:|---|---:|---|
| `arch-04-typed` | `scan_mtnh0227.pdf` | 5 | same file | 1.00 | partial |
| `arch-04-full` | `scan_mtnh0227.pdf` | 5 | same file | 1.00 | partial |
| `arch-06-typed` | `scan_gzyh0227.pdf` | 9 | same file | 1.00 | wrong |
| `study-03-typed` | `deck_022.pdf` | 7 | same file | 1.00 | false_abstain |
| `study-08-typed` | `deck_027.pdf` | 6 | same file | 1.00 | false_abstain |
| `study-08-full` | `deck_027.pdf` | 6 | same file | 1.00 | wrong |

Every one is a multipage PDF; 47 of 520 indexed files are multipage. The sweep, running at
`fetch_k=12` (24 pages requested), returns a full 12 files for all six.

**Plainly stated: zero gating occurred in this run.** The 5% "fire rate" is six instances of a
different product behaviour — page-collapse starving the retrieval slate below `top_k` — wearing
the gate's name. Two consequences:

1. The `in_prompt` labels `"solo_excluded"` on those rows (`doc_14760.jpg`, `bad_receipt_012.jpg`,
   `doc_14759.jpg`, `info_038.jpg`, `scan_yjgx0227.pdf`, `deck_030.pdf`) are also wrong. Nothing
   excluded them; the answer pass's own 4-page candidate pool never surfaced them.
2. **Retrieval cost of the collapse: zero.** All six are single-gold rows whose gold is the
   surviving file at rank 1. It cost the generator its second context file, which is an answers-side
   concern, not a recall one.

`metrics.json` should not publish a `solo_gate` block on a run stamped
`solo_gate_structurally_off: true`; at minimum it should be renamed to something like
`slate_collapsed_to_one`.

---

## 5. Typed vs full, paired by `pair_id` — retrieval only

52 pairs have retrieval metrics on both phrasings. **48 of 52 (92.3%) are metric-identical on the
sweep basis.** Four differ:

| pair | typed (r@1 / r@5 / r@12 / nDCG@5) | full (r@1 / r@5 / r@12 / nDCG@5) | real? |
|---|---|---|---|
| `rcpt-05` | 0.000 / 1.000 / 1.000 / 0.387 | **1.000 / 1.000 / 1.000 / 1.000** | **yes** — §2.1 |
| `rcpt-08` | 0.333 / 0.333 / 0.333 / 0.469 | 0.333 / **0.667** / **1.000** / **0.765** | **yes** — §2.2 |
| `study-02` | 0.250 / 0.750 / 1.000 / 0.823 | 0.250 / 0.750 / 1.000 / **0.811** | no — acceptable-source tie order, typed marginally *better* |
| `viz-11` | 0.111 / 0.556 / 1.000 / 0.856 | 0.111 / 0.556 / 1.000 / **0.747** | no — 9-way identical-file lottery, typed *better* by luck |

On the end-to-end basis only **two** pairs diverge at all — `rcpt-05` (typed 0.00 vs full 1.00) and
`rcpt-08` (typed 0.33 vs full 1.00). Everything else the generator saw was phrasing-invariant.

Aggregates, honest denominator (n = 49 each):

| | typed | full | gap |
|---|---:|---:|---:|
| hit@1 | 0.9796 | **1.0000** | −0.0204 |
| hit@5 | 1.0000 | 1.0000 | 0 |
| recall@5 | 0.9722 | 0.9790 | −0.0068 |
| recall@12 | 0.9864 | **1.0000** | −0.0136 |
| MRR | 0.9837 | 1.0000 | −0.0163 |
| nDCG@5 | 0.9688 | 0.9849 | −0.0161 |

**Verdict: the typed-vs-full retrieval gap is real but tiny, and it is two questions wide.**
`rcpt-05-typed` costs the entire `hit@1` and `MRR` gap; `rcpt-08-typed` costs the entire
`recall@12` gap. There is no systematic degradation from terse phrasing on this corpus. Both
failing typed queries share a signature: the query's only concrete nouns name a *scene* ("shop") or
a phonetically-mangled brand ("mr diy") with no document-type anchor, which is precisely where a
page-image encoder with no lexical partner goes wrong.

One structural asymmetry worth recording: the `list_all` classifier fires on **7 full** phrasings
versus **3 typed** (§1, item 2). Full phrasings therefore get a 12-file slate where their typed
twins get 2. That helps `rcpt-01-full`, `arch-06-full`, `study-03-full`, `phone-11-full` and
`nf-06-full` end-to-end without any ranking difference, and is worth separating from ranking
quality in any downstream comparison.

---

## 6. `extract_rare_tokens` — the only keyword source, and it is silent

With `rewrite=false`, `worker.py` uses `raw_query()` (`search.py:1013`), which makes no LLM call
and fills `keywords` from `extract_rare_tokens()` unless `MAGPIE_RARE_TOKENS=0`. The regex
(`search.py:975-983`) matches camelCase, PascalCase-with-internal-capital, snake_case,
`filename.ext`, and `[A-Za-z]+\d+`.

I ran it over all 120 golden questions (in-repo `.venv`, `src.stage2.search.extract_rare_tokens`).
Recomputed output matches the logged `search_query.keywords` on all 120 rows, and
`search_query.rewritten` is `False` on all 120 — the config did what it said.

| phrasing | questions yielding ≥1 token | rate |
|---|---:|---:|
| **typed** | **0 / 60** | **0.000** |
| **full** | 7 / 60 | 0.117 |
| pooled | 7 / 120 | 0.058 |

Token-count distribution: 113 questions produce 0 tokens, 6 produce 1, 1 produces 2. Every
non-empty result, in full:

| qa_id | tokens | why it matched |
|---|---|---|
| `arch-06-full` | `pH` | lowercase-then-uppercase |
| `study-03-full` | `kW` | lowercase-then-uppercase |
| `study-06-full` | `arXiv` | lowercase-then-uppercase |
| `study-09-full` | `arXiv` | lowercase-then-uppercase |
| `rcpt-02-full` | `McDonald`, `ChicMcMuffins` | PascalCase with internal capital |
| `rcpt-03-full` | `RedVelvet` | PascalCase with internal capital |
| `rcpt-08-full` | `D.I` | `filename.ext` rule mis-firing on "Mr D.I.Y." |

**Three findings.**

1. **On typed phrasings the feature is completely inert — 0/60.** The typed style is all-lowercase
   natural shorthand ("how much did i spend at mr diy altogether"), which contains no
   identifier-shaped token by construction. The docstring's motivating example (`GetIndentation` on
   a C# corpus) does not exist in a corpus of charts, receipts and photos. This corpus has no
   identifiers.
2. **The seven hits it does produce are near-worthless, and one is a bug.** `pH`, `kW` and `arXiv`
   are units and a site name, not discriminating identifiers. `D.I` is the `\w+\.[A-Za-z]{1,5}\b`
   filename rule chewing the middle out of "Mr D.I.Y." and emitting a fragment that matches nothing;
   the useful token would have been the full brand string. Only `McDonald`/`ChicMcMuffins` and
   `RedVelvet` are genuinely discriminating, and neither pair shows any retrieval difference between
   phrasings (`rcpt-02` and `rcpt-03` are both in the 48 metric-identical pairs).
3. **Even a good token could not have helped, because the tier it was designed for did not run.**
   `raw/qdrant/collections/` contains **exactly one collection: `fast_tier`**. There is no summaries
   collection, so `_search_summary_tier` (`search.py:370-372`) returns `[]` on its
   `collection_exists` guard on every query — confirmed by all 1,437 sweep hits carrying
   `tier: "fast"` and by all 520 manifest entries having `summary_file: null` /
   `summarized_at: ""`. The prior run's `worker_index_result.json` records it directly:
   `"summary_tier_note": "no supported files found under .../corpus"` — all 545 files are
   images/PDFs, so nothing routes to the text tier.

   The whole point of `extract_rare_tokens` is `search.py:398-405`: keywords get **their own sparse
   (BM25) prefetch**, so one rare token is not drowned by eight common ones. That code path never
   executed. The only place keywords entered this run is `search.py:851`,
   `query_text = sq.query + " " + " ".join(sq.keywords)` — the tokens were appended to the string
   fed to ColQwen's image-text encoder, where "pH" is just two more characters.

**Conclusion: on a 100%-visual corpus, `extract_rare_tokens` is a no-op with a 5.8% false-activity
rate.** It is not harmful here, but it must not be credited with anything, and `rewrite=false` on
this dataset means *genuinely no query processing at all*.

---

## 7. What to fix, in order of measured cost

1. **The index drops files silently** (`REPORT-indexing.md` owns the fix). It costs 6 of 104 scored
   rows — 5.8% of the eval — and is the single largest term in every published retrieval number. A
   run cannot report `hit@5` honestly while the index is missing gold.
2. **`top_k=2` is below the corpus's `n_rel`** on 24 rows, and below the *returned* slate on 8. It
   costs 0.0518 recall@12 and 0.0218 nDCG@5 between the two bases with zero ranking involvement.
   Any k-sweep should read the `retrieval` block, never `retrieval_end_to_end`.
3. **Page-collapse starves the slate below `top_k`** on multipage PDFs (§4). `_search_fast_tier`
   dedups to one result per file *after* the `fetch_k*2` page limit, so the file count is not
   guaranteed. It should over-fetch pages until it has `top_k` distinct files, or `fetch_k` should
   not equal `top_k` when rerank is off.
4. **`metrics.json` publishes a `solo_gate` block on a run where the gate is structurally off.**
   Rename the inferred field, or suppress it when `run.json.solo_gate_structurally_off` is true.
5. **Dataset hygiene before any further diagram/notes measurement**: `diagrams/` is 40 files and 9
   unique images; `viz-11`'s gold has 8 byte-identical twins. Deduplicate, or grade tie groups
   uniformly, or exclude them — otherwise nDCG@5 will keep moving between identical runs.
6. **ColQwen alone has no lexical partner on this corpus.** §2.1 and §2.2 are both cases where one
   BM25 term ("total", "D.I.Y.") would have settled the ranking. On an all-image corpus the summary
   tier no-ops entirely, which means visual-tier evals are single-channel by construction. That is
   worth knowing before drawing any conclusion about hybrid search from this dataset.

---

### Appendix — reproduction

All figures above are recomputed from run artefacts, not copied from `metrics.json`: short passes
over `answers_enriched.json`, `raw/retrieve.jsonl`, `raw/appdata/manifest.json`,
`datasets/custom_dataset_rahul_Aug30/qrels.tsv` and `golden.json`, plus `sha256` over
`corpus/diagrams/` and one `.venv` call into `src.stage2.search.extract_rare_tokens`. Nothing under
`src/` was modified.
