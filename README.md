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
- A cloud-sync service. Files don't leave your machine. With `LLM_PROVIDER=local`, nothing leaves at all — Qdrant is always local. Cloud LLM providers see only the small structured summaries sent for embedding / answering.
- An always-on background daemon. You run sync when you want the index refreshed.
- A replacement for full-text search over every file on your disk. It's scoped to the folders you point it at.

## LLM backends

Five interchangeable providers, selected via the `LLM_PROVIDER` environment variable. Flipping the variable is all it takes to swap — no code changes, no re-indexing. Prompts, schemas, and retrieval logic are identical across all of them.

- **`moonshot`** — Moonshot Kimi via their OpenAI-compatible API. Vision-capable, structured output via native JSON mode.
- **`openrouter`** *(default)* — OpenRouter gateway. Any model they front (Gemma, Claude, GPT, Llama, etc.) works; same OpenAI-compatible protocol.
- **`ollama`** — Local Ollama daemon (Linux / Windows / Intel-Mac). OpenAI-compatible.
- **`local`** — Subprocess inference via `llama-server` (HTTP) + GGUF weights. Cross-platform: Metal on macOS, CUDA on Linux / Windows, CPU fallback. Vision support via mmproj projector (Gemma 4 E4B native). No API key, no network calls for inference. Files never leave the machine.
- **`magpie-cloud`** — Magpie's hosted backend. Auth via invite code; prompts live server-side.

The cloud providers rely on native structured output (the model is constrained to emit valid JSON matching the schema). The local provider has no equivalent mechanism, so structured output goes through a repair pipeline — direct parse, strip markdown fences, extract a JSON object by brace match, fall back to a minimal valid structure on hard failures. The pipeline never crashes on a malformed response.

### Local inference

When `LLM_PROVIDER=local`, Magpie spawns one or more `llama-server` subprocesses (Metal / CUDA / CPU built-in to the binary) and routes all LLM calls — T3 summarize, query rewrite, answer synthesis, the `POST /generate` endpoint — through their HTTP `/v1/chat/completions` endpoint. The Python sidecar manages the subprocess pool: spawn on demand, health-check, idle-evict, kill at exit.

#### One-time install

After `just sync-environment`, run:

```
just install-llama-server
```

This downloads the right `llama-server` binary for your platform from llama.cpp's GitHub releases (~30 MB), stages it under `<APP_DATA_DIR>/bin/`, strips macOS quarantine, and verifies the version. It ALSO pre-downloads the Gemma 4 E4B vision projector (`mmproj-BF16.gguf`, ~946 MB) so the first vision-bearing summary doesn't pause for several minutes on a slow connection. Skip the projector with `SKIP_MMPROJ_DOWNLOAD=1 just install-llama-server` if you don't need local vision. Override the version pin with `LLAMA_SERVER_VERSION=b5500 just install-llama-server`.

Supported platforms (auto-detected):

| Platform | Asset |
|---|---|
| macOS Apple Silicon | `macos-arm64.zip` (Metal) |
| macOS Intel | `macos-x64.zip` (Accelerate) |
| Linux x86_64 | `ubuntu-x64.zip` (CPU; CUDA build = manual override) |
| Windows | manual download (documented in the recipe) |

#### Default model

`unsloth/gemma-4-E4B-it-GGUF` at the `Q5_K_XL` quant (~6.7 GB) downloads automatically from Hugging Face into `<APP_DATA_DIR>/cache/hub/` on first inference. Subsequent runs load from local cache in ~10-20s. Override via `.env`:

```
LOCAL_MODEL=unsloth/gemma-4-E4B-it-GGUF   # HF GGUF repo
LOCAL_QUANT=Q5_K_XL                       # quant inside that repo
LOCAL_N_CTX=8192                          # context window
LOCAL_TEMPERATURE=0.7                     # sampling temperature
```

Subprocess pool tunables (also in `.env`):

