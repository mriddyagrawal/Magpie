# Supervisor report — 20260906T103913Z

**Arm:** branch `prompt-image-order`, backend `4ce90a8`
**Baseline:** `20260906T090247Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`, backend `92f9ba9`
**Dataset:** `custom_dataset_rahul_Aug30` (545 files, 100% visual) · **golden_sha** `0ebcdcbcdf109adb` · 120 questions
**Config:** `custom-rahul-topk2-rerank-off-norewrite` — rerank OFF, `solo_margin 0` (gate off, stamped
`solo_gate_structurally_off: true`), rewrite OFF, `top_k 2`, `temperature 0`, `local_n_ctx 16384`,
`col_model auto` → ColQwen2.5, grounding guard ON, strict grounding ON.

This is the deliberate ARM against the baseline. Config, golden set, index mount, judge model and
rubric sha are all identical; **only the code axis moved**, by four commits. The compare skill was
deliberately not run — the owner runs it separately.

---

## 1. Verification before judging

Every axis the skill requires, plus the fingerprint check the owner asked for:

| Check | Result |
|---|---|
| `status` | `complete` |
| `isolation.real_appdata_untouched` | `true` |
| `isolation.cache_model_blobs_unchanged` | `true` (157 files / 27,157,872,740 bytes, identical before and after) |
| Answer errors | 0 / 120 |
| `golden_sha` | `0ebcdcbcdf109adb` — equal to baseline |
| `index_store` | HIT, key `66974090bdcd62e6` — same mount as baseline |
| `params` vs baseline | byte-identical |
| **`provenance.fingerprint`** | **`2bd85ac1c6a9fd99` — equal to baseline** |
| Judge model / rubric sha | `claude-opus-5` / `47e93a279e70cef9` — equal to baseline |
| `backend_git_sha` | `4ce90a8` vs `92f9ba9` — the intended and only moving axis |

All ten swept env axes match the requested config: `LOCAL_TEMPERATURE=0.0`, `LOCAL_SOLO_MARGIN=0`,
`MAGPIE_RERANK=0`, `LOCAL_N_CTX=16384`, `MAGPIE_COL_MODEL=auto`, `MAGPIE_FORCE_PROVIDER=local`,
`LLM_PROVIDER=local`, `LLAMA_SERVER_STARTUP_TIMEOUT_S=300`, `MAGPIE_GROUNDING_GUARD=1`,
`MAGPIE_STRICT_GROUNDING=1`.

**Two non-substantive `env_snapshot` differences, reported as required and neither blocking:**

1. `MAGPIE_DATA_DIR` — the per-run scratch appdata path. Expected; it is the isolation root.
2. One `PATH` element: a Claude plugin cache directory renamed itself between the two runs
   (`…/frontend-design/85cce0381e78/bin` → `…/frontend-design/unknown/bin`). It sits after
   `.venv/bin`, is not on the backend's resolution path, and cannot reach the run. The identical
   `provenance.fingerprint` — which covers llama-server build 10502/`0adcc3bb5`, the GGUF and mmproj
   sha256s, ColQwen2.5 on mps/float16, and the uv lockfile hash — is the stronger evidence that the
   runtime did not move.

**Verdict: the recorded config was in force.** Nothing here is confounded.

---

## 2. Headline

**58 judged flips of 120 — 44 improvements, 14 regressions, 0 lateral. All 58 attributed to
`prompt_assembly`. Zero attributed to noise.**

Against the baseline pair's measured floor of **10 flips / 120**, this is 5.8×. The attribution is
not a judgement call — **both noise channels are structurally empty in this pair**:

