# Feature Inventory — 2026-04-26

> One-page glossary of every behavior the system currently exhibits. Skim
> to understand the capability surface without reading 200 lines of
> shipped log. Each row: a single-word tag + a one-line description.
> Cross-references point at the detailed entries in
> [IO - shipped_20Apr26.md](IO%20-%20shipped_20Apr26.md) and the
> [Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md).
>
> **Updated 2026-04-26:** added hidden-path policy, secret-skip patterns,
> three ingest modes (default / `--force` / `--rebuild`), walker auto-push,
> fast-tier orphan cleanup, T4 GIF support.

---

## A. Ingest — getting files into the index

| Tag | What it does |
|---|---|
| `walker` | Recursively discovers files under a path, dispatches each to a tier, writes summaries + manifest rows. Entry: `python -m src.ingest <path>`. |
| `peek` | Cheap pre-routing inspection of each file (page count, text density, image dims, content sample) — costs ~10–50 ms per file, never opens the LLM. |
| `router` | Pure-function decision: given peek + folder-config + budgets, chooses tiers `T0..T4` per file. |
| `tiers` | Five processing lanes — `T0` register-only (huge files, ripgrep at answer time), `T1` direct embed, `T2` extract-then-embed, `T3` LLM summary, `T4` ColPali visual. |
| `criticality` | Auto-upgrades sensitive files (currency / legal / ID patterns in peek text) from `normal` to `critical` so they pick up `T3+T2`. |
| `nasconfig` | Folder-level overrides via `.nasconfig.yaml` (accuracy tier, T4 budget, colpali on/off). |
| `nasignore` | Cascading gitignore-style rules from `.gitignore` / `.nasignore` files plus a hardcoded defaults list. |
| `defaults` | Hardcoded ignores for VCS dirs, build artifacts, OS cruft, lockfiles, system temps, OS caches, trash dirs, OOXML decomposition (`*_extracted/{ppt,word,xl}/media/`), and **common-secret filenames** (`.env`, `.env.*`, `.npmrc`, `.netrc`, `.pgpass`, `.git-credentials`, `id_rsa[.*]`, `id_ed25519[.*]`, `id_ecdsa[.*]`, `id_dsa[.*]`, `*.pfx`, `*.p12`). Cannot be overridden by user config. |
| `hiddenpaths` | Three-level dot-handling: (1) dot-folders pruned during walk via `os.walk` (never even listed), (2) leaf dotfiles default-skipped except a small `_USEFUL_DOTFILE_NAMES` allowlist (`.bashrc .zshrc .vimrc .gitconfig .tmux.conf` etc.), (3) per-folder opt-in via `.nasconfig.yaml`'s `include_dotfiles: true` lets the walker descend dot-folders + accept all dotfiles in that subtree (built-in secret defaults still apply). |
| `siblingdensity` | Structural rule — a folder with ≥15 images and 0 documents is treated as an asset library; its images skip the index regardless of name. |
| `thumbnails` | Skip images smaller than 600 px in either dimension AND smaller than 50 KB on disk. |
| `prune` | Walker drops manifest rows whose source files vanished (and deletes their summary markdowns). Mirrored on the fast tier (see `fastorphan`). |
| `fastorphan` | At end of every ingest, `fast_tier` ColPali points whose source path no longer exists in the manifest are deleted. Closes the zombie-data drift after `--rebuild`, asset-library skips, file deletions. |
| `autopush` | Walker auto-runs Stage 2 (push to Qdrant) at the end of every ingest. `--no-push` opts out for offline / dry-run cases. |
| `modes` | Three mutually-exclusive modes: default (append, skip-unchanged) / `--force` (re-encode every file under root, including T4) / `--rebuild` (drop both Qdrant collections + clear manifest under root, then re-ingest from scratch). |
| `colpali` | Visual late-interaction indexing — renders pages as images, encodes via ColPali / ColSmolVLM, stores multi-vectors in `fast_tier` Qdrant collection. |
| `pooling` | Patch pooling at `pool_factor=2` for `.pptx` (whitelisted in `tier4.POOL_SAFE_EXTS`); off elsewhere. |
| `toc` | Bookmark-based table of contents extracted via `pymupdf.get_toc()` and prepended to PDF text → ends up in the summary embedding so section names are findable. |
| `fallback` | Secondary LLM provider via `FALLBACK_LLM_PROVIDER` env var; T3 falls back on this when the primary raises a non-retryable error. |
| `manifest` | Persistent JSON of every processed file — size, summary path, fast-tier state, router audit fields. |
| `dimcheck` | Asserts the configured embedding model's dim equals the stored collection's dim; raises `DenseDimMismatchError` with re-index instruction on mismatch. |
| `extractors` | Native handlers for `.pdf` (pypdf+pymupdf, OCR fallback as page renders), `.docx` (python-docx), `.xlsx` (openpyxl), `.pptx` (python-pptx, slide-by-slide), `.html` (trafilatura with utf-8 fallback for SPAs), `.ipynb` (json cell parser), `.csv` (raw text), `.log` (text), and `.alt` video sidecars. T4 visual lane handles `.png .jpg .jpeg .webp .gif` (GIF → first frame via PIL). |
| `alt` | Stage 3 video pathway — `.alt` YAML sidecars (source / summary / scenes / themes) → transcoded into one whole-file summary plus one summary per scene. Per-scene Qdrant points keyed by `<file>#scene:MM:SS` so search returns timecoded hits. |
| `videoindex` | `python -m src.stage3 <dir>` — Stage 3 walker; finds every `.alt` under a root, transcodes + writes summaries, registers per-scene manifest rows. |
| `legacy` | `python -m src.stage1.summarize <dir>` — original walker that routes every file through T3 (kept for benchmark comparison vs the router-driven walker). |
| `fastonly` | `python -m src.stage1_fast.index <dir>` — fast-tier-only batch indexer; renders + encodes pages without touching the summary tier. |
| `routerexplain` | `python -m src.router <file\|dir>` — inspect what tier a file (or every file under a dir) would route to. No writes, no LLM. Useful for debugging routing policy. |
| `gpudetect` | Auto-detects CUDA / MPS / CPU at startup; selects the right ColPali model (ColQwen2.5 on big GPU, ColSmolVLM-500M on CPU/small GPU) and batch size. |
| `concurrency` | Walker uses an `asyncio.Semaphore` (default 4) to bound concurrent file processing; `--concurrency N` tunable per run. |
| `429retry` | T3 calls retry on HTTP 429 with exponential backoff parsing the server's `retryDelay` hint when present (default 6 retries). |
| `repair` | Local-model output that fails strict JSON parsing is run through progressive cleanups (strip code fences, extract first `{...}` block, retry). Falls back to a default instance only when caller passes one. |

