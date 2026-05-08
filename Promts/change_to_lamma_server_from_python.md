```
# Goal

Add `llama-server` subprocess support to Magpie's inference layer as an
ALTERNATIVE backend to the existing in-process `llama-cpp-python`. Both
backends coexist behind the same `LocalLLM` Protocol. Once llama-server
is validated with vision (Gemma 4 E4B + mmproj, optionally Qwen2.5-VL),
deprecate the in-process backend in a follow-up — but NOT in this PR.

The win we're after: native support for any llama.cpp GGUF, vision
models that don't depend on llama-cpp-python's binding maturity, and
grammar-constrained structured output that doesn't go through our
JSON-repair fallback.

# Context

Current state (shipped 2026-05): the Python sidecar uses
`llama-cpp-python` in-process via `src/inference/local_llm.py`. The
`LocalLLM` Protocol is the public contract. `LocalAgent` in
`src/llm.py` adapts that into structured-output (Pydantic-class) for
T3 summarize / answer / query rewrite. Vision is partly implemented
via PydanticAI `BinaryContent` blocks but the local-backend path
currently drops them — see Plan #17 follow-up.

This refactor adds a parallel `LlamaServerLLM` implementation of the
same `LocalLLM` Protocol. Selectable via env var. The existing
`LlamaCppLLM` stays untouched in this PR — we want a known-good fallback
while validating the new path.

The Magpie stack is Tauri (Rust) ↔ Python sidecar (FastAPI) ↔ Qdrant.
This refactor only touches the Python sidecar's inference layer. It
should NOT touch retrieval, RRF fusion, query rewriting, or any other
layer.

# Architecture target

```
Python sidecar (FastAPI, orchestration)
    ↕ HTTP (localhost)
llama-server subprocess pool, dynamically managed:
    - one instance per active model
    - spawned on first use, kept warm with idle timeout
    - on memory-constrained machines, only one runs at a time
       (LRU eviction)
