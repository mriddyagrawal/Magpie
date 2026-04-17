# NotAnotherSpotlight

A better Spotlight: RAG-style semantic search over your local filesystem.

## The problem

Every desktop search tool we have — macOS Spotlight, Windows Search, `find`, `grep` — works the same way: you type keywords, it matches filenames and maybe a bit of file content. That's fine when you remember the exact word. It falls apart the moment you ask a real question.

- "How much was that flight to Hartford last March?"
- "Which course teaches relativity?"
- "What's our club's policy on guest voting?"

Spotlight can't answer those. It can find a file whose name contains "Hartford," but it can't read the receipt and tell you the total. It can list every course catalog PDF, but it can't scan their contents and return the one that covers relativity. The information is on your machine. The search tool just doesn't understand it.

Meanwhile, the "chat with your documents" experience on the internet — upload a PDF, ask questions, get grounded answers with citations — has become standard. Retrieval-Augmented Generation (RAG) makes that possible: embed the documents into a vector database, retrieve the relevant chunks for a question, feed them to an LLM, get an answer.

**NotAnotherSpotlight** is that same experience, but pointed at your local files instead of a curated web corpus. Ask a natural-language question about anything in a folder — receipts, course catalogs, meeting notes, PDFs, photos of whiteboards — and get back an answer grounded in the actual files, with the source files cited so you can verify.

## The idea

Three conceptual stages, run as a pipeline:

### 1. Understand each file

When you add files to the watched folder, the system reads them and produces a **structured summary** per file: title, a few sentences describing what the file is, the key entities (people, organizations, merchants, dates, amounts), and the identifiers that uniquely distinguish this file from similar ones (receipt numbers, order IDs, course codes, SKUs).

For most file types — PDFs, text, code, images of receipts — this is done by sending the file content to a vision-capable LLM and asking for that structured summary back. Scanned PDFs are handled by rasterizing each page and treating them as images. Images go through directly.

CSVs are a special case. A typical CSV is a table of many similar-looking rows (a course catalog, a list of clubs, a sales log). Summarizing the whole file in prose loses the per-row detail that makes it searchable — you can't find "the course about relativity" if the summary only says "catalog of Physics courses." So CSVs skip summarization entirely and are handled row-by-row in the next stage.

### 2. Make it searchable

The summaries (and CSV rows) are embedded into a **vector database**. Each entry gets two representations:

- A **dense embedding** that captures semantic meaning — so "pay the landlord" and "rent payment" land close together in vector space.
- A **sparse BM25 vector** that captures exact-token matching — so specific strings like `PHY-312`, `25 May 2022`, `$143.50` remain findable by their literal form.

Both representations point to the same source file, and the two scores are fused at query time so semantic and keyword-matching cases both work well. The index lives in Qdrant Cloud; the files stay local.

### 3. Answer questions

When you ask a question in natural language:

1. **(Optional) Rewrite** — the question is passed through an LLM that rewrites it into a keyword-rich search query, optionally using prior conversation turns to resolve references like "its prerequisites" or "the same course."
2. **Retrieve** — the rewritten query is embedded and searched against the vector database. The hybrid (dense + BM25) retrieval returns the top-k most relevant files.
3. **Read and answer** — the full contents of those top-k files are sent to an LLM along with the question. The model produces a grounded answer and cites which files it actually used.

The end result has the same shape as any internet-RAG chatbot — "ask a question, get a cited answer" — except the corpus is your own filesystem.

## Design principles

A few decisions shape the whole system:

**The filesystem is the source of truth.** Files are summarized and indexed, but never copied into a different store. If you delete a file, the next sync notices it's gone and cleans up the summary and the vector database entry. No shadow copies, no stale data.

**Incremental sync.** A manifest tracks every file we've seen — its byte size, when it was summarized, when it was indexed. If the size hasn't changed, we skip it. Adding one file to a folder of thousands only re-processes that one file.

**Two embeddings are better than one.** Dense embeddings handle synonyms and paraphrasing; BM25 handles exact identifiers. Each approach alone has blind spots; together they cover both "what does this mean" and "find me this specific string."

**Summaries for prose, rows for tables.** A 3-sentence summary is a great index for a receipt or a contract — the whole file has a single topic. For a 1,700-row course catalog, per-row indexing preserves the detail that makes individual rows findable.

**Conversation-aware, optionally.** Follow-up questions ("what about its prerequisites?") only make sense if the system remembers the prior turn. History is tracked per session and can be turned on or off. When on, it's sent to both the query rewriter (to resolve references) and the answer model (to interpret the current question in context), but never conflated — the answer is still grounded in the retrieved files, not recycled from a prior answer.

**Cite your sources.** Every answer names the exact files it relied on, as clickable paths. You can always verify.

## What it is, and what it isn't

