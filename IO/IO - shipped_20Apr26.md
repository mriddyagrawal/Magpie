# Shipped — 2026-04-20

> Companion snapshot to [Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md).
> Captures what actually landed on disk (and in tests) as of this date.
> Use this doc to cross-reference "was this delivered?" — if it's here, the
> answer is yes, with a pointer to the code.

Conventions:
- **Status**: a one-line description of the shipped state + test count where
  relevant.
- **Where**: concrete file paths. Line numbers when they help a reviewer.
- **Why it mattered**: what problem this solved (so we can judge later
  whether the solution aged well).
- **Follow-ups**: open items from [backlog_20Apr26.md](../Plans/backlog_20Apr26.md)
  that extend this piece.

---

## A. Ingest architecture — the router refactor

### A1. Ingest router (`src/router.py`)
- **Status:** Shipped. Pure functions `peek()` + `compute_visual_score()` +
  `compute_sensitivity_score()` + `estimate_t4_cost()` + `decide()`, plus
  `load_nasconfig()` for folder overrides. 37 unit tests green.
- **Where:** [src/router.py](../src/router.py); [tests/test_router.py](../tests/test_router.py).
- **Why it mattered:** Today's pipeline previously sent every file through
  an LLM call regardless of cost-benefit. The router replaces a blanket
  Stage-1 path with deterministic tier dispatch: most files skip the LLM
  entirely, visual files go to ColPali (on GPU), discriminator-heavy files
  still get the LLM summary they need. Projected ingest speedup: 4–6× on
  realistic corpora.
- **Follow-ups:** [B1](../Plans/backlog_20Apr26.md) adaptive query router
  (same *idea*, but query-side); [G1](../Plans/backlog_20Apr26.md) revisit
  one-pass vs two-pass after real benchmarking.

### A2. Five-tier dispatch with tier workers (`src/ingest/`)
- **Status:** Shipped. One module per tier, each exports a clean
  `run(path, source_rel)` contract.
- **Where:**
  - [src/ingest/tier0.py](../src/ingest/tier0.py) — register + on-demand ripgrep for huge files
  - [src/ingest/tier1.py](../src/ingest/tier1.py) — direct embed for code / text / small config
  - [src/ingest/tier2.py](../src/ingest/tier2.py) — extract-then-embed for PDF / DOCX / XLSX
  - [src/ingest/tier3.py](../src/ingest/tier3.py) — LLM summary (existing behavior, now scoped)
  - [src/ingest/tier4.py](../src/ingest/tier4.py) — thin wrapper around `src/stage1_fast/` ColPali pipeline
  - [src/ingest/common.py](../src/ingest/common.py) — hash, render_summary_markdown, title helpers
- **Why it mattered:** Replaces the "every file takes the same path" model
  with "the right path per file type + sensitivity." Tier workers share a
  `TierOutcome` contract so the walker dispatches without branching on
  tier-specific I/O shape.
- **Follow-ups:** [G3](../Plans/backlog_20Apr26.md) multi-tier additive
  execution (e.g. `T3 + T2` for sensitive text-native docs); [F3–F4](../Plans/backlog_20Apr26.md)
  adding more file-type handlers under the same contract.

### A3. Router-driven walker with audit trail (`src/ingest/walker.py`)
- **Status:** Shipped. CLI: `python -m src.ingest <dir>`. Async worker
  pool, lazy LLM-agent construction, semaphore-bounded concurrency,
  manifest prune for deleted files, full summary line.
- **Where:** [src/ingest/walker.py](../src/ingest/walker.py);
  [src/ingest/\_\_main\_\_.py](../src/ingest/__main__.py);
  [tests/ingest/test_walker.py](../tests/ingest/test_walker.py) (7 tests).
- **Why it mattered:** The seam between "router decides" and "tier runs"
  needs a real orchestrator. This one is defensively written — LLM agent
  only instantiated when a T3/T4 file is actually encountered, so corpora
  of pure code / text never need an API key in `.env`.
- **Follow-ups:** [C1](../Plans/backlog_20Apr26.md) filesystem watcher to
  turn this from a one-shot command into a daemon; [D4](../Plans/backlog_20Apr26.md)
  audit for REPO_ROOT assumptions before pipx packaging.

### A4. Manifest audit extension (`src/manifest.py`)
- **Status:** Shipped. `Entry` grew eight new fields (`routes`,
  `visual_score`, `sensitivity_score`, `t4_cost_mb`, `t4_cost_s`,
  `criticality`, `criticality_source`, `skip_reason`). Backward-compatible
  loader drops unknown keys rather than crashing on downgrade.
