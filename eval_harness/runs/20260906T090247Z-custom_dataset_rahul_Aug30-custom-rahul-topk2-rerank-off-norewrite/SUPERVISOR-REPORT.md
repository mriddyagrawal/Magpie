# Supervisor report — 20260906T090247Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

**Dataset** custom_dataset_rahul_Aug30 (545 files, 15 visual categories) · **Golden** 120 items / 60 pairs, REUSED unchanged, `golden_sha 0ebcdcbcdf109adb` · **Config** `custom-rahul-topk2-rerank-off-norewrite` unchanged: top_k 2, rerank OFF, rewrite OFF, solo_margin 0, temperature 0, local_n_ctx 16384, col_model auto → ColQwen2.5, lfm-local, grounding_guard ON + strict_grounding ON (production defaults, not in the config file, pinned by `envctl`) · **Backend** `92f9ba9` · **Wall** 2258.9 s (index mounted 1 s / answer 2224 / retrieve 34)

## Purpose

This run is the **BASELINE for a later compare against branch `prompt-image-order`** (inline images under file headers, system→documents→query order, clock above the question, rewriter clock fence). Everything below is written so that compare can read flips per cause. The most load-bearing result here is not a quality number — it is the **noise floor** (§2), which no previous pair of Magpie runs could measure.

## Verification (done before judging)

| Check | Result |
|---|---|
| `status` | `complete` |
| `isolation.real_appdata_untouched` | **true** |
| `isolation.cache_model_blobs_unchanged` | **true** (157 files / 27,157,872,740 bytes, byte-identical before and after) |
| `env_snapshot` vs requested config | **10/10 axes match, zero mismatches** — `LOCAL_TEMPERATURE=0.0`, `LOCAL_SOLO_MARGIN=0`, `MAGPIE_RERANK=0`, `LOCAL_N_CTX=16384`, `MAGPIE_COL_MODEL=auto`, `MAGPIE_FORCE_PROVIDER=local`, `LLM_PROVIDER=local`, `MAGPIE_GROUNDING_GUARD=1`, `MAGPIE_STRICT_GROUNDING=1`, `LLAMA_SERVER_STARTUP_TIMEOUT_S=300` |
| `solo_gate_structurally_off` | **true** — as accepted by the owner when choosing rerank OFF |
| answer/retrieve errors | **0 / 0** (prior run: 3 / 0) |

The recorded config was in force. **Neither isolation flag was affected by the untracked files in the tree** — `.agents/`, `src/inference/llm_queue.py`, `tokens.ipynb`. Those flags fingerprint the real app data dir and the shared model cache; repo state cannot reach them. Reported per instruction 6, but there was nothing to report: nothing was stashed or touched, and no flag went false. (Note: the `CLAUDE.md` / `Plans/Future Plans.md` edits mentioned in the brief were not present in the tree at launch — `git status` showed only those three untracked paths.) `src/inference/llm_queue.py` is referenced nowhere but its own docstring, so it is inert; `backend_git_sha` is `git log -1 -- src/` and is unaffected by untracked files.

**Two provenance gaps worth knowing.** `run.json.col_model_resolved` is `null` because resolution happens in the index phase, which was skipped on a store mount — the resolved retriever is recorded instead in the new `provenance.col_model` block (`colqwen2_5` / `vidore/colqwen2.5-v0.2`, mps, **float16**). And `provenance.qdrant.reachable` is `false` because provenance is computed at 09:02:48, before Qdrant starts. Neither invalidates anything; both make `run.json` read as less complete than the run was.

## 1. Index: mounted, not built — and why that is correct

The store `66974090bdcd62e6` was **mounted** (HIT, ~1 s), built 2026-08-30 under backend `cca67570`. The harness warned. I did not pass `--rebuild-index`, and the indexing agent verified the decision independently and more strongly than I had: `git diff cca67570..HEAD -- src/` touches 15 files (`answer.py`, `drift/*`, `inference/*`, `server.py`, `tools/`) and **every indexing file is byte-identical**; the decisive test is that the import closure of `{stage1_fast.model, stage2.fast_db}` — index-side *and* query-side encoder — intersects the changed set **empty**. Mounting is provably equivalent to rebuilding, and it keeps the index constant for the `prompt-image-order` compare, which is what that compare needs.

