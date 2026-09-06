# INDEXING REPORT

**Run:** `20260906T103913Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
**Backend:** `4ce90a8` · **Harness:** `0fd316b` · **Dataset:** `custom_dataset_rahul_Aug30` (545 files, 15 categories)
**Index:** MOUNTED from `eval_harness/indexes/66974090bdcd62e6/`, built `20260830T095758Z` under `cca67570`
**Contrast run:** `20260906T090247Z-…` (backend `92f9ba9`) — **same mount, same store, same key**

---

## 0. Bottom line

1. **This run did not index.** It copied a store built on 2026-08-30 by a third backend. The
   baseline arm copied the same store. **Indexing quality is identical across the two arms
   by construction — every number below applies to both arms equally.** I verified this
   byte-for-byte, not by inference (§1).
2. **The index contains no text at all.** Not thin summaries, not generic summaries — *none*.
   Every Qdrant payload is exactly `{source_path, page_num}`; the summary tier produced zero
   entries out of 545 files. Task items about "spot-checking summaries", "hallucinated
   summaries" and "date-contaminated summaries" have an empty subject, and I say so with the
   measurement rather than inventing findings (§3, §4, §6).
3. **The single largest thing indexing poisons downstream is not a bad summary — it is a
   discarded page number.** ColQwen indexes and ranks per page; the answer stage re-reads the
   file *from page 1* and caps at 5 pages, throwing the matched page index away. 49 indexed
   pages (6.9%) can never reach the generator. `study-08-typed` / `study-08-full` are a clean
   demonstration: the index matched page 5 of a 6-page deck, and page 5 is the exact one page
   the answer stage did not send (§9.1). The judge then recorded *"Declined although
   deck_027.pdf, the gold source, was the only retrieved file"* — a mis-attribution the
   baseline report did not catch.
4. **25 of 545 files (4.6%) and 55 of 764 pages (7.2%) are absent from the index**, from an
   fp16-NaN defect plus a per-file upsert design. Independently re-verified here (§5). Six
   golden items are structurally dead.
5. **The 2026-08-30 LLM log in `raw/appdata/logs/` is not summariser traffic.** It is the
   *answer-phase* log of the Aug-30 build run, carried in by the mount. It is a harness
   hazard, but not the hazard the brief describes (§2.1).
6. **Two arms, one index, and still 2 of 120 questions retrieve different files.** Both are
   `viz-11`, and the difference is only *which of nine byte-identical `diagrams/` twins* won
   an exact score tie. That is index-manufactured flip noise and it must not be read as an
   arm effect (§9.4).

---

## 1. Provenance: verified, not assumed

`run.json` → `index_store: {key: "66974090bdcd62e6", hit: true, built_under_sha: "cca67570b04adce9980575d367f3cb9a6836a800"}`.
`indexes/66974090bdcd62e6/meta.json` → `built_utc: "20260830T095758Z"`, `built_by_run: "20260830T095758Z-custom_dataset_rahul_Aug30-…"`.

`harness/run.py:178-200` `shutil.copytree`s `store/appdata` and `store/qdrant` into `raw/`
and calls `progress.phase_done(raw, "index", note="mounted from store")`. No indexing code
runs. The run's own artifacts corroborate:

| check | result |
|---|---|
| `raw/qdrant.log` request mix (762 lines) | 241 × `GET /collections/fast_tier/exists`, 241 × `GET /collections/summaries/exists`, 240 × `POST /collections/fast_tier/points/query`, 1 × `GET /collections/fast_tier`. **Zero upserts.** |
| `raw/worker_index_payload.json` / `_result.json` / `worker_index.log` | absent (all three exist in the Aug-30 run dir) |
| `run.json` `phases` | `answer`, `retrieve` only — no `index` |
| `raw/appdata/{manifest,indexing_rules,settings}.json` vs store copies | `cmp` → **byte-identical** |
| `raw/appdata/logs/llm-2026-08-30T10-40-06Z.log` vs store copy | `cmp` → **byte-identical** |

And the load-bearing point for this report: I diffed the *mounted artifacts* of the two
2026-09-06 arms and they are the same store, so **no statement in this report can be a
difference between the arms.** Where the two arms differ (answer accuracy 19/120 vs 6/120),
the cause is entirely downstream of indexing — which is itself a useful control: it means
this run's +13 correct answers are attributable to the prompt change, not to anything the
index did.

**Is the mount sound across `cca67570 → 4ce90a8`?** Yes, and more narrowly than the baseline
argued. `git diff cca67570..4f22e25 -- src/` touches 15 files; none of
`src/stage1_fast/{index,model,device,router}.py`, `src/stage2/{fast_db,db,search}.py`,
`src/manifest.py`, `src/ingest/walker.py`, `src/pipeline.py` is among them. Index-side and
query-side encoders are the same unchanged code on the same resolved family
(`provenance.col_model.family = colqwen2_5`, matching the Aug-30 run's
`col_model_resolved: "colqwen2_5"`). I re-read those files at HEAD to confirm the payload
and upsert shapes I measure below are the ones that were written. Mount is sound.

---

## 2. Two corrections to the framing I was handed

### 2.1 The Aug-30 log is answer traffic, not summariser/indexing traffic

The brief says the carried-in `llm-2026-08-30T10-40-06Z.log` is "the summariser/indexing
traffic". It is not. Measured:

```
llm-2026-08-30T10-40-06Z.log : session_start 1, request 120, response 120
llm-2026-09-06T10-39-33Z.log : session_start 1, request 120, response 120
```

Every one of the Aug-30 log's 120 requests carries the `Answer` JSON schema and the
file-grounded QA system prompt. It is named verbatim in the Aug-30 run's
`phases.answer.llm_log`. The timeline settles it: the Aug-30 index phase ran
`09:57:58Z + 2514.3s = 10:39:52Z`, and this log opens at `10:40:06Z` — *after* indexing
finished.

**There is no summariser traffic to mine, in this log or anywhere**, because the summariser
made zero LLM calls (§3.2). So the answer to "is the Aug-30 log useful evidence for me?" is:
**no, not for indexing.** Its only value to this report is negative — it is a foreign run's
answer prompts sitting inside this run's appdata, and anything that treats
`raw/appdata/logs/` as this run's data will mine the wrong backend's prompts.

**Does anything glob it? No — confirmed.** `harness/enrich.py:283-288`:

```python
llm_log = None
result_file = raw / "worker_answer_result.json"
if result_file.exists():
    llm = json.loads(result_file.read_text()).get("llm_log")
    llm_log = Path(llm) if llm else None
