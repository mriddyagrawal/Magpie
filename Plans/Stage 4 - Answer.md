# Stage 4 — Answer

## Goal

Given a natural-language **question** and a list of **file paths** (the top-k output from stage 3 / Qdrant, typically k = 5), read those files, send them together with the question to Kimi k2.5, and return a structured `Answer` object containing:

1. The answer itself (natural language).
2. The subset of input paths the model actually relied on.

Stage 4 is the last step in the pipeline before the user sees an answer.

## Non-goals (owned by other stages or Future Plans)

- Retrieval from Qdrant → that's stage 3 (friend's work). Stage 4 **trusts** the list of paths it receives.
- Re-ranking the retrieved files — stage 3's ordering is respected.
- The agentic `fetch_next_documents` loop (top-k = 5 → model requests more) — that's in [Future Plans.md](Future%20Plans.md). Stage 4 is strictly one-shot.
- Query rewriting / HyDE — stage 3's concern.
- Summarization — stage 1.

## Public interface

The whole stage is one function — easy for stage 3 to call.

```python
async def answer_question(
    agent: Agent[None, Answer],
    question: str,
    file_paths: Sequence[str | Path],
) -> Answer: ...
```

Callers build the agent once via `build_answer_agent()` and reuse it across questions (avoids redundant client construction). For convenience there's also a sync wrapper `answer_question_sync(...)` used by the CLI and by simple scripts.

## Output schema

```python
class Answer(BaseModel):
    answer: str = Field(
        description="Natural-language answer to the question, grounded strictly in the provided files."
    )
    sources_used: list[str] = Field(
        description="Subset of the input file paths the answer actually depends on. Verbatim, no paraphrasing."
    )
```

Both fields required. `sources_used` is a subset of the input — we validate that post-hoc and drop any path the model hallucinated.

## How it works, end to end

1. **Resolve + validate paths.** Each input path is resolved relative to the repo root. Missing / unsupported files are logged (one warning line per file) and skipped. If *every* path is missing, raise `SummarizeError` (reusing the stage-1 error class) with a clear message — stage 3 gave us nothing usable.
2. **Build content blocks per file.** For each valid path, call the shared `build_content_blocks(path, max_chars=ANSWER_MAX_CHARS_PER_FILE, max_pdf_pages=ANSWER_MAX_PDF_PAGES)` — same dispatch table as stage 1 (text extract for PDF/docx/xlsx/md/txt/code; vision fallback for scanned PDFs; direct image blocks for PNG/JPG/etc.).
3. **Assemble one chat message.** Single list containing:
   ```
   [
     "Question: <user question>\n\nAnswer the question strictly using the files below. "
     "Cite the exact file paths you rely on in `sources_used`.",
     "--- File 1: <path-1> ---",
     ...content blocks for file 1...,
     "--- File 2: <path-2> ---",
     ...content blocks for file 2...,
     ...
   ]
   ```
   Paths are **repo-relative** (e.g. `Test Content/Lab 3 - Tokenizer.pdf`) so the model can reproduce them verbatim in `sources_used`.
