# Supervisor report — 20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

**Dataset** custom_dataset_rahul_Aug30 (545 files, 15 visual categories) · **Golden** 120 items / 60 pairs, fresh, `golden_sha 0ebcdcbcdf109adb` · **Config** top_k 2, rerank OFF, rewrite OFF, solo_margin 0, lfm-local, ColQwen2.5, float16/MPS, n_ctx 16384 · **Backend** `cca67570` · **Wall** 4996 s (index 2514 / retrieve 34 / answer 2448)

Provenance verified before judging: `status: complete`, both isolation checks true, model cache byte-identical (152 files / 21.5 GB), and every swept env axis matches the requested config. The recorded config was actually in force.

---

## The one-sentence result

**Retrieval is essentially solved on this corpus and reading is not:** hit@1 is 0.990 on the clean pool, while the answerer converts 5 of 92 answerable questions (5.4%) — so ~95% of the loss sits downstream of retrieval, and the single largest bucket (44 false abstentions) is the model going silent while the correct file is in its prompt.

## Scoreboard

| | Judge | Deterministic |
|---|---|---|
| correct | 5 | 3 |
| partial | 16 | 16 |
| wrong | 39 | 41 |
| false_abstain | 44 | 44 |
| correct_abstain | 9 | 8 |
| false_answer | 7 | 8 |

Judge reported **VALID** (model `claude-opus-5`, rubric `47e93a279e70cef9`), 11/120 disagreements with the deterministic matcher, and — importantly — **overturned no gold answer**: all 16 source files it opened confirmed the golden set exactly, including four values where a wrong Magpie answer challenged the gold.

**Honest denominators.** Of 120 items, 12 are doomed for reasons unrelated to answering quality: 6 whose gold was never indexed, 3 HTTP 400 infrastructure failures, 2 whose gold sits on a page the answerer structurally cannot see, and 1 whose gold never entered the prompt. That leaves **92 answerable**: 5 correct (5.4%), 21 correct-or-partial (22.8%). Retrieval placed gold in the prompt for **91 of those 92**.

| Retrieval | raw | clean pool (n=96) |
|---|---|---|
| hit@1 | 0.933 | **0.990** |
| MRR | 0.935 | 0.992 |
| nDCG@5 | 0.922 | 0.982 |

There is exactly **one genuine ranking failure in the entire run**: `rcpt-05-typed` ("that shop where i bought loads of chocolate bars total"), gold at rank 5, because ColQwen is a visual matcher and matched "shop" to literal photographs of shop interiors — the terse query names no document type. Its `full` twin wins at rank 1 because it contains "Delicia", printed on the receipt.

---

## Findings, ranked

### 1. Two independent silent data-loss bugs at index time — 25 files / 55 of 764 pages (7.2%), run still exits 0

**1a. fp16 NaN overflow (24 files).** ColQwen2.5 emits **100% NaN** embeddings for certain images under float16. NaN serializes to the bare token `NaN`, which is invalid JSON, so Qdrant rejects the body with `Format error in JSON body: data did not match any variant of untagged enum VectorStruct`. The per-file error is caught, the file is skipped, indexing continues, and the run reports success.

- Verified: `receipt_040.jpg` 677×128 = 86,656 NaN (all); `CseGyan-Cpp-Notes-17.pdf` 747×128 = 95,616 NaN (all); indexed controls 0 NaN.
- **fp32 verified to fix it across all 25 files.** The live dtype site is `device.py:244` (`dtype="float16",  # MPS bfloat16 support is patchy`) — *not* `:154`, which is the `MAGPIE_COL_MODEL` pin branch and dead under `col_model=auto`.
- **Apple-Silicon-only.** CUDA takes bfloat16. Note the code comment: bfloat16 on MPS was rejected as "patchy", so "just switch to bf16" may not be available — fp32, or a guarded fp32 retry, is the verified path.
- **No file property predicts it.** Size refuted (dropped median 1.6 MP vs kept 1.3 MP; a 37.2 MP file indexed, a 0.5 MP file did not). Aspect ratio refuted (identical medians). The indexing agent added JPEG quantization tables, EXIF, ICC and 20k-permutation tests: `notes_handwritten` dropped-vs-kept is statistically indistinguishable (p=0.67–0.92). **You cannot pre-screen; you need a post-encode assert.**

**1b. Qdrant 32 MiB body cap (1 file) — a different bug that fp32 makes worse.** `scan_nglg0227.pdf` (20 pages) has **zero NaN** yet still failed: its serialized upsert body exceeds Qdrant's 33,554,432-byte cap. Any PDF of roughly ≥20 pages at 150 DPI silently fails this way, dtype-independent. fp32 would double the payload.