**Consequence to carry forward:** the index defects below are inherited verbatim from 2026-08-30 and are **identical in both arms of the future compare**. They are a constant, not a variable.

## 2. THE NOISE FLOOR — the reason this run exists

This is the first time two Magpie runs have ever shared config, `golden_sha`, index, rubric sha and judge model, so it is the first time flip noise could be measured rather than assumed.

Against `20260830T095758Z`: **10 judged flips of 120**, every one attributed:

| qa_id | judged flip | prompt | answer text | cause |
|---|---|---|---|---|
| `phone-05-typed` | false_abstain → wrong | DIFF | DIFF | code: HTTP-400 crash fixed |
| `phone-11-full` | false_abstain → partial | DIFF | DIFF | code: HTTP-400 crash fixed |
| `phone-05-full` | wrong → **correct** | DIFF | DIFF | code: prompt composition |
| `phone-07-typed` | wrong → false_abstain | DIFF | DIFF | code: prompt composition |
| `rcpt-08-typed` | wrong → false_abstain | DIFF | DIFF | code: prompt composition |
| `arch-08-full` | wrong → false_abstain | same | DIFF | model nondeterminism |
| `study-04-full` | partial → wrong | same | DIFF | model nondeterminism |
| `arch-05-typed` | partial → wrong | same | **same** | **judge noise** |
| `phone-03-full` | wrong → partial | same | **same** | **judge noise** |
| `viz-09-typed` | wrong → partial | same | **same** | **judge noise** |

- **Judge noise: 3/120 (2.5%).** Byte-identical answer string, identical evidence, identical rubric `47e93a279e70cef9`, identical model `claude-opus-5` — different verdict.
- **Model nondeterminism at temperature 0: 2/120 (1.7%).** Across 112 identical prompts, **4 produced different answer text** (111/120 answers are byte-identical overall). The GGUF filename, quant and mmproj variant are identical across runs, so the candidates are the llama-server binary bump and MPS kernel nondeterminism. **Not separable from this evidence** — separating it needs a same-binary re-run, which I did not do.
- **Attributable to the code axis: 5/120.**

> **Rule for the `prompt-image-order` compare: ~5 flips out of 120 are noise before any causal effect is counted, and 3 of those can flip on an unchanged answer. A verdict-level delta smaller than that is not a result.** Prefer paired comparison on *answer text* and *prompt composition*, which are far quieter than verdicts, and treat a verdict flip as real only when the underlying text or prompt also changed.

**Retrieval is provably constant.** On all 117 rows that completed in both runs the retrieved list is byte-identical; the 3 that differ are exactly the 3 rows that crashed in the prior run before retrieval was recorded. Every hit/recall/MRR value is unchanged. The single moving metric is `ndcg@5` (0.9219 → 0.9205), entirely from `viz-11` — tie-order among duplicate images (§5), not a ranking change. **100% of this run's movement is answer-side.**

## 3. Scoreboard

| | Judge | Deterministic |
|---|---|---|
| correct | 6 | 4 |
| partial | 17 | 17 |
| wrong | 36 | 38 |
| false_abstain | 45 | 45 |
| correct_abstain | 9 | 8 |
| false_answer | 7 | 8 |

Judge **VALID** (`claude-opus-5`, rubric `47e93a279e70cef9`), 13/120 disagreements, `matcher_precision 1.0`, 18 source files opened, **no gold answer overturned** — every gold fact the judge checked held. 7 golden issues raised (§7).

Prior baseline judged 5 / 16 / 39 / 44 / 9 / 7. The headline moved by roughly the noise floor. **This re-baseline did not change quality; it changed which failures are reachable.**

## 4. Findings, ranked

### 1. The grounding guard is this run's largest single failure cause — 31 of 45 false abstentions (69%)

