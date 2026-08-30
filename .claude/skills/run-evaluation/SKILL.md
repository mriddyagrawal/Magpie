---
name: run-evaluation
description: Run a Magpie evaluation against a corpus folder end-to-end — generate the questions JSON (LLM-as-judge), index the corpus and run the evaluation script, then write per-question correctness verdicts and a REPORT.md. The full process the README in Evaluations/ documents.
use_when: User asks to "evaluate Magpie on <folder>", "run an eval against <corpus>", "benchmark Magpie on <X>", "create a new evaluation for <X>", or otherwise wants the three-step Evaluations/ workflow executed against a particular folder. Also use when the user hands over an existing eval_<dataset>.json and wants Steps 2 + 3 done.
user-invocable: true
---

# Run a Magpie evaluation

This skill executes the three-step workflow defined in
[`Evaluations/README.md`](../../../Evaluations/README.md) against a
specific corpus. The README is the source of truth for schema, taxonomy,
and report template — re-read it before each step rather than going from
memory. This skill exists to coordinate the steps, gather the inputs,
and call the right tools in the right order.

## Inputs to confirm before starting

Ask the user (or read from their request) and confirm before doing any
work:

1. **`corpus_path`** — absolute path to the folder being evaluated. If
   they gave a relative path or just a name, expand it.
2. **`dataset`** — short snake_case identifier. If not given, suggest
   one derived from the folder name (`~/Documents/Course Information/`
   → `course_information`).
3. **`provider`** — which LLM backend Magpie should use to answer the
   questions in Step 2: `local` (Gemma 4 via llama-server, no API
   cost), `moonshot` (Kimi cloud), or `openrouter`. If the user wants
   to compare local vs cloud, run Step 2 twice with different
   `--answers` filenames (e.g. `eval_answer_<dataset>__local.json` and
   `eval_answer_<dataset>__moonshot.json`) and produce one REPORT per
   run, or a single combined REPORT contrasting both.
4. **Which steps to run** — Step 1 (questions), Step 2 (answers), Step 3
   (report), or all three. Default is all three; if the user already
   has a questions or answers file, skip ahead.

If a `Evaluations/<dataset>/` directory already exists, surface the
existing files and confirm whether to overwrite, resume, or pick a new
dataset name.

## Step 1 — generate the questions (LLM)

Read [`Evaluations/README.md`](../../../Evaluations/README.md)
"Step 1 — Create the questions" for the schema, taxonomy, and
acceptance criteria. Then:

1. List every file under `corpus_path` (depth-first or `ls -R`-style).
   For large corpora (>200 files) sample at least 30 files spanning
   subdirectories and content types.
2. Read enough content from those files to author *grounded* ground
   truths. Do not invent answers; if you cannot verify a claim from
   the file, do not write a question about it.
3. Author exactly **25 questions** with the difficulty distribution
   targeted in the README (~10 easy, ~8 medium, ~5 hard, ~2 very_hard).
   Cover at least: one aggregation/counting question, one
   cross-document synthesis, one negative-result / "info absent" probe,
   one data-quality probe, one comparative question.
4. Use the canonical schema from the README. Fields to populate per
   entry: `id` (q01..q25), `question`, `ground_truth`, `reasoning_type`
   (one or more taxonomy tags), `key_files` (relative to `corpus_path`),
   `notes` (why this question matters / what failure mode it probes),
   `difficulty`.
5. Write the array to
   `Evaluations/<dataset>/eval_<dataset>.json`.
6. Verify by running `python -c "import json; print(len(json.load(open('Evaluations/<dataset>/eval_<dataset>.json'))))"`
   — must print 25. Spot-check 3 entries against the source files.

## Step 2 — run the evaluator

Per the README "Step 2 — Run the evaluation":

1. Tell the user to ensure the corpus folder is included under
   `include_paths` in
   `~/Library/Application Support/Magpie/indexing_rules.json` (or
   the platform equivalent). If they confirm it isn't, offer to
   read and propose an edit to that file. Do not silently edit
   indexing rules — the user controls what gets indexed.