**1c. One-upsert-per-file amplifies both.** `index.py:126-140` issues a single upsert per file, so one bad page destroys the whole document: `scan_zxjd0228.pdf` has exactly **one** NaN page of 12 and lost all 12. **32 of the 55 lost pages (58%) come from two files, neither of which was a whole-file failure.**

**1d. No retries happened.** `qdrant.log` shows exactly 545 PUTs (520×200 + 25×400). `_upsert_with_retry` catches only `ResponseHandlingException`; a 400 raises `UnexpectedResponse` and propagates. The "48 errors" in the worker log is the log double-printing, not retry attempts.

**Eval impact:** 3 golden pairs lost entirely (`rcpt-07`, `study-05`, `study-10`). But **22 of the 25 dropped files carry no golden item, so this eval observes only ~12% of the defect** — the true production blast radius is ~8× what the scoreboard shows.

### 2. The answerer cannot read printed numbers off images — this is the product's core limitation today

The false-abstain bucket (44, the largest) has a single dominant discriminator, and it is **not** any of the obvious candidates. Whether the gold answer requires reading a printed multi-digit number:

- answers report: **57% abstain (34/60) vs 12% (4/33)**, Fisher p = 2.2e-5; holding image count fixed at 2 (n=70), 55% vs 8%, p = 8.2e-5
- my independent recount (key_facts contains a digit): **49% (39/80) vs 10% (2/21)** — different operationalization, same ~5× effect

Context length, prompt megapixels, gold-file resolution, PDF-vs-image, answer_type and difficulty all wash out once content type is fixed. The decisive natural experiment kills the resolution story: **screenshots (1080×1920) abstain 0/5, while receipts_phone — which are *smaller* — abstain 6/7.** It is glyph size and print quality, not pixel count.

The variable predicts failure *shape* as much as rate: non-number questions fail as `wrong` (58%), number questions fail as silence (58% abstain). **The model's abstention is arguably well-calibrated** — it declines when it genuinely cannot read the digits. The problem is that the user sees "I couldn't find anything", which reads as a retrieval failure when it is a reading failure.

**Category tiers (what the product can do today):** usable — `figures`, `screenshots` (0 abstentions), `scene_text`, `diagrams`; headline-only — `charts`, `documents`, `receipts_degraded`; **unusable — `receipts_phone` 0/8, `tables_fr` 0/6, `slides` 0/3.**

### 3. Rahul's transcription work is half-merged, and it is the fix for finding 2

`699834b` (2026-08-26) landed the **reader** — `transcript_for()` at `content.py:51`, called at `:602` — but the **writer** (`Evaluations/transcribe_index.py`) was never wired into indexing, and `src/transcribe.py` does not exist. The commit message never mentions it; it says the transcript *retrieval* experiment "failed pre-registered gates and **were removed**", which is why this looked dropped.

Consequence: `transcript_for()` returns `None` for all 86 PDFs, so scanned PDFs fall back to rendering pixels. The code's own comment (`content.py:29-37`) records that the index-time transcript read a scanned page "near-perfectly" while **the answer-time pixel path converted ~1/12 of scanned eval questions** — this run measured 5/92, which is squarely in that range and independently reproduces the spike's result at 4× the scale.

A prior reviewer already connected these (`comments.md`): a file with a transcript has a real summary, so the cross-encoder stops scoring the `"(visual match — page N)"` placeholder against itself — **two of the three known product bugs, one mechanism.**

**Structural blocker worth knowing:** transcripts are keyed to `APP_DATA_DIR/transcripts/`, and the harness gives every run a fresh isolated scratch appdata. So the transcript path is currently **unreachable from the harness by construction**, not merely unused. Wiring it into `sync_files` fixes both the product and the ability to measure it.

### 4. `page_num` is computed, then thrown away — 49 of 709 indexed pages (6.9%) are permanently unreachable

Retrieval knows exactly which page matched. `search.py:553` formats it into the display string `"(visual match — page N)"` and **the value appears nowhere else in `src/`**. The answerer therefore always renders pages 1–5 (`ANSWER_MAX_PDF_PAGES`), regardless of which page actually matched.

`study-08` is the clean demonstration: `deck_027.pdf` indexed perfectly, retrieved at **rank 1**, and its pie chart carrying every key fact is on **page 6 of 6**. Magpie returned `not_found` with zero citations. Retrieval did everything right and the answer stage could not see the evidence.

### 5. More files monotonically hurt — and the widener fights the context budget

| Files actually delivered | n | correct + partial |
|---|---|---|
| 1 | 6 | **33%** |
| 2 | 104 | 16% |
| 12 (widened) | 7 | **0%** |

`enumerate_lists` widened 7 questions to 12 files; **all 7 failed**, and all 3 HTTP 400s were widened. The widener is also incoherent with the budget: of the 12 files it fetches, the answer stage omits 5–9 to fit 16k ctx. It dilutes rather than helps.

