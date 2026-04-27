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

## Snapshot freeze

This document is a dated snapshot. When a backlog item lands, move its
"shipped" entry here (under the appropriate theme) and remove it from
[Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md). When this doc is
superseded by a newer dated snapshot, rename the file (e.g.
`IO - shipped_01May26.md`) and keep the old one as historical record.
