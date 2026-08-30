# RETRIEVAL REPORT

Run: `20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
Dataset: `custom_dataset_rahul_Aug30` (545 files, 15 folders, 14 categories carrying golden items)
Config: `top_k=2`, `rerank=OFF` (`MAGPIE_RERANK=0`), `rewrite=OFF`, `solo_margin=0`, `fast_search=ON`, `col_model` resolved to `colqwen2_5`, device MPS.

Scope: retrieval quality only. Answer correctness and the indexing defect are other agents' lanes; this report uses the indexing defect only to subtract items that ranking never had a chance on.

---

## 0. What this run actually measured (read this before any number)

Three structural facts, all established from the run's own artefacts, change how every metric below should be read.

**(a) This is a pure ColQwen run. The text tier contributed nothing.**
`run.json` `phases.index.summary_tier_note` reports *"no supported files found"* for the summary tier, and `worker_index.log:167` shows the summary-tier section producing nothing. Empirically: all **1437** ranked hits across all 120 queries in `raw/retrieve.jsonl` carry `tier: "fast"`. Zero `summary` and zero `both`. So dense-text and BM25 retrieval never voted. Every ranking in this run is ColQwen2.5 MaxSim over rendered page images.

**(b) The fused score carries zero information beyond rank.**
`src/stage2/search.py:598-644` computes RRF as `1/(RRF_K + rank)` summed across the summary and fast lists, with `RRF_K = 60`. With only one list populated, the score collapses to exactly `1/(60+rank)`. Verified: **120/120** records have scores matching `1/(60+i+1)` to within 1e-9 - 0.016393, 0.016129, 0.015873, ... in every single query. Consequence: there is **no magnitude, no separation, no confidence signal** in `score` anywhere in this run. Any downstream logic keyed on score margin (the solo gate; any abstention heuristic; any "is this hit good enough" threshold) is reading a constant. This is not a bug introduced by this config - it is what RRF does with one list - but it means this run cannot tell a confident retrieval from a desperate one, and no report on this run should claim it can.

**(c) Two different retrieval passes are being compared.**
The `retrieval` block (n=104) comes from the retrieval-only sweep in `raw/retrieve.jsonl` at `k_max=12`. The `retrieval_end_to_end` block (n=101) comes from what `ask()` actually returned at `top_k=2`. Because `rerank=False` sets `fetch_k = top_k` (`search.py:836`) and the fast tier is queried at `fetch_k * 2` (`search.py:850`), the sweep pulls **24** page-level candidates and the answer pass pulls **4**. They are not the same search. Section 6 shows this has a real, measurable consequence.

---

## 1. Headline metrics, with structurally-impossible items separated

### 1.1 As reported

| basis | n | hit@1 | hit@5 | MRR | nDCG@5 | recall@1 | recall@5 |
|---|---|---|---|---|---|---|---|
| `retrieval` (sweep, k=12) | 104 | 0.933 | 0.942 | 0.935 | 0.922 | 0.808 | 0.919 |
| `retrieval_end_to_end` (k=2) | 101 | 0.931 | - | 0.931 | 0.896 | 0.807 | - |

`retrieval_divergence`: `n_comparable=101`, `n_top1_differs=2`, `n_query_differs=0`.

### 1.2 What is inside those numbers that ranking did not cause

Three golden pairs (6 items) have their **entire gold set absent from the index**, per the supervisor diagnosis (fp16-NaN on MPS, 25 files dropped):

- `rcpt-07-typed` / `rcpt-07-full` - gold `receipt_040.jpg`, not indexed.
- `study-05-typed` / `study-05-full` - gold `electric-charge-and-field-9.pdf`, not indexed.
- `study-10-typed` / `study-10-full` - gold `CseGyan-Cpp-Notes-17/18/19.pdf`, **all three** not indexed (and already impossible at top_k=2 regardless).

I confirmed this independently: `raw/worker_index_result.json.manifest` holds 520 paths against the dataset manifest's 545; the 25-file difference is `notes_handwritten` 14, `receipts_phone` 9, `scans_multipage` 2, matching the diagnosis exactly. For these 6 items the ranker returned a coherent, on-topic neighbourhood of the true answer - `study-05` returned six other `electric-charge-and-field-*.pdf` pages; `study-10` returned six other `CseGyan-Cpp-Notes-*.pdf` pages - and scored zero because the only correct file did not exist in the collection. **This is not a ranking failure and must not be counted as one.**

One further pair is capped by construction: `viz-11` (gold `diagram_003.jpg`) has 8 byte-identical twins in `acceptable_sources`, so |relevant| = 9 and recall@2 caps at 0.222. hit@1 and MRR are unaffected (twins are rel=1, so a twin at rank 1 is a legitimate hit); recall@k and nDCG@5 are structurally depressed.

### 1.3 The honest ranking-quality number

| pool | n | hit@1 | hit@5 | MRR | nDCG@5 | recall@1 | recall@2 | recall@5 |
|---|---|---|---|---|---|---|---|---|
| all scored | 104 | 0.933 | 0.942 | 0.935 | 0.922 | 0.808 | 0.881 | 0.919 |
| minus index-dead (rcpt-07, study-05, study-10) | 98 | **0.990** | **1.000** | **0.992** | 0.978 | 0.858 | 0.935 | 0.976 |
| minus index-dead minus viz-11 | 96 | **0.990** | **1.000** | **0.992** | **0.982** | 0.873 | 0.950 | 0.984 |
| ... single-file items only | 80 | 0.988 | 1.000 | 0.990 | 0.988 | 0.952 | - | 0.994 |
| ... multi-file items only | 16 | 1.000 | 1.000 | 1.000 | 0.952 | 0.479 | - | 0.938 |

End-to-end, same subtraction:

| pool | n | hit@1 | MRR | recall@1 | nDCG@5 |
|---|---|---|---|---|---|
| e2e all | 101 | 0.931 | 0.931 | 0.807 | 0.896 |
| e2e minus index-dead | 95 | 0.990 | 0.990 | 0.859 | 0.952 |
| e2e minus index-dead minus viz-11 | 93 | 0.989 | 0.989 | 0.875 | 0.964 |

(The e2e nDCG@5 stays below the sweep's because the e2e list is only 2 long on most items while the ideal DCG is computed over 5 positions - a list-length artefact, not worse ordering. Do not read the 0.896-vs-0.922 gap as degradation.)

**Read-out.** On the 96 items where ranking could actually succeed, gold sits at rank 1 in **95 of 96** cases. hit@5 is a perfect 1.000. The retrieval stage of this pipeline is, on this corpus, close to saturated: there is essentially **one** genuine ranking error in the entire run. Against `answer.correct = 0.029` and `false_abstain = 0.423`, this confirms the supervisor's framing - retrieval is not the bottleneck, and no amount of retrieval work will move the answer numbers.

The remaining recall gap (recall@1 0.873, recall@2 0.950) is almost entirely the **top_k=2 window**, not ordering: 7 of 96 clean items have incomplete gold in the top-2, and 6 of those 7 are items whose |relevant| exceeds 2 (see section 4.2). Only `rcpt-05-typed` is a true miss.

---

## 2. Where ranking actually went wrong

Across all 104 scored items, gold was **not** at rank 1 in 7 items. Clustered:

### Cluster A - gold not in the index (6 items, NOT ranking)
`rcpt-07-typed`, `rcpt-07-full`, `study-05-typed`, `study-05-full`, `study-10-typed`, `study-10-full`. Covered in 1.2. In every case the ranker returned same-series, same-category neighbours - for `study-10-typed` the top-6 are `CseGyan-Cpp-Notes-14, -15, -11, -4, -13, -16`, i.e. the ranker landed precisely on the C++ notes series and would plausibly have found 17/18/19 had they existed. Attribute to indexing.

### Cluster B - the one genuine ranking failure (1 item)

**`rcpt-05-typed`** - gold `bad_receipt_014.jpg`, first gold rank **5**.

```
 1. scene_887bfd79f29a3fcb.jpg   scene_text          0.01639
 2. 110671448.jpg                photos              0.01613
 3. info_008.jpg                 infographics        0.01587
 4. receipt_024.jpg              receipts_phone      0.01562
 5. bad_receipt_014.jpg          receipts_degraded   0.01538  <- GOLD
