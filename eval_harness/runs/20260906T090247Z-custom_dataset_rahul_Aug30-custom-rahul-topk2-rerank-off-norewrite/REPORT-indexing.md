# INDEXING REPORT

**Run:** `20260906T090247Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
**Dataset:** `custom_dataset_rahul_Aug30` — 545 files, 15 categories
**Index:** MOUNTED, not built. Store `eval_harness/indexes/66974090bdcd62e6/`

---

## 0. Framing: this run built nothing

`run.json` → `index_store: {key: "66974090bdcd62e6", hit: true, built_under_sha: "cca67570..."}`.
`eval_harness/indexes/66974090bdcd62e6/meta.json` says the store was built
`20260830T095758Z` by run `20260830T095758Z-custom_dataset_rahul_Aug30-...` under backend
`cca67570b04adce9980575d367f3cb9a6836a800`.

`eval_harness/harness/run.py:175-199` copies `store/appdata` and `store/qdrant` into
`raw/`, stamps the mount, and calls `progress.phase_done(raw, "index", note="mounted from
store")`. No indexing code executes. This is visible in the run's own artifacts:

- `raw/qdrant.log` (762 lines) contains **zero** `PUT /collections/fast_tier/points`
  requests. Every logged request is `GET .../exists` or `POST .../points/query`, all HTTP
  200. (The strings `400` and `404` at log lines 124 and 136 are *response byte counts* on
  200 responses, not status codes.)
- `raw/` has no `worker_index_payload.json` / `worker_index_result.json` /
  `worker_index.log` — the Aug-30 run dir has all three.
- `run.json` `phases` has only `answer` and `retrieve`. There is no `phases.index`.
- `raw/appdata/manifest.json` and `raw/appdata/logs/llm-2026-08-30T10-40-06Z.log` are dated
  **Aug 30**, byte-identical to the store copies. The mount carries the old build's LLM log
  into this run's appdata alongside this run's own `llm-2026-09-06T09-03-12Z.log`.

**Consequence for this report.** Everything below about *what is in the index* is verified
against artifacts this run carries. Everything about *why files are missing* had to be
verified elsewhere, because this run recorded no index-time evidence at all. Where I say
VERIFIED-HERE I mean this run's `raw/`; where I say VERIFIED-INDEPENDENTLY I mean I
reproduced the mechanism myself today, from the corpus files and the same model/Qdrant
version; where I say INHERITED I am relying on the Aug-30 run's artifacts.

---

## 1. Is mounting across a backend-SHA change sound here?

The supervisor's reading is **CONFIRMED**, and I can put a stronger boundary on it.

`git diff cca67570b04adce9980575d367f3cb9a6836a800..HEAD -- src/` touches 15 files,
1902 insertions / 63 deletions:

```
src/answer.py                        src/inference/gguf_meta.py
src/drift/__init__.py                src/inference/image_tokens.py
src/drift/__main__.py                src/inference/llama_server_pool.py
src/drift/oracles.py                 src/inference/local_llm.py
src/drift/pins.py                    src/inference/model_downloader.py
src/drift/provenance.py              src/inference/profiles.py
src/drift/tripwire.py                src/server.py
                                     src/tools/install_llama_server.py
```

**No indexing-path file changed.** `src/stage1_fast/index.py`, `src/stage1_fast/model.py`,
`src/stage1_fast/device.py`, `src/stage1_fast/router.py`, `src/stage2/fast_db.py`,
`src/stage2/db.py`, `src/manifest.py`, `src/ingest/walker.py`, `src/pipeline.py` and
`src/stage2/search.py` are all byte-identical between `cca67570` and HEAD.

The decisive test is not "did any indexing file change" but "can the query encoder still
read these vectors". The stored vectors come from
`stage1_fast/model.encode_images` → `device.detect_device`; the query vectors come from
`stage1_fast/model.encode_queries` → the same `device.detect_device`. I computed the import
closure of `{stage1_fast.model, stage2.fast_db}` and intersected it with the changed set:
**empty**. Query-side and index-side encoders are the same unchanged code, on the same
resolved family (`provenance.col_model = colqwen2_5 / mps / float16` in `run.json`, matching
`col_model_resolved: "colqwen2_5"` in the Aug-30 `run.json`). Mounting is sound.

Two caveats worth recording:

1. `src/stage1_fast/index.py:40` does `from src.ingest.walker import find_candidates`, and
   `src/ingest/walker.py:33` imports `src.ingest.tier0..tier4` at module level, which
   transitively pulls `src.answer` and the whole `src.inference` stack — all of which *did*
   change. Those modules are imported but never called on the embedding path
   (`_render_pages` → `encode_images` → `upsert_pages_batch`), so the only residual exposure
   is import-time side effects. For *this* run it is moot: no indexing code ran at all.
2. The store's summary tier was produced by code that has since changed
   (`inference/profiles.py`, `inference/local_llm.py`). That would matter if the summary
   tier held anything. It does not — see §5.1.

---

## 2. What is actually in the index

I booted Qdrant 1.17.1 (`/Applications/Magpie.app/Contents/MacOS/qdrant`, the same version
the run logs) against a **copy** of `eval_harness/indexes/66974090bdcd62e6/qdrant/` and
scrolled every point. VERIFIED-HERE.

| | |
|---|---|
| Collections | **1** — `fast_tier`. No `summaries` collection exists. |
| Points (pages) | **709** |
| Distinct `source_path` (files) | **520** |
| Files on disk | **545** |
| Pages on disk | **764** |
| **Files missing** | **25 (4.6%)** |
| **Pages missing** | **55 (7.2%)** |
| Collection status | `green`, `indexed_vectors_count: 684`, `segments_count: 5` |

Per-category coverage (files indexed / files on disk, pages indexed / pages on disk):

| category | files on disk | files indexed | pages on disk | pages indexed | lost |
|---|---:|---:|---:|---:|---|
| charts | 40 | 40 | 40 | 40 | — |
| diagrams | 40 | 40 | 40 | 40 | — |
| documents | 53 | 53 | 53 | 53 | — |
| figures | 40 | 40 | 40 | 40 | — |
| infographics | 40 | 40 | 40 | 40 | — |
| **notes_handwritten** | **37** | **23** | **37** | **23** | **14 files / 14 pages** |
| notes_iam | 30 | 30 | 30 | 30 | — |
| photos | 40 | 40 | 40 | 40 | — |
| receipts_degraded | 36 | 36 | 36 | 36 | — |
| **receipts_phone** | **40** | **31** | **40** | **31** | **9 files / 9 pages** |
| **scans_multipage** | **19** | **17** | **140** | **108** | **2 files / 32 pages** |
| scene_text | 40 | 40 | 40 | 40 | — |
| screenshots | 40 | 40 | 40 | 40 | — |
| slides | 30 | 30 | 128 | 128 | — |
| tables_fr | 20 | 20 | 20 | 20 | — |
| **TOTAL** | **545** | **520** | **764** | **709** | **25 / 55** |

The loss is concentrated in three categories. Twelve categories are complete.

**Integrity of what *is* there is perfect.** Cross-checking Qdrant against
`indexes/66974090bdcd62e6/appdata/manifest.json` and against the files on disk:

- Qdrant's 520 `source_path` values are set-equal to the manifest's 520 keys.
- For every file, `manifest.fast_pages == len(points)`: **0 mismatches**.
- Every file's `page_num` set is exactly `0..n-1`, contiguous: **0 anomalies**.
- Indexed page count equals the true `pymupdf` page count for all 86 PDFs and equals 1 for
  every raster file: **0 mismatches**.
- **0 zombies** — no indexed path is absent from the manifest or from disk.
- Sampled vectors: `dim=128`, every component finite, every patch vector L2-normalised to
  exactly 1.000.

The manifest is a *record of successes only*: `index.py:141` calls
`manifest.mark_fast_indexed` **after** the upsert returns, so a failed file leaves no row.
`raw/appdata/manifest.json` therefore has 520 entries, all with a non-null
`fast_indexed_at`, and **contains no trace whatsoever of the 25 failures**. `run.json`'s
`dataset_manifest_files: 545` is the dataset's declared count, not the indexed count; the
two differ by 25 and nothing in this run flags it.

---

## 3. Per-file indexing failures and root cause

### 3.1 What this run records: nothing

There is no index-error evidence in this run's artifacts, because there was no index phase.
This is the whole point of the section: **a run can mount a defective store and emit an
apparently clean `errors: 0` record.** `run.json` reports `phases.answer.errors: 0`,
`phases.retrieve.errors: 0`, `status: "complete"`, `metrics.json` reports `errors: 0`.
Nothing in either file says 25 source documents are absent.

### 3.2 What the build run records (INHERITED, from Aug-30 artifacts)

`runs/20260830T095758Z-.../raw/worker_index.log` ends with:

```
fast tier: 520 files indexed (709 pages), 0 unchanged, 0 pruned, 25 errors
```

and enumerates all 25. Two distinct error strings:

- **24 files** — `UnexpectedResponse: 400 (Bad Request)`,
  `{"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum VectorStruct"}}`
- **1 file** (`scans_multipage/scan_nglg0227.pdf`) —
  `{"status":{"error":"Payload error: JSON payload (33600110 bytes) is larger than allowed (limit: 33554432 bytes)."}}`

That run's `run.json` `phases.index` records only `wall_s`, `manifest_entries: 520` and
`summary_tier_note`. **The error count is not in any structured artifact anywhere** — it
exists only as printed text in a log. `worker.py:phase_index` (lines 165-226) returns
`{corpus_dir, wall_s, summary_tier_note, manifest_path, manifest, col_model_resolved}`;
there is no error field to return, because `stage1_fast/index.py:run_fast_batch` collects
errors into a local list, prints them, and returns `None`.

### 3.3 Root causes — VERIFIED INDEPENDENTLY, today

I did not take the prior investigation's word for any of this. Three separate
reproductions:

**(a) ColQwen2.5 under float16 on MPS emits all-NaN embeddings — CONFIRMED, and stronger
than claimed.**

`src/stage1_fast/device.py:240-246` selects `dtype="float16"` for ColQwen2.5 on MPS
(comment: "MPS bfloat16 support is patchy"). `model.py:110-124` runs the forward pass with
no finiteness check; `index.py:133` does `tensor.float().cpu().tolist()` and ships it.

I re-encoded **all 25 failed files** plus a 30-file control sample through the exact
production path (`src.stage1_fast.model.encode_images` + `src.stage1_fast.index._render_pages`,
`DeviceConfig(device='mps', model_id='vidore/colqwen2.5-v0.2', dtype='float16', batch_size=2)`):

- **All 24 VectorStruct-failing files reproduce NaN**, deterministically, at
  `isnan().mean() == 1.0` — the *entire* page embedding, not a few components.
- `scan_nglg0227.pdf` (the size failure) reproduces **0.0 NaN on all 20 pages** — a cleanly
  separated second failure mode, exactly as the two distinct error strings imply.
- **0 of 30 control files** (2 sampled per category, all currently indexed) show any NaN;
  all have mean patch norm 1.000.
- Re-encoding two of the failures in **float32 on CPU** with the same weights gives
  `nanfrac = 0.0000`, `absmax ≈ 0.39`. The input images are fine; **float16 is the cause.**

It is not size-dependent: `receipt_011.jpg` (864×1296) is 100% NaN while `receipt_001.jpg`
(864×1296, same dimensions) is clean. It is content-dependent and silent.

**Correction to the inherited account:** the claim that "NaN serializes to bare `NaN` which
is invalid JSON" is **wrong in mechanism**. `qdrant_client` builds the upsert body with
pydantic's `jsonable_encoder`, which renders a non-finite float as **`null`**, not `NaN`. I
captured the actual request bytes:

```
b'{"points":[{"id":"...","vector":[[null,1.0],[2.0,3.0]],"payload":{...}}]}'
```

The JSON is well-formed; Qdrant rejects it because `null` is not an `f32`. The outcome is
identical, but anyone fixing this by reaching for `allow_nan=False` in `json.dumps` would be
patching a code path that is not involved.

**(b) The Qdrant error strings — CONFIRMED byte-for-byte.** I stood up a scratch Qdrant
1.17.1 with the same collection config as `fast_db.ensure_fast_collection` and upserted
probes:

| probe | server response |
|---|---|
| clean vector | OK |
| NaN in vector | `Format error in JSON body: data did not match any variant of untagged enum VectorStruct` |
| all-NaN page | *(same string)* |
| ±inf in vector | *(same string)* |
| **wrong dimension** | `Wrong input: Vector dimension error: expected dim: 4, got 3` |
| >32 MiB body | `Payload error: JSON payload (123425866 bytes) is larger than allowed (limit: 33554432 bytes).` |

The distinct dimension-error string **rules out** a dim mismatch as an alternative
explanation for the 24. The only residual ambiguity is NaN vs ±inf — Qdrant gives the same
message for both — and the direct re-encode settles it: NaN.

**(c) One upsert per FILE, so one bad page destroys the whole document — CONFIRMED in code
and observed in the data.**

`src/stage1_fast/index.py:124-142` accumulates every page of a file into
`pages_to_upsert` and issues a single `upsert_pages_batch(pages_to_upsert)` at line 139
("One upsert call per file; small + amortizes network cost vs per-page"). Qdrant validates
the whole body; one bad vector rejects all of it.

The empirical proof is `scans_multipage/scan_zxjd0228.pdf`: 12 pages, of which my re-encode
finds **exactly one** NaN page — page index 8 — and eleven clean ones. All 12 pages are
absent from the index. **11 perfectly good pages were destroyed by 1 bad one.** Of the 55
lost pages, 41 (74%) are collateral: they encode cleanly and would have indexed fine under
per-page upserts.

**(d) The 32 MiB body cap — CONFIRMED, and it is the same architectural cause.**

`scan_nglg0227.pdf` is 20 pages. At ~1030 ColQwen patches × 128 float32 dims rendered as
JSON text, that is ~1.68 MB/page → 33,600,110 bytes, 45 KB over Qdrant's 33,554,432-byte
default. The boundary is tight and observable: `scan_yscw0217.pdf` and `scan_xqgl0226.pdf`,
both **18** pages, indexed successfully. Under a per-page upsert this file would also have
indexed fine. Both failure modes are the same design decision.

**(e) The error is swallowed and the run still exits 0 — CONFIRMED.**
`index.py:188-203` wraps `index_file` in `except Exception`, appends to a local list, and
continues; `run_fast_batch` returns `None`. `worker.py:phase_index` has nothing to inspect.
`run.py:255` gates only on `manifest_entries == 0` (rule #106). 520 > 0, so the Aug-30 run
reported `status: "complete"`, and `run.py:363-383` then **published the defective index to
the shared store** as the authoritative artifact for key `66974090bdcd62e6`. Every
subsequent run against these index-side params — including this one — silently inherits it.

### 3.4 The 25 files

| # | file | pages lost | cause |
|---|---|---:|---|
| 1-7 | `notes_handwritten/CseGyan-Cpp-Notes-{2,8,9,17,18,19,20}.pdf` | 1 each | fp16 NaN |
| 8-14 | `notes_handwritten/electric-charge-and-field-{3,8,9,11,13,16,17}.pdf` | 1 each | fp16 NaN |
| 15-23 | `receipts_phone/receipt_{006,011,012,015,016,029,031,037,040}.jpg` | 1 each | fp16 NaN |
| 24 | `scans_multipage/scan_zxjd0228.pdf` | **12** (1 NaN + 11 collateral) | fp16 NaN + per-file upsert |
| 25 | `scans_multipage/scan_nglg0227.pdf` | **20** (0 NaN) | 32 MiB body cap + per-file upsert |

---

## 4. Downstream impact

### 4.1 Golden items that lost their gold source

Cross-checking the 25 dropped files against `datasets/custom_dataset_rahul_Aug30/golden.json`:
the golden set cites **62 distinct gold files**, of which **5 are absent from the index**.

**6 of 120 golden items (5.0%) are structurally unanswerable** — every gold source gone, no
`acceptable_sources` fallback:

| item | difficulty | gold_sources (all missing) | verdict in this run |
|---|---|---|---|
| `rcpt-07-typed` | hard | `receipt_040.jpg` | `false_abstain` |
| `rcpt-07-full` | hard | `receipt_040.jpg` | `false_abstain` |
| `study-05-typed` | medium | `electric-charge-and-field-9.pdf` | `wrong` |
| `study-05-full` | medium | `electric-charge-and-field-9.pdf` | `wrong` |
| `study-10-typed` | hard | `CseGyan-Cpp-Notes-{17,18,19}.pdf` | `wrong` |
| `study-10-full` | hard | `CseGyan-Cpp-Notes-{17,18,19}.pdf` | `wrong` |

No item is *partially* affected — every affected item lost 100% of its gold.
`scan_nglg0227.pdf` and `scan_zxjd0228.pdf`, the two largest losses by page count, carry no
golden items, so 32 of the 55 lost pages are invisible to the eval.

### 4.2 The index defect accounts for essentially all retrieval failure

Recomputed with the harness's own `harness/metrics.py` over `raw/retrieve.jsonl`
(n=104 scoreable items; the other 16 are `not_found`):

- **hit@1 = 97/104 = 0.9327** — exactly matches `metrics.json`. **7 misses.** Six are the
  index-dropped items above. Only **one** (`rcpt-05-typed`, gold `bad_receipt_014.jpg`) is a
  genuine retriever miss. **86% of rank-1 retrieval failure is the index, not the retriever.**
- **hit@12 = 98/104 = 0.9423.** The misses at k=12 are **exactly the 6 index-dropped items,
  and nothing else.** Every item whose gold is in the index is found within 12. The ceiling
  imposed by the index is `(104-6)/104 = 0.9423` and the system hits it precisely. There is
  **zero** headroom left for retrieval tuning at k=12 on this dataset.

Per-category hit@1 makes the attribution visible:

| category | hit@1 | n | note |
|---|---:|---:|---|
| notes_handwritten | 0.60 | 10 | 4 misses = 4 items with dropped gold; 6/6 answerable items hit |
| receipts_phone | 0.80 | 10 | 2 misses = 2 items with dropped gold; 8/8 answerable items hit |
| receipts_degraded | 0.88 | 8 | the one genuine miss |
| all other categories | 1.00 | — | |

Both "weak" categories are weak *only* because of indexing. Excluding the 6 dead items,
retrieval is 97/98 = 0.990.

### 4.3 The downstream failure is silent and the judge mis-attributes it

The system does not signal "I have no such document". From `raw/answers.jsonl`:

- `study-05-typed` — gold page absent — answers **confidently and with no citation** from a
  *different* page of the same notebook: *"The electric field lines follow some intrinsic
  properties: (i) field lines start from the charges and end at -ve charge..."*. The
  question asked about torque.
- `study-10-typed` — cites `Notes-14.pdf` and `Notes-15.pdf` (the operator pages) instead of
  the absent type-casting pages, and emits the degenerate answer `"C++ Tutorials[1], C++
  Tutorials[2]"`.
- `rcpt-07-*` — empty answer, no citation, scored `false_abstain`.

The judge then blames the model. From `judge_verdicts.json`:

> `study-05-full`: *"electric-charge-and-field-9.pdf marks 180 degrees unstable and 90
> degrees as tau_max = PE; the answer says unstable at 90 degrees, contradicting the page."*

The judge is comparing the answer against a page **the system was never able to see**, and
recording a reasoning failure. Four `wrong` and two `false_abstain` verdicts in this run are
mis-attributed: they are index defects wearing an answer-quality label. Any reader of
`JUDGE-REPORT.md` who does not also read this report will draw the wrong conclusion about
where to spend effort.

### 4.4 How much of the defect this eval can observe

Poorly, and this is worth stating plainly:

| | |
|---|---|
| Files dropped | 25 |
| Files dropped that carry a golden item | **5 (20%)** |
| Pages dropped | 55 |
| Pages dropped that carry a golden item | **5 (9%)** |
| Golden items affected | 6 / 120 (5%) |

**91% of the lost pages are invisible to this eval.** The eval sees a 5% dent; the product
lost 4.6% of the user's documents and 7.2% of their pages. A user who owns
`scan_nglg0227.pdf` has a 20-page document that Magpie will never find, and Magpie will
never say so. Do not read "5% of golden items affected" as the size of the defect.

---

## 5. Anything else in the index that would poison downstream answers

### 5.1 The summary tier is empty, and nothing says so loudly

`run.json` `params.index_summary_tier: true`. The store has **one** collection, `fast_tier`.
`raw/qdrant.log` line 24 shows `GET /collections/summaries/exists → 200` at startup; the
collection does not exist. The Aug-30 `run.json` explains why:

```json
"summary_tier_note": "no supported files found under .../custom_dataset_rahul_Aug30/corpus"
```

Every one of the 545 files routes to the fast tier, so `src/stage1/summarize.py:603`
`sys.exit()`s and `worker.py:194-200` absorbs it as benign. That is the correct call for an
all-image corpus. But the consequence is that **100% of retrieval on this dataset is
single-tier ColQwen visual matching** — no text summaries, no keyword tier, no lexical
fallback. `index_summary_tier: true` in `run.json` describes a parameter that produced
nothing, and a reader comparing this run to a text-corpus run will not see that from the
params block alone. This is worth a note next to the param, not just in the Aug-30 log.

### 5.2 The index carries 31 byte-identical duplicate points

SHA-256 over the corpus: **514 distinct contents across 545 files.** All 31 duplicates are
in `diagrams/`, in 8 groups:

| copies | files |
|---:|---|
| 9× | `diagram_003` … `diagram_011` |
| 8× | `diagram_028` … `diagram_035` |
| 6× | `diagram_022` … `diagram_027` |
| 5× | `diagram_036` … `diagram_040` |
| 4× | `diagram_014` … `diagram_017` |
| 3× | `diagram_019` … `diagram_021` |
| 2× | `diagram_012`, `diagram_013` |
| 2× | `diagram_001`, `diagram_002` |

The `diagrams` category is 40 files but only **9 distinct images**. The indexer faithfully
created 40 points with (up to) 9 distinct vectors. This is a corpus defect, not an indexer
defect — but the index propagates it, and at `top_k=2` it wastes retrieval slots:

- `viz-11-typed` top-2 = `diagram_004.jpg`, `diagram_011.jpg` — **byte-identical files.**
- `viz-11-full` top-2 = `diagram_007.jpg`, `diagram_011.jpg` — **byte-identical files.**

Both queries deliver the generator *one* picture in *two* slots. The k=2 budget is
effectively k=1 for any query landing in a duplicate cluster. (The golden set already
handles the scoring side correctly — `viz-11` lists the 8 twins in `acceptable_sources`, so
the metric is not corrupted. The wasted generation context is not compensated anywhere.)

`index.py`'s point ID is `md5(source_path::page:N)`, so identical content under different
filenames cannot dedupe. A content-hash-keyed dedupe (or a `content_hash` payload field —
the manifest already has a `content_hash` slot, unused and `null` for all 520 entries) would
collapse these.

### 5.3 Patch counts vary 8.5× and bias MaxSim ranking

ColQwen2.5 uses dynamic resolution and does not upscale, so patch count tracks source pixel
dimensions. Across the 709 points: **min 91, median 747, max 779**, with 87 pages below 300
patches.

| category | pages | min | median | max |
|---|---:|---:|---:|---:|
| **diagrams** | 40 | **91** | **245** | 759 |
| **charts** | 40 | **95** | **251** | 739 |
| **photos** | 40 | **191** | **245** | 335 |
| figures | 40 | 146 | 739 | 770 |
| tables_fr | 20 | 179 | 752 | 771 |
| documents / slides / scans | 289 | 731 | 755 | 771 |

Qdrant's `MAX_SIM` comparator sums, over query tokens, the max similarity against *any*
document patch. More patches = more chances to score a high max per query token, independent
of content. I measured the bias directly: 12 trials of 20 random unit query vectors, top-10
each (120 winners):

- Pages with ≥731 patches are **76.9%** of the corpus but **96.7%** of random-query winners.
- Every single random winner had ≥572 patches; the 87 sub-300-patch pages won **zero** slots.

This is a structural handicap on `diagrams`, `charts` and `photos` — 120 files, and the
categories carrying 20 golden items. It compounds a fidelity problem: a chart at 95 patches
(a ~10×10 grid over the whole image) cannot resolve axis labels. `chart_014.jpg` gets 95
patches; `chart_001.jpg` gets 641. Items like `viz-01`, which requires reading "18.81" off a
bar label, depend on which side of that spread the file lands.

This run's data does not isolate the effect (charts hit@1 = 1.00), but `viz-11` is
suggestive: gold `diagram_003.jpg` (305 patches) ranked 4th and 7th behind other diagrams —
though in that case the winners were its own byte-identical twins, so content-wise it did
retrieve correctly.

### 5.4 `page_num` is 0-based and is surfaced to the user un-incremented

`src/stage2/search.py:553` builds the result summary as:

```python
summary=f"(visual match — page {page})"
```

using the raw `page_num` from the Qdrant payload, which `index.py:135` writes 0-based. I
confirmed the offset visually: page_num 3 of `scans_multipage/scan_gzyh0227.pdf` renders a
UCSF water-analysis form whose own printed footer reads **"- 2 -"**, and which a human would
call page 4. **Every multi-page citation the product emits is off by one.** This affects the
236 indexed pages in `scans_multipage` (108) and `slides` (128).

Related, from the same function (`search.py:545-551`): `best_by_path` collapses all matching
pages of a file to the single highest-scoring one. A multi-page PDF can contribute **at most
one page** to any answer, regardless of how many pages are relevant. For a corpus where
`scans_multipage` averages 6.4 pages/file, that is a real ceiling on multi-page synthesis
questions.

### 5.5 What is *not* wrong — checks that came back clean

Ruled out by direct measurement, so nobody re-investigates them:

- **Render fidelity.** All 86 PDFs, all 305 pages: `pix.alpha == False`, `pix.n == 3`,
  `pix.stride == width*3` on every page. `index.py:58`'s
  `Image.frombytes("RGB", (w,h), pix.samples)` — which would shear the image under stride
  padding or misread an alpha channel — is safe on this corpus. **0 anomalies.**
- **EXIF orientation.** `index.py:64` uses `Image.open(path).convert("RGB")`, which ignores
  EXIF orientation. I checked all 459 raster files: **0** carry a non-trivial Orientation
  tag. (This is latent — a real phone-camera corpus would trip it — but it did not fire here.)
- **Colour mode.** 429 RGB, 30 grayscale (`L`); `convert("RGB")` handles the latter cleanly.
- **Content faithfulness.** I rendered pages through the indexer's own `_render_pages` and
  read them, sampling across categories. All faithful to the source and to the golden set:
  `chart_001.jpg` shows exactly the 14 commodities with Cocoa at 18.81 and Lamb at 103.7
  (matching `viz-01`'s golden answer); `diagram_003.jpg` shows leopard seal, elephant seal
  and "other seals" (matching `viz-11`'s golden answer verbatim); `table_fr_011.jpg` is the
  KLM Cargo revenue table; `note_002.png` is exactly the incoherent IAM sentence-strip the
  owner's `_notes.notes_iam_excluded` describes.
- **Distractor pressure from `notes_iam` is negligible.** The 30 IAM strips are 5.8% of the
  index but take **0.4%** of top-2 slots (1 of 240) across all 120 queries, and appear in
  top-12 for only 10 of 120 queries. The "pure distractor pressure" slice is behaving as
  designed and is not poisoning anything.
- **The mount is not stale.** Every one of the 520 manifest `size` values still matches the
  file on disk (**0 mismatches**), and the newest mtime anywhere in the corpus is
  `2026-08-30T04:44:10`, five hours before the store was built. *This is luck, not
  engineering* — see §6.3.

---

## 6. Recommendations for the harness

### 6.1 A nonzero index error count MUST fail the run — yes, unambiguously

The current gate is `run.py:255`: fail only if `manifest_entries == 0` (rule #106). That
catches "indexed nothing" and misses "indexed 95.4% of the corpus and published it as
authoritative". The Aug-30 build dropped 25 files, exited 0, printed `status: "complete"`,
and `run.py:363-383` wrote it into the shared store — from where it has now been mounted by
at least three subsequent runs, each reporting `errors: 0`.

Three changes, in dependency order:

1. **Make the error count structured data.** `stage1_fast/index.py:run_fast_batch` currently
   returns `None`; it must return `(indexed, skipped, pruned, errors)` — or the harness must
   parse its own worker's output — so `worker.py:phase_index` can return
   `index_errors: [{path, error_class, message}]` and `run.py` can put
   `phases.index.errors` in `run.json`. Right now the only record of the 25 failures is
   unstructured text in a log file, which is why this defect survived three runs. *(Note:
   this touches `src/`, so it is a product change, not a harness-only one. It is the
   load-bearing one — everything below is unenforceable without it.)*
2. **Hard-fail the run on `index_errors > 0`,** with `--allow-index-errors N` for a
   deliberate, recorded tolerance. A partial index makes every downstream metric a lower
   bound of unknown depth; publishing it as a comparable measurement is worse than not
   measuring.
3. **Never publish a store with errors.** `run.py:363` gates publication on
   `manifest_entries > 0`; it should also require `index_errors == 0`. Publication is what
   turned a one-run failure into a durable, silently-inherited artifact.

Interim, and cheap: `run.py` already has `dataset_manifest_files` (545) and, after an index
phase, `manifest_entries` (520). Comparing those two numbers would have caught this on
Aug 30 with a three-line change, and would catch it on a *mount* too — which matters,
because on a mount there is no index phase to instrument.

### 6.2 Mounting across a backend-SHA change: warn is right, hard-fail is wrong — but the warning is too weak

`run.py:191-197` prints a stderr warning on SHA drift and records `built_under_sha` in
`run.json`. Hard-failing would be wrong: the index key is params-only *by design*
(`run.py:44-51`) so routine commits do not invalidate a 42-minute build, and this run is the
proof — 15 files changed, none of them on the vector path, and the mount was entirely sound.
A hard fail would have forced a needless 2514-second rebuild and, worse, trained everyone to
pass `--rebuild-index` reflexively.

But the current warning is a `print(..., file=sys.stderr)` that scrolls past and lands in no
artifact. Make the check *precise* instead of *loud*:

- **Gate on the indexing path, not on `src/`.** `run.py` can run
  `git diff --name-only <built_under_sha>..HEAD -- src/stage1_fast/ src/stage2/fast_db.py
  src/stage2/db.py src/manifest.py src/ingest/walker.py src/pipeline.py`. Empty → mount
  silently. Non-empty → **that** is a hard fail (or an explicit `--force-mount`), because a
  changed encoder means the stored vectors are not readable by the query encoder. Today the
  two cases produce the identical, ignorable warning.
- **Record the verdict.** Put `index_store.backend_drift: {changed_indexing_files: [...]}` in
  `run.json` so a reader of the run — or `compare.py` — can see it without the console.

### 6.3 Two smaller gaps found along the way

- **The store meta does not record the resolved retriever family.** `run.py:44-51` comments
  that "the RESOLVED family additionally lands in run.json and the index store meta", but
  the meta write at `run.py:375` uses `{k: params.get(k) for k in INDEX_SIDE_PARAMS}`, so
  `meta.json` records `"col_model": "auto"` — the *request*, not the resolution. Meanwhile
  `worker.py:phase_index` **does** compute `col_model_resolved: "colqwen2_5"` and `run.py:243`
  stamps it into the build run's `run.json`. So the information exists and is simply not
  carried into the portable artifact. The consequence is exactly the failure the comment
  claims to prevent: a machine resolving `auto` → ColSmol computes the *same* index key
  `66974090bdcd62e6`, mounts this ColQwen store, and queries 128-dim ColQwen vectors with a
  ColSmol encoder — incompatible vectors, no error, garbage rankings. One line:
  `"col_model_resolved": run_record.get("col_model_resolved")` in the meta payload, and a
  mount-time assertion against `detect_device().model_family`. (On a mount there is no index
  phase, so `run.json` gets `col_model_resolved: None` — as it does here; the family survives
  only incidentally, via `provenance.col_model.family`.)
- **The index key has no corpus content hash.** `index_params_hash` (`run.py:55-57`) hashes
  `{dataset_name, model_config, index_fast_tier, index_summary_tier, local_n_ctx,
  col_model}`. Edit a corpus file and the key is unchanged, so the run mounts a stale index
  and never notices. I verified by hand that this corpus has not drifted (§5.5) — but the
  harness did not, and could not. `meta.json` should carry a manifest digest
  (path + size + mtime over the corpus) and the mount should compare it, warn on drift, and
  offer `--rebuild-index`.

---

## Appendix: evidence index

| claim | source |
|---|---|
| Mount, no index phase | `run.json` `index_store.hit`, `phases` (no `index`); `raw/qdrant.log` (no upserts); absence of `raw/worker_index.*` |
| Store provenance | `eval_harness/indexes/66974090bdcd62e6/meta.json` |
| 520 files / 709 points / 1 collection | live scroll of a copy of `indexes/66974090bdcd62e6/qdrant/` on Qdrant 1.17.1 |
| 545 files / 764 pages on disk | `find` + `pymupdf` over `datasets/custom_dataset_rahul_Aug30/corpus/` |
| 25 errors, both error strings | `runs/20260830T095758Z-.../raw/worker_index.log` (INHERITED) |
| fp16 NaN on all 24, none on the 25th, none in 30 controls, none in fp32 | independent re-encode via `src.stage1_fast.model.encode_images`, this machine, today |
| Qdrant error strings for NaN / inf / wrong-dim / oversize | scratch Qdrant 1.17.1, same collection config as `src/stage2/fast_db.py` |
| `null` (not bare `NaN`) on the wire | captured `httpx` request body from `qdrant_client`'s own `jsonable_encoder` |
| One upsert per file | `src/stage1_fast/index.py:139`; `scan_zxjd0228.pdf` = 1 NaN page of 12, all 12 absent |
| float16 on MPS | `src/stage1_fast/device.py:240-246`; `run.json` `provenance.col_model.dtype` |
| Errors swallowed, run exits 0 | `src/stage1_fast/index.py:188-215`; `harness/worker.py:165-226`; `harness/run.py:251-263` |
| Defective index published | `harness/run.py:363-383` |
| 6 dead golden items | `datasets/custom_dataset_rahul_Aug30/golden.json` × the 25 dropped files |
| hit@1 = 97/104, 7 misses, 6 index-caused; hit@12 misses = the 6 | `raw/retrieve.jsonl` scored with `harness/metrics.py` |
| Silent wrong answers, judge mis-attribution | `raw/answers.jsonl`, `judge_verdicts.json` |
| 31 byte-identical duplicates | SHA-256 over the corpus |
| MaxSim length bias | 12×20 random unit query vectors against the live `fast_tier` |
| Patch-count distribution | vector lengths of all 709 points |
| Render / EXIF / colour-mode checks clean | `pymupdf` + PIL over all 86 PDFs and 459 images |
| 0-based page in citations | `src/stage2/search.py:553` vs rendered `scan_gzyh0227.pdf` page 3 (printed "- 2 -") |
| Mount not stale | manifest `size` vs disk (0 mismatches); newest corpus mtime `2026-08-30T04:44:10` |
| No indexing code changed | `git diff cca67570..HEAD -- src/`; import-closure intersection |