- **Where:** [src/manifest.py:44-75](../src/manifest.py#L44-L75);
  `mark_routed()` mutation method.
- **Why it mattered:** Every routing decision becomes grep-able per file.
  Answers the "why did this bank statement go to T2 instead of T3+T2?"
  support question in O(1) without re-running the router.
- **Follow-ups:** `ns why <file>` CLI to pretty-print a manifest entry
  (not yet built; captured as a nice-to-have).

### A5. `.gitignore` / `.nasignore` + built-in defaults (`src/ingest/ignore.py`)
- **Status:** Shipped. Cascading user rules + hard-coded defaults for
  `node_modules/`, `.git/`, `__pycache__/`, `.venv/`, `venv/`, `target/`,
  `build/`, `dist/`, IDE caches, OS cruft, lock files, and our own
  `Test Summaries/`. 9 unit tests green. Built-in defaults cannot be
  un-ignored by user rules (safety rail). Run summary reports
  `ignored=N`.
- **Where:** [src/ingest/ignore.py](../src/ingest/ignore.py);
  [tests/ingest/test_ignore.py](../tests/ingest/test_ignore.py).
- **Why it mattered:** Closed the single biggest operational gap vs
  comparable tools. Demo: a 9-file corpus that naïvely would have
  included `node_modules/*` and `dist/*` now ingests exactly 2 files
  (`src/app.py`, `README.md`) with 4 ignored — zero effort from the user.

### A8. Adaptive query router — list/enumeration top_k widening (B1)
- **Status:** Shipped 2026-04-24. Pure-regex classifier; no LLM, no network.
- **Where:**
  - [src/stage2/query_classify.py](../src/stage2/query_classify.py) — `QueryClass` enum (`LIST_ALL` / `GENERAL`), `classify(question)`, `RetrievalConfig`, `config_for(klass)`. 10 enumeration patterns covering imperative list verbs ("list X", "show me X", "give me X", "enumerate X"), "what topics", "what / which X did I learn", "every X", "all my/the X", "contents of X", "everything about X".
  - [src/stage2/search.py:run_search](../src/stage2/search.py) — accepts optional `question` kwarg. Only **widens** top_k (5 → 20 for LIST_ALL) when the class wants more than the caller asked for. Explicit small (`--top-k 3`) and large (`.top-k 50`) caller values are both respected.
  - [cli/notspotlight/repl.py](../cli/notspotlight/repl.py) + [src/pipeline.py](../src/pipeline.py) — both pass raw `question` through to `run_search` so classification fires.
  - [tests/stage2/test_query_classify.py](../tests/stage2/test_query_classify.py) — 45 new tests (24 LIST_ALL parametrized, 17 GENERAL parametrized, plus config / enum / round-trip).
- **Why it mattered:** 2026-04-21 transcript symptom — "what topics did I learn in AI class" returned 1 Propositional Logic file when the user's `sem6/343/` folder has 26 indexed AI-course files. Fixed top_k=5 cannot serve enumeration queries no matter how good the ranker is. Widening to 20 lets same-folder semantic clustering surface the rest.
- **Design rule that emerged:** the classifier only **widens, never narrows**. If the caller passes top_k=3, they get 3 — even if the class default is 5. Explicit user intent always wins.
- **Verification still pending:** activates after E4 + re-ingest. Test: run "what topics did I learn in AI class" — expect 15-20 of `sem6/343/`'s files to surface, not just Propositional Logic.
- **Follow-ups:** [B2](../Plans/backlog_20Apr26.md) HyDE depends on extending the classifier with a CONCEPTUAL class. [B4](../IO/IO%20-%20shipped_20Apr26.md) reranker stacks orthogonally — A9.

### A9. Cross-encoder reranker — opt-in second-pass ranking (B4)
- **Status:** Shipped 2026-04-24. Default OFF (per rememex postmortem warning that always-on rerankers shipped 2 ranking-regression bugs); opt-in via REPL `.rerank on`.
- **Where:**
  - [src/stage2/rerank.py](../src/stage2/rerank.py) — `rerank(query, candidates, top_k)` runs candidates through `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80 MB, downloads on first use, cached via `lru_cache`). Score-rewrites each `SearchResult.score` to carry the cross-encoder value (no more opaque RRF=0.016 noise — REPL now shows real, comparable numbers like 0.92 / 0.71 / 0.45).
  - [src/stage2/search.py:run_search](../src/stage2/search.py) — accepts `rerank=False` kwarg. When True, fetches `top_k * RERANK_OVERSAMPLE` (=10× → 50 for top_k=5) RRF-fused candidates, reranks, returns top_k. Off by default; backward-compatible.
  - [cli/notspotlight/repl.py](../cli/notspotlight/repl.py) — new `_rerank` session state + `.rerank on/off` dot-command + dropdown menu entry. Spinner status changes label when active.
  - [tests/stage2/test_rerank.py](../tests/stage2/test_rerank.py) — 7 tests, all mocking `_load_model` so no model download in CI: reordering by score, top_k truncation, empty input no-op, single-candidate short-circuit, (query, summary) pair construction, summary-empty fallback to path, tier-field preservation.
- **Why it mattered:** Hybrid dense + BM25 + ColPali gets the candidate set right *most* of the time, but on disambiguator-heavy queries (multiple files about the same topic, same vocabulary, only one is the correct match) the fusion can put the wrong one at rank 1. A cross-encoder reads `(query, doc)` together — much more discriminating than vector cosines — at the cost of one model forward pass per candidate.
- **Anti-patterns avoided:** (1) no silent threshold filtering — every input candidate gets a score, truncation is by `top_k` only; (2) score is exposed to user, not opaque; (3) opt-in by default, so factoid queries (where rerankers occasionally regress) aren't paying the latency cost without consent.
- **Layered with A8:** B1 (A8) widens the candidate window, B4 (A9) re-orders the candidates we got. They stack — turn both on for "what topics did I learn" type queries. Test plan post-E4: query without rerank, query with rerank, compare which list of 20 actually contains more sem6/343/ files.

### A7. Asset-folder cleanup — sibling-density rule + threshold bump (C7)
- **Status:** Shipped 2026-04-21. Replaces brittle path-pattern `.nasignore` proposal with a structural rule, after user feedback that "people don't name paths in the most intuitive manner."
- **Where:**
  - [src/ingest/ignore.py](../src/ingest/ignore.py) — added `**/*_extracted/{ppt,word,xl}/media/**` to DEFAULT_IGNORE_PATTERNS (Microsoft OOXML spec, not user naming). Brittle filename patterns intentionally omitted.
  - [src/router.py:73](../src/router.py#L73) — `IMAGE_THUMBNAIL_MIN_DIM` raised 200 → 600 px. Real document scans are ≥1200 px; decorative clip-art is typically ≤500 px.
  - [src/ingest/walker.py](../src/ingest/walker.py) — `_asset_library_folders()` flags any folder with ≥15 images and 0 documents as an asset library, drops its images from the candidate set. `find_candidates` now returns `(accepted, ignored, asset_lib_skipped)`.
  - [tests/ingest/test_walker.py](../tests/ingest/test_walker.py) + [test_ignore.py](../tests/ingest/test_ignore.py) — two new tests (sibling docs save the folder, subfolder docs don't save the parent), all 3-tuple callers updated. 176 tests pass.
- **Why it mattered:** ~576 MB of the 612 MB fast_tier was decorative single-page images (mediasources-4ed clip-art, pptx-extracted slide assets). Path-pattern `.nasignore` would have been brittle to the user's actual naming variability. The structural rule catches the **shape** of asset libraries regardless of folder name — including 3 subfolders inside `mediasources-4ed/` (`kid-in-bg-seq`, `kids-blue`, `fish`) the rule found independently.
- **Decision rule that emerged:** path patterns where paths are tool-mandated (Office decomposition, `node_modules/`, `__pycache__/`); structural rules where paths are human-chosen. Documented across [IO/IO - Human.md](IO%20-%20Human.md) 2026-04-21 transcript.
- **Expected savings on re-ingest:** ~434 images dropped (~433 MB est.). Re-ingest pending — change shipped, effect activates on `python -m src.ingest <root>`.
- **Follow-ups:** [E4](../Plans/backlog_20Apr26.md) — Qdrant Docker server for real quantization is the next storage lever once C7's savings are booked. [B8](../Plans/backlog_20Apr26.md) — Semantra-style chunking for long text-native PDFs (separate retrieval-quality concern).

### A6. Ripgrep as query-time enrichment for T0 files
- **Status:** Shipped. Answer step detects T0 files via manifest,
  runs ripgrep for tokens in the user's question, prepends matching
  lines to the LLM prompt instead of a whole-file read. Falls back to
  a pure-Python line scan if the `rg` binary isn't on PATH. 11 tests.
- **Where:** [src/ingest/ripgrep.py](../src/ingest/ripgrep.py);
  [src/answer.py:146-182](../src/answer.py#L146-L182);
  [tests/ingest/test_ripgrep.py](../tests/ingest/test_ripgrep.py).
- **Why it mattered:** Huge CSVs and logs deliberately don't have per-row
  Qdrant points (that way madness lies — 10M points that all look alike).
  Ripgrep at answer time surfaces the exact rows that match the query,
  giving the LLM real content to ground its answer in.
- **Follow-ups:** [B7](../Plans/backlog_20Apr26.md) — promote ripgrep
  from a prepend-always helper to an actual agent tool in a multi-turn
  retrieval loop.

---

## B. Video / too-big-to-read files — Stage 3

### B1. `.alt` YAML sidecar parser + transcoder
- **Status:** Shipped. Parses the `.alt` schema (source / summary / scenes /
  themes / search_tokens / context), transcodes into Stage-2-compatible
  summary markdown — one file-level point plus one per scene.
- **Where:** [src/stage3/alt.py](../src/stage3/alt.py);
  [src/stage3/transcode.py](../src/stage3/transcode.py);
  [tests/stage3/test_alt.py](../tests/stage3/test_alt.py) + [test_transcode.py](../tests/stage3/test_transcode.py).
- **Why it mattered:** Video and other too-big-to-read files can't survive
  the "retrieve file, read it, answer" pattern — the bytes are unreadable
  by an LLM. `.alt` is a compact, structured, **text-native** artifact that
  carries everything answerable about the video. `Source:` correctly
  points at the `.alt`, not the original `.mov`, so the answer step works.
- **Follow-ups:** [A1 in backlog](../Plans/backlog_20Apr26.md) —
  end-to-end smoke test against a real video `.alt` through Qdrant still
  parked.

### B2. Stage 3 indexer + CLI
- **Status:** Shipped. `python -m src.stage3 <dir>` walks a directory,
  finds `.alt` files, transcodes + writes per-file and per-scene markdowns
  into `Test Summaries/`, registers manifest rows for each. Per-scene
  manifest keys use `<alt>#scene:MM:SS` so Qdrant points stay unique.
- **Where:** [src/stage3/index.py](../src/stage3/index.py);
  [src/stage3/\_\_main\_\_.py](../src/stage3/__main__.py);
  [tests/stage3/test_index.py](../tests/stage3/test_index.py).
- **Why it mattered:** Wires `.alt` into the same ingestion pipeline as
  everything else. No separate Qdrant collection, no separate search path
  — sessions work.

### B3. Fragment-aware file resolution in `src/answer.py`
- **Status:** Shipped. `_resolve()` strips `#scene:...` fragments before
  opening a file, dedupes multiple scene hits from the same `.alt` so the
  LLM doesn't re-read the same bytes N times.
- **Where:** [src/answer.py:82-143](../src/answer.py#L82-L143).
- **Why it mattered:** Per-scene retrieval needs unique Qdrant IDs
  (hence fragments) but the underlying bytes are one file. Without this
  the answer step would either try to open `video.alt#scene:00:30` and
  fail, or read the `.alt` three times for a three-scene hit.

### B4. `.alt` as a readable extension in `src/content.py`
- **Status:** Shipped. `.alt` is now in the dispatch table so the answer
  step can read it as structured YAML text. Deliberately **not** in
  `SUPPORTED_EXTS` so Stage-1's walker doesn't try to LLM-summarize
  pre-made summaries.
- **Where:** [src/content.py](../src/content.py).

---

## C. ColPali fast tier (pre-existed; verified + polished)

### C1. Int8 scalar quantization on multi-vector collection
- **Status:** Shipped before this session; verified intact and documented
  as policy.
- **Where:** [src/stage2/fast_db.py:54-59](../src/stage2/fast_db.py#L54-L59)
  `ScalarQuantization(type=INT8, always_ram=False)`.
- **Why it mattered:** 4× compression over float32, ~1.5% recall loss.
  Primary mechanism for keeping T4 storage tractable without pooling.

### C2. MaxSim retrieval + RRF fusion across tiers
- **Status:** Shipped before this session; `tier4.py` now slots into the
  same collection.
- **Where:** [src/stage2/fast_db.py:search](../src/stage2/fast_db.py);
  [src/stage2/search.py:_rrf_merge](../src/stage2/search.py).
- **Why it mattered:** A single search request fans out to `summaries`
  and `fast_tier`, fuses results keyed by `source_path`. `SearchResult`
  carries a `tier` field ("summary" / "fast" / "both") for trust and
  debuggability.

### C3. tier4 worker wiring
- **Status:** Shipped. Thin wrapper around the existing
  `src.stage1_fast.index.index_file` so the router dispatches to ColPali
  when it makes sense, without duplicating the batch-encode plumbing.
- **Where:** [src/ingest/tier4.py](../src/ingest/tier4.py).
- **Why it mattered:** Closes the loop between "router says T4" and
  "ColPali actually runs." Before this, T4 silently fell back to T3.

### C4. Storage-curbing stack (documented)
- **Status:** Policy documented; mechanisms live in router + fast_db.
- **Where:** [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md),
  "Hard gates" section.
- **Mechanisms (no pooling):**
  - Int8 quant (4×)
  - HNSW graph on disk (`on_disk=True`)
  - Per-file cap: `T4_MAX_STORAGE_MB_PER_FILE = 50 MB`
  - Corpus budget: `DEFAULT_T4_BUDGET_MB = 5 GB`, user-overridable
  - Routing bias — most files never touch T4
  - Model-by-hardware: ColSmol-500M on CPU/small GPU, ColQwen2.5 on big GPU
  - Thumbnail skip for tiny images
- **Why it mattered:** Explicit alternative to the pooling shortcut,
  which we rejected because it degrades financial-doc retrieval (FIQA
  paper flag).

---

## D. Design docs

### D1. [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md)
- **Status:** Shipped. Source-of-truth policy document — 5 tiers,
  one-pass ingest, three-axis scoring (visual / sensitivity / T4 cost),
  hard gates, collection layout, manifest schema, implementation order,
  success criteria.
- **Why it mattered:** Every `if ext == ...` decision in the code paths
  either matches this doc or contradicts it (and should be challenged).

### D2. [Plans/Stage 3 - Videos.md](../Plans/Stage%203%20-%20Videos.md)
- **Status:** Shipped. Video `.alt` design doc.

### D3. [Plans/Port.md](../Plans/Port.md)
- **Status:** Shipped. Two-phase cloud→local porting plan (Phase 1: real
  data on cloud stack, zero code changes; Phase 2: Ollama + local Qdrant
  via env-var swap).

### D4. [Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md)
- **Status:** Shipped. Companion to this doc. Every pending item with
  *what / effort / why / why not yet / revisit trigger*.

---

## E. Test suite growth

### E1. New coverage
- **Status:** Shipped.
- **Additions:**
  - [tests/test_router.py](../tests/test_router.py) — 37 router tests
  - [tests/ingest/test_common.py](../tests/ingest/test_common.py) — 8
  - [tests/ingest/test_tier0.py](../tests/ingest/test_tier0.py) — 4
  - [tests/ingest/test_tier1.py](../tests/ingest/test_tier1.py) — 6
  - [tests/ingest/test_tier2.py](../tests/ingest/test_tier2.py) — 6
  - [tests/ingest/test_ripgrep.py](../tests/ingest/test_ripgrep.py) — 11
  - [tests/ingest/test_walker.py](../tests/ingest/test_walker.py) — 7
  - [tests/ingest/test_ignore.py](../tests/ingest/test_ignore.py) — 9
- **Total new tests from this session:** 88.

### E2. Stale-test cleanup
- **Status:** Shipped. Three stage-2 test files that had drifted from the
  shipped code's behavior were repaired or rewritten:
  - [tests/stage2/test_db.py](../tests/stage2/test_db.py) — inverted the
    entity-exclusion assertion to match the current shipped behavior
    (entities + identifiers are intentionally in the embedded text).
  - [tests/stage2/test_parser.py](../tests/stage2/test_parser.py) —
    removed the committed-fixture dependency; each test now generates a
    hermetic Breeze-Airways-shaped summary in `tmp_path`.
  - [tests/stage2/test_search.py](../tests/stage2/test_search.py) —
    mocked `_search_fast_tier` in each case so the summary-collection
    behavior can be asserted without also hitting the new fast-tier
    fusion. Updated field-set to include the new `tier` column.

### E3. Real bugs caught by the new tests
- Walker's prune loop was silently disabled for corpora outside
  `REPO_ROOT` — fixed to fall back to absolute-path prefixes.
- Ripgrep stopword list killed the month "May" (collision with the modal
  verb) — narrowed the stopword set.
- Tier4 walker's manifest-update path was skipping `mark_summarized`
  correctly (tier4 manages its own `fast_indexed_at` state via
  `index_file`) — verified and locked in by tests.
- PathSpec 1.0 `DeprecationWarning` on `gitwildmatch` → switched to
  `"gitignore"` factory name.

### E4. Current suite totals
- **Status:** 153 tests passing in the default run (routing + ingest +
  stage2 + stage3 + manifest). Integration-grade tests for T3 (LLM) and
  T4 (ColPali model load) deferred to [H1 in backlog](../Plans/backlog_20Apr26.md).

---

## F. Rememex learnings that made it in

Cross-referenced back to the research report (see `Plans/backlog_20Apr26.md`
for the "NO, still pending" list).

| Tag | Learning | Where |
|---|---|---|
| R2 | Filename + parent in embedded text | [tier1.py](../src/ingest/tier1.py), [tier2.py](../src/ingest/tier2.py) — title and identifiers always include the filename |
| A6 | Never silently drop files | [router.py](../src/router.py) `decide()` always records a `skip_reason`; walker persists it |
| A2 | Never pool ColPali patches | [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md) hard rule; int8 quant used instead |
| A3 | Silent dimension mismatch is a footgun | **NOT yet fixed** — tracked as [B3](../Plans/backlog_20Apr26.md) |
| A7 | Use the `ignore` crate idiom for file walks | [ignore.py](../src/ingest/ignore.py) via `pathspec` |
| (our stricter version) | Content-based criticality, not filename regex | [router.py:compute_sensitivity_score](../src/router.py) |
| (ours) | Full manifest audit trail for every routing decision | [manifest.py:Entry](../src/manifest.py) + `mark_routed()` |

---

## G. What's NOT in this doc

Anything still open lives in [Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md).
Specifically: adaptive query router (B1), HyDE (B2), dim-mismatch detection
(B3), cross-encoder reranker (B4), hierarchical chunking (B5), payload
filters (B6), agentic retrieval loop (B7), filesystem watcher (C1), REPL
score breakdown (C2), config JSON schema (C3), MCP server (C4), pipx
packaging (C5), Tauri shell (C6), benchmark README (D1), competitors
table (D2), license/privacy statements (D3), REPO_ROOT audit (D4), Qdrant
local docs (E1), local-vs-cloud benchmarks (E2), ColPali version bump (E3),
HTML/eml (F1), legacy Office (F2), audio (F3), EXIF (F4), two-pass revisit
(G1), transient T4 retirement (G2), multi-tier additive walker (G3),
integration test lane (H1), eval baseline (H2).

---

## H. Mid-session continuation (2026-04-24 → 2026-04-25)

Cluster of fixes that landed after the initial A7/A8/A9 trio. Most aren't
tagged backlog items — they were tactical fixes uncovered by real-data
testing of B1+B4. Captured here so the audit trail is complete.

### H1. Stage 2 back-door removal (correctness)
- **Status:** Shipped 2026-04-23.
- **Where:** [src/stage2/db.py](../src/stage2/db.py) — `upsert_csv_rows` deleted.
  [src/stage2/__main__.py](../src/stage2/__main__.py) — replaced ext-sniffing
  dispatch with a single contract: every manifest row is either router-skipped,
  fast-tier-only, or has a `summary_file`. Any other shape raises
  `RuntimeError` with a re-run message. Manifest's `row_count` field dropped
  from the schema (`Entry`).
- **Why it mattered:** A 2551-row CSV was being row-by-row embedded over
  ~14 hours. The legacy `upsert_csv_rows` path predated the tier router and
  bypassed it for any CSV that fell through. Now stage 2 has exactly one way
  in and crashes loud if upstream routing was incomplete.

### H2. PDF TOC extraction + T3 summary supplement
- **Status:** Shipped 2026-04-23.
- **Where:** [src/content.py:_extract_pdf_toc](../src/content.py) — pulls the
  bookmark-based TOC via `pymupdf.get_toc()` and prepends it to extracted
  text. [src/answer.py:_summary_supplement](../src/answer.py) — when the
  manifest has a T3 summary for a retrieved file, the summary is included
  as supplementary context alongside the raw file content. Critical for
  scanned PDFs and 700+ page books where pypdf returns near-nothing.
- **Why:** The Taylor textbook query returned "the file is a cover and
  mathematical reference page" because pypdf got 1614 chars from a 700-page
  scan. T3 summary supplement put the actual chapter list back in scope.

### H3. Whitespace-tolerant path matching in answer stage
- **Status:** Shipped 2026-04-23.
- **Where:** [src/answer.py:_normalize_path_for_match](../src/answer.py).
- **Why:** LLM answers occasionally render path citations with subtle
  whitespace drift (collapsed double-spaces, %20-encoded spaces, leading/
  trailing whitespace). Strict equality dropped legitimate citations as
  "hallucinated" and the user saw `Sources used: (none)` for valid answers.

### H4. System temp + cache patterns in DEFAULT_IGNORE_PATTERNS
- **Status:** Shipped 2026-04-25.
- **Where:** [src/ingest/ignore.py DEFAULT_IGNORE_PATTERNS](../src/ingest/ignore.py)
  — added `tmp/`, `var/tmp/`, `.cache/`, `**/Library/Caches/**`,
  `**/AppData/Local/{Temp,Cache}/**`, `pytest-of-*/`, `__MACOSX/`,
  `.fseventsd/`, `.Spotlight-V100/`, `.TemporaryItems/`, `.Trashes/`,
  `.Trash/`, `.Trash-*/`.
- **Why:** Pytest fixture roots (`/tmp/pytest-of-*/`) were leaking into the
  user's production manifest because tests fired with that as a root and
  the manifest persisted across runs. New patterns prevent recurrence.
  Existing stale rows handled by H6.

### H5. Walker skip-check accepts `fast_indexed_at`
- **Status:** Shipped 2026-04-25.
- **Where:** [src/ingest/walker.py:ingest_one](../src/ingest/walker.py).
- **Why:** Skip check required `summary_file` to be truthy, but T4-only
  files (images routed to ColPali) don't have a summary_file — only
  `fast_indexed_at`. So image files were "re-routed" to T4 every ingest,
  index_file's internal short-circuit caught them, but the walker reported
  `T4=N` instead of `unchanged=N`. Cosmetic accounting bug; no actual
  re-encoding happened. Fix: skip if EITHER summary_file or
  fast_indexed_at is set.

### H6. Manifest robustness — clean_stale + reconcile_from_fast_tier + mark_summarized bug fix
- **Status:** Shipped 2026-04-25.
- **Where:**
  - [src/manifest.py:Manifest.mark_summarized](../src/manifest.py) — was
    replacing the whole `Entry` on every call, silently zeroing out
    `fast_indexed_at`, `fast_pages`, and the router audit fields whenever a
    previously-T4-indexed file got re-summarized. Vectors stayed in Qdrant;
    manifest forgot. Now mutates the existing entry, preserving unrelated
    fields. Symmetric to `mark_fast_indexed` (which was already correct).
    Real bug; user lost ~42 fast-tier rows before this was caught.
  - [src/manifest.py:Manifest.clean_stale](../src/manifest.py) — drops rows
    whose source files no longer exist + deletes orphaned summary markdowns.
  - [src/manifest.py:Manifest.reconcile_from_fast_tier](../src/manifest.py)
    — scrolls Qdrant `fast_tier`, counts pages per source, re-stamps
    `fast_indexed_at` for any entry that lost it. Recovery for the bug above.
  - [justfile](../justfile) — `just clean-stale-manifest`, `just recover-fast-tier`.
  - [tests/test_manifest.py](../tests/test_manifest.py) — 7 new tests
    covering all three: bug regression (mark_summarized preserves
    fields), clean_stale behavior, repo-relative path handling.

### H7. FALLBACK_LLM_PROVIDER — second-provider rescue for cloud failures
- **Status:** Shipped 2026-04-24.
- **Where:**
  - [src/llm.py:build_chat_model](../src/llm.py) — accepts `provider_override`
    so a parallel agent can be built against a different provider without
    mutating env vars.
  - [src/stage1/summarize.py:get_fallback_agent](../src/stage1/summarize.py) —
    lazy-loaded cached fallback agent.
  - [src/stage1/summarize.py:_run_with_retry](../src/stage1/summarize.py) —
    extended to attempt fallback once on any non-retryable primary failure
    (`UnexpectedModelBehavior`, exhausted 429s, etc.). Original 429 backoff
    loop preserved.
  - [tests/test_fallback_agent.py](../tests/test_fallback_agent.py) — 9 tests.
  - [.env](../.env) — documented `FALLBACK_LLM_PROVIDER=ollama` opt-in.
- **Why:** OpenRouter free-tier rate-limits returned `200 OK` with a
  non-chat-completion JSON body, which the SDK couldn't parse and threw
  `UnexpectedModelBehavior`. 58 of 356 files failed silently in one ingest
  run. With fallback armed, those would route to Ollama and succeed.

### H8. B1 bare-form regex fix + B1↔B4 wiring (auto-suppress rerank for LIST_ALL)
- **Status:** Shipped 2026-04-24.
- **Where:**
  - [src/stage2/query_classify.py:_LIST_ALL_PATTERNS](../src/stage2/query_classify.py)
    — added `(\s+\w+)?` between question word and verb so "what did I
    learn in X" matches LIST_ALL alongside "what topics did I learn in X".
  - [src/stage2/search.py:run_search](../src/stage2/search.py) — when
    classifier returns `LIST_ALL`, the cross-encoder rerank is suppressed
    even when caller passed `rerank=True`. Empirical evidence: rerank=on +
    "find me all my uber receipts" → 0 receipts in top-20; rerank=off →
    11 receipts. Cross-encoder over-weights semantic prose vs terse
    receipt-style summaries.
  - [tests/stage2/test_search.py](../tests/stage2/test_search.py) — 2 new
    tests verify suppression for LIST_ALL + firing for GENERAL.
- **Why:** B4's reranker regresses on enumeration / proper-noun-heavy
  queries (rememex's documented anti-pattern). Auto-gating via B1's class
  info gives "use the right tool per query" without user toggling.

### H9. Answer prompt de-hacking + minimal rewriter improvement
- **Status:** Shipped 2026-04-25.
- **Where:**
  - [src/answer.py:SYSTEM_PROMPT](../src/answer.py) — removed enumerated
    synonym example pairs (BPM↔beats-per-second, prereqs↔prerequisites,
    etc.). Replaced with a single general principle: "Look for synonyms,
    abbreviations, alternate units, paraphrases. There is no fixed list."
    This was the standout hack from the session — examples that worked on
    the test cases but would fail on every new vocabulary.
  - [src/stage2/search.py:REWRITE_SYSTEM_PROMPT](../src/stage2/search.py)
    — minimal one-sentence addition: keywords expanded from 3-8 to 5-12 +
    instruction to include "synonyms, abbreviations, alternate vocabulary,
    paraphrases the documents themselves may use." No 6-rule restructure
    (an earlier overshoot the user correctly pushed back on).
- **Why:** CLAUDE.md "no hacks" standard. Enumerated example pairs are
  the textbook anti-pattern — they pass the test suite, fail the moment
  a real user types something not in the list.

### H10. E4 — Qdrant standalone binary wiring
- **Status:** Shipped 2026-04-24 (wiring); user-side activation pending.
- **Where:**
  - [justfile](../justfile) — `qdrant-install`, `qdrant-up`, `qdrant-down`,
    `qdrant-status` targets. Binary + data on `/mnt/hardisk/qdrant/` by
    default (`QDRANT_HOME` overridable) so root drive isn't filled.
  - [src/stage2/db.py:get_qdrant_client](../src/stage2/db.py) — `QDRANT_API_KEY`
    is now optional when `QDRANT_CLUSTER_ENDPOINT` is on localhost (loopback
    detection via `_is_localhost_url`). Cloud auth still required for
    non-localhost.
- **Why:** Local-mode Qdrant is a Python reimplementation that silently
  drops quantization, compaction, and HNSW segments. Standalone Rust binary
  is the same code as Cloud — gets all features. Subprocess pattern carries
  forward to end-user shipping (E5 in backlog).

### H12. B3 — embedding-dimension mismatch detection
- **Status:** Shipped 2026-04-25.
- **Where:**
  - [src/stage2/db.py:DenseDimMismatchError](../src/stage2/db.py) +
    [assert_dense_dim_match](../src/stage2/db.py) — compares the configured
    model's `DENSE_VECTOR_SIZE` against the stored collection's vector size.
    Raises with a clear remediation message (`python -m src.stage2 ingest --force`)
    on mismatch.
  - [src/stage2/db.py:create_collection](../src/stage2/db.py) — asserts before
    returning an existing collection, so any subsequent upsert / search hits
    the loud error path instead of cryptic Qdrant errors or silent garbage.
  - [src/stage2/search.py:_search_summary_tier](../src/stage2/search.py) —
    same assertion at search time.
  - [tests/stage2/test_db.py](../tests/stage2/test_db.py) — 4 new tests:
    correct dim passes, mismatch raises with hint, missing collection no-ops,
    no-dense-vector edge case.
- **Why:** rememex's documented foot-gun. A user swaps embedding model
  (MiniLM-384 → E5-base-768), the existing index is now incompatible, and
  every subsequent search either errors with a useless Qdrant message or
  silently returns garbage. With this assertion, the failure is loud and
  immediate, with the exact fix in the error message.

### H14. Strict grounding rules in answer prompt + dual-page citation refinements
- **Status:** Shipped 2026-04-25.
- **Where:** [src/answer.py:SYSTEM_PROMPT](../src/answer.py).
- **What changed:**
  1. Added 5 explicit "STRICT GROUNDING RULES" forbidding training-data leakage, scope expansion (e.g. "ML applications" added to a Dirac-delta question grounded in an electrodynamics textbook), decorative citations, and source-conflation (claim from file A attributed to file B).
  2. Inline page citations in the answer prose are now suppressed by default — the prior rule ("cite both forms inline whenever you reference a passage") was producing `[book p. N / PDF p. M]` annotations on every bullet, which the user found unreadable. Page info now lives in `sources_used` only; inline page mentions allowed only when the user explicitly asked "where" / "on what page".
  3. Math-notation guidance: prefer Unicode (∂ ∫ ∑ ∇ × · α θ ⇒ ≤ ≥), reserve LaTeX `$...$` for genuinely structural cases (fractions, integrals with limits). Reconstruct OCR-garbled math from physics knowledge; never copy garbled OCR verbatim.
- **Why it mattered:** Real hallucination caught the same day the lazy-chunking landed — LLM answered "what's a Dirac delta function?" pulling content from BOTH Griffiths (real Dirac coverage) and UnderstandingDeepLearning (ML empirical-distribution view), then attributed all of it to Griffiths in `sources_used` with confident-looking page numbers. The user noticed because they actually checked the cited Griffiths page and the ML content wasn't there. Worst kind of hallucination: plausible, well-formatted, attached to real-looking citations. The prompt-level fix is the cheap first lever; programmatic citation verification is queued as **B9** for if the prompt rules + better LLM aren't enough.
- **Limit, honestly:** prompt rules constrain LLM behavior, they don't guarantee it. Free-tier Gemma may still extrapolate occasionally. The structural fix (B9 in backlog) is post-generation citation verification: parse cited pages, look up their actual text, score similarity to the cited claim, strip / warn on mismatch. Build only if prompt rules + paid LLM (Kimi) still misbehaves on real queries.

### H13. Lazy chunking — keyword-driven page picker for long PDFs
- **Status:** Shipped 2026-04-25.
- **Where:**
  - [src/content.py:extract_pdf_relevant_pages](../src/content.py) — new
    primitive: scores each PDF page by keyword hit count, picks top-K, expands
    with ±N context pages, emits in document order with `## Page N` anchors.
    Caps at `max_chars`. Falls back to "" when no page matches; caller's job
    to fall back to extract_pdf_text.
  - [src/content.py:build_content_blocks](../src/content.py) — accepts new
    optional `search_keywords` kwarg. When provided AND the PDF's full text
    exceeds `max_chars`, lazy-chunking fires; otherwise the regular front-of-
    file extract is used. Short PDFs that fit entirely in budget always use
    the regular path (the LLM has the full context for free).
  - [src/answer.py:answer_question](../src/answer.py) — accepts
    `search_keywords` kwarg, threads it to `build_content_blocks`.
  - [cli/notspotlight/repl.py](../cli/notspotlight/repl.py) +
    [src/pipeline.py](../src/pipeline.py) — call sites pass
    `sq.keywords` (the rewriter's keyword list) through.
  - [tests/test_lazy_chunking.py](../tests/test_lazy_chunking.py) — 13 new
    tests using a synthetic in-memory PDF: top-K by score, context expansion,
    document-order output, case-insensitive match, max_chars cap, fallback to
    regular extract on no-match, short-PDF ignore-keywords behavior, missing-
    file graceful failure, backward compat.
- **Why:** The Liouville-textbook problem. Before this, retrieving Taylor's
  textbook for "what is in chapter 13.7" gave the answer LLM only the first
  ~25 K chars (= cover + preface + maybe TOC); the actual section was on
  page ~500 and the LLM said "the file does not contain this." With lazy
  chunking, the rewriter's keywords drive a page-level search inside the
  retrieved file, and only the matching pages are passed to the LLM. Same
  pattern as the existing T0 ripgrep enrichment, but for PDFs.
- **Storage cost:** zero. No new index, no new Qdrant points. The scoring
  happens at answer time from the source PDF.
- **Latency cost:** 5-15 s per query that hits a long PDF (one-time cost
  for one query; nothing if the query targets short files).
- **Scope deliberately narrow:** only fires for PDFs where the full text
  exceeds `max_chars`. Doesn't help DOCX / PPTX (already shorter than budget
  in practice) and doesn't help research papers without bookmark TOCs (the
  file may not be retrieved at all if the query term isn't surface-visible).
  Conditional upfront chunking for that case is deferred — see backlog.

### H11. Operational inspection targets in justfile
- **Status:** Shipped 2026-04-21 → 2026-04-25.
- **Where:** [justfile](../justfile) — `disk-usage`, `fast-tier-files`,
  `fast-tier-config` targets. Plus `qdrant-*` (H10), `clean-stale-manifest`
  + `recover-fast-tier` (H6).
- **Why:** Diagnostic commands the user can run anytime without remembering
  flags. `fast-tier-config` was specifically what surfaced the Qdrant local
  quantization gap.

---

## Snapshot freeze

This document is a dated snapshot. When a backlog item lands, move its
"shipped" entry here (under the appropriate theme) and remove it from
[Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md). When this doc is
superseded by a newer dated snapshot, rename the file (e.g.
`IO - shipped_01May26.md`) and keep the old one as historical record.
