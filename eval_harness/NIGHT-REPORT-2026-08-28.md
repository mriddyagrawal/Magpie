# Eval harness — overnight build report (2026-08-28)

> ⚠️ All accuracy numbers below are from a **SILVER (unverified) golden set**.
> Directionally trustworthy — the effects are 20–60 points, not 2 — but do not
> publish figures until the silver→gold review (PLAN §6) is done.

## TL;DR

The harness is built, isolation-proven, and produced its first real science in
one night: **retrieval is excellent (hit@1 = 0.87), and the local vision answer
path collapses as context widens — 61% → 0% across k=1→12.** Context stacking,
not the model, is the dominant failure (your thesis, confirmed with precision —
with one carve-out: even solo, the model misreads ~⅓ of receipts). Five product
bugs found, each verified in code, including one that structurally disables the
solo gate on exactly the corpora it was built for.

## What was built (all phases 0–2 + judge scaffold; PLAN §7)

- **Phase 0 complete, exit test passing 13/13**: controlled env (managed-set
  contract over `.env`), per-run private Qdrant (the vector store was NEVER
  isolated by `MAGPIE_DATA_DIR` — it's a localhost server), shared model cache
  with zero-download enforcement, provider forced via `MAGPIE_FORCE_PROVIDER`,
  write/read isolation proven against the live app with a conflicting `.env`.
- **Phase 1 complete**: config-driven runner (`harness/run.py`), resume-safe
  worker phases (index / retrieve / answer), per-run provenance (git SHAs,
  machine, redacted env, status), `--reuse-index` cache, isolation violations
  fail the run.
- **Phase 2 complete**: pre-gate retrieval pass at k_max (the answer pass
  returns POST-gate lists — discovered, not assumed), pure-Python IR metrics
  cross-checked exactly against pytrec_eval (41 cases, 0 mismatch), qrels.
- **Enrichment**: observed-never-inferred scoring — `in_prompt` from the
  backend's own prompt markers, fact spans three-valued, prose-abstain
  detection, solo-gate observation self-validated, per-basis H1.
- **Judge scaffold (Phase 3 start)**: binary reference-guided rubric v1.0,
  claude-CLI engine, judges only rows determinism can't settle + samples
  correct rows to measure matcher precision. Validated live.
- **Dataset**: `receipts` — 150 SROIE scans (pinned revision, verbatim bytes,
  sha256-verified), 53 mechanical golden items (42 extractive / 6 not_found /
  5 enumeration), blind-by-construction, opaque filenames.
- 21 unit tests; runbook README; ~60 review findings from the reviewer
  instance processed across 20 commits (see comments.md on this machine).

## The numbers (receipts · lfm-local · temp 0 · ctx 16384 · silver set)

Retrieval (identical across arms, k_max=12 pre-gate): **hit@1 .87 · hit@5 .94 ·
MRR .90 · nDCG@5 .91**. ColQwen is doing its job.

Answering vs context width (same cached index, only `top_k` changes):

| k | correct (answerable) | H1-eligible accuracy* | eligible n | false-abstain | true-not_found OK | citation prec. | p50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **1** | **46.8%** | **61.1%** | 36/42 | 23.4% | 1/6 | .60 | **9.6s** |
| 3 | 14.9% | 15.8% | 38/42 | 21.3% | 0/6 | — | 23.5s |
| 5 (prod) | 2.1% | 2.6% | 38/42 | 63.8% | 4/6 | .06 | 35.6s |
| 12 | 0.0% | 0.0% | **21/42**‡ | **91.5%** | 6/6† | — | 34.8s |

\* file-level basis (image corpus — fact-level spans unobservable; PLAN H1
caveat). † at k=12 the model abstains on ~everything, so "perfect" abstention
there is just blanket refusal. The true-not_found column is raw counts on
n=6 — the non-monotonic swing is what noise looks like at that n; don't read
a story into it. ‡ k=12's eligible half is a rank-biased survivor subset —
gold was budget-evicted for the other 21 (see caveats below).

**Read**: the shipped config (k=5) answers **1 of 47**; a single file answers
**22 of 47** — same questions, same index, 3.7× faster. The failure mode flips with k: low k
force-answers (bad on not_found), high k blanket-refuses (bad on everything).
Curve caveats (reviewer #67/#68): judge H3 on the H1-eligible column (extractive
only) — enumeration items are exempt from k (the router widens their top_k, so
they never varied) and dilute the "correct" column ~equally across arms; and the
k=12 point is half a BUDGET result — twelve receipt images exceed ctx-16384, the
gold file was evicted for 21/42 extractive questions (dropped 10→145), so its
eligible half is a rank-biased survivor subset.

## Product bugs found (each verified in code)

1. **Rerank flattens all visual-tier scores to a constant** —
   `src/stage2/rerank.py:92` pairs the query against the placeholder
   `"(visual match — page N)"` (`search.py:523`) and OVERWRITES scores with the
   result. Every margin is exactly 0.0, so `gate_to_solo` can never fire on
   image corpora — the distractor mitigation is dead precisely where it's
   needed. (Observed: 0/53 fires; the 2026-08-24 "fires ~24%" was text-corpus.)
2. **Structured `not_found` fires on 64–92% of answerable vision questions at
   k≥5** — grammar-conforming blanket refusal with gold in the prompt.
3. **`sources_used` ≈ empty on the local vision path** — `[1]` markers appear
   in answer text but citations are stripped/never populated (precision .06 at
   k=5). Citations are the headline feature.
4. **Prose abstain without the flag** — the model sometimes declines in prose
   while `not_found=false`, so the frontend would render a normal answer card
   instead of the not-found state.
5. **`summarize.py:603` calls `sys.exit()` on a legitimate all-image folder** —
   would kill a host process in production; the harness absorbs it, but it's a
   library-code bug.

## Hypotheses docket status (PLAN §"Neutrality")

- **H1 (≥85% when fact available): REFUTED at the shipped config** (2.6%
  file-level basis) and still short at the best arm (61.1% at k=1) — the model
  misreads solo receipts ~⅓ of the time, so scaffolding is the main problem
  but not the whole problem. Reviewer-verified robust to all known scoring
  bugs (even scoring every "wrong" as correct, k=5 ≤ 36%).
- **H3 (accuracy degrades with k): CONFIRMED**, 61 → 0 points across the
  bracket — beyond the ">40 = consistent with the ladder" band.
- **H5 (gate recovers the collapse): BLOCKED on receipts** by bug #1 — the
  gate cannot fire there at any margin. Test on a text corpus or after the fix.
- **H2 (rewrite helps vague queries): REFUTED — no recall effect at the
  pre-registered threshold, in either direction.** recall@5, retrieval-only
  arms: vague ON .875 vs OFF .906; primary ON .936 vs OFF .979. Both deltas
  are under H2's own 10-point floor (primary is inside its <5 "no movement"
  band), so the docket's rule reads them as no effect — NOT as "rewrite
  hurts." In counts: the entire vague-phrasing difference is **one question
  out of 32** (28/32 vs 29/32). The claim that survives: rewrite costs
  ~1.3–2s per query (a mechanism, not a measurement), so on this corpus it
  isn't earning its latency. Single-corpus; ≥2-corpora rule before acting.
  Follow-up registered as H2′: after H3, the decision-relevant config is
  k=1, where hit@1 — not recall@5 — is the whole retrieval story, and hit@1
  moved more (26/32 vs 29/32 on vague; still 3 questions, not a finding).
