# REPORT — Indexing analyst

Run: `20260829T065335Z-receipts-topk2-rerank-off`
Corpus: 148 receipt JPEGs, `~/Documents/Magpie-eval-corpora/receipts/batch_00..batch_10/`
Config: `index_fast_tier: true`, `index_summary_tier: true`, `fast_search: true`, `top_k: 2`, `MAGPIE_RERANK=0`, provider `local`.

**Bottom line:** the fast tier did its job cleanly — 148/148 files, 148 pages, 0 errors, no
outliers, no silent skips. The summary tier producing nothing is **correct by design**, not a
bug: the router assigns every image to the fast tier and the summary tier is explicitly told to
skip fast-tier files, so an all-image corpus leaves it with an empty work list. The real finding
is not "indexing broke" — it is that **Magpie has no text-producing index path for image-only
corpora at all**, and this run is the first time that architectural hole has been measured.

---

## 1. Why the summary tier found "no supported files" — BY DESIGN

This is the most important question in the brief, so the full chain, with quotes.

**`.jpg` is emphatically supported.** It is in `IMAGE_EXTS` and therefore in `SUPPORTED_EXTS`:

- `src/content.py:24` — `IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ...}`
- `src/content.py:74-86` — `SUPPORTED_EXTS = set(IMAGE_EXTS) | CSV_EXTS | PDF_EXTS | ...`

So the extension filter in `find_supported_files` keeps all 148 files:

```
src/stage1/summarize.py:765
    return sorted(p for p in files if p.suffix.lower() in SUPPORTED_EXTS)
```

The files are removed one step later, by tier de-duplication. The router sends every image to the
fast tier unconditionally:

```
src/stage1_fast/router.py:110-111
    if suffix in FAST_IMAGE_EXTS:
        return "fast"
```

and `run_batch` is invoked with `skip_fast_tier=True`, which strips exactly those files:

```
src/stage1/summarize.py:789-796
    files = find_supported_files(root)
    if skip_fast_tier:
        # Don't double-process files the fast tier already covers (PDFs <=50p,
        # images). Routes are decided by `src.stage1_fast.router.route_file`.
        from src.stage1_fast.router import route_file
        files = [p for p in files if route_file(p) != "fast"]
    if not files:
        sys.exit(f"no supported files found under {root}")
```

The caller that sets the flag:

```
src/pipeline.py:307-312
    await run_batch(
        summ_agent,
        source_dir,
        force=force_summarize,
        concurrency=concurrency,
        skip_fast_tier=True,
    )
```

**Verdict: by design, not misconfiguration.** `148 files -> extension filter -> 148 -> route filter ->
0 -> sys.exit`. Turning `index_summary_tier` on for a 100%-image corpus is a no-op by construction;
there is no setting in this run's config that would have made the summary tier produce anything.
The supervisor's claim 1 is confirmed, with the correction that the cause is tier mutual exclusion,
not an unsupported extension.

### Three real defects visible in that same chain (design smells, not run-breakers)

1. **The error message is actively misleading.** `sys.exit("no supported files found under …")` is
   emitted after the *route* filter, not the *extension* filter. Every file was supported; none was
   summary-routed. A reader of `worker_index_result.json` reasonably concludes Magpie cannot read
   JPEGs. It can. The message should distinguish "0 supported" from "0 summary-routed, N handled by
   the fast tier."
2. **`sys.exit` used as control flow inside a library function.** It forces the harness to catch
   `SystemExit` and string-match the message (`eval_harness/harness/worker.py:184-190`,
   `if "no supported files" in msg`). Any reword of that string silently converts a benign
   condition into a hard harness failure, or vice versa. The comment there also cites
   `src/stage1/summarize.py:603`; the actual line is 796 — stale reference.
