---
name: magpie-eval
description: Run a full Magpie evaluation end to end - interview the owner, prepare a golden set, drive the harness, judge, and produce reports with agents. Trigger with /magpie-eval.
---

# Magpie eval — supervisor procedure

You are the SUPERVISOR for one evaluation of Magpie's backend. You orchestrate;
deterministic execution belongs to the harness CLI, judgment belongs to agents
you spawn. Ground rules that apply the whole way through:

- **Ask the owner whenever you are uncertain** — dataset semantics, ambiguous
  config choices, borderline golden items, anything. Use AskUserQuestion
  freely; the owner prefers answering questions over silent guesses.
- Everything of record goes in `eval_harness/runs/<run_id>/` (summaries
  committed, `raw/` never). Commit at each milestone.
- Read `eval_harness/README.md` and `eval_harness/PLAN.md` before starting;
  they are the source of truth for mechanics and schemas. This skill is the
  procedure, not the documentation.

## Phase 1 — Interview

Ask (AskUserQuestion, multiple rounds fine):
1. **Dataset** — which `eval_harness/datasets/<name>`, or a new corpus path.
2. **Golden set** — one of: *reuse* the committed golden as-is; *adapt* an
   existing annotation source into our schema; *generate fresh* by reading the
   files (Phase 2).
3. **Config / permutations** — which arms to run: model_config, top_k,
   rewrite on/off, solo-gate margin (0 disables the gate; it is a first-class
   axis), temperature, anything else in `configs/baseline.json`. Offer
   baseline-only as the default and ablation arms as options. One index per
   index-side config; reuse it across answer-side arms (`--reuse-index`).

The judge is NOT a question: it always runs.

## Phase 2 — Golden set (only if generate/adapt)

Spawn a FEW agents (3–6, batched by files — not one per question) that READ the
actual files with their own vision/text understanding. Labels or existing
annotations, when they exist, are withheld from the generating agents and used
only as a post-generation cross-check; disagreements get flagged for owner
review, not silently resolved.

Question requirements:
- **Persona-real**: first decide who would actually own this corpus (a student
  with class notes, a household with receipts, an employee with HR letters) and
  have agents write what THAT person would type or ask. Nothing that reads like
  a benchmark.
- **Dual phrasing**: every fact asked twice — `typed` (terse, lowercase,
  occasional typo, how people hit a search box) and `full` (complete sentence)
  — sharing a `pair_id`.
- **Difficulty mix**: easy / medium / hard, recorded per item.
- **Multi-file items**: several questions must span 2–3 files (comparisons,
  cross-file totals, counts, date lists), plus ~10–15% `not_found` items about
  plausible-but-absent subjects.
- Schema: exactly `golden.json`'s fields (`golden_answer`, `key_facts`,
  `gold_sources`, `phrasing`, `pair_id`, …) as in the existing dataset files;
  regenerate `qrels.tsv` and update `manifest.json`. All items
  `human_verified: false` until the founders review.

Assemble, cross-check, show the owner a sample plus anything doubtful, commit.

## Phase 3 — Run

For each arm, launch in the background, wrapped so the Mac cannot sleep:

```bash
caffeinate -dims uv run python eval_harness/harness/run.py \
    --config <config> [--reuse-index <prior_run_id>] > /tmp/<arm>.log 2>&1
```

Schedule a wake every **3 minutes** (ScheduleWakeup). At each wake, report
progress in one line: phase (index/retrieve/answer), questions answered so far
(count lines of `runs/<id>/raw/answers.jsonl`), rough ETA. The completion
notification, not the timer, is the real signal; the timer is for the owner's
visibility. If a run fails, show the tail of its worker log and ask the owner
before retrying.

## Phase 4 — Judge (always)

When a run completes (enrichment runs automatically inside the harness):

```bash
uv run python eval_harness/judge/judge.py --run-dir eval_harness/runs/<id>
```

One full-context judge instance grades every answer against the golden set and
the source files themselves, per `eval_harness/judge/rubric.md`, producing
`judge_verdicts.json` + `JUDGE-REPORT.md`. Verify the wrapper reported VALID.

## Phase 5 — Report agents (after all arms are judged)

Spawn exactly these, in parallel, each reading the run folders (and raw/ logs
locally) for every arm:

1. **Answers report** — why answers failed or succeeded, per failure cluster,
   with qa_id examples; abstention behavior; typed-vs-full comparison.
2. **Retrieval report** — hit@k/recall/MRR across arms, where ranking went
   wrong and why (read the retrieve JSONLs), gate behavior, phrasing gap.
3. **Indexing report** — quality of what indexing produced: read the scratch
   summaries/manifest in `raw/appdata`, spot-check against source files, note
   per-file failures, timing, and anything that would poison downstream
   answers.

Each writes `eval_harness/runs/<run_id>/REPORT-{answers,retrieval,indexing}.md`
(multi-arm comparisons go in the newest run's folder). Reports must explain
WHY, not just tabulate — every claim tied to qa_ids or files.

## Phase 6 — Supervisor synthesis

You (not an agent) read all three reports + the judge reports and write
`eval_harness/runs/<run_id>/SUPERVISOR-REPORT.md`: the handful of findings that
matter, ranked; disagreements between reports resolved or surfaced; and a
**suggestions** section — you may read `src/` to ground suggestions in code,
and you may propose changes there, but you never edit `src/`. Commit
everything, then give the owner the one-paragraph version in chat.
