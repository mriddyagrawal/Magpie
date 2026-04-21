# Backlog — 2026-04-20

> Snapshot of everything we've agreed to, designed, or flagged but not yet
> shipped. Grouped by theme, not priority — the "Next up" section at the end
> is the prioritized slice. Revisit this doc when planning the next sprint;
> freeze it by date when superseded.

Conventions:
- **Effort**: S (hours) / M (half-day-to-day) / L (multi-day).
- **Why**: the original reason we wanted it. Tied to a specific
  observation, not just a vibe.
- **Why not yet**: what would need to change for this to unblock.
- **Revisit trigger**: a concrete condition that flips it from backlog to
  active.

---

## A. Parked work (mid-session pauses)

### A1. Stage 3 video `.alt` end-to-end smoke test
- **Status:** Code built (`src/stage3/{alt.py,transcode.py,index.py}`), 22 unit tests green, never verified through the full pipeline.
- **Effort:** S.
- **Why:** We already shipped the video pathway in [Plans/Stage 3 - Videos.md](Stage%203%20-%20Videos.md). A smoke test (`python -m src.stage3 <videos-dir>` → `python -m src.stage2 ingest` → `python -m src.pipeline "kids dancing birthday"`) verifies the scene-level Qdrant points actually return the expected hit with timecode.
- **Why not yet:** Paused to do the router refactor. No blockers.
- **Revisit trigger:** Immediately after this backlog is reviewed — this is finish-what-you-started.

---

## B. Retrieval-quality gaps (rememex learnings still owed)

### B1. R1 — Adaptive query router
- **What:** Classify incoming queries into {ExactMatch, ExactSymbol, Keyword, Conceptual} via ~150 lines of regex, vary the Dense/BM25 RRF weights per class. HyDE fires only for Conceptual.
- **Effort:** S.
- **Why:** rememex commit `c50b526` plus `d2d69e4`. Today's `run_search` applies a single RRF weight to every query — a conceptual "what do I owe next month" and a symbol "parseConfig" compete on the same scoring curve. Rememex's query router lifted Recall@5 visibly in their resume benchmark.
- **Why not yet:** Router refactor consumed the ingest side. Query side untouched.
- **Revisit trigger:** After benchmark-on-real-data (see D1) shows the biggest misses are either (a) symbol queries being drowned by dense score, or (b) conceptual queries missing because BM25 dominates. Either justifies R1.

### B2. R4 — HyDE gated on Conceptual queries
- **What:** For Conceptual-class queries only, use the local `ChatAgent` to produce a hypothetical declarative summary, embed *that*, and use it as the dense query. Raw query fed to BM25 side.
- **Effort:** M.
- **Why:** The asymmetric-search problem (declarative summaries in the index vs interrogative queries from users) — [Plans/Future Plans.md](Future%20Plans.md) item #2 is the same concept. rememex ships this gated (via their router), not always-on.
- **Why not yet:** Needs B1 first (we need the classifier to gate on). Plus a small prompt engineering loop.
- **Revisit trigger:** Right after B1 lands.

### B3. R6 — Embedding-dimension mismatch detection
- **What:** At search time, assert the configured embedding model's dim equals the stored collection's dim. On mismatch: auto-reindex if possible, else error loudly with "the dense model was changed; run `ns reindex --force`."
- **Effort:** S.
- **Why:** rememex `search.rs:67` — they added this assertion *after* a user-reported silent-garbage bug. Same class of bug we'll hit the first time someone swaps MiniLM for E5-Base.
- **Why not yet:** Minor, but genuinely cheap. Cheapest item on this whole backlog per unit of user-pain-avoided.
- **Revisit trigger:** Do it before any embedding-model swap work.

