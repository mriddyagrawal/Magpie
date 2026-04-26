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

### ~~B1. R1 — Adaptive query router~~ — ✅ Shipped 2026-04-24 (LIST_ALL slice). See [IO/IO - shipped_20Apr26.md §A8](../IO/IO%20-%20shipped_20Apr26.md). Verification pending E4 activation. Future expansion: CONCEPTUAL / EXACT_SYMBOL classes when B2 / B6 land.

### B2. R4 — HyDE gated on Conceptual queries
- **What:** For Conceptual-class queries only, use the local `ChatAgent` to produce a hypothetical declarative summary, embed *that*, and use it as the dense query. Raw query fed to BM25 side.
- **Effort:** M.
- **Why:** The asymmetric-search problem (declarative summaries in the index vs interrogative queries from users) — [Plans/Future Plans.md](Future%20Plans.md) item #2 is the same concept. rememex ships this gated (via their router), not always-on.
- **Why not yet:** Needs B1 first (we need the classifier to gate on). Plus a small prompt engineering loop.
- **Revisit trigger:** Right after B1 lands.

### ~~B3. R6 — Embedding-dimension mismatch detection~~ — ✅ Shipped 2026-04-25. See [IO/IO - shipped_20Apr26.md §H12](../IO/IO%20-%20shipped_20Apr26.md). Now any subsequent embedding-model swap raises `DenseDimMismatchError` with a re-index instruction, instead of silent garbage.

### ~~B4. Cross-encoder reranker~~ — ✅ Shipped 2026-04-24 (default off, opt-in via REPL `.rerank on`). See [IO/IO - shipped_20Apr26.md §A9](../IO/IO%20-%20shipped_20Apr26.md). Verification pending E4 activation. Future expansion: bigger model (`bge-reranker-v2-m3`) once `RERANK_MODEL` env-var swap is benchmarked.

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

### B10. Vocabulary-aware T2 summary templating
- **What:** When T2 generates a summary for a file with an obvious **content type** (a receipt, an invoice, a flight booking, a hotel reservation, a tax form, a transcript), prepend a small canonical-vocabulary tag to the summary body so retrieval matches category-style queries. Examples:
  - Receipt PDF whose body says *"Uber ride from GSP to Furman, $36.94"* → summary body starts with `"Receipt / expense / transaction record: ..."` then the original text.
  - Hotel booking PDF → `"Lodging receipt / hotel reservation / accommodation expense: ..."`
  - Flight ticket → `"Transportation receipt / flight booking / airfare: ..."`
- **Effort:** S to M. Detection is heuristic (filename hints + content patterns: `$\d+\.\d+`, `Order #`, `confirmation number`, `boarding pass`, etc.). The router already does similar work in `compute_sensitivity_score`; reuse those signals.
- **Why:** Real failure observed 2026-04-25 — query *"give me all the receipts that I have on my laptop by type"* retrieved 7 of ~15 actual receipts in top-20. The missing 8 were mostly Uber screenshot PNGs, Hotel YQuantum, Flight Yale-GSP, etc. Their summaries say things like *"Uber ride"* / *"American Airlines flight booking"* — the user's query expansion (`receipt, sales slip, voucher, expense`) didn't connect to the file vocabulary. Index-side enrichment fixes this once instead of asking the rewriter to enumerate every transit/lodging synonym at query time.
- **Why not yet:** Wait for user-side testing of the new ENUMERATION-MODE prompt fix (shipped 2026-04-25). If that alone makes the cherry-picking better, retrieval recall might be sufficient already. If real receipts still don't surface in top-20, ship B10.
- **Revisit trigger:** Run the receipts query post-prompt-fix. If <80% of corpus receipts are in top-20, ship B10.
- **Related:** B11 is the query-side counterpart (enrich the query instead of the index). They're complementary — both improve the same recall metric, attacked from opposite ends.

