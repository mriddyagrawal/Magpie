# Stage 1 — File Summarization

## Goal

Take a single local file (image, PDF, text, code, or markdown) and produce a **structured summary** via the Moonshot Kimi API, using **PydanticAI** to get a typed `FileSummary` object back. This structured summary is the raw material for Stage 2 (vector embedding + DB indexing).

## Non-goals (deferred to later stages)

- Embedding the summary into a vector.
- Writing to a DB (vector, text, path).
- Video / audio understanding.
- Incremental re-summarization / change detection beyond the hash-based skip (we skip if a summary for the exact same bytes already exists, but we don't detect content renames / moves).

## Output schema (`FileSummary`)

Pydantic model returned from the Agent via `output_type=FileSummary`:

| Field | Type | Purpose |
|---|---|---|
| `title` | `str` | Short human-readable title for the file (≤ ~80 chars). |
| `summary` | `str` | 2–5 sentence dense summary. This will be the primary string embedded in Stage 2. |
| `content_type` | `Literal["image", "pdf", "text", "code", "markdown", "other"]` | What kind of content the file is. |
| `keywords` | `list[str]` | 3–10 topical keywords/tags for keyword-style retrieval. |
| `key_entities` | `list[str]` | Named entities (people, orgs, places, products, file paths, function names, IDs). |

All fields required. The Agent's `output_type` forces the LLM to return JSON matching this schema — Pydantic validates.

## Model / provider

- **Provider:** Moonshot (Kimi), OpenAI-compatible at `https://api.moonshot.ai/v1`.
- **Default model:** `kimi-k2.5` (overridable via `MOONSHOT_MODEL` env var).
- **Auth:** `MOONSHOT_API_KEY` env var (loaded via `python-dotenv` from `.env`).
- **Wiring (per official PydanticAI docs):**
  ```python
  from pydantic_ai import Agent
  from pydantic_ai.models.openai import OpenAIChatModel
  from pydantic_ai.providers.openai import OpenAIProvider

  model = OpenAIChatModel(
      "kimi-k2.5",
      provider=OpenAIProvider(
          base_url="https://api.moonshot.ai/v1",
          api_key=os.environ["MOONSHOT_API_KEY"],
      ),
  )
  agent = Agent(model, output_type=FileSummary, system_prompt=SYSTEM_PROMPT)
  ```

## File-type dispatch

The Kimi chat API accepts **text** and **images** (`image_url` content blocks). It does **not** accept PDFs/Office docs directly — they are pre-processed locally to text.

| Extension(s) | Handling | Sent to Agent as |
|---|---|---|
| `.png .jpg .jpeg .webp .gif` | `BinaryContent(data=bytes, media_type="image/<ext>")` | image content block |
| `.pdf` | **Fast path:** `pypdf.PdfReader` → concatenate page text. **Fallback (empty text → scanned/image-only PDF):** Marker → markdown. Truncate to ~120k chars. | plain text prompt |
| `.docx` | `python-docx` → concatenate paragraphs + table cells (tab-separated rows) | plain text prompt |
| `.xlsx .xlsm` | `openpyxl` → for each sheet: `## Sheet: <name>` header + CSV rows (formulas evaluated via `data_only=True`) | plain text prompt |
| `.md .markdown` | Read UTF-8 | plain text prompt |
| `.txt` | Read UTF-8 | plain text prompt |
| `.py .js .ts .tsx .jsx .go .rs .java .c .cpp .h .hpp .cs .rb .swift .kt .sh .sql .json .yaml .yml .toml` | Read UTF-8 | plain text prompt, with a hint that it is source code |
| anything else | Error out (`SummarizeError`). Batch mode continues; single-file mode exits non-zero. | — |

`content_type` is passed into the prompt as a hint so the LLM summarizes appropriately (e.g., summarize code by what it does, not what libraries it imports). Legacy `.doc` and `.xls` are intentionally unsupported.

### PDF vision fallback

For image-only / scanned PDFs (`pypdf` returns empty text), we fall back to **Kimi vision**: pages are rendered to PNG with `pymupdf` at 150 DPI (cap 20 pages) and appended as `BinaryContent(media_type="image/png")` blocks in a single chat message. This reuses the image path we already have, adds no new heavyweight dep, and handles receipts / handwriting / messy layouts well — which is where a vision LLM beats line-OCR.

An OSS alternative (**Marker**) is recorded in [Future Plans.md](Future%20Plans.md) with the reasoning for when to switch.

## System prompt (gist)

> "You are a file-summarization assistant. Given a single file's content, produce a `FileSummary` JSON object: a short `title`, a dense 2–5 sentence `summary`, the `content_type`, 3–10 `keywords`, and `key_entities`. Be specific and factual; do not invent content that is not present."

## CLI

```
# single file
uv run python3 src/summarize.py <path-to-file>

# batch a whole directory (recursive), parallelized
uv run python3 src/summarize.py <path-to-dir> [--concurrency 6] [--force]
```

- Single-file mode prints the `FileSummary` as pretty-printed JSON to stdout and writes the `.md` summary. Non-zero exit on unrecoverable error.
- Batch mode walks the directory, filters to supported extensions, runs summarization concurrently (default 6 in-flight requests, async + semaphore), shows a `tqdm` progress bar, and continues past per-file failures. Prints a `done: X summarized, Y already-cached, Z errors` tally at the end with the list of errors.
- Summaries are written to `Summaries/<sha256-of-file-bytes-first-16-hex>.md`. Each file starts with `Source: <repo-relative-path>` followed by the rendered markdown summary.
- Re-running on the same directory is cheap: files whose hash already has a summary are skipped unless `--force` is passed.

## Project layout after Stage 1

```
NotAnotherSpotlight/
├── .claude/
├── CLAUDE.md
├── .env / .env.example
├── .gitignore
├── .python-version
├── pyproject.toml
├── Plans/
│   ├── Stage 1 - Summary.md
│   └── Future Plans.md
├── src/
│   └── summarize.py
├── Summaries/              (generated, one <hash>.md per file)
└── Test Content/           (input, gitignored)
```

## Dependencies (pyproject.toml)

- `pydantic-ai` — the Agent framework.
- `pydantic` — comes with pydantic-ai but pinned explicitly.
- `pypdf` — fast-path PDF text extraction.
- `pymupdf` — renders scanned-PDF pages to PNG for the Kimi vision fallback.
- `python-docx` — `.docx` text extraction.
- `openpyxl` — `.xlsx` / `.xlsm` extraction.
- `tqdm` — batch-mode progress bar.
- `python-dotenv` — load `.env`.

Managed by `uv`. Python 3.11+.

## Acceptance criteria for Stage 1

1. `uv sync` installs cleanly.
2. With a valid `MOONSHOT_API_KEY` in `.env`, running `uv run python3 src/summarize.py "Test Content/Lab 1 - Doubly-Linked Lists.pdf"` prints a valid `FileSummary` JSON and writes `Summaries/<hash>.md`.
3. Same works for a PNG in `Test Content/` (e.g. an Uber reservation screenshot).
4. Same works for `.md`, `.py`, `.docx`, `.xlsx`.
5. Image-only PDFs (e.g. `Hotel YQuantum Receipt.pdf`, `MLK Letter.pdf`) summarize successfully via the Kimi vision fallback (`pymupdf` → PNG per page → image content blocks).
6. Batch mode on `Test Content/` finishes with `0 errors` and respects `--concurrency 6`.
7. Unsupported file types produce a clear per-file `SummarizeError`, not a stack trace from deep inside a library, and do not abort the batch.

## Hand-off to Stage 2

The `FileSummary` object plus the original file path is exactly what Stage 2 needs: embed (say) `f"{title}\n{summary}\n{', '.join(keywords)}"`, store `(embedding, summary_json, path)` as a row.