```
LLAMA_SERVER_PATH=                        # empty = auto-discover
LLAMA_SERVER_MIN_VERSION=b9049            # hard-fail if older — must support gemma4 arch
LLAMA_SERVER_BASE_PORT=9100               # NOT 8765 (FastAPI sidecar)
LLAMA_SERVER_MAX_LOADED_MODELS=1          # 1 = sequential, LRU eviction
LLAMA_SERVER_IDLE_TIMEOUT_S=600           # unload after 10 min idle
LLAMA_SERVER_STARTUP_TIMEOUT_S=60         # wait for /health on spawn
LLAMA_SERVER_TEXT_MODEL=gemma-4-e4b-vision  # default profile (handles BOTH text and images)
LLAMA_SERVER_VISION_MODEL=gemma-4-e4b-vision  # routing target if a text-bound caller hits an image
LOCAL_MMPROJ_VARIANT=BF16                 # mmproj quant (BF16 / F16 / Q8_0 / …)
```

Available Gemma 4 E4B quants (all UD = Unsloth Dynamic-2.0, on the Pareto frontier):

| Quant | Size | Notes |
|---|---|---|
| `Q4_K_XL` | ~5.1 GB | smaller / faster |
| `Q5_K_XL` | ~6.7 GB | **default** — balanced |
| `Q6_K_XL` | ~7.5 GB | higher quality |
| `Q8_K_XL` | ~8.7 GB | near-original quality, ~2× slower |

#### Runtime characteristics

