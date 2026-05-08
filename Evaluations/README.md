# Magpie Evaluations

A standard, portable way to evaluate Magpie's question-answer pipeline
against an arbitrary folder of files.

An evaluation has three artifacts that all live together under
`Evaluations/<dataset>/`:

```
Evaluations/<dataset>/
├── eval_<dataset>.json         questions + ground truth (Step 1 output)
├── eval_answer_<dataset>.json  Magpie's answers + retrieval traces (Step 2 output)
└── REPORT.md                   correctness verdicts + failure-mode analysis (Step 3 output)
```

The corpus itself does **not** live in this repo. Magpie indexes
arbitrary folders on disk (e.g. a folder under `~/Desktop/...`); only
the question/answer/report triplet is checked in.

## How to use this README

This document is also a runbook. To evaluate Magpie against a new folder
(say, Rahul wants to evaluate `~/Documents/MyCorpus/`), an LLM coding
assistant (Claude Code, etc.) can be given the corpus path and a dataset
name and execute Steps 1-3 in order. Each step below specifies its
inputs, outputs, and acceptance criteria so the steps can be done
independently or chained.

## Step 1 — Create the questions (LLM-as-judge)

**Inputs:**
- `corpus_path`: absolute path to the folder being evaluated
- `dataset`: snake_case identifier (e.g. `course_information`,
  `furman_directory`, `student_notes`)

**Output:** `Evaluations/<dataset>/eval_<dataset>.json` — a JSON array
of ~25 question entries.

**What the LLM does:**

1. Read broadly across the corpus. Sample multiple files and content
   types so the question set is representative — not just the easy ones.
2. Author 25 questions covering a mix of difficulties and reasoning
   types (see distribution and taxonomy below). Include a few questions
   that probe known data-quality issues (duplicates, missing fields,
   string variants), a few that test honest "I don't know" behaviour,
   and at least one cross-document / aggregation question.
3. For each question, write the ground truth answer **directly from the
   source files** — do not editorialize. Cite the specific file(s) used
   in `key_files`.
4. In `notes`, explain *why this question matters* and what failure mode
   it is meant to probe — this is what the report writer will use to
   understand the eval's intent.
5. Write the array to `Evaluations/<dataset>/eval_<dataset>.json`
   (create the directory if missing).

### Question entry schema

```jsonc
{
  "id": "q01",                      // q01..q25, zero-padded
  "question": "...",                // natural-language question a real user would ask
  "ground_truth": "...",            // the correct answer, grounded in the corpus
  "reasoning_type": ["..."],        // one or more tags from the taxonomy below
  "key_files": ["relative/path/in/corpus.csv"],
  "notes": "Why this question matters / what failure mode it probes",
  "difficulty": "easy" | "medium" | "hard" | "very_hard"
}
```

### Difficulty distribution (rough target for 25 questions)

| Difficulty  | Count |
| ----------- | ----: |
| easy        |    10 |
| medium      |     8 |
| hard        |     5 |
| very_hard   |     2 |

### Reasoning-type taxonomy

Pick one or more per question. Extend the taxonomy if the corpus
demands it; document new tags in the question's `notes`.

| Tag                       | Meaning                                                 |
| ------------------------- | ------------------------------------------------------- |
| `single_doc`              | answer lives in one file                                |
| `cross_doc`               | requires synthesis across files                         |
| `aggregation`             | counts, totals, list-everything-that-matches           |
| `filter`                  | subset of records by a property                         |
| `boolean_logic`           | preserves AND/OR structure (e.g. nested prereqs)        |
| `multi_hop`               | follows a dependency chain                              |
| `field_lookup`            | reverse lookup by an opaque ID                          |
| `topic_search`            | paraphrased subject query                               |
| `subject_matching`        | subjective recommendation                               |
| `comparative`             | A-vs-B contrast                                         |
| `string_normalization`    | inconsistent labels for the same thing                  |
| `data_quality`            | catches a data-entry issue                              |
| `data_absence`            | tests honest refusal when info is missing               |
| `ambiguous_question`      | tests disambiguation                                    |
| `recursive_prereq_chain`  | full prereq-tree planning                               |