3. **`SystemExit` aborts the rest of `sync_files`.** `ingest_from_manifest` (`src/pipeline.py:315`)
   and the per-tier timing print never ran. Harmless here (nothing to ingest), but it means the
   run has no recorded fast-vs-summary tier split — `wall_s: 426.17` is harness-measured wall clock
   only, and `worker_index.log` contains no tier-timings block (verified: 0 matches).

---

## 2. Coverage: all 148 files indexed — verified, no exceptions

Cross-checked `worker_index_result.json.manifest` (148 keys) against
`eval_harness/datasets/receipts/manifest.json` (`n_files: 148`, `files[].name`) and against a
filesystem glob of `batch_*/`:

| Check | Result |
|---|---|
| Dataset manifest names | 148, all unique |
| Files on disk under `batch_*/` | 148, set-identical to dataset manifest |
| Manifest entries in index result | 148, all unique basenames |
| In dataset but **missing from index** | **none** |
| In index but **not in dataset** | **none** |
| Entries with `fast_indexed_at` unset | **0** |
| Entries with a non-null `skip_reason` | **0** |
| `fast_pages` distribution | `{1: 148}` — every receipt one page, as expected |

The indexer's own tally agrees exactly (`raw/worker_index.log`, final fast-tier line):

```
fast tier: 148 files indexed (148 pages), 0 unchanged, 0 pruned, 0 errors
```

Qdrant agrees too (`raw/qdrant.log`):

- `PUT /collections/fast_tier HTTP/1.1` x 1 (collection created)
- `PUT /collections/fast_tier/index?wait=true` x 1 (`source_path` payload index)
- **`PUT /collections/fast_tier/points?wait=true` x 148** — one upsert per file, one point per page
- `POST /collections/fast_tier/points/query` x 240 (the query phase)
- **0 lines matching `error|panic|fail`** across the whole 161 KB log

On-disk collection is 146 MB for 148 pages (~1 MB/page), consistent with ColQwen2.5's ~1030
patch vectors x 128 dims held at float32 plus the int8 quantized copy and the on-disk HNSW graph.
No page produced zero vectors — a zero-vector page would have failed the multivector upsert, and
all 148 upserts returned clean.

**No file is missing, errored, or silently skipped. Coverage is 100%.**

### Storage/model configuration is sound

`~/.cache/notspotlight/device.json` records the selection actually used:
`device: mps`, `model_id: vidore/colqwen2.5-v0.2`, `dtype: float16`, `batch_size: 2` — i.e. the
capable model, not the small-slot ColSmol fallback (the machine is an M1 Max / 64 GB, comfortably
over `COLQWEN_UNIFIED_MIN_GB = 24.0`, `src/stage1_fast/device.py:83`). The collection is created
with `MAX_SIM` multivector comparison, int8 scalar quantization **with rescore enabled**
(`_RESCORE_PARAMS`, `rescore=True, oversampling=2.0`, `src/stage2/fast_db.py:183-190`), and
`on_disk=True` for both vectors and HNSW. Images are passed to the processor at native resolution
— `_render_pages` does no downscaling for images (`src/stage1_fast/index.py:63`,
`return [Image.open(path).convert("RGB")]`), so any resizing is ColQwen's own trained preprocessing.
Nothing in the indexing configuration degrades quality beyond the documented ~1.5% quantization
recall cost, which the rescore pass largely recovers.

---

## 3. Per-file timing: uniform, no outliers

Two independent sources agree.

**tqdm (`raw/worker_index.log`)**: `148/148 [06:51<00:00, 2.78s/file]`. The rate is flat across the
whole run — sampled instantaneous rates at 88%-100% stay inside 2.70-2.81 s/file. No stall, no
tail.

**Manifest timestamps** (`fast_indexed_at`, 1-second resolution, so deltas quantize):

| Statistic | Value |
|---|---|
| First -> last indexed | `06:53:52Z` -> `07:00:39Z` (407 s span) |
| Per-file delta, n | 147 |
| min / median / mean / max | 2.0 s / 3.0 s / 2.77 s / **4.0 s** |
| Delta histogram | 3 s x 109, 2 s x 36, 4 s x 2 |

