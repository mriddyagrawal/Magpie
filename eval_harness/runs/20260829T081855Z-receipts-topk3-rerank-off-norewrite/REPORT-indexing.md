# REPORT — Indexing analyst

Run: `20260829T081855Z-receipts-topk3-rerank-off-norewrite`
Config: `lfm-local`, `top_k=3`, `rewrite=false`, `rerank=false` (`MAGPIE_RERANK=0`),
`solo_margin=0`, temp 0, `n_ctx` 16384, `index_fast_tier=true`,
`index_summary_tier=true`, `fast_search=true`.
Corpus: `receipts`, 148 scanned JPEGs under
`/Users/mriddy/Documents/Magpie-eval-corpora/receipts/batch_00..batch_10/`.
Backend `c823a44`, harness `2e1c851`, `golden_sha` `a3b05ea95c052a65`.

**This run did not build an index.** `run.json` records
`index_store: {key: 5ff3e0adf0448de6, hit: true, built_under_sha: c823a44…}` and its
`phases` block contains no `index` entry at all — only `retrieve` (33.2 s) and
`answer` (2649.7 s). The artifact was built by the previous run
(`20260829T065335Z-receipts-topk2-rerank-off`, 428.1 s, `hit: false`) and mounted here.
This is the first run in the project's history to actually exercise the index cache,
so the primary job of this report is verification, not description.

---

## Bottom line

1. **The mounted index is sound.** Verified four independent ways — structural
   (148 Qdrant points ⇔ 148 manifest rows ⇔ 148 sha256-verified files on disk),
   byte-level (the mounted copy is bit-identical to the store), behavioural
   (the run issued only reads against it — zero writes, zero errors), and
   functional (all 148 files, and all 74 gold source files, were actually
   retrievable). §1. **A clean verification is the result here.**
2. **The cache key is not sufficient, and this is a live correctness bug.**
   `index_params_hash()` (`run.py:49-51`) keys on the dataset *name* and four
   answer-side knobs. It does not key on the corpus **content**, on the corpus
   **path**, on the `dataset_dir` override, or on the **visual encoder identity** —
   the four things that actually determine what lands in `fast_tier`. Two of the
   four keyed parameters (`model_config`, `local_n_ctx`) cannot affect the index of
   an all-image corpus at all. The dataset's own manifest documents a live trigger
   for the corpus-drift case. §2.
3. **A SHA drift is warned on stderr and then silently accepted.** No run field,
   no failure, no exit code. §3.
4. **The mount cost 0.24 s** (measured by replaying the exact `copytree` calls)
   against a 428.1 s rebuild — a 1780× saving, 16% of this run's wall clock. §4.
5. **Indexing quality: the pixels are fine; the representation is thin.** Twelve
   receipts read directly with vision — every asked-for fact is legible in the
   source, no file is corrupt, blank, or truncated. But the fast tier stores
   **`{"source_path", "page_num"}` and ~744 patch vectors per page and nothing
   else** — no text, no crop, no transcript. 12 of 148 files are small slips
   scanned on a full page, where the receipt occupies as little as 12% of the
   frame and therefore ~90 of ~750 patches. §5.
6. **The empty-text-block claim is exact, and it is 100%, not 97%.** Reproduced by
   running `build_content_blocks` over all 148 files: **148/148 return exactly one
   `BinaryContent` block and zero `str` blocks — 0 characters of text in the whole
   corpus.** `context_text` at `src/answer.py:888` is therefore literally `""` for
   every one of the 120 questions, which reduces the groundedness guard to
   "delete any answer containing a number ≥ 100". Confirmed on this run's data:
   32 guard kills in `worker_answer.log`, and **zero of the 79 surviving answers
   contain a number ≥ 100**. §6.
7. **Isolation holds, re-verified independently at audit time.** §7.

---

## 1. The mounted index is correct and complete — verification

The mount is `run.py:166-186`: if `indexes/<key>/meta.json` exists, `raw/appdata` and
`raw/qdrant` are deleted and replaced by `copytree` from the store. Nothing else is
checked. So everything below is verification the harness does *not* do.

### 1.1 Structural: 148 = 148 = 148, with no duplicates and no strays

I decoded the Qdrant payload storage directly rather than trusting any log. The
segment payload pages are LZ4-block compressed; I wrote a minimal LZ4 decoder and
parsed every record out of the five segments under
`raw/qdrant/collections/fast_tier/0/segments/*/payload_storage/page_0.dat`:

| Segment | Decoded payloads |
|---|---|
| `066f3351…` | 27 |
| `354b616a…` (mutable, unquantized) | 9 |
| `53020fa8…` | 29 |
| `d079180e…` | 30 |
| `df016048…` | 53 |
| **Total** | **148** |

Results:

- **Every payload has exactly the key set `("page_num", "source_path")`** — 148/148.
  There is no text field, no summary field, no vendor field. This is the whole of
  what the index knows about a receipt besides its vectors.
- **148 distinct `source_path` values; zero duplicates.**
- **`page_num == 0` for all 148** — one page per receipt, as expected for single JPEGs.
- The Qdrant payload path set is **set-identical** to the 148 keys of
  `raw/appdata/manifest.json`, and their basenames are **set-identical** to the 148
  `files[].name` in `eval_harness/datasets/receipts/manifest.json`. Missing: none.
  Extra: none.
- **All 148 files on disk hash-match the dataset manifest** — I recomputed sha256 for
  all 148 and got 0 mismatches against `datasets/receipts/manifest.json`. There are
  also **no duplicate content hashes among the 148**, so the 150→148 dedup
  (`selection` note in the dataset manifest) is complete: no residual twins.
- The corpus root holds exactly 149 files: 148 `.jpg` + one `.DS_Store`, which is
  correctly not indexed.
