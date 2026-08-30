# Supervisor report — 20260830T121044Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-rewrite

**Dataset** custom_dataset_rahul_Aug30 (545 files, 15 visual categories) · **Golden** reused, 120 items / 60 pairs, `golden_sha 0ebcdcbcdf109adb` (still silver, 0 human-verified) · **Config** top_k 2, rerank OFF, **rewrite ON** (the only knob changed vs run `20260830T095758Z`), solo_margin 0, lfm-local, temp 0, n_ctx 16384 · **Backend** `cca67570` (identical to baseline) · **Index** store HIT `66974090bdcd62e6` — mounted the baseline's index in ~1 s, byte-identical collection (verified) · **Wall** 2119.7 s (answer 2073.8 / retrieve 45.3 / mount ~1)

Provenance verified before judging: `status: complete`, both isolation checks true, env matches the requested config on every swept axis (provider, temp 0.0, solo margin 0, ctx 16384, `MAGPIE_RERANK=0`), `solo_gate_structurally_off` stamped, replay integrity `n_query_differs=0`. The comparability triple moves on exactly one layer (config: rewrite); backend SHA and golden_sha are identical to the baseline, so every delta below is a paired, question-for-question reading.

---

## The one-sentence result

**Rewrite ON cost 7.7 points of hit@1 (0.933 → 0.856; clean pool 0.990 → 0.906) and every point of that is one implementation defect, not the concept:** the shared LLM plumbing prepends a wall-clock line ("Current date and time: Sunday, 2026-08-30 08:NN EDT") to the rewrite call, and on terse typed queries the 3B rewriter reproducibly rewrites *the timestamp instead of the question* — with the echo rows excluded, rewrite's retrieval effect on this corpus measures 0.0 points, and answer quality is unchanged at the strict level (deterministic correct 3 = 3).

## Scoreboard

| verdict | judge, rewrite | judge, norewrite | deterministic, rewrite | deterministic, norewrite |
|---|---|---|---|---|
| correct | 12 | 5 | 3 | 3 |
| partial | 13 | 16 | 20 | 16 |
| wrong | 33 | 39 | 36 | 41 |
| false_abstain | 46 | 44 | 45 | 44 |
| correct_abstain | 11 | 9 | 10 | 8 |
| false_answer | 5 | 7 | 6 | 8 |

Judge VALID both runs (claude-opus-5, rubric `47e93a279e70cef9`); this session opened 24 source files, the baseline's 16 — **all 40 confirmed the golden answers; no gold has ever been overturned on this dataset.** Answerable (n=104): judge 12 correct (11.5%), 25 correct-or-partial (24.0%) vs baseline 5 / 21.

| Retrieval (replay pool n=104) | rewrite | norewrite |
|---|---|---|
| hit@1 | 0.856 | 0.933 |
| MRR | 0.862 | 0.935 |
| nDCG@5 | 0.845 | 0.922 |
| clean pool n=96: hit@1 / MRR | **0.906 / 0.913** | **0.990 / 0.992** |
| clean non-echo n=84: hit@1 | 0.976 | 0.988 |
| end-to-end (top_k=2, n=101): hit@1 | 0.851 | 0.931 |

Abstention: raw structured abstentions 51 vs 49; correct_abstain 11/16 vs 9/16 (judge) — the +2 is retrieval-lottery artifact, not improved discipline (finding 3). Same 3 HTTP-400 infra casualties as baseline (`study-03-full`, `phone-05-typed`, `phone-11-full`), scored false_abstain per rubric, excluded from cross-arm claims by both judges' advice.

---

## Findings, ranked

### 1. The timestamp injection is the whole retrieval story — mechanism fully resolved, fix is one line

`_prepend_timestamp()` (`src/llm.py:329`) puts `_timestamp_prefix()`'s wall-clock line as the first element of every LLM message list unless the output type is in `_NO_TIMESTAMP_OUTPUTS = {"FileSummary"}` (`src/llm.py:340`). `SearchQuery` — the rewriter — is not exempt, so every rewrite call opens with the clock line, followed by the user's question, followed by a JSON-format instruction. The comment block at the injection site *already documents this exact 3B-copies-the-date failure class* (it is why FileSummary was exempted); the rewrite system prompt then aggravates it by instructing the model to preserve "dates" verbatim — and the only date in context is the harness clock.