2. From the repo root (this repo, `NotAnotherSpotlight`), run:
   ```bash
   just sync
   ```
   This may take several minutes on a fresh corpus. Stream the output
   so the user sees progress; do not background it without saying so.
   Indexing always runs locally regardless of the answer-time backend.
3. Run the evaluator with the `provider` chosen up front. The flag
   sets `LLM_PROVIDER` for this run and is recorded on every answer.
   For cloud providers, verify the matching `*_API_KEY` is set in
   `.env` *before* starting — running 25 questions against an
   unconfigured backend wastes wall-clock time.
   ```bash
   # local
   LLAMA_SERVER_STARTUP_TIMEOUT_S=180 \
     uv run python Evaluations/run_eval.py \
       --provider local \
       --questions Evaluations/<dataset>/eval_<dataset>.json \
       --answers   Evaluations/<dataset>/eval_answer_<dataset>.json

   # cloud
   uv run python Evaluations/run_eval.py \
     --provider {moonshot|openrouter} \
     --questions Evaluations/<dataset>/eval_<dataset>.json \
     --answers   Evaluations/<dataset>/eval_answer_<dataset>__{provider}.json
   ```
   The script is resume-safe; if it crashes, just rerun.
4. Report the headline numbers (questions answered, errors, total
   wall-clock time, provider used) before moving on.

## Step 3 — verdicts + REPORT.md (LLM)

Per the README "Step 3 — Create the report":

1. Read `Evaluations/<dataset>/eval_<dataset>.json` (for `notes`,
   `reasoning_type`, `difficulty`) and the answers file produced in
   Step 2.
2. For every entry in the answers file, add `correctness` (one of
   `correct` / `partially_correct` / `incorrect` / `unable_to_evaluate`)
   and a 1-2 sentence `correctness_notes`. Save the answers file in
   place. Use the verdict definitions in the README — do not invent new
   verdict labels.
3. Write `Evaluations/<dataset>/REPORT.md` using the template in the
   README. The existing reports under
   `Evaluations/{course_information,furman_directory,student_notes}/`
   are good real examples — match their tone and depth, not just the
   structure.
4. The report must include: headline numbers table, failure-mode
   breakdown, per-question patterns (cluster similar verdicts; call out
   interesting outliers), 2-4 paragraphs of synthesis, methodology
   caveats. A pure verdict dump is not a report.

## Step 4 — update the pipeline map (only when the result ships)

[`docs/PIPELINE.md`](../../../docs/PIPELINE.md) is the living map of
the query and index pipeline. It must move in lockstep with the code,
and the trigger is a **positive eval**: the arm's strict score meets
its pre-registered gate, or beats the baseline arm on the same dataset
with the same criteria (`Evaluations/RUNLOG.jsonl` records both), and
the change is being kept on by default.

When that is true for the change just evaluated:

1. Redraw the affected Mermaid figure if a stage was added, removed,
   moved, or changed its default (a dashed node is opt-in; a solid one
   is on).
2. Update that stage's row in the stage table and, if it has a knob,
   the defaults table.
3. Append one entry to the **Change log** at the bottom: date, what
   changed, dataset, score before → after (strict N/M), the RUNLOG
   `note` of the winning arm, and the commit once it exists.

When the arm **misses** its gate and the change stays off, still add a
one-line "tried, did not ship" entry with the number — that is what
stops the same experiment being re-run blindly next month. Do not
touch the figures for a change that did not ship.

## Reporting back

When all requested steps are done, report:

- The dataset name and where each file landed.
- Headline numbers (X/25 strict correct, Y/25 partial+, avg latency).
- The single most interesting failure pattern surfaced.
- Any caveats the user should know (skipped step, errors during run,
  ambiguous ground truths, etc.).

Do not commit or push the new `Evaluations/<dataset>/` files unless the
user explicitly asks — eval data is review-worthy and the user may want
to spot-check before it lands on a remote.