- **Latency**: ~1-3s per text call on Metal/CUDA (Apple Silicon M-series, modern NVIDIA), plus ~5 ms HTTP localhost overhead. CPU fallback is bounded but noticeably slower.
- **Concurrency**: HTTP-safe — multiple Python coroutines can submit concurrent requests; llama-server's internal scheduler handles them. Throughput is bounded by the single subprocess.
- **Vision**: Gemma 4 E4B is natively multi-modal — one set of weights handles text and images, with `mmproj-BF16.gguf` (~946 MB) acting as the image encoder bolted onto the base GGUF. By default both load into the same subprocess and serve every request: text-only calls run at full speed (the projector tensors aren't in the forward pass when no image is attached), image-bearing calls go through the vision path. No LRU swapping. To save the projector's resident memory on tight-RAM machines, opt out with `LLAMA_SERVER_TEXT_MODEL=gemma-4-e4b-text` in `.env` — that splits inference into two profiles and incurs a ~25-30s cold-load when transitioning between text and image workloads. The same `--mmproj` pattern applies to Qwen2.5-VL, LFM2-VL, MiniCPM-V (architectural parity, not yet tested in Magpie).
- **Quality caveat**: Gemma 4 E4B is small. Summaries may be less detailed than what `gemma-4-31B-it` or Claude Sonnet produce. The JSON-repair layer keeps the pipeline running on imperfect output.

#### Thinking mode

Gemma 4 supports a thinking mode (model emits internal reasoning before the final answer). Toggle per-call via the `thinking=True` kwarg on `ChatAgent.run` / `ChatAgent.run_sync`, or in `POST /generate`'s request body. Default off — Magpie is latency-sensitive. Cloud providers accept the kwarg but currently no-op with a one-time warning until per-provider reasoning APIs are wired (tracked in `Plans/Future Plans.md` #16).

Run `ns` the same way regardless of provider. Only `.env` changes.

## Vector database

Magpie targets exactly one Qdrant deployment shape: **the real Qdrant Rust binary running on localhost.** No remote clusters, no Python embedded shim, no Docker. Both alternatives existed in earlier versions and were dropped in 2026-05 — the remote-cluster mode broke the privacy promise, and the embedded Python shim silently disabled quantization, payload indexes, and other server features that the at-scale tests relied on.

Set up once with:

```bash
just qdrant-install   # one-time download (~30 MB)
just qdrant-up        # start the binary on port 6433
```

Port 6433 (deliberately NOT Qdrant's default 6333) avoids colliding with OpenWhispr and other apps that ship their own bundled Qdrant. Override the port via `QDRANT_CLUSTER_ENDPOINT=http://localhost:<port>` if you need to; the host must resolve to loopback or Magpie hard-errors at startup.

Combined with `LLM_PROVIDER=local`, the entire pipeline runs offline once the LLM weights and Qdrant binary are in place. Storage footprint is modest — the current corpus (~2,500 row-level points) uses under 10 MB on disk.

## Magpie UI

A Spotlight-style floating window sits on top of the RAG backend. Same index, same answer pipeline — just a native-feeling macOS surface instead of a terminal REPL. Hit ⌘K from anywhere, type a question, get a grounded answer with clickable sources and an inline file preview on the right.

Multi-card layout, dark-vibrancy glass, single gold accent (`#ffe97a`), Roboto / Roboto Mono / Roboto Slab typography. Answer mentions and document contents are highlighted in gold so the grounding is visually obvious.

### One-time setup

The backend stays the same as the CLI workflow. The UI needs two extra tools:

1. **Rust toolchain** (for Tauri). Installs into `~/.cargo`, doesn't touch system paths:
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
   source ~/.cargo/env
   ```
2. **Node package manager**. `pnpm` is recommended; `npm` works too. If you have neither:
   ```bash
   brew install pnpm
   ```

Then install frontend deps once:

```bash
cd frontend && pnpm install
```

### Dev loop

Two processes. The Python sidecar on a known port (so Vite can hit it) and Tauri driving the window.

```bash
# Terminal 1 — Python sidecar (auto-reloads on source change)
uv run uvicorn src.server:app --port 8765 --reload

# Terminal 2 — Tauri window (launches Vite + Rust shell)
cd frontend && pnpm tauri dev
```

Switch the LLM backend the same way as the CLI — edit `.env` (`LLM_PROVIDER=local`, `LLM_PROVIDER=openrouter`, etc.). The status pill at the bottom of the window shows which backend you're running against. Qdrant is always local.

### Production build

```bash
cd frontend && pnpm tauri build
# output: src-tauri/target/release/bundle/macos/Magpie.app
```

In a production build, Tauri spawns the Python sidecar itself (`uv run python3 -m src.server`) and reads the chosen port from its first stdout line, so the running app is self-contained — no separate terminal required.

### Shortcuts

| Key | Action |
|---|---|
| `⌥ Space` (global) | Summon the window from any app |
| `Enter` in the question bar | Submit |
| `Esc` (first press) | Collapse back to resting state + clear input |
| `Esc` (again, empty) | Hide the window |
| `↑` / `↓` | Move through source list, preview follows |
| `Enter` on a source | Open in the OS default app |
| `⌘ + Enter` on a source | Reveal in Finder |

Spotlight-style behavior: Magpie **hides whenever the window loses focus** — click another app, hit Spotlight, switch to a browser, whatever. Summon it back with `⌥ Space`. This includes dev mode, so editing code in VS Code while developing *will* hide the window; `⌥ Space` brings it back instantly.

If the global `⌥ Space` registration fails at startup (you'll see it in the terminal log: `⌥Space register failed: ...`), something else on your machine has already claimed that combo. The window still works; you just won't be able to summon it globally. Change the shortcut in [src-tauri/src/lib.rs](frontend/src-tauri/src/lib.rs) (look for `Modifiers::ALT` + `Code::Space`) and rebuild.

The CLI (`ns`) keeps working as a parallel entry point — same index, same answers, no UI dependency.

## Provenance and test corpus

The project is developed against a mix of test content to stress different parts of the pipeline:

- **ReceiptQA** — a benchmark of receipt images paired with Q&A pairs, used to test image understanding and identifier extraction (amounts, dates, merchant names).
- **A university course catalog** — 1,724 courses across 61 departments, split into CSVs by department and by general-education-requirement category. Tests the row-level CSV path and the retrieval system's ability to route the right kind of query to the right kind of file.
- **A student organization directory** — 236 clubs with descriptions and categories, plus each club's uploaded PDFs and Word documents (constitutions, by-laws). Tests mixed-media ingestion at scale.

Each corpus exposes a different retrieval failure mode, which is the point — the system should handle receipts, tables, and messy real-world documents with the same interface.
