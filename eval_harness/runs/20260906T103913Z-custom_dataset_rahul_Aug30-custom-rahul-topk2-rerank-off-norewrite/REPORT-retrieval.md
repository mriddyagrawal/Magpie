# REPORT — RETRIEVAL

Run: `20260906T103913Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
Baseline: `20260906T090247Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
Dataset: `custom_dataset_rahul_Aug30`, 545 files on disk (100% images/PDFs), golden 120 items / 60 pairs, `golden_sha 0ebcdcbcdf109adb`
Index: MOUNTED, key `66974090bdcd62e6`, built 2026-08-30 under backend `cca67570`. `hit: true` on both arms — **the same bytes on disk served both runs.**
Config: `top_k=2`, `top_k_retrieval_max=12`, `rerank=false`, `rewrite=false`, `solo_margin=0`, `fast_search=true`, `enumerate_lists=true`, ColQwen2.5-v0.2 on MPS.
Axis under test: backend `92f9ba9 -> 4ce90a8` (branch `prompt-image-order`). Provenance fingerprint `2bd85ac1c6a9fd99` on both arms; only `backend_git_sha` differs.
Scope: retrieval ranking only. Generation, citation and verdict causes belong to the answers/judge reports.
Sources: `raw/retrieve.jsonl` (primary), `raw/answers.jsonl`, `answers_enriched.json`, `raw/appdata/manifest.json`, `raw/appdata/logs/llm-2026-09-06T10-39-33Z.log` (the one named in `run.json phases.answer.llm_log`; the co-resident `llm-2026-08-30T10-40-06Z.log` rode in with the mounted index and was not read), `datasets/custom_dataset_rahul_Aug30/{golden.json,qrels.tsv,corpus/}`.

The baseline's committed `REPORT-retrieval.md` is a complete forensic account of this configuration. This report does not restate it. It **verifies** its load-bearing claims against this run's own artefacts, **corrects three errors in the premise handed to me**, and adds findings the baseline did not have.

---

## 0. Headline

**Retrieval did not move. Not "almost". At the level that matters — what content reached the ranker's output and the generator's prompt — it is identical on 120 of 120 rows, on both the sweep basis and the end-to-end basis.**

I hashed all 545 corpus files (MD5) and re-expressed every ranked list as a sequence of *content hashes* rather than filenames. On that basis:

| comparison | rows differing by **filename** | rows differing by **content** |
|---|---:|---:|
| sweep (`raw/retrieve.jsonl`, 12 deep) | 5 / 120 | **0 / 120** |
| answer pass (`raw/answers.jsonl`, what fed the generator) | 2 / 120 | **0 / 120** |
| within-run: sweep top-1 vs answer-pass top-1, this arm | 2 / 120 | **0 / 120** |
| within-run: same, baseline arm | 2 / 120 | **0 / 120** |

Every filename-level difference is a permutation *inside a group of byte-identical duplicate files*. Zero bits of retrieval information changed between the arms.

The consequence for the code axis: across 104 scored rows x 2 metric bases x 11 metrics — **2,288 per-row numbers — exactly one moved.** `viz-11-typed` sweep `ndcg@5`, 0.855811 -> 0.844712. That single row drags the published aggregate `ndcg@5` by −0.000107. Everything else is bit-identical, including the entire `retrieval_end_to_end` block.

Meanwhile 57 of 120 verdicts flipped. **None of them can be caused by retrieval**, because retrieval handed both arms the same pixels. The whole flip surface is answer-side. §8 closes the one row where a retrieval cause was still on the table.

---

## 1. LOUD: three errors in the premise I was given

I was asked to confirm or refute the byte-identical claim myself and to say so loudly if I found rows that were missed. I did.

### 1.1 The sweep differs on **five** rows, not two

`raw/retrieve.jsonl` differs (ignoring `latency_s`) on:

| row | what differs | rank positions | files involved | in a duplicate group? |
|---|---|---|---|---|
| `viz-11-typed` | whole 12-list reshuffled, **set membership too** | 1-12 | `diagram_003…011` (x9 group) + `diagram_022…027` (x6 group) | yes, both |
| `viz-11-full` | whole 12-list reshuffled, **set membership too** | 1-12 | same two groups | yes, both |
| `arch-01-full` | 3-cycle | 5, 6, 7 | `diagram_019/020/021` | yes (x3 group) |
| `arch-05-full` | swap | 5, 6 | `diagram_001/002` | yes (x2 group) |
| `study-08-typed` | swap | 10, 11 | `diagram_001/002` | yes (x2 group) |

`arch-01-full`, `arch-05-full` and `study-08-typed` were not in the premise. They are metric-inert (deep ranks, identical sets, no gold involved), which is presumably why the deterministic differ missed them — but they matter as **evidence**: the tie-break shuffle is not a `viz-11` peculiarity, it fires anywhere a duplicate group lands in the retrieved window.

### 1.2 `viz-11` is not "`diagram_006` and `diagram_011` swapping ranks 1 and 2"

