# Spec — llama-cpp-python → llama-server migration (vision-capable local LLM)

**Status:** PRs 1 / 2 / 3 shipped on branch `llama-server` 2026-05-07; PR 4 (cross-platform installer) added 2026-05-07 after a real-install validation surfaced cross-platform gaps.

**Author:** Mridul + Claude (planning session 2026-05-07).

**Branch:** `llama-server` (off `ingestion-rules`).

**Ship strategy:** four sequential PRs in this session. Each PR is independently testable; failure in any later phase does not roll back earlier phases.

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
| `LLAMA_SERVER_MIN_VERSION` pin | ~~`b5400`~~ → **`b9049`** (corrected 2026-05-07 post-validation). | b5400 turned out to be a mid-2024 build that predates the `gemma4` model architecture in llama.cpp — model load fails with "unknown model architecture: 'gemma4'". I had no calibrated sense of how many builds llama.cpp ships per day (turns out ~10/day, so b5400 was ~12 months stale). Rule going forward: pin a recent **release**, not an arbitrary "looks recent" tag. |
| Binary install: shell script vs. Python | ~~bash recipe in justfile~~ → **Python module** (`src/tools/install_llama_server.py`), called from a 1-line justfile recipe. PR 4 deviation. | Bash recipe was broken on native Windows shells (no bash, no curl, no unzip on PowerShell), missed Linux-arm64, and broke when llama.cpp switched zip→tar.gz. Python uses stdlib (`urllib`, `tarfile`, `zipfile`) — works on every platform that runs Magpie. |
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

### PR 2 — Vision plumbing (Gemma 4 + mmproj) **[SHIPPED 2026-05-07]**

**Goal:** load the mmproj projector alongside the text model; an image submitted to `LocalLLM.complete(images=...)` returns a description.

**Outcome:** wiring complete. Image-bearing T3 ingest calls now route bytes through the vision profile transparently. Real-spawn integration test gated by `LLAMA_SERVER_VISION_INTEGRATION=1` (skipped by default — first run downloads the ~946 MB projector, slow on bandwidth-limited CI).

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