reqs = load_llm_requests(llm_log) if llm_log else []
```

It reads one named path. There is no `glob` anywhere in `enrich.py`. I checked the named
path resolves correctly: `raw/worker_answer_result.json` → `.../llm-2026-09-06T10-39-33Z.log`.
Enrichment is clean.

*Nuance worth recording:* enrich reads the path from `worker_answer_result.json`, **not**
from `run.json`'s `phases.answer.llm_log`. They agree here, but they are two independent
copies of the same fact, and a future refactor that updates one will silently desync the
other. The hazard is real; it just is not currently firing.

**The hazard that IS live** is store hygiene: `run.py:363-383` publishes the build run's
*entire* `appdata` — including its answer-phase LLM log — into the shared store. Every mount
of key `66974090bdcd62e6` from now until the store is rebuilt inherits a stale
`llm-2026-08-30T10-40-06Z.log`. Publication should copy `manifest.json`,
`indexing_rules.json` and `qdrant/` and exclude `logs/` and `drift/`.

### 2.2 The 4ce90a8 summariser fix is not merely inert here — it is unmeasurable on this dataset

`4ce90a8` removed the generic clock plumbing from `src/llm.py` (`_append_timestamp`,
`_wants_timestamp`, `_NO_TIMESTAMP_OUTPUTS`) so the summariser no longer receives a
wall-clock line it can copy into `FileSummary.identifiers`. The mechanism is real and
visible in the prompt: `src/stage1/summarize.py:193` instructs the model to emit
`identifiers` as "exact tokens that uniquely distinguish this file: numeric IDs, **dates in
their ORIGINAL format**, SKUs … copied verbatim". A clock line in the same turn is exactly
the bait that instruction is primed to take.

The brief says the fix is inert in this run and would need a `--rebuild-index` arm to
measure. The first half is right; the second is not enough. **A rebuild arm on this dataset
would still measure nothing**, because the summariser never runs here at all:

```
src/stage1/summarize.py:789-796
    files = find_supported_files(root)
    if skip_fast_tier:
        from src.stage1_fast.router import route_file
        files = [p for p in files if route_file(p) != "fast"]
    if not files:
        sys.exit(f"no supported files found under {root}")