### B4. Cross-encoder reranker (bge-reranker-v2-m3)
- **What:** Pull top-50 from Qdrant, rerun `(query, doc)` through a small cross-encoder, keep top-5 to feed Stage 4. Disabled by default with threshold=0, opt-in via flag.
- **Effort:** M.
- **Why:** [Plans/Future Plans.md](Future%20Plans.md) item #6. rememex shipped this and then hit two ranking bugs from it (`651feda`, `c733881`). The anti-pattern to avoid is **silent threshold filtering** — always show scores, always default threshold=0.
- **Why not yet:** Only earns its keep on disambiguator-heavy corpora; unclear yet whether our dense+sparse+tier-fusion is enough.
- **Revisit trigger:** After benchmarking shows recall@5 leaving obvious disambiguator misses.

### B5. Hierarchical chunking (the 400-page manual problem)
- **What:** Two-level: per-section chunk summaries + rolled-up doc summary, both embedded. Retrieval queries both levels.
- **Effort:** L.
- **Why:** [Plans/Future Plans.md](Future%20Plans.md) item #5. Currently a 400-page textbook gets one summary; "what does Chapter 12 say about X?" can't find Chapter 12.
- **Why not yet:** No file in our test corpus currently hits the threshold. Premature until we have one.
- **Revisit trigger:** First real file > 50 pages lands in the index AND search returns the generic summary for specific questions.

### B6. Structured payload filters (date / merchant / amount)
- **What:** Extract normalized `transaction_date` and `merchant_name` into Qdrant payload; let the query rewriter emit filters ("`transaction_date` in 2022-05").
- **Effort:** L.
- **Why:** [Plans/Future Plans.md](Future%20Plans.md) item #7. Date-scoped queries are filter-shaped, not similarity-shaped.
- **Why not yet:** Requires reliable date extraction AND a query-rewrite path that classifies when a filter is needed. Both are their own projects.
- **Revisit trigger:** Retrieval eval starts including range/categorical queries ("all receipts from May 2022") and verbatim BM25 matching fails on them.

### B7. Agentic retrieval loop ("RAG with legs")
- **What:** Answer agent gets tools — `fetch_more(offset, k)`, `read_file(path)`, `ripgrep_file(path, pattern)` (last one partially shipped). Model loops read → decide → fetch more → answer.
- **Effort:** L.
- **Why:** [Plans/Future Plans.md](Future%20Plans.md) item #3. SufficientPie's direct critique in the Reddit thread: "RAG doesn't work well — it gets snippets and gives them to the LLM which assumes they're all relevant." Tool-loop is the cure.
- **Why not yet:** Meaningful only once we have a measurable baseline to beat (see D1).
- **Revisit trigger:** Ship the non-agentic baseline, eval it, then A/B against an agentic loop.

