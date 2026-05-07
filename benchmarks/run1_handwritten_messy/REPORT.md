# Run 1 — Handwritten (messy) PDFs

**Date:** 2026-05-07
**Corpus:** `~/Desktop/Magpie testing/student notes_handwritten/` (20 actually-handwritten PDFs: 11 cs301 + 8 psych250 + 1 weekly_planning)
**Eval file:** `~/Desktop/Magpie testing/eval_student_notes.json` (25 questions)
**Backend:** `LLM_PROVIDER=local`, Gemma 4 E4B + mmproj-BF16, llama-server `b9049`, vision profile as singleton default
**Pipeline:** `ask_sync(question, top_k=5, rewrite=True)`

## Result

| Verdict | Count | % |
|---|---:|---:|
| correct | 2 | 8% |
| partially_correct | 5 | 20% |
| incorrect | 18 | 72% |
| **partial-or-better** | **7** | **28%** |

Average per-question latency: **44.7s** (min 26.7s, max 75.3s).
Average answer length: 262 chars.
Total wall-clock to run 25: **~18.6 min**.

## What Magpie got right

- **q12 (Psych 250 guest lecture)**: identified Dr. Kirchhoff + Oct 22 + false memories. Missed the Stanford affiliation but got the core facts.
- **q22 (Oct 14 schedule change)**: correctly described the midterm-pushed → clustering-moved-up causal chain.

## Failure modes

### 1. Conflict resolution (5 of 25)
The eval was specifically designed to test this — many questions have an updated answer in a lecture that overrides the syllabus default. Magpie almost universally went with the syllabus.

| q | Question | Stale source | Updated source | Magpie picked |
|---|---|---|---|---|
| q01 | Midterm date | syllabus says Oct 14 | lecture06 says Oct 21 | "do not specify" |
| q02 | Open-book? | syllabus says closed | lecture06 says open-note | closed-book ❌ |
| q04 | HW1 due | syllabus says Sep 9 | lecture03 extends to Sep 12 | "vague — week after Aug 26" ❌ |
| q09 | Paper proposal due | syllabus says Oct 8 | lecture05 extends to Oct 15 | Oct 8 ❌ |
| q10 | Paper length | syllabus says 8-10 pages | lecture05 reduces to 6-8 | 10 pages ❌ |
| q25 | What to bring? | syllabus says closed-book + cheat sheet | lecture06 makes it open-note | closed-book ❌ |

In every case where Magpie failed, **the updating lecture wasn't in the top-5 retrieval**. The model behaved correctly given its retrieved context — it just never saw the override.

### 2. Retrieval recall (~8 of 25)
The file with the answer simply didn't make top-5. Examples:

| q | Answer location | Why it didn't surface |
|---|---|---|
| q13 | lecture11 has Dr. Jaya Patel | likely embedding distance — the lecture's title is "Reinforcement learning intro", not "guest" |
| q14 | weekly_planning_oct19 has the project + teammates | embedding miss on "final project" + "teammates" query |
| q15 | syllabus has the readings column | retrieved syllabus but model didn't extract chapters |
| q17 | study_group_oct12/study_group_nov02 have study habits | retrieved edu.csv / hb.csv (irrelevant) instead |
| q18 | lecture08 has HW3 extension | embedding miss on "HW3 due" |
| q19 | lecture07_oct08 has the extra credit announcement | retrieved syllabus only |
| q20 | weekly_planning_oct19 has the connection reflection | retrieved syllabi, missed the planning note |
| q23 | lecture01 has "DeepMind" | embedding miss — query "previous job" doesn't match the casual mention |

### 3. Numeric / OCR ambiguity (1 of 25)
- q16 (median midterm score): GT 75/90, Magpie said 73. The handwritten "75" is genuinely ambiguous in the lecture09 image.

### 4. Wrong-question answering (1 of 25)
- q06 (TA office hours): Magpie returned Dr. Rahm's *instructor* office hours (Tuesdays 2-4pm, Thursdays 3-4pm) instead of TA Marcus's hours (Mondays 1-3pm, Fridays 10am-12pm in Uris 105). Both are in the syllabus header, model picked wrong row.

## Diagnostic notes

The dominant failure mode here is **upstream of the LLM**: the retrieval system isn't surfacing the right files for these student-notes queries. When the right context is in the prompt, Magpie extracts it correctly (q12, q22); when retrieval misses, the model has nothing to work with.

Whether the OCR quality contributes to retrieval failures vs. extraction failures was the open question this run couldn't answer alone — needs the run2 comparison.
