# Magpie Q&A Benchmarks

This folder records eval runs against the student-notes corpus under
different document representations. The questions and `expert_ground_truth`
are identical across runs — only the source-document quality varies.

The point of these benchmarks is to isolate the contribution of vision-OCR
quality vs. retrieval/LLM quality. Same questions, same backend (Gemma 4
E4B + mmproj-BF16 via llama-server), only the corpus changes.

## Setup common to all runs

- LLM backend: `LLM_PROVIDER=local` (Gemma 4 E4B + mmproj-BF16, llama-server `b9049`)
- Default profile: `gemma-4-e4b-vision` (so text + image queries share one subprocess)
- Pipeline: `python -m src.pipeline "<q>" --rewrite --json` semantics
  - rewrite: enabled (Kimi-style query expansion)
  - top_k: 5 (auto-bumps to 8 for `LIST_ALL` query class)
- Eval question file: `/Users/mriddy/Desktop/Magpie testing/eval_student_notes.json` (25 questions)
- Each entry in the answer files: `id`, `question`, `expert_ground_truth`,
  `magpie_answer`, `magpie_sources_used`, `magpie_retrieved`,
  `latency_seconds`, `correctness`, `correctness_notes`.

## Runs

### run1_handwritten_messy

Corpus: `student notes_handwritten/` — actually-handwritten PDFs (penmanship,
scribbles, occasional cut-off lines, misspelled words).

Result: 2 correct, 5 partially_correct, 18 incorrect (8% / 28% partial-or-better).

The vision pipeline struggled to recover specific facts (dates, percentages,
proper nouns) from the messy handwriting. Many questions failed at retrieval
because the T3 summary at ingest time also missed the key terms.

### run2_handwritten_font

Corpus: `student notes_handwritten_font/` — typed PDFs rendered in a
handwriting-style font. Same content semantically as `run1`, but legibility
is dramatically higher: full sentences, clean punctuation, numerals
unambiguous, no scribbles or cut-offs.

This run isolates: how much of run1's failure was the OCR/handwriting hurdle
specifically, vs. fundamental retrieval/LLM limits?

If run2 substantially outperforms run1, the bottleneck for handwritten input
is the vision-OCR step (and we'd want better mmproj or pre-OCR).
If run2 is similar to run1, the bottleneck is retrieval or LLM reasoning
(and improving handwriting won't help — we need pipeline work).