### B8. Semantra-style window chunking for long text-native PDFs
- **What:** For text-native PDFs over some threshold (say >50 pages), augment the T2 whole-file text dump with **overlapping token-window chunks** á la [Semantra](https://github.com/freedmand/semantra) — default `128_0_16` (128 tokens, 16-token overlap). Each chunk gets its own Qdrant point with `source_path`, `page_num`, and `char_offset` payload fields. Retrieval returns both whole-file summary hits and chunk-level hits; the answer stage uses chunk `page_num` to cite "page 237" instead of the whole file. Reuse the existing dense+sparse embeddings; no new model.
- **Effort:** M.
- **Why:** Today a 400-page text-native PDF goes through T2 as **one** embedding — "what's on page 237?" retrieves the whole-file vector with no page-level signal. Semantra's entire pitch is this chunking, and it's why their recall on long docs beats naive file-level RAG. See transcript discussion 2026-04-21 where the Taylor textbook (808 pages) returned only the cover + preface because no chunking surfaced the TOC or later chapters. Complements B5 (hierarchical summaries) but solves a different problem: B5 gives you section-level *summaries*, B8 gives you raw-text chunk *matches* with page anchors.
- **Why not yet:** Router refactor consumed ingest. Also a multiplier on Qdrant point count (50-page PDF → ~5× more points) — want B5 or a storage-vs-recall measurement first to make sure we're not exploding the summary collection for content where the file-level vector is already sufficient.
- **Revisit trigger:** First text-native PDF over 100 pages lands in the index AND a realistic "page N covers X" query misses because retrieval only has the file-level vector. Or whenever we ship B5 — build both together, they share infrastructure.

---

## C. Operational / UX gaps (rememex learnings + Reddit signals)

### C1. Filesystem watcher (`watchfiles`, 500 ms debounce)
- **What:** Background watcher that calls the ingest walker on file changes, with a debounce to batch rapid saves. Mutex around reindex so concurrent change events serialize.
- **Effort:** M.
- **Why:** rememex `681505d` + `0bfa625` (race-fix commit is a warning). Recall-lite's user experience goal was "alt+space, find the file" — that only works if the index stays fresh automatically.
- **Why not yet:** Manual `python -m src.ingest` is fine for dev. Watcher adds daemon complexity and a permission surface.
- **Revisit trigger:** First non-dev user tries the product and asks "why didn't my new file show up?"

### C2. Score breakdown in the REPL
- **What:** Each search result shows `dense=0.82 · bm25=rank 3 · fast=0.71 · route=T2` next to the answer, not just a fused number.
- **Effort:** S.
- **Why:** rememex learning — makes the product feel trustworthy instead of magic. `SearchResult.tier` already carries this info, we just aren't displaying it. Costs nothing.
- **Why not yet:** REPL has been stable and we didn't want to churn it during the router work.
- **Revisit trigger:** After C1 or any UX-visible release — ship together.

### C3. `.nasconfig.yaml` JSON Schema
- **What:** Publish a `$schema` file at repo root (or a served URL) that VSCode / any YAML-LSP editor can autocomplete against. Keys today: `accuracy`, `t4_budget_gb_override`, `colpali`.
- **Effort:** S.
- **Why:** rememex `config.schema.json` is exactly this. Free polish; users discover the available keys without reading docs.
- **Why not yet:** Waited until the config keys stabilized — they now have. Unblocked.
- **Revisit trigger:** Ship with C2.

### C4. MCP server
- **What:** Tiny stdio binary exposing `nas_search`, `nas_read_file`, `nas_list_files`, `nas_ripgrep`. Pair with Claude Desktop / Cursor / any MCP client.
- **Effort:** M.
- **Why:** Recall-lite Reddit thread: two separate top-comment upvotes asked for this, and the author's PR #2 was received as "this solves 3 feature requests at once." This is the single highest-leverage feature for the dev/LocalLLaMA audience.
- **Why not yet:** Distinct market from our small-business/student persona. Would split focus right when we haven't yet validated the primary product.
- **Revisit trigger:** After the first honest Phase-1 real-data test is published (see D1, D2).

### C5. Pipx-installable wheel
- **What:** Publish `notanotherspotlight` to PyPI, user installs with `pipx install notanotherspotlight`, gets a global `ns` command.
- **Effort:** S (for pipx); Tauri shell is a separate L item.
- **Why:** Adoption friction. `uv sync` + `-m src.pipeline` is dev-only; nobody finds a product that requires that.
- **Why not yet:** Some pieces still assume repo-relative paths (see D4); clean up first.
- **Revisit trigger:** After D4 lands.

### C6. Tauri / Electron desktop shell
- **What:** Native desktop app with a search bar, results panel, file preview. REPL stays as CLI.
- **Effort:** L.
- **Why:** Your `CLAUDE.md` says "I want to launch it publicly." Neither recall-lite nor Fenn launched without a GUI. The REPL alone won't win non-dev users.
- **Why not yet:** Plumbing a whole front-end when the backend is still in motion is premature optimization.
- **Revisit trigger:** Backend API surface has stabilized (no search-layer changes in 30 days) and we have at least one happy Phase-1 user asking "where's the app?"

---

## D. Trust / positioning / measurement

### D1. Reproducible benchmark + README result table
- **What:** Pick a public dataset (Enron emails subset, or a couple of SEC 10-Ks), define 10–15 natural-language queries + ground-truth files, run the pipeline, paste a table into README.md with path + score + whether the right file was top-5.
- **Effort:** M.
- **Why:** rememex's README benchmark is the single most-quoted artifact in that repo. It's what makes LocalLLaMA readers trust the tool. Without one, we're another RAG demo.
- **Why not yet:** Router refactor changed retrieval shape; benchmark before-router would be misleading.
- **Revisit trigger:** Right now — the router is stable enough.

### D2. `Plans/Competitors.md` table
- **What:** NAS vs recall-lite / rememex / Fenn / Spotlight / semantra / ripgrep, on axes: offline, multi-lingual, video, audio, OCR, code search, MCP, platform, price.
- **Effort:** S.
- **Why:** Same trust reason as D1. Readers want to place us on a map.
- **Why not yet:** No reason. Small doc; just hadn't written it.
- **Revisit trigger:** Ship with D1.

### D3. License + privacy + telemetry statements
- **What:** `LICENSE` file (MIT or Apache-2.0), README header saying "nothing leaves your machine by default" + an enumerated list of every HTTPS destination in default mode (= zero when `LLM_PROVIDER=local`, one when cloud), explicit "no telemetry, ever" line in both README and config output.
- **Effort:** S.
- **Why:** Every single local-search launch on LocalLLaMA gets judged on this in the top comments. If we haven't nailed it before we announce, we lose the thread.
- **Why not yet:** Pre-launch work. Unblocked as soon as we're close to launch.
- **Revisit trigger:** Pre-public-release.

### D4. Drop hard REPO_ROOT assumptions
- **What:** A few paths (summary filenames, manifest key generation) implicitly assume ingest runs inside the NotAnotherSpotlight checkout. A user installing via pipx will not. Audit and fix.
- **Effort:** S.
- **Why:** Without this, C5 ships a pipx package that only works if you happen to have cloned the repo into `$(pwd)`. Embarrassing.
- **Why not yet:** Discovered mid-session; ignored scope was tighter.
- **Revisit trigger:** Before C5.

---

## E. Porting / local-first (from Plans/Port.md)

### E1. Qdrant local Docker + `.env` swap docs
- **What:** One-line in README, `docker run` snippet, confirm `QDRANT_CLUSTER_ENDPOINT=http://localhost:6333` works. (Code already supports it.)
- **Effort:** S.
- **Why:** Promise of [Plans/Port.md](Port.md) Phase 2. Users who try local Qdrant today discover it works but we never documented it.
- **Revisit trigger:** Any release note mentioning "local-first" needs this to be true, not aspirational.

### E2. `LLM_BACKEND=ollama` benchmarking against cloud
- **What:** Run `tests/retrieval_eval.py` + `tests/run_pipeline_eval.py` twice: once on Kimi, once on `LLM_PROVIDER=ollama` with Qwen 2.5 3B + 7B. Document the quality delta in [Plans/Port.md](Port.md).
- **Effort:** M (mostly waiting).
- **Why:** The question every LocalLLaMA user will ask: "how much worse is the local version?" We need the numbers before we can answer honestly.
- **Revisit trigger:** Pre-launch.

### E3. ColPali version bump decision (0.3 → 0.8+)
- **What:** Verify our `src/stage1_fast/model.py` call surface against colpali-engine 0.8. Bump pin if clean; pin at 0.x.x if we rely on a behavior that changed.
- **Effort:** S.
- **Why:** User explicitly asked "did we use 0.8 for colpali" — we're on `>=0.3`. Version drift is a quiet risk.
- **Revisit trigger:** Next dep-refresh pass.

---

## F. File-type coverage (not yet)

### F1. HTML (`trafilatura`/`selectolax`) + `.eml` email parsing
- **What:** Parse HTML with boilerplate-stripper (`trafilatura`); parse `.eml` via stdlib `email`. Route via the normal text/T1 path.
- **Effort:** S.
- **Why:** Small-business user has saved web pages and Outlook exports. rememex treats HTML as raw text (poor); we can do better cheaply.
- **Why not yet:** Not in the first router slice.
- **Revisit trigger:** First user who asks "why doesn't it see my emails?"

### F2. Legacy Office (`.doc`, `.xls`, `.ppt`)
- **What:** Fall back to `antiword` / `xls2csv` for pre-2007 Office formats.
- **Effort:** M.
- **Why:** Small-business target audience has decades of old `.doc` files. Fenn ships this; rememex doesn't.
- **Why not yet:** Libraries are fragile on Linux. Not our first priority.
- **Revisit trigger:** Any business-user demo that fails because of `.doc`.

### F3. Audio (`.mp3`, `.wav`, `.m4a`) via `faster-whisper` → `.alt`
- **What:** Mirror the video `.alt` sidecar pattern: whisper transcribes, writes a sidecar with `{start, end, text}` segments, Stage 3 ingests it.
- **Effort:** M.
- **Why:** Fenn's headline feature; not validated as top-demand in the recall-lite Reddit thread, so lower priority than I initially weighted.
- **Why not yet:** We explicitly parked audio/video for the router refactor per your instruction.
- **Revisit trigger:** One user who cares OR a product demo where audio search would be the hero feature.

### F4. EXIF reverse-geocoding + human date phrasing for images
- **What:** For JPEG/PNG with EXIF, extract GPS → reverse-geocode to city name via a local geocoder, extract capture date → human phrase ("summer morning"). Append to the image's T3 summary.
- **Effort:** S.
- **Why:** rememex ships this (pair of commits in `indexer/ocr.rs` + EXIF parsing) and users love it per their README.
- **Why not yet:** Not in the router slice; parked with audio/video.
- **Revisit trigger:** Second user who asks "can I find that photo from Brooklyn last summer?"

---

## G. Architecture decisions we promised to revisit

### G1. Two-pass vs one-pass ingest — revisit with data
- **What:** Current `Plans/Indexing Tiers.md` ships **one-pass** on the argument that T1/T2/T4-on-GPU are all fast, so only T3 costs time and most files skip T3. If we measure real-world T3-heavy corpora and see ingest taking >2 hours, switch to a two-pass: T1/T2/T4 stream in minutes, T3 enrichment runs in background.
- **Effort:** L (if triggered).
- **Why:** Explicit open question from the design session — don't overdesign before measuring.
- **Revisit trigger:** A real 10k+ file corpus measured under the current one-pass shape takes >120 min wall-clock AND users are waiting on the progress bar.

### G2. Transient T4 retirement for low-visual-score files
- **What:** After a T3 summary is generated for a file that was originally routed T4, delete its ColPali patches if `visual_score < 5`. Keeps visual-retrieval for content that genuinely needs it; frees disk for content that doesn't.
- **Effort:** M.
- **Why:** Storage tension explicitly discussed. Not in v1 because the cost gates + budget cap already prevent runaway growth.
- **Revisit trigger:** First user whose corpus T4 budget keeps hitting the cap.

### G3. Multi-tier additive T3 + T2 execution in the walker
- **What:** Today if decision.routes contains `["T3", "T2"]`, the walker picks T3 only. The T2 arm is deferred with a note. Wire both.
- **Effort:** S.
- **Why:** The Plans doc sells "multi-tier per file" and the router produces multi-tier decisions. Walker is the lagging piece.
- **Revisit trigger:** Soon — maybe next sprint after the backlog review. No external blocker.

### G4. Conditional ColPali patch pooling — PPTX / educational content only
- **Status:** **Partially shipped (2026-04-21).** `.pptx` only; `pool_factor=2`.
  Financial / receipt / scan paths deliberately unchanged.
  - [src/stage1_fast/index.py:index_file](../src/stage1_fast/index.py) — `pool_factor` kwarg (default 1)
  - [src/ingest/tier4.py](../src/ingest/tier4.py) — `POOL_SAFE_EXTS = {".pptx"}` gate
  - [tests/ingest/test_tier4_pooling.py](../tests/ingest/test_tier4_pooling.py) — 6 tests green
- **What's still open:** Expanding the whitelist (image-heavy DOCX decks, long
  lecture PDFs, etc.) is blocked on a real-data recall benchmark. First need:
  - (a) A small PPTX corpus with known ground-truth query→slide pairs.
  - (b) Run the ingest with `POOL_SAFE_EXTS` set vs not, measure recall@5.
  - (c) If it holds, cautiously add the next content class (e.g. image-heavy
    lecture DOCX) and rerun. Do NOT widen based on paper results alone —
    the FIQA warning in Clavié et al. 2024 is exactly the kind of
    corpus-specific surprise we don't want to re-hit.