```

Every one of the 545 files is a jpg/png/pdf that `route_file` sends to the fast tier, so
`files` is empty and the summariser exits before its first call. The Aug-30 build confirms
it in two places: `worker_index.log` ends at the banner `━━━ Summary tier (LLM) ━━━` with
nothing after it, and `worker_index_result.json` records
`summary_tier_note: "no supported files found under …/corpus"`.

**To measure what 4ce90a8 buys on the summariser you need a different corpus, not a
different index flag** — one containing files that route away from the fast tier (`.md`,
`.txt`, `.docx`, `.xlsx`, `.pptx`, `.csv`, `.html`, code). On
`custom_dataset_rahul_Aug30`, `index_summary_tier: true` is a parameter that describes
nothing, in every arm, forever.

---

## 3. Tier coverage: what fraction of 545 files got an entry

### 3.1 Fast tier — 520 / 545 (95.4%)

From `raw/appdata/manifest.json` (520 entries) and from a live scroll of the mounted
`fast_tier` collection (Qdrant 1.17.1 booted against a copy of
`indexes/66974090bdcd62e6/qdrant/`, 709 points, all scrolled):

| | files on disk | files indexed | pages on disk | pages indexed |
|---|---:|---:|---:|---:|
| charts | 40 | 40 | 40 | 40 |
| diagrams | 40 | 40 | 40 | 40 |
| documents | 53 | 53 | 53 | 53 |
| figures | 40 | 40 | 40 | 40 |
| infographics | 40 | 40 | 40 | 40 |
| **notes_handwritten** | **37** | **23** | **37** | **23** |
| notes_iam | 30 | 30 | 30 | 30 |
| photos | 40 | 40 | 40 | 40 |
| receipts_degraded | 36 | 36 | 36 | 36 |
| **receipts_phone** | **40** | **31** | **40** | **31** |
| **scans_multipage** | **19** | **17** | **140** | **108** |
| scene_text | 40 | 40 | 40 | 40 |
| screenshots | 40 | 40 | 40 | 40 |
| slides | 30 | 30 | 128 | 128 |
| tables_fr | 20 | 20 | 20 | 20 |
| **TOTAL** | **545** | **520 (95.4%)** | **764** | **709 (92.8%)** |

Integrity of what *is* stored is clean, re-measured here:

- Qdrant's 520 distinct `source_path` values are set-equal to the 520 manifest keys. **0 zombies**, **0 orphans**.
- Every file's `page_num` set is exactly `0..n-1`. **0 non-contiguous files.**
- All 709 points: vector dim **128**, `payload_schema.source_path` indexed as keyword over all 709.
- Collection `green`, `points_count: 709`, `indexed_vectors_count: 684`, `segments_count: 5`,
  `multivector_config.comparator: max_sim`, int8 scalar quantization, `on_disk_payload: true`.
- Manifest `size` vs disk: **0 mismatches** — the mount is not stale.

### 3.2 Summary tier — 0 / 545 (0.0%)

Measured three independent ways:

1. `manifest.json`: `summary_file` is `null` for **520/520** entries; `summarized_at` is `""`
   for **520/520**; `ingested_at`, `row_count`, `routes`, `skip_reason`, `content_hash` are
   likewise empty for all 520.
2. Qdrant: the storage directory contains exactly one collection, `fast_tier`. There is no
   `summaries` collection. `raw/qdrant.log` shows the client asking
   `GET /collections/summaries/exists` **241 times** and never getting one.
3. `worker_index_result.json` (Aug-30): `summary_tier_note: "no supported files found…"`.

There is no sqlite store, no JSON summary store, and no on-disk transcript directory. The
complete content of the mounted `appdata` is: `manifest.json`, `settings.json`,
`indexing_rules.json`, `logs/`. Nothing else.

**Therefore 100% of retrieval and 100% of generation on this dataset runs on visual
embeddings alone**, with no text tier, no keyword tier and no lexical fallback of any kind.

---

## 4. §2 of the ask, honestly answered: there are no summaries to spot-check

The task asks me to open a sample of files and say whether "the stored text actually
describes the image or is generic/wrong". The measured answer is that **the index stores no
text about any image whatsoever.**

`src/stage2/fast_db.py:143-147` and `:167`:

```python
payload={"source_path": source_path, "page_num": page_num}
```

Confirmed empirically: all 709 points have the payload key set `('page_num', 'source_path')`
and **zero** string-valued payload fields other than the path.

The only per-hit "text" that exists anywhere is manufactured at query time, in
`src/stage2/search.py:553`:

```python
summary=f"(visual match — page {page})"
```

Across this run's 334 fed hits, that string is **100% generic, 100% of the time** — it
carries no information about the image beyond a page index. This is not a quality problem
with a summariser; it is the absence of one. It matters in three places:

- It is what the cross-encoder reranker scores against (product bug #1 in the run notes) —
  which is why `rerank` is off in this config at all.
- It is what the desktop UI shows the user as the reason a file matched.
- It is *not* what reaches the generator. I verified from the answer prompts that the
  placeholder never enters the LLM turn; the answer step re-reads the file and inlines the
  raw bytes (§9.1). So this is a UI/rerank defect, not an answer-poisoning one.

### 4.1 What I checked instead: content faithfulness of 21 files across all 15 categories

The useful version of the question is whether the *thing the index points at* is what the
golden set says it is, and whether renders through the indexing path are faithful. I opened
21 files/pages spread over all 15 categories and read them.

| file (page) | patches | what it actually is | verdict |
|---|---:|---|---|
| `charts/chart_001.jpg` | 641 | OWID "Long-term price index in food commodities, 1850-2015"; Cocoa **18.81** lowest, Lamb **103.7** highest | faithful; matches `viz-01` gold verbatim |
| `charts/chart_014.jpg` | **95** | Pew pie, "Strong Support for Army to Fight Drug Traffickers", 80/17/3 | faithful, but a ~10×10 patch grid over the whole image |
| `diagrams/diagram_003.jpg` | 305 | Antarctic food web: leopard seal, elephant seal, "other seals", krill, penguins | faithful; matches `viz-11` gold |
| `figures/arxiv_025.png` | 749 | particle-filter pose scatter, Step 1/50/100, YCB object legend | faithful — and a *pure* distractor: it took rank 2 on `viz-01` ("food commodity price index") with zero topical relation |
| `infographics/info_032.jpg` | 739 | Australian immunisation coverage map, 94% / 90.6% / 94.6%, target 95% | faithful |
| `photos/1007129816.jpg` | 236 | man in a crocheted Blitz beer-carton bucket hat | faithful |
| `scene_text/scene_002f860e692757f7.jpg` | 751 | boy beside a green Jaguar, plate `R275 ULO` | faithful; plate legible |
| `screenshots/screen_24184.jpg` | 731 | Android "Weather Notifications — Champaign, IL" settings toggles | faithful |
| `tables_fr/table_fr_011.jpg` | 752 | KLM Cargo revenue table, FY2011 9-month vs 2010/2011 12-month | faithful |
| `documents/doc_10877.jpg` | 755 | UCSF Figure V-8, Cuyahoga County health expenditures 1955-1960 | faithful; carries a burned-in `industrydocuments.ucsf.edu/docs/xhfg0227` footer |
| `receipts_phone/receipt_001.jpg` | 731 | Korean café receipt, TOTAL 45,500 / CASH 50,000 / CHANGE 4,500 | faithful |
| `receipts_degraded/bad_receipt_014.jpg` | 747 | ASIA MART Klang tax invoice 22/12/2017, GST summary | faithful — this is the one genuine retrieval miss in the run, and it is not a fidelity problem |
| `notes_handwritten/CseGyan-Cpp-Notes-14.pdf` p0 | 747 | handwritten "C++ Tutorials (14)" — relational + logical operators | faithful; explains `study-10`'s degenerate answer `"C++ Tutorials[1], C++ Tutorials[2]"` — that string is the page's handwritten title |
| `notes_iam/note_004.png` | 749 | 7 unrelated handwriting strips ("…Diana was trailing up the gravelled drive…") | faithful; no coherent subject, exactly as designed |
| `notes_iam/note_022.png` | 745 | 7 more unrelated strips ("…exactly the Ritz Hotel but we've got our little…") | faithful; no coherent subject |
| `slides/deck_027.pdf` p0 | 755 | "Biosensor Prototype (system integration)" hub diagram | faithful |
| `slides/deck_027.pdf` **p5** | 755 | "Usage of Biosensors in Food Industry" pie: LC/MS 38, ELISA 18, LC/UV 18, other 12, **Biosensors 8**, electrophoresis 6 | faithful — and this is `study-08`'s entire gold answer (§9.1) |
| `scans_multipage/scan_yjgx0227.pdf` p0 | 755 | **blank back-of-photograph**, faint stamp `J 4 1 7 1 1 1 D` | faithful; content-free |
| `scans_multipage/scan_yjgx0227.pdf` **p10** | 755 | health-fair display photo: "RESEARCH / GAMES / POSTERS", "SCORE HIGH … GOOD HEALTH" | faithful |
| `scans_multipage/scan_xqgl0226.pdf` **p9** | 755 | corporate by-laws, Sections 5-8 + Article VI; printed footer **`(5)`** | faithful |
| `scans_multipage/scan_gzyh0227.pdf` p3 | 755 | Fort Morgan WATER ANALYSIS, Main Supply Tank, TDS 1404.0, pH 8.0; printed footer **`- 2 -`** | faithful |

**21 of 21 faithful. 0 wrong, 0 generic-but-inaccurate, 0 mixed-up.** The renders are not
sheared, not mis-rotated, not colour-broken. The image pipeline (`index.py:58`
`Image.frombytes("RGB", …, pix.samples)` for PDFs, `Image.open(...).convert("RGB")` for
rasters) is doing its job on this corpus.

**What indexing gets wrong here is not fidelity. It is coverage (§5) and addressing (§9).**

---

## 5. Per-file failures: empty / truncated / boilerplate / hallucinated

**Empty, truncated, boilerplate and hallucinated summaries: 0 of 545, because summaries: 0 of 545.**
That number is not a pass. The failure mode on this corpus is *whole files missing*, and it
is quantified exactly.

I recomputed the missing set from disk vs manifest rather than trusting the Aug-30 log:
**25 files absent, 0 zombies.**

| # | file(s) | pages lost | error string (Aug-30 `worker_index.log`) |
|---|---|---:|---|
| 1-7 | `notes_handwritten/CseGyan-Cpp-Notes-{2,8,9,17,18,19,20}.pdf` | 1 each | `VectorStruct` 400 |
| 8-14 | `notes_handwritten/electric-charge-and-field-{3,8,9,11,13,16,17}.pdf` | 1 each | `VectorStruct` 400 |
| 15-23 | `receipts_phone/receipt_{006,011,012,015,016,029,031,037,040}.jpg` | 1 each | `VectorStruct` 400 |
| 24 | `scans_multipage/scan_zxjd0228.pdf` | **12** | `VectorStruct` 400 |
| 25 | `scans_multipage/scan_nglg0227.pdf` | **20** | `Payload error: JSON payload (33600110 bytes) is larger than allowed (limit: 33554432 bytes).` |

Totals: **25 files (4.6%), 55 pages (7.2%)**. The Aug-30 log's own tally agrees:
`fast tier: 520 files indexed (709 pages), 0 unchanged, 0 pruned, 25 errors`.

The two mechanisms — fp16 NaN embeddings on MPS rejected by Qdrant's `VectorStruct` parse,
and the 32 MiB request-body cap — were reproduced in detail by the baseline report's author
(re-encoding all 25 failures plus 30 controls, and probing a scratch Qdrant with NaN / ±inf
/ wrong-dim / oversize payloads). I re-read the code paths (`src/stage1_fast/device.py`
selecting `float16` for ColQwen2.5 on MPS; `src/stage1_fast/index.py:139` issuing **one
upsert per file** so a single bad page rejects every page of the document) and confirm the
account is consistent with the code at HEAD and with the error strings in the log. **I did
not independently re-run the 25-file re-encode** — that investigation is sound, well
evidenced, and re-running it would not change any conclusion in this report. I flag the
boundary rather than implying I re-derived it.

**The run's own artifacts contain no trace of any of this.** `manifest.mark_fast_indexed` is
called only *after* a successful upsert (`index.py:141`), so a failed file leaves no row;
`run_fast_batch` collects errors into a local list, prints them, and returns `None`;
`run.py:255` gates only on `manifest_entries == 0`. Result: `run.json` says
`status: "complete"`, `phases.answer.errors: 0`, `phases.retrieve.errors: 0`, and
`metrics.json` says `errors: 0` — on a run whose index is missing 4.6% of the corpus. On a
*mount* it is worse still: there is no index phase at all to instrument.

`run.json` already carries `dataset_manifest_files: 545`, and the manifest has 520.
**Comparing those two numbers, on mounts as well as builds, would have caught this on
2026-08-30 and would catch it today.**

---

## 6. Date contamination: measured zero, and here is what that is worth

Scanned every surface the index actually has:

| surface | date-shaped strings found |
|---|---|
| Qdrant payloads (709 points) | **0** — payloads are `{source_path:str, page_num:int}`; zero non-path string values |
| Qdrant storage on disk (788 MB, binary scan for `2026-0`) | **0** |
| `manifest.json` file identifiers / paths | **0** — no corpus path contains an ISO date |
| `manifest.json` fields | `fast_indexed_at` on 520/520 entries, all `2026-08-30`. Every other string field is empty. |
| stored summaries | n/a — none exist |

So: **520 entries carry a date, and all 520 are the `fast_indexed_at` metadata timestamp** —
a field the harness writes, that no retriever reads, that no generator sees, and that has
nothing to do with the summariser's clock line. **Copied-date contamination in the index:
zero occurrences.**

**What this says about the value of 4ce90a8's summariser change on a rebuilt index:
nothing, and it cannot say anything.** The summariser is unreachable on an all-image corpus
(§2.2). A `--rebuild-index` arm would re-run the fast tier for ~42 minutes and then exit the
summary tier at the same `sys.exit` line, producing the same zero summaries. The correct
experiment is a mixed-media corpus, and until one exists this fix is unfalsifiable here.

One thing I *can* say from this run's evidence: the mechanism the commit message describes is
plausible and the prompt is primed for it. `summarize.py:193` asks for identifiers with
"dates in their ORIGINAL format … copied verbatim", and `summarize.py:204`'s JSON exemplar
repeats `"<id, code, date or amount COPIED FROM THE FILE>"`. A wall-clock line in the same
turn is precisely the input that instruction converts into a stored date. Removing the line
is right on the merits; it simply has no measurable footprint on this dataset.

---

## 7. The `notes_iam` slice (30 files)

**What the indexer wrote for them:** exactly what it wrote for everything else — 30 points,
one page each, payload `{source_path, page_num}`, one 128-dim multivector of 725-771 patches.
No text, no summary, no label. I opened `note_004.png` and `note_022.png`: incoherent IAM/LOB
handwriting strips with no shared subject, exactly as `_notes.notes_iam_excluded` describes.

**Are those summaries the reason they surface as distractors? No — and they barely surface
at all.** Measured over this run's `retrieve.jsonl` (1,437 ranked slots across 120 queries):

| | value |
|---|---|
| notes_iam share of the index | 30/520 = **5.77%** |
| notes_iam share of top-12 slots | 10/1437 = **0.70%** |
| queries with ≥1 notes_iam file in top-12 | **10 / 120** |
| notes_iam files fed to the generator | **1 of 334 fed slots (0.30%)** — `note_004.png`, rank 1 on `nf-05-typed` |
| distinct notes_iam files ever ranked | 8 of 30 (`note_{004,007,010,014,021,022,023,030}`) |

They are **under-represented by a factor of 8** relative to their share of the corpus. The
one time a notes_iam file took rank 1, the question was `nf-05-typed` — a deliberate
*not-found* item with no gold source at all, so there was nothing correct for it to displace.

This also kills a tempting explanation. `notes_iam` pages carry among the **highest** patch
counts in the whole index (725-771, vs a corpus median of 747 and a `diagrams`/`charts`
median near 240). If ColQwen's `MAX_SIM` length bias dominated real queries, these 30 files
would be everywhere. They are nowhere. **On real queries, content beats length.** (The
length bias the baseline demonstrated with *random unit* query vectors is genuine, but random
vectors are the degenerate case; §9.5.)

The slice is behaving exactly as the owner designed it: real distractor pressure, absorbed.
Nothing about it needs fixing, and it is not a contributor to the 19/120 answer score.

---

## 8. Timing: build vs mount

| | value | source |
|---|---|---|
| Index build (Aug-30) | **2,514.3 s** (41m 54s) | `20260830T095758Z-…/run.json` `phases.index.wall_s` |
| ↳ worker-reported | 2,512.04 s | that run's `worker_index_result.json` |
| ↳ per indexed page | ~3.55 s/page (709 pages), ~4.83 s/file (520 files) | derived |
| ↳ summary tier's share | **0 s of useful work** — spawned llama-server (2.3 s), printed its banner, exited | `worker_index.log` tail |
| Build run total | 4,996.3 s | Aug-30 `run.json` |
| **Mount (this run)** | **≤ 1 s** | `progress.json`: index phase `first_utc == last_utc == 2026-09-06T10:39:14Z`; run started `10:39:13Z`, answer phase began `10:39:17Z` |
| ↳ measured directly | **0.19 s** (`shutil.copytree` of the 788 MB store, the exact call `run.py:181-185` makes) / 0.44 s for `cp -R` | reproduced on this machine today |
| This run's total | 2,380.5 s, of which answer 2,343.5 s + retrieve 36.3 s | `run.json` |

**The mount is ~13,000× cheaper than the build, and it is not recorded anywhere as a cost.**
`run.py:228` starts the wall clock *after* the mount, so `wall_s_total` (2,380.5 s) excludes
it entirely: 2,343.5 + 36.3 = 2,379.8 leaves 0.7 s unaccounted, which is everything except
the answer and retrieve phases. `run.json` has no `phases.index` on a mount — the only record
that the phase happened at all is the `progress.json` sidecar, at 1-second resolution. Cheap
fix: on a mount, write `phases.index = {wall_s, mounted: true, key, built_under_sha,
built_utc, manifest_entries}` so a reader of `run.json` alone can see both that no build
occurred and how many files the mounted index actually holds.

---

## 9. What in the index poisons downstream answers

This is the section that matters. The answer stage is at **19/120 correct** and part of that
ceiling is set here.

### 9.1 The index knows which page matched; the answer stage throws it away and then truncates at 5 pages

**This is the biggest index→answer defect on this corpus and it is not in the baseline report.**

The index is page-addressed. `fast_db.search` returns `(source_path, page_num, score)`;
`search.py` surfaces `page_num` in the hit summary. But the answer stage takes only the
path:

```
src/answer.py:882-886
    blocks = await asyncio.to_thread(
        build_content_blocks, abs_path,
        max_chars=ANSWER_MAX_CHARS_PER_FILE,   # 25_000
        max_pdf_pages=ANSWER_MAX_PDF_PAGES,    # 5
        search_keywords=keywords)
