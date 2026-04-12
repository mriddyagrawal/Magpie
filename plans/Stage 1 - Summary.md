# Stage 1 — File Summarization

## Goal

Take a single local file (image, PDF, text, code, or markdown) and produce a **structured summary** via the Moonshot Kimi API, using **PydanticAI** to get a typed `FileSummary` object back. This structured summary is the raw material for Stage 2 (vector embedding + DB indexing).

## Non-goals (deferred to later stages)

- Embedding the summary into a vector.
- Writing to a DB (vector, text, path).
- Batching / walking directories.
- Video / audio understanding.
- OCR of image-only PDFs beyond what pypdf's text extraction gives us.
- Incremental re-summarization / change detection.

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

The Kimi chat API accepts **text** and **images** (`image_url` content blocks). It does **not** accept PDFs directly — PDFs are pre-processed locally.

| Extension(s) | Handling | Sent to Agent as |
|---|---|---|
| `.png .jpg .jpeg .webp .gif` | `BinaryContent(data=bytes, media_type="image/<ext>")` | image content block |
| `.pdf` | `pypdf.PdfReader` → concatenate page text → truncate to ~120k chars | plain text prompt |
| `.md` | Read UTF-8 | plain text prompt |
| `.txt` | Read UTF-8 | plain text prompt |
| `.py .js .ts .tsx .jsx .go .rs .java .c .cpp .h .hpp .cs .rb .swift .kt .sh .sql .json .yaml .yml .toml` | Read UTF-8 | plain text prompt, with a hint that it is source code |
| anything else | Attempt UTF-8 read; if it fails, error out with a clear message | — |

`content_type` passed into the prompt as a hint so the LLM summarizes appropriately (e.g., summarize code by what it does, not what libraries it imports).

## System prompt (gist)

> "You are a file-summarization assistant. Given a single file's content, produce a `FileSummary` JSON object: a short `title`, a dense 2–5 sentence `summary`, the `content_type`, 3–10 `keywords`, and `key_entities`. Be specific and factual; do not invent content that is not present."

## CLI

```
uv run python summarize.py <path-to-file>
```

Prints the `FileSummary` as pretty-printed JSON to stdout. Non-zero exit on error.

## Project layout after Stage 1

```
NotAnotherSpotlight/
├── .claude/
├── CLAUDE.md
├── .env.example
├── .gitignore
├── .python-version
├── pyproject.toml
├── plans/
│   └── Stage 1 - Summary.md
├── summarize.py
└── Test Content/           (existing)
```

## Dependencies (pyproject.toml)

- `pydantic-ai` — the Agent framework.
- `pydantic` — comes with pydantic-ai but pinned explicitly.
- `pypdf` — PDF text extraction.
- `python-dotenv` — load `.env`.

Managed by `uv`. Python 3.11+.

## Acceptance criteria for Stage 1

1. `uv sync` installs cleanly.
2. With a valid `MOONSHOT_API_KEY` in `.env`, running `uv run python summarize.py "Test Content/Lab 1 - Doubly-Linked Lists.pdf"` prints a valid `FileSummary` JSON.
3. Same works for a PNG in `Test Content/` (e.g. an Uber reservation screenshot).
4. Same works for a `.md` or `.py` file.
5. Unsupported file types fail with a clear error, not a stack trace from deep inside a library.

## Hand-off to Stage 2

The `FileSummary` object plus the original file path is exactly what Stage 2 needs: embed (say) `f"{title}\n{summary}\n{', '.join(keywords)}"`, store `(embedding, summary_json, path)` as a row.
