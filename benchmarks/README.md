# Magpie Q&A Benchmarks

This folder records eval runs against three datasets, each with 25
questions and `expert_ground_truth` annotations. The point is to
understand where Magpie's pipeline performs well, where it fails, and
why — broken down by dataset class (CSV row lookup, multi-CSV catalog,
handwritten document) and by failure mode (retrieval recall,
aggregation, OCR, conflict resolution, etc.).

## Layout

```
benchmarks/
├── README.md                                        ← you are here
├── student_notes/
│   ├── COMPARISON.md                                ← head-to-head: messy handwriting vs typed font
│   ├── runner.py                                    ← parametric runner used for both runs
│   ├── run1_handwritten_messy/
│   │   ├── REPORT.md                                ← per-run analysis
│   │   └── eval_answer_student_notes.json           ← 25 entries with magpie_answer + correctness
│   └── run2_handwritten_font/
│       ├── REPORT.md
│       ├── eval_answer_student_notes.json
│       └── run.log                                  ← captured stdout
├── course_information/
│   ├── REPORT.md                                    ← single-run analysis
│   └── eval_answer_course_information.json
└── furman_directory/
    ├── REPORT.md
    └── eval_answer_furman_directory.json
```

## Common setup

All runs share:

- **LLM backend**: `LLM_PROVIDER=local`, Gemma 4 E4B + mmproj-BF16 via llama-server `b9049`
- **Default profile**: `gemma-4-e4b-vision` (one subprocess serves text + vision; no LRU swaps)
- **Pipeline**: `ask_sync(question, top_k=5, rewrite=True)` — query rewrite enabled, retrieval top-5, answer step reads file content blocks (text or rendered page images) plus the T3 summary supplement
- **Eval question files** (live alongside the corpus, NOT in this repo): `~/Desktop/Magpie testing/eval_*.json`. Each entry has `question`, `expert_ground_truth`, `expert_reasoning_type`, `expert_key_files`, `expert_notes`, and `difficulty`.

## Each `eval_answer_*.json` entry

```jsonc
{
  "id": "q01",
  "question": "...",
  "expert_ground_truth": "...",
  "magpie_answer": "...",                         // what Magpie returned
  "magpie_sources_used": ["..."],                 // file paths Magpie cited
  "magpie_retrieved": [{"path": "...", "score": 0.016}, ...],
  "latency_seconds": 26.94,
  "correctness": "correct" | "partially_correct" | "incorrect" | "unable_to_evaluate",
  "correctness_notes": "1-2 sentence reasoning for the verdict"
}
```

## Headline numbers

| Dataset | Questions | Strict correct | Partial+ | Avg latency |
|---|---:|---:|---:|---:|
| **furman_directory** | 25 | 18 (72%) | 20 (80%) | 18.1s |
| **course_information** | 25 | 8 (32%) | 13 (52%) | 26.6s |
| **student_notes** (run1, handwritten messy) | 25 | 2 (8%) | 7 (28%) | 44.7s |
| **student_notes** (run2, typed font) | 25 | 8 (32%) | 11 (44%) | 40.4s |

**Furman Directory** is the strongest result — clean CSV, one row per
person, direct lookups where retrieval almost always lands on the right
row.

**Course Information** is middling — exact lookups work, but
aggregation / counting questions consistently fail (model only counts
retrieved rows, not the full file).

**Student Notes** is the hardest set — handwritten PDFs + cross-document
conflict resolution + retrieval recall problems compound. The clean-PDF
run (run2) demonstrates that ~6 of run1's 18 failures were OCR-bound;
the remaining 12 are retrieval / pipeline issues that wouldn't be fixed
by better OCR alone.

See per-dataset `REPORT.md` files for failure-mode breakdowns + specific
patterns. See `student_notes/COMPARISON.md` for the OCR-isolation
analysis.

## Failure-mode patterns across datasets

The three evals surface different failure modes in different proportions:

| Failure mode | Furman | Course Info | Student Notes |
|---|---:|---:|---:|
| Retrieval recall (right file not in top-5) | 2 | 4 | 8-9 |
| Aggregation / counting | 0 | 4 | 0 |
| Disambiguation among similar rows | 1 | 0 | 0 |
| Conflict resolution (newer source vs syllabus default) | 0 | 0 | 5 |
| OCR / handwriting ambiguity | n/a | n/a | 6 (recoverable in run2) |
| Wrong-question / hallucination / structured-output drift | 1 | 0 | 3 |

**Magpie's biggest pipeline gain across all datasets would come from
retrieval recall improvements** — that single bottleneck explains
roughly half of the incorrect cases on student_notes and is the
dominant blocker for course_information's CSC-prefixed questions.

## Repro

To rerun a student-notes eval against an arbitrary corpus representation
(different folder of PDFs / markdowns / etc.), update the indexing rules
to point at that folder, run `just sync` to populate Qdrant, then:

```bash
LLM_PROVIDER=local LLAMA_SERVER_STARTUP_TIMEOUT_S=180 \
  uv run python benchmarks/student_notes/runner.py \
    --out-dir benchmarks/student_notes/<new_run_dir>
```

The runner is resume-safe: rerunning skips IDs already present in the
output JSON. The correctness verdicts are still a manual LLM-judgment
pass after the answers land — no automation for that yet.

For course_information and furman_directory, no parametric runner is
checked in (only one run each). The data was generated by the
`run_all_evals.py` script that lives alongside the corpus.

## Methodology caveats

1. **Single run per condition.** Each row in the headline table is one
   trial. Some answers will vary across runs at the model's temperature
   (0.7); for tight comparisons run n=3-5 and report median.

2. **Self-evaluation.** I (Claude) authored the `expert_ground_truth`
   AND classified `magpie_answer` correctness. Self-marking is a known
   bias risk. The verdicts try to be conservative on partial credit
   and explicit about reasoning, but a third-party evaluator would be
   cleaner.

3. **`expert_key_files` references in the question files** still
   reference the original `student notes_handwritten/` paths in some
   cases. Run2 indexed `student notes_handwritten_font/` paths instead
   — the questions are content-based so this doesn't affect scoring,
   but the question file's `expert_key_files` could be updated for
   consistency.

4. **Furman Directory's eval `key_files` references** point at
   `people_profiles.json` + `people_urls.json` which don't exist; the
   actual source is `furman_directory.csv`. The `expert_key_files`
   fields in the question file already correct this; the original
   `key_files` was stale from an earlier corpus layout.