### ~~B12. T4 robustness on weird image variants~~ — ✅ Shipped 2026-04-26.
- **Root cause:** `processor.process_images` returned `pixel_values` as float32 regardless of how the model was loaded; the model was loaded with `torch_dtype=bfloat16` (CUDA) or `float16` (MPS). Forward pass blew up with `RuntimeError: expected mat1 and mat2 to have the same dtype, got: float != c10::Half`. Triggered on every image batch, but only surfaced when the dot-folder prune stopped catching the high-volume `.antigravity/.codex` case and real user content (`/home/astavak/Downloads/*.png`) reached T4.
- **Fix:** Added `_cast_batch_floats(batch, target_dtype)` in [src/stage1_fast/model.py](../src/stage1_fast/model.py) — casts every floating-point tensor in the batch to the model's dtype before forward, leaving int tensors (`input_ids`, `attention_mask`) untouched. Both `encode_images` and `encode_queries` call it now.
- **Tests:** 5 unit tests in [tests/test_stage1_fast_dtype.py](../tests/test_stage1_fast_dtype.py) — cast-to-half-leaves-ints-alone, mixed-dtype handling, no-op when already target, non-tensor metadata pass-through, float32 cast (for the CPU path).
- **Side effect — useful-dotfile routing:** Same debug pass found that `.bashrc` / `.zshrc` / `.gitconfig` / etc. were skipped at the router layer with "unsupported extension: (none)" because `peek()` and `decide()` didn't know about the walker's `_USEFUL_DOTFILE_NAMES` allowlist. Moved the allowlist into [src/router.py](../src/router.py) (single source of truth, walker now imports it) and added a name-based branch in `decide()` that routes these files to T1/T0 by size. 4 new regression tests in [tests/ingest/test_hidden_paths.py](../tests/ingest/test_hidden_paths.py).

### B11. Domain-aware synonym expansion in the rewriter
- **What:** When the rewriter's LLM detects that the user's query is about a recognizable category (receipts, courses, lectures, papers, music, photos), expand the keyword list with the **specific vocabulary that documents in that category actually use** — not just synonyms of the user's word.
  - "receipts" → also include `Uber ride, hotel reservation, flight ticket, airfare, rental car, lodging, transit, parking, food expense, voucher, booking confirmation, invoice, refund` ...
  - "lectures" → also include `slides, presentation, syllabus, lesson notes, handout, pptx, transcript`
  - "papers" → also include `paper, draft, manuscript, preprint, arxiv, study, paper.pdf`
- **Effort:** S. One paragraph addition to `REWRITE_SYSTEM_PROMPT` instructing the rewriter to generate domain-specific vocabulary, not just synonyms of the surface term. No code structure changes; pure prompt work.
- **Why:** Same root cause as B10 — vocabulary mismatch between user's category word and the documents' actual language. B10 fixes it at index time; B11 fixes it at query time. Both work; together they overlap usefully (a corpus indexed before B10 still benefits from B11).
- **Risk:** This is the kind of prompt change that drifts toward the synonym-enumeration anti-pattern. Discipline: tell the rewriter to use **one principle** ("expand to vocabulary documents actually use") rather than enumerating example domains. Trust the LLM to apply the principle universally; never list "receipts → Uber, hotel, flight" as an example pair the way I almost did in my earlier overshoot.
- **Why not yet:** Same trigger as B10 — wait for the ENUMERATION-MODE prompt fix to be tested first, then see if recall is good enough.
- **Revisit trigger:** Same as B10. Ship together if either is needed.

### B9. Answer-side citation verification — programmatic hallucination check
- **What:** After the LLM produces an answer, programmatically verify every page citation it emitted. For each `[book p. N / PDF p. M]` citation, look up page M's actual text (we already have the file content in scope at answer time — the lazy-chunk blocks include `## PDF page N (book p. M)` anchors), compute a similarity / containment score against the cited claim's surrounding sentences, and flag (or strip) citations that don't match.
- **Effort:** M to L. Multiple sub-pieces:
  - Citation parser: regex `(\[book p\. (\d+) / PDF p\. (\d+)\])` plus surrounding-sentence extractor.
  - Page-text lookup: maintain a `pdf_path → {pdf_page: text}` map built from the lazy-chunk content blocks before the LLM call.
  - Similarity / containment metric. Cheapest reasonable: extract proper-noun + numeric tokens from the cited sentence, check if ≥50% appear in the cited page text. Better: small cross-encoder pass `(claim, page_text) → score` (we already have ms-marco-MiniLM loaded for B4 rerank — reuse it).
  - Threshold + behavior: above threshold → keep citation as-is; below → strip the citation (so the answer text loses the false reference but the user still sees the source file in `sources_used`); if many citations fail → warn the user inline that the answer may be partially ungrounded.
  - Optionally: programmatically rewrite `sources_used` so each cited file has only its **verified-cited** pages listed.