**Validation gate (PR 2):**
- ✓ 16 unit tests cover `_detect_image_media_type`, `_attach_images_to_last_user`, `LlamaServerLLM._select_profile` (no-images / text-instance / vision-instance / unregistered) and the new `_flatten_message_for_local` tuple return.
- ✓ Real-spawn smoke test in `tests/inference/test_vision.py::test_vision_recovers_visible_text_from_fixture_image` (gated by `LLAMA_SERVER_VISION_INTEGRATION=1`) sends the `image.png` LLM-evaluation diagram and asserts the response contains at least one of its visible labels.
- **End-to-end summarize smoke (manual)**: `just walk` over a folder with one image file (the user's fixture) and one receipt-PDF. T3 summary markdowns should contain image-derived content. Skipped during automated testing because it requires the mmproj download.

**Estimated size:** ~250 LOC net change.

---

### PR 3 — Wire vision into the answer step **[SHIPPED 2026-05-07]**

**Goal:** vision-bearing T3 calls (PDF page renders, image files) actually get the images at answer time. Currently they're dropped silently with a one-time warning.

**Outcome:** PR 2's `_flatten_message_for_local` rewrite already routes image bytes for both T3 ingest AND the answer step (both paths share `LocalAgent.run`), so this PR's job collapsed to: strengthen smoke-test assertions to require non-trivial image-derived content (catching regressions where vision silently falls back to text), add an answer-from-image test that asserts the same image-content gate over the full retrieval+answer pipeline, and refresh docs.

**Files updated:**

| File | Change |
|---|---|
| `tests/test_mlx_smoke.py` | `test_mlx_summarize_image` now requires non-trivial image-derived content when the committed fixture is the image source (regression gate). New `test_mlx_answer_from_image` exercises the full retrieval + answer pipeline against the fixture and asserts visible-label recovery. Both gated by `LLM_PROVIDER=local`. |

**Files NOT updated (already done in PR 2):**
- `src/llm.py:LocalAgent.run/run_sync` — already forwards image bytes via the `images=` kwarg.
- `src/answer.py:answer_question` — calls `LocalAgent.run` so image content from `build_content_blocks` flows transparently.

**Validation gate (PR 3):**
- ✓ `LLM_PROVIDER=local pytest tests/test_mlx_smoke.py::test_mlx_summarize_image` — picks up the committed fixture and asserts at least one of the diagram's visible labels survives into the FileSummary.
- ✓ `LLM_PROVIDER=local pytest tests/test_mlx_smoke.py::test_mlx_answer_from_image` — sends the same fixture to the answer step and asserts the answer mentions visible-text labels (not just file metadata).
- Manual: `just sync --include-data` over a folder containing one image-only PDF (e.g., a scanned receipt). T3 summary should contain image-derived content. Quality should be in striking distance of OpenRouter for receipts.

---

### PR 4 — Cross-platform installer (Python) **[in flight 2026-05-07]**

**Goal:** make `just install-llama-server` work on every platform Magpie runs on, without depending on bash, curl, unzip, find, or xattr being available — only on a working Python 3.11 (which Magpie already requires for the sidecar).

**Why this PR exists.** PR 1 shipped a bash-based installer. Real-install validation on macOS surfaced four bugs (asset format, version regex, version-pin staleness, `head -3` SIGPIPE) — each one a separate first-run failure mode that would have hit Rahul on Linux/Windows the same way. The bash recipe also can't run on native Windows shells (PowerShell / cmd) and silently dies on Linux-arm64 (no case in the platform switch). The deviation here is about **install reliability**, not feature scope: PR 4 doesn't add new user-visible behavior, it makes PR 1's installer actually work for Rahul.

**Deviations from PR 1's plan, justified:**
- ~~`just install-llama-server` is a bash recipe~~ → **Python module called from a 1-line just recipe.** Bash ergonomics on Windows are bad enough (Git Bash users have varying tool availability; PowerShell has neither) that platform-specific recipes would have multiplied. Python stdlib gives us the same logic across every platform with `urllib` / `tarfile` / `zipfile` / `pathlib` / `shutil`.
- ~~`xattr -d com.apple.quarantine`~~ → **shelled out via `subprocess.run([...], check=False)` only on macOS.** No portable Python equivalent and we can't avoid it (Gatekeeper blocks downloaded binaries otherwise). 5 LOC inside an `if sys.platform == 'darwin':` block.
- ~~Implicit "find binary anywhere in extracted tree"~~ → **explicit per-platform expected location** (`build/bin/llama-server[.exe]`) with a fallback rglob. Faster, less error-prone, behaves the same on every OS.

**Files added:**
| File | Purpose |
|---|---|
| `src/tools/__init__.py` | New top-level package for build / install helpers (currently empty; future scripts land here). |
| `src/tools/install_llama_server.py` | Cross-platform installer. Public entrypoints: `download_and_install(version=...)`, `select_asset(os_name, arch, gpu_hint)`, `extract_to(archive_path, dest)`. Module is `python -m`-runnable and importable for tests. |
| `tests/inference/test_install_llama_server.py` | Asset-name selection table-driven tests; archive-extraction round-trip with synthetic tarballs/zips; macOS-only xattr branch test (skipped elsewhere). No real network. |

**Files updated:**
| File | Change |
|---|---|
| `justfile:install-llama-server` | Single line: `uv run python -m src.tools.install_llama_server`. Env vars (`LLAMA_SERVER_VERSION`, `LLAMA_SERVER_GPU`, `SKIP_MMPROJ_DOWNLOAD`) read directly by the Python module. |
| `src/inference/llama_server_binary.py:_BIN_NAME` | `_BIN_NAME` becomes platform-aware (`llama-server.exe` on Windows). Discovery loop unchanged otherwise. |
| `README.md` | Cross-platform install section: per-platform asset table, GPU-variant notes for Linux x86_64 + Windows, troubleshooting one-liners. |

**Asset-selection logic** (the load-bearing decision PR 4 owns):
| OS / arch | GPU hint | Asset name (b9049+) |
|---|---|---|
| Darwin / arm64 | (Metal, baked in) | `llama-bXXXX-bin-macos-arm64.tar.gz` |
| Darwin / x86_64 | (Accelerate, baked in) | `llama-bXXXX-bin-macos-x64.tar.gz` |
| Linux / x86_64 | `cpu` (default) | `llama-bXXXX-bin-ubuntu-x64.tar.gz` |
| Linux / x86_64 | `vulkan` | `llama-bXXXX-bin-ubuntu-vulkan-x64.tar.gz` |
| Linux / x86_64 | `cuda-12.4` / `cuda-13.1` | (build from source — release tarballs are CPU-only on Ubuntu) |
| Linux / aarch64 | `cpu` | `llama-bXXXX-bin-ubuntu-arm64.tar.gz` |
| Linux / aarch64 | `vulkan` | `llama-bXXXX-bin-ubuntu-vulkan-arm64.tar.gz` |
| Windows / x86_64 | `cpu` (default) | `llama-bXXXX-bin-win-cpu-x64.zip` |
| Windows / x86_64 | `cuda-12.4` | `llama-bXXXX-bin-win-cuda-12.4-x64.zip` (+ `cudart-llama-bin-win-cuda-12.4-x64.zip` if user lacks CUDA runtime) |
| Windows / x86_64 | `cuda-13.1` | `llama-bXXXX-bin-win-cuda-13.1-x64.zip` (+ cudart) |
| Windows / x86_64 | `vulkan` | `llama-bXXXX-bin-win-vulkan-x64.zip` |
| Windows / arm64 | `cpu` | `llama-bXXXX-bin-win-cpu-arm64.zip` |

GPU hint set via `LLAMA_SERVER_GPU=cuda-12.4` (etc.). Default per platform is `cpu` for max compatibility. CUDA runtime DLL bundle is fetched alongside on Windows-CUDA paths.

**Validation gate (PR 4):**
- ✓ macOS-arm64: re-run `just install-llama-server`, confirm same outcome as the bash recipe (binary installed + verified, mmproj cached).
- Unit: asset-selection table for every (OS, arch, gpu) combo above.
- Unit: archive extraction round-trip with a synthetic tar.gz + zip containing a fake `llama-server` binary.
- Manual (Rahul follow-up): Linux x86_64 install, Windows + PowerShell install. Documented as a "first-run validation" item in README; not gated in CI because we don't have the runners.

**Estimated size:** ~250 LOC installer + ~150 LOC tests.

---

## Post-validation deviations log (2026-05-07, after first real install)

These are the diff between what PR 1's spec said and what actually shipped. Logged here so future readers don't trust the wrong details:

| Original | Reality | Why |
|---|---|---|
| Pin `b5400` | `b9049` | b5400 (mid-2024) doesn't have the `gemma4` model arch. Model load fails before inference. |
| Asset format `.zip` | `.tar.gz` for macOS / Linux, `.zip` for Windows only | llama.cpp switched its release artifacts to tar.gz on unix-y platforms in the b8000+ range. Python installer (PR 4) handles both. |
| Asset name `llama-bXXXX-bin-macos-arm64.zip` | `llama-bXXXX-bin-macos-arm64.tar.gz` (no schema change, just the extension) | Same release-naming convention; the `bin-` infix is still there. |
| Version regex matches only `bNNNN` | Also accepts `version: NNNN` (bare digits) | Modern macOS builds emit `version: 9049 (sha)` without the `b` prefix. Original regex returned `None`, making the min-version check a silent no-op. |
| `--version` subprocess timeout 10s | 30s (binary helper) / 60s (installer verify) | macOS b9000+ initializes Metal on `--version` (cold cache: 12-15s). 10s false-failed every check. |
| Bash recipe with `find` + `unzip` + `curl` | Python module (`src/tools/install_llama_server.py`) | See PR 4 above. Cross-platform requirement; bash assumed POSIX userland. |
| `thinking=False` was assumed to mean "no thinking" | Plus `chat_template_kwargs.enable_thinking=false` on every request | b9049 + Gemma 4 E4B with `--jinja` auto-enables thinking via the GGUF's chat template. Our `<\|think\|>`-token injection only suppressed the OLD-style thinking; the new template-driven thinking eats the entire token budget and leaves `content` mostly empty (`reasoning_content` gets it instead). The vision integration test caught this: with max_tokens=512, all 512 went to reasoning and content was a 13-token cliff. Fix: thread `thinking` into the request body as `chat_template_kwargs.enable_thinking`, plus a belt-and-suspenders `_extract_content` fallback that surfaces `reasoning_content` if `content` is empty. Spec risk #1 (`<\|think\|>` token survives `--jinja`) was the right *area* but the wrong *direction* — newer builds DO pass it through, but they ALSO add a separate template flag we now have to manage. |

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