Result, per-row census over 117 completed rewrites (answers report §1.1, retrieval report §2.3): **class A, topic fully erased: 12 rows, all typed** (`arch-05`, `nf-01`, `nf-04`, `nf-05`, `nf-08`, `phone-09`, `study-04`, `study-10`, `viz-02`, `viz-07`, `viz-08`, `viz-10`); class B, clock text plus surviving topic: 23; class C, clean query but clock-token keywords: 17; clean: 65. Echoed timestamps advance minute-by-minute with the run (08:11 → 08:45 EDT, including an independent reproduction in the retrieve-phase re-rewrite of `phone-11-full`), proving per-call evaluation, and two different questions produced byte-identical echo outputs.

Retrieval damage is exactly the class-A answerable rows: **7 golds fell from rank 1 out of the entire top-12** (ColQwen, aimed at a pure date/time query, correctly returned the corpus's most date-dense pages — fax cover sheets with bold `Date:/Time: ... EST` headers, a degraded receipt printing `8:01:11 PM`, a tweet-timing deck; the retrieval agent opened them all). Whether gold survived an echo is perfectly predicted, 12/12, by whether any real content token survived anywhere in the concatenated ColQwen query string (`sq.query + " " + keywords`, `src/stage2/search.py:849` — on this corpus keywords act *only* through that concatenation; their sparse-prefetch leg targets the structurally empty summary tier). Net flips vs baseline: 9 worse, 1 better (`rcpt-05-typed` 5 → 1, the baseline's only genuine ranking failure, fixed by added receipt vocabulary — then wasted: the model answered off the rank-2 receipt anyway). −8 net rank-1 items / 104 = the entire −7.7 headline.

Within the typed register, no measurable feature (length, digits, case, interrogative shape) separates the 16 echoing from the 44 non-echoing typed queries — a deterministic per-prompt lottery. You cannot pre-screen for it; the fix is to remove the timestamp from the rewrite call or validate rewrites against the question.

### 2. The "5 → 12 correct" jump is roughly half scoring artifact; strict correct is 3 = 3

Decomposition of the +7 judge-correct (answers report §1.3–1.4, all 36 verdict flips traced): **+3 is judge run-to-run variance on byte-identical answers** ("55.25", "Laganside 10K" twice — same answer, same rubric, different session, different verdict); **+4 is real improvement, but partial-grade** — wrong → partial movements that this run's more lenient judge promoted to correct under a golden-set defect it itself flagged (over-specified `key_facts` demanding values the question never asks for). Under the deterministic scorer — identical code both arms — strict correct is 3 vs 3 and correct-or-partial moves 19 → 23.

The measured judge-noise floor: on 41 rows where both arms produced byte-identical answers, verdicts differ on 4 (~10%). This session disagreed with the deterministic pass 23 times vs the baseline session's 11 — mostly generous (16 upgrades). **Practical rule adopted for this project's A/B work: judged-correct deltas smaller than ~5 rows are indistinguishable from judge noise; use the deterministic verdicts for regression detection and the judge for direction and diagnosis.** A second, subtler channel: the baseline's four recorded-but-unapplied golden amendments did not stay neutral — each judge session adopts them or not unpredictably (this one scored a prose "No" as correct_abstain and "Biltz" as partial; the last one did the opposite), so the correct/partial boundary currently belongs to the judge session, not the golden set.

And the paradox is no paradox: the two motions live on disjoint rows. Retrieval died on 7 typed rows that were already mostly failing (baseline verdicts there: 2 partial, 3 wrong, 2 false_abstain — 8 points of hit@1 bought back only 2 previously-passing rows), while every answer-side gain happened where gold was retrieved in both arms and the rewrite merely re-rolled the rank-2 distractor.

### 3. At top_k=2 with rerank off, answer quality is a distractor lottery — and rewrite mostly re-rolls the dice

Of 36 verdict flips, 31 are rewrite-mediated retrieval changes, and 14 of the 15 improvements are the same mechanism as 7 of the 9 regressions: **which file sits at the other prompt slot next to an intact gold.** Replace a confusable same-genre neighbor (a second chart, another receipt) with an obviously-irrelevant file and the model reads the gold (`viz-01-full` wrong → correct); do the reverse and it reads the neighbor (`viz-01-typed` correct → wrong — the pair literally swapped which half wins on exactly this). The date-contaminated keywords are a large hidden hand here: clock tokens pull receipts into rank 2, and an irrelevant receipt next to a gold chart is an accidental, degenerate solo gate. This measured effect is the strongest evidence yet for the baseline's finding 5 (fewer files monotonically better) and for reranking/gating deliberately rather than by lottery.