On an all-image corpus the guard's support text is empty — 71 of 120 prompts have **zero text** between file headers, 40 more carry only the "scanned / image-only" banner — so `_apply_grounding_guard` degenerates to *"any number ≥ 100 in the answer → not_found."* The answers agent replicated the predicate exactly using the shipped `looks_fabricated`: **TP 31, FP 0, FN 0, TN 89**, and **zero of the 67 surviving answers contains a numeral ≥ 100.** That is not a guard, it is a filter on the answer's number range.

It destroyed real answers. Re-scoring the 31 suppressed texts with the harness's own matcher: **4 correct** (`arch-03-full` "849", `arch-06-full` "1506.0 / pH 7.8", `arch-07-full` all four KLM facts, `arch-09-full` "216.00 / 318.40"), 18 partial, 9 wrong. Guard-off counterfactual: false_abstain 0.433 → **0.135**, correct 0.038 → 0.077, partial 0.163 → **0.337**. Four fires are pure 4-digit-**year** artifacts — `MIN_INTERESTING=100` does not exclude years.

The 31 fires are **stable across runs** (31 in both, differing by a single swap: `rcpt-08-full` in the prior run, `study-03-full` here). This is a fixed ~26% tax on any all-image corpus, not run noise. All 53 abstentions partition with zero overlap and zero remainder: 31 guard + 22 model-set.

`baseline.json` already documents this measurement from 2026-09-03 and `e4ce01d` shipped the off-switch. **This run is the third independent confirmation, now with the 4 destroyed correct answers named.** The image-aware fix remains unwritten.

### 2. Prompt order inverts retrieval rank — directly relevant to `prompt-image-order`

In **all 104 two-file rows the prompt presents retrieval rank-2 as "File 1" and rank-1 as "File 2."** Every `[1]` marker the model can cite points at the distractor. The judge independently found the matching symptom without knowing the cause — "rank-2 contamination, right question, neighbour's document," ~10 items, e.g. `viz-01-full` answering "Denmark, 0.81" out of the rank-2 `chart_030.jpg` while rank-1 `chart_001.jpg` holds the answer its typed twin got right.

**This is the defect `prompt-image-order` exists to address, and this baseline now documents it in the arm without the fix.** The compare should test it directly: does rank-1-first change which file the answer is read from, independent of verdict?

### 3. Retrieval is at the ceiling the index imposes — one genuine ranking miss in the whole run

On the honest denominator (98 rows, index casualties removed) **hit@5 = 1.000, hit@1 = 0.9898**, against published 0.9423 / 0.9327. Raw hit@1 is 97/104 and **6 of the 7 misses are index-caused**; at k=12 the misses are *exactly* those 6. The retriever sits precisely on its ceiling.

The one true ranking failure is **`rcpt-05-typed`** ("that shop where i bought loads of chocolate bars total"): ColQwen put a Hallmark storefront photo and a café interior above the receipt because it is a visual matcher and matched the word *shop* to pictures of shops. Its `full` twin wins at rank 1. `rcpt-08-typed` is the only indexed-gold row below its recall ceiling — `bad_receipt_027.jpg` is a tilted washed-out scan whose merchant line reads "MR. O.I.Y."

RRF was a **no-op**: the store holds only `fast_tier`, every one of 1,437 sweep hits is `tier:"fast"` scored at exactly `1/(60+rank)`, so the ranking is raw ColQwen MaxSim and the "scores" carry no quality signal. That is also *why* the solo gate is structurally dead rather than merely switched off.

### 4. Index loss: 25 files / 55 pages, all inherited, all now root-caused with direct evidence

520 of 545 files and 709 of 764 pages are in the store. The indexing agent **re-encoded all 25 failed files on this machine** rather than assuming the prior investigation: 24 reproduce **100% NaN** under ColQwen2.5 fp16/MPS, 30 controls give 0 NaN, and **float32/CPU on the same images gives 0 NaN** — fp16 is the cause, not the input. The 25th, `scan_nglg0227.pdf`, reproduces **0 NaN** and failed purely on Qdrant's 32 MiB body cap (33,600,110 vs 33,554,432 bytes). One upsert per file (`index.py:139`) means **41 of the 55 lost pages (74%) are clean pages destroyed as collateral** — `scan_zxjd0228.pdf` lost all 12 pages to one bad one.

