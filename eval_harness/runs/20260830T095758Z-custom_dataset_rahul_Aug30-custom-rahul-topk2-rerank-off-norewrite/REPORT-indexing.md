# REPORT — INDEXING

Run: `20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
Dataset: `custom_dataset_rahul_Aug30` (545 files, 15 categories, 100% visual)
Scope: index quality only. Retrieval ranking and answer correctness are owned by other agents.
Machine: Apple M1 Max, 64 GB unified, macOS 26.4.1, `device=mps dtype=float16 family=colqwen2_5 batch_size=2`.

Line numbers into `raw/worker_index.log` below refer to the file after `tr '\r' '\n'`
(the raw file is one long carriage-return-delimited tqdm stream).

---

## 0. Headline

| | |
|---|---|
| Files offered | 545 |
| Files indexed | **520** (95.4%) |
| **Pages** offered (PDFs expanded) | **764** |
| **Pages** indexed | **709** (92.8%) |
| Files lost | 25 (4.6%) |
| **Pages lost** | **55 (7.2%)** |
| Index phase wall | 2514.3 s (41 m 54 s) |
| Run status | `complete`, exit 0 |

The page-level loss (7.2%) is **56% larger than the file-level loss** (4.6%) that
`phases.index.manifest_entries` implies, because two of the casualties are a 20-page
and a 12-page PDF. Any statement of the form "we lost 25 of 545 files, 4.6%"
understates the content loss.

Three defects are established below. Two are index-time data loss; one is an
answer-time ceiling that makes correctly-indexed content unreadable.

---

## 1. What indexing produced

### 1.1 Volume

Every file in the corpus routes to the **fast tier** (ColQwen2.5 visual). The summary
tier ran and found nothing:

> `"summary_tier_note": "no supported files found under .../corpus"` — `run.json`, `raw/worker_index_result.json`

So there are **zero T3 LLM summaries and zero index-time vision transcripts** in this
run. I verified this three ways: all 520 manifest entries have `summary_file: null` and
`summarized_at: ""`; `raw/appdata/` contains no `transcripts/` or `summaries/`
directory (only `manifest.json`, `settings.json`, `indexing_rules.json`, `logs/`); and
`transcript_for()` returns `None` for all 86 PDFs.

Note the summary tier still paid startup cost before no-oping — it resolved
`LiquidAI/LFM2.5-VL-3B-GGUF`, spawned `llama-server` on port 9400, and loaded the model
(2.3 s) before discovering it had no supported files (`worker_index.log:1385-1388`).
Small, but it is wasted work that a file-type precheck would avoid.

### 1.2 Per-category outcome

`pages` = true page count, computed with `pdfinfo` over all 86 PDFs (images count as 1).

| category | ext mix | files | files indexed | files lost | pages | pages indexed | pages lost | % pages lost |
|---|---|---|---|---|---|---|---|---|
| charts | jpg×40 | 40 | 40 | 0 | 40 | 40 | 0 | 0.0% |
| diagrams | jpg×40 | 40 | 40 | 0 | 40 | 40 | 0 | 0.0% |
| documents | jpg×53 | 53 | 53 | 0 | 53 | 53 | 0 | 0.0% |
| figures | png×40 | 40 | 40 | 0 | 40 | 40 | 0 | 0.0% |
| infographics | jpg×40 | 40 | 40 | 0 | 40 | 40 | 0 | 0.0% |
| **notes_handwritten** | pdf×37 | 37 | 23 | **14** | 37 | 23 | **14** | **37.8%** |
| notes_iam | png×30 | 30 | 30 | 0 | 30 | 30 | 0 | 0.0% |
| photos | jpg×40 | 40 | 40 | 0 | 40 | 40 | 0 | 0.0% |
| receipts_degraded | jpg×36 | 36 | 36 | 0 | 36 | 36 | 0 | 0.0% |
| **receipts_phone** | jpg×40 | 40 | 31 | **9** | 40 | 31 | **9** | **22.5%** |
| **scans_multipage** | pdf×19 | 19 | 17 | **2** | 140 | 108 | **32** | **22.9%** |
| scene_text | jpg×40 | 40 | 40 | 0 | 40 | 40 | 0 | 0.0% |
| screenshots | jpg×40 | 40 | 40 | 0 | 40 | 40 | 0 | 0.0% |
| slides | pdf×30 | 30 | 30 | 0 | 128 | 128 | 0 | 0.0% |
| tables_fr | jpg×20 | 20 | 20 | 0 | 20 | 20 | 0 | 0.0% |
| **TOTAL** | | **545** | **520** | **25** | **764** | **709** | **55** | **7.2%** |

Indexed file types: 380 jpg, 70 png, 70 pdf.
`scans_multipage` loses only 2 of 19 files (10.5%) but **22.9% of its pages** — the two
casualties are the two largest PDFs in the corpus.

### 1.3 Timing and where it went

- Model load: ~10 s (826 + 506 weight shards, `worker_index.log:55-61`).
- Encode/upsert loop: **2490 s** (tqdm final elapsed).
- Phase total: 2514.3 s. The ~14 s residual is collection setup, manifest write and the
  summary-tier no-op.

Aggregate throughput: **0.219 files/s, 0.307 pages/s, 3.26 s/page** wall-averaged.

I measured the true steady-state cost by re-encoding representative files today on the
same machine and dtype: **2.52-2.64 s/page** for a full-page 755-patch render, uniform
across decks, scans and images. That is the reference against which the run's blocks
should be judged.

The corpus walk is alphabetical, so each category is a contiguous block. Block wall
time against the 2.56 s/page reference:

| category block | files | pages | wall s | s/page | expected @2.56 | ratio |
|---|---|---|---|---|---|---|
| charts | 40 | 40 | 66 | 1.65 | 102 | 0.64 |
| diagrams | 40 | 40 | 50 | 1.25 | 102 | 0.49 |
| documents | 53 | 53 | 147 | 2.77 | 136 | 1.08 |
| figures | 40 | 40 | 106 | 2.65 | 102 | 1.04 |
| infographics | 40 | 40 | 99 | 2.48 | 102 | 0.97 |
| notes_handwritten | 37 | 37 | 101 | 2.73 | 95 | 1.07 |
| notes_iam | 30 | 30 | 82 | 2.73 | 77 | 1.07 |
| photos | 40 | 40 | 38 | 0.95 | 102 | 0.37 |
| receipts_degraded | 36 | 36 | 101 | 2.81 | 92 | 1.10 |
| receipts_phone | 40 | 40 | 114 | 2.85 | 102 | 1.11 |
| scans_multipage | 19 | 140 | 407 | 2.91 | 358 | 1.14 |
| scene_text | 40 | 40 | 118 | 2.95 | 102 | 1.15 |
| screenshots | 40 | 40 | 106 | 2.65 | 102 | 1.04 |
| **slides** | 30 | **128** | **894** | **6.98** | 328 | **2.73** |
| tables_fr | 20 | 20 | 61 | 3.05 | 51 | 1.19 |

**The rate did not "collapse mid-run" in the way a files/s chart suggests.** Read
per-file, the run looks like it fell off a cliff twice (files 401-450 at 9.06 s/file,
files 501-545 at 20.07 s/file). Normalised per page, the first cliff disappears
entirely — files 401-450 are the `scans_multipage` PDFs averaging 3.2 pages each, and
they ran at 2.87 s/page, dead in line with everything else. That "collapse" is an
artifact of measuring per file in a corpus with variable pages per file.

The second one is real and is confined to **one block**: `slides` ran at 6.98 s/page,
**2.73× the reference**, consuming 894 s (35.9% of the loop) to process 128 pages
(16.8% of the pages). Excess cost ≈ **566 s, or 23% of the whole indexing phase**.

Cause: **not determinable from these artifacts, but it is not a property of the deck
files.** Evidence:
- Rendering is not the cost. `_render_pages` on the slowest decks takes 0.05-0.14 s for
  the whole file (all pages 1397×1048 at `PDF_RENDER_DPI=150`).
- Re-encoding the same files today: `deck_017.pdf` 2.64 s/page, `deck_008.pdf`
  2.56 s/page, `deck_016.pdf` 2.52 s/page — indistinguishable from `chart_001.jpg`
  (2.55 s/page) and `scan_xqgl0226.pdf` (2.56 s/page). The 2.73× penalty does not
  reproduce.
- Within the block the cost oscillates file-to-file on identical geometry: `deck_008`
  (9 pages) finished in ~8 s while `deck_017` (5 pages, same 1397×1048 render, same 755
  patches/page) took ~172 s, with fast files interleaved between slow ones. A file
  property cannot oscillate on a seconds timescale between byte-similar inputs.

That signature points to transient host-level contention (memory pressure or thermal)
during the last ~15 minutes of the phase. **Two caveats I will not paper over:** (a)
per-file time attribution is reconstructed from tqdm postfix ordering and is approximate
— only the block-level totals are exact; (b) no single-page image files were interleaved
during the slow window (positions ~503-517 are all decks), so there is no in-window
control, and I cannot fully exclude a deck-specific interaction that happens not to
reproduce on an idle machine. The block totals and the non-reproduction are solid; the
attribution to host contention is my best reading, not a proven fact.

The three blocks *faster* than the reference (photos 0.95, diagrams 1.25, charts 1.65
s/page) are explained: those images are small and produce fewer patches
(`chart_001.jpg` = 641 patches vs 755 for a full-page render), and `diagrams` is 40
files that are only 9 unique images (§5.3).

---

## 2. The 25-file silent data loss

### 2.1 Verification of the supervisor's diagnosis — confirmed for 24 of 25

I reproduced the NaN independently, encoding each image **alone** (batch of 1) at the
run's resolved config (`mps` / `float16` / `colqwen2_5`):

| file | status in run | shape | NaN | max abs |
|---|---|---|---|---|
| `receipts_phone/receipt_040.jpg` | dropped | (1, 677, 128) | **86,656 / 86,656** | — |
| `receipts_phone/receipt_011.jpg` | dropped | (1, 737, 128) | **94,336 / 94,336** | — |
| `receipts_phone/receipt_012.jpg` | dropped | (1, 747, 128) | **95,616 / 95,616** | — |
| `receipts_phone/receipt_010.jpg` | indexed | (1, 737, 128) | 0 | 0.4038 |
| `receipts_phone/receipt_013.jpg` | indexed | (1, 747, 128) | 0 | 0.3582 |
| `receipts_phone/receipt_001.jpg` | indexed | (1, 737, 128) | 0 | 0.3577 |
| `notes_handwritten/CseGyan-Cpp-Notes-17.pdf` | dropped | (1, 747, 128) | **95,616 / 95,616** | — |
| `notes_handwritten/CseGyan-Cpp-Notes-16.pdf` | indexed | (1, 747, 128) | 0 | 0.3875 |
| `notes_handwritten/electric-charge-and-field-9.pdf` | dropped | (1, 770, 128) | **98,560 / 98,560** | — |
| `notes_handwritten/electric-charge-and-field-10.pdf` | indexed | (1, 747, 128) | 0 | 0.4346 |

Findings that extend the diagnosis:

- **It is per-file deterministic, not batch contagion.** `cfg.batch_size = 2`, and the
  dropped files cluster into adjacent runs in processing order (`CseGyan` 17/18/19/2/20
  consecutive, `receipt_011`+`012`, `receipt_015`+`016`), which superficially looks like
  a poisoned batch. It is not. `index.py:126` batches over `images` — *the pages of one
  file* — not across files. Every single-page file is therefore encoded alone anyway,
  and my batch-of-1 reproduction above still NaNs. The adjacency is alphabetical
  clustering of similar content, nothing more.
- **It is all-or-nothing.** Across every page I measured, a page is either 100% NaN or
  0% NaN. I never observed a partially-NaN embedding. This matters for §3: partial
  corruption cannot have slipped into the index.
- **Patch count is not the driver.** `receipt_011` (737 patches) NaNs while `receipt_010`
  and `receipt_001` (also 737 patches) are clean; `CseGyan-17` and `CseGyan-16` are both
  747 patches, opposite outcomes.

### 2.2 CORRECTION 1 — one of the 25 is not a NaN failure

The supervisor's note says all 25 files are the fp16-NaN defect. **They are not.**
Parsing every error block in `worker_index.log` gives two distinct Qdrant rejections:

| kind | count | Qdrant message |
|---|---|---|
| `nan_vectorstruct` | **24** | `Format error in JSON body: data did not match any variant of untagged enum VectorStruct` |
| `payload_too_large` | **1** | `Payload error: JSON payload (33600110 bytes) is larger than allowed (limit: 33554432 bytes).` |

`scans_multipage/scan_nglg0227.pdf` is the odd one out (`worker_index.log:1301` and
`:1379`). I encoded all 20 of its pages at fp16: **zero NaN on every page.** Its
embeddings were perfectly good. It failed because the single upsert request exceeded
Qdrant's **32 MiB request-body cap**:

```
20 pages × 755 patches × 128 dims = 1,932,800 floats
JSON serialised            = 33,600,110 bytes   (≈ 17.4 bytes/float)
Qdrant limit               = 33,554,432 bytes
over by                    =     45,678 bytes   (0.14%)
```

This is a **second, independent, dtype-agnostic bug**. The float32 fix does not touch
it. The effective ceiling at `PDF_RENDER_DPI=150` is **≈19-20 pages per file**:
`scan_xqgl0226.pdf` and `scan_yscw0217.pdf` (18 pages each, ~30.2 MB) cleared it with
about 10% of headroom. **Any PDF of ~20 pages or more silently fails to index on a
default Qdrant configuration.** For an eval corpus that is one file; for a real user's
Documents folder it is a large and arbitrary class of their content. The fix is
chunking `upsert_pages_batch` into sub-32 MiB requests, not a dtype change.

### 2.3 CORRECTION 2 — there were no retries, and no retry latency

The supervisor's note reads "48 of these for 25 files — `_upsert_with_retry` retries the
SAME poisoned payload, so every retry is guaranteed to fail; the retry wrapper adds
latency and no recovery." That is a double-count artifact, and the mechanism is wrong.

- The log prints **each file's error exactly twice**: once inline as
  `  error on <name>:` (`worker_index.log:1230-1305`) and again in the final `errors:`
  block (`:1307` onward). 24 NaN files × 2 = 48 occurrences of the `VectorStruct`
  string; the payload file likewise appears twice. 25 files, 50 blocks, 2 each.
- `raw/qdrant.log` settles it at the HTTP layer: **520 `PUT /collections/fast_tier/points` → 200**
  and **25 `PUT /collections/fast_tier/points` → 400**, total 545 = one request per file,
  **zero retries**.
- Mechanism: `_upsert_with_retry` (`src/stage2/db.py:124-150`) catches only
  `ResponseHandlingException` (timeouts, connection errors). A 400 raises
  `UnexpectedResponse`, which propagates on the first attempt by design — the docstring
  says so explicitly ("Other exceptions propagate immediately"). No backoff was paid.

Same conclusion (no recovery), but the retry wrapper is innocent and cost nothing.
Worth correcting because "kill the retry wrapper" would be a wasted fix.

### 2.4 CORRECTION 3 — the dtype is set at device.py:244, not :154

The note cites `device.py:154` as the site of `dtype = "bfloat16" if cfg.device == "cuda" else "float16"`.
That line is real, but it sits inside `_apply_env_override`, the **`MAGPIE_COL_MODEL` pin
branch**, which returns early when the value is empty or `auto` (`device.py:137-138`).
This run used `MAGPIE_COL_MODEL=auto` (`run.json` env snapshot). Line 154 never
executed.

The live site is **`src/stage1_fast/device.py:244`**, in the MPS auto-detect branch:

```python
return DeviceConfig(
    device="mps",
    model_id=COLQWEN_MODEL_ID,
    model_family="colqwen2_5",
    dtype="float16",  # MPS bfloat16 support is patchy
    batch_size=2,
)
```

The supervisor's *conclusion* is correct — CUDA gets bfloat16 (`device.py:211`) whose
wider exponent range does not overflow this way, so every Apple-Silicon user is exposed
and no CUDA user is. But anyone patching line 154 and re-running would see the bug
unchanged.

### 2.5 EXTENSION — blast radius amplification

`scans_multipage/scan_zxjd0228.pdf` has 12 pages. I encoded each page separately at
fp16: **exactly one page is NaN — page index 8. The other 11 are clean.**

Because `index.py:126-140` accumulates every page of a file into `pages_to_upsert` and
issues **one upsert per file**, that single bad page destroyed 12 pages of content.
Combined with `scan_nglg0227.pdf` (20 pages, zero NaN, killed by size), **32 of the 55
lost pages — 58% of all lost content — come from just 2 files, neither of which is a
whole-file failure.** A per-page or per-chunk upsert would have salvaged 31 of those 32
pages.

### 2.6 Exactly which files, and how much of each category

**`notes_handwritten` — 14 of 37 (37.8%), spread evenly across BOTH sub-families:**

| family | corpus | dropped | % |
|---|---|---|---|
| `CseGyan-Cpp-Notes-*.pdf` | 20 | 7 | 35.0% |
| `electric-charge-and-field-*.pdf` | 17 | 7 | 41.2% |

- CseGyan dropped: **2, 8, 9, 17, 18, 19, 20**
- electric-charge dropped: **3, 8, 9, 11, 13, 16, 17**

**`receipts_phone` — 9 of 40 (22.5%):** `receipt_006, 011, 012, 015, 016, 029, 031, 037, 040`

**`scans_multipage` — 2 of 19 files (10.5%) but 32 of 140 pages (22.9%):**
`scan_nglg0227.pdf` (20 pages, payload cap), `scan_zxjd0228.pdf` (12 pages, one NaN page)

All other 12 categories: zero loss.

### 2.7 Golden-set impact

I cross-referenced every golden item's `gold_sources` and `acceptable_sources` against
the 25 dropped files. **The supervisor's finding is exactly right and I confirm it.**

| pair | items | gold sources | dropped | survivors | verdict |
|---|---|---|---|---|---|
| `rcpt-07` | `rcpt-07-typed`, `rcpt-07-full` | `receipt_040.jpg` | all | none | **TOTAL LOSS** |
| `study-05` | `study-05-typed`, `study-05-full` | `electric-charge-and-field-9.pdf` | all | none | **TOTAL LOSS** |
| `study-10` | `study-10-typed`, `study-10-full` | `CseGyan-Cpp-Notes-17/18/19.pdf` | all 3 | none | **TOTAL LOSS** |

**6 of 120 items (5.0%) are unanswerable for index reasons alone.** No partial losses:
no affected pair retains a single usable gold or acceptable source. Do not attribute
these six to retrieval or answering.

Two extensions:

- **The eval sees only 12% of the defect.** 22 of the 25 dropped files carry no golden
  item at all. The measured eval impact (3 pairs) is an accident of which files the
  golden set happened to sample. A user's real experience of this bug would be
  proportional to the 4.6%/7.2% loss, not to 5% of questions.
- **The 8 `not_found` pairs (16 items, `nf-01`…`nf-08`) are unaffected.** Their premise
  is corpus-wide absence of a topic; removing files from the index can only strengthen
  that premise, never falsify it.

### 2.8 Does the pattern suggest anything beyond fp16 overflow? — No.

I tested the "shared source / camera / colour profile / encoder" hypotheses directly.

**JPEG encoder fingerprint (`receipts_phone`, all 40 files):** every file shares **one
identical quantization-table fingerprint** (`75277221`). The entire folder was
re-encoded uniformly by a single encoder at a single quality setting. Dropped and kept
files are byte-level siblings from the same pipeline. Encoder identity cannot be the
discriminator.

**EXIF and colour management:** **0 of 40** receipts carry any EXIF tag (no `Make`, no
`Model`, no `Software`) and **0 of 40** carry an ICC profile. All are baseline
(non-progressive) RGB. There is no camera, no software provenance and no colour profile
to differ on. `exiftool` is not installed on this machine; I used PIL's `getexif()`,
`info['icc_profile']`, `info['progressive']` and `quantization`, which covers the same
ground for these questions.

**Geometry:** every common dimension group appears on **both** sides.

| dimensions | dropped | kept |
|---|---|---|
| 576×864 | 1 | 9 |
| 864×1296 | 2 | 6 |
| 1108×1478 | 2 | 5 |
| 960×1280 | 1 | 1 |
| 2304×4096 | 0 | 6 |

The four singleton geometries among the dropped (907×1280, 605×1280, 493×1040) have no
kept counterpart, but the largest shared geometries appear on both sides.
For `notes_handwritten`, all 37 files are single-page PDFs rendered at the same 150 DPI
and land on the same patch counts on both sides (747 patches for both the dropped
`CseGyan-17` and the kept `CseGyan-16`).

**Pixel statistics, permutation-tested** (20,000 resamples, two-sided, on the greyscale
render):

| group | metric | dropped | kept | diff | p |
|---|---|---|---|---|---|
| receipts_phone (9 vs 31) | mean | 161.77 | 146.78 | +14.99 | 0.101 |
| | std (contrast) | 36.75 | 48.84 | −12.09 | 0.089 |
| | p1 (black floor) | 59.00 | 39.16 | +19.84 | 0.074 |
| | p99 | 210.00 | 208.84 | +1.16 | 0.887 |
| notes_handwritten (14 vs 23) | mean | 191.19 | 188.45 | +2.74 | 0.665 |
| | std | 42.97 | 43.11 | −0.14 | 0.915 |
| | p1 | 31.57 | 30.87 | +0.70 | 0.824 |
| | p99 | 240.43 | 242.22 | −1.79 | 0.701 |

`notes_handwritten` dropped and kept files are **statistically indistinguishable** on
every metric (p = 0.67-0.92). The receipts show a weak trend — dropped receipts are
brighter and lower-contrast — but at n=9, with four comparisons, nothing reaches
significance. I would not act on it.

**Verdict: no observable file property separates the dropped set from the kept set.**
This is content-specific numerical overflow inside the ColQwen2.5 vision tower under
fp16, and it is invisible from the outside. The operational consequence is important:
**you cannot pre-screen for it.** The only two defences are (a) fix the dtype, or (b)
add a post-encode `torch.isnan(tensor).any()` assert that fails loudly instead of
letting Qdrant reject a malformed JSON body far downstream.

### 2.9 The fp32 fix, verified across all 25

I forced `dtype="float32"` and re-encoded **every page of all 25 dropped files**:

```
STILL NaN under float32: []
```

All 24 NaN files come back with **0 NaN on every page** — including the multi-page
`scan_zxjd0228.pdf` (12 pages, 1,134,848 values, zero NaN). This generalises the
supervisor's 2-file spot check to the full set.

**But note what the dtype fix does *not* do:** `scan_nglg0227.pdf` also reports 0 NaN
under fp32 — it always had 0 NaN. It would fail again, identically, on the 32 MiB
payload cap. **The dtype fix recovers 24 of 25 files and 35 of 55 pages. The remaining
20 pages need the payload fix.** Any remediation plan that ships only the dtype change
should say so.

### 2.10 Why it was silent

1. `index.py` catches the per-file exception and continues (`worker_index.log:1230+`
   shows the collected errors, not a crash).
2. `manifest.mark_fast_indexed` is called **after** the upsert, so a failed file leaves
   no manifest row — the loss is clean, but also invisible in the manifest.
3. `run.py` does not fail the run on a nonzero index error count.
4. Result: `"status": "complete"`, exit 0, `manifest_entries: 520` against a 545-file
   dataset — a discrepancy that is present in `run.json` but never raised as an error.

The one place the truth is stated plainly is `worker_index.log:1306`:
`fast tier: 520 files indexed (709 pages), 0 unchanged, 0 pruned, 25 errors`.

---

## 3. Is the surviving index trustworthy? — Yes, unreservedly

I did not rely on the manifest. I booted the run's own Qdrant storage (copied to
scratch, port 6699) with the bundled binary and scrolled the entire collection.

| check | result |
|---|---|
| `points_count` reported by Qdrant | **709** |
| Σ `fast_pages` over the appdata manifest | **709** — match |
| Points recovered by full scroll | **709** — match |
| Distinct `source_path` values | **520** — match |
| Files in collection ∉ appdata manifest | **0** |
| Files in appdata manifest ∉ collection | **0** |
| Dropped files that leaked into the collection | **0** |
| Duplicate point IDs | **0** |
| Duplicate `(path, page_num)` pairs | **0** |
| Files whose page set ≠ `{0 … fast_pages−1}` | **0** — no truncation, no gaps |
| Points with a path outside the corpus dir | **0** |
| Entries with `fast_pages == 0` or `null` | **0** |
| Entries with no `fast_indexed_at` | **0** |
| `pdfinfo` page count vs manifest `fast_pages`, all 70 indexed PDFs | **0 mismatches** |
| Manifest `size` vs on-disk size, all 520 | **0 mismatches** |

**Vector sanity.** I pulled the full multivector for a random sample of 60 points:
**0 NaN values, 0 zero-norm rows, every row exactly unit-norm** (min = max = 1.0). This
holds by construction as well as by measurement: `json.dumps` emits bare `NaN` /
`Infinity`, which is not valid JSON, so Qdrant rejects the *whole* request — a partially
corrupted page can never be stored. Everything that landed is finite and normalised.

**Duplicate indexing is structurally impossible.** Point IDs are
`md5("<source_path>::page:<N>")` as a UUID (`fast_db.py:72-78`), so a re-upsert
overwrites in place rather than duplicating.

**One benign observation:** `indexed_vectors_count` is 684 against `points_count` 709.
25 points sit in a segment below HNSW's `full_scan_threshold` (10,000) and are searched
by brute force rather than the graph. This is normal Qdrant behaviour and costs no
recall.

**One latent caveat, not a defect in this run:** every one of the 520 manifest entries
has `content_hash: null` and `mtime: null`, so `needs_fast_indexing` discriminates on
**file size alone**. Irrelevant here — this was a cold index (`index_store.hit: false`,
`0 unchanged, 0 pruned`) — but on a warm re-run, a file edited without a size change
would be silently treated as up to date.

**Conclusion: the 520 files that made it into the index are complete, correctly paged,
correctly pathed, un-duplicated and numerically clean.** The defect is entirely one of
*omission*. Nothing that survived is wrong.

---

## 4. The 5-page PDF ceiling

### 4.1 The mechanism is live, and it is worse than a page budget

I verified each link in the chain:

1. **All 86 PDFs have zero extractable text.** `extract_pdf_text` returns empty for
   **86 of 86**. So `content.py:580` (`if full_text:`) is false for every PDF.
2. **The keyword lazy-chunking path is dead.** `content.py:586` — the branch that would
   pick the *relevant* pages via `extract_pdf_relevant_pages` — is nested inside
   `if full_text:`. With no embedded text it can never fire, regardless of keywords.
3. **No transcript exists.** `transcript_for()` returns `None` for **86 of 86**; the
   run's appdata has no transcripts directory at all.
4. Therefore `content.py:609` fires: `render_pdf_pages_as_png(path, ANSWER_MAX_PDF_PAGES)`
   with `ANSWER_MAX_PDF_PAGES = 5` (`src/answer.py:40`), and that function breaks at
   `if i >= max_pages` (`content.py:376`) — **literally pages 1-5, in file order.**

**The deeper defect: the retrieved page number is known and then thrown away.**
`fast_db.search` returns `(source_path, page_num, score)` (`fast_db.py:194-211`), and
`search.py:544-549` explicitly collapses a file's hits to its *best* page. But that page
number is then interpolated into a **display string** —
`summary=f"(visual match — page {page})"` (`search.py:553`) — and nowhere else.
`page_num` appears in **no other file under `src/`**. `SearchResult` carries no page
field, so `answer.py` has no way to ask for the page that actually matched.

So the system knows exactly which page answered the query, and renders pages 1-5 anyway.

### 4.2 Every golden item that cites a multi-page PDF

7 pairs (14 items) cite a multi-page PDF. I located the gold content per page using
per-page OCR of the source files.

| pair | file (pages) | gold content on page | inside first 5? |
|---|---|---|---|
| `arch-03` | `scan_fybg0227.pdf` (4) | p1 — attendance "849" | YES |
| `arch-04` | `scan_mtnh0227.pdf` (5) | p3 — invoice A-3088, $55.25 balance | YES |
| `arch-06` | `scan_gzyh0227.pdf` (9) | p3 — dissolved solids 1506.0 | YES |
| `arch-08` | `scan_psjf0226.pdf` (3) | file is 3 pages; all rendered | YES |
| `study-03` | `deck_022.pdf` (7) | p3 — 50 kW / $150,000 / 67.5 MWh | YES |
| `study-11` | `deck_002.pdf` (5) | p2 — "17 installed apps on average" | YES |
| `study-11` | `deck_018.pdf` (6) | p1 (18 / 15.5) and p2 (iPhone 88, Android 68) | YES |
| **`study-08`** | **`deck_027.pdf` (6)** | **p6 — the entire "Usage of Biosensors in Food Industry" pie chart** | **NO** |

### 4.3 The one structurally unreachable item: `study-08`

`study-08` asks for the biosensor share on a food-industry pie chart. Its key facts —
`Biosensors 8%`, `LC/MS 38%`, `ELISA 18%`, `LC/UV 18%`, `other screening methods 12%`,
`electrophoresis 6%` — appear on **page 6 of `deck_027.pdf`, which has exactly 6 pages.**
Pages 1-5 are unrelated slides (detection-unit design, a typical biosensor diagram, the
Indian scenario, nanotech food packaging, biosensor elements). The answer lives on the
one page the answerer is structurally forbidden from rendering.

The file indexed **perfectly**: all 6 pages are present in Qdrant, verified in §3.
Page 6's own embedding is what won the match. From `raw/answers.jsonl`:

```json
"qa_id": "study-08-typed",
"retrieved": [{"path": ".../slides/deck_027.pdf", "score": 0.01639, "rank": 1, "tier": "fast"}],
"magpie_cited": [], "not_found": true, "error": null
```

Rank 1, the correct file, the only file passed to the generator — and a false abstain
with zero citations. **This is a clean index/answer-contract failure, not a retrieval
failure and not a generation failure.** Both `study-08-typed` and `study-08-full` are
affected: **2 items, 1 pair, structurally unanswerable despite a perfect index and a
rank-1 retrieval.**

### 4.4 How much of the index is unreachable at answer time

Of the 709 indexed pages, **49 (6.9%) sit at page index ≥ 5 and can never be shown to
the generator**, across 10 files:

| file | pages | unreachable |
|---|---|---|
| `scans_multipage/scan_xqgl0226.pdf` | 18 | 13 |
| `scans_multipage/scan_yscw0217.pdf` | 18 | 13 |
| `scans_multipage/scan_yjgx0227.pdf` | 13 | 8 |
| `scans_multipage/scan_gzyh0227.pdf` | 9 | 4 |
| `slides/deck_008.pdf` | 9 | 4 |
| `scans_multipage/scan_xhwg0227.pdf` | 7 | 2 |
| `slides/deck_022.pdf` | 7 | 2 |
| `slides/deck_015.pdf` | 6 | 1 |
| `slides/deck_018.pdf` | 6 | 1 |
| `slides/deck_027.pdf` | 6 | 1 |

The golden set happens to sample this shallowly — only `study-08` lands past page 5.
**That is luck, not safety.** 6.9% of what was indexed is write-only, and the fraction
scales with document length: on a corpus of ordinary 20-50 page PDFs, most of the index
would be unreadable.

---

## 5. What would poison downstream answering

Ordered by expected damage.

### 5.1 Every PDF answer is pixels from pages 1-5, with no text and no summary

This is the compounding one. For all 70 indexed PDFs (236 pages across 47 multi-page
files): zero embedded text, zero T3 summaries, zero vision transcripts. The generator
receives up to five PNG page images and nothing else — no OCR, no transcript, no
supplement. Combined with §4, a PDF question can only succeed if the answer is
(a) within pages 1-5 **and** (b) legible to the VLM from a 150 DPI raster.

One genuinely positive consequence: because `_summary_supplement` returns `None` for all
520 files, the "fictional summary poisons the answer" failure mode documented in
`answer.py:684-697` (the sem_4 Cursor-invoice case) **cannot occur in this run**. No
fabricated context was injected.

### 5.2 The page-number contract break (§4.1)

`page_num` is stored in the Qdrant payload, returned by search, used to pick the best
page — and then discarded into a display string. Until `SearchResult` carries the page
and `build_content_blocks` honours it, retrieval accuracy on long documents cannot
convert into answer accuracy. `study-08` is the worked example, and metrics.json's
combination of hit@1 = 93.3% with correct = 2.9% is the shape this defect produces.

### 5.3 31 redundant index entries consuming top-k slots

`diagrams/` is 40 files that are **9 unique images**: 8 byte-identical groups
(by sha256), 31 redundant copies, largest group 9 identical files
(`diagram_003`…`diagram_011`). All 40 are indexed as separate points. **5.96% of the
520-file index is byte-identical duplicates**, each occupying its own top-k slot. At
`top_k=2`, a diagram query can fill **both** slots with the same picture.

For the golden set this is contained: only `viz-11` cites a diagram
(`diagram_003.jpg`), and all 8 of its twins are correctly listed in
`acceptable_sources`, so hit@k accounting is honest and any twin carries the same
answer. But the slot consumption is real for any question needing two *different*
files. This is a corpus property, documented in the dataset's `known_defects` — I flag
it as an index-side fact, not a new discovery.

### 5.4 The silent-failure policy itself

`run.py` does not fail on a nonzero index error count, so a 4.6% file / 7.2% page loss
shipped as `"status": "complete"`. Every number downstream — hit@1, recall@k,
correctness, abstention — was computed against an index that was quietly 7.2% smaller
than the corpus, and nothing in `metrics.json` or `report.md` says so. Anyone reading
the metrics without opening `worker_index.log` will believe the index is whole.

A secondary distortion: the 25 missing files are also 25 fewer distractors. Their
absence can only make retrieval look *better* than it would on the complete corpus.
I flag the direction; sizing it belongs to the retrieval report.

### 5.5 The Qdrant payload cap is a production landmine (§2.2)

Independent of this eval, **any PDF of ~20+ pages at 150 DPI will silently fail to
index** on a default Qdrant configuration. The corpus hit it once because it contains
exactly one 20-page PDF. A real Documents folder contains many. Neither the fp16 fix nor
any dtype change addresses it.

---

## 6. Suggested fixes, in priority order

1. **`src/stage1_fast/device.py:244`** — use fp32 (or a validated bf16 path) on MPS for
   ColQwen2.5. Verified to clear all 24 NaN files. Cost: fp32 on MPS is materially
   slower; a cheaper variant is to keep fp16 and re-encode in fp32 only on NaN detection.
2. **`src/stage1_fast/index.py:128`** — assert `not torch.isnan(tensor).any()` right
   after `encode_images`, and fail loudly (or retry in fp32) instead of letting a
   malformed JSON body surface as an opaque Qdrant 400.
3. **`src/stage2/fast_db.py:151` (`upsert_pages_batch`)** — chunk into sub-32 MiB
   requests. Fixes `scan_nglg0227.pdf` and every ≥20-page PDF. Also shrinks the blast
   radius: `scan_zxjd0228.pdf` would lose 1 page instead of 12.
4. **`src/stage2/search.py:553` → `src/answer.py`** — carry `page_num` as structured
   data on `SearchResult` and pass it to `build_content_blocks` so the *matched* page is
   rendered, not pages 1-5. Fixes `study-08` and unlocks the 49 currently-unreachable
   indexed pages.
5. **`eval_harness/.../run.py`** — fail, or at minimum stamp a loud
   `index_errors: 25` / `files_missing: 25` field into `run.json` and `metrics.json`, so
   a lossy index can never again be reported as `complete` without comment.

---

## 7. Uncertainties, stated plainly

- **The `slides` 2.73× slowdown is unexplained.** I established what it is *not*
  (rendering, page count, file geometry, a reproducible property of the deck files) but
  not what it *is*. No image files were interleaved during the slow window, so there is
  no in-window control. Host contention is my reading, not a proven fact.
- **Per-file timings are reconstructed** from tqdm postfix ordering and are approximate;
  the category-block totals in §1.3 are exact and all quantitative claims rest on those.
- **Gold-page locations in §4.2 come from OCR** of the source pages. OCR on chart-heavy
  slides is imperfect, and for `arch-08` no key fact matched any page — that file is 3
  pages so the ceiling cannot bite regardless. The `study-08` finding does **not** rest
  on fuzzy matching: page 6 of `deck_027.pdf` OCRs cleanly to
  "Usage of Biosensors in Food Industry … Biosensors 8% … LC/MS 38%", every key fact
  verbatim, and pages 1-5 contain none of them.
- **The weak brightness/contrast trend in the dropped receipts** (§2.8) is reported for
  completeness. At n=9, p≈0.07-0.10 across four comparisons, it is not evidence of
  anything and I do not build on it.
- I audited the index by booting **a copy** of the run's Qdrant storage. The copy was
  byte-identical (`cp -R`) and the collection reported `status: green`,
  `optimizer_status: ok`, so I treat it as faithful to the live run.
