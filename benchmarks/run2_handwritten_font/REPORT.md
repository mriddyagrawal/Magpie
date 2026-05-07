# Run 2 — Handwritten-font (clean typed) PDFs

**Date:** 2026-05-07
**Corpus:** `~/Desktop/Magpie testing/student notes_handwritten_font/` (18 typed PDFs in a handwriting-style font, semantically same content as run1)
**Eval file:** `~/Desktop/Magpie testing/eval_student_notes.json` (same 25 questions as run1)
**Backend:** identical to run1 (Gemma 4 E4B + mmproj-BF16, vision profile as singleton)
**Pipeline:** `ask_sync(question, top_k=5, rewrite=True)`

## Result

| Verdict | Count | % | Δ vs run1 |
|---|---:|---:|---:|
| correct | 8 | 32% | **+6** |
| partially_correct | 3 | 12% | -2 |
| incorrect | 14 | 56% | -4 |
| **partial-or-better** | **11** | **44%** | **+4** |

Average per-question latency: **40.4s** (min 25.4s, max 69.6s) — ~10% faster than run1.
Average answer length: 192 chars.
Total wall-clock to run 25: **14.8 min**.

## Wins (newly correct vs run1)

| q | Question | run1 | run2 |
|---|---|---|---|
| q01 | When is the CS 301 midterm? | "do not specify" ❌ | "Oct 21st (Tuesday)" ✓ |
| q03 | Grading weights for CS 301? | "weights changed" (no numbers) ◐ | exact 25/20/40/15 ✓ |
| q08 | Psych Exam 1 essay question? | yes (garbled details) ◐ | "Yes, with retrospective citation" ✓ |
| q10 | Psych paper length? | "10 pages" ❌ | "6-8 pages, not 8-10" ✓ |
| q11 | Psych Exam 2 topics? | wrongly included visual imagery ❌ | correct scope (no visual imagery) ✓ |
| q16 | Median midterm score? | "73" (numeral OCR error) ❌ | "75/90 (83%)" ✓ |
| q24 | Visual imagery on Exam 2? | "scope is unclear" ◐ | "explicitly NO" ✓ |

These are precisely the questions where the answer is in a specific lecture/study-group note, retrieval surfaced that lecture, and the lecture's content needed to be read carefully. **In each case, the cleaner PDF made facts that were borderline in run1 unambiguous in run2.**

## Regressions (worse than run1)

| q | Question | run1 | run2 |
|---|---|---|---|
| q21 | Prof Chen office hours? | "Wednesdays 1-3pm" ✓ | "Wednesdays 10am-12pm in 308" ❌ |
| q22 | Oct 14 schedule? | midterm pushed + clustering ✓ | "scheduled for Oct 14" (only stale) ❌ |

Two clean regressions. q21 is a hallucination — model wrote 10am-12pm (the TA's hours) but assigned them to Prof Chen. q22 returned an empty source list (`magpie_retrieved` was 0 hits) so the model fell back to the original syllabus reading without the lecture08 update. Both are bad — but they're not OCR-related.

## Where Magpie still fails (same as run1)

The 14 still-incorrect cases break down into the same buckets as run1:

### 1. Conflict resolution where the updating lecture wasn't retrieved (3 cases)
- q02 (open vs closed-book): lecture06 missing from top-5
- q04 (HW1 due): lecture03 missing
- q25 (what to bring): lecture06 missing

These are *exactly the same retrieval failures as run1*. Cleaner PDFs didn't help because retrieval still doesn't surface the right files.

### 2. Pure retrieval misses (6 cases)
Same files, same misses:
- q13 (CS guest lecture) → lecture11 missing
- q15 (readings before midterm) → didn't extract from syllabus
- q17 (study strategies) → retrieved edu.csv (irrelevant)
- q19 (Psych extra credit) → lecture07_oct08 missing
- q20 (CS↔Psych connection) → weekly_planning_oct19 missing
- q23 (Dr. Rahm previous job) → lecture01 missing

Six of run1's eight retrieval-failures repeated identically. The retrieval system's recall problems are independent of OCR quality.

### 3. Wrong-question / hallucination (3 cases)
- q06 (TA office hours): same confusion as run1
- q09 (paper proposal due): said Dec 3 (the FINAL paper due date), confused with proposal
- q14 (project teammates): added Alex to the team (study group member, not project teammate)
- q18 (HW3 due): answered with HW1 info — model misread the question

## Diagnostic notes

The clean-PDF run shows that **the OCR step is a real ceiling for the messy-handwritten run**: ~6 questions have answers that depend on extracting specific facts (dates, percentages, names, counts) from PDF content, and those facts went from unrecoverable in run1 to perfectly extracted in run2.

But the clean-PDF run **does not improve on retrieval-bound failures**: when the file with the answer doesn't make top-5, the answer is wrong regardless of how legibly the file is written. The eight retrieval misses in run1 are essentially the same eight in run2.

This isolates the bottlenecks:
- **OCR quality** → fixes ~6 of the 18 run1 failures (35% of failures recoverable here)
- **Retrieval recall** → blocks at least 8 questions; needs work upstream of OCR
- **JSON schema brittleness** (model misreading questions, hallucinating answers): ~3 questions, mostly in run2's regressions

Cleaner PDFs are a real improvement but they're not the dominant lever. Magpie's next-biggest gain is in retrieval, not vision quality.