Phrasing split (the run's cleanest genuine result): **full-phrasing improved 8 rows and regressed 0 (paired across arms, p=0.008); typed churned 7 up / 9 down (p=0.80).** Typed-vs-full within this run is now a rate gap (judge success 14 → 10 typed vs 16 → 26 full; answerable discordant pairs 1 vs 16, p=0.0003), where the baseline had found mode-not-rate. But the answers agent's subset analysis corrects the judge's summary attribution: the gap is *not* concentrated in hijacked pairs — clean-typed pairs show the sharpest full advantage (p=0.004). Rewrite turned one product into two: genuinely better on verbose questions, a coin flip on terse ones. Even the full-side gain is composition-lottery in mechanism, so it should motivate rerank/gate work, not a rewrite-on default.

Abstention behaved consistently with this: of the 8 answerable class-A garbage retrievals, 4 abstained and 4 confabulated fluently off unrelated receipts (`viz-08-typed` answered "31.00", `bad_receipt_005.jpg`'s printed total; `study-10-typed` recited a receipt line). The hijack also manufactured 2 brand-new false answers on not_found probes (`nf-01-typed`, `nf-05-typed` — both answered "31.00" off the same receipt) while accidentally curing 4 baseline false-answers by hiding their trigger files; the entire +2 correct_abstain gain is that artifact, not discipline.

### 4. H2′ (docket): threshold formally cleared — by the defect, not the concept

H2′ predicts rewrite changes hit@1 on vague phrasings by ≥10 points. Measured on typed (the vague proxy): **−13.5 points with echo rows in; 0.0 points with them out** (n=37 clean pairs: each arm misses one different item); full −1.9 (inside the no-effect band). Caveats: n=49–52 typed is below H2′'s pre-registered ≥64 floor, and this is one corpus. Recommended docket entry: *the ≥10-point movement exists and is entirely attributable to the timestamp-injection defect; the intended-behavior effect on vague phrasings measures 0.0 on this corpus; H2′ proper remains open pending the fix.* This run is also direct quantitative vindication of the existing production default (rewrite off locally) and of the `search.py` comment that motivated it.

### 5. What did not move — the product's core limitations are rewrite-invariant, as they should be

- **Printed-number abstention replicates almost frozen:** number questions abstain 34/60 (57%) vs non-number 7/33 (21%), p=1.1e-3; the number side is 34 in both arms row-for-row. The reading limitation lives in the answer stage; no query knob touches it.
- **False abstention on a correct retrieval is still the biggest bucket:** 46 false abstains, gold retrieved in 38 (baseline: 38/44). The `arch` family: 17/20 false-abstain with gold present for all but one.
- **The same 3 HTTP 400s, now proven query-independent:** the LIST_ALL widener classifies the *raw question* (identical across arms), and `phone-05-typed` overflowed at ~the same token count (16,551–17,761 vs the 16,384 window) with 5 of 7 prompt files different. It is a property of the question class plus the flat 6,000-char image cost, not of retrieval.
- Baseline reporting bugs all reproduce: `not_found_topic` landlord leak (12 rows), verbatim topic echo (35 rows, 100% typed), query-echo answers (4, all typed), citation degeneracy (0/57 citations name an absent file; 1/38 lists is a genuine subset), phantom `solo_gate.fire_rate` 0.042 published while the gate is structurally off — with a twist that settles the phantom's nature: the phantom set *changed* (6 → 5 rows) purely because a rewritten query altered one row's fetch-window composition. The metric tracks retrieval dedup, not gating.

### 6. The `sources_used` header-parse bug is now provably deleting correct citations

9 entries arrived as `"--- File N: <path> ---"` and were dropped by the exact-match guard; **4 of the 9 named the gold file, and 3 of those are judge-`correct` answers that the judge then criticized for citing the wrong file** (`viz-01-full`, both `phone-02` halves). The model actually cited the gold; the parse deleted it. Fixing the strip is a free citation-metric gain and removes a judge-facing distortion.

### 7. The mount worked perfectly — and exposed four provenance gaps worth closing

The indexing agent verified byte-identical storage (only an empty `temp_segments` scratch dir differs), zero write requests in 720 (all HTTP 200), md5-identical manifest (520 entries), a perfect manifest↔collection bijection (709 points), all 520 payload paths resolving, and the same 25-file / 6-item loss as the baseline (5.0% of items doomed by the index in both arms — which is exactly what makes the arms comparable). Gaps: (a) **nothing in a mounted run records the retriever family** — `col_model_resolved` is build-path-only, and the store meta records raw `"auto"` (the `run.py:47-51` comment claiming otherwise describes unimplemented intent), so a synced store or changed auto-resolution would silently mix embedding spaces; (b) manifest `content_hash`/`mtime` are null, so mounts do no corpus revalidation; (c) mount time and phase are absent from `run.json` and — verified against the harness SHA this run executed (80f7c61: `progress.update(phase="index", ...)` exists only in the build branch) — from the progress sidecar, so a mounted run's watch page never shows an index phase; (d) each mounted run copies 788 MB into `runs/<id>/raw/`.

### 8. Golden-set specification is now load-bearing and must be settled before the next arm

This judge flagged 14 golden issues; 2 repeat baseline amendments (`viz-06`, `viz-11`), 12 are new — dominated by over-specified `key_facts` (9 rows demanding values the question never asks: "72%", "A-3088", "Intel", "Pure Running") and compound unscorable facts (3 rows). 8 of this judge's 9 partial→correct upgrades sit exactly on the over-specified set — the "12 correct" headline deflates to the deterministic picture without that policy. Recorded, not applied: `golden.json` is untouched and `golden_sha` unchanged. The founders' silver→gold review should decide the key_facts trims (or a required/context split) **before** another arm is judged, because until then the correct-vs-partial boundary is judge-session property (finding 2).

---

## Disagreements between reports, resolved

| Claim | Resolution |
|---|---|
| Supervisor mid-run: "5 echo rows kept gold at rank 1 with identical garbage queries — mystery (keywords fusion leg? tie behavior?)" | **Premise refuted by the retrieval agent, accepted.** Survivor queries were never bare timestamps — all 5 retain real content tokens (hybrid class B), and content-anywhere-in-the-concatenation predicts survival 12/12. Keywords have no separate fusion vote on this corpus (empty summary tier); ColQwen tie behavior is irrelevant. |
| Supervisor: "16/60 typed replaced entirely" | **Modified by both agents, consistently.** 16 contain the literal phrase, but only 10 of those are full replacements; the canonical topic-erased set (class A) is 12, adding `nf-04-typed`/`nf-05-typed` phrased differently. Agents' totals for query-level contamination (34 vs 35 rows) differ by one row at a definitional edge — immaterial; the class taxonomy above is adopted. |
| Judge: "the rewriter accounts for most of the typed-vs-full gap" | **Answers agent's paired analysis adopted:** clean-typed pairs show the sharpest full advantage (p=0.004), so the gap is mostly rewrite *lifting full*, with the hijack truncating typed's upside. The judge is right that the hijack is the largest single lever on typed `wrong`s. |
| Judge: "retrieval depth is bimodal and unexplained (eight 12-doc rows)" | **Explained by the retrieval agent:** the `enumerate_lists` widener classifies the raw question, so the widened set is rewrite-invariant by construction — the same 7 completed rows in both arms, plus the 3 overflow crashes. |
| Judge scored the 3 HTTP-400 rows `false_abstain` | Per rubric, correct labeling; **all three reports and both judges agree they are infrastructure failures excluded from cross-arm answer-quality claims.** Adopted throughout this report. |
| Indexing agent (hedged): "the missing sidecar index entry probably predates the fix; not confirmable" | **Confirmed by supervisor git inspection:** at this run's `harness_git_sha` 80f7c61 the mount branch writes no sidecar entry — the gap was live in the executed code, not pre-fixed. |
| `metrics.json hallucinated_citations: 0.240` | As in the baseline: counts non-gold citations, not invented paths — 0 of 57 citations named a file absent from the prompt. The real citation defects are the degenerate copying and the header-parse deletion (finding 6). |

## Corrections to my own earlier claims

1. "Rewrite replaced the entire query on 16/60 typed" — overcounted full replacements (10 of those 16; canonical class A = 12) and undercounted total contamination (52/117 rows somewhere in query or keywords).
2. My survivor-mystery framing had a false premise (see table above); the resolution is the retrieval report's central finding, not mine.
3. My hypothesis that a "keywords leg in fusion" rescued survivors was mechanically wrong — keywords enter ranking on this corpus only via string concatenation into the ColQwen query.
4. My mid-run progress note inferred rewrite would slow the run; the answer wall was 374 s *faster*, and the answers agent showed it is a host-speed confound (generation 232 s faster on 43 byte-identical prompts) — rewrite's true marginal cost is +1.2 s/question. Do not book the wall-clock saving to rewrite.
5. My early framing of "correct 5 → 12" as the headline improvement was wrong by half — see finding 2.

---

## Suggestions

I read `src/` but edited nothing. Ranked by value per unit of risk:

1. **Add `"SearchQuery"` to `_NO_TIMESTAMP_OUTPUTS` (`src/llm.py:340`).** One line. The rewriter has no legitimate use for "today" (it resolves nothing time-relative; it *invents* dates — `nf-07-typed` asserted the user's certificate was issued on the run date). The codebase already exempted `FileSummary` for this exact failure. Deletes the entire class-A mechanism and, per the clean-pair analysis, would leave rewrite within one item of norewrite on this corpus.
2. **Validate rewrites against the question:** `rewrite_query()` already falls back to the raw question on parse failure (`search.py:110-111`); extend the fallback to zero-content-word-overlap between rewrite+keywords and the question — that predicate separates all 7 losers from everything else in this run with no false positives.
3. **Strip pure date/time tokens from `keywords` before the `search.py:849` concatenation.** Defense in depth; on a mixed text corpus the contaminated keyword lists would get a dedicated BM25 vote, so the blast radius there is plausibly larger than measured here.
4. **Fix the `sources_used` header parse** (strip a leading `--- File N: … ---` before the hallucination guard). Baseline suggestion, now upgraded by proof that it deletes gold citations from judge-correct answers.
5. **Harness, mount provenance:** stamp the resolved col family (family + model id + device/dtype) into store `meta.json` at publish and into `run.json` on mount, warning loudly on mismatch (makes the `run.py:47-51` comment true); write `phases.index = {mounted: true, wall_s, manifest_entries}` and a sidecar entry on the mount path; populate manifest `content_hash` so mounts can revalidate; consider hardlinking instead of copying 788 MB per mounted run.
6. **Golden v2.1 before the next judged arm:** trim or split the over-specified `key_facts` (finding 8) and adopt the four baseline amendments — unadopted amendments are a per-session judge lottery that moved verdicts in both runs.
7. **A/B discipline going forward:** deterministic verdicts for regression detection; judged-correct deltas under ~5 rows are inside the measured judge-noise floor; interleave arms or record a thermal baseline before crediting latency deltas.
8. **Rewrite prompt hardening** (if rewrite is ever to ship): instruct preservation of every named target — `viz-05-full` shows the rewriter deleting one of a two-chart comparison, an echo-independent intent-loss failure of the same 3B weakness.
9. **Suppress the `solo_gate` block in `metrics.json` when `solo_gate_structurally_off`** — repeat of the baseline suggestion, still unfixed, and this run demonstrated the phantom tracks retrieval composition (6 → 5 rows purely from a query change).

## Recommended next run

Land suggestion 1 (plus 2–3 if cheap) and re-run this exact config. That is the true H2′ test: it isolates intended-behavior rewrite at the config that matters, on a corpus where the clean-pair evidence predicts ~0 retrieval delta but a possible genuine full-phrasing answer gain worth confirming without the confound. Note it will move `backend_git_sha`, so it opens a new comparability cell by design. Independently valuable and orthogonal: a rerank-ON arm to convert the distractor lottery (finding 3) into a deliberate mechanism.

## What this run does and does not measure

**Does:** the shipped visual-tier pipeline with query rewriting ON, exactly one knob from the norewrite baseline, on the same mounted index — the cleanest paired comparison this harness has produced (94/104 rows byte-stable across arms 2.5 hours apart).

**Does not:** rewrite×rerank interaction (rerank off throughout), the keyword/BM25 path (summary tier structurally empty on an all-visual corpus), transcripts (still unwired), cloud answering, or most of the index-loss defect (22 of 25 dropped files carry no golden item). Judged numbers remain provisional until the golden set is human-verified; this run added 14 specification flags to that review queue.

**Comparability:** paired to `20260830T095758Z-…-norewrite` on all three provenance layers except config. Not comparable to the receipts runs (different dataset/golden) — and note both this run's grading and the baseline's postdate the GBNF merge, so PLAN's #78 grammar caveat does not apply between these two arms.
