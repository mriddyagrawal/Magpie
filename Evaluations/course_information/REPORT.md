# Course Information eval

**Date:** 2026-05-07
**Corpus:** `~/Desktop/Magpie testing/Course Information/` (78 CSV files: 18 by-GER + 60 by-major)
**Eval file:** `~/Desktop/Magpie testing/eval_course_information.json` (25 questions)
**Backend:** `LLM_PROVIDER=local`, Gemma 4 E4B + mmproj-BF16, llama-server `b9049`, vision profile as singleton default
**Pipeline:** `ask_sync(question, top_k=5, rewrite=True)`

The questions test exact-field lookups, aggregation/counting across rows,
boolean prereq parsing, data-quality probes (duplicates, values buried in
description), and topic-search across course descriptions.

## Result

| Verdict | Count | % |
|---|---:|---:|
| correct | 8 | 32% |
| partially_correct | 5 | 20% |
| incorrect | 12 | 48% |
| **partial-or-better** | **13** | **52%** |

Average per-question latency: **26.6s** (min 15.7s, max 41.1s).
Total wall-clock: ~11 min for the 25 questions.

## What Magpie got right (8 strict-correct)

| q | Question | Why it worked |
|---|---|---|
| q01 | CSC-122 prereqs | Direct row lookup, csv.csv retrieved correctly |
| q02 | CSC-105 credits | Same — clean field extraction |
| q05 | CSC-372 prereqs (boolean) | **Preserved AND/OR structure exactly**: `(CSC-122 AND CSC-272) AND (MTH-120 OR MTH-150)` |
| q13 | NLY major prefix | Negative-result test — correctly answered "no" |
| q15 | CSC-372 credits | Inferred 4 credits from the description tail (the credits column is empty for this row — data-quality test passed) |
| q18 | CSC writing-intensive (WR) | Listed both CSC-475 and CSC-502 — exact match |
| q22 | CSC database course | CSC-341 with prereq CSC-122 — exact |
| q25 | Cryptography courses | Returned CSC-362 + MTH-116 (Introduction to Cryptology) — arguably more relevant than my GT's MTH-320 |

## Partial credit (5)

- **q11** (HB ∩ WC GER courses): correctly answered yes with 3 example courses but undercounted (12 actual)
- **q12** (Who teaches MHC, count): correctly admitted no instructor data; missed the count of 1 MHC course
- **q14** (CSC-475 + prereqs): got the prereqs from the description but missed credits + GER classification
- **q17** (CSC-372 prereq sequence): listed immediate prereqs but didn't trace the chain back to CSC-121
- **q24** (SUS Senior Capstone): identified SUS-474 but missed the second capstone option (SUS-473)

## Failure modes

### 1. Aggregation / counting (4 of 12 incorrect)
Pattern: model only counts what's in the top-5 retrieval rows, not the full file.

| q | Question | GT count | Magpie said |
|---|---|---:|---:|
| q07 | SUS major courses | 27 | "does not state the total" |
| q08 | VP GER course count | 56 | 5 |
| q21 | MXP program courses | 84 | 5 |
| q23 | 0-credit courses across all majors | 28 | 2 |

The CSV files have all the data; retrieval surfaces only 5 rows; the model counts only those 5. Pure aggregation failure — no LLM size will fix this without pipeline changes (e.g., row-count metadata in the index, or an aggregation-mode that reads the full file when the question implies counting).

### 2. Retrieval misses on numeric-id lookup (1 of 12)
- **q03** (coid 67390): the answer (CSC-025) is in csc.csv, but retrieval surfaced 7 unrelated CSVs (ids/phy/ha/ne/spn/hb/ggy). Numeric-id queries don't embed close to the matching row's content embedding.

### 3. CSC-prefixed retrieval bias (3 of 12)
Several CSC-related questions failed because retrieval scored unrelated CSVs at near-tie:

| q | Question | What was retrieved instead |
|---|---|---|
| q04 | MR GER courses | mxp.csv (irrelevant) ranked above mr.csv |
| q06 | CSC courses requiring CSC-122 | only 3 of 10 found (csc.csv was retrieved but model missed rows) |
| q09 | CSC course satisfying UQ | "do not contain" (CSC-271 IS in csc.csv + uq.csv) |
| q10 | CSC-221 vs CSC-241 | claimed CSC-241 not present (it is in csc.csv) |
| q20 | CSC-271 description | "do not contain" (CSC-271 IS in csc.csv) |

### 4. Subject-search misses (3 of 12)
- **q16** (intro AI courses): missed CSC-272/343/372, picked CSC-105 + FYW-1128 (Turing seminar — not directly AI)
- **q19** (duplicate course entries): said no duplicates; GT identifies WGS-220 + THA-241 as duplicates
- (Plus the cryptography one which I scored correct)

## Diagnostic notes

The course-information eval has **two distinct bottlenecks**:

1. **Aggregation/counting** is a fundamental Magpie pipeline limitation, not an LLM size problem. The system retrieves 5 rows; the LLM counts what it sees. To fix: either bake row-count metadata into the index (so questions like "how many SUS courses" can be answered without reading the file), or detect "count / how many" queries and switch to a full-file read tier.

2. **CSC-prefixed retrieval bias**: csv.csv is the most-relevant file for ~10 of these questions, but retrieval often scores other CSVs at the same level (~0.016) so its rows don't always make top-5. This is an embedding-similarity artifact — the courses-by-majors files all have similar CSV structure, so they all look similar in vector space.

When retrieval lands on the right row, the small Gemma 4 E4B handles structured-output extraction well (q01, q02, q05, q15, q18, q22 all clean). The bottleneck isn't the model.