### Acceptance for Step 1

- File parses as JSON.
- Exactly 25 entries with unique `id`s.
- Every entry has all schema fields populated.
- A spot-check of 3 entries verifies the ground truth against the corpus.

## Step 2 — Run the evaluation

**Inputs:**
- The corpus folder on disk.
- `Evaluations/<dataset>/eval_<dataset>.json` from Step 1.

**Output:** `Evaluations/<dataset>/eval_answer_<dataset>.json` — for
each question, Magpie's answer plus retrieval trace.

**Choose a backend.** Magpie's pipeline can answer questions using
either a **local** LLM (Gemma 4 served by `llama-server`) or a **cloud**
LLM (Moonshot Kimi or OpenRouter). Pick whichever the user wants tested
— most evals should run both for comparison. The `--provider` flag on
`run_eval.py` (or `LLM_PROVIDER` env var) selects between them. Cloud
modes need their API keys in `.env`; see `.env.example`.

**What you do:**

1. **Point Magpie at the corpus.** Edit
   `~/Library/Application Support/Magpie/indexing_rules.json` and add
   the corpus path under `include_paths`. The index can include other
   files too — having extra unrelated files indexed is fine and is
   actually a more realistic test (Magpie has to find the right files
   among many).
2. **Build the index.** From the repo root:
   ```bash
   just sync
   ```
   This walks every enabled `include_paths` entry and brings the
   manifest, summaries, and Qdrant collections up to date. Wait for it
   to finish — re-running is idempotent. Indexing always runs locally
   regardless of the backend used in step 3.
3. **Run the evaluator.** From the repo root, pick one:

   *Local backend* (Gemma 4 via llama-server — no API cost, slow warm-up):
   ```bash
   LLAMA_SERVER_STARTUP_TIMEOUT_S=180 \
     uv run python Evaluations/run_eval.py \
       --provider local \
       --questions Evaluations/<dataset>/eval_<dataset>.json \
       --answers   Evaluations/<dataset>/eval_answer_<dataset>.json
   ```

   *Cloud backend — Moonshot Kimi* (needs `MOONSHOT_API_KEY` in `.env`):
   ```bash
   uv run python Evaluations/run_eval.py \
     --provider moonshot \
     --questions Evaluations/<dataset>/eval_<dataset>.json \
     --answers   Evaluations/<dataset>/eval_answer_<dataset>.json
   ```

   *Cloud backend — OpenRouter* (needs `OPENROUTER_API_KEY` in `.env`):
   ```bash
   uv run python Evaluations/run_eval.py \
     --provider openrouter \
     --questions Evaluations/<dataset>/eval_<dataset>.json \
     --answers   Evaluations/<dataset>/eval_answer_<dataset>.json
   ```

   The script records `"provider"` on every answer entry so the report
   in Step 3 can attribute results correctly. To compare local vs cloud
   on the same dataset, use distinct `--answers` paths
   (e.g. `eval_answer_<dataset>__local.json`,
   `eval_answer_<dataset>__moonshot.json`).

   The script is **resume-safe**: re-running skips IDs already in the
   answers file. Per-question results are flushed to disk after every
   call, so a crash mid-run loses at most one question's worth of work.

   Optional flags: `--top-k 5` (retrieval depth), `--no-rewrite` (skip
   the query rewrite, ~20s faster per question on local), `--fast`
   (also run the ColPali visual tier — opt-in because of cold-start cost).

### Answer entry schema

```jsonc
{
  "id": "q01",
  "question": "...",
  "ground_truth": "...",                          // copied through from the question file
  "provider": "local" | "moonshot" | "openrouter",// LLM backend that produced this answer
  "magpie_answer": "...",                         // what Magpie returned
  "magpie_sources_used": ["..."],                 // file paths Magpie cited
  "magpie_retrieved": [{"path": "...", "score": 0.016}, ...],
  "latency_seconds": 21.81
  // On error, instead of magpie_*: "error": "<ExceptionType>: <msg>"
}
```