**6 of 120 golden items are structurally unanswerable** (`rcpt-07`, `study-05`, `study-10`, both phrasings). Worse, the loss is *mis-attributed*: `study-05` answers confidently from a different page and the judge writes "the answer says unstable at 90 degrees, contradicting the page" — comparing against a page the system could never see. **Four `wrong` and two `false_abstain` verdicts are index defects wearing an answer-quality label.** The eval observes only ~9% of the lost pages; 32 of 55 carry no golden item.

The run still exited 0. The only index gate is `manifest_entries == 0`.

### 5. The corpus contains duplicate images that make one metric meaningless

`diagrams/` is **40 files but only 9 distinct images** (31 byte-identical duplicates; `diagram_003…011` share sha256 `8acac741b245`). Identical vectors produce identical scores and therefore arbitrary order — which is the entire explanation for the only retrieval metric that moved between the two runs, and for both `top1_differs` rows. At `top_k=2` this fills both slots with the same picture twice on `viz-11`. Any citation or nDCG number on `viz-11` measures which duplicate the index happened to return.

### 6. Reporting defects that will mislead the next reader

- **`metrics.json` still publishes `solo_gate.fire_rate: 0.05` for a run where the gate cannot fire.** `enrich.py:369` infers gating from `len(retrieved)==1 and len(ranked)>=2`; all six "firings" are multi-page PDFs where `fetch_k=2` fetched pages that deduped to one file. Unchanged from the prior baseline — nothing in `enrich.py` was touched.
- **`hallucinated_citations: 0.183` does not mean hallucination.** All 56 cited entries name an in-prompt file; the metric counts non-gold neighbours. The real defect is upstream: of 67 non-abstain rows, only 2 had empty model `sources_used`, but **30 rows had their citations dropped entirely** because the 3B model emitted an ordinal ("1", "file 2") or page text ("GUY CODE") instead of a path.
- **Citation lists are mechanical**: 23 of 35 citers cite *every* file in the prompt. Precision 0.557 ≈ the 0.5 baseline of "cite both when one of two is gold". The metric measures `top_k`, not judgement.
- **`search.py:553` surfaces a 0-based `page_num`** — every multi-page citation is off by one.
- **`meta.json` records `col_model: "auto"`, not the resolved family**, despite a code comment claiming otherwise. A ColSmol machine computes the same index key and would silently mount incompatible vectors. The index key also carries no corpus content hash, so a stale mount is undetectable — this corpus happens not to have drifted.

### 7. Phrasing changes failure mode, not success rate — again

Paired McNemar over the answerable pairs: strict correct typed-only 1 vs full-only 5, **exact p = 0.219**; correct-or-partial p = 0.125. The judge's prose ("full beats typed 5 to 1") is an unpaired reading of a difference that does not reach significance. What phrasing *does* change: 19 of 52 answerable pairs flip verdict and 11 of those are `wrong ↔ false_abstain`. Median answer length is 3 words typed vs 11 full, so terse prompts yield single-token answers that can only be right or wrong, never partial.

`extract_rare_tokens` — the only keyword source with rewrite off — yields nothing on **113 of 120** questions (**0/60 typed**, 7/60 full: `pH`, `kW`, `arXiv`×2, `McDonald`, `RedVelvet`, plus a buggy `D.I` fragment). It could not have helped regardless: with no summary tier, the sparse keyword prefetch never runs.

## 5. Disagreements between reports, resolved