- **Why:** Real hallucination caught 2026-04-25 — LLM answered "what's a Dirac delta function?" with content from BOTH Griffiths electrodynamics AND UnderstandingDeepLearning textbooks but listed only Griffiths in `sources_used` and attributed all citations (including a "Machine Learning Application" bullet that came from the deep-learning textbook) to Griffiths page 440/454. The cited pages of Griffiths don't actually contain ML content. This shape of hallucination is the most dangerous: well-formatted, plausible, with real-looking page numbers — only catchable by checking the actual file. Prompt-level "strict grounding rules" (shipped 2026-04-25, see [IO §H14](../IO/IO%20-%20shipped_20Apr26.md)) reduce the rate but don't guarantee correctness.
- **Why not yet:** Prompt-level constraints are the cheaper first lever — they're free, easy to iterate, and effective enough for most LLMs (especially paid ones like Kimi). Citation verification is necessary only if hallucinations persist after (a) strict prompt rules and (b) using a more disciplined LLM. Build this if real-data testing shows the prompt + Kimi combination still produces wrong-source citations.
- **Revisit trigger:** A reproducible hallucinated citation on Kimi (or another paid model) where the cited page text does not match the cited claim. Don't pre-build before that signal.
- **Related:** **H9** (answer-prompt de-hacking) and **H14** (strict grounding rules in answer prompt) are the cheap upstream mitigations. B9 is the structural belt-and-suspenders.
- **What:** Upfront overlapping token-window chunks á la [Semantra](https://github.com/freedmand/semantra) (default `128_0_16`) for text-native files where the **lazy** approach (H13, shipped 2026-04-25) doesn't apply: research papers, dense unstructured docs, files without bookmark TOCs. Each chunk → its own Qdrant point with `page_num` payload.
- **Effort:** M.
- **Why lazy isn't enough for these files:** The lazy approach (H13) only kicks in *after* a file has been retrieved at the index level. For research papers / transcripts / no-TOC PDFs, the relevant term isn't in the file-level summary, so retrieval can't find the file at all → lazy never gets a chance. Upfront chunking is the only way to make sub-section terms findable.
- **What's deliberately NOT in scope (covered by lazy, H13):**
  - Textbooks / manuals with bookmark TOCs (file findable via TOC in summary; lazy picks the right page at answer time)
  - Short docs (<10 pages of dense content; T2's single embedding is sufficient)
- **Why not yet:** No observed failure on the user's corpus that fits the "research paper / no TOC / dense" shape. Storage cost for B8 on the 3 textbooks would be ~80 MB; cost on a typical research-paper-heavy corpus would be ~5-10 MB per paper.
- **Router-side trigger needed first:** add a "would benefit from upfront chunking" flag to the router decision (`text_density > N AND page_count > 5 AND has_bookmark_toc == False`). Ship that as a logging-only signal first, see how often it fires on real corpora, then build B8 if the flag fires often enough to matter.
- **Revisit trigger:** A real query against a research-paper-shaped file misses because of the dilution. The trigger: user asks "did this paper use ResNet" → wrong answer → that's the signal.
- **Related:** Complements **H13** (lazy chunking, shipped). The two together = "upfront chunk where you must, lazy-chunk where you can."

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

### ~~C7. Default ignore patterns for asset / decorative content~~ — ✅ Shipped 2026-04-21. See [IO/IO - shipped_20Apr26.md §A7](../IO/IO%20-%20shipped_20Apr26.md). Re-ingest pending; unblocks E4.

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

### ~~E4. Qdrant standalone binary upgrade — reclaim fast_tier storage~~ — ✅ Wiring shipped 2026-04-24. See [IO/IO - shipped_20Apr26.md §H10](../IO/IO%20-%20shipped_20Apr26.md). **User-side activation pending:** `just qdrant-install && just qdrant-up`, then `.env` swap to `QDRANT_PROVIDER=cloud` + `http://localhost:6333`, then re-ingest. Until activated, fast_tier stays at 1 MB/page.

### E5. Bundle Qdrant binary for end-user distribution (future)
- **What:** When packaging the app for non-developer users (pipx wheel / Tauri shell), embed the Qdrant binary inside the distribution and spawn it on app launch via the same subprocess pattern E4 introduced. End user installs the app like any other (`pipx install notspotlight` or download a `.dmg`/`.exe`); the app spawns Qdrant transparently in the background. No Docker, no separate Qdrant install step, user sees nothing beyond a one-time "setting up your local index..." spinner.
- **Effort:** M. The startup logic exists in `just qdrant-up`; it needs to move into Python (so the wheel can launch it) and gain platform-aware binary selection (Linux/macOS/Windows).
- **Why:** Docker is a non-starter for the small-business / student persona. Bundling is how every tool with a native dep ships (Ollama, LanceDB-Rust core, VS Code's Electron). Single-install user experience is non-negotiable for launch.
- **Implementation sketch:**
  1. Per-platform binary selection at install: download once into `~/.local/share/notspotlight/qdrant/<arch>/` (or bundle inside the wheel for the smaller ones).
  2. Python helper `notspotlight.qdrant_proc.start()` wraps the same subprocess + pidfile logic as `just qdrant-up`.
  3. App startup calls `start()`, app shutdown sends SIGTERM. Crash detection + auto-restart optional v1.
  4. Wheel/`.dmg` payload size tradeoff: ~30 MB binary per platform — bundle if total stays <100 MB, otherwise auto-download.
- **Why not yet:** No public users yet; CLI dev-flow (E4 `just qdrant-up`) is sufficient until shipping. Activates with **C5** (pipx packaging) and/or **C6** (Tauri shell).
- **Revisit trigger:** Right before C5 or C6 ship.
- **Related:** Builds directly on E4's subprocess pattern. The Python `start()` helper IS the same code that `just qdrant-up` runs today, just relocated from the justfile into a module.

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

### G5. Vector DB choice — stay on Qdrant, do NOT migrate to LanceDB (decision record 2026-04-21)
- **Status:** Decided. Not an open item. Keeping here so we don't re-debate it in 3 months when LanceDB marketing surfaces again.
- **Context:** Investigated LanceDB as a replacement for Qdrant local after discovering local mode silently drops quantization (see **E4**). Surface reason: LanceDB advertises fp16 and PQ natively in a serverless library — which is exactly the hole in Qdrant local.
- **Two concrete findings that killed the migration:**
  1. **LanceDB fp16 is broken in their own tracker.** GitHub issue [lancedb/lance#2120](https://github.com/lancedb/lance/issues/2120) — "db query error when creating GPU index with FP16 vectors". Opened Feb 2025, **still open** April 2026, filed by this repo's author. Workaround documented there is "don't specify fp16 in schema, let it silently convert to fp32" — which defeats the reason to migrate. The feature we'd be migrating *for* doesn't reliably work in their library either.
  2. **LanceDB's ColPali story is O(N) linear scan, not an indexed MaxSim.** Per their own Sep 2024 engineering blog ("Late Interaction & Efficient Multi-modal Retrievers"), the recommended pattern is:
     ```python
     r = table.search().limit(None).to_list()    # fetch ALL docs
     scores = CustomEvaluator(is_multi_vector=True).evaluate_colbert(...)
     ```
     They reported **34 seconds for 556 documents** — MaxSim done in Python, not a vector index. Their proposed optimization is "use FTS or single-vector dense as a pre-filter to top-100, then MaxSim rerank on the 100" — a workaround that compromises recall and is not native late-interaction indexing. As the corpus grows, query time grows linearly. Our [src/stage2/fast_db.py ensure_fast_collection](../src/stage2/fast_db.py) uses Qdrant's `MultiVectorConfig(comparator=MAX_SIM)`, which is a **real HNSW-indexed MaxSim** — O(log N) queries regardless of corpus size. That is the single most important property of the fast tier at scale.
- **Scaling math, one-shot:**

  | Corpus size | Qdrant HNSW MaxSim | LanceDB linear MaxSim |
  |---|---|---|
  | 1,000 pages  | <100 ms / query  | ~60 s / query |
  | 10,000 pages | <200 ms / query  | ~10 min / query |
  | 100,000 pages | <500 ms / query | effectively unusable |

  (LanceDB's pre-filter workaround rescues the small end at the cost of recall; it doesn't rescue the large end.)
- **Decision:** Qdrant is the right DB. Storage gap is solved by **E4** (Docker server → real quantization), not by DB migration.
- **Revisit trigger:** One of the following would reopen the debate:
  (a) Qdrant drops / deprecates `MultiVectorConfig(MAX_SIM)` or removes HNSW-indexed multi-vector support.
  (b) LanceDB's fp16 bug closes AND they ship indexed multi-vector (not linear-scan).
  (c) We add a columnar-analytics use case that needs Lance's format natively (e.g. dataset versioning for ML training). At that point LanceDB may pay for itself elsewhere; it still wouldn't replace the fast tier.

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

**Updated 2026-04-25** based on what shipped this session (B1, B4, C7, E4 wiring, plus the H1-H11 cluster — see [IO/IO - shipped_20Apr26.md](../IO/IO%20-%20shipped_20Apr26.md) §A8/A9/A7/H1-H11).

**Immediate (user action, not code):**
1. **Activate E4** — `just qdrant-install && just qdrant-up`, swap `.env` to localhost, re-ingest one root. Without this, fast_tier stays uncompressed at 1 MB/page.
2. **Run `just recover-fast-tier`** to restore the 42 lost `fast_indexed_at` rows from the H6 bug. Requires closing the REPL first (Qdrant local single-writer lock).

**Next code work, ordered:**
1. **B3** (dim-mismatch detection) — S effort, single biggest preventive fix. Ship before any embedding-model swap.
2. **D1 + D2** (benchmark + competitors table) — trust artifacts before public release. Now that the search/answer stack has stabilized (B1, B4, prompts), the benchmark numbers won't be moving targets.
3. **G3** (T3 + T2 additive in walker) — ships what `Plans/Indexing Tiers.md` already promises. Walker currently runs only the primary tier; multi-tier files leave their non-primary work undone.
4. **A1** (Stage 3 video `.alt` smoke test) — finish what we paused before the router refactor.
5. **C2** (REPL score breakdown) + **C3** (.nasconfig.yaml JSON Schema) — small polish that makes the product feel finished.

**Pending real-data signal (don't pre-build):**
- **B8** (Semantra-style chunking for long text-native PDFs) — only worth it if the textbook section-level queries (e.g. "what's in chapter 13 of Taylor") keep failing after E4 activation. Confirmed root cause for the Liouville-style failure; storage cost is ~80 MB for >50-page threshold (cheap relative to E4 savings). Build when the user asks about chapter content and the file-level summary keeps coming up short.
- **B2** (HyDE on conceptual queries) — only worth it if B1+B4 still misses on factoid queries the user actually types. Depends on extending B1's classifier with a CONCEPTUAL class first.
- **Sibling-density rule tuning** (mediasources-4ed parent folder still slips through because it has 2 CSVs + 1 TXT among its hundreds of decorative images, defeating the strict "0 documents" gate). Fix: switch from `0 docs` to a ratio-based rule (e.g. `≥10:1 image:doc`). Real bug observed 2026-04-25; flagged but not a tagged backlog item yet.
- **Default rerank to OFF** instead of opt-in. The auto-suppression for LIST_ALL helps, but rerank also collapses duplicate content (scanned + text-native versions of the same book) and sometimes returns thinner answers as a result. Watch real-data behavior; flip the default if regressions outnumber wins.

**Long-tail (won't trigger soon):**
- B5, B6, B7 — each waits for a measurable failure mode in real use.
- C1 (filesystem watcher), C4 (MCP server), C5 (pipx wheel), C6 (Tauri shell) — adoption-path items for after Phase-1.
- E2 (Ollama benchmarking), E3 (ColPali version bump), E5 (bundle Qdrant for end-users) — pre-launch chores.
- F1-F4 (file-type coverage), G1-G2 (architecture revisits), H1-H2 (test infrastructure) — opportunistic.

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
- **LanceDB migration** (rejected 2026-04-21) — fp16 bug unresolved in their tracker, ColPali story is O(N) linear-scan not indexed. See **G5** for the full decision record.