### Acceptance for Step 2

- Answer file parses as JSON.
- Has the same number of entries as the question file (or exactly the
  set of IDs you intended to run).
- No more than ~10% of entries carry an `error` key — if more, something
  is broken in the pipeline or the corpus path, not in Magpie's answers.

## Step 3 — Create the report (LLM-as-judge)

**Inputs:**
- `Evaluations/<dataset>/eval_<dataset>.json`
- `Evaluations/<dataset>/eval_answer_<dataset>.json`

**Outputs:**
- The answers file, **updated in place** with `correctness` +
  `correctness_notes` on every entry.
- `Evaluations/<dataset>/REPORT.md` — the human-readable analysis.

**What the LLM does:**

### Part A — Per-question correctness

For each entry in the answers file, compare `magpie_answer` against
`ground_truth` and add:

```jsonc
{
  ...,
  "correctness": "correct" | "partially_correct" | "incorrect" | "unable_to_evaluate",
  "correctness_notes": "1-2 sentence reasoning for the verdict"
}
```

Verdict definitions:
- **correct** — covers everything the ground truth covers, no
  meaningful contradictions.
- **partially_correct** — gets the main thing right but misses or
  garbles a sub-fact, OR gets a sub-fact right but misses the main
  point.
- **incorrect** — contradicts the ground truth, hallucinates, or fails
  to answer.
- **unable_to_evaluate** — Magpie returned an error, the ground truth
  is itself wrong, or the question is ambiguous.

### Part B — REPORT.md

Use this template. Per-dataset reports under
`Evaluations/{course_information,furman_directory,student_notes}/REPORT.md`
are good real examples to mimic in tone and depth.

```markdown
# <Dataset Name> — eval report

Brief paragraph: what the corpus is, what's special about it, what
this eval is meant to surface.

## Headline numbers

| Metric            |   Value |
| ----------------- | ------: |
| Questions         |      25 |
| Strict correct    | N (n%)  |
| Partial+ correct  | N (n%)  |
| Avg latency       |    Xs   |

## Failure-mode breakdown

| Failure mode                                | Count |
| ------------------------------------------- | ----: |
| Retrieval recall (right file not in top-k)  |     N |
| Aggregation / counting                      |     N |
| Disambiguation among similar records        |     N |
| Conflict resolution                         |     N |
| OCR / handwriting ambiguity                 |     N |
| Wrong-question / hallucination / drift      |     N |

(Add or remove rows to match the dataset's actual failure modes.)

## Per-question patterns

- **q01** — verdict — one-line summary of why it landed there.
- **q02** — ...

(Don't summarize all 25 line-by-line; group similar verdicts into
clusters and call out the interesting outliers individually.)

## What this dataset reveals

2-4 paragraphs of analysis. What is Magpie good at on this corpus?
What is it bad at? Where is the headline number misleading? Which
single fix would move the most numbers?

## Methodology caveats

- Single run per question; temperature non-zero, so re-running may
  shift partial-credit verdicts a bit. For tight comparisons run n=3-5
  and report median.
- Self-evaluation: the same family of LLM authored ground truth and
  scored Magpie's answers. A third-party evaluator would be cleaner.
- Note any dataset-specific caveats (stale `key_files` paths, label
  variants the question set didn't fully cover, etc.).
```

### Acceptance for Step 3

- Every answer entry has `correctness` and `correctness_notes`.
- `REPORT.md` includes headline numbers, failure-mode breakdown, and
  at least one paragraph of synthesis (not just a verdict dump).

## Existing evaluations

| Dataset                                         | Corpus type                       |
| ----------------------------------------------- | --------------------------------- |
| [`course_information/`](course_information/)    | clean CSVs (Furman course catalog)|
| [`furman_directory/`](furman_directory/)        | clean CSV (Furman people)         |
| [`student_notes/`](student_notes/)              | handwritten / typed PDFs          |

`student_notes/` has two sub-runs (`run1_handwritten_messy/`,
`run2_handwritten_font/`) for an OCR-isolation comparison. See
`student_notes/COMPARISON.md`.
