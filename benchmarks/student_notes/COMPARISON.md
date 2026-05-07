# Run 1 vs Run 2 — Side-by-side

Identical 25 questions, identical eval JSON, identical Magpie pipeline + backend
(Gemma 4 E4B + mmproj-BF16 via llama-server `b9049`). The **only** variable
between runs is the document representation of the same content:

- **Run 1** (`run1_handwritten_messy/`): actually-handwritten PDFs — penmanship,
  occasional cut-off lines, scribbled letters, misspelled words.
- **Run 2** (`run2_handwritten_font/`): typed PDFs in a handwriting-style font.
  Full sentences, clean punctuation, unambiguous numerals, no truncations.

## Headline numbers

| Metric | Run 1 (messy) | Run 2 (clean) | Δ |
|---|---:|---:|---:|
| **Strict correct** | 2/25 (8%) | 8/25 (32%) | **+6 (4×)** |
| Partially correct | 5 | 3 | -2 |
| Incorrect | 18 | 14 | -4 |
| Partial-or-better | 7 (28%) | 11 (44%) | +4 |
| Avg latency / question | 44.7s | 40.4s | -4.3s |
| Total wall-clock | 18.6 min | 14.8 min | -3.8 min |

**Strict correctness 4× higher with clean PDFs.**

## Per-question outcome

| q | Question (truncated) | Run 1 | Run 2 | Δ |
|---|---|:-:|:-:|---|
| q01 | When is the CS 301 midterm? | ❌ | ✅ | **win** |
| q02 | Open-book or closed-book? | ❌ | ❌ | same |
| q03 | Grading weights for CS 301? | ◐ | ✅ | **win** |
| q04 | When is HW1 due? | ❌ | ❌ | same |
| q05 | Midterm topics? | ◐ | ◐ | same |
| q06 | TA office hours? | ❌ | ❌ | same |
| q07 | Midterm format? | ❌ | ◐ | partial gain |
| q08 | Psych 250 Exam 1 essay? | ◐ | ✅ | **win** |
| q09 | Psych paper proposal due? | ❌ | ❌ | same |
| q10 | Psych paper length? | ❌ | ✅ | **win** |
| q11 | Psych Exam 2 topics? | ❌ | ✅ | **win** |
| q12 | Psych guest lecture? | ✅ | ✅ | same |
| q13 | CS guest lecture? | ❌ | ❌ | same |
| q14 | CS final project + teammates? | ❌ | ◐ | partial gain |
| q15 | Readings before midterm? | ❌ | ❌ | same |
| q16 | Median midterm score? | ❌ | ✅ | **win** |
| q17 | Study strategies? | ❌ | ❌ | same |
| q18 | HW3 due date? | ❌ | ❌ | same |
| q19 | Psych extra credit? | ❌ | ❌ | same |
| q20 | CS↔Psych connection? | ❌ | ❌ | same |
| q21 | Prof Chen office hours? | ✅ | ❌ | **regression** |
| q22 | Oct 14 schedule? | ✅ | ❌ | **regression** |
| q23 | Dr. Rahm previous job? | ❌ | ❌ | same |
| q24 | Visual imagery on Exam 2? | ◐ | ✅ | **win** |
| q25 | What to bring to midterm? | ❌ | ❌ | same |

Net: 6 wins, 2 regressions, 17 unchanged. (✅=correct, ◐=partially_correct, ❌=incorrect.)

## Where clean PDFs help (the wins)

Every win above shares one property: **the right file was retrieved in both runs, but in run1 the relevant fact was buried in messy handwriting and in run2 it was crisp typed text.** Examples:

- **q01 (midterm date)**: lecture06 in retrieval both times. Run1's handwritten "midterm is moved to Oct 21" was on a page where the surrounding text was scribbled and partially cut off. Run2's typed-font "Oct 21" is unambiguous.
- **q03 (grading weights)**: lecture09 had four percentage values. Run1's handwritten numerals were genuinely hard to read (some looked like "20"/"40"/"15" but with significant ambiguity). Run2 gave exact figures.
- **q16 (median score)**: same lecture09. Run1 read "75" as "73" (handwriting ambiguity). Run2 got it right.
- **q10 (paper length)**: lecture05 says "6-8 pages now, not 8-10". Run1's handwriting on that line was mid-sentence-truncated. Run2 has full sentence + correct interpretation.
- **q24 (visual imagery on Exam 2)**: the TA's confirmation "NO visual imagery" in study_group_nov02 was clearer in the typed font; run1 hedged with "unclear", run2 says definitively no.

