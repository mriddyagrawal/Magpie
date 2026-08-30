# REPORT — INDEXING (mounted index, not a build)

Run: `20260830T121044Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-rewrite`
Baseline / index builder: `20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
Store entry: `eval_harness/indexes/66974090bdcd62e6/` (built 2026-08-30 by the baseline, backend SHA `cca67570`)
Scope: this run performed **no indexing**. It mounted the baseline's cached index (`run.json` `index_store.hit: true`, `built_under_sha` == this run's `backend_git_sha`). All build-time root causes — fp16 NaN embeddings (24 files), the Qdrant 32 MiB body cap (1 file), 3 golden pairs with gold never indexed, one-upsert-per-file amplification — are established in the **baseline's `REPORT-indexing.md`** and are not re-derived here. This report verifies that the same index, with the same losses, is what this run served, and audits the risks specific to mounting.

Audit method: byte-level diffs of the store entry against this run's `raw/` trees, plus a full scroll of the collection by booting the bundled binary (`frontend/src-tauri/binaries/qdrant-aarch64-apple-darwin`) on a **scratch copy** of the store's qdrant dir. No run or store file was modified.

---

## 0. Executive summary

- **The mount is intact.** This run's Qdrant served a collection byte-identical to the store entry: 709 points, 520 distinct files, manifest md5-identical across store, this run, and the baseline. Zero index-build work happened: no index phase in `run.json`, no `worker_index.*` artifacts, and `raw/qdrant.log` contains **zero write requests** — 720 requests, all read-side, all HTTP 200.
- **The losses carried over exactly.** The 25 build-dropped files are absent from the served collection (recomputed independently: 545 corpus files − 520 manifest = the same 25 names as baseline §2.6). The 3 doomed golden pairs (`rcpt-07`, `study-05`, `study-10`) still have `first_gold_rank: null` — **6 of 120 items (5.0%) unanswerable for index reasons alone, identical to baseline**.
- **No mount-time poison found.** All 520 payload paths resolve on this machine and sit under the corpus root; no corpus file changed since the build (0 size mismatches, newest corpus mtime predates the build); qdrant.log shows only 3 benign startup warnings.
- **Mounting introduced provenance gaps.** Nothing in this run records which retriever family embedded the queries or built the index (`col_model_resolved` is never written on the mount path); the store `meta.json` records only the raw `col_model: "auto"`, contradicting the code comment that claims otherwise; mount wall time is excluded from `wall_s_total`; the progress sidecar has no index phase entry.
- **Cost of the mount: about one second and 790 MB of duplicated disk**, versus the baseline's 2514.3 s build.

---

## 1. Mount integrity

**What mounting does** (`eval_harness/harness/run.py:175-207`): if `--rebuild-index` is not passed and `eval_harness/indexes/<key>/meta.json` exists, the harness `shutil.copytree`s the store's `appdata/` and `qdrant/` into the run's `raw/` (lines 180-184), stamps `index_store: {key, hit: true, built_under_sha}` (186-189), and skips the entire build block (`if not index_mounted:` at line 219). A run-private Qdrant is then started on `raw/qdrant` (lines 209-217, `backend.py:52+`). The store entry itself is never served directly and never written — republish is gated on `not index_mounted` (run.py:349), so a mounted run cannot mutate the store. A SHA-drift warning (191-197) did not fire here: `meta.json` `backend_sha` and this run's `backend_git_sha` are both `cca67570b04adce9980575d367f3cb9a6836a800`.

**Zero build work, verified three ways:**

1. `run.json` `phases` contains only `answer` and `retrieve`; the baseline's contains `index` (2514.3 s, 520 manifest entries) as well. `col_model_resolved` and `phases.index` are only ever written inside the build branch (run.py:229-235), which never executed.
2. `raw/` contains no `worker_index.log`, `worker_index_payload.json`, or `worker_index_result.json` (all three exist in the baseline's `raw/`).
3. `raw/qdrant.log` request tally — **zero PUT/DELETE of any kind**:

   | request | this run | baseline |
   |---|---|---|
   | `PUT /collections/fast_tier` (create) | 0 | 1 |
   | `PUT /collections/fast_tier/index` | 0 | 1 |
   | `PUT /collections/fast_tier/points` (upserts) | **0** | 545 (520 HTTP 200 + 25 HTTP 400) |
   | `POST /collections/fast_tier/points/query` | 240 | 240 |
   | `GET /collections/fast_tier/exists` | 240 | 241 |
   | `GET /collections/summaries/exists` | 240 | 240 |

   All 720 of this run's requests returned HTTP 200. The requests that DO appear are exactly the query workload: 120 questions x 2 passes (120 queries timestamped inside the answer window 12:10:45-12:45:19Z, 120 in the retrieve window) plus two per-`ask()` existence probes — `fast_tier` (exists) and `summaries` (does not exist in this index; the store holds only the `fast_tier` collection, consistent with the baseline's zero-summaries finding). At startup the log shows a **load, not a creation**: `Loading collection: fast_tier` ... `Recovered collection fast_tier: 1/1 (100%)` (12:10:45.1Z).

**Identical collection, verified at the byte level and by content:**

- `diff -rq` store `qdrant/` vs this run's `raw/qdrant/`: identical except `collections/fast_tier/0/temp_segments` — an **empty** scratch directory present only in the store, which Qdrant removes during shard recovery at load. After 35 minutes of serving, not one storage byte differs, because the harness sent no writes and Qdrant mutates storage only on writes.
- `appdata/manifest.json` is md5-identical (`ef9d0b1ecfa739cbad4f0a16e4f7458c`) across the store entry, this run's `raw/appdata`, and the baseline's `raw/appdata`: **520 entries**, matching baseline `run.json` `phases.index.manifest_entries: 520`. The only `raw/appdata` deltas are two LLM logs this run's own passes wrote and `settings.json` flipping `rewrite_default: false -> true` — precisely this arm's single knob, written by the app at runtime.
- Booting a scratch copy of the store's qdrant: `points_count` **709**, distinct `source_path` **520**, `indexed_vectors_count` 684 (the baseline's benign below-HNSW-threshold detail), status green, same vector config (128-dim cosine multivector, max_sim, int8 scalar quantization, on-disk). Manifest<->collection is a perfect bijection (0 files either way); every file's page set matches its manifest `fast_pages`; sum = 709. Since the served tree is byte-identical to this, these numbers are what this run served.
- From the response side: the **380 distinct paths retrieved across both passes** (answers.jsonl + retrieve.jsonl) are all members of the 520-file manifest; nothing outside the mounted index was ever surfaced.

## 2. Same-loss carryover

Recomputed independently of the baseline report: 545 corpus files on disk minus the 520 manifest entries = 25 files, name-for-name the baseline's §2.6 list (7 `CseGyan-Cpp-Notes-*`, 7 `electric-charge-and-field-*`, 9 `receipt_0*`, `scan_nglg0227.pdf`, `scan_zxjd0228.pdf`). **All 25 are absent from the served collection** (0 leaked points), and the doomed pairs' gold files (`receipt_040.jpg`, `electric-charge-and-field-9.pdf`, `CseGyan-Cpp-Notes-17/18/19.pdf`) are in the collection = false, in the manifest = false, on disk = true.

In `answers_enriched.json`, all six items have `retrieval.first_gold_rank: null`, exactly as in the baseline:

| qa_id | this run | baseline | top-2 retrieved this run |
|---|---|---|---|
| `rcpt-07-typed` | wrong | false_abstain | `receipts_degraded/bad_receipt_013.jpg`, `receipts_phone/receipt_005.jpg` |
| `rcpt-07-full` | false_abstain | false_abstain | `receipt_005.jpg`, `receipt_007.jpg` |
| `study-05-typed` | wrong | wrong | `electric-charge-and-field-10.pdf`, `-7.pdf` |
| `study-05-full` | wrong | wrong | same |
| `study-10-typed` | wrong | wrong | `scene_text/scene_70a4e0de3ea8509c.jpg`, `receipts_degraded/bad_receipt_005.jpg` |
| `study-10-full` | wrong | wrong | `CseGyan-Cpp-Notes-14.pdf`, `-15.pdf` |

Retrieval fills the slots with indexed siblings of the missing gold — the expected signature of gold-absent-from-index, not of a ranking failure. **Eval impact is identical to the baseline: 6 of 120 items (5.0%) doomed by the index.** The verdict labels differ slightly (5 wrong + 1 false_abstain here vs 4 + 2 in the baseline); that is generation noise on unanswerable items — do not read the `rcpt-07-typed` false_abstain->wrong flip as a rewrite effect on answerable content.

## 3. Mount-specific poison risks

- **Payload path resolution: clean.** All 520 `source_path` payloads are absolute paths under this machine's corpus root (`eval_harness/datasets/custom_dataset_rahul_Aug30/corpus`), and all 520 resolve (`os.path.exists`), so answer-time page rendering could always open the retrieved file. Expected — same machine as the build — but this is the check that will fail first if the store is ever copied to another machine or the dataset is re-prepared at a different path, since the index stores **absolute** paths.
- **qdrant.log: nothing beyond benign startup noise.** Exactly 3 WARN lines (`Config file not found: config/config`, `config/development`, missing web-UI static folder) plus a jemalloc note — inherent to running the bare bundled binary; zero ERROR lines; zero non-200 responses.
- **Staleness: none detected, but the detection is weak by construction.** No corpus file was modified after the build (newest corpus mtime 04:44 local; build started 05:57); all 520 manifest `size` values match today's on-disk sizes. However, **all 520 manifest entries have `content_hash: null` and `mtime: null`** (the baseline's §3 caveat, now frozen into the store): an in-place edit that preserves file size would be undetectable, and the mount path performs no corpus revalidation of any kind — the key (`run.py:55-57`) hashes dataset name + index-side params, never corpus content. Today's cleanliness is verified fact; future cleanliness is only convention.

## 4. Provenance gaps introduced by mounting

- **`col_model_resolved` is nowhere in this run.** The baseline `run.json` stamps `"colqwen2_5"` (written from the index worker at run.py:229 — build path only). This run's `run.json` never gets the key (absent, i.e. null when queried). Neither `worker_answer_result.json` nor `worker_retrieve_result.json` records a family (their `resolved_env` shows only `MAGPIE_COL_MODEL: "auto"`), and neither worker log mentions colqwen/colsmol/device at all. **No artifact of this run states which retriever family embedded its queries or built the index it queried.**
- **The store meta does not carry it either, contrary to the code's own comment.** `run.py:47-51` says "the RESOLVED family additionally lands in run.json and the index store meta" — but the publish block (run.py:358-365) writes only the raw `index_side_params`, so `indexes/66974090bdcd62e6/meta.json` says `col_model: "auto"`. The comment describes an intent that was never implemented.
- **Cross-machine (or cross-time) mixing is therefore possible and would be silent.** The index key hashes the raw param value `"auto"`, so two machines whose auto-detection resolves to different families produce the **same key**. If the `indexes/` store were synced, or this machine's resolution changed (device.py's auto branch is hardware-dependent; the baseline report pins this build to the MPS branch at `src/stage1_fast/device.py:244`), a run would mount one family's vectors and query them with another family's encoder — same 128-dim shape, no error, garbage scores, and no stamped field anywhere to catch it in audit. It did not happen here (same machine, same backend SHA, and retrieval hit@1 0.856 is sane), but that safety is circumstantial, not recorded.
- **Recommendation (prose only):** at publish, stamp the resolved family (family + model id + dtype/device) into store `meta.json`, making the run.py:47-51 comment true; at mount, resolve the query-side family and write it into `run.json` as `col_model_resolved` exactly as builds do, and hard-fail (or at least warn as loudly as the SHA-drift branch at run.py:191-197) when it differs from the store's recorded family. Additionally stamp a `phases.index = {mounted: true, wall_s, manifest_entries}` entry so mounted runs carry the same accounting shape as builds.
- **`phases.index` is absent and mount time is unaccounted.** `t0` starts at run.py:214, **after** the copytree, so `wall_s_total` (2119.7 s) = answer 2073.8 + retrieve 45.3 + 0.6 s of qdrant boot/teardown — the mount appears in no timing field. (Symmetric gap on builds: the store-publish copy at run.py:349-369 runs after `wall_s_total` is stamped at line 317.) The progress sidecar (`raw/progress.json`) also has **no index phase entry**, although current `run.py:199` writes one on mount ("mounted from store"); the missing entry is exactly the "watch-page grey-index bug, 2026-08-30" named in the comment at run.py:203-206, so this run most plausibly predates that fix (not confirmable here — git inspection was out of scope for this report). Mitigations that do exist: `index_store {key, hit, built_under_sha}` is stamped in both `run.json` and `metrics.json`, so the mount itself is discoverable.

## 5. Timing and disk

- **Mount cost: about one second.** Bounded by timestamps: `progress.json` `started_utc` 12:10:44Z (written before the copy) to the first qdrant log line 12:10:45.1Z — the two isolation fingerprints plus the ~790 MB copytree fit in <= 1.1 s. First query at 12:10:58Z (the gap is answer-worker spawn and query-encoder load, not the mount).
- **Versus the baseline build: 2514.3 s** (`phases.index.wall_s`), a >2000x saving; run totals 2119.7 s vs 4996.3 s.
- **Where it shows up: only in those timestamps.** No run.json field, no phases entry, no sidecar entry (§4).
- **Disk:** the store entry is **788 MB** (`du`: 787 MB `qdrant/` + 1.2 MB `appdata/`), and the mount duplicates it into the run (`raw/qdrant` 787 MB + `raw/appdata` 3.2 MB), so every mounted run permanently carries a full copy of the index in `runs/`.

## 6. Index-inherited failures to subtract downstream

`metrics.json` `retrieval.n = 104` (120 items − 16 `nf-*` abstention items). `hit@12 = 0.875` = 91/104, leaving **13 items whose gold never appeared at any rank** (`first_gold_rank: null`). They split cleanly:

- **Index-inherited — subtract from answer-quality and retrieval conclusions (6 items):** `rcpt-07-typed`, `rcpt-07-full`, `study-05-typed`, `study-05-full`, `study-10-typed`, `study-10-full`. Their gold was never indexed (§2); no query, rewrite, or generator change can recover them. They contribute 5 of the run's "wrong" and 1 of its "false_abstain" verdicts, and depress citation metrics.
- **Not index-inherited — property of this run's retrieval (7 items, all `-typed`):** `viz-02-typed`, `viz-07-typed`, `viz-08-typed`, `viz-10-typed`, `arch-05-typed`, `study-04-typed`, `phone-09-typed`. Verified: every gold and acceptable source of these pairs **is** in the mounted index (`chart_010.jpg`, `info_001.jpg`, `info_020.jpg`, `diagram_018.jpg`, `doc_357.jpg`, `CseGyan-Cpp-Notes-15/11/13.pdf`, `1167908324.jpg` all in the manifest and collection). The baseline's null set was exactly the 6 inherited items and nothing else, so these 7 are new under rewrite=true and belong to the retrieval report.
- **Adjacent, but not index data loss:** `study-08-typed`/`study-08-full` again retrieved gold `deck_027.pdf` at rank 1 (`first_gold_rank: 1`) and still failed (false_abstain / wrong) — the inherited answer-time page ceiling (gold on page 6, `ANSWER_MAX_PDF_PAGES = 5`; baseline §4.3). The index served those pages correctly; the answers report should discount this pair for the same structural reason, but it is not part of the 6.

## Open risks

1. **Family-blind mounts** (§4): the index key cannot distinguish retriever families resolved from `"auto"`, the store meta does not record the resolved family, and mounted runs stamp nothing — a synced store or a changed auto-resolution would silently mix incompatible embedding spaces.
2. **No corpus revalidation at mount** (§3): with `content_hash`/`mtime` null in all 520 manifest entries, a size-preserving corpus edit after a build would poison every future mounted run undetectably.
3. **Absolute payload paths** (§3): the store is machine-specific by construction; mounting it after a corpus move or on another machine yields an index whose every hit points at nonexistent files, failing at answer time rather than at mount time.
4. **Invisible mount accounting** (§4-5): no `phases.index`, no mount wall time, no sidecar entry — a reader of `run.json` alone must infer the index's entire history through the `index_store` pointer to another run's artifacts.
5. **Inherited defects persist unfixed** (§2): every mounted run of key `66974090bdcd62e6` re-serves the 25-file/55-page loss and re-dooms the same 6 items; the store has no notion of a superseding rebuild after the fp16/payload-cap fixes land. Baseline `REPORT-indexing.md` §6 lists the fixes; until an intentional `--rebuild-index` republishes the entry, comparisons on this dataset inherit the loss by design (which is also what makes the two arms cleanly comparable).
