# Local LLM — llama-cpp-python migration plan

**Status:** approved 2026-05-06; implementation in progress.

## Goal

Replace the Apple-only `mlx-vlm` local backend with `llama-cpp-python` + GGUF
weights so local inference works on macOS (Metal), Linux (CUDA / CPU), and
Windows (CUDA / CPU) from one codebase. One engine, two surfaces:

- **Structured-output surface** — existing `ChatAgent` contract used by T3
  summarize, query rewriting, and answer synthesis. JSON-repair stays as the
  glue between raw model output and Pydantic.
- **Raw chat surface** — new `LocalLLM.complete()` and `LocalLLM.stream()`
  feeding a new `POST /generate` endpoint on the FastAPI sidecar, intended
  for future agentic loops and direct chat use cases.

## Locked design decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Module layout | New code under `src/inference/`. No new `magpie/` package. |
| 2 | mlx-vlm | **Replace.** Drop dependency. Drop `_require_apple_silicon`. |
| 3 | Architecture | One engine. `LocalAgent` is rewritten as a thin wrapper around `LocalLLM` + `parse_json_with_repair`. |
| 4 | Cache directory | `<APP_DATA_DIR>/cache/hub/` via the existing `HF_HOME` redirect from `manifest.py`. No new directory. |
| 5 | Config home | `.env` env vars for now (`LOCAL_MODEL`, `LOCAL_QUANT`, etc.). Future Plan #16 covers GUI migration. |
| 6 | Default quant | `Q5_K_XL` (6.66 GB). Override via `LOCAL_QUANT`. Smaller `Q4_K_XL` (5.13 GB) is the lighter alternative. |
| 7 | Thinking mode | Per-call `thinking: bool = False` kwarg on `ChatAgent.run/run_sync`. Local honors it (Gemma 4 `<|think|>` token). Cloud accepts it but no-ops with a one-time warning until per-provider reasoning APIs land. |
| 8 | `/generate` placement | Co-located in `src/server.py`. Extract to a router file later if the LLM-side endpoint count grows. |

## Files

### Dependencies / install

- **`pyproject.toml`** — drop `mlx-vlm` from dependency list. Add `llama-cpp-python>=0.3.0` (no platform filter; `CMAKE_ARGS` controls hardware accel at install time).
- **`justfile`** — new `install-llama` recipe. Detects platform; runs the right `CMAKE_ARGS … uv pip install --force-reinstall --no-cache-dir llama-cpp-python`.
  - macOS: `CMAKE_ARGS="-DGGML_METAL=on"`
  - Linux + CUDA: `CMAKE_ARGS="-DGGML_CUDA=on"`
  - Windows + CUDA: same flag, `cmd` syntax
  - CPU fallback: no `CMAKE_ARGS`.

### New code

- **`src/inference/__init__.py`** — package marker; re-exports `LocalLLM` and `LlamaCppLLM`.
- **`src/inference/local_llm.py`**
  - `LocalLLM` Protocol: `async complete(messages, *, thinking=False, temperature=None, max_tokens=None) -> str` and `async stream(messages, *, thinking=False, ...) -> AsyncIterator[str]`.
  - `LlamaCppLLM` impl wrapping `llama_cpp.Llama.create_chat_completion`. Sync calls wrapped in `asyncio.to_thread`. Streaming uses an `asyncio.Queue` + producer thread (sync generator → async iterator).
  - Module-level singleton: `get_local_llm()`. Lazy load.
  - Reads env on construction: `LOCAL_MODEL` (default `unsloth/gemma-4-E4B-it-GGUF`), `LOCAL_QUANT` (default `Q5_K_XL`), `LOCAL_N_CTX` (default 8192), `LOCAL_N_GPU_LAYERS` (default -1), `LOCAL_TEMPERATURE` (default 0.7).
- **`src/inference/model_downloader.py`**
  - `ensure_model(repo_id, quant) -> Path`. Wraps `huggingface_hub.hf_hub_download` with `tqdm` progress callback. Idempotent (cache hit returns immediately). SHA verification is automatic via `huggingface_hub`.
  - Filename derivation: `gemma-4-E4B-it-UD-{QUANT}.gguf` for Unsloth's UD-prefixed Gemma 4 GGUFs. (Generic helper would let other repos override the pattern.)
- **`src/inference/chat_template.py`**
  - Helper for thinking-mode token injection. Per the Gemma 4 spec, `<|think|>` in the system prompt enables thinking; absence disables. E4B specifically does not emit empty thought blocks when off.
  - Gracefully no-op when `enable_thinking` is True for a non-thinking-capable model (LLM never sees the token; no crash).