- **Why the narrow first cut:** ext-based gating is robust, debuggable, and
  the user can see in the verbose ingest output exactly which files are pooled.
  "Is educational?" as a router signal would be fragile; skip until measured.
- **Revisit trigger:** after (b) above ships; OR first user whose T4 corpus
  budget keeps hitting the 5 GB cap primarily due to non-PPTX visual content.
- **Related:** See `IO/IO - Colpali.md` §"v1.1+ backlog → Token pooling" for
  the original flag-gated proposal. This item *narrowed* that proposal from
  "opt-in per user" to "auto-applied per ext whitelist."

---

## H. Test infrastructure

### H1. Integration test lane (`pytest -m integration`)
- **What:** Add `[tool.pytest.ini_options] markers = ["integration"]` to `pyproject.toml`. Tag `test_tier3.py` and `test_tier4.py` with `@pytest.mark.integration`. Default `just test` excludes them; `just test-integration` runs them. Goal: real Kimi/Ollama call + real ColPali model load in CI on a merge.
- **Effort:** S.
- **Why:** T3 + T4 are currently uncovered because unit tests can't mock the LLM/GPU cost cleanly. Integration tests are the right home.
- **Revisit trigger:** Before any pre-public release, or the first time a T3/T4 silently regresses.

### H2. `tests/retrieval_eval.py` baseline against the new router
- **What:** Run the retrieval-eval harness before and after major retrieval changes. Capture the recall@5 delta in the PR description.
- **Effort:** S.
- **Why:** This is the measurement mechanism for D1, E2, B1, B4. Without a baseline, every retrieval change is guesswork.
- **Revisit trigger:** Immediately before B1 or B4 lands.