---

## B. Search — finding the right files

| Tag | What it does |
|---|---|
| `rewrite` | LLM query expansion — `.rewrite on/off`. Generates a dense query string + 5-12 keywords including synonyms / paraphrases / verbatim identifiers. |
| `classify` | Pure-regex query classifier — distinguishes `LIST_ALL` (enumeration) from `GENERAL` (factoid / conceptual). Drives downstream knobs. |
| `widening` | LIST_ALL queries auto-widen `top_k` from 5 → 20 (adaptive). Caller's explicit value always wins if larger. |
| `dense` | Sentence-transformers MiniLM-L6 384-dim embedding; default for both summary and chunk lookups. |
| `sparse` | BM25 sparse vector via fastembed; complements dense for exact-match tokens. |
| `fastsearch` | ColPali MaxSim retrieval against `fast_tier` collection; collapses multiple page-hits per file to best-page. |
| `rrf` | Reciprocal-rank fusion of summary-tier + fast-tier results; `RRF_K=60`. |
| `rerank` | Cross-encoder (`ms-marco-MiniLM-L-6-v2`) second-pass scoring — `.rerank on/off`. Auto-suppressed for `LIST_ALL` queries (regresses enumeration). |
| `searchcli` | `python -m src.stage2 search "<question>" [--top-k N] [--rewrite]` — non-interactive search command; same retrieval path as the REPL but scriptable. |
| `scenehits` | Search results from `.alt` files include scene-level timecodes (`#scene:MM:SS` payload anchors) so the answer stage knows which segment matched. |