| Claim | Resolution |
|---|---|
| Prior investigation: "NaN serializes to the bare token `NaN`, invalid JSON" | **Indexing agent is right, prior report was wrong.** `qdrant_client`'s pydantic encoder emits **`null`**; the agent captured the wire bytes and reproduced Qdrant 1.17.1's exact error strings. The *effect* (400, skip, exit 0) is unchanged, so no conclusion moves — but the mechanism in the 2026-08-30 report should not be repeated. |
| Manifest note: `notes_iam` is meaningful distractor pressure | **Both agents refute it.** 5.8% of the index, 0.7% of sweep slots, 0.3–0.4% of top-2, and **zero** end-to-end slots on the 104 scored rows. Real pressure comes from screenshots + scene_text + photos (29.4% of non-relevant slots). The manifest's framing should be corrected at the silver→gold review. |
| Judge: `not_found_topic` "a landlord's emergency phone number" is a fixture leak on 12 rows | **Answers agent is right.** It is verbatim the example in Magpie's own system prompt, and 11 of the 12 rows have `not_found=false`. Still user-facing, but it is a prompt-design defect, not a harness leak. |
| Judge: the shared "ORDER, TIP WELL, WALK AWAY" string on two unrelated questions is "cross-photo bleed from some third photo" | **Answers agent is right** — `info_021.jpg` (the GUY CODE beer flowchart) was the rank-2 neighbour in *both* prompts. Not a mystery; it is finding 2 again. |
| My reading that the 2 newly-worse flips show "more files monotonically hurt" | **Survives, but narrowed.** I checked whether they were guard conversions: they are not (`rcpt-08-typed`, `phone-07-typed` are model-set abstentions in both runs). The mechanism holds. But n=2, and the prior report's own table rested on n=6/n=7 extremes — directional, not proven. |
| My reading that the HTTP-400 fix is a clean win | **Partly refuted by my own follow-up.** It rescued 3 crashes, but the guard immediately converted one of them (`study-03-full`) into a false abstention — the only new guard fire in this run. Net rescued to a real answer: 2. |
| Judge scored `viz-04-full` and `phone-08-full` as wrong | **Answers agent is right, they are `partial`** — one correctly-attributed right fact plus one wrong fact. The judge's "contradiction poisons" rule is not applied consistently elsewhere. (Also: `viz-04-full`'s deterministic 3/4 is bogus — two "matched facts" are the bare years the question supplies.) |

## 6. What this run does and does not measure

**Does:** the shipped production path — ColQwen2.5 visual retrieval and answer-time pixel reading by LFM2.5-VL-3B at 16K ctx — on a 545-file multi-genre visual corpus, with the production grounding guard ON, and with the **first measured flip-noise floor** for Magpie evals.

**Does not:** indexing (mounted, not built), rerank or the solo gate (both off by choice, and the gate is structurally dead regardless), the summary/BM25 tier (empty by construction on an all-visual corpus), the transcript path (still unwired), or cloud answering. It observes ~9% of the index-loss defect.

**Comparability:** question-for-question comparable to `20260830T095758Z` (same `golden_sha`, same index, same rubric, same judge model; backend differs). Judged numbers stay provisional — all 120 items are `human_verified: false`.

## 7. Suggestions

I have not edited `src/`. Ranked by value per unit of risk.