---

## Next up (prioritized slice, ~1 sprint)

1. **A1** (Stage 3 video smoke test) — finish what we paused.
2. **G3** (T3 + T2 additive in walker) — ships what our design doc already promises.
3. **B3** (dim-mismatch detection) — cheapest preventive fix on the whole list.
4. **D1 + D2** (benchmark + competitors table) — trust artifacts before anything public-facing.
5. **C3** (JSON Schema for `.nasconfig.yaml`) + **C2** (REPL score breakdown) — small UX polish that makes the product feel finished.

Everything in B (except B3), C1/C4/C5/C6, E2/E3, F, and G1/G2 stays in backlog until a specific trigger fires.

---

## Nuked from the backlog (explicit rejects)

Kept here so we don't re-debate them. See also [Plans/Future Plans.md](Future%20Plans.md) and [Plans/Indexing Tiers.md](Indexing%20Tiers.md) for fuller context.

- **Archive walking** (`.zip`, `.tar.gz`) — scope creep + security surface.
- **Git-log messages appended to code embeddings** — wrong audience.
- **Silent file-size cap** — always warn, never drop.
- **Always-on reranker** — rememex shipped two ranking bugs from this.
- **Byte-based chunking for code** — multi-byte-unsafe.
- **VSCode extension** — MCP (C4) solves it better.
- **Windows-only OS dependencies** — rememex trapped themselves; don't.
- **Pooling ColPali patches** — destroys the late-interaction signal exactly where it matters (financial docs).
