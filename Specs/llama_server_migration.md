# Spec — llama-cpp-python → llama-server migration (vision-capable local LLM)

**Status:** approved 2026-05-07; implementation in progress on branch `llama-server`.

**Author:** Mridul + Claude (planning session 2026-05-07).

**Branch:** `llama-server` (off `ingestion-rules`).

**Ship strategy:** three sequential PRs in this session. Each PR is independently testable; failure in any later phase does not roll back earlier phases.

---

## Goal

Swap Magpie's local LLM backend from in-process `llama-cpp-python` to subprocess `llama-server` (HTTP). The win:

- **Vision works locally.** llama-cpp-python's binding maturity for newer VLMs (Gemma 4 + mmproj) is the bottleneck. llama-server has native vision support via the OpenAI-compatible content-blocks format.
- **Native grammar-constrained structured output.** llama-server supports `response_format` with JSON schema (server-side, ~free). We currently rely on JSON-repair fallbacks.
- **Cross-platform binary, no wheel matrix.** llama-cpp-python required `CMAKE_ARGS="-DGGML_METAL=on"` rebuilds; llama-server is a single platform-specific binary.
- **Simpler install path.** Auto-download from llama.cpp GitHub releases, same mechanism for dev install AND eventual `.app` bundling (Plan #10).

This is a complete replacement, not coexistence. `llama-cpp-python` is removed in PR 1.

---

## Pre-flight audit findings (clean)

Verified 2026-05-07 against current `ingestion-rules` tip:

| Question | Result |
|---|---|
| Direct `llama_cpp` imports in `src/`, `tests/` | **Only** `src/inference/local_llm.py`. ✓ |
| `Llama(...)` instantiations outside the wrapper | **Zero**. ✓ |
| `LocalLLM` / `get_local_llm()` call sites | Three: `src/server.py:251` (`/generate`), `src/llm.py:461,478` (`LocalAgent.run/run_sync`), `src/stage1/summarize.py:460` (preload). All go through the singleton. Backend selector pattern works cleanly. ✓ |
| Sync-latency hot paths | `complete_sync` is called once per `LocalAgent.run_sync` (not a tight loop). ~5 ms HTTP overhead is invisible. ✓ |
| Chat-template / thinking-token | `apply_thinking_to_messages` injects `<|think|>` into the system-message string BEFORE the LLM call. With `--jinja`, llama-server applies the GGUF's chat template to the message list — our injected token goes through as system-message content. Should survive. **Verify empirically in PR 1's smoke test.** |

Conclusion: no architectural surprises. Backend swap is a localized change to `src/inference/`.

---

## Decisions log (locked in)

| Decision | Choice | Rationale |
|---|---|---|
| Coexist or replace | **Replace.** Remove llama-cpp-python entirely in PR 1. | We just shipped llama-cpp-python, but vision is the immediate need and llama-cpp-python has no path to it. Maintaining two backends adds churn. |
| `LOCAL_BACKEND` env selector | **Remove.** Only one backend now. | Less moving parts. |
| `LLAMA_SERVER_MIN_VERSION` pin | `b5400` (May 2026) | Spring 2026 is post-Gemma-4 stable + Qwen2.5-VL support. b5400 is the current month's tip; safe and well-tested. |
| Binary install path | Auto-download from llama.cpp GitHub releases via a justfile recipe. NOT brew. | Same download mechanism dev + prod (eventual `.app` bundle). One source of truth. |
| Bundling story (Plan #10 future) | The `.app` build pipeline calls the same downloader to vendor the binary into `<App.app>/Contents/Resources/bin/llama-server`. Discovery order: env var → bundled path → `PATH`. | Dev workflow (brew or PATH) and prod workflow (bundled) share code. |
| mmproj download | Eager — at `just install-llama-server` time, not lazy on first vision query. | Predictable. Avoids a 946 MB pause on the user's first PDF query. |
| Default vision model | **Gemma 4 E4B + mmproj-BF16.gguf** (~6.7 GB GGUF + 946 MB mmproj). NOT Qwen2.5-VL-7B. | We already ship Gemma 4 E4B for text. Adding the mmproj projector is one extra file. Qwen2.5-VL-7B is too heavy for the 8 GB Apple-Silicon target. Add Qwen as an opt-in profile in PR 2 if there's RAM. |
| `LFM2.5-350M` text-only profile | **Out of scope.** Defer to Workstream 3 (entity extraction). | This spec is about the llama-server swap, not adding new models. |
| Streaming | SSE proxy from llama-server's native stream | Lower latency, less code than the asyncio queue+thread pattern. |
| Test image | User provides a real test image; placed at `tests/inference/image.png` | Spec note: real fixture committed to the repo. |
| Auto-restart on subprocess crash | **Drop.** Log loudly + fail the request. | Auto-restart hides real failures (OOM, bad model, version mismatch). Add later as a flag if telemetry justifies it. |
| Tests | Pool manager unit, HTTP client unit, integration smoke (gated by env). User provides the image fixture; chat-test prompts I write. | Standard structure mirroring existing `tests/inference/`. |

---

## Phase / PR breakdown

Three PRs. Each commits cleanly on `llama-server` and is independently shippable to `ingestion-rules`.

### PR 1 — Text path through llama-server (replaces llama-cpp-python)

**Goal:** prove the new backend matches `llama-cpp-python`'s text behavior. Vision still doesn't work; that comes in PR 2.

**Files added:**

| File | Purpose |
|---|---|
| `src/inference/profiles.py` | Model launch profiles dict, keyed by name. Initial entry: `gemma-4-e4b-text` (no mmproj). |
| `src/inference/llama_server_pool.py` | Subprocess pool manager. Spawns llama-server on demand; health-checks `GET /health`; LRU eviction at `LLAMA_SERVER_MAX_LOADED_MODELS`; idle-timeout unloads at `LLAMA_SERVER_IDLE_TIMEOUT_S`; SIGTERM/atexit kills children; streams stderr to logger; logs-and-fails (no auto-restart) on subprocess death. |
| `src/inference/llama_server_binary.py` | Binary discovery: env var → bundled path → `PATH`. `--version` parsing + min-version check (hard-fail at startup). |
| `tests/inference/test_llama_server_pool.py` | Unit tests with mocked subprocess + `httpx`. |
| `tests/inference/test_llama_server.py` | HTTP client unit tests with `pytest-httpx`. |
| `tests/inference/test_llama_server_integration.py` | `@pytest.mark.integration`, gated by `RUN_LLAMA_SERVER_TESTS=1` + binary present. Smoke: full text completion, streaming, `complete_sync`. |

**Files rewritten:**

| File | Change |
|---|---|
| `src/inference/local_llm.py` | `LocalLLM` Protocol stays. `LlamaCppLLM` is **deleted**. New `LlamaServerLLM` is the only impl, satisfying the same Protocol. `get_local_llm()` always returns it. |
| `src/inference/__init__.py` | Re-exports update. Drop `LlamaCppLLM`. |

**Files updated:**

| File | Change |
|---|---|
| `pyproject.toml` | Remove `llama-cpp-python` and `huggingface-hub` (the latter stays only if model_downloader still needs it — it does, for GGUFs). Keep `huggingface-hub`. |
| `justfile` | **Delete** `install-llama` (the cpp-python rebuild recipe). **Add** `install-llama-server` (downloads platform-appropriate binary tarball from llama.cpp GitHub releases, extracts to `<APP_DATA_DIR>/bin/`, verifies `llama-server --version`). |
| `.env` + `.env.example` | Remove `LOCAL_N_GPU_LAYERS` (replaced by per-profile `ngl`). Add `LLAMA_SERVER_PATH`, `LLAMA_SERVER_MIN_VERSION=b5400`, `LLAMA_SERVER_BASE_PORT=9100`, `LLAMA_SERVER_MAX_LOADED_MODELS=1`, `LLAMA_SERVER_IDLE_TIMEOUT_S=600`, `LLAMA_SERVER_STARTUP_TIMEOUT_S=60`. Keep `LOCAL_MODEL`, `LOCAL_QUANT`, `LOCAL_N_CTX`, `LOCAL_TEMPERATURE`, `LOCAL_THINKING`. |
| `README.md` | Replace the Metal/CUDA `CMAKE_ARGS` matrix with `just install-llama-server` instructions. |
| `tests/inference/test_chat_template.py` | No change — pure unit tests. |
| `tests/inference/test_message_flatten.py` | Update the warning-on-binary-drop test. With vision still unsupported in PR 1, the warning behavior stays — just emitted from `LlamaServerLLM` now. |
| `tests/inference/test_local_llm_integration.py` | **Delete.** Replaced by `test_llama_server_integration.py`. |

**Validation gate before merging PR 1:**
- `LOCAL_THINKING=false`, run `just sync` over the user's test corpus, confirm T3 LLM summaries land in Qdrant
- Run `just run-magpie`, ask a known-good question, confirm answer + sources match the previous run
- Confirm zero orphan llama-server processes after `kill -9` of the sidecar (test by `pgrep llama-server`)

**Estimated size:** ~600 LOC net change (delete 350 from `local_llm.py` + tests, add 950 across new pool/server/tests).

---

### PR 2 — Vision plumbing (Gemma 4 + mmproj)

**Goal:** load the mmproj projector alongside the text model; an image submitted to `LocalLLM.complete(images=...)` returns a description.

**Files added:**

| File | Purpose |
|---|---|
| `tests/inference/image.png` | **User-provided real image.** Committed to the repo. The test will assert visible-text recovery + a description match. |
| `tests/inference/test_vision.py` | Unit + integration tests for the vision path. |

**Files updated:**

| File | Change |
|---|---|
| `src/inference/profiles.py` | New profile `gemma-4-e4b-vision` — same GGUF + `mmproj-BF16.gguf` projector path. |
| `src/inference/model_downloader.py` | New `ensure_mmproj(repo_id)` that downloads `mmproj-BF16.gguf` from the same Unsloth repo. SHA verification via `huggingface_hub`. |
| `src/inference/local_llm.py` (`LocalLLM` Protocol) | Add `images: list[bytes] | None = None` kwarg to `complete()` and `complete_sync()`. |
| `src/inference/llama_server.py` | Implement vision path: when `images` is non-empty, route message through OpenAI's content-blocks format — text block + base64 `image_url` block per image. |
| `src/inference/llama_server_pool.py` | Profile dispatch: vision queries trigger spawn of the `gemma-4-e4b-vision` profile (mmproj-loaded subprocess), distinct from the text-only one. LRU eviction may unload the text profile if the user's `MAX_LOADED_MODELS=1`. |
| `justfile:install-llama-server` | Also calls `ensure_mmproj(...)` on first run (eager download). |
| `.env` + `.env.example` | New keys: `LLAMA_SERVER_VISION_MODEL=gemma-4-e4b-vision` (default; settable to other profiles in PR 3+). |
| `src/llm.py:_flatten_message_for_local` | Stop dropping `BinaryContent` blocks; instead, extract their bytes and pass to `complete(images=[...])`. |

**Validation gate before merging PR 2:**
- Submit `tests/inference/fixtures/test_image.png` to `LlamaServerLLM.complete()` with prompt `"Describe what's in this image."`. Assert the response is non-empty and mentions a recognizable feature of the image (the test will use a known fixture, so the assertion can be specific).
- Submit a receipt-PDF page-image. Assert the merchant name comes back. (User supplies the receipt image too.)
- Confirm subprocess for the vision profile launches with both `--model` and `--mmproj` flags (peek at the launch command via `LlamaServerPool.spawn_command()` test helper).
- Confirm LRU eviction works: with `MAX_LOADED_MODELS=1`, querying vision after a text query unloads text and loads vision; querying text again unloads vision and reloads text.
- **End-to-end summarize check:** `just walk` over a folder containing one image file (the user's fixture) AND one receipt-PDF. The resulting T3 summary markdowns must contain image-derived content (visible text from the image, not just filename metadata). This validates the `_flatten_message_for_local` wiring works at INGEST time, not just `/generate`. Both T3 summarize and the answer step share `LocalAgent.run`, so this also pre-validates the answer-side path that PR 3 fully wires.

**Estimated size:** ~250 LOC net change.

---

### PR 3 — Wire vision into the answer step

**Goal:** vision-bearing T3 calls (PDF page renders, image files) actually get the images at answer time. Currently they're dropped silently with a one-time warning.

**Files updated:**

| File | Change |
|---|---|
| `src/llm.py:LocalAgent.run/run_sync` | When the message list contains `BinaryContent` blocks AND the active profile supports vision, pass them through to `LlamaServerLLM.complete(images=...)`. Otherwise (text-only profile), keep the existing drop-with-warning. |
| `src/answer.py:answer_question` | Image-bearing T3 calls (PDF/image hits) get rendered page bytes routed via the new `images=` kwarg. The `_flatten_message_for_local` helper from PR 2 does the actual extraction. |
| `tests/test_mlx_smoke.py` (already renamed scope-wise to "local-backend smoke" but kept name) | Unblock the `test_mlx_summarize_image` test — it currently passes BUT silently drops images. Update assertion to require non-trivial image-derived content in the FileSummary. |
| `Plans/Future Plans.md` (Plan #17 Part B notes) | Update the "image-bearing T3 falls back to text-only" footnote — now wired. |
| Docs: `docs/inference.md` (new in PR 1, expanded in PR 3) | Cover the dual-profile behavior, how to swap vision models, how to add Qwen2.5-VL as opt-in. |

**Validation gate before merging PR 3:**
- `just sync --include-data` over a folder containing one image-only PDF (e.g., a scanned receipt where text extraction yields nothing). The T3 summary should now contain content from the image, not just file metadata.
- Compare the summary quality side-by-side with the cloud OpenRouter path. Should be within striking distance for receipts.
- Smoke test: ask "what's the merchant on this receipt?" against an image-only PDF, confirm the merchant name comes back from the local model.

**Estimated size:** ~150 LOC net change.

---

## Bundling story (Plan #10 future)

Today's `just install-llama-server` recipe downloads the platform-appropriate binary from llama.cpp's GitHub releases:
- **macOS Apple Silicon** → `llama-bXXXX-bin-macos-arm64.zip`
- **macOS Intel** → `llama-bXXXX-bin-macos-x64.zip`
- **Linux x86_64** → `llama-bXXXX-bin-ubuntu-x64.zip`
- **Windows x86_64** → `llama-bXXXX-bin-win-cuda-x64.zip` or `-cpu-x64.zip`

Extracts to `<APP_DATA_DIR>/bin/llama-server`. The discovery code looks for the binary in this order:
1. `LLAMA_SERVER_PATH` env var
2. `<APP_DATA_DIR>/bin/llama-server` (where `install-llama-server` puts it)
3. `<bundled .app resources>/bin/llama-server` (Plan #10)
4. `llama-server` on `PATH` (developer convenience)

When Plan #10 (self-contained packaging) ships, the `.app` build pipeline runs the same download recipe at build time and stages the binary into `<Magpie.app>/Contents/Resources/bin/`. End users who install Magpie.app get the binary for free — no separate install step. Discovery (3) handles them.

This is the answer to "does brew block bundling" — no, because we don't use brew. The download mechanism is uniform across dev and prod.

---

## Migration impact for existing users

After PR 1 merges (still on `llama-server` branch — not yet on `main`), users on `ingestion-rules` who pull and rebuild need to:

1. `just install-llama-server` (downloads the binary, ~30 MB)
2. `just install-llama` no longer exists — its old mention in their muscle memory will fail with "recipe not found"
3. Re-run `just sync` if they want to re-summarize anything (existing summaries stay valid; only re-summarized files use the new path)

After PR 2 merges, users get vision capability automatically — first vision query downloads the mmproj projector (~946 MB) eagerly during install (not lazily on first use, per the locked decision).

After PR 3 merges, T3 image-bearing calls use vision automatically. Users see better summaries for receipts / scanned PDFs / image files without changing anything in their workflow.

---

## Risks

1. **`<|think|>` token survives `--jinja` rendering — unverified.** PR 1's smoke test must confirm. **Likely outcome:** works fine — `--jinja` renders the GGUF's embedded chat template over the message list, and `<|think|>` inside system-message content is just text that passes through. **If it doesn't:** the fix is NOT switching to `/v1/completions` (raw, no chat template) — that's a much bigger rewrite because every call site assumes chat format with system/user/assistant roles. The right fallback is to inject the thinking token **after** the chat template is applied, by intercepting the rendered prompt and prepending the token before sending. llama-server exposes this via the `prefill` parameter on `/v1/chat/completions` in newer builds; if not available on b5400, we add a string-rewrite step on the rendered template. Either way, message construction stays in chat-format. Document the chosen path in PR 1 if the smoke test forces the fallback.
2. **Streaming + structured output don't compose.** Current code already handles this — `stream()` is `/generate`-only; `LocalAgent.run` is non-streaming. PR 1 keeps that boundary.
3. **Subprocess port collisions.** If a previous run left an orphan process on port 9100, the next spawn fails. Pool manager picks the next available port automatically (port + 1, retry). The atexit handler should prevent this in practice.
4. **Binary version skew at startup.** Hard-fail at startup with a clear message if `llama-server --version` is below `LLAMA_SERVER_MIN_VERSION`. User runs `just install-llama-server` to upgrade.
5. **Vision quality on Gemma 4 E4B (the load-bearing claim of PR 2).** If receipts come back garbled, falling back to OpenRouter / Moonshot for image-heavy T3 is the escape hatch. We don't lose it — `LLM_PROVIDER` still lets users flip to cloud.
6. **mmproj download fails behind a firewall.** The model_downloader reuses `huggingface_hub` which already handles this. Surface the error clearly; don't silently fall back to text-only.
7. **macOS Gatekeeper on the downloaded llama-server binary.** First run may show "cannot verify developer." The `just install-llama-server` recipe runs `xattr -d com.apple.quarantine <bin>` automatically on macOS so users never see the dialog. README documents this happens for transparency. For Plan #10, the eventual notarized .app removes the issue entirely.

8. **mmproj's 946 MB download is a long pause on slow connections.** PR 2's `install-llama-server` recipe must print a clear "downloading mmproj-BF16.gguf (~946 MB) — this may take several minutes on slow connections" message before kicking off the download, and stream `huggingface_hub`'s progress bar. Don't let this look like the install hung.

---

## Test plan

### PR 1 — text only

- **Unit (mocked):** pool spawn / health / shutdown cycle. HTTP client request format (verify `/v1/chat/completions` body matches OpenAI shape). `complete_sync` does not raise inside an event loop.
- **Integration (gated by `RUN_LLAMA_SERVER_TESTS=1` + binary):** real text completion. Real streaming yields ≥ 2 chunks. `complete_sync` returns the same string as `await complete()` for the same input + temperature=0.
- **Smoke (manual, before merge):** `just sync` parity with previous behavior on a known corpus.

### PR 2 — vision plumbing

- **Unit:** mmproj download path. Profile dispatch: vision query routes to vision profile.
- **Integration (gated):** `complete(images=[user_test_image_bytes], prompt="Describe...")` returns non-empty content with at least one expected keyword (assertion uses the user's known fixture).
- **LRU eviction:** with `MAX_LOADED_MODELS=1`, alternating text + vision queries each kill+respawn the appropriate subprocess.

### PR 3 — answer-step integration

- **Integration (gated):** known image-only PDF (provided by user) round-trips through `just sync` and the resulting T3 summary contains image-derived content.
- **End-to-end:** ask a vision-shaped question via `just run-magpie`, confirm answer correctness against the user's image.

User provides the test image fixture(s); chat-test prompts I write.

---

## What gets removed in this work

- `llama-cpp-python` from `pyproject.toml`
- `src/inference/local_llm.py:LlamaCppLLM` (the class, ~200 LOC)
- `tests/inference/test_local_llm_integration.py` (replaced by `test_llama_server_integration.py`)
- `just install-llama` recipe (replaced by `just install-llama-server`)
- README's Metal/CUDA `CMAKE_ARGS` matrix
- `LOCAL_N_GPU_LAYERS` env var (replaced by per-profile `ngl`)

---

## Sequencing within this session

1. Write spec (this file). ✅ Done.
2. Commit spec on `llama-server` branch.
3. Implement PR 1 → tests pass → smoke pass → commit + push.
4. Implement PR 2 → tests pass (need user's image at fixture path) → commit + push.
5. Implement PR 3 → tests pass → commit + push.
6. Final state: `llama-server` branch carries all three commits. Ready to merge into `ingestion-rules` when validated.

---

*End of spec.*