### Rewritten

- **`src/llm.py`**
  - `LocalAgent` rewritten on top of `LocalLLM`:
    - `LocalAgent.run(message, *, thinking=False)` → `LocalLLM.complete(...)` → `parse_json_with_repair(raw, output_type, fallback)`.
  - Drop `_require_apple_silicon`, drop `get_model()` (the mlx-vlm loader), drop all `mlx_vlm` imports.
  - `ChatAgent` Protocol grows a `thinking: bool = False` kwarg on both `run` and `run_sync`.
  - `_CloudAgent` accepts `thinking` but logs a `warnings.warn(...)` once per process when `thinking=True`. Future per-provider reasoning support lands here.
  - `PROVIDERS["local"]` default model string changes from `mlx-community/gemma-3n-E2B-it-4bit` to `unsloth/gemma-4-E4B-it-GGUF`.

### Server

- **`src/server.py`**
  - New `POST /generate` endpoint. Body: `{messages: [{role, content}], stream: bool, thinking: bool, temperature: float?, max_tokens: int?}`. Returns JSON for `stream=false`, `text/event-stream` SSE for `stream=true`.
  - Reuses `get_local_llm()` singleton; first call triggers GGUF download + load.

### Config

- **`.env`** — replace MLX-related lines:
  ```
  LOCAL_MODEL=unsloth/gemma-4-E4B-it-GGUF
  LOCAL_QUANT=Q5_K_XL
  LOCAL_N_CTX=8192
  LOCAL_N_GPU_LAYERS=-1
  LOCAL_TEMPERATURE=0.7
  LOCAL_THINKING=false
  ```
- **`.env.example`** — same with explanatory comments.

### Tests

- **`tests/inference/__init__.py`**
- **`tests/inference/test_local_llm.py`**
  - Smoke tests using TinyLlama-1.1B-Chat-v1.0-Q4_K_M (~640 MB).
  - `complete()` returns a non-empty string for a trivial prompt.
  - `stream()` yields ≥ 2 chunks.
  - `LocalAgent` round-trip with a tiny Pydantic schema (validates the `LocalLLM` ↔ `parse_json_with_repair` integration).
  - `thinking=True` on a non-thinking model is a silent no-op (no exception, no token leak in output).
- **`tests/inference/test_local_llm_integration.py`** — `@pytest.mark.integration` tests using the real Gemma 4 E4B Q5_K_XL. Skipped by default. `just test-integration` runs them.

### Docs

- **`README.md`** — rewrite the "Local inference (Apple Silicon)" section as "Local inference" with the install matrix:
  - macOS Metal: `just install-llama`
  - Linux CUDA: `just install-llama`
  - Linux CPU: `just install-llama` (auto-detected)
  - Windows: documented but un-tested
  - `LOCAL_QUANT` override examples and quality/size table.
- **`Plans/Future Plans.md`** — add Plan #16: "LLM / Inference settings UI" covering future migration of `LLM_PROVIDER`/`LOCAL_*` from `.env` to a GUI-editable JSON, plus tracking cross-provider thinking-mode unification.

## Migration & risks

- **Disk impact:** first `just sync` after this lands triggers a ~6.66 GB GGUF download. Cached at `<APP_DATA_DIR>/cache/hub/` for all subsequent runs.
- **No re-ingestion needed.** Existing summaries stay valid; only re-summarized files use the new model.
- **mlx-vlm stays in the venv** until `uv sync` cleans it up; production code no longer references it.
- **`notebooks/chat_local.py`** still imports `mlx_vlm` directly. Left as-is with a one-line header noting that running it requires `uv pip install mlx-vlm` separately. It's an exploration notebook, not in the prod path.
- **Streaming + structured output don't compose.** `stream()` is `/generate`-only; T3/answer/rewrite stay non-streaming because they need parsed Pydantic. Right boundary, worth noting.
- **Cloud `thinking=True`** is a soft warning, not a hard error. Could promote to error later if it becomes a footgun.
- **macOS+Metal install fragility:** `llama-cpp-python` Metal wheels can fail on Xcode CLT mismatch. The `install-llama` recipe surfaces a clear failure mode rather than silently falling back to CPU.

## Order of implementation

1. `pyproject.toml` — dependency swap.
2. `justfile` — `install-llama` recipe.
3. `src/inference/local_llm.py` + helpers + `__init__.py`.
4. `src/inference/model_downloader.py`.
5. `src/inference/chat_template.py`.
6. `src/llm.py` rewrite.
7. `src/server.py` `/generate` endpoint.
8. `.env` + `.env.example`.
9. Tests.
10. README + Future Plans.md.