That description conflates the two retrieval passes. What actually happened:

| pass | this run, top-2 | baseline, top-2 |
|---|---|---|
| sweep, `viz-11-typed` | `diagram_008`, `diagram_011` | `diagram_004`, `diagram_011` |
| sweep, `viz-11-full` | `diagram_011`, `diagram_009` | `diagram_007`, `diagram_011` |
| **answer pass**, `viz-11-typed` | `diagram_006`, `diagram_011` | `diagram_011`, `diagram_006` |
| **answer pass**, `viz-11-full` | `diagram_006`, `diagram_011` | `diagram_011`, `diagram_006` |

The `006`/`011` rank-1<->2 swap is in the **answer pass**, not the sweep. In the sweep the entire twelve-file list is reshuffled and the *tail membership changes* (`diagram_024`/`022` appear where the baseline had `025`/`027`). Two different phenomena were fused into one sentence.

### 1.3 There is no "identical score" — the score column carries no information at all

All 1,437 sweep hits and all 334 answer-pass hits carry `tier: "fast"`, and **every score is exactly `1/(60 + rank)`** (verified: 1437/1437 match). Only one list voted, so RRF is a no-op and `score` is a pure positional constant re-derived from rank. Two files can never "tie on score" and can never be "separated by score" — the number is written *after* the ordering is decided, by `_rrf_merge` (`src/stage2/search.py:640-642`).

So "swap ranks 1 and 2 at identical scores 0.016393 / 0.016129" is doubly wrong: those are two *different* constants (1/61 and 1/62), they belong to rank slots not to files, and the real similarity scores — the ColQwen MaxSim values that actually decided the order — are overwritten before they reach any artefact. **The evidence for a tie in `viz-11` is the file hashes, not the score column.** See §8.

---

## 2. The published numbers, and the honest ones

| | this run | baseline | delta |
|---|---:|---:|---:|
| rows scored | 104 / 120 | 104 / 120 | 0 |
| `retrieval` hit@1 | 0.932692 | 0.932692 | 0 |
| `retrieval` hit@3 | 0.932692 | 0.932692 | 0 |
| `retrieval` hit@5 | 0.942308 | 0.942308 | 0 |
| `retrieval` hit@12 | 0.942308 | 0.942308 | 0 |
| `retrieval` recall@1 | 0.808226 | 0.808226 | 0 |
| `retrieval` recall@3 | 0.894231 | 0.894231 | 0 |
| `retrieval` recall@5 | 0.919338 | 0.919338 | 0 |
| `retrieval` recall@12 | 0.935897 | 0.935897 | 0 |
| `retrieval` MRR | 0.934615 | 0.934615 | 0 |
| `retrieval` nDCG@5 | 0.920369 | 0.920476 | **−0.000107** |
| `retrieval` first_gold_rank | 1.040816 | 1.040816 | 0 |
| `retrieval_end_to_end` (all 11 metrics) | — | — | **0 on every one** |

