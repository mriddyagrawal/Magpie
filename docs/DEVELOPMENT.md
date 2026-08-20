# Development

Everything needed to run Magpie from source, swap LLM backends, and cut a release.
For what Magpie *is* and how to install the packaged app, see the [README](../README.md).

---

## Architecture

Four processes ship in the app:

```
Magpie.app
└─ Tauri shell ── Rust supervisor: spawns children, picks ports, global shortcut
   ├─ WebView ─── React UI (in-process, not a separate OS process)
   ├─ magpie-sidecar ── Python / FastAPI, ~40 endpoints    :8765 (dynamic)
   │   ├─ in-process models: MiniLM, BM25, ColPali, cross-encoder
   │   └─ llama-server ── spawned subprocess, local inference  :9100+
   └─ qdrant ──── bundled Rust binary, vector database    :6433 + gRPC
```

The Rust shell contains no product logic — it supervises processes, pre-picks free
ports (both Qdrant HTTP *and* gRPC, to avoid colliding with other Qdrant-shipping
apps), reaps orphans from prior crashes, and owns the global hotkey. The React UI
talks only to the sidecar over HTTP; it never touches Qdrant or an LLM.

In a **packaged build**, Tauri spawns the bundled `magpie-sidecar` PyInstaller
binary and the bundled `qdrant` binary, both declared as `externalBin` in
`tauri.conf.json`. In **dev**, Tauri does *not* start Qdrant — you run
`just qdrant-up` yourself.

---

## Prerequisites

```bash
# Python deps (uv manages the venv)
just sync-environment

# Local vector database — one-time ~30 MB download
just qdrant-install

# Rust toolchain, for Tauri
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# Frontend deps
cd frontend && pnpm install
```

## Dev loop

Three terminals:

```bash
just qdrant-up                                       # 1 — vector DB on :6433
uv run uvicorn src.server:app --port 8765 --reload   # 2 — backend, hot reload
cd frontend && pnpm tauri dev                        # 3 — Vite + Rust shell
```

Magpie hides on focus loss, including in dev — so editing code *will* hide the
window. `⌥Space` brings it back.

## Tests

```bash
uv run pytest tests/ -q
```

> **Note:** CI does not run the test suite, and several files have rotted as a
> result — expect pre-existing failures unrelated to your change. Diff the failure
> set before and after your work rather than trusting a green/red summary.

---

## Vector database

Magpie supports exactly one Qdrant shape: **the real Rust binary on localhost.**

```bash
just qdrant-install    # download
just qdrant-up         # start on :6433
just qdrant-status
just qdrant-down
```

Port 6433 is deliberately not Qdrant's default 6333 — that avoids colliding with
other apps that bundle their own Qdrant. Override with
`QDRANT_CLUSTER_ENDPOINT=http://localhost:<port>`; the host **must** resolve to
loopback or Magpie exits at startup. Remote clusters and the embedded Python shim
both existed earlier and were removed in 2026-05: remote broke the privacy
promise, and the shim silently disabled quantization and payload indexes.

Two collections: `summaries` (dense + sparse, file-level *and* CSV row-level
points) and `fast_tier` (ColPali multi-vectors, int8-quantized).

**Qdrant stores vectors and a source path — nothing else.** Summary prose is
re-read at query time from `<APP_DATA_DIR>/summaries/*.md` via the manifest. This
keeps payload size down at scale, and means `manifest.json` is the real hub
joining a file on disk to its summary and its Qdrant points.

---

## Indexing tiers

`src/router.py` decides what each file deserves; `src/ingest/walker.py` runs it.

| Tier | LLM? | For |
|---|---|---|
| **T0** | No | Files too big to embed. Registers filename + first 2 KB; real content comes from ripgrep at query time |
| **T1** | No\* | File *is* the content — small text, code, JSON, YAML. \*The CSV path does call an LLM, plus per-row points |
| **T2** | No | Text inside a container — PDF, DOCX, XLSX. Extracted verbatim |
| **T3** | **Yes** | Receipts, contracts, scanned short PDFs. Structured `FileSummary` |
| **T4** | Local only | Scanned pages and images → ColPali page vectors. Never goes to cloud |