```

# Requirements

## 1. Subprocess pool manager

Create `src/inference/llama_server_pool.py` with a class
`LlamaServerPool` that:

- Tracks a registry of model profiles (see #2 below)
- Spawns a `llama-server` subprocess on demand for a requested model
- Allocates ports starting from a configurable base (default 9100;
  NOT 8765 — that's the FastAPI sidecar). Picks the next available
  port for each new instance.
- Health-checks the spawned server (poll GET /health until 200 or
  timeout)
- Returns a client object the caller can use to make completions
- Supports concurrent instances (multiple models loaded at once)
  AND single-instance mode (LRU eviction when RAM is tight) — env
  var `LLAMA_SERVER_MAX_LOADED_MODELS` (default 1 on local, bump to
  3 on dev machines with RAM)
- Handles graceful shutdown: kill all subprocesses on sidecar exit,
  including SIGTERM trap and atexit handler so we don't leave orphan
  llama-server processes
- Streams subprocess stdout/stderr to a logger so we can debug
- On unexpected subprocess death: log loudly with the last 50 lines
  of stderr, fail the in-flight request with a clear error, surface
  to the user. **Do NOT auto-restart silently** — a crashing model
  is a real signal the user needs to act on (OOM, bad model file,
  binary version mismatch). Auto-restart can come later as a config
  flag once we have telemetry on what actually crashes and why.

Critical: ensure no orphan processes. Test by killing the Python
sidecar with SIGKILL and verifying no llama-server processes remain.

## 2. Model launch profiles

Define profiles in `src/inference/profiles.py` as a dict keyed by
model name. Each profile contains:
- `model_path`: GGUF file path
- `mmproj_path`: optional, for vision models
- `ngl`: number of layers to offload to GPU (default 999 = all)
- `ctx_size`: context window
- `batch_size`, `ubatch_size`: optional overrides (Gemma 4 vision
  needs 2048)
- `image_min_tokens`, `image_max_tokens`: optional, for vision
- `jinja`: bool, whether to pass --jinja
- `extra_args`: list[str], escape hatch for one-off flags

Initial profiles needed (in priority order):
- `gemma-4-e4b-text` — text-only, no mmproj. This is what we already
  ship today; the migration target needs to match it byte-for-byte
  before we touch anything else.
- `gemma-4-e4b-vision` — same Gemma 4 E4B model + the `mmproj-BF16.gguf`
  projector (~946 MB extra). Native vision on the model we already
  bundle. **First vision profile, not Qwen.** A 4B-effective model
  with mmproj is much better than a 7B alternative for our 8 GB
  Apple-Silicon target. Cost: one extra file to download (~946 MB).
- `qwen25-vl-7b` — vision-only fallback for users with RAM headroom
  (16 GB+ Macs, GPU desktops). Don't ship as default; document as
  opt-in via env var. Skip in this PR if it slows things down — we
  can add it as a follow-up once Gemma 4 vision is validated.
- `lfm2-5-350m` — text-only structured-output workhorse for entity
  extraction (workstream 3 of the roadmap). Cheap and fast at
  ~350M params. Add only when workstream 3 starts; out of scope for
  this PR if the goal is just "swap inference backend."

## 3. HTTP client wrapper

Implement `LlamaServerLLM` in `src/inference/llama_server.py` that
satisfies the existing `LocalLLM` Protocol from `src/inference/local_llm.py`
(`complete`, `complete_sync`, `stream` — the same surface the
`LlamaCppLLM` already implements). Same upstream callers (`LocalAgent`
in `src/llm.py`, `/generate` in `src/server.py`) just point at a
different impl based on env var.

For VISION specifically, extend the Protocol with one new method or
add a `images: list[bytes]` kwarg to `complete` — your call which is
cleaner. Vision messages translate to OpenAI's content-blocks format
(text + base64 image_url blocks) at the HTTP layer.

For STRUCTURED OUTPUT: keep the existing Pydantic-class API. The
caller passes a `BaseModel` subclass (e.g. `FileSummary`); the
`LlamaServerLLM` derives the JSON schema from the Pydantic model,
passes it as `response_format={"type": "json_object", "schema": ...}`
to llama-server (which uses grammar-constrained sampling natively),
and returns parsed JSON. The existing `parse_json_with_repair`
fallback in `src/llm.py` stays as a safety net for the rare case
the model still emits malformed JSON.

Important: do NOT introduce a separate dict-schema API
(`structured(messages, schema: dict)` returning `dict`). Every
existing call site uses Pydantic classes (`FileSummary`, `Answer`,
`SearchQuery`); migrating them all to dicts is gratuitous churn.
Adapt llama-server's grammar input under the hood.

## 4. Binary bundling and discovery

- Look for `llama-server` binary in this order:
  1. `MAGPIE_LLAMA_SERVER_PATH` env var if set
  2. `<app_resources>/bin/llama-server[.exe]` (bundled)
  3. `llama-server` on PATH (developer convenience)
- If not found, fail loudly at sidecar startup with a clear error
  pointing to setup docs.
- Verify version compatibility: run `llama-server --version`,
  check it's >= the minimum we require. **Hard-fail at startup**, not
  warning — a too-old binary produces cryptic errors at inference
  time, much worse than a clear "your llama-server is too old, get
  >= bNNNN" exit message. Pin the actual minimum tag in code; b8600+
  (spring 2026) is a reasonable target — pick one specific tag,
  pin it, ship.

For now, just document the bundling structure. Don't try to ship
binaries automatically — we'll wire that into the Tauri build
pipeline separately.

## 5. Migrate existing call sites — by adding a backend selector, NOT replacing

Find every place currently using `LocalLLM` / `LlamaCppLLM` and
verify they all go through the Protocol (they should — the audit
should turn up zero direct `from llama_cpp import` outside
`src/inference/local_llm.py`).

The migration is **a one-line change**: add a backend selector in
`src/inference/__init__.py:get_local_llm()` that picks between
`LlamaCppLLM` (existing) and `LlamaServerLLM` (new) based on env var
`LOCAL_BACKEND` (values: `llama-cpp` (default), `llama-server`).

```python
def get_local_llm() -> LocalLLM:
    backend = os.environ.get("LOCAL_BACKEND", "llama-cpp").strip().lower()
    if backend == "llama-server":
        from src.inference.llama_server import LlamaServerLLM
        return LlamaServerLLM()
    return LlamaCppLLM()  # existing default
```

That's it. Every existing call site (`LocalAgent`, `/generate`,
T3 summarizer's preload, etc.) keeps working. Users opt into
the new backend by setting `LOCAL_BACKEND=llama-server` in `.env`.

**Critical pre-flight check** — before writing any code, audit:
- Any direct `Llama(...)` instantiation outside `LlamaCppLLM`
- Any code that passes `LocalLLM` instances around as parameters
  (should be fine — we use the singleton everywhere — but verify)
- Any synchronous-latency assumption in hot loops that won't survive
  HTTP round-trips (~5ms localhost overhead per call)
- Any chat-template or tokenization assumption — chat templates run
  server-side now via llama-server's `--jinja` flag. Verify our
  current Gemma 4 prompt format (the `<|think|>` token injection in
  `src/inference/chat_template.py`) survives the move

Don't change prompt construction or any business logic — just swap
the underlying call.

## 6. Configuration

Magpie uses `.env` env vars, not YAML. Add the new inference knobs
to `.env` and `.env.example`, mirroring the existing `LOCAL_*` style.
Example block to add:

```
# --- llama-server backend (alternative to llama-cpp-python) ---
# Default backend stays llama-cpp-python until llama-server is validated
# with vision. Switch with LOCAL_BACKEND=llama-server.
LOCAL_BACKEND=llama-cpp                          # llama-cpp | llama-server
LLAMA_SERVER_PATH=                               # empty = auto-discover
LLAMA_SERVER_MIN_VERSION=b8600                   # pin to a specific tag
LLAMA_SERVER_BASE_PORT=9100                      # NOT 8765 (FastAPI sidecar)
LLAMA_SERVER_MAX_LOADED_MODELS=1                 # 1 on local; 3 on dev box
LLAMA_SERVER_IDLE_TIMEOUT_S=600                  # unload idle models after this
LLAMA_SERVER_STARTUP_TIMEOUT_S=60                # health-check before giving up