**Slowest file cost 4 seconds.** There is no pathological outlier, no file that took double-digit
seconds, and no file that produced zero pages. Total harness-measured index wall clock was 426.2 s;
411 s of that is the fast tier (model load ~15 s + 6m51s encode), and the remaining ~15 s is the
summary tier spinning up the local LFM2.5-VL llama-server before immediately exiting — wasted work,
visible in the log as `llama-server: 'lfm25-vl-vision' ready … (pid 51716, 2.8s)` followed
directly by the summary-tier banner and nothing else.

**Telemetry gap:** `t4_cost_s` and `t4_cost_mb` are `0.0` for all 148 entries, and `visual_score`,
`routes`, `content_hash` are likewise unpopulated. `src/stage1_fast/index.py` only calls
`manifest.mark_fast_indexed(rel, size=size, pages=len(images))` (line 141); the cost fields are
written by a different code path (`src/router.py:847-848`, itself hard-coded to `0.0`). Not a
correctness problem, but it means the manifest cannot be used to attribute per-file indexing cost
in any future run.

**Related, and relevant to the dedup story:** fast-tier change detection is **size-only** —
`if not force and not manifest.needs_fast_indexing(rel, size)` (`src/stage1_fast/index.py:111`),
and `content_hash` is never populated. Magpie therefore cannot detect byte-identical duplicates
itself; two identical receipts get two distinct point IDs (`_page_point_id` hashes the *path*,
`src/stage2/fast_db.py:72-79`) and both compete for the same rank. The owner's external 150->148
dedup fixed a gap the indexer has no way to close on its own. Supervisor claim 3 is confirmed and
consistent with the dataset manifest's own `selection` note (`receipt_X51005301666.jpg` ==
`receipt_X51005268275.jpg`; `receipt_X510056849111.jpg` == `receipt_X51005684949.jpg`); the two
removed twins are correctly absent from both the corpus and the index.

---

## 4. Spot-check: image quality vs. what the golden set asks

Six files opened and read directly, chosen to span the degradation axes (lowest bytes-per-pixel,
smallest pixel area, tallest aspect ratio, largest file) rather than at random. Gold-set coverage
is 74 distinct files across 120 questions; all 74 are present in the corpus (verified — zero gold
files missing).

| File | px | Legibility | Question asked | Fact present & readable? |
|---|---|---|---|---|
| `receipt_X51005442322.jpg` (batch_01) | 1080x1528 | Excellent, clean scan | `rcpt-a-01` Tony Roma's total -> `269.40` | **Yes** — `Total 269.40` in large type |
| `receipt_X00016469671.jpg` (batch_00) | 463x776, smallest area | Excellent despite size — crisp digital render | `rcpt-a-10` OJC safety-shoe sum -> `170.00` | **Yes** — `TOTAL: 170.00` |
| `receipt_X51005288570.jpg` (batch_00) | 447x1127 | Excellent, dot-matrix but sharp | `rcpt-a-03` which car park -> `Riverwalk Village`, `Jalan Ipoh` | **Yes** — both lines in the header |
| `receipt_X51005447844.jpg` (batch_02) | 936x2015, **lowest bytes/px in the gold set (0.10)** | Good text, but **right edge is physically cropped** — the Amt(RM) column is truncated (`42.`, `5.0`, `3.0`) | `rcpt-b-01` Jiawei dinner total -> `110.00` | **Yes** — `TOTAL RM 110.00` sits left of the crop |
| `receipt_X51005710963.jpg` (batch_05) | 880x2526 | Faint/low-contrast thermal print, header partially ghosted, still readable | `rcpt-c-08` receipt number -> `CS00032256` | **Yes** — `RECEIPT #: CS00032256` legible |
| `receipt_X51006008090.jpg` (batch_10) | 744x2318, tallest aspect (3.12:1) | Excellent | `rcpt-e-09` Popular Empire vs AEON -> `30.50` | **Yes** — `Total RM 30.50`, and `EMPIRE SHOPPING GALLERY` + date `05/03/18` match the golden answer exactly |