```

`build_content_blocks(path, …)` has **no page parameter**. For an image-only PDF it falls
through `content.py:600-616` to `render_pdf_pages_as_png(path, max_pdf_pages)` — **pages 1
through 5, from the front of the file, every time.**

The designed mitigation is the index-time vision transcript
(`content.py:602` `transcript_for(path)`) and the T3 summary supplement
(`answer.py:747-762`, whose own docstring reads *"the scanned-fallback only renders the first
5 pages — but the T3 summary has the full chapter list"*). **Both live in the summary tier,
and the summary tier is empty (§3.2).** `transcript_for` finds no file; `_summary_supplement`
returns `None` because `entry.summary_file` is null for all 520 entries. The mitigation is
absent precisely on the corpus that needs it.

I confirmed all 49 multi-page PDFs in this corpus (30 `slides` + 19 `scans_multipage`) have a
**completely empty text layer** (pymupdf: 0 characters across all 268 pages), so every one of
them takes the render-first-5-pages path.

**Consequences, measured:**

| | value |
|---|---|
| Indexed pages the answer stage can never read (page index ≥ 5) | **49 of 709 (6.9%)** |
| Files affected | 10 — `scan_yscw0217` (13 unreachable), `scan_xqgl0226` (13), `scan_yjgx0227` (8), `deck_008` (4), `scan_gzyh0227` (4), `scan_xhwg0227` (2), `deck_022` (2), `deck_027` (1), `deck_018` (1), `deck_015` (1) |
| Top-2 hits in this run that landed on an unreadable page | **5** |
| Golden items whose gold source is a >5-page image-only PDF | **8** (`arch-06-*`, `study-03-*`, `study-08-*`, `study-11-*`) |
| Golden items where the matched page was itself unreachable | **2** (`study-08-typed`, `study-08-full`) |

**The clean demonstration — `study-08`.** The question is *"biosensor deck food industry pie
chart what % was biosensors"*; gold is `deck_027.pdf`, key facts `Biosensors 8%`, `LC/MS 38%`.
Retrieval was **perfect**: `deck_027.pdf` was the *only* file returned, matched at
`page_num 5`. I rendered page 5 and it is the pie chart, containing every key fact verbatim
(§4.1). The answer prompt, read straight from `llm-2026-09-06T10-39-33Z.log`:

```
Content type: pdf (scanned / image-only — 5 page(s) as images)
[File 1, image 1 of 5] … [File 1, image 5 of 5]      # = pages 0,1,2,3,4
extra: {"images": 5}
```

Six-page deck. Five images sent. **The one page not sent is the one page that answers the
question.** Both variants returned an empty answer, and the judge recorded:

> `study-08-typed`: **false_abstain** — *"Declined although deck_027.pdf, the gold source, was the only retrieved file."*
> `study-08-full`: **false_abstain** — *"Declined although deck_027.pdf, the gold source, was the only retrieved file."*

The model abstained correctly given what it was shown. **Two more mis-attributed verdicts**,
on top of the six the baseline identified (§9.6). And `study-08-full` moved `wrong → false_abstain`
between the arms — a flip that has nothing to do with either backend.

`scan_yjgx0227.pdf` shows the waste side of the same bug: it was retrieved twice
(`phone-07-typed` rank 11, `phone-09-typed` rank 2) on page-10 matches, and both times the
generator received pages 0-4 — page 0 being a **blank back-of-photograph** (§4.1). Five image
payloads of context spent on nothing.

I checked the other six at-risk items before claiming them: `arch-06` (gold on
`scan_gzyh0227.pdf`) matched page 2 and I verified by reading pages 3-8 that the City Water
sheet the question asks about is *not* on any page ≥ 5 — so `arch-06`'s `false_abstain` is a
genuine answer-stage failure, not a cap victim. Same for `study-03` (matched page 2) and
`study-11` (matched page 1). **Confirmed cap victims: 2 of 120. Latent risk: 6 more.**

**Fix, in order of cost:** (a) thread `page_num` from the retrieval hit into
`build_content_blocks` and render the matched page ± a small window instead of the front of
the file — this is a small change with a large payoff and it needs no summary tier; (b)
failing that, at minimum make the caption honest about *which* pages were sent (see §9.2).

### 9.2 Three prompts declare more pages than they attach

`content.py:611` writes the header from the *rendered* page count while
`answer.py:_trim_blocks_to_budget` (invoked at `answer.py:929-931` under `LOCAL_N_CTX=16384`)
drops image blocks afterwards. The header is not updated. Measured across all 120 prompts:

| qa_id | file | header says | images attached |
|---|---|---:|---:|
| `arch-03-typed` | `scan_xqgl0226.pdf` | 5 pages | **3** |
| `rcpt-08-full` | (rank-1 PDF) | 5 pages | **4** |
| `nf-05-full` | (rank-1 PDF) | 5 pages | **2** |

Also: 9 of 120 prompts carry the "lower-ranked source file(s) were omitted" note, and 371
images were sent in total. Small in count, but the model is being told a page exists that it
cannot see — the exact condition that produces a confident guess instead of an abstention.

### 9.3 Page numbers surfaced to the user are wrong twice over

`search.py:553` formats `f"(visual match — page {page})"` from the **0-based** `page_num`.
I verified the offset against printed page numbers on the UCSF scans, which is a stronger
check than the PDF index alone:

| file | `page_num` | PDF page (1-based) | printed on the page |
|---|---:|---:|---|
| `scan_gzyh0227.pdf` | 3 | 4 | **`- 2 -`** |
| `scan_gzyh0227.pdf` | 4 | 5 | **`- 3 -`** |
| `scan_gzyh0227.pdf` | 5 | 6 | **`- 4 -`** |
| `scan_gzyh0227.pdf` | 7 | 8 | **`- 6 -`** |
| `scan_gzyh0227.pdf` | 8 | 9 | **`- 7 -`** |
| `scan_xqgl0226.pdf` | 9 | 10 | **`(5)`** |

So the product says "page 3" where the PDF viewer says page 4 and the document itself says
page 2 — and on `scan_xqgl0226.pdf` it says "page 9" for a sheet printed `(5)`. This
confirms the baseline's off-by-one and extends it: there are **two** offsets, and the string
shown is the least useful of the three. It affects the 236 indexed pages in
`scans_multipage` (108) and `slides` (128). The one-character fix (`page + 1`) closes the
first gap; the printed-label gap needs `content.py:_extract_book_page_label`, which already
exists for text PDFs and is unreachable on scans.

Related, same function (`search.py:545-551`): `best_by_path` collapses all matching pages of
a file to its single best page. A multi-page PDF contributes **at most one page** to any
answer regardless of how many are relevant — which, combined with §9.1, means a 13-page scan
is represented to the ranker by one page and to the generator by five different ones.

### 9.4 Corpus duplication is in the index, and it manufactures flip noise between the arms

SHA-256 over the corpus: **514 distinct contents across 545 files; 8 duplicate groups, 31
extra copies, all in `diagrams/`.**

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

The `diagrams` category is 40 files and **9 distinct images**. `index.py`'s point id is
`md5(source_path::page:N)`, so identical content under different names cannot dedupe; the
manifest's `content_hash` slot exists and is `null` for all 520 entries.

**Two costs, both measured in this run:**

*Wasted generation slots.* `viz-11-typed` and `viz-11-full` were each fed two
byte-identical files (`diagram_006.jpg` + `diagram_011.jpg`) — one picture in two slots, so
`top_k=2` was effectively `top_k=1`.

*Flip noise that looks like an arm effect.* The two 2026-09-06 arms share one index and one
set of queries (`rewrite: false`, so the query strings are identical). Retrieval still
differs:

| comparison | top-1 differs | top-2 differs | top-12 order differs |
|---|---:|---:|---:|
| this run vs baseline arm | 2 | **2** | 5 |

Both differing questions are `viz-11`, and in both cases the difference is *which twin from
the 9-member cluster* won:

```
viz-11-typed  RUN: diagram_008, diagram_011   BASE: diagram_004, diagram_011
viz-11-full   RUN: diagram_011, diagram_009   BASE: diagram_007, diagram_011
```

It is not even stable **within** a single run. The answer pass and the replayed retrieval
sweep disagree on exactly 3 questions in *each* arm — `viz-11-typed`, `viz-11-full`, and
`arch-05-typed` — and every one of those disagreements is a swap inside a byte-identical
cluster (`arch-05-typed`: `diagram_002` vs `diagram_001`, a 2× twin pair).

The whole of the arms' retrieval-metric difference is `ndcg@5` `0.9203694…` vs `0.9204762…`
— **1.07 × 10⁻⁴** — with `hit@1`, `hit@12`, `mrr`, `recall@k` and `first_gold_rank` bit-identical.
**Any flip attributed to `viz-11` or `arch-05` in a compare pass is duplicate tie-break
noise, not a backend effect.**

The golden set already handles the scoring side correctly (`viz-11` lists the twins in
`acceptable_sources`), so the metric is not corrupted — but the wasted context and the noise
are uncompensated. A `content_hash` payload field and a dedupe at upsert would collapse
both.

### 9.5 Patch-count spread: real, but not the story on real queries

Re-measured over all 709 points: **min 91, median 747, max 779; 87 pages below 300 patches.**

| category | pages | min | median | max |
|---|---:|---:|---:|---:|
| diagrams | 40 | **91** | 245 | 759 |
| charts | 40 | **95** | 235 | 739 |
| photos | 40 | 191 | 236 | 335 |
| figures | 40 | 146 | 747 | 770 |
| tables_fr | 20 | 179 | 752 | 771 |
| documents / slides / scans / notes | 289 | 725 | 755 | 779 |

*(Minor correction to the baseline: it reports the `charts` median as 251; I measure 235 over
the same 40 points. The `diagrams` figure, 245, reproduces exactly.)*

`MAX_SIM` sums per-query-token maxima over document patches, so more patches means more
chances to score high independent of content, and the baseline demonstrated this convincingly
with random unit query vectors. **But this run's real-query data does not support treating it
as a live defect.** Top-12 slot share vs index share:

| category | index share | top-12 slot share | ratio | golden items |
|---|---:|---:|---:|---:|
| notes_iam (**725-771 patches**) | 5.77% | **0.70%** | **0.12×** | 0 |
| notes_handwritten (747-779) | 4.42% | 11.90% | 2.7× | 10 |
| photos (**191-335 patches**) | 7.69% | 7.79% | **1.01×** | 6 |
| diagrams (91-759) | 7.69% | 2.71% | 0.35× | 4 |
| charts (95-739) | 7.69% | 4.73% | 0.62× | 10 |
| figures (146-770) | 7.69% | 3.20% | 0.42× | 6 |

The highest-patch slice in the corpus (`notes_iam`) is the *least* retrieved, by 8×, and the
lowest-patch slice (`photos`, none above 335) sits exactly at parity. The `diagrams` and
`figures` deficits track their small golden-item counts (4 and 6 of 120) far better than they
track patch counts. **Conclusion: length bias is real for uninformative queries and is
dominated by content on real ones.** It stays on the list as a latent risk — a 95-patch chart
genuinely cannot resolve an axis label — but it is not where the 19/120 is being lost, and
`charts` hit@1 is 1.00 here.

### 9.6 The failures are silent, and the judge charges them to the model

The index has no way to say "that document is not in me". Six golden items lost 100% of
their gold to §5 (`study-05-*`, `study-10-*`, `rcpt-07-*`), and two more lost their gold page
to §9.1 (`study-08-*`). This run's judge verdicts on those eight:

| item | this run | baseline arm | judge's stated reason (this run) |
|---|---|---|---|
| `study-05-typed` | wrong | wrong | *"electric-charge-and-field-9.pdf marks θ=180° as unstable…"* — a page the system cannot see |
| `study-05-full` | false_abstain | wrong | *"retrieval returned -10 and -7 rather than the gold page -9"* |
| `study-10-typed` | wrong | wrong | *"Answers from CseGyan-Cpp-Notes-14/15… the type-casting pages…"* |
| `study-10-full` | false_abstain | wrong | *"top-k of 2 returned the operator pages instead of any of the three gold…"* |
| `rcpt-07-typed` | wrong | false_abstain | *"Emits the degenerate string '[{' after retrieving receipt_005.jpg…"* |
| `rcpt-07-full` | false_abstain | false_abstain | *"retrieval returned receipt_005.jpg and a photo instead of the gold receipt_040.jpg"* |
| `study-08-typed` | false_abstain | false_abstain | *"Declined although deck_027.pdf, the gold source, was the only retrieved file."* |
| `study-08-full` | false_abstain | wrong | *"Declined although deck_027.pdf, the gold source, was the only retrieved file."* |

**Eight of 120 verdicts (6.7%) are index defects wearing an answer-quality label**, and six
of the eight *changed verdict between the arms* purely as a by-product of prompt-driven
abstention behaviour, on an unchanged index. Any reader of `JUDGE-REPORT.md` alone will
mis-locate the effort. The `study-08` pair is the sharpest case, because the judge explicitly
notes the gold file *was* retrieved and still scores the model down.

### 9.7 What this eval cannot see

| | |
|---|---|
| files dropped | 25 |
| …carrying a golden item | 5 (20%) |
| pages dropped | 55 |
| …carrying a golden item | 5 (9%) |
| pages present but unreachable at answer time | 49 |
| …carrying a golden item | 1 (`deck_027.pdf` p5) |
| golden items affected in total | 8 / 120 (6.7%) |

**91% of the lost pages and 98% of the unreachable pages are invisible to this eval.** A user
who owns `scan_nglg0227.pdf` has a 20-page document Magpie will never find and will never
admit to not having; a user who owns `scan_yscw0217.pdf` has 13 pages that are indexed,
retrievable, and unreadable. Do not read "6.7% of golden items" as the size of the defect.

---

## 10. Verifying, correcting and extending the baseline's `REPORT-indexing.md`

The baseline arm's report analysed this same mount. Where I could re-measure, I did.

**Confirmed independently (re-measured today, same numbers):**
520 files / 709 points / 1 collection / no `summaries` collection · 545 files & 764 pages on
disk · per-category coverage table (all 15 rows) · 0 zombies, 0 page-num gaps, 0 manifest/disk
size mismatches · the 25-file failure list · 62 distinct gold files, 5 missing, **6**
structurally dead golden items · 514 distinct contents / 8 duplicate groups / 31 extra copies,
group membership exact · patch distribution min 91 / median 747 / max 779, 87 sub-300 ·
`page_num` 0-based in citations, verified against `scan_gzyh0227.pdf` p3's printed `- 2 -` ·
retrieval metrics `hit@1 0.9327`, `hit@12 0.9423` · no indexing-path file changed between
`cca67570` and HEAD · the summary tier is empty and `index_summary_tier: true` describes
nothing.

**Corrections:**

1. **"Newest corpus mtime `2026-08-30T04:44:10`, five hours before the store was built."**
   The mtime is `2026-08-30T08:44:10Z`; `04:44` is local EDT. The store was built at
   `09:57:58Z`, so the margin is **1 h 14 m, not five hours.** The conclusion (mount not
   stale) holds; the safety margin is four times narrower than stated, which sharpens rather
   than weakens the recommendation for a corpus digest in `meta.json`.
2. **`charts` median patch count** is 235, not 251. `diagrams` (245) reproduces exactly.
3. **notes_iam distractor share.** The baseline reports "1 of 240 top-2 slots (0.4%)". The
   correct denominator is **334**, not 240 — 10 of 120 questions were widened by the LIST_ALL
   path to 12 files, and all 12 were fed to the generator (`104×2 + 6×1 + 10×12 = 334`,
   matching `answers.jsonl` exactly). The share is **0.30%**. The conclusion is unchanged and
   in fact strengthened.
4. **`viz-11` duplicate examples.** The baseline names `diagram_004`+`diagram_011` and
   `diagram_007`+`diagram_011` as the top-2 pairs. Those are *its own arm's* draws; this arm
   drew `diagram_008`/`diagram_006`/`diagram_009`. The observation is right, but stating
   specific filenames implies determinism the data does not have — the winners are an
   arbitrary tie-break among nine identical vectors, unstable even between the answer pass
   and the retrieval sweep *within one run* (§9.4).

**Extensions (new here):**

- §9.1 — the retrieved `page_num` is discarded by the answer stage, which renders the front 5
  pages instead; 49 indexed pages (6.9%) are structurally unreadable; `study-08` is a
  confirmed golden-item casualty and **two more judge verdicts are mis-attributed** beyond
  the six the baseline found. The mitigation the code documents for this (T3 summary /
  index-time transcript) is exactly the tier that is empty here.
- §9.4 — the duplicate clusters are a **noise source for the comparison**, not just a wasted
  slot: 2 of 120 top-2 lists differ between the arms on an identical index, and 3 of 120
  differ within each run. Quantified as `ndcg@5` Δ = 1.07 × 10⁻⁴ with every other retrieval
  metric bit-identical.
- §9.5 — real-query evidence that `MAX_SIM` length bias is dominated by content:
  `notes_iam` (highest patches) is retrieved 8× *less* than its index share; `photos` (lowest)
  sits at parity.
- §9.2 — three prompts declare five PDF pages and attach 3/4/2, because budget trimming drops
  image blocks after the header string is built.
- §9.3 — the citation offset is **double**: `page_num` vs PDF page vs printed page, verified
  on six pages of two UCSF scans.
- §2.1 — the carried-in Aug-30 log is *answer* traffic, not summariser traffic; the
  summariser made **zero** LLM calls; and `enrich.py` reads the named path from
  `worker_answer_result.json` (not from `run.json`), which is correct today but is a second
  copy of the same fact.
- §2.2 / §6 — the summariser clock fix is not merely inert on a mount, it is **unmeasurable
  on this dataset at all**; a `--rebuild-index` arm would not test it.
- §8 — mount cost measured directly (0.19 s via the exact `shutil.copytree` call) and shown to
  be excluded from `wall_s_total` because `t0` is set at `run.py:228`, after the mount.

**Where I stopped short:** I did not re-run the 25-file fp16 re-encode or the scratch-Qdrant
error-string probes. The baseline's reproduction of those is thorough and consistent with the
code at HEAD and the logged error strings, and re-deriving it would not move any conclusion.
I say so rather than implying I verified it.

---

## 11. Recommendations

**Product (`src/`), in payoff order:**

1. **Thread `page_num` into the answer stage.** `build_content_blocks` should accept the
   matched page(s) and render those, not pages 1-5. This alone recovers 49 unreachable pages
   and would flip `study-08` on this dataset without touching the model, the prompt or the
   retriever. Everything else in this list is smaller.
2. **Upsert per page, not per file** (`index.py:139`). One NaN page currently destroys an
   entire document (11 good pages lost with `scan_zxjd0228.pdf`) and one large document
   exceeds the 32 MiB body cap wholesale (`scan_nglg0227.pdf`, 20 pages). Both failure modes
   are the same design decision.
3. **Check embeddings for finiteness before upsert** (`index.py:133`) and either retry the
   page in float32 or record it as a named, structured error. Today a silent fp16 NaN becomes
   a 400 that becomes a log line that becomes nothing.
4. **`run_fast_batch` must return errors as data**, not print them. It returns `None`; the
   only record of 25 failed files is unstructured text in a log, which is why this survived
   four runs.
5. `search.py:553` — `page + 1`. One character. And prefer the printed page label where
   `_extract_book_page_label` can recover it.
6. Populate the manifest's existing `content_hash` slot and dedupe identical content at
   upsert. Removes both the wasted `top_k` slots and the tie-break flip noise.

**Harness (`eval_harness/`):**

7. **Compare `dataset_manifest_files` (545) against `manifest_entries` (520) on every run,
   builds and mounts alike, and fail on a gap.** This is a few lines, needs no `src/` change,
   works on mounts where there is no index phase to instrument, and would have caught this on
   2026-08-30.
8. **Never publish a store that had index errors** (`run.py:363-383` currently gates only on
   `manifest_entries > 0`). Publication is what turned a one-run failure into a durable
   artifact now inherited by four runs.
9. **Exclude `logs/` and `drift/` when publishing a store.** A published index should not
   carry the build run's answer-phase LLM log into every future run's appdata (§2.1).
10. **Record the mount in `run.json`**: `phases.index = {wall_s, mounted: true, key,
    built_under_sha, built_utc, manifest_entries}`. Today a mount leaves `run.json` with no
    index phase at all.
11. **Make the SHA-drift check precise instead of loud.** `run.py:191-197` prints an
    identical stderr warning whether the diff touched `src/drift/` or `src/stage1_fast/`.
    Diff only the indexing path (`src/stage1_fast/`, `src/stage2/fast_db.py`,
    `src/stage2/db.py`, `src/manifest.py`, `src/ingest/walker.py`, `src/pipeline.py`); empty →
    mount silently; non-empty → hard fail or `--force-mount`. Record the verdict in
    `run.json` so `compare.py` can see it.
12. **Store `col_model_resolved` in `meta.json`.** It currently records `"col_model": "auto"`
    — the request, not the resolution — so a machine resolving `auto → ColSmol` computes the
    same key `66974090bdcd62e6`, mounts these 128-dim ColQwen vectors, and returns garbage
    with no error. `worker.py:phase_index` already computes the resolved family.
13. **Put a corpus digest in `meta.json`** (path + size + mtime over the corpus) and compare
    at mount. The index key hashes only params, so an edited corpus mounts a stale index
    silently. This corpus happens to be clean — by 74 minutes (§10, correction 1).

**Reporting:** a compare pass over these two arms should treat `viz-11-typed`, `viz-11-full`
and `arch-05-typed` as **noise**, and the eight items in §9.6 as **index-attributed**, not as
answer-quality signal.

---

## Appendix: evidence index

| claim | source |
|---|---|
| mount, no index phase | `run.json` `index_store` / `phases`; `raw/qdrant.log` request mix (0 upserts); absence of `raw/worker_index.*`; `raw/progress.json` `index.note = "mounted from store"` |
| mounted appdata byte-identical to store | `cmp` of `manifest.json`, `settings.json`, `indexing_rules.json`, `logs/llm-2026-08-30T10-40-06Z.log` |
| store provenance | `eval_harness/indexes/66974090bdcd62e6/meta.json` |
| 520 files / 709 points / payload = `{source_path,page_num}` / dim 128 / 0 gaps / patch counts | live scroll of every point, Qdrant 1.17.1 booted on a copy of `indexes/66974090bdcd62e6/qdrant/` |
| summary tier empty | 520/520 `summary_file: null`; no `summaries` collection; 241 × `GET /collections/summaries/exists`; Aug-30 `worker_index_result.json` `summary_tier_note` |
| summariser unreachable on this corpus | `src/stage1/summarize.py:789-796`; `worker_index.log` ends at the summary-tier banner |
| Aug-30 log is answer traffic | 120 requests, all `Answer` json_schema; named in Aug-30 `phases.answer.llm_log`; opens `10:40:06Z`, after index end `10:39:52Z` |
| enrich reads a named path, no glob | `harness/enrich.py:283-288`; no `glob` in the file; `raw/worker_answer_result.json` `llm_log` |
| 25 missing files, 0 zombies, 0 stale sizes | disk vs `raw/appdata/manifest.json`, recomputed |
| error strings and 25-error tally | `runs/20260830T095758Z-…/raw/worker_index.log:84` and the error block (INHERITED) |
| errors swallowed / run exits 0 | `src/stage1_fast/index.py:141,188-215`; `harness/worker.py` `phase_index`; `harness/run.py:255` |
| payload has no text | `src/stage2/fast_db.py:143-147,167` + scroll (0 non-path string values) |
| placeholder summary | `src/stage2/search.py:553`; 334 occurrences in `raw/worker_answer.log` |
| answer stage discards `page_num`, caps at 5 | `src/answer.py:40,882-886`; `src/content.py:522-528,600-616`; `_summary_supplement` `answer.py:747-762` |
| all 49 multi-page PDFs have empty text layers | pymupdf over `slides/` + `scans_multipage/` (0 chars, 268 pages) |
| 49 unreachable pages; `study-08` = 5 images for a 6-page deck | point counts per path; `llm-2026-09-06T10-39-33Z.log` request bodies (`extra.images`, `[File N, image k of n]` captions) |
| declared-vs-attached page mismatches (3) | regex over all 120 request bodies |
| page-number offsets | rendered `scan_gzyh0227.pdf` pp. 3-8 (printed `- 2 -` … `- 7 -`) and `scan_xqgl0226.pdf` p9 (printed `(5)`) |
| 31 byte-identical duplicates, 8 groups | SHA-256 over all 545 corpus files |
| cross-arm and intra-run tie-break divergence | `raw/retrieve.jsonl` and `raw/answers.jsonl` of both 2026-09-06 runs |
| retrieval metrics identical except ndcg@5 | `metrics.json` of both arms |
| notes_iam pressure | `raw/retrieve.jsonl` (1,437 slots), `raw/answers.jsonl` (334 fed slots) |
| 6 dead golden items, 62 gold files, 5 missing | `datasets/custom_dataset_rahul_Aug30/golden.json` × the 25 missing files |
| judge mis-attribution | `judge_verdicts.json` of both arms |
| timings | Aug-30 `run.json` `phases.index.wall_s`; this run's `progress.json`; `run.py:228` (`t0` after the mount); measured `shutil.copytree` of the store = 0.19 s |
| 21-file visual spot-check | direct reads of renders through the indexing path (`pymupdf` + PIL), all 15 categories |