# Per-model selection (model name → profile in src/inference/profiles.py)
LLAMA_SERVER_TEXT_MODEL=gemma-4-e4b-text
LLAMA_SERVER_VISION_MODEL=gemma-4-e4b-vision     # default; opt into qwen25-vl-7b
```

Plan #19 covers the eventual move from `.env` to a structured config
file with keychain-backed secrets. Don't preempt it here — adding YAML
just for this feature creates a third config format. Stay on `.env`
until the unified-config work lands.

## 7. Keep llama-cpp-python for now; deprecate after vision validation

DO NOT remove `llama-cpp-python` from `pyproject.toml` in this PR.
We just shipped that backend (commit `82ecb8c`, 2026-05); throwing
it away before validating llama-server end-to-end with vision is
real waste — the `LocalAgent` test suite, `just install-llama`
recipe, README install matrix, all of it would have to be rewritten
twice in a month.

Instead:
- Add llama-server as a coexisting alternative behind `LOCAL_BACKEND`
- Document install instructions for llama-server (manual download
  for now: link to llama.cpp releases page, document the binary
  location, mention the version pin)
- Once llama-server is validated with Gemma 4 vision (mmproj) on
  Mac/Linux/Windows, open a follow-up PR that:
  1. Flips the `LOCAL_BACKEND` default to `llama-server`
  2. Adds a deprecation warning when `LOCAL_BACKEND=llama-cpp`
  3. After one release of warning, drops `llama-cpp-python` and the
     `LlamaCppLLM` impl

Two backends in the tree for a release cycle is a small price for
a clean migration.

## 8. Tests

- Unit tests for the pool manager: spawn/health/shutdown cycle
- Unit tests for client: mock the HTTP responses, verify request
  format
- Integration test that requires a real llama-server binary +
  a tiny GGUF model — mark as `@pytest.mark.integration`, skip by
  default in CI without that fixture
- Smoke test: spawn llama-server with a tiny model, make one
  completion request, verify response, shut down, verify no orphan
  process

# Out of scope

- Don't refactor retrieval, RRF, or any non-inference code
- Don't auto-bundle binaries in this PR — just document where they
  go and how to discover them. Bundling goes in a follow-up tied to
  the Tauri build.
- Don't add MLX or any other backend — llama-server only for this
  refactor.
- Don't change the API surface that the Tauri frontend talks to —
  the sidecar's HTTP endpoints stay identical.

# Deliverables

- `src/inference/llama_server_pool.py` — pool manager
- `src/inference/profiles.py` — model launch profiles
- `src/inference/llama_server.py` — `LlamaServerLLM` implementation
  of the existing `LocalLLM` Protocol
- `src/inference/__init__.py` — `get_local_llm()` updated to dispatch
  on `LOCAL_BACKEND` env var
- `src/inference/local_llm.py` — UNCHANGED (existing `LlamaCppLLM`
  stays the default backend until validated)
- `.env` + `.env.example` — new `LOCAL_BACKEND` + `LLAMA_SERVER_*`
  knobs documented
- README — new section on llama-server install (binary download +
  version pin); existing `just install-llama` recipe stays for the
  default llama-cpp backend
- Tests as described — pool manager unit + LlamaServerLLM HTTP
  client unit + integration test (gated like the existing one)
- A short `docs/inference.md` explaining the dual-backend architecture,
  how to add a new model profile, and how to debug a stuck subprocess

# Process

Confirm the plan back to me before writing code. Especially flag:
- Any current llama-cpp-python usage I haven't anticipated
- Any chat-template or tokenization assumptions in current code
  that won't survive the move to HTTP (chat templates now apply
  server-side — verify this doesn't break anything)
- Anything in retrieval/orchestration that was implicitly assuming
  in-process calls (e.g. shared state, model handles passed around)
```

Two things to know before kicking this off:

**Verify before swapping.** The "anything in retrieval that assumed in-process" line in the Process section is the real risk. If any code is passing a `Llama` object around as a parameter, doing zero-shot inference inside hot loops without HTTP timeout handling, or relying on synchronous in-process latency for batch-like patterns, those need to be flagged before refactor, not discovered during.

**The `min_version: "b6500"` placeholder.** Replace with whatever the actual minimum llama.cpp release tag you want to require is. Pick a tag that's recent enough to have Gemma 4 + Qwen2.5-VL working cleanly but stable enough that you're not chasing nightly bugs. The b8600+ range from spring 2026 is a reasonable target — pick one specific tag, pin to it, ship.

The "confirm the plan first" line at the end is important. Without it Claude Code will dive into writing code, and the migration depends on understanding your existing call sites first. Make it stop and propose before generating.