- Per-row manifest state is uniform: `fast_indexed_at` set on **148/148**,
  `fast_pages == 1` on **148/148**, `skip_reason` null on 148/148,
  and `size` matches the on-disk `st_size` for all 148.
  `summary_file`, `summarized_at`, `ingested_at`, `row_count`, `content_hash` are
  null/empty on 148/148 — see §5 and §6.

### 1.2 Byte-level: the mounted copy is the store

`diff -rq eval_harness/indexes/5ff3e0adf0448de6 → raw/` returns exactly three
differences, all explained:

| Difference | Explanation |
|---|---|
| `appdata/logs/llm-2026-08-29T08-19-38Z.log` present only in the run | This run's own LLM session log, written after the mount. |
| `appdata/settings.json` differs | The worker rewrites it per phase (`worker.py:_write_settings`, l.99-112). Store copy says `top_k: 2, rewrite_default: true` (the prior run's); the run copy correctly says `top_k: 3, rewrite_default: false`. See §2.5. |
| `qdrant/collections/fast_tier/0/temp_segments` present only in the store | Empty scratch dir left by the build. |

Everything else is byte-identical, including `appdata/manifest.json`
(md5 `5cbacbe8b37312c1fc389811eaf2b2f5` on both sides) and **the entire 615 MB Qdrant
tree**. The index manifest was not mutated by this run.

### 1.3 Behavioural: the run only ever read the index

`raw/qdrant.log` (759 lines) contains exactly three kinds of HTTP request and nothing
else:

```
 240 POST /collections/fast_tier/points/query
 240 GET  /collections/fast_tier/exists
 240 GET  /collections/summaries/exists
```

**Zero `PUT`, zero `DELETE`, zero `POST …/points` upserts, and 0 lines matching
`error|panic|fail`.** 240 = 120 retrieval-sweep queries + 120 `ask()` queries. Qdrant
recovered the mounted shard cleanly at boot (`Recovered collection fast_tier: 1/1
(100%)`, 08:18:55.52Z, ~98 ms after start). The `summaries` collection was probed 240
times and never existed — the summary tier produced nothing, consistent with the prior
run's `summary_tier_note`.

### 1.4 Functional: everything in the index is actually reachable

Structural completeness would still permit dead points — vectors present but
unsearchable. They were not:

- The 120-question retrieval sweep (`raw/retrieve.jsonl`, 12 hits each = 1440 hits)
  surfaced **148 distinct files — all of them**. Every point in the collection won a
  top-12 slot at least once. Mean top-12 appearances 9.7 per file.
- All 1440 sweep hits and all 375 `ask()` hits are `tier: "fast"`, `.jpg`, and present
  in the mounted manifest. Zero hits from any other tier or any path outside the corpus.
- **All 74 distinct `gold_sources` files named by `golden.json` are present in the
  mounted index.** Zero gold files missing. This is the check that most directly
  guards against a stale mount poisoning the score, and it passes.
- End-to-end retrieval computed from `answers.jsonl` gives hit@1 = 0.794 / hit@3 =
  0.892 (n=102 with gold), against `metrics.json` hit@1 = 0.792 / hit@3 = 0.887 from
  the separate sweep. A stale or partial index does not produce a 0.79 hit@1.

**Verdict: the cached index mounted in this run is complete, uncorrupted, unmutated,
and functionally equivalent to the one the prior run built. Nothing downstream of it
is poisoned by the cache hit.** I found no evidence of any defect in the artifact.

---

## 2. The cache key is not sufficient — a latent correctness bug (brief item a)

```python
# eval_harness/harness/run.py:44-51
INDEX_SIDE_PARAMS = (
    "model_config", "index_fast_tier", "index_summary_tier", "local_n_ctx",
)

def index_params_hash(dataset: str, params: dict) -> str:
    view = {"dataset": dataset, **{k: params.get(k) for k in INDEX_SIDE_PARAMS}}
    return hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest()[:16]
```

The key set is **not** sufficient. The sharpest way to see it: for an all-image corpus
like `receipts`, the key varies on things that *cannot* change the artifact and is
constant across the things that *can*.

- `model_config` selects the answer/summarization LLM (`envctl.MODEL_CONFIGS`,
  l.101-110). `local_n_ctx` sizes that LLM's context. Neither touches the visual
  encoder. On a 100%-image corpus the summary tier is a structural no-op (prior
  finding #6, re-confirmed in §8), so **both of these keyed parameters are inert for
  this dataset** — flipping either forces a needless 428 s rebuild of a byte-identical
  index.
- `index_fast_tier` / `index_summary_tier` are correctly keyed.

### 2.1 Not in the key: the corpus content — **highest risk**

The key contains the dataset *name*, `"receipts"`. It contains no hash of the corpus,
no file count, no manifest digest. `load_dataset` (`run.py:56-69`) reads the corpus
root from a per-machine pointer and loads the manifest — including a `sha256` for
every one of the 148 files — and the only validation performed anywhere in the harness
is a basename-uniqueness check:

```python
# run.py:103-106
basenames = [Path(f["name"]).name for f in dataset["manifest"].get("files", [])]
if len(basenames) != len(set(basenames)):
    raise SystemExit(f"dataset {config['dataset']!r} has duplicate file basenames")
```

`grep -rn "sha256" eval_harness/harness/` confirms it: the per-file hashes are loaded
and never used. `golden_sha` (`run.py:123-125`) hashes `golden.json` only.

**On a cache hit the harness never looks at the corpus at all.** `phase_index` — the
only code that touches `corpus_dir` — is skipped entirely. So the corpus could be
edited, extended, truncated or repointed between runs and the mount would proceed
identically, with `dataset_manifest_files: 148` stamped into `run.json` purely from the
manifest file, not from anything observed.

**This dataset ships a documented trigger for exactly that.** From
`datasets/receipts/manifest.json`:

> "NOTE: prepare_receipts.py regenerates all 150 from the HF split; re-running it
> restores the two dropped files on disk and they must be deleted again to match this
> manifest."

Re-run the prepare script, forget the manual deletion, and the corpus on disk is 150
files while the key stays `5ff3e0adf0448de6`. Either the 148-file index is mounted
against a 150-file corpus (two receipts silently unretrievable, and the qrels
ambiguity the dedup was meant to remove is back on disk), or — if that run happens to
miss the cache — a 150-file index is published under the key that every "148" config
will mount forever after. Neither is detected, and `run.json` will read `hit: true`,
`dataset_manifest_files: 148`, `status: complete` in both cases.

The fix is cheap and the inputs are already in hand: mix a digest of the manifest's
`files[]` (name + sha256) into `index_params_hash`, and on a hit spot-verify a sample
of file hashes against disk before mounting.

### 2.2 Not in the key: `dataset_dir` and `corpus_root.local.json`

`run.py:104` calls `load_dataset(config["dataset"], config.get("dataset_dir"))`, but
`run.py:118` calls `index_params_hash(config["dataset"], params)` — the override is
dropped. Two configs naming `dataset: "receipts"` with different `dataset_dir` values
(different golden set, different corpus root pointer, different files) collide on one
key and share one index. Likewise `corpus_root.local.json` (`run.py:60-63`) can be
repointed at a different folder on the same machine with no effect on the key.

### 2.3 Not in the key: the visual encoder — the quiet one

The `fast_tier` vectors are produced by whichever model `detect_device()` picks:

```
src/stage1_fast/device.py:8-11
Exactly one model is usable per machine: this picks it, and nothing
downstream offers a choice. Switching would invalidate the whole `fast_tier`
collection, since the two produce incompatible vectors and the query encoder
must match whatever built the index.
```

The codebase states the invariant and nothing enforces it. The selection is
`vidore/colqwen2.5-v0.2` vs `vidore/colSmol-500M` (`device.py:34,52`), decided by a
24 GB unified-memory threshold (`device.py:83`) and **cached at
`~/.cache/notspotlight/device.json` (`device.py:56`)** — a path that sits outside
every isolation boundary the harness has. `envctl.cache_fingerprint()` walks only
`~/Library/Application Support/Magpie/cache`; `envctl.appdata_fingerprint()` walks only
`REAL_APP_DATA`. Neither sees it. This machine's cache currently reads
`{device: mps, model_id: vidore/colqwen2.5-v0.2, dtype: float16, batch_size: 2,
selector_version: 3}`, which is what built this index — I verified that. But:

- bumping `_SELECTOR_VERSION` (`device.py:69`) discards the cache by design;
- deleting the cache, or running on a machine near the threshold with different memory
  pressure, can flip the pick;
- neither event changes `5ff3e0adf0448de6`.

And the failure would be **silent, not loud**, because both models are dimensionally
compatible:

```
src/stage2/fast_db.py:45-48
# Late-interaction embedding dim. Both ColQwen2.5 and ColSmol project to
# 128-dim patch vectors; the patch count differs (1030 vs ~1139) but Qdrant's
FAST_VECTOR_DIM = 128
```

A ColSmol query encoder issued against a ColQwen-built collection would not error — it
would return well-formed, meaningless rankings. Nothing in `run.json`, `metrics.json`
or `meta.json` records which encoder built the index, so nothing downstream could
detect it either. `meta.json` records `backend_sha` but not `device.json`.

**Recommendation:** stamp the resolved `DeviceConfig` into `meta.json` and into
`run.json`, and mix `model_id` + `dtype` into `index_params_hash`. This is a one-line
key change that closes a failure mode with no other detector.

### 2.4 Correctly excluded (for the record)

`top_k`, `top_k_retrieval_max`, `rewrite`, `rerank`, `solo_margin`, `temperature`,
`fast_search`, `enumerate_lists`, `prompt_style` are all query- or answer-side and
correctly absent from the key — that is the whole point of the store. `pool_factor` is
a genuine index-side knob (`index.py:82-90`) but is not a live variable:
`run_fast_batch` calls `index_file(p, manifest)` with no `pool_factor`, so it is
always 1. `PDF_RENDER_DPI` affects PDFs only. `backend_git_sha` is deliberately
excluded, with a documented rationale (`run.py:180-186`) — see §3.

### 2.5 A structural observation: the store snapshot is post-*answer*, not post-*index*

Publication (`run.py:307-327`) runs at the very end of `main()`, after the retrieve and
answer phases. So the store holds whatever `raw/appdata` and `raw/qdrant` looked like
when the *whole* prior run finished, not what indexing produced. Direct evidence: the
store's `appdata/logs/` contains the prior run's two LLM session logs
(`llm-2026-08-29T07-00-44Z.log`, `llm-2026-08-29T07-03-31Z.log` — its retrieve and
answer sessions, 1.7 MB), and its `settings.json` carries the prior run's *query-side*
parameters `top_k: 2, rewrite_default: true`.

Both were copied into this run's `raw/appdata` at mount. Consequences:

- **Benign:** the stale `settings.json` is overwritten by
  `worker.py:_write_settings` before every phase — verified, the mounted copy correctly
  reads `top_k: 3, rewrite_default: false`.
- **A provenance trap:** this run's `raw/appdata/logs/` now holds three LLM logs, two
  of which belong to a different run and a different config. Any analysis that globs
  `appdata/logs/*.log` will silently mix runs. The harness itself is safe because
  `run.json` names the correct log explicitly
  (`phases.answer.llm_log = …llm-2026-08-29T08-19-38Z.log`), but nothing says so in the
  directory.
- **Not a problem:** the Qdrant snapshot is taken after `qdrant.stop()` in the `finally`
  block, so it is a consistent, flushed copy. Confirmed by §1.2 — it round-tripped
  byte-identically.

Publishing only the index-relevant subset (or snapshotting immediately after the index
phase) would remove the trap.

### 2.6 Minor: the publish is not atomic

`run.py:325-326` does `shutil.rmtree(store_dir)` then `tmp.replace(store_dir)`. A
concurrent run mounting inside that window sees either a missing `meta.json`
(→ harmless MISS and a redundant rebuild) or a half-removed tree (→ `copytree` raises).
The harness supports parallel slots (`--slot`, `envctl.Ports.for_slot`), so this is
reachable. Publishing to `.tmp-<key>` and doing a single `replace` onto a *fresh*
name, or taking a lock file, would fix it.

---

## 3. `built_under_sha` — matches here; drift is warned, then accepted (brief item c)

**This run: match.** `run.json.index_store.built_under_sha` =
`c823a44f1227a18359f1823af720fcc7f0979209` and `run.json.backend_git_sha` =
`c823a44f1227a18359f1823af720fcc7f0979209`. Identical.
`indexes/5ff3e0adf0448de6/meta.json` independently agrees (`backend_sha: c823a44…`,
`built_by_run: 20260829T065335Z-receipts-topk2-rerank-off`, `built_utc:
20260829T065335Z`), as does `metrics.json.index_store`. The harness SHA advanced from
`c9eb90a` to `2e1c851` between the two runs, but `backend_git_sha` is path-scoped to
`src/` (`envctl.git_sha`, l.301-315), so the code under test genuinely did not move.
**Provenance is clean.**

**If a future run mounts an index built under a different backend SHA, it is detected
but not acted on.** `run.py:180-186`:

```python
if meta.get("backend_sha") != run_record["backend_git_sha"]:
    print(f"[run] WARNING: stored index built under … rebuild with "
          f"--rebuild-index if indexing code changed", file=sys.stderr)
```

That is the entire mechanism. Specifically:

- The run **does not fail**, does not set `status` to anything unusual, and the exit
  code is unaffected.
- **No field records the drift.** `run_record["index_store"]` gets `built_under_sha`,
  so a reader who knows to compare it against `backend_git_sha` can find it — but
  there is no boolean, no flag, and no mention of it in `report.md` or `metrics.json`
  (`enrich.py:473` copies `index_store` through verbatim). Compare this to how
  seriously the codebase treats the same class of problem elsewhere:
  `solo_gate_structurally_off` exists as a stamped boolean precisely so "the confound
  travels with the data, not just comments" (`run.py:143-149`), and isolation
  violations *fail* the run because "a compensating control that only writes a JSON
  field nobody must read is not a control" (`run.py:288-290`). The SHA-drift path is
  weaker than both.
- The warning goes to the runner's **stderr**, which is not captured into any run
  artifact. On an unattended or backgrounded run it is simply lost.

The design choice not to key on SHA is defensible and documented (routine commits
would otherwise invalidate a 428 s artifact). The gap is that its compensating control
is the weakest kind the codebase has. **Recommendation:** add
`index_store.sha_drift: true|false` alongside `built_under_sha` and surface it in
`report.md`; optionally require an explicit `--allow-sha-drift` before mounting across
a `src/` change.

---

## 4. Timing and cost (brief item 3)

**What the hit saved.** The prior run's index phase cost **428.1 s** wall
(`20260829T065335Z…/run.json`, `phases.index.wall_s`); the worker's own measurement
was 426.17 s, of which ~411 s was the ColQwen encode pass at a flat 2.78 s/file and
~15 s was the local LFM2.5-VL server starting for a summary tier with no work.

**What the mount cost.** `run.json.started_utc` is `20260829T081855Z` and the mounted
Qdrant logged its first line at `2026-08-29T08:18:55.42Z`, so the mount plus both
isolation fingerprints completed inside the run's first second. To get a real number I
replayed the exact operation `run.py:169-173` performs — `shutil.copytree` of
`indexes/5ff3e0adf0448de6/{appdata,qdrant}` into scratch:

```
copytree wall_s = 0.24
```

**0.24 s versus 428.1 s — a ~1780× saving, and 16% of this run's 2683.5 s total.**
For contrast, the mount is 138× cheaper than the run's own retrieval phase (33.2 s).

**Store integrity on disk.** `eval_harness/indexes/5ff3e0adf0448de6/`:

| | |
|---|---|
| Total | 617 MB (615 MB allocated, 614 MB apparent — not sparse) |
| `qdrant/` | 615 MB — one collection, `fast_tier`, 1 shard, 5 segments, 148 points |
| `appdata/` | 1.8 MB — `manifest.json` (79 KB, 148 rows), `indexing_rules.json`, `settings.json`, `logs/` (1.7 MB, prior-run logs — §2.5) |
| `meta.json` | key, dataset, `index_side_params`, `backend_sha`, `built_utc`, `built_by_run` — all present and internally consistent |

Collection config is as designed: 128-dim multivectors with `comparator: max_sim`,
int8 scalar quantization, `on_disk: true` for vectors, payload and HNSW, and a
`keyword` payload index on `source_path`. Cross-checked against the quantization
metadata: the four quantized segments hold 20264 + 21309 + 22564 + 39278 = **103,415
patch vectors across 139 points**, and `quantized.data` size ÷ patch count is exactly
**132.0 bytes** in all four (128 int8 dims + 4 bytes) — the vectors are real, complete
and correctly shaped. Storage is ~4.2 MB/page, i.e. ~617 MB for 148 receipts.

**The store published correctly and mounted correctly.** `meta.json` matches the
producing run, the mounted bytes match the store (§1.2), and Qdrant recovered the
shard without complaint (§1.3).

---

## 5. What indexing actually produced, and how faithful it is (brief item 1)

### 5.1 The stored representation, exactly

For each of the 148 receipts the index holds precisely two things:

1. **One Qdrant point**, payload `{"source_path": "<abs path>", "page_num": 0}`, with a
   multivector of **~744 128-dim patch vectors** (measured: 750.5 / 734.8 / 752.1 /
   741.1 per page across the four quantized segments; the mutable segment's
   per-point offsets give 725, 731, 746, 747, 749, 749, 752, 767, 771 — range
   725-771).
2. **One manifest row** with `size`, `fast_indexed_at`, `fast_pages: 1`, and every
   other field null.

That is the entire index. No text, no crop, no transcript, no vendor, no date, no
total. Two consequences follow directly and are visible in this run's data:

- **RRF has only one list to fuse**, so scores collapse to `1/(60+rank)`. Observed
  exactly: 116 hits at 0.016393 (=1/61), 116 at 0.016129 (=1/62), 116 at 0.015873
  (=1/63). Rank 1 always scores 0.016393 whether the match is perfect or absurd —
  every score margin downstream is a constant. With `MAGPIE_RERANK=0` there is no
  second signal anywhere.
- **Nothing can disambiguate on tokens.** §5.3 shows two concrete cases from this run.

A side note on the measured patch counts: `src/stage2/fast_db.py:46` says ColQwen2.5
produces "1030" patch vectors per page. The measured mean here is **744**, ranging
725-771 — ColQwen2.5 inherits Qwen2-VL's dynamic-resolution processor, so patch count
tracks the *resized* image, not a fixed grid. The 1030 figure is a leftover from
ColPali/PaliGemma. Harmless, but the comment is wrong and it is the number anyone
sizing this collection will reach for.

### 5.2 Vision spot-check: 12 receipts read directly

Twelve files, chosen to span the degradation axes rather than at random, and
deliberately disjoint from the six the prior run's report checked. I opened each image
and read it myself; nothing below relies on labels, on `golden.json`, or on the prior
report.

| # | File (batch) | px | What I read | Source legible? |
|---|---|---|---|---|
| 1 | `X51005361923` (b01) | 2481×3508 — largest area | SWC ENTERPRISE SDN BHD, Ijok Selangor; TAX INVOICE; 02/01/2018 10:46:55; TOTAL AMOUNT 4.20; CASH 50.20; CHANGE 46.00; GST 0.24 | Yes — but see §5.4 |
| 2 | `X51005568855` (b02) | 936×3521 — tallest (3.76:1) | POPULAR BOOK CO (M) SDN BHD, Cheras Leisure Mall; 23/12/17 15:53; Slip 9050338975; Total RM Incl. of GST 140.65; Mastercard; 14 items; GST T@6% 4.18 | Yes, fully |
| 3 | `X51005442388` (b02) | 1080×1528 — lowest bytes/px (0.065) | CONTENTO, Permas Johor; 20/03/18 17:19; ***TOTAL RM 21.60; CASH 30.00; CHANGE 8.40 | Yes — faint, small in frame |
| 4 | `X51005684949` (b05) | 439×907 — 2nd smallest; **dedup survivor** | WESTERN EASTERN STATIONERY SDN BHD; TAX INVOICE; 26-02-2018 14:27; CLR P.S A4/A3 RM7.42; GST 6% RM0.42; TOTAL RM7.42 | Yes, crisp |
| 5 | `X51005268275` (b00) | 835×2333 — **dedup survivor** | LIGHTROOM GALLERY SDN BHD, Klang; **CREDIT NOTE** LCN00212; 20/11/2017; Sub Total 263.02; GST 15.78; TOTAL RM 278.80 | Yes, fully |
| 6 | `X51005337867` (b00) | 619×2175 | OLDTOWN WHITE COFFEE, Sri Rampai; "Guest Check — **THIS IS NOT A RECEIPT**"; 22 Mar 18; Subtotal 25.94; Amount Due 30.25 | Yes, fully |
| 7 | `X51005806692` (b09) | 808×2360 | GREAT ZONE HOUSEHOLD CENTRE SDN BHD, Kluang; 18/02/2018; Sub Total 346.51 (circled in magenta highlighter); GST 6% 20.79; Rounded Total 367.30; Credit Card | Yes, fully |
| 8 | `X51005705759` (b05) | 1135×2753 | MYDIN MART SRI MUDA, Shah Alam; 1/08/2017; Total 109.90; Cash 150.00; Change 40.10; GST S=6% tax 6.19 | Yes, fully |
| 9 | `X51005746210` (b08) | 705×2287 | Segi Cash & Carry Sdn Bhd, Shah Alam; Invoice 31911; 12 Mar 2018; 12 items; Total Incl. GST 145.10; Master …0000 | Yes, fully |
| 10 | `X51005361908` (b01) | 1654×2339 — largest file (1.9 MB) | TEO HENG STATIONERY & BOOKS, Batang Berjuntai; CS1803/28617; 15/03/2018; ARTLINE 70 ×48; TOTAL 127.20; TOTAL TAX 7.20 | Yes — heavy speckle, still clear |
| 11 | `X51005230648` (b00) | 620×880 | CROSS CHANNEL NETWORK SDN BHD, Batang Kali; Tax Invoice BTG-052332; Schneider E15R switch 6.36; Total Amt Payable 6.35; 29/01/2018 | Yes, fully |
| 12 | `X51005568894` (b03) | 936×2915 | VIVOPAC MARKETING SDN BHD, Taman Segar KL; CS21532619; **17/01/2017**; Sub Total 44.00; GST 6% 2.64; Rounded Total 46.65 | Yes, fully |

**No per-file indexing failure or degradation found.** No file is corrupt, blank,
rotated illegibly, or truncated. Every one carries a readable vendor, date and total.
Combined with `fast_pages: 1` and `skip_reason: null` on all 148, and with the flat
2.78 s/file build rate the prior run recorded, there is no evidence of any file being
partially or badly encoded.

### 5.3 Where the representation *is* unfaithful: two cases from this run

The images are fine; what the index keeps of them is not enough to distinguish them.
Two spot-check files were retrieved at **rank 1** for questions they cannot answer:

- **`X51005337867` (OLDTOWN WHITE COFFEE guest check) was rank 1 for four questions**,
  including `"wan sheng march which one more expensive"` and
  `"mr diy march total spent"` — two completely different vendors. A generic
  thermal-slip layout wins on visual similarity because there is no lexical channel in
  which "Wan Sheng" fails to match "OLDTOWN WHITE COFFEE".
- **`X51005568894` (VIVOPAC) was rank 1 for `"vivopac gst amout sept"`.** Right vendor —
  a genuine ColQwen success on the logo/layout — but the receipt is dated **17/01/2017**,
  not September. The index stores no date, so "sept" is un-actionable.

Both are the predicted consequence of §5.1, and both are exactly the case where a
one-line indexed transcript ("VIVOPAC MARKETING · 17/01/2017 · GST 2.64 · total 46.65")
would fix retrieval, citation text, and answer grounding at once.

For the positive control: `X51005806692` was rank 1 for *"How much GST did I get
charged on the Great Zone Household Centre bill?"*, and `X51005705759` was rank 1 for
both Mydin Sri Muda phrasings. The visual tier does work when the query names something
visually distinctive.

### 5.4 A measured degradation axis nobody has quantified: wasted frame

ColQwen2.5 resizes every page to a roughly fixed token budget — the measured
725-771 patches per page across a corpus whose areas span 0.36 to 8.7 megapixels
(a 24× range) proves the budget, not the image, sets the resolution. At ~750 tokens ×
784 px/token the encoder sees roughly 588 k pixels of every receipt regardless of the
original, a median linear downscale of **0.61×** and, for the largest file, **0.26×**.

`_render_pages` does no cropping — `return [Image.open(path).convert("RGB")]`
(`src/stage1_fast/index.py:64`) — so whatever white paper surrounds a small slip on a
flatbed scan consumes the same budget as the print. I measured the content bounding box
(pixels below 200 grey, 4× downsample) for all 148:

| Content bbox as fraction of frame | Files |
|---|---|
| ≥ 50% | 136 |
| < 35% | **12** |
| worst (`X51005433543`, 1080×1527) | **12.0%** |

The twelve worst are almost all `1080×1527` scans from `batch_01`/`batch_02` — small
slips centred on a large page. For `X51005433543` the receipt occupies ~90 of ~750
patches; for `X51005442388` (spot-check #3) ~147 of ~750. `X51005361923` (spot-check
#1) is a different flavour of the same problem: bbox 1.00 only because scanner
colour-bleed artefacts touch the page edges, while its **ink fraction is 0.020** — the
receipt is a small slip on an 8.7-megapixel A4 scan, downscaled 0.26×.

**Honest negative result:** I tested whether this hurt retrieval in this run, and it did
not. Comparing the 12 low-bbox files against the other 136:

| | low-bbox (<35%) | others |
|---|---|---|
| mean appearances in a top-12 list | 10.17 | 9.69 |
| mean best rank achieved | 2.50 | 2.53 |

No measurable penalty. Three of the twelve are gold sources (`X51005200931`,
`X51005442322`, `X51005442343`) and their gold file reached rank 1 on 4 of 6 questions —
in line with the corpus-wide 0.79. So: the mechanism is real and quantified, the harm
is not demonstrated on this corpus, and I would rank an auto-crop below a text tier.
Recording it because it is cheap insurance for denser or lower-contrast corpora, and
because nobody had measured it.

---

## 6. The upstream root cause, quantified exactly (brief item 2)

The prior run reported "97-100% of TEXT blocks are empty". **The number is 100%, and it
is structural, not statistical.**

I ran the real code path over the real corpus, in-process, under a scratch
`MAGPIE_DATA_DIR` — `build_content_blocks(path, max_chars=ANSWER_MAX_CHARS_PER_FILE,
max_pdf_pages=ANSWER_MAX_PDF_PAGES)` for each of the 148 indexed files:

```
files probed: 148
block shape (total_blocks, str_blocks, first_type) -> {(1, 0, 'BinaryContent'): 148}
total str blocks across all 148 files: 0
total text characters available to the groundedness guard: 0
```

**148 of 148 files return exactly one block, and it is a `BinaryContent`. Zero `str`
blocks. Zero characters.** The mechanism is one branch:

```python
# src/content.py:575-576
if ext in IMAGE_EXTS:
    return [BinaryContent(data=path.read_bytes(), media_type=IMAGE_EXTS[ext])]
```

For an image there is no code path that can emit text. `transcript_for` (`content.py:51`)
exists but is consulted only in the scanned-**PDF** branch (`content.py:600-606`), and no
`transcripts/` directory exists in this run's appdata anyway. The one other possible
`str` block, the T3 summary supplement (`answer.py:695`), returns `None` for all 148
because `summary_file` is null on all 148 rows — which is itself a direct consequence
of the summary tier indexing nothing (§8).

Therefore at `src/answer.py:887-889`:

```python
_blocks = [b for _d, blocks in per_file_blocks for b in blocks if isinstance(b, str)]
...
context_text = "\n".join(_blocks)
```

`per_file_blocks` for this run contains only image blocks — **375 retrieved hits across
120 questions, 100% `tier: "fast"`, 100% `.jpg`, 100% present in the mounted index** —
so `_blocks == []` and `context_text == ""` on **every one of the 120 questions**. With
an empty context, `looks_fabricated()` reduces to "does the answer contain any numeral
≥ `MIN_INTERESTING`" (`src/grounding.py:31`, `MIN_INTERESTING = 100`); `is_sum_of`
cannot rescue anything because the set of present numbers is empty.

**Verified against this run's own output, not inferred:**

- `raw/worker_answer.log` contains **32** occurrences of
  `note: every figure in the answer is absent from the files read; returning not-found
  instead`, plus 5 occurrences of the model's own `not_found=true` normalisation.
  32 + 5 = **37 = the exact `not_found` count in `answers.jsonl`.** Every abstention in
  this run is accounted for, and 32 of 37 (86%) were manufactured after generation.
- Decisive test: **zero of the 79 surviving non-empty answers contain a numeral ≥ 100**
  (`grounding.numerals()` returns `[]` for all 79), and `looks_fabricated(answer, "")`
  returns False for 0 of 79. The guard has not merely fired often — it has removed
  *every single* receipt-scale figure the model produced, with no exceptions in either
  direction.

So the causal chain from indexing to the headline failure is fully closed and every
link is measured on this run's artifacts: **image-only index → zero text blocks →
`context_text == ""` → any answer with a number ≥ 100 deleted.** Receipt totals are
mostly ≥ 100. That is the run's headline failure, and its first link is an indexing
gap, not an answering bug.

The prior report's correction still stands and is worth restating: the VLM *did*
receive every retrieved receipt as pixels, so it was not answering from nothing. What
is missing is textual **grounding**, citation surface, and lexical retrieval — not
context.

---

## 7. Isolation (brief item 4)

`run.json` claims `real_appdata_untouched: true`, `cache_model_blobs_unchanged: true`,
cache 152 files / 21,540,575,951 bytes before and after. I re-verified independently
at audit time rather than trusting the field:

- **Shared model cache:** re-running `envctl.cache_fingerprint()` now returns
  `{'files': 152, 'bytes': 21540575951}` — byte-identical to both `cache_before` and
  `cache_after`. Nothing downloaded during the run, and nothing has changed since.
  (Note the run *did* run online — `HF_HUB_OFFLINE` is deliberately unset, `envctl`
  l.192-203 — so this is a real result, not a tautology.)
- **Real app data dir** (`~/Library/Application Support/Magpie`): its `manifest.json`
  holds **39 entries, none of them under `Magpie-eval-corpora`** — all are the user's
  own `~/Desktop/Mri/...` files — and its mtime is Aug 27 03:05, two days before this
  run. `settings.json` (Aug 29 02:23) and `indexing_rules.json` (Aug 29 02:48) both
  predate the run's 04:18 local start. The real dir's `summaries/` directory is
  populated for the user's own corpus and was untouched.
- **The index cache mount cannot have written to either.** The mount writes only to
  `run_dir/raw/{appdata,qdrant}` (`run.py:169-173`), and the run's Qdrant is a private
  process with `QDRANT__STORAGE__STORAGE_PATH` pinned inside the run folder on port
  6533 (`backend.py:71-88`), well away from the app's 6433. `MAGPIE_DATA_DIR` pointed
  at the run's scratch appdata for every phase and the worker asserts it after
  `load_dotenv` (`worker.py:_assert_controlled_env`).
- **One caveat, stated rather than glossed:** `appdata_fingerprint()` is size+mtime, not
  content — its own docstring says so — and it excludes `cache/`, `bin/` and `logs/`.
  A same-size, same-second overwrite would be invisible. The independent manifest check
  above is stronger evidence than the fingerprint for the specific question "did the
  eval write its corpus into the user's app?", and the answer is no.

**Isolation is intact. The cache mount did not touch the real app data dir or the
shared model cache.**

---

## 8. Re-examining prior finding #6: "no summary tier on image corpora — by design"

**The mechanism the prior report described is correct** and I re-confirmed the chain:
`.jpg` is in `IMAGE_EXTS` (`src/content.py:24`) and therefore in `SUPPORTED_EXTS`
(`content.py:74`), so all 148 survive the extension filter; `route_file` sends every
image to `"fast"` (`src/stage1_fast/router.py:110-111`); `pipeline.py:312` passes
`skip_fast_tier=True`, which strips exactly those files at
`src/stage1/summarize.py:789-796`, leaving an empty list and a `sys.exit`. It is tier
mutual exclusion, not an unsupported extension. The harness absorbs it by string-match
(`worker.py:189`).

**"By design" describes the code, but it is not an adequate description of the
product's position, and this run makes that concrete in a way the prior one could not.**
Three things now sit on the record:

1. **100% of retrieval on this corpus rides on the fast tier alone.** Not 97%, not
   "mostly": 1440/1440 sweep hits and 375/375 `ask()` hits are `tier: "fast"`, and the
   `summaries` collection was probed 240 times and does not exist. There is no
   redundancy anywhere in the stack for an image corpus.
2. **The design decision has a measured cost, not a theoretical one.** §6 shows the
   groundedness guard deleting every receipt-scale figure the model produced — 32
   answers — because "no summary tier" and "no text blocks" are the same fact. §5.3
   shows two rank-1 retrievals that a single indexed line of text would have fixed. The
   `(visual match — page N)` placeholder means the user is shown no evidence for any
   answer.
3. **The config lies about what ran.** `index_summary_tier: true` is stamped into
   `run.json` and into the index store's `meta.json` and `index_params_hash`, where it
   is one of only four keyed parameters — for a dataset where it is a guaranteed no-op.
   Flipping it to `false` would produce a byte-identical index under a different key.

So: by design, yes — but it is a gap worth closing, and the sharpest argument is that
the design intends the summary tier to be the *text* half of a two-tier system, and on
image corpora Magpie has no text-producing index path at all. The prior report's
recommendation (route images through a VLM transcription pass, ~148 × 3 s here, and
ingest the result into `summaries`) remains the single highest-value change available,
and this run adds the guard-interaction evidence that makes it a correctness fix rather
than a quality improvement.

Two adjacent defects the prior report raised are unchanged and still worth fixing:
`sys.exit` as control flow inside a library function forces the harness to string-match
a human-readable message (`worker.py:189`), and it aborts the rest of `sync_files`
(`pipeline.py:315`) so no tier-timing split is ever recorded.

---

## 9. What I could not verify, and why

- **Per-file patch counts for 139 of 148 points.** Qdrant's quantized segments expose
  patch counts only in aggregate (`quantized.meta.json`'s `vector_parameters.count`);
  I recovered exact per-point counts for just the 9 points in the unquantized mutable
  segment. So "725-771 patches/page" is exact for 9 files and a segment-level mean
  (734.8-752.1) for the rest. Reading per-point counts would require starting Qdrant
  against a copy of the store, which I did not do.
- **The actual vector *values*.** I verified point count, payload, dimensionality
  (132 bytes/patch = 128 int8 + 4) and end-to-end retrieval behaviour, but I did not
  re-encode any receipt and compare embeddings. A cached index whose vectors were
  subtly wrong but structurally perfect would not be caught by anything here except the
  functional check in §1.4 — which does constrain it hard (hit@1 = 0.79 across 106
  gold-bearing questions is not what a corrupted embedding space produces).
- **Which encoder built the index.** `~/.cache/notspotlight/device.json` currently reads
  ColQwen2.5-v0.2/mps/float16 and its mtime (Aug 20) predates both runs, so it almost
  certainly is what ran. But nothing in `meta.json`, `run.json` or the collection
  records it, so this is inference from an unversioned cache file, not provenance. §2.3.
- **The `.DS_Store` question in reverse.** I confirmed `.DS_Store` was not indexed, but
  I did not test what would happen if a corpus contained a file with a fast-tier
  extension that PIL cannot open — no such file exists here, and `run_fast_batch`'s
  per-file `except` would record it as an error rather than skip silently.
- **The 428.1 s rebuild figure** is the prior run's harness-measured wall clock,
  reported not reproduced; I did not rebuild the index (and was asked not to write into
  `eval_harness/indexes/`).
- **Nothing in `src/` or `eval_harness/indexes/` was modified.** All measurement was
  read-only, except a 0.24 s `copytree` into the session scratch directory (deleted)
  and one in-process `build_content_blocks` probe under a scratch `MAGPIE_DATA_DIR`.

---

## 10. Recommendations, in priority order

1. **Key the index on the corpus, not on the dataset's name** (`run.py:49-51`). Mix in a
   digest of `manifest.json`'s `files[]` (name + sha256) and the resolved
   `dataset_dir`/`corpus_root`. On a hit, spot-verify a sample of file hashes against
   disk before mounting. The hashes are already loaded at `run.py:67` and currently
   used for nothing but a basename check. This closes the one failure mode the dataset's
   own manifest documents a trigger for. **§2.1**
2. **Key the index on the visual encoder, and record it.** Stamp the resolved
   `DeviceConfig` (`model_id`, `dtype`, `device`) into `meta.json` and `run.json`, and
   mix `model_id` into the key. ColQwen2.5 and ColSmol are both 128-dim, so a switch
   fails silently rather than loudly, and `device.json` sits outside every isolation
   fingerprint the harness has. **§2.3**
3. **Give image corpora a text tier.** One VLM transcription per image, ingested into
   `summaries`. It is the single change that fixes lexical retrieval, the
   `(visual match — page N)` citation surface, and the groundedness guard's empty
   `context_text` at once. On this corpus that is the difference between 32 deleted
   answers and 0. **§6, §8**
4. **Make groundedness vision-aware** (`src/answer.py:887-889`) — or at minimum stamp
   `strict_grounding_context_chars: 0` into the run record so a run whose guard operated
   on an empty string is self-evidently marked. As shipped, the guard is a correctness
   regression on every image-only corpus and nothing in the artifacts says so. **§6**
5. **Escalate the SHA-drift warning.** Add `index_store.sha_drift: bool` next to
   `built_under_sha`, surface it in `report.md`, and consider requiring an explicit flag
   to mount across a `src/` change. A stderr `print` is not a control. **§3**
6. **Publish an index-only snapshot.** Snapshot after the index phase, or exclude
   `appdata/logs/` and `settings.json` from the store, so mounting runs stop inheriting
   another run's LLM logs and query-side settings. **§2.5**
7. **Make the publish atomic** — `rmtree` + `replace` has a window that a parallel
   `--slot` run can land in. **§2.6**
8. **Populate `content_hash` at index time** (`index.py:141`); change detection is
   size-only (`index.py:111`), so Magpie cannot detect the byte-identical duplicates that
   forced the manual 150→148 dedup. **§1.1**
9. **Low severity: fix two comments.** `src/stage2/fast_db.py:46` says 1030 patch
   vectors per page; measured 744 (725-771). `eval_harness/harness/worker.py:186` cites
   `src/stage1/summarize.py:603`; the `sys.exit` is at `:796`. **§5.1, §8**
10. **Consider auto-cropping to the content bounding box before encoding.** 12/148 files
    spend 65-88% of a fixed ~750-patch budget on blank paper. No retrieval penalty is
    measurable on *this* corpus (§5.4), so this ranks last — but it is cheap and the
    measurement is now on record.