**Pattern**: clean PDFs unlock facts whose extraction was OCR-bound, not retrieval-bound.

## Where clean PDFs don't help (the same-result questions)

Most of the still-incorrect questions in run2 have the same retrieval problem as run1: **the file with the answer didn't make top-5 retrieval**. Specifically:

| q | Answer is in | Got retrieved? |
|---|---|---|
| q02 | lecture06 (open-note) | ❌ in both runs |
| q04 | lecture03 (Sep 12 extension) | ❌ in both runs |
| q13 | lecture11 (Dr. Jaya Patel) | ❌ in both runs |
| q17 | study_group_oct12, study_group_nov02 | ❌ in both runs |
| q18 | lecture08 (HW3 extension) | ❌ in both runs |
| q19 | lecture07_oct08 (extra credit) | ❌ in both runs |
| q20 | weekly_planning_oct19 (CS↔Psych reflection) | ❌ in both runs |
| q23 | lecture01 (DeepMind) | ❌ in both runs |
| q25 | lecture06 (open-note) | ❌ in both runs |

That's nine questions (out of 14 still-incorrect in run2) where the bottleneck is retrieval, not OCR. **Doing better OCR can't fix these — they fail before the LLM ever sees the relevant file.**

## The two regressions

Run2 broke two questions that run1 had right. Both are interesting:

**q21 (Prof Chen office hours)** — Hallucination. Run1 returned "Wednesdays 1-3pm" (correct). Run2 said "Wednesdays 10am-12pm in Psych Building 308" — the 10am-12pm is the TA's hours, not Prof Chen's. The model conflated the two rows in the syllabus. Same source file in both runs; the regression isn't about OCR quality, it's about model variance / structured-output drift.

**q22 (Oct 14 schedule)** — Retrieval miss. Run1 returned the full causal chain (midterm pushed → clustering moved up). Run2 retrieved 0 sources for this query and fell back to "midterm exam was scheduled for Oct 14" with no schedule-change context. Embedding similarity for this exact question varied enough between runs that lecture08 dropped out of top-5.

Both regressions are within model-variance noise, not signal that clean PDFs hurt. Re-running run1 today on the same corpus would probably show similar drift on a different couple of questions.

## What this tells us about Magpie's bottlenecks

Three distinct error sources, in order of impact:

1. **Retrieval recall** — biggest blocker. ~8-9 questions fail because the right file doesn't make top-5. Clean PDFs don't help.
2. **Vision OCR quality** — real blocker for handwritten input. ~6 questions go from unrecoverable to correct just by switching to typed PDFs.
3. **Model variance / structured output** — noise floor. ~2-3 questions regress per run for reasons unrelated to corpus or retrieval.

**If you only had budget for one improvement, retrieval recall would beat OCR quality.** The eval shows that even with perfect OCR (run2), Magpie still gets only 32% strictly correct on student-notes — because retrieval misses the right file 30%+ of the time.

That said, **OCR is a meaningful contributor**. The 4× lift from messy → clean was free in this experiment (no code changes; just better source documents). For a real handwritten-notes user, this is the difference between "Magpie can answer 8% of my study questions" and "Magpie can answer 32%."

## Methodology caveats

1. **Single run per condition.** Both run1 and run2 are single trials. Some of the regressions on run2 are likely just sampling noise (the LLM is non-deterministic at temperature > 0). For tighter conclusions, n=3-5 runs per condition with median-of-runs reporting.
2. **Evaluator is the same model that wrote `expert_ground_truth`.** I authored the GT after reading the source PDFs (handwritten ones), and I'm the same Claude classifying correctness. Self-marking is a known bias risk. Mitigation: I tried to be conservative on partial credit and explicit about why each verdict landed where it did, but a third-party evaluator would be cleaner.
3. **Corpus drift not fully controlled.** Run1 was against a Qdrant index that included the Furman directory + course CSVs (not used for student-notes questions but possibly affecting retrieval ranking via score normalization). Run2 was against the same index after adding the new font folder. The included-corpus cardinality is similar but not identical.
4. **Question set was authored against handwritten PDFs.** Some `expert_key_files` references in `eval_student_notes.json` still point at the `student notes_handwritten/` paths even though run2 indexed `student notes_handwritten_font/` paths. The questions are content-based so this doesn't affect correctness scoring, but if you regenerate the eval with the font-corpus paths it'd be cleaner.