This matches `gate_to_solo`'s own documented rationale (near-perfect solo, ~13% with 4 distractors) — and **the solo gate is off in this run** because rerank is off. That makes it a concrete lever, not a curiosity. Caveat: n=6 and n=7 on the extremes; directional, not proven.

**HTTP 400s root-caused:** 16,527 / 17,785 / 17,598 tokens against a 16,384 limit, driven by a flat 6,000-char (~1,875-token) per-image cost in `_block_cost_chars` that caps prompts at exactly 7 images. 7 images is necessary but not sufficient (11 other 7-image requests survived) — the answers agent stated this as unresolved rather than fitting a curve to 3 points, which is the right call.

### 6. Reporting bugs that will mislead the next reader

- **`metrics.json` publishes `solo_gate.fire_rate: 0.05` for a run where the gate structurally cannot fire.** `gate_to_solo` early-returns on `MAGPIE_RERANK=0`, and `run.json` stamps `solo_gate_structurally_off: true`. `enrich.py:369` *infers* gating from "provider local AND post-gate list is 1 AND pre-gate had ≥2". All 6 phantom firings are multi-page PDFs where `fetch_k = top_k = 2` fetched 4 page-points that deduped to a single file (`search.py:836/850`). Nobody should credit or blame the gate.
- **15 `sources_used` entries arrive with the prompt header attached** (`"--- File 2: /path ---"`) and are silently dropped by the hallucination guard. 7 items lost their **gold** citation. Prompt order is the exact reverse of retrieval rank in 111/111 requests, so the last prompt file is the rank-1 gold. Fixing the parse lifts "any gold cited" from 25% to ~32% with no model change.
- **`not_found_topic` leaks hard-coded few-shot examples.** `answer.py:233/285` embed `'a landlord's emergency phone number'` etc. in the schema field description; the model copies one verbatim in 6 of 49 abstentions (10 under looser matching). This is user-facing: someone asking about their McDonald's receipt is told the app looked for a landlord's phone number. Separately, `not_found_topic` echoes the query verbatim in 14 cases, **100% of them `typed`**.
- **Citations are degenerate, not hallucinated.** I side with the answers agent over the judge here: zero of 45 emitted citations named a file absent from the prompt. `hallucinated_citations: 0.202` counts non-gold citations, not invented paths. The real defect is that 34 of 35 citation lists are mechanical copies (23 copy the whole prompt list in order, 6 copy File 1, 5 copy File N, 1 is a genuine subset).

### 7. `extract_rare_tokens` never fires for the way people actually type

Run over all 120 golden questions: **7/60 `full` produce keywords, 0/60 `typed`**. Every token recovered is mixed-case (`pH`, `kW`, `arXiv`, `McDonald`, `RedVelvet`); the regex is identifier-shaped and its docstring's motivating example is `GetIndentation`, a code symbol. The function exists precisely to replace the rewriter's keyword list now that rewrite is off by default — and for a terse lowercase query it supplies nothing, always. Latent here (keywords feed the empty BM25 tier and a ripgrep path with no T0 files); it would bite on a mixed text+visual corpus.

### 8. typed vs full is one effect, not two

Retrieval gap is one item (full 48/48 at rank 1, typed 47/48; Δhit@1 0.021) — far smaller than I predicted. On answers, paired McNemar over 45 clean pairs: `wrong` typed-only 13 vs full-only 4 (p=0.049); `false_abstain` full-only 9 vs typed-only 4 (p=0.267), and 8 of those 9 are the same pairs. **Overall quality is unchanged (p=0.29).** Terse phrasing changes the failure *mode* — it makes the model echo the query back (7/7 query-echo answers and 14/14 verbatim topic echoes are typed) — not the success rate.

---

## Disagreements between reports, resolved

| Claim | Resolution |
|---|---|
| Judge: "several answers cite a file they demonstrably did not read" | **Answers agent is right.** Zero citations named an absent file; the metric counts non-gold citations. Judge's phrasing overstates it. |
| Judge scored `study-07-typed` as `partial` | **Answers agent is right** — it is a pure query echo and should be `wrong`, consistent with how the judge scored the other six echoes. Net: 5 correct, 15 partial, 40 wrong. |
| My "48 errors = retries" | **Indexing agent is right.** 545 PUTs, zero retries; the log double-prints. |
| My "fp16 NaN explains all 25 files" | **Indexing agent is right.** 24 of 25. `scan_nglg0227.pdf` is the 32 MiB body cap, and fp32 makes it worse. |
| My "dtype site is `device.py:154`" | **Indexing agent is right** — `:154` is dead under `auto`; the live site is `:244`. |
| My "loss is 25 files (4.6%)" | **Indexing agent is right** — the honest unit is pages: 55 of 764 (7.2%). |
| Indexing agent: slides indexed 2.73× slower | **Accepted as a reading, not a fact** — it does not reproduce today, and they said so. Likely transient host contention. |