---

## C. Answer — turning retrieved files into a grounded answer

| Tag | What it does |
|---|---|
| `read` | Per-file content-block builder — text PDFs → text, images → bytes, scanned PDFs → page renders, .alt files → structured YAML. |
| `lazychunk` | Within-file keyword search at answer time — for long PDFs, picks pages matching the rewriter's keywords instead of the dumb first-25k-chars cut. |
| `tocfilter` | Excludes TOC-shaped pages from lazy chunking (otherwise they outscore content pages on keyword density). |
| `dualpages` | Page anchors on lazy chunks emit `## PDF page N (book p. M)` so citations carry both the digital page and the printed page. |
| `supplement` | T3 LLM summary attached as supplementary content for any file that has one — rescues scanned PDFs where raw extraction is empty. |
| `grounding` | Five strict rules in the system prompt: no training-data leakage, no scope expansion, no decorative citations, no source conflation, faithfulness over completeness. |
| `synonyms` | One general principle (no enumerated examples) — bridge synonyms / abbreviations / paraphrases / units when the file covers the user's concept under a different name. |
| `enumeration` | LIST_ALL queries get an extra prompt rule telling the LLM to be exhaustive — include every plausibly-fitting file, hedge borderline cases rather than dropping. |
| `unicode` | Math output prefers Unicode glyphs (∂ ∫ ∑ ∇ × · α θ ⇒ ≤ ≥); LaTeX `$...$` reserved for genuinely structural cases. |
| `whitespace` | Path-citation filter is whitespace-tolerant + suffix-aware — survives LLM echoing `path  [book pp. X / PDF pp. Y]` with collapsed spaces or %20-encoding. |
| `cite` | Sources_used line shows file paths with optional `[book pp. ... / PDF pp. ...]` suffix, rendered as clickable file:// link plus dim text outside the link tag. |
| `history` | Optional multi-turn conversation context — `.history on/off/clear`. Resolves pronouns ("it", "that course") against prior turns. |
| `fragments` | Path resolver strips `#scene:...` fragments before opening a file, dedupes multiple scene hits from the same `.alt` so the LLM doesn't re-read the bytes N times. |
| `t0ripgrep` | Files routed to T0 (huge CSVs / logs not embedded line-by-line) get answer-time enrichment — `ripgrep` finds query-keyword-matching lines and prepends them to the LLM prompt. Falls back to a pure-Python line scanner when `rg` isn't on PATH. |

---

## D. Ops + UX — running and inspecting the system

