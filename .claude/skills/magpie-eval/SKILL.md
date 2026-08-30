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
   For a NEW corpus, register it first (creates the manifest + per-machine
   pointer the runner requires):

       uv run python eval_harness/scripts/register_corpus.py --name <name> \
           [--corpus-dir /path/to/files]

   Without `--corpus-dir` it expects files in
   `eval_harness/datasets/<name>/corpus/` (gitignored). Duplicate basenames
   are refused - the harness anchors gold matching on basenames.
2. **Golden set** — one of: *reuse* a committed golden if the dataset has
   one; *adapt* an existing annotation source into our schema; *generate
   fresh* by reading the files (Phase 2). If the dataset directory has no
   `golden.json`, say so and offer only adapt/generate.
3. **Config — exactly ONE per skill run.** A skill run drives Magpie end to
   end once, under one fixed configuration: model_config, top_k, rewrite,
   temperature, anything else in `configs/baseline.json`. Offer baseline as
   the default. Comparing configurations = separate skill runs; never launch
   multiple arms in one.

   **Always ask explicitly — rerank and solo gate** (never silently inherit
   these two from a config file):
   - **rerank** — on/off. Off kills the cross-encoder stage
     (`MAGPIE_RERANK=0`); results come back in fusion order (for visual
     corpora that is ColQwen's own ranking). Warn when the answer is off:
     it ALSO structurally disables the solo gate (the gate's margin is on
     cross-encoder score scale), so the run is a rerank+gate change, and
     `solo_gate_structurally_off` will be stamped in run.json.
   - **solo gate** — margin value (`solo_margin`; 0 disables, production
     default 2.0). If rerank is off, tell the owner the gate cannot fire
     regardless and recommend pinning 0 so the config says what the run does.

   **Duplicate guard**: before launching, compare the chosen config against
   every prior `eval_harness/runs/*/run.json` on the comparability TRIPLE —
   resolved-params hash, backend git SHA, and `golden_sha`. All three equal
   on a COMPLETE run → tell the owner it is an exact re-run of <run_id> and
   ask whether to proceed. Any one differing → announce which layer changed
   (config / code / questions) and continue as a legitimate comparison.

The judge is NOT a question, it always runs — but note to the owner when the
dataset is personal: the judge reads corpus files in full, so their contents
go to the API (standing approval exists; still say it out loud for personal
corpora).

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
Regenerating a golden set changes `golden_sha`: tell the owner that runs
before and after are no longer comparable question-for-question.

## Phase 3 — Run (one run, one config)

Launch the single run in the background, wrapped so the Mac cannot sleep:

```bash
caffeinate -dims uv run python eval_harness/harness/run.py \
    --config <config> > /tmp/eval-run.log 2>&1
```

Indexes cache automatically (`eval_harness/indexes/`, keyed by dataset +
index-side params): the runner prints store HIT (mounts in seconds) or MISS
(builds, then publishes). Include that in your first progress line.

Schedule a wake every **3 minutes** (ScheduleWakeup). At each wake, report
progress in one line: phase (index/retrieve/answer), questions answered so far
(count lines of `runs/<id>/raw/answers.jsonl`), rough ETA. The completion
notification, not the timer, is the real signal; the timer is for the owner's
visibility. If a run fails, show the tail of its worker log and ask the owner
before retrying.

When a run completes, VERIFY before judging — a recorded config is a claim,
not a fact, and this project has twice shipped runs whose recorded config was
not in force. Check in `run.json`: `status: "complete"`; both `isolation.*`
values true; and `env_snapshot` values match the requested config on every
swept axis (temperature, solo margin, ctx, provider). Any mismatch: stop and
show the owner.

## Phase 4 — Judge (always)

After verification (enrichment runs automatically inside the harness):

```bash
uv run python eval_harness/judge/judge.py --run-dir eval_harness/runs/<id>
```

One full-context judge instance grades every answer against the golden set and
the source files themselves, per `eval_harness/judge/rubric.md`, producing
`judge_verdicts.json` + `JUDGE-REPORT.md`. Verify the wrapper reported VALID.

## Phase 5 — Report agents (after the run is judged)

Spawn exactly these, in parallel, each reading this run's folder (and its
raw/ logs). Where a prior run with comparable provenance exists, they may
cite it for contrast, but this run is the subject:

1. **Answers report** — why answers failed or succeeded, per failure cluster,
   with qa_id examples; abstention behavior; typed-vs-full comparison.
2. **Retrieval report** — hit@k/recall/MRR, where ranking went wrong and
   why (read the retrieve JSONL), gate behavior, phrasing gap.
3. **Indexing report** — quality of what indexing produced: read the scratch
   summaries/manifest in `raw/appdata`, spot-check against source files, note
   per-file failures, timing, and anything that would poison downstream
   answers.

Each writes `eval_harness/runs/<run_id>/REPORT-{answers,retrieval,indexing}.md`. Reports must explain
WHY, not just tabulate — every claim tied to qa_ids or files.

## Phase 6 — Supervisor synthesis

You (not an agent) read all three reports + the judge reports and write
`eval_harness/runs/<run_id>/SUPERVISOR-REPORT.md`: the handful of findings that
matter, ranked; disagreements between reports resolved or surfaced; and a
**suggestions** section — you may read `src/` to ground suggestions in code,
and you may propose changes there, but you never edit `src/`. Commit
everything, then give the owner the one-paragraph version in chat.