## Corrections to my own earlier claims

1. I said `rcpt-08`/`study-10` were "structurally unanswerable at top_k=2". **Wrong** — `enumerate_lists` widens enumeration queries past top_k. `study-10` fails because its gold was never indexed.
2. I said `rcpt-08-full` "received all three gold files". **Wrong** — it received two; the third was budget-dropped.
3. I counted `len(in_prompt)` as prompt size. **Wrong** — `in_prompt` has three values (`full` 258, `dropped` 40, `solo_excluded` 6).
4. Plus the four corrections from the agents in the table above.

Both the dataset manifest and this report carry the corrected versions. Pre-registered predictions and their outcomes (2 of 8 refuted) are in the run's scratch notes.

---

## Suggestions

I have not edited `src/`. Ranked by value per unit of risk.

1. **Assert on NaN immediately after encode** (`index.py`, after line 128). `if not torch.isfinite(tensor).all(): retry that page in float32, else raise`. This is the single highest-value change in this report: it converts silent corpus loss into either a recovery or a loud failure. Verified: fp32 clears all 24 NaN files.
2. **Chunk the upsert by page, not by file** (`fast_db.upsert_pages_batch`). Fixes the 32 MiB cap independently of dtype, and stops one bad page from destroying an 12-page document (58% of lost pages).
3. **Fail the run on nonzero index errors** (`run.py`). A run that silently drops 4.6% of the corpus must not report `status: complete`. At minimum surface `index_errors` at the top level of `run.json` — the skill's own verification checklist did not catch this because it checks status, isolation and env, but not index integrity.
4. **Wire `transcribe_index.py` into `sync_files`**, and make the transcript directory harness-visible. This is the measured fix for finding 2 and simultaneously removes the rerank placeholder (finding: `search.py:541`). It is the highest-ceiling change here, and the evidence for it already existed in-tree before this run.
5. **Thread `page_num` from retrieval into the answer stage** so a PDF renders the pages that actually matched, not pages 1–5. Recovers 6.9% of indexed pages, `study-08` among them.
6. **Fix the `sources_used` header parse** — strip a leading `--- File N: ... ---` before the hallucination guard. Free ~7-point gain in gold-citation rate, no model change.
7. **Stop `enrich.py:369` inferring gate firings.** Have the backend emit an explicit gate signal, or suppress `solo_gate` from `metrics.json` whenever `solo_gate_structurally_off` is set.
8. **Move the `not_found_topic` examples out of the schema description**, or derive the topic in code from the question. Small, user-facing, cheap.
9. **Make `extract_rare_tokens` case-insensitive** (or add a lowercase-content-word path) so terse queries get keywords at all.
10. **Reconsider `enumerate_lists` at low ctx.** It widened 7 questions, lost all 7, and caused all 3 crashes. At minimum, cap widening by the context budget rather than widening and then silently dropping 5–9 files.

## Golden-set amendments for the founders' silver→gold review

Recorded, **not applied** — changing `golden.json` changes `golden_sha` and would break comparability with this run. Decide these during human verification.

- `viz-06` — add "1 in 10 adults" as a `key_facts` variant; `info_024.jpg` prints it as one claim with "1.7 MILLION".
- `phone-03` — split `"Blitz Weinhard"` into two facts so a near-miss ("Biltz") can earn partial credit.
- `viz-11` — gold is `diagram_003.jpg` with 8 byte-identical twins in `acceptable_sources`; `recall@2` caps at 0.222 by construction. Collapse the duplicate set or exclude this pair from recall/nDCG aggregates.
- `nf-07-full` — the answer is the prose word "No" with the structured flag unset. `correct_abstain` should accept abstaining prose, as `false_abstain` already does.

## What this run does and does not measure

**Does:** the shipped production path — visual-tier retrieval with ColQwen2.5 and answer-time pixel reading by LFM2.5-VL-3B, on a hard 545-file multi-genre visual corpus with no summaries and no transcripts.

**Does not:** the transcript path (unwired), rerank or the solo gate (both off by choice), the summary/BM25 tier (structurally empty on an all-visual corpus), or cloud answering. It also does not measure most of the index-loss bug — 22 of 25 dropped files carry no golden item.

**Comparability:** no prior run shares this dataset or `golden_sha`, so nothing here is comparable question-for-question to the two committed `receipts` runs. Treat as a new baseline. Judged numbers stay provisional until the golden set is human-verified (all items are `human_verified: false`).