**It is:**
- A way to ask natural-language questions about a folder of local files and get grounded answers.
- A hybrid semantic + keyword search over structured summaries of your files.
- Incremental — syncs only what's changed.
- Self-contained — you run it against the folder you care about.

**It isn't:**
- A cloud-sync service. Files don't leave your machine. If you run both `LLM_PROVIDER=local` and `QDRANT_PROVIDER=local`, nothing leaves at all. Cloud providers see only the small structured summaries sent for embedding / answering.
- An always-on background daemon. You run sync when you want the index refreshed.
- A replacement for full-text search over every file on your disk. It's scoped to the folders you point it at.

## LLM backends

Three interchangeable providers, selected via the `LLM_PROVIDER` environment variable. Flipping the variable is all it takes to swap — no code changes, no re-indexing. Prompts, schemas, and retrieval logic are identical across all three.

- **`moonshot`** *(default)* — Moonshot Kimi via their OpenAI-compatible API. Vision-capable, structured output via native JSON mode.
- **`openrouter`** — OpenRouter gateway. Any model they front (Gemma, Claude, GPT, Llama, etc.) works; same OpenAI-compatible protocol.
- **`local`** — On-device inference via `mlx-vlm` on Apple Silicon. Defaults to `mlx-community/gemma-3n-E2B-it-4bit` (~2GB, fits comfortably on an 8GB machine). No API key, no network calls for inference. Files never leave the machine.

The cloud providers rely on native structured output (the model is constrained to emit valid JSON matching the schema). The local provider has no equivalent mechanism, so structured output goes through a repair pipeline — direct parse, strip markdown fences, extract a JSON object by brace match, fall back to a minimal valid structure on hard failures. The pipeline never crashes on a malformed response.

### Local inference (Apple Silicon)

When `LLM_PROVIDER=local`:

- **Requirements**: Apple Silicon Mac, macOS, ~4GB free disk (~2GB model + runtime), 8GB+ RAM.
- **First run**: the model downloads automatically from Hugging Face on first use (~2GB for E2B, ~4GB for E4B). Subsequent runs load from the local HF cache in ~10-20 seconds.
- **Latency**: ~2-6s per text call, 4-12s per image-bearing call. Noticeably slower than cloud, but bounded and predictable.
- **Concurrency**: keep `--concurrency 1` for `ns --sync`. Local inference is single-GPU; parallel workers contend for the same hardware and increase memory pressure without throughput benefit. Cloud providers with generous rate limits can handle more.
- **More memory available?** On 16GB+ Macs, switch to the larger `mlx-community/gemma-3n-E4B-it-4bit` (~4GB) for better quality: `LOCAL_MODEL=mlx-community/gemma-3n-E4B-it-4bit` in `.env`.
- **Quality caveat**: Gemma 3n E2B/E4B are small models. Summaries may be less detailed and rewritten queries less precise than what cloud models produce. The repair layer keeps the pipeline running, but expect noisier output until prompts are tuned specifically for local inference. That tuning is deliberately out of scope for the initial port.

Run `ns` the same way regardless of provider. Only `.env` changes.

## Vector database

Same pattern as the LLM: pick cloud or local via `QDRANT_PROVIDER`.

- **`cloud`** *(default)* — Qdrant Cloud cluster. Requires `QDRANT_API_KEY` and `QDRANT_CLUSTER_ENDPOINT`. Data lives in their infrastructure.
- **`local`** — Embedded Qdrant that persists to a directory on disk (defaults to `./qdrant_data/`, override with `QDRANT_LOCAL_PATH`). No server, no Docker, no network. The index lives in RAM during use and is flushed to disk on shutdown.

Combined with `LLM_PROVIDER=local`, the entire pipeline runs offline once the LLM weights and Qdrant directory are in place. Storage footprint is modest — the current corpus (~2,500 row-level points) uses under 10 MB on disk.

Switching between providers does not migrate data. After flipping `QDRANT_PROVIDER`, the new backend is empty; re-run `ns --sync` (or `--reset -y` if the manifest is stale) to rebuild the index in the new location.

## Provenance and test corpus

The project is developed against a mix of test content to stress different parts of the pipeline:

- **ReceiptQA** — a benchmark of receipt images paired with Q&A pairs, used to test image understanding and identifier extraction (amounts, dates, merchant names).
- **A university course catalog** — 1,724 courses across 61 departments, split into CSVs by department and by general-education-requirement category. Tests the row-level CSV path and the retrieval system's ability to route the right kind of query to the right kind of file.
- **A student organization directory** — 236 clubs with descriptions and categories, plus each club's uploaded PDFs and Word documents (constitutions, by-laws). Tests mixed-media ingestion at scale.

Each corpus exposes a different retrieval failure mode, which is the point — the system should handle receipts, tables, and messy real-world documents with the same interface.