1. **Make the grounding guard image-aware** (`src/answer.py:_apply_grounding_guard`). It is the single largest correctable loss in this run: 31 conversions, 4 verified-correct answers destroyed, false_abstain 0.433 → 0.135 if disabled. Minimum viable fix: skip the guard when the support text is empty or banner-only (71+40 of 120 prompts here) — an answer read off an image has no text to be grounded in, so the guard is testing a proposition that cannot be true. Second, exclude 4-digit years from `MIN_INTERESTING`. `e4ce01d` gave us the off-switch and the measurement; this is the fix it was meant to precede.
2. **Assert on NaN immediately after encode** (`index.py`, after line 128): `if not torch.isfinite(t).all()` → retry that page in float32, else raise. Now verified three ways on this machine — 24/25 files, fp32/CPU clean, controls clean.
3. **Chunk the upsert by page, not by file.** Independently fixes the 32 MiB cap and stops one bad page destroying a document — 74% of lost pages are collateral.
4. **Fail the run on nonzero index errors.** `run_fast_batch` returns `None`, so the error count exists only as log text. A three-line `dataset_manifest_files (545) vs manifest_entries (520)` check would have caught this on Aug 30 and would have prevented six golden items being scored as answer-quality failures. Errors must also block store publication.
5. **Emit rank-1 first in the prompt** — or at minimum stop labelling the distractor `[1]`. `prompt-image-order` is already aimed here; this run gives it a documented before-state and a specific prediction to test (§4.2).
6. **Stop `enrich.py:369` inferring gate firings**; suppress `solo_gate` from `metrics.json` whenever `solo_gate_structurally_off` is set.
7. **Fix the `sources_used` parse** to accept an ordinal or a header-prefixed path — 30 of 67 answered rows lose their citations to formatting alone.
8. **Record the resolved col family in the index `meta.json`** and add a corpus content hash to the index key. Today a ColSmol machine computes the same key and mounts incompatible vectors silently.
9. **Gate the store-mount SHA check on indexing paths only** (empty diff → silent; non-empty → hard fail) and record the verdict in `run.json` rather than a stderr print. The current warn is correct in spirit but fires on every unrelated commit, which trains people to ignore it.
10. **Make `page_num` 1-based at `search.py:553`**, and thread it into the answer stage so a PDF renders the pages that matched.
11. **Collapse the duplicate `diagrams/` images** (40 → 9) or exclude `viz-11` from order-sensitive aggregates. It is the only source of metric instability between two otherwise identical runs.

## 8. Golden-set amendments for the founders' silver→gold review

Recorded, **not applied** — changing `golden.json` changes `golden_sha` and breaks comparability with both this run and the pending compare. The judge raised 7; these are those plus the carried-over items still outstanding.

- `phone-06` (both phrasings) — `key_facts` requires "Pure Running", the timing sponsor, which neither question asks for. A complete correct answer ("Laganside 10K") caps at `partial`.
- `arch-04` (both) — `key_facts` requires invoice number "A-3088"; both questions ask only for the balance due. "55.25" is complete and still scores `partial`.
- `viz-06-full` — accept "1 in 10 adults" as an equivalent to "1.7 million"; `info_024.jpg` prints them as one claim and the golden answer joins them with "or".
- `viz-11` (both) — gold `diagram_003.jpg` has 8 byte-identical twins; recall@2 caps at 0.222 by construction and nDCG is unstable. Collapse the duplicates or exclude the pair from order-sensitive aggregates.
- Several `key_facts` lists mix the answer with scene description (e.g. `study-06`), which makes a deterministic matcher structurally unable to score `correct` — a known source of judge/matcher divergence on the study tier.
- Carried over, still open: `phone-03` split "Blitz Weinhard" into two facts; `nf-07-full` should accept abstaining prose as `correct_abstain`.
- Correct the manifest's `notes_iam` note: measured distractor pressure is negligible (§5), not the "pure distractor pressure" the note implies.

## 9. Handoff to the `prompt-image-order` compare

1. Compare **against this run**, not `20260830T095758Z` — same code axis, so flips read as prompt-order effects.
2. **Clear the noise floor first**: ~5 flips/120 are non-causal, 3 of them on unchanged answer text. Report deltas in answer text and prompt composition alongside verdicts.
3. **Constants across both arms**, which must not be re-litigated as causes: the mounted index and its 25 missing files / 6 dead golden items; the 31 guard conversions; the duplicate `diagrams/` images; the empty summary tier.
4. **The specific prediction to test**: this arm labels retrieval rank-2 as "File 1" on all 104 two-file rows (§4.2). If `prompt-image-order` fixes that, the expected signature is a drop in rank-2 contamination among `wrong` verdicts — which is measurable per-question from `in_prompt` + `magpie_cited`, and is a much quieter signal than the verdict counts.
5. Keep `grounding_guard` ON in the compare arm so the axis stays single. If you want the guard's cost isolated, that is a **separate** two-arm run, not a knob to change here.