4. **`agent.run(message)`** — PydanticAI forces the output into the `Answer` schema via `NativeOutput(Answer)` (same trick as stage 1, required to coexist with Kimi's thinking mode).
5. **Validate `sources_used`.** Drop any path that isn't in the original input (defensive — the model shouldn't invent paths, but if it does, we don't propagate the hallucination). If the filter leaves it empty, keep the answer but flag in a warning.
6. **Return** the `Answer` object.

## System prompt (gist)

> "You are a file-grounded question-answering assistant. Given a question and a set of files, produce an `Answer`:
> - `answer`: a direct, factual response, grounded only in the provided files. If the files do not contain the information, say so explicitly — do not invent.
> - `sources_used`: the exact file paths (copied verbatim from the '--- File N: <path> ---' headers) that your answer actually depends on. Do not include files you consulted but did not actually use."

## Refactor required before implementing

The content-dispatch logic in `src/summarize.py` (images → `BinaryContent`, PDFs → pypdf + vision fallback, docx / xlsx / text) is reused almost verbatim by stage 4. Extract it into a shared module **before** writing `answer.py`:

- New file: `src/content.py`
  - `build_content_blocks(path: Path, *, max_chars: int, max_pdf_pages: int) -> list`
  - Moves `extract_pdf_text`, `render_pdf_pages_as_png`, `extract_docx_text`, `extract_xlsx_text`, the extension-set constants (`IMAGE_EXTS`, `CODE_EXTS`, …), `SUPPORTED_EXTS`, and `SummarizeError` here.
  - `build_user_message` in `summarize.py` becomes a thin wrapper that adds the stage-1 filename hint + "Summarize this file" framing on top of `build_content_blocks`.

- `build_agent()` becomes parameterized:
  - `build_openai_model() -> OpenAIChatModel` — the shared Moonshot client wiring.
  - `summarize.py` and `answer.py` each compose their own `Agent(model, output_type=..., system_prompt=...)` on top.

This refactor is small (< 150 lines moved) and keeps both stages in lock-step on file handling forever.

## Context-size strategy

Kimi k2.5's context is ~128k tokens. With k = 5 files and the stage-1 cap of 120k **chars** per file, we could blow that out. So for stage 4 we use tighter caps:

| Constant | Stage 1 | Stage 4 (proposed) |
|---|---|---|
| `MAX_TEXT_CHARS` | 120_000 | **25_000** per file (≈ 6k tokens × 5 = 30k) |
| `PDF_VISION_MAX_PAGES` | 20 | **5** per file |

These caps leave headroom for the system prompt, the question, the framing boilerplate, and the response. If we ever hit truncation in practice we tune these two numbers in one place.

Images pass through unchanged (PNG size doesn't hit the char cap — it hits the token-count via vision encoding, which Kimi charges per image).

## File layout after stage 4

```
NotAnotherSpotlight/
├── src/
│   ├── content.py          (new — shared file-reading / content-block builder)
│   ├── summarize.py        (stage 1, refactored to use content.py)
│   └── answer.py           (new — stage 4)
├── Plans/
│   ├── Stage 1 - Summary.md
│   ├── Stage 4 - Answer.md
│   └── Future Plans.md
└── ...
```

Stages 2 and 3 will add their own files when they land.

## CLI (for standalone dev / testing, pre-stage-3)

```
uv run python3 src/answer.py "your question here" path1 path2 path3 [...]
```

Emits a pretty-printed JSON `Answer` to stdout. Non-zero exit if the question is empty, if no valid files remain after validation, or if the API errors out.

## Testing / eval hook

The [Test Questions/questions.jsonl](../Test%20Questions/questions.jsonl) file already carries ground-truth `source_files` per question. Before stage 3 lands, we can run stage 4 **end-to-end by bypassing retrieval**: feed each question's own `source_files` directly into `answer_question`. That isolates stage 4's answer quality from retrieval quality.

Proposed lightweight eval script (`src/eval_answer.py`, optional, can live behind a script or a Makefile target):

```python
# for each line in questions.jsonl:
#   ans = answer_question_sync(agent, q.question, q.source_files)
#   print(f"[{q.id}] answer: {ans.answer}")
#   print(f"[{q.id}] sources_used: {ans.sources_used}")
#   print(f"[{q.id}] expected: {q.expected_answer}")
```

Scoring (automated) can come later — for now, eyeballing a handful of easy / medium / hard questions will surface the big issues (hallucination, wrong citation, context truncation).

## Acceptance criteria

1. `src/content.py` exists; `src/summarize.py` uses it and still passes its stage-1 acceptance criteria unchanged (re-running on `Test Content/` should hit the existing hash cache — 0 re-runs, 0 errors).
2. `src/answer.py` exposes `build_answer_agent()`, `answer_question(...)`, `answer_question_sync(...)`, and a CLI.
3. `uv run python3 src/answer.py "Who wrote the Letter from Birmingham Jail?" "Test Content/MLK Letter.pdf"` returns an `Answer` with the correct name and `sources_used == ["Test Content/MLK Letter.pdf"]`.
4. Running on `hard-01` (the total-cost question) with all 6 receipt paths returns the correct sum and a `sources_used` that includes all six files.
5. Running on a question with one bad path mixed in (e.g. `"Test Content/does-not-exist.pdf"`) logs a skip warning and still answers from the remaining files.
6. All five file types (image, PDF-text, PDF-scanned, docx, xlsx) work end-to-end in answer mode — verified by picking a question per type from `questions.jsonl`.

## Handoff to stage 3

Stage 3 just needs to call:

```python
ans: Answer = await answer_question(agent, question, retrieved_paths)
```

That's the entire contract. Stage 4 doesn't know or care how `retrieved_paths` was produced.