`first_gold_rank` is a mean over the rows where a gold was found: 98 rows on the sweep basis (97 at rank 1, `rcpt-05-typed` at rank 5 -> 102/98 = 1.0408), 97 rows end-to-end (`rcpt-05-typed`'s gold at rank 5 is cut by `top_k=2`, so it drops out of the mean entirely and the remaining 97 are all rank 1 -> exactly 1.0000). **A `first_gold_rank` that *improves* from 1.041 to 1.000 when you truncate the list is an artefact of the denominator shrinking, not of better ranking.** Do not read that cell as a win.

**Honest denominator** (drop the 6 rows whose gold was never written to the index — §4.1; n = 104 -> 98). Identical in both arms:

| | sweep | end-to-end |
|---|---:|---:|
| hit@1 | **0.9898** | 0.9898 |
| hit@5 | **1.0000** | 0.9898 |
| hit@12 | 1.0000 | 0.9898 |
| recall@1 | 0.8577 | 0.8577 |
| recall@5 | 0.9756 | 0.9348 |
| recall@12 | 0.9932 | 0.9382 |
| MRR | 0.9918 | 0.9898 |
| nDCG@5 | 0.9767 | 0.9537 |

On every scored question whose gold is actually in the index, ColQwen put a gold file in the top 5. `hit@5 = 1.000`, 98/98.

---

## 3. `retrieval` vs `retrieval_end_to_end`, and what `retrieval_divergence` actually reports

`retrieval` is computed over `raw/retrieve.jsonl -> ranked`: a **second** search pass at `top_k = top_k_retrieval_max = 12`, with the query replayed verbatim from the answer pass (`query_source: "replayed_from_answer_pass"`). `retrieval_end_to_end` is computed over what `ask()` handed the generator after `top_k` truncation. `enrich.py:331-341`.

`retrieval_divergence` compares those two *within one run*. It is not a cross-arm statistic.

- **`n_query_differs: 0`.** `search_query` is byte-identical on 120/120 between the sweep and the answer pass — and, separately, byte-identical on 120/120 **between the two arms**: same `final_query`, same `keywords`, `rewritten: false` everywhere, and `final_query == question` verbatim on all 120 rows. **This is the proof that commit `4ce90a8`'s rewriter clock-line removal is inert in this arm.** With rewrite off, `worker.py` calls `raw_query()` (`search.py:1013`), which makes no LLM call at all — there is no clock, no rewrite, nothing for the commit to touch. Any behaviour change in this run originates strictly downstream of retrieval.

- **`n_top1_differs: 2`.** Both rows are `viz-11-typed` and `viz-11-full` (`retrieval_top1_matched: false`). Cause: with `rerank=False`, `search.py:836` sets `fetch_k = top_k`, so the answer pass asks ColQwen for `2 x 2 = 4` page candidates while the sweep asks for `12 x 2 = 24`. Different pool depths break ties differently — and `viz-11`'s entire candidate neighbourhood is nine copies of one file. **On a content-hash basis the divergence is zero: the sweep top-1 and the answer-pass top-1 are the same image in both rows, in both arms.** The divergence counter is measuring filename lottery, not disagreement about content.

Four mechanisms separate the two bases; all are unchanged from the baseline:

1. **`top_k=2` truncation (dominant).** 89 of 104 scored rows carry exactly 2 files end-to-end. `hit@12` on the e2e basis is a misnomer for `hit@2`. Accounts for the whole recall@12 gap (0.9359 -> 0.8841).
2. **`enumerate_lists` widening.** 10 rows classified `list_all` widened `top_k 2->12` (9 of them scored). Phrasing-asymmetric: 7 full, 3 typed.
3. **Fast-tier page-collapse.** 6 rows returned exactly one file — see §7.
4. **Tie-order instability.** The `viz-11` pair, above.

---

## 4. Where ranking went wrong, and the ceiling the answer stage is working under

### 4.1 `hit@1 = .933` but `recall@1 = .808` — where the 12.5 points go

They are different questions. `hit@1` asks *did any relevant file land at rank 1*; `recall@1` asks *what fraction of the relevant set landed at rank 1*. When a question has `n_rel` relevant files, `recall@1` is arithmetically capped at `1/n_rel`.

`qrels.tsv` grades 152 pairs over 120 questions. Relevant-set sizes over the 104 scored rows:

| `n_rel` | rows |
|---:|---:|
| 1 | 80 |
| 2 | 14 |
| 3 | 6 |
| 4 | 2 |
| 9 | 2 (`viz-11-typed/full`) |

Note this is **not** the same as `gold_sources` length: `recall` is scored against gold (`rel=2`) **plus** `acceptable_sources` (`rel=1`). `viz-11` has one gold and eight acceptables, so its `recall@1` ceiling is 0.111.

Structural ceilings, computed as `mean(min(k, n_rel) / n_rel)` over the 104 scored rows:

| k | ceiling | observed | true shortfall |
|---:|---:|---:|---:|
| 1 | 0.8627 | 0.8082 | **0.0545** |
| 3 | 0.9824 | 0.8942 | 0.0881 |
| 5 | 0.9915 | 0.9193 | 0.0721 |
| 12 | 1.0000 | 0.9359 | 0.0641 |

So the real `recall@1` deficit is 5.5 points, not the 19.2 the raw number implies. 24 of 104 rows cannot reach `recall@1 = 1` no matter how good the ranker is.

The end-to-end basis has its own ceiling, since the slate length varies per row (89 rows x 2 files, 9 x 12, 6 x 1). `mean(min(slate_len, n_rel)/n_rel) = 0.9626` against an observed `0.8841`.

**Rows below their own end-to-end ceiling — 12, and only 12:**

| row | `n_rel` | slate | relevant delivered | missing |
|---|---:|---:|---:|---|
| `rcpt-05-typed` | 1 | 2 | 0 | `bad_receipt_014.jpg` |
| `rcpt-07-typed` / `-full` | 1 | 2 | 0 | `receipt_040.jpg` (not indexed) |
| `study-05-typed` / `-full` | 1 | 2 | 0 | `electric-charge-and-field-9.pdf` (not indexed) |
| `study-10-typed` / `-full` | 3 | 2 | 0 | `CseGyan-Cpp-Notes-17/18/19.pdf` (none indexed) |
| `rcpt-08-typed` | 3 | 12 | 1 | `bad_receipt_004.jpg`, `bad_receipt_027.jpg` |
| `study-02-typed` / `-full` | 4 | 2 | 1 | 3 acceptables cut by `top_k` |
| `study-04-typed` / `-full` | 3 | 2 | 1 | 2 acceptables cut by `top_k` |

Four of those twelve are pure `top_k=2` truncation of *acceptable* sources with gold at rank 1 (`study-02`, `study-04`) — not ranking failures. Six are index-drop casualties. **The entire genuine ranking failure surface with indexed gold is two rows: `rcpt-05-typed` (gold at rank 5, cut at k=2) and `rcpt-08-typed` (2 of 3 golds outside the 12-deep sweep).**

### 4.2 The answer stage's hard ceiling — unanswerable by construction

**7 of 104 scored rows reached the generator with zero relevant files in the prompt.** These are unanswerable no matter what the prompt-assembly change does:

| row | why | this-arm verdict |
|---|---|---|
| `rcpt-07-typed` / `-full` | gold `receipt_040.jpg` is not in the index | wrong / false_abstain |
| `study-05-typed` / `-full` | gold `electric-charge-and-field-9.pdf` is not in the index | wrong / false_abstain |
| `study-10-typed` / `-full` | all three golds (`Notes-17/18/19`) not in the index | wrong / false_abstain |
| `rcpt-05-typed` | genuine rank failure: gold at rank 5, `top_k=2` | wrong |

Six of those seven owe to the index, not the ranker: `raw/appdata/manifest.json` holds **520 entries against 545 files on disk**, and the 25 missing files (14 `notes_handwritten`, 9 `receipts_phone`, 2 `scans_multipage`) include the gold of three golden pairs. I re-verified the manifest independently in this run: identical 520 entries, identical 25-file miss list, identical folder split. Root cause is owned by `REPORT-indexing.md` (all-NaN fp16 ColQwen embeddings rejected at upsert; one file over Qdrant's 32 MiB cap). On every one of those six rows the ranker returned adjacent pages of the correct source document — right notebook, wrong (surviving) page.

A further **2 rows** (`viz-11-typed`, `viz-11-full`) received *no grade-2 gold* but did receive two grade-1 acceptables — which happen to be byte-identical copies of the gold (§8). They are answerable in fact and unanswerable on paper.

**Bottom line for the answers report: 7 of 120 questions (5.8%) had a zero-information prompt before the generator saw a token, and 6 of those 7 are an indexing defect, not a retrieval one.** Any answer-side accuracy claim should quote 113 as its ceiling denominator, not 120.

`ndcg@5` on the e2e basis (0.8987) is 0.0218 below the sweep (0.9205) with zero ranking involvement — pure `top_k=2` window loss on `study-02`, `study-04` and `viz-11`.

### 4.3 A note on rank order: rank 1 is presented **last**

Not previously recorded in this run family, and it changes how "top-1" should be read downstream. `src/answer.py:644`:

```python
ordered_blocks = list(reversed(per_file_blocks))
```

The prompt deliberately reverses retrieval order so the highest-ranked file sits closest to generation (the comment cites Liu et al. 2023 "Lost in the Middle" on recency bias in small decoder-only models). I verified it against the llm logs: on **114 of 120 rows in both arms** the `--- File N: ---` header order in the prompt is the exact reverse of `answers.jsonl -> retrieved`. The 6 that "match" are the single-file rows of §7.

Two consequences: (a) "the file at rank 1" is `--- File 2 ---` in a 2-file prompt, so any answers-side reasoning about file position must invert; (b) this is identical in both arms, so it is not a confound for the code axis — but it is part of why the `viz-11` swap has no effect (§8).

---

## 5. The phrasing gap — it is two questions wide, and the mechanism is a regex

`by_phrasing` publishes typed `hit@1 .9231` / `recall@5 .9161` vs full `.9423` / `.9225`. Both arms identical.

Paired by `pair_id` over the 52 scored pairs: **48 of 52 (92.3%) are metric-identical on the sweep basis.** Four differ, and only two are real:

| pair | typed r@1 / r@5 / r@12 / nDCG@5 | full r@1 / r@5 / r@12 / nDCG@5 | real? |
|---|---|---|---|
| `rcpt-05` | 0.000 / 1.000 / 1.000 / 0.387 | **1.000** / 1.000 / 1.000 / **1.000** | **yes** |
| `rcpt-08` | 0.333 / 0.333 / 0.333 / 0.469 | 0.333 / **0.667** / **1.000** / **0.765** | **yes** |
| `study-02` | 0.250 / 0.750 / 1.000 / **0.823** | 0.250 / 0.750 / 1.000 / 0.811 | no — typed marginally *better*, acceptable-source tie order |
| `viz-11` | 0.111 / 0.556 / 1.000 / **0.845** | 0.111 / 0.556 / 1.000 / 0.747 | no — 9-way identical-file lottery, typed *better* by luck |

**The entire published `hit@1` gap (.923 vs .942) is one question: `rcpt-05-typed`. The entire `recall@12` gap is one question: `rcpt-08-typed`.** There is no systematic degradation from terse phrasing on this corpus.

Which typed queries fail that their full pair-mates get right, and what breaks:

**`rcpt-05`** — gold `bad_receipt_014.jpg`.
- typed: `"that shop where i bought loads of chocolate bars total"` -> top-5 `scene_887bfd79f29a3fcb.jpg`, `110671448.jpg`, `info_008.jpg`, `receipt_024.jpg`, **`bad_receipt_014.jpg`** (rank 5, cut at k=2 -> prompt gets zero relevant files, verdict `wrong` in both arms).
- full: `"Which shop was it where I bought a whole pile of Delicia chocolate bars, and what did that shop come to?"` -> `bad_receipt_014.jpg` at rank 1.
- What broke: the typed phrasing's only concrete nouns are **"shop"** and **"chocolate bars"** — a *scene* description. ColQwen is a page-image encoder; "shop" is a strong visual match for a shopfront photo, which is exactly what rank 1 is. The full phrasing adds the single token **`Delicia`**, the brand printed on the receipt, and that one word moves the correct receipt from rank 5 to rank 1. Terse phrasing here does not fail because it is short; it fails because the user dropped the one proper noun that appears in the image.

**`rcpt-08`** — golds `bad_receipt_002/004/027.jpg`.
- typed: `"how much did i spend at mr diy altogether"` -> 12-file slate but only `bad_receipt_002.jpg` relevant; ranks 2-12 are `screen_24454`, `screen_24403`, `info_002`, `bad_receipt_022`, `receipt_009`, … `recall@12 = 0.333`.
- full: `"Adding up all my Mr D.I.Y. receipts, how much did I spend there in total?"` -> `bad_receipt_002`, `bad_receipt_004`, `receipt_036`, `bad_receipt_000`, `bad_receipt_034`, … all three golds inside 12, `recall@12 = 1.000`.
- What broke: **`mr diy` vs `Mr D.I.Y.`**. The receipts print the punctuated logo. A visual-text encoder matching page pixels reads the dotted form; the flattened lowercase form is a different string. The word `receipts` in the full phrasing also anchors document type, where the typed form has none.

**The asymmetry has a measurable structural component.** With `rewrite=false`, the only query processing left is `extract_rare_tokens()`. Across all 120 rows exactly 7 produce a non-empty `keywords` list — **all 7 are `-full` phrasings; 0 of 60 typed phrasings produce a single token**:

`arch-06-full` `[pH]` · `study-03-full` `[kW]` · `study-06-full` `[arXiv]` · `study-09-full` `[arXiv]` · `rcpt-02-full` `[McDonald, ChicMcMuffins]` · `rcpt-03-full` `[RedVelvet]` · `rcpt-08-full` `[D.I]`

The regex keys on CamelCase, PascalCase, snake_case, `filename.ext` and digit-glued tokens. All-lowercase natural shorthand cannot trip it by construction. Two riders: (a) the tokens are near-worthless here — `pH`, `kW`, `arXiv` are units and a site name, and `D.I` is the `filename.ext` rule chewing the middle out of "Mr D.I.Y." and emitting a fragment; (b) the sparse/BM25 prefetch these keywords were designed for **never ran** — `raw/qdrant/collections/` contains exactly one collection, `fast_tier`, so `_search_summary_tier` returns `[]` on every query (confirmed: 1,437/1,437 sweep hits carry `tier: "fast"`). Keywords entered this run only by string concatenation into the ColQwen query text (`search.py:851`). So the 0/60-vs-7/60 asymmetry is *not* what made full win `rcpt-05` — `Delicia` produced no keyword either. Full wins on plain query-text content.

Second structural asymmetry: the `list_all` classifier fires on **7 full** phrasings vs **3 typed**, so full phrasings get a 12-file slate where their typed twins get 2. That is an output-budget advantage, not a ranking one, and must be separated from ranking quality in any downstream comparison.

---

## 6. `notes_iam` distractor pressure — negligible, and sub-proportional

The 30 IAM/LOB handwriting strips are indexed as realistic distractors and carry zero golden items, so any hit is a false positive by construction. Measured on this run (identical to baseline, as retrieval is content-identical):

| | count | share |
|---|---:|---:|
| `notes_iam` files in the index | 30 / 520 | 5.8% |
| slots won in the 12-deep sweep, all 120 rows | **10 / 1,437** | **0.7%** |
| distinct `notes_iam` files ever retrieved | **8 / 30** | 27% |
| rows with >=1 `notes_iam` file in the sweep top-12 | 10 / 120 | 8.3% |
| rows with a `notes_iam` file at sweep rank 1 | **1** | 0.8% |
| slots won end-to-end (in the prompt) | **1 / 334** | **0.3%** |
| slots won end-to-end on the 104 **scored** rows | **0** | **0.0%** |

Every appearance, with its rank:

| row | rank | question | category |
|---|---:|---|---|
| `nf-05-typed` | **1** | `"transcript"` | not_found |
| `viz-10-typed` | 4 | `"leaf diagram cordate obcordate what ob means"` | diagrams |
| `nf-06-typed` | 5 | `"training loss curve"` | not_found |
| `viz-07-full` | 7 | condoms infographic | infographics |
| `study-04-typed` | 8 | cpp notes ternary operator | notes_handwritten |
| `study-06-typed` | 8 | train/validation/test figure | figures |
| `viz-10-full` | 8 | leaf shape diagram | diagrams |
| `viz-05-typed` | 9 | armed forces share chart | charts |
| `study-04-full` | 10 | cpp notes ternary operator | notes_handwritten |
| `study-10-typed` | 12 | cpp notes type casting | notes_handwritten |

**What this says about ColQwen on handwriting strips: it suppresses them roughly 8x below chance** (5.8% of the index, 0.7% of retrieved slots), and only 8 of the 30 files ever surface at all. Handwriting strips are not a generic attractor — the encoder discriminates "page of cursive English on ruled paper" from charts, receipts, screenshots and figures reliably.

The one rank-1 hit is the informative case. `nf-05-typed`'s entire query is the bare word **`"transcript"`**, and a handwriting transcription strip is a defensible visual match for it — the failure mode is not "handwriting attracts everything", it is "a one-word query with no document-type anchor lets the literal reading of the word win". Three of the remaining nine (ranks 8, 10, 12) are the `notes_handwritten` C++ questions, where confusing one handwriting corpus with another is the *expected* near-miss.

Cost to the run: zero. `nf-05-typed` is the only row where a `notes_iam` file reached the generator, it is a not-found probe, and the verdict is `correct_abstain` in both arms. On the 104 scored rows this slice occupied no prompt slot at all.

---

## 7. The gate: `solo_gate.fire_rate = 0.05` on a run stamped `solo_gate_structurally_off: true`

Both statements are true and they do not contradict. `gate_to_solo` (`search.py:895`) returns early at `if not _rerank_enabled(): return retrieved` — with `MAGPIE_RERANK=0` it cannot execute a single line of gating logic, and `LOCAL_SOLO_MARGIN` is pinned to `0` which would disable it a second time. **Zero gating occurred.**

What produced the 0.05 is `enrich.py:369-373`, a **post-hoc inference** with no access to the gate:

```python
post_gate = row.get("retrieved") or []
out["solo_gated"] = (
    params.get("provider") == "local"
    and len(post_gate) == 1
    and len(ranked_paths) >= 2
)
```

It flags any row where the answer pass returned exactly one file while the 12-deep sweep returned two or more. Six of 120 rows match -> 0.05. Those same six carry the `solo_excluded` labels in `in_prompt` (`enrich.py:425-430`, which back-fills the label for pre-gate files that "the gate excluded").

The six, and what actually happened:

| row | single file returned | pages in that PDF | rank-2 file mislabelled `solo_excluded` |
|---|---|---:|---|
| `arch-04-typed` | `scan_mtnh0227.pdf` | 5 | `doc_14760.jpg` |
| `arch-04-full` | `scan_mtnh0227.pdf` | 5 | `bad_receipt_012.jpg` |
| `arch-06-typed` | `scan_gzyh0227.pdf` | 9 | `doc_14759.jpg` |
| `study-03-typed` | `deck_022.pdf` | 7 | `info_038.jpg` |
| `study-08-typed` | `deck_027.pdf` | 6 | `scan_yjgx0227.pdf` |
| `study-08-full` | `deck_027.pdf` | 6 | `deck_030.pdf` |

**Every one is a multipage PDF, and the mechanism is fast-tier page-collapse at small `fetch_k`.** With `rerank=False`, `search.py:836` sets `fetch_k = top_k = 2`, `search.py:850` asks the fast tier for `fetch_k * 2 = 4` **pages**, and `_search_fast_tier` (`search.py:516-560`) then dedups those page hits to **one result per file, best page wins**. When a 5-to-9-page PDF owns all four page slots, the deduped file list is one file long. The sweep, running at `fetch_k=12` (24 pages), returns a full 12 files on all six rows.

The same defect is visible at the *sweep's* depth too, which the baseline did not note: `viz-08-typed` returned 11 files and `arch-08-full` returned 10, not 12 — both slates dominated by multipage PDFs (`deck_*.pdf`, `scan_*.pdf`). The collapse is not a `top_k=2` edge case; it scales with fetch depth.

**Is the `solo_excluded` classification meaningful here? No — it is actively misleading.** Nothing excluded those six files. The answer pass's own 4-page candidate pool never surfaced them. The harness's own self-check is vacuous on top of that: `gate_inference_disagreement` compares `solo_margin_observed` (= `1/61 − 1/62` = 0.00026, which `round(..., 3)` flattens to `0.0`) against `params["solo_margin"]` (= `0`), so `0.0 < 0.0` is `False` on all six and the check reports an agreement it did not earn.

Retrieval cost of the collapse: **zero**. All six are single-gold rows whose gold is the surviving rank-1 file (`recall@1 = 1.00` on all six). It cost the generator its second context file, which is an answers-side concern.

Recommendation stands from the baseline: suppress or rename the `solo_gate` block when `run.json.solo_gate_structurally_off` is true, and rename the `solo_excluded` label — `slate_collapsed_below_top_k` describes what happened.

---

## 8. `viz-11` — the clean prompt_assembly-vs-noise call

This is the only row where retrieval was a candidate cause. It is not the cause. Here is the chain, each link independently verified.

### 8.1 The tie is genuine and total — nine copies of one file

`md5` over `corpus/diagrams/`:

```
f15f998481495f00affa09c0312f9c92  diagram_003.jpg diagram_004.jpg diagram_005.jpg
                                  diagram_006.jpg diagram_007.jpg diagram_008.jpg
                                  diagram_009.jpg diagram_010.jpg diagram_011.jpg
```

Nine files, one hash, 69,350 bytes each, 576x396 each. `diagram_006.jpg` and `diagram_011.jpg` are **not near-duplicates and not "two copies of the same diagram" in a loose sense — they are the same file, twice.** I read both images: identical Antarctic marine food web, same nodes (`baleen whale`, `smaller toothed whales`, `leopard seal`, `elephant seal`, `other seals`, `penguins`, `birds`, `fish`, `krill`, `carnivorous zooplankton`, `other herbivorous zooplankton`, `phytoplankton`), same arrows, same pixels.

Identical bytes -> identical ColQwen page embeddings -> identical MaxSim against any query -> the relative order among them is decided entirely by Qdrant's traversal/tie-break, which is arbitrary and, as §1.1 shows, not stable across processes. **The rank swap carries zero information. It is not a ranking difference.**

This is not confined to `viz-11`. The whole corpus is 545 files but only **514 distinct content hashes** — 31 redundant copies, **all 31 of them in `diagrams/`**. That folder is 40 files comprising **9 unique images** (groups of 9, 8, 6, 5, 4, 3, 2, 2, plus the singleton `diagram_018.jpg`). Every diagram question is a lottery among identical files.

### 8.2 The prompt was pixel-identical in both arms

From the llm logs, `viz-11-full`:

- **this run** (`llm-2026-09-06T10-39-33Z.log`): `--- File 1: …/diagram_011.jpg ---` then `--- File 2: …/diagram_006.jpg ---`
- **baseline** (`llm-2026-09-06T09-03-12Z.log`): `--- File 1: …/diagram_006.jpg ---` then `--- File 2: …/diagram_011.jpg ---`

(Both are the *reverse* of `answers.jsonl -> retrieved`, per §4.3.) Both requests carry `extra: {"images": 2}`. Since the two files are byte-identical, **the generator received the same two images, in the same two positions, in both arms.** The only textual difference anywhere in the file zone is which of two filename strings appears in which header. Nothing about the evidence available to the model changed.

### 8.3 What *did* change — and it is entirely prompt assembly

The same two log records show the prompt-assembly change directly:

| | baseline (`92f9ba9`) | this run (`4ce90a8`) |
|---|---|---|
| user message shape | a single flat `str` | a **list of 5 typed content parts**: `text, image, text, image, text` |
| image delivery | out-of-band; the file headers sit adjacent with nothing between them | each `{"type":"image","data":"<69350 bytes>"}` sits **directly under its own `--- File N ---` header** |
| question copies | **2** (`"Current question: …"` at the top, `"Now answer this question: …"` at the end) | **1** (recency zone only) |
| clock line | `"Current date and time: …"` at the very top, above the files | `"Today: Sunday, 2026-09-06 06:44 EDT"` below the files, directly above the question |

### 8.4 Verdict

| row | baseline verdict | this-run verdict | baseline answer | this-run answer |
|---|---|---|---|---|
| `viz-11-typed` | `false_abstain` (`not_found: true`, empty answer) | **`correct`** 3/3 facts | `""` | `baleen whale, other seals, penguins, fish, krill, leopard seal, elephant seal, smaller toothed whales` |
| `viz-11-full` | `partial` 1/3 | **`correct`** 3/3 | `leopard seal and penguins` | `leopard seal, penguins, elephant seal, other seals` |

**Attribution: `prompt_assembly`. Unambiguously, and with no noise component.**

The retrieval swap cannot be the cause because it changed nothing the model could read — same two images, same two prompt positions, only the filename strings traded places. The baseline arm, holding the *same* two images, produced an empty abstention on the typed phrasing; this arm produced a complete, correct enumeration. The one thing that differs is that the images now sit inside typed content parts directly under their headers instead of being passed out-of-band behind headers with empty bodies. That is the commit under test.

Corroborating detail worth recording: the `sources_used` list the model emitted is **identical in both arms** (`diagram_011.jpg`, then `diagram_006.jpg`) even though the prompt order was reversed between them — itself evidence that the file order was not what the model was reacting to.

One caveat for the owner, stated plainly: `viz-11` is a *bad row to draw any conclusion from*, in either direction. Its `n_rel = 9` relevant set is nine copies of one image, its `ndcg@5` moves between provably identical runs, and its "gold" (`diagram_003`, `rel=2`) never reached either prompt — both arms answered from `rel=1` acceptables that happen to be the gold file under a different name. The verdict flip is real and prompt-caused; the *retrieval metrics* on this row should be discarded, not interpreted.

---

## 9. What is new in this pass, relative to the baseline's `REPORT-retrieval.md`

Confirmed and unchanged (verified independently, not copied): the 520/545 manifest and its exact 25-file miss list; the 6 index-drop rows and the honest denominator; the `n_rel` distribution and both recall ceilings; the RRF no-op and single-tier `fast` retrieval; the `notes_iam` slot counts; the page-collapse mechanism behind the six "gated" rows; the 48/52 phrasing-identical pairs and the `extract_rare_tokens` 0/60-typed result.

New or corrected here:

1. **Content-hash identity, not filename identity.** Retrieval is identical on **120/120** rows on both bases. The baseline compared filenames and inherited a "byte-identical on N rows" framing; hashing the corpus turns "mostly unchanged with one unstable item" into "provably zero information changed".
2. **Three additional cross-arm movers found** — `arch-01-full`, `arch-05-full`, `study-08-typed` (§1.1). All duplicate-group permutations, all metric-inert, all previously unreported.
3. **The `viz-11` premise corrected** (§1.2): the `006`/`011` rank-1<->2 swap is in the *answer pass*; the *sweep* reshuffles all 12 and changes tail membership.
4. **The "identical scores" framing refuted** (§1.3): `score` is `1/(60+rank)`, written after ordering. It can never evidence a tie.
5. **The prompt reverses retrieval order** (`answer.py:644`, verified on 114/120 rows in both arms) — §4.3. Not previously recorded, and necessary to read any downstream statement about file position.
6. **Page-collapse also bites at sweep depth** — `viz-08-typed` (11 files) and `arch-08-full` (10) returned short of `top_k_retrieval_max=12` (§7).
7. **Corpus-wide duplication quantified**: 545 files / 514 distinct hashes, all 31 redundant copies inside `diagrams/`, which is 40 files over 9 unique images (§8.1).
8. **The `viz-11` attribution closed** with direct log evidence (§8).

---

## 10. What to fix, in order of measured cost

Unchanged from the baseline in substance — this run supplies no new evidence to reorder it, and that is itself the finding.

1. **The index silently drops 25 files.** Costs 6 of 104 scored rows (5.8% of the eval) and is the single largest term in every published retrieval number. `REPORT-indexing.md` owns the fix.
2. **`top_k=2` is below `n_rel` on 24 rows and below the returned slate on 8.** Costs 0.0518 recall@12 and 0.0218 nDCG@5 between the bases with zero ranking involvement. K-sweeps must read the `retrieval` block, never `retrieval_end_to_end`.
3. **Page-collapse starves the slate below `top_k`.** `_search_fast_tier` dedups to one result per file *after* the `fetch_k*2` page limit, so the file count is not guaranteed at any depth. Over-fetch pages until `top_k` distinct files are held, or decouple `fetch_k` from `top_k` when rerank is off.
4. **Dataset hygiene before any further diagram measurement.** `diagrams/` is 40 files and 9 unique images. Deduplicate, or grade tie groups uniformly at `rel=2`, or exclude them — otherwise nDCG@5 will keep drifting between provably identical runs, and every future comparison will spend a paragraph explaining `viz-11`.
5. **`metrics.json` should not publish `solo_gate` on a run stamped `solo_gate_structurally_off: true`**, and `enrich.py` should not emit the `solo_excluded` label there.
6. **ColQwen has no lexical partner on this corpus.** `rcpt-05` and `rcpt-08` are both cases where one BM25 term (`Delicia`, `D.I.Y.`) would have settled the ranking, and the summary tier no-ops entirely on an all-image corpus. Visual-tier evals here are single-channel by construction — worth knowing before drawing any hybrid-search conclusion from this dataset.

---

## 11. One-line verdict for the comparison

**Retrieval is a null axis for `92f9ba9 -> 4ce90a8`.** Content-identical on 120/120 rows, on both bases, in both the sweep and the prompt; `search_query` byte-identical on 120/120, proving the rewriter change inert; one row's `ndcg@5` moved by 0.011 (aggregate 0.0001) and that row is a nine-way byte-identical-file lottery. **Attribute every one of the 57 verdict flips — `viz-11-typed` and `viz-11-full` included — to the answer stage. No flip on this dataset has a retrieval cause available to it.**

---

### Appendix — reproduction

Every figure above is recomputed from run artefacts, not copied from `metrics.json`: short passes over `answers_enriched.json`, `raw/answers.jsonl`, `raw/retrieve.jsonl`, `raw/appdata/manifest.json`, `raw/appdata/logs/llm-2026-09-06T10-39-33Z.log`, `datasets/custom_dataset_rahul_Aug30/{golden.json,qrels.tsv}`, plus `md5` over all 545 files in `corpus/` and reads of `corpus/diagrams/diagram_006.jpg` and `diagram_011.jpg`. Source files under `src/` were read (`stage2/search.py`, `answer.py`) and **not modified**. The `magpie-eval-compare` skill was not run.