**No gold file is unanswerable in principle.** Every fact the golden set asks for is present and
readable in the pixels. Two things worth the supervisor's attention anyway:

- **`receipt_X51005447844.jpg` is a near-miss.** Its right column is genuinely cut off by the scan.
  The asked-for fact (grand total) survives, but any future question about a *line-item amount* on
  this receipt would be unanswerable from the image. It is the one file in the gold set I would
  not reuse for a harder question.
- **`rcpt-e-09` cross-checks clean.** The golden answer ("AEON Shah Alam RM30.70 on 06/03/18 vs
  Empire Shopping Gallery RM30.50 on 05/03/18") matches `receipt_X51006008090.jpg` exactly on the
  Empire side, so the two files are not swapped.

**This means the failures downstream are not an image-quality problem.** For `rcpt-a-01` the
correct file `receipt_X51005442322.jpg` was retrieved at **rank 1** and the receipt plainly reads
`Total 269.40` — yet `raw/answers.jsonl` records `magpie_answer: "40.80"`. The pixels were there,
the retrieval was right, and the answer was still wrong. That is an answering-stage defect, not
an indexing or golden-set one.

---

## 5. What was actually lost, and what an ideal pass should have produced

### The supervisor's claim 2, verified — with one important correction

Confirmed: the placeholder is real and constant. `src/stage2/search.py:553` (the supervisor's
`:552` points at the enclosing `SearchResult(` on the line above):

```python
    return [
        SearchResult(
            summary=f"(visual match — page {page})",
            path=path,
            score=score,
            tier="fast",
```

Every one of the 262 retrieval hits across the 120 questions carries `tier: "fast"` — not a single
`summary`-tier hit in the entire run. No `summaries` Qdrant collection was ever created (the log
shows 240 `GET /collections/summaries/exists` probes and **zero** `PUT /collections/summaries`),
no summary `.md` files exist anywhere under `raw/appdata/`, and all 148 manifest rows have
`summary_file: null`, `ingested_at: null`, `row_count: null`.

**The correction:** "97% of file text blocks are empty" is true but reads as more damning than it
is. For an image, `_build_content_blocks` returns the raw image bytes, not an empty string:

```
src/content.py:575-576
    if ext in IMAGE_EXTS:
        return [BinaryContent(data=path.read_bytes(), media_type=IMAGE_EXTS[ext])]
```

The answering VLM **did** receive every retrieved receipt as a picture. The text block is empty
because the receipt was sent as an image instead — the model was not answering from nothing. What
is genuinely lost is everything *textual*: nothing to BM25 against, nothing to show the user,
nothing to fall back on when the VLM misreads a number.

### A concrete, measurable consequence: fusion collapsed to a single list

With only one retrieval list feeding RRF, every score degenerates to `1/(60+rank)`. The observed
distribution across all 262 hits is exactly that: `0.016393` (= 1/61) x 116, `0.016129` (= 1/62)
x 116, then a thin tail. **Scores carry zero confidence information** — rank 1 always scores
0.016393 whether the match is perfect or garbage. Any downstream logic that reads a score or a
score *margin* (the solo gate, any thresholding) is operating on a constant. With `MAGPIE_RERANK=0`
also in force this run, there is no second signal anywhere in the stack to break the tie. Observed
gold-in-top-2 was 88/120.

### What an ideal indexing pass should have produced for 148 receipt images

1. **What it did produce, and should keep:** 148 ColQwen2.5 page embeddings, ~1030 x 128-dim
   patch vectors each, int8-quantized with rescore, MaxSim-searchable. This is the right primitive
   for receipts and it ran flawlessly.
2. **A per-image text artifact — the actual gap.** Roughly 100-300 words per receipt: vendor,
   date, invoice/receipt number, total, tax, payment method, notable line items. 148 x ~3 s of
   local VLM time is a few minutes on this hardware — the same order as the ColPali pass that
   already ran. The machinery exists and is already wired for scanned PDFs
   (`transcript_for` / `transcript_path_for`, `src/content.py:540-556`); it simply is not invoked
   for images.
3. **That artifact ingested into the `summaries` collection**, so BM25 + dense retrieval runs
   alongside ColPali and RRF has two genuinely independent lists to fuse. Exact-token queries
   ("CS00032256", "PEGIV-1030531") are precisely where lexical search beats a page embedding, and
   receipts are full of such tokens.
4. **Real summary text on every `SearchResult`,** replacing `"(visual match — page N)"`. This is
   the citation surface the user reads; today it is a string that tells them nothing about why the
   file matched.
5. **Content hashes in the manifest,** so byte-identical files are detected at index time instead
   of requiring an out-of-band dedup pass.

**What was lost, in one line each:**

- *Retrieval text* — no lexical/BM25 signal at all; RRF fused one list with itself, and every
  score is a rank constant.
- *Citation surface* — 100% of hits show `(visual match — page N)`; the user gets no evidence for
  any answer.
- *Answer context* — the VLM sees pixels only, with no text scaffold to anchor or cross-check a
  misread figure. `rcpt-a-01` is the clean demonstration: right file at rank 1, number plainly
  legible, answer still wrong. A one-line summary carrying `total: 269.40` would very likely have
  saved it.

---

## 6. Supervisor claims — adjudicated

| # | Claim | Verdict |
|---|---|---|
| 1 | Summary tier indexed nothing despite `index_summary_tier: true`; only the fast tier ran (148 files, ~428 s, ~2.9 s/file) | **Confirmed.** 148 files, 411 s fast-tier, 2.78 s/file measured. Cause refined: tier mutual exclusion (`skip_fast_tier=True`), **not** an unsupported extension — `.jpg` is in `SUPPORTED_EXTS`. |
| 2 | 97% of answer-prompt file text blocks empty; every hit's summary is `"(visual match - page N)"` | **Confirmed with a correction.** The placeholder is universal (262/262 hits, `search.py:553` — not `:552`). But images are attached as `BinaryContent`, so the VLM did receive the receipt pixels; the loss is textual grounding, not total absence of context. |
| 3 | Corpus deduped 150 -> 148 this session (two byte-identical pairs) | **Confirmed.** Dataset manifest documents both pairs; both twins are absent from corpus and index. Worth noting the indexer could not have caught them itself — change detection is size-only and `content_hash` is never written. |

## 7. Recommendations, in priority order

1. **Give image-only corpora a text tier.** Route images to a VLM transcription pass that writes a
   summary and ingests it into `summaries`. This is the one change that fixes retrieval text,
   citation surface, and answer grounding at once. Until then, `index_summary_tier: true` is
   silently meaningless for any image corpus and the eval config is misleading about what ran.
2. **Fix the exit path.** Replace `sys.exit()` at `src/stage1/summarize.py:796` with a return value
   or a typed exception, and distinguish "no supported files" from "all files routed to the fast
   tier." Remove the string-match in `eval_harness/harness/worker.py:186` and fix its stale
   `:603` line reference. Today a benign condition also silently kills `ingest_from_manifest` and
   the tier-timing report.
3. **Don't start the local LLM server for a tier with no work.** ~15 s per run wasted here; on a
   larger eval matrix it compounds.
4. **Populate `content_hash` at index time** so duplicate detection stops depending on an
   out-of-band curation step.
5. **Golden-set note (low severity):** `receipt_X51005447844.jpg` has a cropped right column. The
   currently-asked fact survives; don't author line-item questions against it.