```

Query: *"that shop where i bought loads of chocolate bars total"*.

I opened the three files. `scene_887bfd79f29a3fcb.jpg` is a photograph of a **Hallmark shop frontage** - signage, retail shelving, a shop interior. `110671448.jpg` is a photograph of people at a **deli/cafe counter** with a fridge and packaged goods on shelves. `bad_receipt_014.jpg` is an ASIA MART tax invoice whose first line item reads `DELICIA CHOCOLATE [50G]`, qty 17, total RM 32.70.

The mechanism is clear and it is a ColQwen-specific one: the terse query's strongest content word is **"shop"**, and ColQwen is a *visual* matcher. It matched "shop" against pictures **of shops**. The query never says "receipt", "invoice", or "total sales" - the only document-type cue is the bare word "total", which is weak - so nothing in the query pulls toward receipt-shaped page layout. The full phrasing of the same pair (*"...a whole pile of **Delicia** chocolate bars..."*) puts gold at rank 1, because "Delicia" is a literal printed string on the receipt image and ColQwen's patch-level MaxSim finds printed text well. See section 3.

This is the entire ranking-error budget of the run. There is no second cluster, and I want to be explicit about the uncertainty that creates: **n=1 does not support a general claim about a failure mode.** What it supports is a hypothesis - terse queries that describe the *scene* rather than the *document* get matched as scenes - which section 3 partially corroborates but does not prove.

### Non-failures worth naming (so nobody re-derives them as failures)

- **`viz-11-typed` / `viz-11-full`** rank a *twin* of the gold at 1 and 2 and the gold itself at 3. `hit@1` correctly scores these as hits (twins are rel=1 and are byte-identical, so the retrieved image is literally the gold image). The apparent "gold at rank 3" is a filename artefact, not a ranking error.
- **`rcpt-08-typed`** puts `screen_24454.jpg` (an Android screenshot) at rank 2, displacing a second Mr D.I.Y. receipt. Gold is at rank 1 and the item is a 3-gold-file synthesis query that top_k=2 cannot satisfy anyway; the widener actually returned 12 files end-to-end for this item (section 6.6). Ceiling, not ranking.

---

## 3. typed vs full phrasing

### 3.1 The gap

| pool | phrasing | n | hit@1 | MRR | recall@1 | recall@2 | recall@5 | nDCG@5 |
|---|---|---|---|---|---|---|---|---|
| all scored | typed | 52 | 0.923 | 0.927 | 0.799 | 0.868 | 0.916 | 0.913 |
| all scored | full | 52 | 0.942 | 0.942 | 0.818 | 0.894 | 0.923 | 0.930 |
| minus dead minus viz-11 | typed | 48 | **0.979** | 0.983 | 0.863 | 0.936 | 0.981 | 0.972 |
| minus dead minus viz-11 | full | 48 | **1.000** | 1.000 | 0.884 | 0.964 | 0.988 | 0.991 |

On the clean pool the gap is **exactly one item**: full phrasing is perfect (48/48 at rank 1), typed loses `rcpt-05`. delta hit@1 = 0.021, delta recall@2 = 0.028, delta nDCG@5 = 0.019.

**Named pairs where the phrasings diverge (only two exist across all 60 pairs):**

- **`rcpt-05` - typed lost, full won.** typed first-gold-rank 5, gold@2 = 0; full first-gold-rank 1, gold@2 = 1. Analysed in section 2 Cluster B. What the terse form lacked: the brand token **"Delicia"**, which is printed on the target image, and any document-type word ("receipt"/"invoice"). What it kept - "shop" - actively steered the visual matcher toward photographs of shops.
- **`rcpt-08` - both hit at rank 1, full recovered more gold.** typed gold@2 = 1 (`bad_receipt_002.jpg` + an unrelated screenshot); full gold@2 = 2 (`bad_receipt_002.jpg` + `bad_receipt_004.jpg`). The full form *"Adding up all my Mr D.I.Y. receipts..."* names the document type and pluralises it; the typed form *"how much did i spend at mr diy altogether"* does not contain the word "receipt" at all. Consistent with the `rcpt-05` mechanism.

### 3.2 Why the gap is real but small, and the mechanism I did find

With `rewrite=OFF` the only query-side normalisation left in the pipeline is `extract_rare_tokens()` (`search.py:985`, enabled by default via `MAGPIE_RARE_TOKENS`). I measured its behaviour directly on this run's 120 queries:

> **Keywords were extracted on 7 of 60 full-phrasing queries and on 0 of 60 typed queries.**

The 7: `arch-06-full` `['pH']`, `study-03-full` `['kW']`, `study-06-full` `['arXiv']`, `study-09-full` `['arXiv']`, `rcpt-02-full` `['McDonald','ChicMcMuffins']`, `rcpt-03-full` `['RedVelvet']`, `rcpt-08-full` `['D.I']`.

The extractor is identifier-shaped-token matching; typed queries in this golden set are uniformly lowercase and unpunctuated, so it is **structurally blind to the typed slice**. That is a genuine asymmetry: the one remaining query-normalisation mechanism fires only on the phrasing that needs it least.

Two honest caveats, both of which cap how much this explains:

1. `rcpt-05-full` extracted **no** keywords (the extractor missed "Delicia"), so keyword extraction is *not* what saved `rcpt-05-full`. The win came from the raw string itself, which ColQwen embeds verbatim.
2. Keywords in this run can only ever have had a weak effect anyway: they feed a dedicated sparse prefetch on the **summary tier** (`search.py:409-419`), which was empty (0a), and are otherwise merely concatenated onto the ColQwen query text (`search.py:849`). So the extractor's typed-blindness is a latent defect that this run *would* expose more sharply on a corpus where the text tier is populated. **I cannot claim it caused the observed gap here.**

**Bottom line on phrasing:** the gap is directionally what you would predict with the rewriter off, and it is visible in every metric, but at n=1 differing item it is not statistically meaningful. What is meaningful is the *mechanism* the single case exposes, and the measured 7-vs-0 keyword asymmetry, which is a defect regardless of its effect size here.

### 3.3 Phrasing changes the ranking a lot even when it does not change correctness

Across all 60 pairs: identical top-1 in **49/60**, identical *ordered* top-2 in only **21/60**, same top-2 *set* in **24/60**. So more than half the time the two phrasings hand the generator a different second file, while still landing the same correct first file. Retrieval is stable where it matters and volatile in the slot that mostly carries distractors - worth knowing before anyone diagnoses an answer-side typed/full difference as a retrieval difference.

---

## 4. Per-category retrieval

### 4.1 Table

Left block = as-scored. Right block = with index-dead items and `viz-11` removed.

| category | n | hit@1 | recall@1 | recall@2 | nDCG@5 | clean n | clean hit@1 | clean recall@2 | clean nDCG@5 |
|---|---|---|---|---|---|---|---|---|---|
| charts | 10 | 1.000 | 0.900 | 1.000 | 1.000 | 10 | 1.000 | 1.000 | 1.000 |
| documents | 6 | 1.000 | 0.833 | 1.000 | 1.000 | 6 | 1.000 | 1.000 | 1.000 |
| figures | 6 | 1.000 | 1.000 | 1.000 | 1.000 | 6 | 1.000 | 1.000 | 1.000 |
| infographics | 8 | 1.000 | 0.875 | 1.000 | 1.000 | 8 | 1.000 | 1.000 | 1.000 |
| photos | 6 | 1.000 | 1.000 | 1.000 | 1.000 | 6 | 1.000 | 1.000 | 1.000 |
| scans_multipage | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 8 | 1.000 | 1.000 | 1.000 |
| scene_text | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 8 | 1.000 | 1.000 | 1.000 |
| screenshots | 8 | 1.000 | 0.875 | 1.000 | 1.000 | 8 | 1.000 | 1.000 | 1.000 |
| slides | 6 | 1.000 | 0.833 | 1.000 | 1.000 | 6 | 1.000 | 1.000 | 1.000 |
| tables_fr | 6 | 1.000 | 0.833 | 1.000 | 1.000 | 6 | 1.000 | 1.000 | 1.000 |
| diagrams | 4 | 1.000 | 0.556 | 0.611 | 0.899 | 2 | 1.000 | 1.000 | 1.000 |
| receipts_phone | 10 | 0.800 | 0.700 | 0.800 | 0.800 | 8 | 1.000 | 1.000 | 1.000 |
| receipts_degraded | 8 | 0.875 | 0.708 | 0.750 | 0.828 | 8 | **0.875** | **0.750** | **0.828** |
| notes_handwritten | 10 | 0.600 | 0.317 | 0.317 | 0.562 | 6 | 1.000 | **0.528** | 0.936 |
| notes_iam | - | - | - | - | - | - | zero golden items by design (section 5) | | |

### 4.2 Reading it

**Eleven of fourteen categories are perfect after subtraction** - hit@1 1.000, recall@2 1.000, nDCG@5 1.000. That includes the categories one would expect to be hardest for a visual retriever: `scans_multipage` (archive scans, 140 pages across 19 PDFs), `tables_fr` (dense financial tables), `figures` (uncaptioned arXiv panels), `screenshots` (RICO app UIs). ColQwen handles all of them.

The three non-perfect categories fail for three *different* reasons, and only one is a ranking problem:

- **`receipts_phone` 0.800 -> 1.000.** The entire deficit is `rcpt-07`, whose gold `receipt_040.jpg` is one of the 9 non-indexed phone receipts. Clean: perfect. Indexing, not ranking.
- **`notes_handwritten` 0.600 -> 1.000 hit@1, but recall@2 only 0.528.** hit@1 recovers completely once `study-05` and `study-10` are removed. The residual recall@2 of 0.528 is the `acceptable_sources` cap: `study-02` has |relevant| = 4 (gold `CseGyan-Cpp-Notes-3.pdf` + 3 acceptable) so recall@2 caps at 0.500, and `study-04` has |relevant| = 3 so it caps at 0.667. Both hit gold at rank 1 in both phrasings. `study-04` even puts the two acceptable pages at ranks 3 and 4 in both phrasings - the ranker found the whole span, the k=2 window cut it. **Not a ranking failure; a top_k ceiling.**
- **`receipts_degraded` 0.875 / 0.750 - the only category with real residual error.** `rcpt-05-typed` (section 2) plus `rcpt-08`'s 3-gold-file ceiling. This is the one category where the honest number does not recover on cleaning, and it is a category where the *document* is visually distinctive but the *query* often is not.

### 4.3 Near-duplicate pressure (diagrams: 9 unique images across 40 files)

Measured, not assumed. `diagrams` occupies **7 of 240** top-2 slots across all 120 queries - a category share of 2.9% against a corpus share of 7.3%, **lift 0.40**, the second-lowest of any category. Duplicate-group files (the 31 redundant diagram copies) appear in only **5** top-2 slots across 3 queries and **37** top-12 slots across 8 queries.

So the duplicate block is *not* flooding the index in general. It floods **one query**, catastrophically:

- `viz-11-typed` and `viz-11-full`: the top-12 contains **9 copies of the same image** - every member of the `diagram_003..011` group. The top-2 window is two byte-identical files, i.e. **slot 2 delivers zero new information to the generator**. Confirmed on both the sweep basis and the end-to-end basis (`retrieve.jsonl` and `answers_enriched.json` agree that both returned files are same-SHA).
- `viz-10` (gold `diagram_018.jpg`, the one *unique* diagram) is clean: rank 1 in both phrasings, no twins anywhere in its top-5.

Three other queries pull 2-3 copies of one image into their top-12 (`arch-01-full` x3, `viz-01` x2, `arch-05` x2, `study-08-typed` x2) but none into the top-2 window.

**Interpretation.** Byte-identical near-duplicates cost nothing on ranking *accuracy* - the ranker still puts a correct image first - but they cost **context budget**, and at top_k=2 that cost is 50% of the window. The measured effect is confined to queries that target a duplicated image, which here is exactly one pair. The product implication is real and independent of this eval: no dedup-by-content-hash exists at retrieval time, so a user with 9 copies of a file gets 9 copies of it in results.

---

## 5. Distractor pressure

### 5.1 notes_iam - the by-construction false-positive slice

30 files (5.5% of the corpus) carrying zero golden items. Every appearance in a result is a false positive.

| window | notes_iam slots | total slots | share | queries affected |
|---|---|---|---|---|
| top-1 | 1 | 120 | 0.8% | 1 |
| top-2 | 1 | 240 | **0.4%** | 1 |
| top-5 | 3 | 600 | 0.5% | 3 |
| top-12 | 10 | 1437 | 0.7% | 10 |

Against a 5.5% corpus share, **lift 0.08** at top-2 - the lowest of any category by a factor of five. The index is not confused by them.

The single top-2 appearance is **`nf-05-typed`**, query `"transcript"`, which retrieved `note_004.png`. This is arguably the retriever behaving *correctly*: the query is one word, the corpus contains no transcript, and IAM handwriting strips are the closest thing in the index to a page of transcribed prose. The 9 other top-12 appearances are similarly explainable - `viz-05-typed`, `viz-07-full`, `viz-10-typed/full`, `study-04-typed/full`, `study-06-typed`, `study-10-typed`, `nf-06-typed` - all handwriting-adjacent or diagram/annotation queries, never a receipt or table query.

**What this says about the index:** ColQwen's page-image embedding separates *document genre* very cleanly. Handwriting strips do not leak into receipt, chart, table, or screenshot queries at all. That is a positive result and it holds across 1437 observed slots.

### 5.2 Category-level distractor lift, top-2 window (240 slots)

| category | slots | share | corpus share | lift |
|---|---|---|---|---|
| notes_handwritten | 29 | 12.1% | 6.8% | 1.78 |
| scans_multipage | 16 | 6.7% | 3.5% | 1.91 |
| tables_fr | 13 | 5.4% | 3.7% | 1.48 |
| infographics | 25 | 10.4% | 7.3% | 1.42 |
| slides | 17 | 7.1% | 5.5% | 1.29 |
| receipts_phone | 20 | 8.3% | 7.3% | 1.14 |
| scene_text | 20 | 8.3% | 7.3% | 1.14 |
| documents | 25 | 10.4% | 9.7% | 1.07 |
| screenshots | 18 | 7.5% | 7.3% | 1.02 |
| charts | 15 | 6.2% | 7.3% | 0.85 |
| photos | 14 | 5.8% | 7.3% | 0.79 |
| figures | 11 | 4.6% | 7.3% | 0.62 |
| receipts_degraded | 9 | 3.8% | 6.6% | 0.57 |
| diagrams | 7 | 2.9% | 7.3% | 0.40 |
| **notes_iam** | **1** | **0.4%** | **5.5%** | **0.08** |

Caveat: lift is confounded with golden-item density - `notes_handwritten` and `scans_multipage` carry 10 and 8 scored items respectively, so some of their over-representation is legitimate gold. The clean signals are the *low* end: `diagrams` (duplicates suppressed, 0.40) and `notes_iam` (0.08).

### 5.3 Who occupies the non-gold slot

On the 80 clean items where rank 1 is gold and rank 2 is not, the runner-up is in the **same category as the gold in 38/80 cases (48%)**. The commonest cross-category confusions are `scans_multipage -> documents` (6), `infographics -> slides` (3), `figures -> notes_handwritten` (3), `receipts_degraded -> infographics` (3) - all pairs that are genuinely similar as *page images* (archive scan vs. scanned document; deck slide vs. infographic; plotted figure vs. hand-drawn diagram). No confusion is semantically absurd.

### 5.4 Index concentration

Across 120 queries, **132 distinct files** appear in some top-2 (of 520 indexed) and **397** in some top-12. No file dominates: the most-repeated top-2 file is `doc_14753.jpg` at 6 appearances, then `info_024.jpg`, `info_001.jpg`, `deck_002.pdf`, `CseGyan-Cpp-Notes-11/14/15.pdf`, `receipt_005.jpg` at 4 each. There is **no "universal attractor" file** - no single page that wins regardless of query, which is a common failure mode in visual indexes and is absent here.

---

## 6. Gate and rerank: confirmed inert

### 6.1 Rerank did nothing - structurally

`MAGPIE_RERANK=0` is stamped in `run.json.env_snapshot`. `_rerank_enabled()` (`search.py:579`) returns False, and `run_search` forces `rerank = False` at `search.py:791` before any classification. The cross-encoder was never constructed and never scored a pair. Corroborated by the data: every returned `score` is exactly `1/(60+rank)` (0b) - cross-encoder scores are on a different, non-positional scale, so their absence is directly observable in the artefact. **All ordering in this run is ColQwen MaxSim, full stop.**

### 6.2 The solo gate did not fire - and the harness's 0.05 fire-rate is a false positive

`metrics.json` reports `solo_gate.fire_rate: 0.05`. **This did not happen.** `gate_to_solo()` (`search.py:923`) returns its input unchanged at the first branch, `if not _rerank_enabled(): return retrieved`, before it ever computes a margin. `run.json` correctly stamps `solo_gate_structurally_off: true`. Additionally `LOCAL_SOLO_MARGIN=0`, which would disable it a second time at `search.py:935`.

The 0.05 comes from `enrich.py:370`, which *infers* a gate firing from the heuristic "the answer pass returned 1 file while the pre-gate sweep had >= 2". That fired on exactly 6 items: `arch-04-typed`, `arch-04-full`, `arch-06-typed`, `study-03-typed`, `study-08-typed`, `study-08-full` - 6/120 = 0.05. Every one of them records `solo_margin_observed: 0.0` (which is `1/61 - 1/62 = 0.000264` rounded to 3 dp, on the RRF scale - visibly not a cross-encoder margin).

### 6.3 What actually caused those 6 one-file results - a real defect, not a gate

All six single-file results are **multi-page PDFs**: `scan_mtnh0227.pdf` (x2), `scan_gzyh0227.pdf`, `deck_022.pdf`, `deck_027.pdf` (x2). The mechanism:

- With rerank off, `fetch_k = top_k = 2` (`search.py:836`).
- The fast tier is queried with `limit = fetch_k * 2 = 4` (`search.py:850`), returning **4 page-level** candidates.
- `_search_fast_tier` then collapses to **one result per file**, best page wins (`search.py:544-551`).
- If all 4 retrieved pages belong to the same PDF, the collapse leaves **one file**, and `ask()` hands the generator a single document instead of two.

The retrieval-only sweep runs the same code at `k_max=12` -> `limit=24`, which is wide enough that other files survive the collapse - which is why `raw/retrieve.jsonl` shows 2 distinct files at ranks 1-2 for all six while `answers_enriched.json` shows 1. **The sweep basis masks this entirely.** It costs no measured recall here (gold was rank 1 in all six), but it means the effective context budget at `top_k=2` is silently 1 file whenever the top hits cluster in one multi-page PDF, and the harness currently mislabels it as a gate firing. Two separate follow-ups: size the fast-tier prefetch off *file* count rather than raw point count, and tighten the `solo_gated` inference (`enrich.py:370`) to return `None` when `solo_gate_structurally_off` is set.

### 6.4 Rewrite did nothing - confirmed

`n_query_differs = 0`. Independently verified: for all 120 records `search_query.final_query == question` byte-for-byte, `rewritten` is False on all 120, and `latency_s.rewrite == 0.0` on all 120. No LLM call was made on the query path. Keywords were populated on 7 items only (3.2).

### 6.5 The 2 top-1 divergences are duplicate tie-breaking, not instability

`retrieval_divergence.n_top1_differs = 2`. Both are `viz-11`:

| qa_id | sweep top-1 | e2e top-1 |
|---|---|---|
| `viz-11-typed` | `diagram_006.jpg` | `diagram_011.jpg` |
| `viz-11-full` | `diagram_006.jpg` | `diagram_011.jpg` |

`diagram_006.jpg` and `diagram_011.jpg` are **byte-identical** (same SHA256, members of the 9-copy group). Their ColQwen embeddings are therefore identical, their MaxSim scores are tied, and the two passes broke the tie differently. This is not ranking instability and carries no information about retrieval quality - with 118/120 top-1s identical across two independently-executed searches, the retriever is **deterministic everywhere it can be**.

### 6.6 The LIST_ALL widener did fire (7 items) - note it, it is not the gate

Seven items returned 12 files end-to-end instead of 2: `arch-06-full`, `rcpt-01-full`, `rcpt-08-typed`, `rcpt-08-full`, `phone-05-full`, `phone-07-typed`, `nf-06-full`. This is `enumerate_lists=true` routing them to `QueryClass.LIST_ALL` and widening `top_k` to the local cap of 12 (`search.py:786-806`). It is the opposite of gating and it is working as designed - notably it gave `rcpt-08` (3 gold files) the window it needed. Anyone reading `len(retrieved)` in this run must account for both the widener (12) and the PDF page-collapse (1) before drawing conclusions.

---

## 7. Caveats and what this run cannot tell you

1. **n=1 ranking error.** Almost every mechanism in sections 2 and 3 rests on a single item (`rcpt-05-typed`). The mechanism is well-evidenced *for that item* (I read the images); its generality is a hypothesis.
2. **No score signal.** 0b means this run cannot support any statement about retrieval confidence, margin, or "how sure the ranker was". Do not let a downstream report infer abstention behaviour from retrieval scores here.
3. **Text tier untested.** With the summary tier empty, this run measures ColQwen alone. It says nothing about hybrid dense+BM25+ColQwen behaviour, which is what production ships. In particular the `extract_rare_tokens` typed-blindness (3.2) is unmeasured here because its main consumer never ran.
4. **Golden set is SILVER / model-authored, 0 human-verified.** Gold assignments come from a vision read by an agent. A wrong gold label would appear as a ranking failure. Given hit@1 = 0.99 there is little room for that to matter, but the 1 failure has not been independently gold-checked.
5. **3 items have no end-to-end retrieval row** (`study-03-full`, `phone-05-typed`, `phone-11-full`) because the generator returned HTTP 400 before recording retrieval. That is why e2e n=101 vs sweep n=104 - a generator error, not a retrieval error.
6. **`top_k=2` is the dominant constraint on recall.** 5 golden pairs have |relevant| > 2 (`viz-11` 9, `study-02` 4, `study-04` 3, `study-10` 3, `rcpt-08` 3); recall@2 is capped below 1.0 for all of them by arithmetic. Any recall comparison against a run at a different `top_k` must exclude them or bound them.

---

## 8. Verdict

Retrieval is **not** the limiting stage of this run and is not close to being it. On the 96 items where the correct file was in the index and the metric was not capped by construction, ColQwen put gold at rank 1 in 95 and inside the top 5 in 96 - hit@1 0.990, hit@5 1.000, MRR 0.992, nDCG@5 0.982. Eleven of fourteen categories are perfect. Distractor pressure from the 30 designed-in false-positive files is 0.4% of the top-2 window (lift 0.08). The near-duplicate block costs context, not accuracy, and only on the one query that targets it. Rerank, the solo gate, and the rewriter each verifiably did nothing.

The three things worth carrying forward from this lane are all *structural*, not quality: the fused score is rank-degenerate and therefore useless as a confidence signal; the fast-tier prefetch is sized in page-points rather than files, so `top_k=2` silently degrades to 1 file on multi-page PDFs; and `enrich.py`'s solo-gate inference reports firings that provably did not occur.