- **Judge noise** (the baseline's largest channel, 3/120) is defined as byte-identical answer text
  graded differently. **0 of the 58 flips have byte-identical answer text**; all 58 come from rows
  whose text changed. The mechanism cannot fire.
- **Temperature-0 model nondeterminism** (the baseline's 2/120) requires a row to receive the same
  input twice. The user turn was restructured on **120/120 rows**, so no row did. The mechanism has
  no opportunity.

Corroborating determinism: 7 rows produced **byte-identical non-empty prose across a changed
prompt** (`arch-04-typed`, `phone-01-full`, `phone-03-full`, `phone-06-full`, `rcpt-05-typed`,
`study-02-typed`, `study-07-typed`), plus 34 both-empty abstentions. The judge was self-consistent
across arms: 14 vs 13 disagreements with the deterministic pass, 7 vs 7 golden issues flagged.

Within the 58, the answers report separates **48 mechanistic** flips (traceable to a named change)
from **10 incidental** re-rolls where no mechanism could be evidenced. Even on the most conservative
reading — charging all 10 incidental flips plus the entire 10/120 floor against the change — **at
least 38 flips remain mechanistically attributable**.

### Judged verdicts

| Verdict | Baseline | This arm | Δ |
|---|---|---|---|
| `correct` | 6 | **19** | +13 |
| `partial` | 17 | **28** | +11 |
| `wrong` | 36 | **21** | −15 |
| `false_abstain` | 45 | **36** | −9 |
| `correct_abstain` | 9 | **14** | +5 |
| `false_answer` | 7 | **2** | −5 |

Retrieval is a **null axis**: identical on 120/120 rows on a content-hash basis. Across 104 scored
rows × 2 bases × 11 metrics — 2,288 numbers — exactly one moved (`viz-11-typed` sweep `ndcg@5`,
Δ −1.07e-4). `search_query` is byte-identical on 120/120, confirming the rewriter clock removal is
inert here as predicted. Indexing is identical **by construction** — both arms mounted the same
2026-08-30 index.

### What actually changed in the prompt

Verified live in the request logs on all 120 rows. Baseline sent two file headers with **nothing
under them** (images went out-of-band via the legacy `images=` kwarg and were appended after all
text), the question twice, and the clock at the very top. This arm sends each image as a typed
content part directly under its own header, the question once, and the clock immediately above it.
Since the corpus is 100% images at `top_k=2`, every row has this shape — which is why the effect is
so large. `--- File 1 ---` is retrieval rank 2 in **both** arms; `reversed(per_file_blocks)`
(`src/answer.py:644`) predates this branch and is not what changed.

---

## 3. Findings, ranked

### F1 — The shipped headline understates this arm by more than half; the grounding guard eats the gain

The guard now causes **33 of 36 false abstentions (92%)**, up from 31 of 45. Its *input* is
unchanged (identical 71-zero / 40-banner / 9-text support distribution), so the increase is purely
the answer text changing — answers got shorter and more numeric, which is exactly what the guard
targets. Re-scoring the 33 suppressed texts with the harness's own matcher: **12 correct / 13
partial / 8 wrong**, versus baseline **4 / 18 / 9**.

Guard-off counterfactual:

| | this arm | baseline |
|---|---|---|
| `correct` | **0.269** | 0.077 |
| `partial` | 0.433 | 0.337 |
| `wrong` | 0.269 | 0.452 |
| `false_abstain` | **0.029** | 0.135 |

**Seven of the 14 regressions are new guard fires, and on five of them the underlying answer got
better** — `arch-02-typed` produced the gold "4,58"; `arch-05-typed` a 2-of-2-fact leaflet
transcription; `study-05-full` the exact gold torque angles. All three were deleted by the guard and
scored as abstentions. This is the single largest correctable loss in the run, and it is the same
finding the baseline made — the change made it worse in the headline while making the underlying
model behaviour better.

### F2 — The citation collapse is a parsing artifact, not a regression

`citations.cited` fell .471 → .279 and `zero_citation_answers` rose 28 → 49, which reads as a
regression and is not one. Raw `sources_used` is non-empty on **101/120 rows (baseline 102/120)** —
the model never stopped citing. Bare paths collapsed 101 → 39 while **header-prefixed** paths rose
33 → 37: the new standalone header content-part leads the model to copy `File 2: /path/to/x.jpg` as
a unit, and the harness's path filter drops anything that isn't a bare path. Stripping the prefix
and resolving ordinals gives **11 zero-citation rows for this arm vs 13 for the baseline** — this
arm carries *more* recoverable provenance. Two independent checks kill the "honest uncertainty"
reading: hallucinated citations fell from the same cause (cite-every-file dropped 21 → 10), and
uncited answers are the *better* ones (70% correct+partial vs 60% for cited).

### F3 — `build_content_blocks` discards the matched page number: 49 indexed pages can never reach the generator

`build_content_blocks(path, …)` takes no page parameter. For an image-only PDF it renders **pages
1–5 from the front, always**, regardless of which page retrieval matched. All 49 multi-page PDFs in
this corpus have empty text layers (0 chars across 268 pages), so they all take that path, and both
designed mitigations (`transcript_for`, `_summary_supplement`) live in the summary tier — which is
empty (F8). `study-08-typed` / `-full` is the clean demonstration: retrieval was perfect
(`deck_027.pdf` the only hit, matched at `page_num 5`), page 5 holds every gold fact, and the prompt
log shows `"5 page(s) as images"` = pages 0–4. The one page not sent is the answer. The judge wrote:
*"Declined although deck_027.pdf, the gold source, was the only retrieved file."* This makes **8 of
120 verdicts mis-attributed** to the answer stage — two more than the baseline found. Not caused by
this branch; it caps both arms.

### F4 — `src/grounding.py:numerals` silently discards comma-terminated numbers

The comma is inside the `\d[\d,]*` character class, so `"849,"` tokenises with its trailing comma,
`float()` raises, and the token is dropped: `numerals("849, attendance") == []` but
`numerals("attendance 849") == ['849']`. Punctuation position therefore decides whether the guard
fires. It decided three rows across the two runs; `study-01-full`'s entire `false_abstain → partial`
flip is a semicolon-to-comma change and nothing else. Pre-existing, not from this branch, but it is
noise injected directly into the metric this arm is being judged on.

### F5 — 25 of 545 files were never indexed; 7 rows are unanswerable by construction

The manifest holds **520 of 545** files (fast tier 95.4%, 709/764 pages). Seven of 104 scored rows
reached the generator with **zero relevant files**: `rcpt-07-typed/full`, `study-05-typed/full`,
`study-10-typed/full` (gold never indexed) and `rcpt-05-typed` (the one genuine indexed-gold rank
failure — gold at rank 5, cut at `top_k=2`). **Answer accuracy should be quoted against 113, not
120.** Relatedly, the `recall@1` .808 vs `hit@1` .933 gap is mostly arithmetic: with `n_rel`
distributed 80×1, 14×2, 6×3, 2×4, 2×9, the structural ceiling is `mean(1/n_rel)` = 0.8627, so the
true shortfall is 0.0545, not 0.192.

### F6 — `solo_gate.fire_rate: 0.05` is an artifact and should not be read as gate activity

`solo_gate_structurally_off: true` is correct — `gate_to_solo` returns early on
`not _rerank_enabled()`. The 0.05 is `enrich.py` inferring post-hoc from
`len(retrieved)==1 and len(ranked)>=2`, matching 6 rows. All 6 rank-1 files are multipage PDFs
(5–9 pages): `_search_fast_tier` requests `fetch_k*2 = 4` **pages**, then dedups to one result per
file, so a single PDF consumes the entire slate. The `solo_excluded` label is misleading — nothing
excluded those files. The same collapse also bites at sweep depth (`viz-08-typed` returned 11,
`arch-08-full` 10).

### F7 — The `diagrams/` category is 40 files over 9 unique images

545 files, only **514 distinct content hashes**; all 31 redundant copies are in `diagrams/`.
`diagram_003`–`diagram_011` are nine byte-identical copies of one JPEG (md5 `f15f998481…`).
`viz-11`'s retrieval metrics are meaningless as a result — its `n_rel=9` is nine copies of one
file, and its rel=2 "gold" reached neither prompt. Dedup, or grade the duplicate group uniformly,
before any further diagram measurement.

### F8 — The summary tier is empty, and `4ce90a8`'s summariser fix is unmeasurable on this dataset

**Summary tier is 0/545**, verified three ways (all 520 manifest rows carry `summary_file: null`; no
`summaries` collection exists; 241 failed `exists` checks in `qdrant.log`). Scrolling all 709 Qdrant
points shows every payload is exactly `{source_path, page_num}` — **the index stores no text about
any image**. The only "summary" is `search.py:553`'s query-time `"(visual match — page N)"`, 100%
generic across 334/334 uses; it feeds the reranker and the UI but never the generator.
`summarize.py:789-796` drops every file whose `route_file()` is `"fast"`, and all 545 files route
fast, so the summariser exits before its first call — **a `--rebuild-index` arm would hit the same
exit.** Measuring the summariser clock fix needs a mixed-media corpus, not a rebuild flag. Date
contamination in the index: **zero**, including a binary scan of the 788 MB store.

### F9 — The index store publishes the build run's `appdata`, including its LLM log

`raw/appdata/logs/` contains **two** `llm-*.log` files: this run's, and
`llm-2026-08-30T10-40-06Z.log` carried in by the mount — which is the Aug-30 build run's
*answer-phase* log (120 requests, all bearing the `Answer` JSON schema), not summariser traffic.
Anything that globs that directory mines a foreign run's prompts. Enrichment is clean
(`enrich.py:283-288` reads one named path from `worker_answer_result.json`), but the hazard is live
for any future analysis, and it is how I initially mis-read this run's prompt log. Source:
`run.py:363-383` publishes the whole `appdata` into the shared store.

### F10 — The prefix-cache win claimed by `4ce90a8` is unobservable in this harness

`4ce90a8` justifies moving the question and clock below the files by llama-server's longest-common-
prefix cache. This eval cannot see that benefit: there are **101 distinct retrieved file-sets across
120 questions**, max repeat 2, and the two members of a typed/full pair are not adjacent, so the
single cached prefix almost never gets a second hit. Wall clock went the *other* way — answer phase
2343.5s vs 2224.4s (+5.4%). `phone-07-full` alone accounts for 36s of the 119s (it degenerated into
7,467 chars of repeated "Bud Light"; 44.3s vs 8.1s). The residual +83s (+3.7%) has **no established
cause** — I am not attributing it. The cache claim needs the product's follow-up-turn path to test,
not this eval.

---

## 4. Disagreements between reports, resolved

**`viz-11` and `arch-05`: `prompt_assembly`, not noise.** The indexing report called both noise from
tie-shuffle; the retrieval and answers reports called them `prompt_assembly`. I resolved it against
the raw data and the indexing report is wrong on this point:

- It conflated the retrieval **sweep** with the **answer pass**. `arch-05-full` permuted at sweep
  ranks 5/6 — metric-inert, never fed to the generator — and **did not flip**. The row that flipped
  is `arch-05-typed`, whose answer-pass retrieval is byte-identical in both arms (`doc_357.jpg`,
  `diagram_002.jpg`).
- On `viz-11`, the two files at File 1 / File 2 are both in the 9-member md5 `f15f998481` duplicate
  group, so the model sees **the same pixels in the same two positions** in both arms; only the
  header filename strings swapped. Decisive: on `viz-11-full`, `sources_used` is *identical in both
  arms* (`diagram_011`, then `diagram_006`) despite the reversed header order — the model's
  citations did not follow the swap, so the swap did not drive the answer.

**Retained from the indexing report**, because it is orthogonal and correct: the tie-break draw is
unstable *within* a single run (answer pass and replayed sweep disagree on 3 questions in each arm).
That makes the duplicate group unfit for measurement (F7) without making these two flips noise.

**Corrections the reports made to my own framing**, recorded so the record is accurate: retrieval is
identical on 120/120 rather than the 118/120 I computed from filenames; the sweep permutes on 5 rows
rather than 2; and the `score` column is a positional constant `1/(60+rank)`, not a similarity, so
my "identical scores" phrasing was reading an artifact. The answers report also corrected my claim
that answers got longer — excluding the one degenerate row, total answer text *fell* 5,039 → 4,099
(−19%) and median raw answer fell 25 → 13 chars.

**Corrections to the committed baseline reports**, from the indexing agent: the "newest corpus mtime
five hours before the build" claim mixes local EDT with UTC (real margin 1h14m); `charts` median
patch count is 235, not 251; the notes_iam denominator is 334 fed slots, not 240. It also
contradicts the baseline's §5.3 emphasis — MaxSim length bias is real for random query vectors but
dominated by content on real ones: `notes_iam` has the highest patch counts and the *lowest*
retrieval share.

**Closed non-issue:** the `notes_iam` distractor slice is not a problem. It takes 0.70% of top-12
slots against a 5.77% index share (8× under-represented), only 8 of 30 files ever surface, and
exactly one reaches a prompt (`nf-05-typed`, on the bare query "transcript", verdict
`correct_abstain`).

---

## 5. Suggestions

Grounded in `src/`; **nothing under `src/` was edited by this run or by any agent in it.**

1. **Re-measure this arm with the grounding guard off** (F1). It is one env knob and it is the
   difference between "this change moved `correct` 6→19" and "this change moved `correct` 6→32 with
   `false_abstain` at 0.029". The guard is currently deleting verified-correct answers — five of the
   fourteen regressions are the guard destroying *improved* output. Per CLAUDE.md the knob is
   already threaded through `envctl.build_env`, so this is a config-only arm.
2. **Fix the citation path filter to accept header-prefixed paths** (F2). The model is emitting
   `File 2: /path/…` because the header is now its own content part. This is a harness-side parsing
   change that recovers ~26 rows of provenance and makes the citation metrics honest for every
   future visual arm.
3. **Thread `page_num` into `build_content_blocks`** (F3). Highest-value product fix in this run: it
   recovers 49 unreachable pages, would flip `study-08`, and needs no summary tier.
4. **Fix `numerals` in `src/grounding.py`** (F4) — move the comma out of the character class so
   `"849,"` tokenises as `849`. Small, self-contained, and it removes punctuation-driven noise from
   the guard.
5. **Have the harness compare `dataset_manifest_files` (545) against indexed `manifest_entries`
   (520) on mounts as well as builds** (F5). Three lines that would have caught the 25 missing files
   on 2026-08-30, before two runs were scored against gold that was never indexed.
6. **Stop publishing `logs/` into the index store** (F9), or name the log by run id, so a mounted
   index cannot contaminate a later run's prompt analysis.
7. **Rename or drop `solo_gate.fire_rate` when the gate is structurally off** (F6). Reporting 0.05
   for a gate that cannot fire invites exactly the misreading it caused here; the underlying
   single-PDF slate collapse deserves its own metric.
8. **Dedup `diagrams/` or grade the duplicate groups uniformly** (F7) before any further measurement
   on that category.

---

## 6. Bottom line

The change does what it was designed to do, and the evidence is unusually clean: identical config,
identical golden set, identical index mount, identical judge, identical runtime fingerprint, and a
retrieval axis that did not move on any of 120 rows. Binding each image to its `--- File N ---`
header — on a corpus where the images *are* the entire evidence — moved `correct` 6→19, `wrong`
36→21 and `false_answer` 7→2, across 58 flips of which none can be explained by either measured
noise mechanism. The headline understates the result, because the grounding guard converted a large
part of the gain into false abstentions; that is a separate, already-known, and separately fixable
defect.

*Golden set is still SILVER (120 model-authored items, 0 human-verified). Judge flagged 7 golden
issues. Do not treat absolute numbers as calibrated — the arm-vs-arm delta is what this run
establishes.*