- **H4 (grammar): not yet run** (needs a grammar off-switch investigation).

## What this suggests for the product (owner's call, not tonight's)

- Fix rerank's placeholder scoring (feed ColQwen scores through, or skip
  cross-encoding for fast-tier hits) — it unblocks the gate AND H5.
- The k=1-vs-k=5 gap says confident-retrieval→narrow-context is the right
  product direction (the gate's bet), but it needs working scores and an
  abstention story: k=1 force-answers on absent vendors (83% false-answer).
- The not_found grammar path needs a look: at prod k it's the dominant output.

## Next steps

1. Founders: silver→gold review of the 53 golden items (~2–3h; the 6
   `not_found` items carry specific review notes) — unlocks acting on numbers.
2. Judge calibration (PLAN §7 Phase 3): both founders label the same 30–50
   judged rows; fixture includes unlike-gold phrasings.
3. H4 ablation (needs a grammar off-switch first); H5 on a text corpus;
   re-test H2 on a second corpus before acting on the rewrite-off finding.
4. Datasets 2–3 (personal_notes, furman_directory) per PLAN §6.
5. Decide which product bugs to file as issues (drafts above are
   copy-pasteable; I did not file publicly from a silver-set night run).

## Reproduce

```bash
uv run python eval_harness/scripts/phase0_isolation_check.py   # 13/13
uv run python eval_harness/harness/run.py --config eval_harness/configs/baseline.json
uv run python eval_harness/harness/run.py \
    --config eval_harness/configs/ablations/topk1.json \
    --reuse-index <baseline-run-id>
```

Run artifacts: `eval_harness/runs/…-receipts-{baseline,topk1,topk3,topk12}/` at commit `18c4035` (runs wiped in `c97e031`; recover via `git show`).
