---
name: magpie-eval-compare
description: Compare two or more completed Magpie eval runs - deterministic paired diff, agent cause-attribution for every flip, and a decision-grade verdict. Trigger with /magpie-eval-compare.
---

# Magpie eval comparison — supervisor procedure

You are the SUPERVISOR for one comparison of completed eval-harness runs.
The deterministic layer is code (`eval_harness/harness/compare.py`); your
job is everything code cannot do: cause attribution, judgment, and the
verdict. Ground rules for the whole procedure:

- **Ask the owner whenever uncertain** — which runs, what question the
  comparison should answer, borderline attributions. Use AskUserQuestion
  freely; the owner prefers questions over silent guesses.
- **Read-only over `eval_harness/runs/`** — never modify a run directory,
  and never edit `src/`. Findings are reported, not fixed, by this skill.
- Everything of record goes in the comparison directory
  (`eval_harness/comparisons/<id>/`). Commit at each milestone.
- Read `eval_harness/PLAN.md` §2 (parameter axes and their confounds)
  before interpreting any config diff.

## Phase 1 — Interview

Ask (multiple rounds fine):

1. **Which runs?** List `eval_harness/runs/*/run.json` with config_name,
   status, started_utc, and the comparability triple (params hash where
   available, `backend_git_sha`, `golden_sha`). Ask which run is the
   BASELINE and which run(s) compare against it. Only `status: complete`
   runs qualify; if the owner insists on an incomplete run, pass
   `--allow-incomplete` and carry a caveat into the verdict.
2. **What question is this comparison answering?** ("did the ordering fix
   work", "is k=3 worth the latency", "did the code change regress
   anything"). The verdict must answer THIS question, not just list
   deltas.
3. **Axis check.** Diff the triple yourself before running anything:
   - exactly one axis differs (config / code / questions) → clean
     comparison, proceed;
   - multiple axes differ → CONFOUNDED: tell the owner which axes moved
     and ask whether to proceed anyway (the report will carry the
     confound warning) or to first produce a run that isolates one axis;
   - zero axes differ → this is a re-run comparison; still legitimate
     (it measures run-to-run noise), and say that is what it measures.
   Remember the standing couplings: `rerank: false` is structurally also
   a solo-gate change (#112); `golden_sha` change means different
   questions and forces intersection mode.

## Phase 2 — Deterministic diff

Run:

    uv run python eval_harness/harness/compare.py <baseline> <other...>

Then READ `COMPARISON.md` and `comparison.json` and verify before
trusting: pairing mode and coverage, which axes it detected (must match
your Phase 1 analysis - investigate any mismatch), and the discordant
counts. The tool marks any metric with fewer than 5 discordant pairs as
not credibly non-noise; those numbers are context, never conclusions.

Per-question retrieval numbers use the `ranked_pre_gate` basis, which is
known to disagree with the end-to-end `ask()` list on some questions —
keep that caveat attached to any retrieval claim you make.

## Phase 3 — Cause attribution (agents)

Every flip the diff surfaced gets a CAUSE, not just a label. Spawn a FEW
agents (2–4, batched — not one per flip), each given a batch of flipped
questions with, per question: both runs' enriched rows, both raw
`answers.jsonl` entries, both retrieved lists, and the corpus file paths
(agents may read the actual images/files — standing approval exists for
eval corpora; still say it out loud for personal corpora).

Each flip must be classified into exactly one primary cause:

- `retrieval_change` — different files retrieved/ranked; answer followed.
- `prompt_assembly` — same files, different presentation (ordering,
  truncation, context overflow).
- `guard` — grounding guard / abstention behavior differed.
- `model_variance` — same inputs, different generation (should be ~zero
  at temperature 0; a nonzero count is itself a finding).
- `judge_disagreement` — the answers are materially the same; only the
  grading differs.
- `infra_error` — HTTP errors, timeouts, context overflows (check the
  `error` field and worker logs before any other attribution).

Agents return per-flip: cause, one-sentence evidence, and confidence.
Verify at least two attributions per agent yourself (spot-check against
the raw artifacts) before accepting the batch; a failed spot-check sends
the batch back with the correction.

Also spawn one **regression hunter** agent over the full diff (not just
flips): silent shifts in citations, abstention rate, latency,
`env_snapshot` diffs, error counts — anything that moved without
flipping a headline metric.

## Phase 4 — Synthesis

Append to `COMPARISON.md` below the marker line
(`<!-- magpie-compare agents append below this line -->`):

1. **Verdict** — answer the owner's Phase-1 question in the first
   sentence, then qualify: is the delta decision-grade (≥5 discordant,
   p, cause-attributed) or suggestive-only?
2. **Cause table** — every flip with its attributed cause; aggregate
   counts per cause. If one cause dominates (like a prompt-assembly bug),
   say what single change the data points at.
3. **Slice story** — typed vs full phrasing and answer_type slices, only
   where discordant counts make them meaningful.
4. **Regression-hunter findings** — anything that moved silently.
5. **Recommended next run** — the single config/code change that would
   best answer the owner's question next, with its expected cost (index
   cache hit or miss, answer-run wall-clock).

Also update `comparison.json`: add a `"synthesis"` object mirroring the
verdict, cause counts, and per-flip attributions (machine-readable, so
future comparisons can cite it).

Commit the comparison directory when done. Judge verdicts are
authoritative for answer quality wherever both runs have them; the
deterministic verdict is a matcher and is always labeled as such.

## Hard rules

- One comparison per skill run (one baseline; N comparison runs allowed
  against it in the same invocation of compare.py).
- Never average away disagreement: report discordant counts alongside
  every rate, and never present a sub-5-discordant delta as a finding.
- Never re-grade answers yourself — grading belongs to the judge from
  each run; your layer is cause attribution and synthesis.
- If the two runs' judges disagree wildly on concordant answers
  (`judge_disagreement` cause > ~20% of flips), stop and tell the owner
  the comparison is judge-limited: the next step is judge calibration,
  not more runs.