Only T3 (and T1's CSV variant) ever calls an LLM. The router's job is keeping
files *out* of T3. Everything else — walking, extraction, ColPali, embedding — is
local regardless of provider.

```bash
uv run python -m src.ingest <path> --help    # run the walker directly
uv run python -m src.router <file>           # inspect one file's routing decision
```

---

## LLM providers

Five providers, all sharing identical prompts, schemas, and retrieval logic.

| Provider | Notes |
|---|---|
| `openrouter` *(default)* | OpenAI-compatible gateway; any model they front |
| `moonshot` | Moonshot Kimi |
| `ollama` | Local Ollama daemon, OpenAI-compatible |
| `local` | `llama-server` subprocess + GGUF weights. No network |
| `magpie-cloud` | Hosted proxy in `server/`; invite-code auth, prompts server-side |

### How the provider is chosen

**`settings.json` wins. `LLM_PROVIDER` is only a fallback.**

Resolution order in `src.llm.active_provider()`:

1. `<APP_DATA_DIR>/settings.json` — what the user picked in **Settings → Search & AI**
2. `LLM_PROVIDER` env var — only when the settings layer is unavailable
3. Hardcoded `openrouter`

This changed on 2026-05-08. Before that, env won absolutely, which meant a
developer's `.env` silently overrode the user's choice in the UI. **Editing `.env`
will not change the provider of a running app** — change it in Settings, or edit
`settings.json` directly.

### Structured output: local is stricter than cloud

This is the opposite of what you'd expect, and the opposite of what earlier docs claimed.

- **Local is hard-constrained.** `LocalAgent` sends
  `response_format={"type":"json_schema", strict:true}` to llama-server, which
  compiles the Pydantic schema to **GBNF** and enforces it token-by-token. The
  model physically cannot emit invalid JSON or stray prose. Because the constraint
  lives in the sampler rather than the weights, this survives a model swap.
- **Cloud is prompt-based.** `response_format` is *disabled* for OpenRouter
  (`supports_json_schema_output=False`, `supports_json_object_output=False`),
  because OpenRouter routes free Gemma traffic to Google AI Studio, which silently
  rejects both variants and returns a malformed completion. Cloud relies on prompt
  guidance plus `parse_json_with_repair`.

If you add a direct provider integration (Anthropic, OpenAI), restore the profile
flags for it — those *can* honor `response_format`.

---

## Local inference

`LLM_PROVIDER=local` spawns `llama-server` subprocesses and routes every LLM call
through their HTTP `/v1/chat/completions`. The pool spawns on demand,
health-checks, idle-evicts after 10 minutes, and kills children at exit.

### Install

```bash
just install-llama-server
```

Downloads the right binary for your platform into `<APP_DATA_DIR>/bin/`, strips
macOS quarantine, verifies the version, and pre-fetches the vision projector.
Skip the projector with `SKIP_MMPROJ_DOWNLOAD=1`.

| OS | Arch | GPU variants |
|---|---|---|
| macOS | arm64, x86_64 | `metal` (built into every macOS build) |
| Linux | x86_64, arm64 | `cpu`, `vulkan` |
| Windows | x86_64 | `cpu`, `vulkan`, `cuda-12.4`, `cuda-13.1` |

Defaults are `metal` on macOS and `cpu` elsewhere. Override with
`LLAMA_SERVER_GPU=vulkan` (etc.).

> **Not bundled in the installer.** `install_llama_server` is reachable only via
> `just` / `python -m`, so packaged builds have no local inference and no way to
> add it. Settings → Local reports this rather than failing cryptically.

### Model and tunables

Default `unsloth/gemma-4-E4B-it-GGUF` at `Q5_K_XL` (~6.7 GB), downloaded to
`<APP_DATA_DIR>/cache/hub/` on first inference.

```bash
LOCAL_MODEL=unsloth/gemma-4-E4B-it-GGUF   # HF GGUF repo
LOCAL_QUANT=Q5_K_XL                       # Q4_K_XL ~5.1G / Q5_K_XL ~6.7G / Q6_K_XL ~7.5G / Q8_K_XL ~8.7G
LOCAL_N_CTX=8192
LOCAL_TEMPERATURE=0.7

LLAMA_SERVER_PATH=                        # empty = auto-discover
LLAMA_SERVER_MIN_VERSION=b9049            # hard-fail if older — must support gemma4
LLAMA_SERVER_BASE_PORT=9100               # NOT 8765 (that's the sidecar)
LLAMA_SERVER_MAX_LOADED_MODELS=1          # 1 = sequential, LRU eviction
LLAMA_SERVER_IDLE_TIMEOUT_S=600
LOCAL_MMPROJ_VARIANT=BF16
```

**Changing model family** also requires a filename pattern in
`src/inference/model_downloader.py` (`_filename_for` / `_mmproj_filename_for`),
which currently hard-raises for any repo other than Unsloth's Gemma 4.

Gemma 4 E4B is natively multi-modal: one set of weights plus `mmproj-BF16.gguf`
(~946 MB) as image encoder. Both load into one subprocess — text-only calls run at
full speed since the projector isn't in the forward pass. Set
`LLAMA_SERVER_TEXT_MODEL=gemma-4-e4b-text` to split them and save the projector's
RAM, at the cost of a ~25–30 s swap when alternating workloads.

---

## Where Magpie writes

```
<APP_DATA_DIR>/            macOS: ~/Library/Application Support/Magpie
                           Linux: ~/.local/share/Magpie
                           Windows: %LOCALAPPDATA%\magpie\Magpie
  manifest.json            the hub: file → summary → index state
  summaries/*.md           tier output; the actual searchable text
  qdrant_storage/          vectors
  cache/hub/               HuggingFace weights (redirected off the shared cache)
  cache/fastembed/         MiniLM + BM25 ONNX weights
  settings.json            provider, top_k, theme
  secrets.json             API keys, mode 0600
  indexing_rules.json      folders, categories, exclusions
  logs/                    bootstrap + LLM session logs
```

Override the root with `MAGPIE_DATA_DIR` — useful for isolated test runs.

> `fastembed` ignores `HF_HOME` and resolves its own cache from
> `FASTEMBED_CACHE_PATH`, defaulting to the OS temp dir. `src/manifest.py` pins it
> under `APP_DATA_DIR` and migrates any pre-existing temp copy, so the two
> always-loaded models don't sit somewhere the OS periodically deletes.

---

## Packaging and release

```bash
just download-qdrant    # fetch the Qdrant binary for this platform
just build-sidecar      # PyInstaller → frontend/src-tauri/binaries/
just build-app          # Tauri bundle
just build              # all three
```

`build_sidecar.py` bundles `src/server.py` with torch, transformers, and
sentence-transformers. **Keep every `print()` in it 7-bit ASCII** — Windows
runners use a cp1252 stdout encoding, and a single non-ASCII character raises
`UnicodeEncodeError` before PyInstaller starts.

### Cutting a release

Push a `v*` tag. `tauri-action` builds, drafts a GitHub Release, and attaches the
installers. Pushes to `main` only validate compilation and upload artifacts.

```bash
git tag -a v0.1.0-beta.2 -m "..." && git push origin v0.1.0-beta.2
```

The release is created as a **draft** — publish it manually after installing it
yourself.

### Signing

Currently unsigned. The six Apple env vars are **commented out** in
`build.yml` — that is deliberate. GitHub Actions resolves an unset secret to an
empty *string*, not an absent variable, so passing `APPLE_CERTIFICATE: ""` makes
Tauri run `security import` against an empty certificate and the macOS build dies.
Uncomment them only once all six secrets exist; a partial set fails the same way.

The bundled OpenRouter key is written from `secrets.OPENROUTER_BUNDLED_KEY` before
the sidecar build (it must run first — `--add-data src:src` is what pulls the file
into the bundle). It ends up extractable inside the shipped binary, so it must
stay a throwaway on a spend cap.

### Linux

Not built for the beta. The Linux job hung for 4h50m with no error: the Rust
compile finished in ~4 minutes, `.deb` bundled in 16 s, and then Tauri's **rpm
bundler** sat silent until the job ceiling. It chokes on this app's payload — a
~377 MB PyInstaller sidecar plus a 91 MB Qdrant binary, both already-compressed
blobs it re-compresses whole. Building `--bundles deb,appimage` (excluding rpm)
completes in ~19 minutes. The matrix entry is commented in `build.yml`.

---

## The CLI

`cli/notspotlight` provides an `ns` terminal REPL. **It is frozen and partially
broken** — the tag `v0.1.0-cli` marks its last working state (2026-05-01), taken
deliberately "before path-portability work begins," and it was never brought
forward.

What still works: the query path. It reads the same Qdrant collections and
manifest the app writes, so `ns` answers questions against the app's live index.

What doesn't:

- `ns --sync` targets `<APP_DATA_DIR>/Test Content`, which doesn't exist, and
  drives the legacy 2-tier pipeline rather than the 5-tier walker the app uses.
- `.suggest` reads `<APP_DATA_DIR>/Test Summaries`, renamed to `summaries/` in May.
- **`ns --reset` deletes the app's live index** — summaries, manifest, and both
  Qdrant collections — while its prompt describes directories that no longer exist.
- Answers differ from the app's: `/query/stream` always reranks, the CLI doesn't.

`src/daemon/` (~1,100 lines) was built to accelerate the CLI and has never had a
caller. Both are candidates for removal.

---

## Gotchas

- **Qdrant is not started by Tauri in dev.** Run `just qdrant-up` or every query fails.
- **`.env` does not control the provider.** Settings does.
- **`/query` and `/query/stream` disagree**: streaming always reranks, non-streaming
  never does. Same question, different results.
- **Four models load locally on every query** — MiniLM, BM25, ColPali, cross-encoder —
  regardless of provider. Cloud mode swaps only the *reasoning* model.
- **torch exists solely for ColPali and the reranker.** `fastembed` is ONNX and
  needs none of it. That's most of the bundle size, for two optional features.