| Tag | What it does |
|---|---|
| `repl` | Interactive CLI (`ns` / `notspotlight` / `nas`). Banner shows active LLM + fast-tier model. |
| `dotcmds` | REPL controls — `.rewrite on/off`, `.rerank on/off`, `.top-k N`, `.history on/off/clear`, `.suggest`, `.help`, `.clear`. |
| `disk-usage` | `just disk-usage` — summary of pipeline storage (markdowns + Qdrant + model cache + venv). |
| `fast-tier-files` | `just fast-tier-files` — top-50 fast-tier files ranked by indexed pages (~1 MB/page) — diagnoses storage hogs. |
| `fast-tier-config` | `just fast-tier-config` — live Qdrant collection config; catches silent local-mode quantization gaps. |
| `clean-stale` | `just clean-stale-manifest` — drops manifest rows whose source files don't exist + deletes orphaned summary markdowns. |
| `recover-fast-tier` | `just recover-fast-tier` — rebuilds lost `fast_indexed_at` fields from the live `fast_tier` collection (recovery for the pre-2026-04-25 `mark_summarized` bug). |
| `qdrant-up` | `just qdrant-up / down / status / install` — manages the standalone Qdrant Rust binary (subprocess on `localhost:6333`, data on `/mnt/hardisk/qdrant/`). |
| `ingest` | `just ingest` — runs `python -m src.stage2 ingest` (stage 2 push + orphan cleanup). Auto-fires at the end of every walker run. |
| `force` | `python -m src.ingest <dir> --force` — re-encode every file under this root, including T4 ColPali pages. Threads through to `index_file(force=True)` so the per-tier size-skip honors the walker's intent. Other corpora untouched. |
| `rebuild` | `python -m src.ingest <dir> --rebuild` — DROP both Qdrant collections + clear all manifest entries under this root, then re-ingest from scratch. Use after multi-policy changes or for corruption recovery. Mutually exclusive with `--force`. |
| `nopush` | `python -m src.ingest <dir> --no-push` — skip the auto-Stage-2 push at end. Leaves new summaries with `ingested_at=None`; run `python -m src.stage2 ingest` later to push manually. |
| `pipeline` | `python -m src.pipeline "<question>" [--top-k N] [--rewrite]` — non-interactive answer; same path as the REPL but scriptable. |
| `suggestions` | LLM-generated example questions cached at `Test Summaries/_suggestions.json`; refreshes when manifest size changes; shown in the REPL banner. `.suggest [refresh]` regenerates on demand. |
| `routerinspect` | Verbose ingest output (`-v` flag) prints a per-file decision line: route(s), scores, criticality, t4_cost. Lets you see exactly why a file landed in the tier it did. |

---

## E. Configuration surface

| Env var | Effect |
|---|---|
| `LLM_PROVIDER` | `moonshot` (Kimi via OpenAI-compat) / `openrouter` (multi-LLM via OpenAI-compat) / `ollama` (localhost OpenAI-compat daemon) / `local` (mlx-vlm on Apple Silicon arm64). |
| `FALLBACK_LLM_PROVIDER` | Same set; fires when the primary raises a non-retryable error during T3. |
| `QDRANT_PROVIDER` | `local` (embedded SQLite shim) or `cloud` (Rust server / Cloud, drop quantization gap). |
| `QDRANT_CLUSTER_ENDPOINT` | URL of the Qdrant server (cloud or self-hosted). |
| `QDRANT_API_KEY` | Required for non-localhost endpoints; optional for localhost. |
| `RERANK_MODEL` | Override the cross-encoder used by B4 (default `cross-encoder/ms-marco-MiniLM-L-6-v2`). |
| `OPENROUTER_MODEL` / `MOONSHOT_MODEL` / `OLLAMA_MODEL` / `LOCAL_MODEL` | Per-provider model selection. |
| `QDRANT_HOME` | Where the standalone Qdrant binary + data live (default `/mnt/hardisk/qdrant`). |

---

## F. Utility scripts (not core retrieval, but in-tree)

| Tag | What it does |
|---|---|
| `enrich-offerings` | `src/enrich_offerings.py` — parses a Workday "Find Course Listings" HTML save, joins term-specific offering data (instructor, days, time, building, room, status) into a course CSV. Standalone script; not part of the ingest path. |
| `split-courses` | `src/split_courses.py` — corpus-management utility for the CSV course catalog (splits by some criterion). Standalone script; not part of the ingest path. |

---

## What's NOT in this doc

Behaviors with backlog tags but no shipped code: B2 (HyDE), B5 (hierarchical summaries), B6 (payload filters), B7 (agentic retrieval), B8 (conditional upfront chunking), B9 (citation verification), B10 (vocab-aware T2 templating), B11 (domain-aware rewriter expansion), C1 (filesystem watcher), C4 (MCP server), C5 (pipx wheel), C6 (Tauri shell), D1 (benchmark), D2 (competitors), D3 (license), E2 (Ollama bench), E5 (bundled binary), F1–F4 (file-type coverage), G1–G2 (architecture revisits), H1–H2 (test infra). See [Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md).

When this doc materially diverges from current behavior, rename it
(`IO - features_<DDmonYY>.md`) and write a fresh one alongside.
