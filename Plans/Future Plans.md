# Future Plans

Ideas we've decided against doing *right now* but want to revisit. Every entry must include **why** we'd make the change — not just the change itself — so future-us can judge whether the reason still applies.

Plan numbers are stable IDs (referenced from code comments and commit messages). Don't renumber. Plans are appended in roughly chronological order; the index below is the recommended way to browse by theme.

---

## Topic index

Each plan is tagged on its own heading with all the topics it touches. A plan can appear under multiple themes — the index below points at it from each. Implemented plans get a ✅; everything else is still open.

### 🔍 Retrieval quality — how search behaves
What gets returned for a query: ranking, fusion, agentic loops, query rewriting, asymmetric search, reranking.

- **#2** Asymmetric-search-aware query path (HyDE)
- **#3** Agentic retrieval loop (top-k → fetch more on demand)
- **#5** Hierarchical chunking — the "400-page manual" problem
- **#6** Cross-encoder reranker (Stage 3.5)
- **#7** Structured payload filtering on date / merchant
- **#8** Smarter T0 / large-CSV retrieval
- **#9** Liquid AI LFM2 model evaluation *(also: Models)*
- **#17** ✅ CSV redesign — row-window retrieval *(also: Indexing, CSV)*

### 🗂 Indexing pipeline — what enters the index, how
File classification into tiers, summarization, manifest lifecycle, ingest robustness.

- **#1** Swap Kimi-vision PDF fallback for Marker (layout-aware OSS OCR) *(also: PDF)*
- **#4** ✅ Data lifecycle, updates & deletions (the manifest)
- **#5** Hierarchical chunking *(also: Retrieval, PDF)*
- **#7** Structured payload filtering *(also: Retrieval)*
- **#11** Unify orphan-cleanup pattern across `summaries` and `fast_tier` *(also: Qdrant)*
- **#12** Routing data files (CSV / JSON / XML / Parquet) properly through tiers *(also: CSV)*
- **#14** Promote `MAGPIE_DEV_USE_MTIME` to a user-facing setting *(also: UI, Config)*
- **#17** ✅ CSV redesign — proper summaries at ingest *(also: Retrieval, CSV)*
- **#21** Surface drift events: warn before silently dropping vanished files *(also: UI)*
- **#24** Batch indexing — knobs, per-batch progress, error handling *(also: UI, Perf)*
- **#25** Answer-step output schema — empirically evaluate two open choices *(also: Models, Evaluation)*
- **#26** Bring-your-own cloud API key — Settings → Advanced → API Keys *(also: UI, Config, Security)*
- **#27** ⚠️ Abort in-flight queries on retype / blur (UI URGENT) *(also: Perf, Pipeline)*

### 🖥 User experience / UI
Settings panels, in-app warnings, anything the user sees.

- **#14** Promote `MAGPIE_DEV_USE_MTIME` to a user-facing setting *(also: Indexing, Config)*
- **#15** Auto-promotion of nested exclude paths into sub-roots *(also: Config)*
- **#16** LLM / inference settings UI + cross-provider thinking-mode unification *(also: Models, Config)*
- **#21** Surface drift events: warn before silently dropping vanished files *(also: Indexing)*
- **#24** Batch indexing — surface upsert-phase progress + bad-file isolation *(also: Indexing, Perf)*
- **#26** Bring-your-own cloud API key — Settings → Advanced → API Keys *(also: Config, Security)*
- **#27** ⚠️ Abort in-flight queries on retype / blur (UI URGENT) *(also: Perf, Pipeline)*

### 📦 Packaging, distribution & process lifecycle
How Magpie ships and runs as an end-user app — from installer through process management.

- **#10** Self-contained packaging (bundled Python & sidecar)
- **#13** Daemon as a true OS service (launchctl / systemd) *(also: Daemon)*
- **#19** Post-packaging configuration story — replace `.env` with structured config + OS-keychain secrets *(also: Security, Config)*
- **#20** Qdrant process lifecycle — who starts, stops, and health-checks the local server *(also: Qdrant, Daemon)*

### 🔒 Security & privacy
Auth, hardening, secret storage.

- **#18** Lock down Magpie's Qdrant — auth + bind hardening *(also: Qdrant)*
- **#19** Post-packaging configuration story (keychain secrets) *(also: Packaging, Config)*

### 🤖 Models & providers
LLM/embedding model swaps, evaluation, cross-provider feature parity.

- **#2** Asymmetric models / HyDE *(also: Retrieval)*
- **#6** Cross-encoder reranker *(also: Retrieval)*
- **#9** Liquid AI LFM2 model evaluation
- **#16** LLM / inference settings UI + thinking-mode unification *(also: UI, Config)*
- **#22** Adding a new local LLM — playbook (Qwen2.5-VL, LFM2-VL, MiniCPM-V, …)
- **#23** MLX backend (Apple Silicon opt-in) for raw speed *(also: Config)*

---

## 1. Swap Kimi-vision PDF fallback for Marker (layout-aware OSS OCR)

**Tags:** indexing · pdf

**What:** Replace (or add an option alongside) the current "render PDF pages → Kimi vision" fallback with [Marker](https://github.com/VikParuchuri/marker). Marker runs small specialized models locally and emits clean markdown with tables / math / figures preserved.

**Why we might want this:**
- **Determinism.** OCR output is stable across runs; vision-LLM output drifts. For a local search index we'd rather the extracted text not change every time we re-ingest.
- **Cost & offline.** No API call per scanned page. Pure local compute after first-time model download (~2–5 GB). Matters once the corpus grows to thousands of scanned PDFs.
- **Provider independence.** Not tied to Kimi / Moonshot uptime or pricing.
- **Layout / math / tables.** Marker is purpose-built for academic-style documents; vision LLMs can miss table cell boundaries and equation structure.

**Why we did NOT do it now:**
- Kimi vision is already in the pipeline for images; scanned-PDF support is just "render to PNG, send to the same path" — ~10 lines of code, no new heavy dep.
- Marker's weak spot is exactly our failing test files' profile: **receipts and handwriting**, where vision LLMs meaningfully outperform layout-aware OCR.
- Model download + ~5–15 s/page CPU inference is noticeable friction for a Stage 1 prototype.

**When to revisit:** corpus > low-thousands of scanned printed docs, or Moonshot cost/latency becomes a pain point, or determinism starts to matter (e.g. we want to diff ingestions).

---

## 2. Asymmetric-search-aware query path (or HyDE)

**Tags:** retrieval · models

**What:** When we add the retrieval stage, don't just embed the raw user question and ANN-search against the summary embeddings. Either (a) pick an embedding model explicitly trained for question↔document asymmetric retrieval, or (b) do **HyDE**: have a cheap LLM (GPT-4o-mini / Haiku / Kimi-Flash) write a *hypothetical summary* that would answer the question, embed *that*, and search with it.

**Why:**
- **The vector-math problem.** We are storing embeddings of *declarative summaries* ("This document is a 2026 Breeze Airways flight receipt from Greenville to Hartford…"). A raw user query is *interrogative* ("when does my passport expire?"). In vector space, questions and declarative statements don't naturally sit near each other — this is called **asymmetric search**. The DB can happily retrieve the wrong thing (e.g. an FAQ) because it sounds like a question, not because it contains the answer.
- **Why asymmetric models fix it:** models like `e5-*`, `bge-*`, `nomic-embed-text` with `query:` / `passage:` prefixes, or OpenAI's `text-embedding-3-*`, are trained with question-document pairs and map both sides into the same neighborhood despite their surface-form difference.
- **Why HyDE works without swapping models:** the hypothetical summary is a *declarative* string in the same shape as what we stored, so we're doing summary-vs-summary similarity — a much stronger signal than question-vs-summary.

**Why we did NOT do it now:**
- Stage 1 is just summarization. We don't have a retrieval stage yet. Picking the strategy now would be premature — we need to see real failure modes on real queries against our Qdrant index first.

**When to revisit:** as soon as Stage 3 (query) starts returning the wrong file. First try: switch to an asymmetric model and measure. If that's not enough, layer HyDE on top.

**Note on Qdrant:** Qdrant is a good choice but doesn't fix this — asymmetric search is a property of the embedding model, not the DB. Qdrant will happily serve whatever vectors we ask it to; the quality question sits upstream.

---

## 3. Agentic retrieval loop (top-K = 5 → fetch more on demand)

**Tags:** retrieval

**What:** In Stage 3, don't hand the final LLM a fixed top-K of retrieved summaries. Set a default top-K (e.g. 5) but expose a tool — `fetch_next_documents(offset, k)` — that the model can call itself when it decides the current batch doesn't contain the answer. The model loops: read → decide "not enough info" → tool-call for more → read → answer, or exhaust the index.

**Why:**
- **Context efficiency.** Stuffing the prompt with top-50 every time wastes tokens on irrelevant files and dilutes the signal. Most queries are answered by 1–3 files; pay for more only when needed.
- **Hallucination resistance.** If the answer isn't in the first batch, a non-agentic setup forces the LLM to either guess or flatly say "don't know." The agentic version gives it a concrete action — fetch more — before it resorts to either.
- **Graceful exhaustion.** The loop has a natural termination ("no more offsets") which maps cleanly to an honest "I don't have this in your files" response with sources.
- **Cheap to build with PydanticAI.** Tools on `Agent` are just decorated functions; the loop is free.

**Why we did NOT do it now:**
- Requires Stage 2 (embedding + Qdrant index) to exist first. Before retrieval is real, an agentic retrieval loop is science fiction.

**When to revisit:** as part of Stage 3. Start with a simple top-K baseline to get a working end-to-end, then upgrade to the agentic loop once we have queries to measure against.

---

## 4. Data lifecycle, updates & deletions — IMPLEMENTED (see `src/manifest.py`)

**Tags:** indexing · ✅ implemented

> **Promoted from Future Plans to shipped.** `Test Summaries/_manifest.json` now
> tracks every source file's `size`, `summary_file`, `summarized_at`, `ingested_at`.
> Stage 1 skips files whose size hasn't changed (no hashing in the common case).
> Stage 2 skips summaries already in Qdrant. Missing source files are hard-deleted
> from both the manifest, `Test Summaries/`, and Qdrant. The simplification from
> the original design: we use `size` alone for change detection (dropped `mtime`
> and lazy-`digest` comparison), because byte-identical size changes are rare in
> practice and one column is easier to reason about. Everything below is the
> original design doc, kept for context.

### Original design (kept for reference)

**What:** Track every summarized source file in a **manifest** so we can answer three questions cheaply at sync time: (a) which files on disk are missing from the DB? (b) which files on disk have changed since we last summarized them? (c) which DB rows point at files that no longer exist on disk?

**Proposed shape:** `Test Summaries/_manifest.jsonl` (or a SQLite DB once we have > ~10k files). One row per source path:

```json
{
  "path": "Test Content/Flight GSP - Hartford Receipt.pdf",
  "mtime": 1712899200.0,
  "size": 17616,
  "digest": "8c2bbf673a91ef8d",
  "summary_created_at": "2026-04-12T17:59:00Z",
  "status": "active"
}
```

**Sync algorithm (the cheap / "rsync-style" path):**

1. Walk the target directory.
2. For each file, `stat()` it and look up `path` in the manifest.
   - **mtime + size match** → skip. No hashing, no API call, no DB write. This is the 99% case and is cheap.
   - **mtime or size differ** → rehash. If the new digest matches the manifest's digest (metadata drift only — touch, rsync, backup restore), just update `mtime`/`size` in the manifest.
   - **digest differs** → the content genuinely changed. Re-summarize, write a new `Test Summaries/<new-digest>.md`, update the manifest row, and mark the old digest's DB row as `status=deprecated` (keep the vector; filter it out at retrieval time by default).
   - **No manifest row** → new file; summarize from scratch, add row.
3. After walking, any manifest row whose `path` no longer exists on disk → mark `status=deleted`. Keep the summary file and the DB row, but filter them at retrieval.

**Why we want a manifest (vs. re-hashing everything or just trusting mtime):**

- **Rehashing is expensive.** A 500 MB PDF corpus is seconds to `stat`, minutes to SHA-256 end-to-end. stat-only is what makes a "sync" feel instantaneous.
- **mtime alone is unreliable.** `rsync`, `touch`, `cp -p`, backup/restore, and Dropbox can all clobber mtime without changing bytes, or leave mtime stale after a genuine change. We use mtime+size as a **pre-filter**: if they match, trust cache; if they differ, verify with a hash. This is exactly how `git status`, `cargo`, and `make` do it.
- **Deletions become explicit.** Without a manifest, a deleted source file is invisible — the summary and vector just live on forever as ghost answers. With the manifest we can answer "is this DB row still valid?" in O(1).
- **The "two passports" case is handled naturally.** An expired passport and an active one have different bytes → different digests → two rows. Retrieval filters by `status=active` by default; a power query can ask for everything including `deprecated`.

**Why we did NOT do it now:**

- Stage 1 currently uses the content-addressed `Test Summaries/<digest>.md` layout as a de facto cache. It works for the "stateless re-run everything" case, which is where we are. The manifest only pays off once we have (a) a vector DB that can hold stale rows, and (b) corpora that are big enough that rehashing hurts.
- Premature: before Stage 2 exists, there is no vector DB to keep in sync with the filesystem. Filesystem-only consistency is already handled by the hash-keyed summary files.

**When to revisit:** immediately after Stage 2 lands. The manifest should be written at the same time as the first vector insertion — otherwise we build up "ghost" vectors on day one.

**On diff-as-summary-field (a sub-idea we considered and rejected for now):** instead of overwriting the summary when a file changes, generate a "what changed since the previous version" field via a small LLM call that reads both the old and new summaries. We're NOT doing this because (a) it's an extra API call per change, (b) most queries want the current state, not a changelog, and (c) git or the filesystem version history already answers "what changed?" outside the RAG path. Reconsider if users start asking historical questions like *"what did my passport look like before it expired?"*.

---

## 5. Hierarchical chunking (the "400-page manual" problem)

**Tags:** indexing · retrieval · pdf

**What:** For any source file above a size threshold (proposed: ~50k characters or ~50 PDF pages), don't produce a single `FileSummary`. Instead build a two-level hierarchy:

1. **Chunk summaries** — one `FileSummary` per chapter / section / natural unit. Each chunk row in the DB stores: `parent_file_id`, `chunk_index`, `char_start`, `char_end`, `page_start`, `page_end`, and `level="chunk"`. Embed the chunk summary.
2. **Document summary** — one top-level `FileSummary` per file, but **derived from the chunk summaries** (LLM reads the ~20 chunk summaries and produces a rolled-up doc summary), not from the raw 400 pages. Stored with `level="document"`.

Both levels live in the same vector collection, distinguished by the `level` metadata field.

**Chunking strategy by file type:**

- **PDFs** — use the PDF outline / bookmarks if present (natural chapter boundaries). If not, fall back to fixed-size char windows with overlap (e.g. 8k chars, 500 overlap).
- **DOCX** — split by Heading 1 / Heading 2.
- **Markdown** — split by `#` / `##` headings.
- **Code files** — split by top-level function / class.
- **Text with no structure** — fixed-size windows with overlap.

**Retrieval behavior (changes stage 3):** queries embed and search the full collection. Chunk hits score higher for specific factoid questions (they have denser, more relevant summaries); document hits score higher for "what is this file about" / "list all files on topic X" questions. A useful default: return the union of top-k at each level, deduplicated by parent file.

**Why we want it:**

- **Specificity.** A single summary of a 400-page textbook is useless for "what does Chapter 12 say about asymmetric search?". Chunk summaries let that question hit the right 8 pages, not the wrong 400.
- **Retrieval precision.** More, smaller, more specific vectors → tighter neighborhoods in embedding space. Asymmetric-search problems (see item #2 above) get worse as summaries get more generic; chunking is a direct mitigation.
- **Context-window efficiency in Stage 4.** Stage 4 currently caps each file at 25k chars. For a 400-page book that means it silently truncates to the first ~25 pages. Chunk retrieval instead lets Stage 4 receive exactly the relevant 8–16 pages of the book and leaves the rest of the context budget for other files.

**Contract change for Stage 4 (worth doing now, even if we don't implement chunking yet):** today Stage 3 hands Stage 4 a `list[str]` of paths and Stage 4 re-reads whole files. Once chunking exists, Stage 3 must hand down `list[Retrieval]` where `Retrieval` is:

```python
class Retrieval(BaseModel):
    path: str
    char_range: tuple[int, int] | None = None  # None = whole file
    page_range: tuple[int, int] | None = None
```

If `char_range` or `page_range` is set, Stage 4 reads only that slice instead of the whole file. `answer.py`'s content-dispatch grows a sliced-read variant. If both are `None`, behavior is today's "whole file" behavior. This is a small change to `build_content_blocks(path, max_chars, max_pdf_pages)` — add an optional `char_range` kwarg.

**Why NOT one-mega-summary-containing-all-chunk-summaries:** we considered it and rejected it. Concatenating 20 chunk summaries into one giant blob gives you a top-level row that is too long to be a useful summary (bad UX when shown to a user) and too averaged-out to be a useful vector (the embedding smears across everything). The two-level approach gives both a genuinely-useful short doc summary AND retrievable per-chunk specificity. The chunk summaries are the primary retrieval target; the doc summary is a "what even is this file" fallback.

**Why we did NOT do it now:**

- No file in `Test Content/` is above the threshold. A 14-page math handout is still one good summary; we'd be implementing a solution to a problem we don't have.
- Requires Stage 2 (vector schema with `parent_file_id` / `chunk_index` metadata fields) and Stage 3 (retrieval that understands multiple levels). Can't meaningfully test chunking without those.
- The chunking-boundary logic is file-type-specific and will absorb real engineering time once we commit to it.

**When to revisit:** as soon as the first real file > 50 pages lands in the index AND retrieval on that file starts returning the generic summary for specific questions. Both conditions together — not either alone.

---

## 6. Cross-encoder reranker (Stage 3.5)

**Tags:** retrieval · models

**What:** Insert a reranking step between Qdrant retrieval and Stage 4. Today the pipeline pulls top-k=5 from Qdrant and hands them straight to the answerer. Instead: pull top-k=50 from Qdrant (cheap), then run a **cross-encoder** (e.g. `bge-reranker-v2-m3` or Cohere's Rerank API) over `(query, doc)` pairs to re-score and pick the top 5 to actually feed Stage 4.

**Why:**
- **The bi-encoder ceiling.** Dense + BM25 hybrid (what we have) is fast because both query and documents are encoded *independently* — but that independence is exactly what limits accuracy. The retrieval eval on receipts 30-40 hit this directly: queries like "Breadfast order delivered to New Cairo on 25 May 2022" landed in the right semantic neighborhood (other Breadfast deliveries) but couldn't pick out the specific one. A cross-encoder reads the query and the candidate document *together* and notices "the question said *25 May 2022* and only one of these summaries contains that exact string."
- **Cheap to add given the architecture.** Stage 3 already has the seam: `run_search(sq, top_k)` returns ranked candidates that flow into `answer_question`. Reranker plugs in as `rerank(query, candidates) -> candidates[:top_k]` between those two calls. No schema or DB changes.
- **Receipt-shaped problem fits perfectly.** Many similar-looking summaries (Breadfast, Breadfast, Breadfast…) where the discriminator is a small handful of tokens. Cross-encoders are exactly the tool for "look at the query and the candidate and judge specificity."

**Why we did NOT do it now:**
- We just diagnosed (and are mid-fixing) a more upstream problem: `key_entities` and `identifiers` weren't even in the embedded text, so neither dense nor BM25 ever saw the discriminating tokens. A reranker on top of an index that's missing those tokens fixes nothing — garbage in, garbage out.
- Adds per-query latency (small local model: ~50–200ms; Cohere API: ~300–500ms) and either a new local dependency (`sentence-transformers` reranker) or a new paid API.
- Better to first re-measure retrieval after the discriminator fix; the lift may be enough that reranker complexity isn't justified yet.

**When to revisit:** after re-running `tests/retrieval_eval.py` against the new (post-discriminator-fix) index. If recall@5 is still leaving meaningful misses on disambiguator-heavy queries, add the reranker. Start with `bge-reranker-v2-m3` (small, local, free) before reaching for paid APIs.

---

## 7. Structured payload filtering on extracted transaction date / merchant

**Tags:** indexing · retrieval

**What:** When Stage 1 produces a `FileSummary`, extract structured fields — at minimum a normalized `transaction_date` (ISO 8601) and `merchant_name` — and store them as Qdrant **payload** alongside the vector. Then Stage 3 query rewriting can emit *filters* (e.g. `transaction_date >= 2022-05-01 AND transaction_date < 2022-06-01`) that Qdrant applies pre-search. This is fundamentally different from "boost newer documents": boosts blend signals, filters scope the search.

**Why:**
- **Date-scoped queries are inherently filter-shaped, not similarity-shaped.** "What did I buy in May 2022?" is a *constraint*, not a vibe. Forcing it through cosine similarity is hoping the embedding model encoded the date as a vector neighborhood — which it doesn't, reliably.
- **Merchant-scoped queries collapse the candidate set massively.** "Show me all Breadfast receipts" should literally be `merchant_name == 'Breadfast'`, not "find vectors close to the word Breadfast." Filtering before scoring beats reranking after scoring for hard categorical constraints.
- **Qdrant supports it natively.** `payload_index` + `must` clauses are first-class. No new infra.
- **The "freshness boost" pattern doesn't apply to receipts.** A 2022 receipt about a 2022 trip is more relevant for "what did I spend in Alexandria last spring?" than yesterday's grocery receipt — file mtime is the wrong signal entirely. The right signal is the transaction date *inside* the document.

**Why we did NOT do it now:**
- Requires (a) Stage 1 to reliably extract a normalized date from arbitrary receipt formats (DD/MM/YY, "08-May-21", "10 December 2023" all show up in our 521-file corpus), (b) a query-rewrite step that classifies the user question into "needs date filter" vs "doesn't" and emits the right Qdrant filter, and (c) graceful fallback when extraction fails.
- Stage 1 is currently emitting `identifiers` as freeform tokens — already enough for BM25 to match exact dates verbatim. That's a much cheaper first attempt at the same problem; it just won't handle range queries.
- Premature: we haven't yet measured whether range queries ("between X and Y", "last month", "first half of 2022") are common in real use.

**When to revisit:** when retrieval eval starts including range / categorical queries (e.g. "all receipts from Breadfast in 2022", "anything I spent over EGP 500 last summer") and verbatim BM25 matching fails on them. First implement extraction + filter for one field (probably `transaction_date`); measure; expand to merchant / total / currency only if needed.

---

## 8. Smarter T0 / large-CSV retrieval (the ripgrep-at-answer-time approach is leaving signal on the floor)

**Tags:** retrieval · csv

**What:** Today T0 files (huge CSVs, logs, multi-MB JSON, big textbooks) embed only a 2 KB preview, and the answer step bridges the gap with `ripgrep_file(path, question_tokens)` (see `src/ingest/ripgrep.py` + `src/answer.py`). The approach works for the easy cases — exact dates, exact merchant names, exact dollar amounts — but it has several known weak points worth thinking about together:

1. **Naive token extraction.** `_tokens_for_pattern` uses `re.findall(r"[\w$/.-]+", question)` minus a narrow stopword list. "How much did I spend at Walmart" yields `["much", "spend", "Walmart"]` — two of those are noise content words that aren't in the stopword set. Ripgrep wastes effort and noise dilutes signal.
2. **Purely lexical — no synonym handling.** "Coffee purchases" never matches "Starbucks." "Rent" never matches "landlord deposit." The semantic gap is exactly why we use dense embeddings everywhere else; ripgrep doesn't have that.
3. **No date / number format normalization.** Question says "May 2022", CSV row says `05/14/22`. No match. Same for currency formats, abbreviations, etc.
4. **No relevance ranking of hits.** `rg --max-count=30` returns the *first 30* matches in file order. If the answer line is row 50,000 of an 80,000-row CSV and the question's tokens collide with row 1-30 noise, the answer line is never returned.
5. **The retrieval step might never surface the file at all.** T0's 2 KB preview is the only thing in Qdrant. If the question is about content deep in the file, the file isn't retrieved → ripgrep never gets a chance.
6. **Per-file latency stacks.** Top-5 retrieval with all T0 hits = 5 sequential ripgreps (15s timeout each). User waits.
7. **Date / range queries are filter-shaped, not lexical-shaped.** "Anything from May" works for one verbatim string but breaks across formats.

**Why we might want to revisit:**
- The current approach optimizes for "find a needle in the file the user already named" — anything where the question contains a literal token that appears in the matching row.
- Real-world question/file mismatches (synonyms, intent paraphrase, range constraints) silently return empty hits, and the LLM gets a degenerate prompt ("file not embedded, no matches"), so it correctly says "I don't see this in your files" — even though the file does contain the answer.
- Stage 4 has no way to know the difference between "we genuinely searched and the answer isn't there" and "we used the wrong tokens."

**Approaches to consider (probably not all of them — these are options, not a roadmap):**

a. **LLM-rewritten ripgrep patterns.** Cheapest improvement. Hand the question to a small LLM with a system prompt: "produce a ripgrep regex that would find lines answering this question over a CSV with these column headers." The LLM can synthesize date-format alternations (`(May|/05/|2022-05)`), pick the discriminating tokens (`Walmart` not `much`), and emit a sane pattern. ~1 LLM call per T0 file at answer time, ~$0.0001 each.

b. **Local relevance-ranking of ripgrep hits.** Pull `--max-count=200` instead of 30, then BM25-rank the matching lines locally against the question, send top-30 to the LLM. Catches cases where the answer is row 5,000 but matches the same token as row 5.

c. **Hybrid CSV indexing — header + first N rows as per-row points, ripgrep for the tail.** For CSVs in the 1k-100k row range, embed the first 1,000 rows as proper Qdrant points (so semantic retrieval works), and treat rows 1,001+ as ripgrep-only. Argument: the first rows are usually representative; if the file is structured (catalog, products, courses), those rows give Qdrant enough vocabulary to retrieve the file confidently. Tail rows still need ripgrep but the file is now findable for semantic queries.

d. **Two-step: classify the CSV at ingest, then route by class** (the user's earlier suggestion, written up in the corresponding ponder note). Catalogs → per-row T1 indexing regardless of size. Datasets/logs → T0 + ripgrep. This kills the worst case of "we treated a 5k-row catalog as a dataset because it happened to be over 1k rows." Cheap heuristics first (avg chars/cell, column-name patterns, row uniqueness signature); LLM classification only as tiebreaker.

e. **Date / number range filters as Qdrant payload** (overlaps with item #7 above). Extract a normalized `transaction_date` per row at index time, support `>=` / `<=` filters at query time. Ripgrep doesn't disappear — it complements filter-narrowed candidate sets.

f. **Page-anchored slicing for huge text-native files.** For 500-page textbooks (which currently route to T0), use the bookmark TOC + per-chapter chunking. Retrieval returns "chapter 7 of textbook X"; answer step reads only chapter 7. Backlog item B5 (hierarchical chunking) covers part of this.

**Why we did NOT do it now:**
- The current ripgrep path covers the *common* case for huge CSVs/logs cheaply. We haven't yet measured how often it silently returns no relevant hits on a real corpus — without that number, it's hard to know which of the above options buys the most.
- The CSV classification problem (item d) is upstream of all of this — fixing the routing first is probably cheaper than fixing the ripgrep behavior. A 5k-row course catalog routed correctly to per-row T1 doesn't need ripgrep at all.
- Most of these (a, b, e) add per-query latency or LLM cost at exactly the moment the user is waiting for an answer.

**When to revisit:**
- After a real-data corpus is in use long enough to log: how many queries hit T0 files? How many of those returned 0 ripgrep hits? Of the 0-hit cases, were the questions answerable from the file in principle?
- Specifically: build a small "T0 questions" eval set (ground-truth question + huge CSV/log + expected row) and run the current pipeline against it. The recall@5 number on that set is the trigger.
- Cheapest first move when triggered: option (a) — LLM-rewritten patterns. Smallest blast radius, biggest plausible lift on the synonym/format-mismatch failure modes. If that doesn't move the number, escalate to (b) and (c).

---

## 9. Liquid AI LFM2 Model Family Evaluation

**Tags:** models · retrieval

**Context:** Magpie's pipeline currently calls cloud LLMs for two tasks: query rewriting (pydantic-ai `SearchQuery` generation) and cited answer synthesis. Stage 1 vision summaries are exploring Gemma 3n E4B via mlx-vlm on Apple Silicon. With Liquid AI's LFM2 family (late 2025) and Google's Gemma 4 family (April 2026) both now available, there are stronger local candidates worth benchmarking against our actual corpora (ReceiptQA, 1,724-course catalog, 236-club directory). All LFM2 models ship with day-one MLX support and an Apache 2.0-derivative license (free commercial use under $10M ARR).

**Binding hardware constraint:** ColQwen2.5 in `fast_tier` consumes ~6 GB VRAM, leaving ~2 GB headroom on 8 GB Apple Silicon. This — not benchmark scores — is the primary filter.

### LFM2.5-1.2B-Instruct — query rewriter (highest priority)

**Why test:** The query rewriter is a pydantic-ai call producing a structured `SearchQuery` — almost certainly a cloud roundtrip today. LFM2 was post-trained specifically on RAG and function-calling. At 4-bit MLX it's ~600–800 MB resident, runs in tens of milliseconds, and pydantic-ai works against any OpenAI-compatible endpoint (mlx-lm serves one natively). Killing the network roundtrip on every keypress is the most direct UX improvement possible. IFEval 74.89% suggests solid schema adherence.

**Where it may fail:** Sub-2B models can produce schema-valid but semantically wrong `SearchQuery` objects — worse than an obvious failure. Multilingual queries outside its 8 trained languages (EN, AR, ZH, JA, KO, ES, FR, DE) may degrade. No thinking mode, so complex multi-clause queries may decompose poorly compared to a cloud model.

**Test plan:** Replay 100 representative queries (synthesize if no logs exist) through cloud and LFM2.5-1.2B; manually grade intent fidelity, schema correctness, and decomposition quality. Measure end-to-end latency. **Lowest-risk swap — implement first.**

### LFM2.5-VL-1.6B — Stage 1 vision summaries

**Why test:** Direct A/B candidate against Gemma 3n E4B (and Gemma 4 E4B) for structured per-file summary generation. Same mlx-vlm tooling. At 8-bit it's ~1.6–1.8 GB resident vs. ~3.5–4 GB for Gemma 3n E4B at 4-bit — better fit alongside ColQwen2.5. Tunable image token budget (96 tokens at 256×384 up to ~1,020 at 1000×3000) lets us trade accuracy/latency per file type. Liquid explicitly markets LFM2 for "data extraction" tasks, which matches our structured summary schema (title / description / entities / identifiers).

**Where it may fail:** 1.6B is small; likely weaker than Gemma 4 E4B on dense visual reasoning (MMMU-Pro 52.6% is a high bar). May struggle with multi-page club directory entries. Native 512×512 patch tiling could lose detail on dense receipts with small fonts. No thinking mode.

**Test plan:** A/B against Gemma 3n E4B and Gemma 4 E4B on ReceiptQA + 50 sampled course entries + 50 sampled club entries. Measure: schema adherence rate, entity extraction F1, peak memory during indexing, time per file.

### LFM2-2.6B / LFM2-8B-A1B — cited answer synthesis (test, do not commit)

**Why test:** The final pipeline stage is the only remaining cloud dependency. Eliminating it completes the "no cloud, filesystem as source of truth" story. LFM2-2.6B at ~2 GB (4-bit) fits alongside the retriever on 8 GB hardware. Strong instruction-following (IFEval 79.56%) matters for citation format adherence. LFM2-8B-A1B (8.3B total / 1.5B active MoE) is worth trying if it fits at ~4–5 GB — it gains +11 MMLU-Pro points over the 2.6B.

**Where it may fail (significant concerns):** Liquid AI explicitly advises against LFM2 for knowledge-intensive tasks. Cited multi-document synthesis is exactly that. MMLU-Pro ~26% for the 2.6B is 30–40 points behind Gemma 4 E4B (69.4%). Expected failure modes: (a) correct format, wrong substance; (b) citation hallucination — claiming a chunk supports a claim it doesn't; (c) failure to reconcile contradictions across 3+ sources.

**Test plan:** Build a held-out eval set of ~30 queries with ground-truth cited answers from the cloud baseline. Score on: citation faithfulness, answer completeness, hallucination rate. **Hard cutoff: if citation faithfulness falls below 90% of cloud baseline, do not ship.** Keep cloud for synthesis and accept the hybrid architecture.

### Suggested order of evaluation

1. LFM2.5-1.2B-Instruct as query rewriter — half a day, immediate latency win, near-zero output risk.
2. LFM2.5-VL-1.6B vs. Gemma 3n E4B vs. Gemma 4 E4B for Stage 1 — let our corpora decide, not public benchmarks.
3. LFM2-2.6B / LFM2-8B-A1B for synthesis — only commit if quality holds within tolerance; otherwise keep hybrid (local rewriter, cloud synthesizer).

### Out of scope

LFM2-ColBERT-350M is text-only late-interaction and cannot replace ColQwen2.5 (visual late-interaction over page patches). Retrieval architecture is unchanged. No `fast_tier` or `summaries` collection changes are part of this evaluation.

---

## 10. Self-contained Packaging (Bundled Python & Sidecar)

**Tags:** packaging

**What:** Package the application so that the `.app` and `.dmg` bundles are entirely self-contained, including the Python interpreter and all necessary dependencies. This likely involves using `PyInstaller`, `Nuitka`, or Tauri's built-in sidecar support with a pre-bundled Python environment (like a `conda` or `uv` export).

**Why:**
- **Zero-dependency install.** Currently, the app expects `uv` and `python3` to be in the user's `$PATH` and the source code to be present in a specific location. A real desktop app should work with a simple "drag to Applications" flow on any Mac, regardless of the user's developer tools.
- **Sidecar reliability.** By bundling the Python sidecar as a compiled binary (or a private internal environment), we eliminate "it works on my machine" issues caused by version mismatches in Python libraries or missing system dependencies.
- **Security & Sandboxing.** A self-contained bundle is a prerequisite for proper macOS code signing and notarization, which removes the "damaged / unidentified developer" warnings that currently plague non-developer users.

**When to revisit:** As soon as we want to share the app with non-technical users or move beyond a "developer-preview" state.

## Addendum to Plan #10 (Self-contained packaging) — `magpie_defaults.json`

The 2026-05 ingestion-rules refactor introduced [src/config/magpie_defaults.json](../src/config/magpie_defaults.json). Today it lives in the source tree; `load_magpie_defaults()` resolves it via `Path(__file__).parent`. That works in dev mode and inside an editable install, but breaks for a packaged binary (PyInstaller / Nuitka / Tauri-bundled-Python) where the file may live alongside the executable in a different layout per OS.

When implementing Plan #10, also handle:
- Bundle `magpie_defaults.json` as a Python package resource (ship via `[tool.uv.sources]` or `package_data` so `importlib.resources` can find it).
- OR pass an env var (`MAGPIE_DEFAULTS_PATH`) from the Tauri Rust shell when spawning the sidecar, pointing at the bundled resource location.
- OR accept the dev-mode `Path(__file__).parent` fallback as the "if everything else fails" path.

The fallback in `load_magpie_defaults()` already prints a warning and runs with empty defaults rather than crashing — so if packaging gets this wrong, users see "running with no built-in exclusion patterns" in stderr rather than a hard failure. That's intentional. Don't relax this safety net during the packaging migration.

---

## 11. Unify orphan-cleanup pattern across `summaries` and `fast_tier`

**Tags:** indexing · qdrant

**What:** The codebase currently has two different orphan-cleanup styles in two collections, and a fix-time decision was made to add a third (count-based for CSV/PDF chunks). Pick one canonical approach and migrate the other.

| Collection | Style today | How it works |
|---|---|---|
| `summaries` | **count-based** (after the 2026-05-03 fix in [src/stage2/__main__.py](../src/stage2/__main__.py)) | Manifest stores `entry.row_count` (and future `entry.chunk_count`). Orphan cleanup generates expected point IDs from those counts and deletes anything in Qdrant not in the expected set. |
| `fast_tier` | **path-based** ([src/ingest/walker.py:776](../src/ingest/walker.py#L776), [src/stage2/fast_db.py:201,224](../src/stage2/fast_db.py#L201)) | Asks Qdrant "what source paths are indexed?" via payload scroll. Diff against `manifest.paths()`. For each orphan path, call `delete_path(path)` which removes ALL pages of that file in one filter-based delete. |

**Why we might want this:**
- **Latent in-file-shrinkage bug in fast_tier.** If a PDF is re-rendered with fewer pages (compression change, edited PDF, renderer behavior change), pages `N..oldN-1` stay in Qdrant forever — search returns them, click jumps to "page doesn't exist." Path-based cleanup looks at the *path* (still in manifest) and skips it, never touching the stale pages. Count-based would catch it.
- **Future-proofing chunked formats.** When PDF semantic chunking lands (Plan #?), audio segment indexing lands, video frame indexing lands, etc. — a new engineer copies one of the two patterns. If they pick path-based ("simpler, mirror fast_tier"), they inherit the same in-file-shrinkage blind spot. One canonical pattern removes that fork in the road.
- **Schema clarity.** `fast_tier` already has `entry.fast_pages` populated — the count is *already there*, it's just not used by the cleanup. The migration is genuinely small.
- **Consider an even cleaner alternative.** Instead of per-tier count fields (`row_count`, `chunk_count`, `fast_pages`, ...), store the actual point IDs in the manifest entry: `point_ids: list[str]`. Orphan cleanup becomes pure set subtraction with no per-tier dispatch. Cost: ~125 KB of extra manifest weight per 1700-file corpus (negligible). Benefit: zero new schema fields per new tier. Worth evaluating during this work.

**Why we did NOT do it now:**
- Both styles work for their current callers. The fast_tier bug is *latent* — users who don't shrink their PDFs never hit it. Migrating proactively risks introducing regressions in the working path-based code.
- ~15 lines of code for the migration, but needs careful testing on a real fast_tier corpus to confirm the point-ID derivation matches what `_page_point_id()` writes (it should — both use MD5 of `f"{source_path}::page:{page_num}"` — but worth verifying with a scroll diff before flipping).
- No user-facing symptom right now; not worth pre-empting Mridul's CSV unblock.

**When to revisit:** Before adding any third tier that produces multi-point-per-file output (PDF chunking, audio segments, video frames). At that point a) we'll have a third writer and choosing must be deliberate, b) the migration test infrastructure is freshest, c) we'll want every cleanup style aligned for the future engineer.

**Risk if deferred indefinitely:** Each new tier doubles the cognitive surface. By tier 4 (audio/video/pdf-chunks/whatever) the codebase will have grown three semi-orphaned conventions and a new contributor will spend a day reverse-engineering which to use.

---

## 12. Routing data files (CSV / JSON / XML / Parquet) properly through tiers

**Tags:** indexing · csv

**What:** Today data files are processed by either (a) the row-level CSV ingester (one Qdrant point per row, no LLM summary) or (b) the standard text summarizer (one summary per file). The router decides via extension + size, but the decision logic is shallow — large CSVs go to row-mode, small JSONs go to summary-mode, and there's no real "what's IN this file" awareness. The `data` category in `categories_enabled` lumps them all together and defaults ON purely to keep Mridul's just-fixed CSV ingestion working.

**Why we might want this:**
- **Different data shapes need different handling.** A 50-row contacts CSV is a useful row-level index ("find Sarah's email"). A 5000-row sales-by-day CSV is better summarized as "daily sales 2024-01 to 2024-12, columns: date, sku, units, revenue" with sparse rows for outliers. A `package.json` doesn't want either — it wants metadata extraction. Today, all three go through the same paths.
- **Sensitivity & dedup.** Bank statement CSVs and project config JSONs need different sensitivity scoring. Today both get the same router treatment.
- **The `data: true` default is currently a hack.** It's TRUE only because `data: false` would silently break Mridul's CSV indexing — not because indexing every JSON file in the world is good.

**Why we did NOT do it now:**
- Mridul's CSV path works as of the 2026-05 fix (`Plans/Ingestion Rules/Implementation Plan.md` cross-ref). Users searching course CSVs get correct results.
- Real product evidence needed: what kinds of data files do users actually have? Without that, any tier scheme we design is speculation.

**When to revisit:** Once users complain about results from data files (either too many irrelevant hits from JSON dumps, OR missed hits because a CSV got summarized at file-level when row-level would've helped). At that point we can build a `data_shape_classifier()` that distinguishes "tabular row index", "key-value extract", "blob to summarize", "stream to skip". 1–2 weeks of work; expensive to do prematurely.

---

## 13. Daemon as a true OS service (launchctl / systemd)

**Tags:** packaging · daemon

**What:** Run the indexing daemon as a real OS-managed service. macOS: a `launchctl` agent under `~/Library/LaunchAgents/`. Linux: a `systemd --user` unit. Windows: a Task Scheduler entry or a real Windows service. The user installs Magpie, the OS handles starting/stopping/respawning the daemon, and Magpie keeps indexing in the background whether or not Tauri is open.

**Why we might want this:**
- **Spotlight-parity.** Spotlight indexes whether you're using it or not. Real users expect "I added a folder to Magpie, new files in it get indexed within minutes" — not "I have to open the GUI for indexing to happen."
- **Decouples indexing lifecycle from GUI lifecycle.** Today's MVP plan (PR2 of `Plans/Ingestion Rules/Implementation Plan.md`) merges the daemon into the Tauri sidecar — file watching dies when the user closes the app. That's a known trade-off for MVP simplicity, but it's not the right end state.
- **Sidecar can stay lean.** Sidecar handles GUI requests; daemon handles background indexing. Different processes, different concerns, easier to reason about each.

**Why we did NOT do it now:**
- Three OS-specific implementations (launchctl + systemd + Task Scheduler) is a meaningful chunk of work — each needs install/uninstall/upgrade scripts and signed plist/unit files for permissions to work cleanly.
- macOS `launchctl` requires entitlements / notarization for full background privilege; ties into Plan #10 (self-contained packaging). Doesn't make sense to do separately.
- Until users actually complain about "I closed Magpie and now indexing doesn't happen," the sidecar-absorbs-daemon path covers the 90% case.

**When to revisit:** After (a) the app ships to non-developers and we get real feedback about background indexing, OR (b) we're already implementing Plan #10 (self-contained packaging) — at that point we have the signing/notarization infrastructure required to register a launchctl agent without permission popups.

---

## 14. Promote `MAGPIE_DEV_USE_MTIME` to a user-facing setting

**Tags:** indexing · ui · config

**What:** Today, the manifest's `needs_summarization()` check uses size-only. A `MAGPIE_DEV_USE_MTIME=1` env var enables a size-AND-mtime check (re-summarize if the file was touched, even if bytes are identical). It exists for dev workflows where you want to force re-ingest by `touch`-ing a file. Promote it to a real user-facing setting in `indexing_rules.json` (`reindex_on_mtime_change: bool`).

**Why we might want this:**
- **Some users want strict re-index on any modification.** Power users editing files in-place (think notes, journals, ongoing project docs) want to be sure search reflects the latest content even if size happens to match.
- **Some users want loose re-index for performance.** Read-heavy corpora (downloaded papers, archived statements) shouldn't get re-summarized every time the OS touches them for backup or sync purposes.
- **Today's env-var approach is dev-only.** Production users have no way to tune this without editing source code.

**Why we did NOT do it now:**
- We don't yet know which users want which behavior. Shipping a setting without real demand creates a "what does this do?" question in the GUI that adds complexity for negligible benefit.
- The dev toggle covers the immediate need (Astavak's debugging workflow). Adding a JSON flag later is a 10-line change once we know the right default.

**When to revisit:** Once a user files a "Magpie didn't pick up my edit" issue, OR once we have telemetry showing how often files change in real-world corpora. Default proposal at that time: `reindex_on_mtime_change: false` (keep current performance behavior), but allow users to flip it ON via the Advanced settings panel.

---

## 15. Auto-promotion of nested exclude paths into sub-roots

**Tags:** ui · config

**What:** Today (per `Plans/Ingestion Rules/Implementation Plan.md`), if a user's per-root rules include nested paths like `exclude_globs: ["src/secrets/*"]`, those rules stay attached to the parent root. An alternative design ("rule normalization") would auto-create a sub-root for each nested path on save: the parent's rule moves into a new `magpie/src/secrets` sub-root with `exclude_globs: ["*"]`. The JSON ends up "denormalized" — every rule is scoped to the immediate directory it lives in.

**Why we might want this:**
- **Cleaner mental model:** every config scope = one directory.
- **Better GUI rendering:** each root becomes a tree node with its own rule panel; nested rules don't sprawl into long path strings.
- **Forces a normalized data model** that's easier to index, search, and validate.
- **The future "Include/Exclude inside folder" UI buttons** (per the locked design) write to per-folder `.magpieinclude` / `.magpieexclude` files — that already produces a quasi-normalized state. Auto-promotion would be the JSON-side equivalent.

**Why we did NOT do it now:**
- **Round-trip surprise risk:** users who edit the JSON by hand see their rules rewritten on save. Loses trust unless the UI explains what's happening.
- **Bidirectional consistency complexity:** if user later removes the auto-generated sub-root, what happens to the original parent rule? Re-promote? Orphan?
- **No GUI yet to render the promoted shape.** Building auto-promotion before the GUI exists means designing for an interface we can't yet test.
- **The current pass-through design works** — `pathspec.PathSpec` handles nested patterns natively. No matching capability is lost.

**When to revisit:** When the Tauri GUI ships (PR3 + GUI work) and we know exactly what shape the rule editor needs. At that point auto-promotion is either an obvious next step (because the GUI demands it) or genuinely unneeded (because the GUI renders parent-relative paths just fine).

---

## 16. LLM / inference settings UI + cross-provider thinking-mode unification

**Tags:** ui · models · config

**What:** Two related pieces of work that both belong upstream of the local-LLM migration shipped in `Plans/Local LLM Plan.md`:

(a) **Settings UI for inference config.** Today the local-backend knobs (`LLM_PROVIDER`, `LOCAL_MODEL`, `LOCAL_QUANT`, `LOCAL_N_CTX`, `LOCAL_N_GPU_LAYERS`, `LOCAL_TEMPERATURE`) live in `.env`. That works for developers but isn't survivable for end-users who can't be asked to edit dotenv files. Promote these to a structured `<APP_DATA_DIR>/llm_config.json` (Pydantic-modeled like `indexing_rules.json`), surface them in the future Tauri settings panel, and let the daemon hot-reload on file change the same way `IndexingRules.maybe_reload` does.

(b) **Unify `thinking` across providers.** The `LocalAgent` honors `thinking=True` (Gemma 4 `<|think|>` token). The cloud agents (`_CloudAgent`, `MagpieCloudAgent`) accept the kwarg for protocol compatibility but currently no-op with a one-time warning. Each cloud provider has its own reasoning surface — OpenAI's `reasoning_effort`, Anthropic's `extra_body.thinking`, Google's `thinking_config`, OpenRouter's pass-through varies by model — and PydanticAI doesn't unify them. Wiring a real implementation means per-provider routing inside `_CloudAgent.run()` and `magpie-cloud`'s `/llm/*` endpoints accepting and forwarding a `thinking` field.

**Why we want both:**

- **Settings UI:** Closes the dotenv-vs-GUI gap that the indexing-rules PR already opened (Plan #10's Addendum lists the `magpie_defaults.json` packaging concern in the same spirit). Once Magpie ships to non-developers, "switch to a smaller quant because my Mac is out of RAM" must be a button, not an editor session.

- **Unified thinking:** A `thinking=True` checkbox in the GUI should produce the same behavioral change regardless of which backend is selected, otherwise users either get a silent no-op (today's cloud behavior) or get confused by toggle-with-no-effect. The right time to design that surface is alongside the settings UI.

**Why we did NOT do it now:**

- The local-LLM PR's primary goal was cross-platform local inference. Settings UI is a separable, larger piece that needs the Tauri settings panel work first (Plans #14 / #15 also block on it).
- Each cloud provider's reasoning API is a research-and-test exercise — model identifiers + parameter shapes vary, and the "what does each one *actually do* with this flag" answer varies more. Doing it half-correctly is worse than the current explicit no-op + warning.
- No user has yet asked for cloud thinking-mode. The local Gemma 4 path is the immediate use case.

**When to revisit:**

- Settings UI: as part of the Tauri settings-panel work that also picks up `indexing_rules.json` (per Plan #14 / #15). That's the next major UI milestone after the indexing-rules MVP.
- Cross-provider thinking: when the GUI exposes the toggle, OR when the answer step shows a meaningful accuracy lift from local thinking-mode and we want the same lift on cloud paths to keep parity. Whichever comes first.

**Notes for the future implementer:**

- `src.llm._warn_cloud_thinking_unsupported` is the single throttle — replace its body when wiring real reasoning support, no need to hunt for callers.
- The `thinking` kwarg is already plumbed through `ChatAgent`, `_CloudAgent`, `_CloudAgentBase`, `LocalAgent`, and the `/generate` endpoint. The data path exists; only the per-provider terminal logic is missing.
- For provider-specific implementations: OpenRouter's structured output API supports a `reasoning` field on supported models (currently a small set). Anthropic's `extra_body={"thinking": {"type": "enabled", "budget_tokens": 1024}}` is the cleanest. OpenAI's `reasoning_effort` is on `o1`/`o3`/`gpt-5` only. Each one needs a model-id allowlist.

---

## 17. CSV redesign — proper summaries (Part A) + row-window retrieval (Part B) — IMPLEMENTED 2026-05-06

**Tags:** indexing · retrieval · csv · ✅ implemented

> **Promoted from Future Plans to shipped.** Both halves landed together,
> as the design required. See `src/ingest/tier1.py:run_csv_async`,
> `src/stage2/search.py:build_csv_row_window_block`, and the new
> `csv_row_hits` plumbing through `src/pipeline.py:ask` and
> `src/answer.py:answer_question`. Tests under
> `tests/ingest/test_tier1_csv.py` and
> `tests/stage2/test_csv_row_windows.py`. The `LOCAL_ANSWER_MAX_CHARS`
> band-aid was removed; `ANSWER_SUPPLEMENT_MAX_CHARS` was relaxed from
> 4 KB to 10 KB. To pick up the new behavior on existing CSVs, run
> `just walk --force <root>` once — that re-summarizes the CSVs through
> the LLM path; PDFs / DOCX get re-summarized too but that's incidental.
>
> Original plan kept below for context.

This is one feature with **two coupled halves**. Either half alone leaves the
system in an awkward intermediate state. Implement them together; do not ship
Part B without Part A landing in the same release.

**The problem today:**

The T1 CSV path conflates "summary" with "embed body." [src/ingest/tier1.py:40](../src/ingest/tier1.py#L40)
writes the entire CSV — capped at 20 MB — into the summary markdown. At
retrieval time, `_summary_supplement` then prepends that whole-file dump to
every answer prompt; `build_content_blocks` separately reads `text[:max_chars]`
of the same file. So the LLM sees the **start** of the CSV (twice, in two
framings) regardless of which row was retrieved. Bad in two directions:
the summary isn't a real summary, and the prompt content has nothing to do
with the matched row.

### Part A — Indexing side: one real summary per CSV

At ingest, replace the "stuff the whole CSV into a markdown" path with:

1. **Sample the CSV.** Header row + first ~20 rows / first ~1000 chars. For
   non-uniform CSVs (sales logs, telemetry dumps where the head can be
   metadata), a future enhancement might add lightweight column-stats
   sampling before the LLM call — but uniform-rows-from-the-top is the
   robust default for the catalog/directory shape Magpie currently sees.
2. **LLM call** producing a `FileSummary(title, summary, keywords,
   key_entities, identifiers)` — same Pydantic shape T3 produces for
   PDFs / DOCX. Write it as the summary markdown alongside other tiers'
   outputs.
3. **Row-level Qdrant points unchanged.** `csv_ingest.py` continues to
   embed every row as a separate point. The summary is a *separate
   artifact*, not the embed source for row points. Stays embedded in the
   `summaries` collection like any other file-level summary, with a payload
   field marking it as the CSV's parent summary.

### Part B — Retrieval side: row windows + the summary, nothing else

At answer time, when any row of a CSV is in the top-k:

1. **Build a row-window block** for each hit: matched row + ±2 neighbors
   (CSV_NEIGHBOR_WINDOW from `src/stage2/search.py`). For multiple hits in
   the same CSV, merge overlapping or adjacent windows into one block
   instead of duplicating rows. Result is ~5-15 rows per CSV, ~1-3 KB of
   text — focused on what the user actually asked about.
2. **Attach the file's summary** (the new Part-A summary) once per CSV.
   Gives the model semantic context: "this row is from a 1,724-row Furman
   course catalog covering N departments and M GERs."
3. **Skip `build_content_blocks` and `_summary_supplement` for CSV row
   hits.** They're the wrong primitives — they read the file's
   beginning, not the matched rows. The row-window block + summary
   replace both. PDFs / DOCX / etc. continue using the existing path
   unchanged.

This means the LLM prompt for a CSV-heavy query goes from ~14 KB/file
(raw prefix dumped twice) to ~3 KB/file (the actual matched rows + a
real summary). At top_k=8 that's ~24 KB total instead of ~112 KB —
~5× faster prompt eval on the local backend, sharper answers across
all backends.

### Why both halves must ship together

- **Part A without Part B:** the retrieval prompt still reads the file's
  beginning. The new summary lands in `_summary_supplement` (where it now
  fits in the 4 KB cap) but the per-file content is still wrong-row
  prefix. Improvement is small.
- **Part B without Part A:** the row windows are good but the
  "summary" attached to each is still the raw-content dump that caused
  the May 2026 token blowup. We'd just be reusing the broken summary in
  a different framing.
- **Both together:** consistent semantics across the pipeline — row-level
  search hits, row-window content, real semantic summary.

**Why we did NOT do it now:**

- The supplement cap and the local per-file cap unblock today's queries.
  No user-visible regression as of 2026-05-06.
- Sampling-strategy design needs evidence: 20 rows is fine for catalog
  CSVs but unclear for sales / log shapes. Worth running a small eval
  before locking the default in.
- Need product evidence that the LLM-call-per-CSV cost at ingest is
  worth the quality lift. ReceiptQA / Furman corpora are the natural
  eval targets.

**When to revisit:**

- Once we have a real-data corpus running through Magpie long enough to
  log: how often do queries hit a CSV row? How often does the answer
  model fail because it sees the wrong rows (or no useful summary)? An
  eval set targeting catalog/directory questions (Furman directory +
  course CSVs) would surface the gap concretely.
- Failure modes today that this fixes: (a) "find me a CSV about X"
  misses because no row contains X verbatim; (b) "what are the *other*
  courses by this instructor" — retrieval returns one row; the answer
  model has no view onto the other rows in the same file; (c) the
  current band-aid `LOCAL_ANSWER_MAX_CHARS = 10_000` truncates real
  PDF / DOCX content unnecessarily because it has to be tight enough
  for the worst-case CSV blowup.

**Implementation sketch (for the future implementer):**

**Part A:**
- New helper `src/ingest/tier_csv_summary.py` (or a new path inside
  `tier1.py`'s CSV branch). Reads header + N sample rows, builds a
  `FileSummary`-shaped LLM prompt via `src.llm.build_agent`, writes a
  normal T3-style summary markdown.
- The summary point lands in the `summaries` Qdrant collection with a
  payload flag like `payload.kind = "csv_parent_summary"` so retrieval
  can find it without scrolling the manifest.
- Row points keep their existing `payload.row_index` and `payload.source_path`.

**Part B:**
- Plumb `SearchResult.row_index` (already populated) into
  `src.pipeline.ask`'s call to `answer_question`.
- In `src/answer.py`, add a CSV-row-hit branch: when a path has any
  retrieved hits with `row_index` set, skip `_summary_supplement` and
  `build_content_blocks` for that path. Substitute (a) merged row-window
  block(s) for that CSV's hits and (b) the parent summary fetched via
  Qdrant payload lookup.
- Multiple hits in the same CSV: merge overlapping windows by sorting
  row_indexes and joining when `next_start <= prev_end + 1`.
- The cap on `ANSWER_SUPPLEMENT_MAX_CHARS = 4_000` in
  [src/answer.py](../src/answer.py) can be removed (or relaxed back to
  ~10 KB) once T1 CSV no longer emits raw-content "summaries."
- The local-only `LOCAL_ANSWER_MAX_CHARS = 10_000` cap can be removed
  once Part B kicks in for CSV hits — the prompt will be small by
  construction. Non-CSV files keep the existing `ANSWER_MAX_CHARS_PER_FILE`.

**Tests:**
- A new fixture under `tests/ingest/` that walks a tiny CSV, asserts
  the produced summary is a valid `FileSummary` (not raw bytes), and
  asserts the row-level Qdrant points still appear.
- An answer-step test: feed a synthetic 100-row CSV with 3 row hits
  at indexes 5, 6, 47. Assert the prompt contains exactly the merged
  windows (rows 3-8 and 45-49) plus the file summary, NOT the file's
  beginning, NOT `text[:max_chars]`.

---

## 18. Lock down Magpie's Qdrant — auth + bind hardening (Layer 2 of the OpenWhispr-collision fix)

**Tags:** security · qdrant

**Context:** The 2026-05-06 audit caught a silent disaster: Magpie's `.env` pointed at `http://localhost:6333`, the Qdrant default, and so did OpenWhispr's bundled Qdrant binary. OpenWhispr was running and Magpie's `just qdrant-up` was not — so every Magpie ingest call landed in OpenWhispr's storage at `~/.cache/openwhispr/qdrant-data/`. Twenty `summaries` points and an empty `fast_tier` collection were created against the wrong instance. The fix shipped (Layer 1): Magpie's standalone Qdrant now runs on **6433/6434** instead of 6333/6334, with `QDRANT__SERVICE__HOST="127.0.0.1"` pinned in `just qdrant-up`. See `justfile` `QDRANT_PORT` / `QDRANT_GRPC_PORT` and the `.env` comment.

That's a port move. It is **not** an isolation guarantee. Anything else on the machine — another app, a stray script, a misconfigured client, a future OpenWhispr update that probes a wider port range — can still talk to `localhost:6433` and read or wipe Magpie's data. The 127.0.0.1 bind keeps the LAN out; it does not keep co-resident apps out.

**What:** Add API-key authentication end-to-end to Magpie's local Qdrant instance, generated per-machine. Two coupled pieces (the 2026-05-07 db.py refactor that dropped both the cloud-cluster and embedded-shim modes also dropped the `api_key=` parameter from the `QdrantClient(...)` constructor — so this plan has to add both ends back, not just enable an existing pathway):

(a) **Generate a per-install secret on first `just qdrant-up`.** If `<APP_DATA_DIR>/qdrant/api_key` doesn't exist, create it with 32 random bytes (`openssl rand -hex 32` or Python `secrets.token_hex(32)`), `chmod 600`. Pass it into the Qdrant binary via `QDRANT__SERVICE__API_KEY="<value>"` alongside the existing `QDRANT__SERVICE__HOST` / `__HTTP_PORT` / `__GRPC_PORT` env block. Magpie's daemon reads the same file at startup.

(b) **Re-add the `api_key=` parameter to `get_qdrant_client()`** ([src/stage2/db.py](../src/stage2/db.py)). Today the constructor call is `QdrantClient(url=url, timeout=timeout_s)` — no auth at all. The plan: read the per-install key file (or the `MAGPIE_QDRANT_API_KEY` env var, dev override) and pass it as `api_key=...`. Hard-error at startup if the key file is missing once the server has been started with a key, rather than silently falling through to anonymous.

**Why we want this:**
- **Stops co-resident apps from accessing Magpie's data.** A different desktop app on the same Mac that probes `localhost:6433` gets `401 Unauthorized` instead of a points dump. Today, only port obscurity keeps anything else out.
- **Stops a future port-collision regression silently.** If something else ever does land on Magpie's port (a user manually starts another Qdrant for testing, a future OpenWhispr update broadens its port scan, etc.), Magpie's client tries to authenticate to it, fails fast, and surfaces the conflict — instead of silently writing into a foreign collection the way the OpenWhispr incident did.
- **Closes the dotfile-readable backdoor.** `chmod 600` on the key file means only the user account that runs Magpie can read it. Other macOS user accounts on the same machine, or an unsandboxed third-party app running as a different user, can't grab it.
- **Adds defense in depth on top of the localhost-only restriction.** db.py already hard-errors when `QDRANT_CLUSTER_ENDPOINT` resolves to a non-loopback host (added 2026-05-07), so off-machine access is already blocked. The API key adds same-machine isolation that the loopback restriction can't provide on its own.

**Why we did NOT do it now:**
- Layer 1 (port move) was the immediate fix — it stops the active misrouting today with a one-line change. Layer 2 needs a key-management story (where the file lives per-OS, what to do when it's deleted/rotated, how the daemon picks up changes), which is more design than the OpenWhispr incident demanded as an emergency response.
- The per-OS key path resolution overlaps with Plan #10 (self-contained packaging) and the `magpie_defaults.json` packaging concern in its addendum — solving both together is cheaper than solving them sequentially.
- No second co-resident app has actually breached Magpie's port-6433 instance yet; the threat model is hypothetical-but-realistic, not actively exploited. Buys time to design the key storage carefully rather than ship a band-aid.

**Implementation sketch (for the future implementer):**

1. **Key file location:** `APP_DATA_DIR / "qdrant" / "api_key"` — same tree as the binary and storage. Mode `0600`. Generated by a new `qdrant-init-key` recipe in `justfile` (or auto-fire from `qdrant-up` on first run if the file's missing). Use `openssl rand -hex 32` or a pure-Python `secrets.token_hex(32)` from a tiny helper script — don't rely on `uuidgen` (only 122 bits of entropy and predictable structure).
2. **Server side:** add `QDRANT__SERVICE__API_KEY="$(cat $KEYFILE)"` to the env block in `qdrant-up` ([justfile:294-297](../justfile#L294-L297)). Optionally also set `QDRANT__SERVICE__READ_ONLY_API_KEY` to a *different* secret if we ever want a read-only client (e.g. a future "spotlight-style" preview UI that should never delete).
3. **Client side:** in `get_qdrant_client()` ([src/stage2/db.py](../src/stage2/db.py)), re-add the `api_key=` parameter to the `QdrantClient(...)` constructor. Resolution order: `MAGPIE_QDRANT_API_KEY` env var (dev override) → per-install key file → fail with a clear message naming the file path. Add a unit test in `tests/stage2/test_qdrant_timeout.py` that asserts `get_qdrant_client()` raises when neither source provides a key *and* the server expects one.
4. **Migration story for existing installs:** the next `qdrant-up` after pulling this change creates the key file, prints the value once with "save this for your other clients (Tauri sidecar, REPL, scripts) — Magpie's daemon reads it from the file automatically." Existing data in `<APP_DATA_DIR>/qdrant/storage/` is preserved; only the running server's auth posture changes.
5. **Tauri / sidecar coupling:** if Plan #10 (self-contained packaging) lands first, the Rust shell that spawns the Python sidecar should pass the key via env (`MAGPIE_QDRANT_API_KEY`) so the sidecar inherits it without re-reading the file. Until then, the Python daemon reads the file directly.
6. **Don't add TLS / client certs.** Out of scope for a single-user local desktop app; the existing 127.0.0.1 bind + the new loopback-only check in `_is_localhost_url` already block off-machine access.
7. **Embedded mode is not an alternative.** It was already removed in the 2026-05-07 refactor — the docstring at [src/stage2/db.py](../src/stage2/db.py) explains why (silent quantization / payload-index gaps that misled at-scale tests). Auth on the standalone server is the only path.

**When to revisit:**
- **Triggering events:** another desktop app on macOS is observed shipping a Qdrant binary (Spotlight-replacement category is small but growing); a user reports unexpected collections appearing in Magpie's instance; or Plan #10 / Plan #13 (self-contained packaging / launchctl daemon) starts and the auth surface is part of the same ship.
- **Background priority:** worth doing within the next two ship cycles regardless. The audit caught the OpenWhispr collision by luck — the next collision may be with an app that *writes* to `summaries` instead of just leaving it alone, and we'd notice only when search results contained someone else's data.

**Risk if deferred indefinitely:** today the port move is the only thing preventing data corruption from co-resident apps. That works as long as port 6433 stays unique to Magpie on every install. The audit pattern (`lsof -i :6433`, `ps -A | grep qdrant`) needs to become a `just qdrant-status` precondition check at minimum — but real isolation requires the key.

---

## 19. Post-packaging configuration story — replace `.env` with structured config + OS-keychain secrets

**Tags:** packaging · config · security

**Context:** Today's runtime configuration lives in `.env` at the repo root and is loaded by `python-dotenv` from inside CLI entrypoints (`src/ingest/walker.main()`, `src/stage2/__main__.main()`, `src/pipeline.main()`, etc.). The justfile now does `set dotenv-load` (added 2026-05-06 after `just reset-index` failed because its `python -c` snippet bypassed every entrypoint that loads dotenv) so every `just` recipe inherits `.env` too. This works for developers running from a checked-out source tree.

It does **not** survive packaging. After Plan #10 ships (PyInstaller / Nuitka / Tauri-bundled-Python), there is no repo root, no `just`, and no convention for "the user's .env" on macOS. Asking a non-developer to edit a dotfile is also a UX non-starter, and stuffing API keys in plaintext at a guessable path next to a `.app` bundle invites trivial theft.

**What:** Split today's `.env` along two axes — *what changes* (config vs. secrets) and *who edits it* (user vs. install-time):

(a) **Non-secret config → JSON.** A new `<APP_DATA_DIR>/config.json`, peer of the existing `indexing_rules.json` and (proposed in Plan #16) `llm_config.json`. Holds: `QDRANT_CLUSTER_ENDPOINT` (the optional port-override; default `http://localhost:6433`), `QDRANT_TIMEOUT_S`, `LLM_PROVIDER`, `LOCAL_MODEL` / `LOCAL_QUANT` / `LOCAL_N_CTX` / `LOCAL_N_GPU_LAYERS` / `LOCAL_TEMPERATURE`, `OPENROUTER_MODEL`, `MOONSHOT_MODEL` / `MOONSHOT_BASE_URL`, `REWRITE`. Pydantic-modeled, schema-validated, hot-reloaded the way `IndexingRules.maybe_reload` does. (`QDRANT_PROVIDER` is gone — there's only one provider now.)

(b) **Secrets → OS keychain.** macOS Keychain via `security` CLI or [`keyring`](https://github.com/jaraco/keyring) Python lib; libsecret on Linux; Credential Manager on Windows. Holds: `MAGPIE_QDRANT_API_KEY` (the per-install local-server key from Plan #18), `OPENROUTER_API_KEY`, `MOONSHOT_API_KEY`, `HF_TOKEN`, `MAGPIE_CLOUD_API_KEY`. Service name `"magpie"`, account name = the env-var name (e.g. `OPENROUTER_API_KEY`). Read at startup; cached in process memory; never written to disk.

(c) **Settings UI surface.** Tauri panel reads/writes `config.json` and the keychain through a single Rust shell command that wraps both. Settings live alongside the indexing-rules editor (per Plans #14 / #15 / #16) so the user has one "Settings" pane covering all knobs, not three.

**Why we want this:**

- **Packaged apps can't reasonably ship `.env`.** A `.app` bundle's bundled-Python sidecar has no `cwd` convention; `.env` files placed by the installer are world-readable by any process running as the same user. The current dev convention doesn't even survive the packaging build.
- **Plaintext API keys at a known path is a theft target.** macOS sandboxes treat Keychain as the canonical secret store; a stolen `.env` sitting in `~/Library/Application Support/Magpie/` is one symlink walk from any app the user grants Files & Folders access to. Keychain entries gate access per-app via signed bundle ID.
- **Per-OS norms.** macOS users expect Keychain prompts; Linux users expect libsecret; Windows users expect Credential Manager. A JSON file matches none of those.
- **Schema validation catches typos.** `.env` errors are silent (a missing variable returns `None` and Magpie either crashes downstream or, worse, falls into a default code path — exactly what bit `just reset-index` and the OpenWhispr port collision). A Pydantic-modeled config file rejects malformed values at startup with a clear message naming the bad field.
- **Runtime hot-reload.** `IndexingRules.maybe_reload` already shows the pattern. Today, changing `LOCAL_TEMPERATURE` in `.env` requires restarting the daemon. With a watched config file it's a save-and-go.
- **Migration is local and one-shot.** The first run of the packaged app reads any `.env` it finds in `~/Library/Application Support/Magpie/` (or the legacy repo root, for upgraders), splits the values into `config.json` + keychain entries, and renames the original `.env.migrated`. Self-cleaning.

**Why we did NOT do it now:**

- `.env` + `set dotenv-load` covers the dev workflow today. No user-visible breakage; the immediate `reset-index` bug is already fixed.
- The keychain-write API differs per OS and per Python wrapper. Doing this without first picking the wrapper (`keyring` is the obvious default but pulls in OS-specific backends conditionally) is premature.
- Without a Tauri settings UI to read/edit the config, swapping the storage format only changes the file the developer hand-edits — net-zero ergonomic improvement until the GUI lands.
- The Plan #10 packaging work has to make a decision about *where* `APP_DATA_DIR` lives in a signed bundle anyway; the config-file location piggybacks on that decision.

**Implementation sketch (for the future implementer):**

1. **`src/config/runtime_config.py`** — Pydantic model covering every variable currently in `.env.example` minus secrets. `load_runtime_config()` returns the validated instance, caches it process-wide, and watches the file for hot-reload using the same `mtime + maybe_reload` pattern as [src/config/__init__.py](../src/config/__init__.py).
2. **`src/config/secrets.py`** — thin wrapper around [`keyring`](https://pypi.org/project/keyring/). `get_secret(name)` returns `os.environ.get(name) or keyring.get_password("magpie", name)` so dev-mode env-var override still works. `set_secret(name, value)` writes to keychain and, on success, `os.environ.pop(name)` (so a subsequent `get_secret` reads the canonical store, not stale env).
3. **`src/stage2/db.py`** — once Plan #18 re-adds the `api_key=` parameter, the resolution order becomes `get_secret("MAGPIE_QDRANT_API_KEY")` → key file fallback → fail. Same `get_secret(...)` shape for [src/llm.py](../src/llm.py)'s provider-key reads.
4. **`scripts/migrate_env_to_config.py`** — one-shot CLI: read `.env` in CWD or `APP_DATA_DIR`, split into `config.json` + keychain writes, rename source to `.env.migrated`. Idempotent (skips already-migrated values). Wired into the packaged installer's first-run hook.
5. **`magpie_defaults.json` packaging concern** (cross-ref Plan #10 addendum) — the new `runtime_config.py` should follow the same load-with-fallback pattern. Bundled defaults via `importlib.resources`; user overrides at `<APP_DATA_DIR>/config.json`; emit a warning (don't crash) when neither resolves.
6. **Justfile cleanup** — once `runtime_config.py` is the source of truth, the `set dotenv-load` line stays as a dev-mode fallback (recipes still want quick env overrides for testing). But the `python -c` snippets get rewritten to read `from src.config.runtime_config import load_runtime_config` first, removing the silent-fallback failure mode.
7. **Don't migrate Magpie-cloud / desktop-app credentials this round.** `MAGPIE_CLOUD_API_KEY` (when it lands) should go directly to keychain — never `.env`. Plan #10 install flow handles the OAuth-style first-launch dance.

**When to revisit:**

- Together with Plan #10 (self-contained packaging) — the same `APP_DATA_DIR` decision drives both.
- Together with Plan #16 (LLM settings UI) — the GUI needs a write API and `runtime_config.py` provides it.
- Together with Plan #18 (Magpie Qdrant API key) — the per-install key is the canonical first secret to flow through this pipeline; doing it as `.env` would be a step backward.

**Risk if deferred:** every new env var added between now and packaging (and there will be more — see Plan #16's local-LLM knobs, Plan #18's Qdrant key, future cloud-provider keys) compounds the migration cost. Doing the migration *after* a half-dozen more `.env` entries land means writing a one-shot importer that has to handle every flavor of dev-mode key Magpie has ever recognized. Today's `.env.example` is short enough that the importer is ~50 lines. By the time Plan #10 is ready it could be 200.

---

## 20. Qdrant process lifecycle — who starts, stops, and health-checks the local server

**Tags:** packaging · qdrant · daemon

**Context:** Today `just qdrant-up` is the only path that launches the binary. Everything else — `reset()`, `ingest_from_manifest()`, every search call — *assumes* Qdrant is already running and surfaces a "Connection refused" error otherwise. That's exactly what bit `just reset-index` on 2026-05-07: the recipe ran fine on the filesystem half but blew up on the Qdrant half because the server had been SIGTERM'd at some earlier point. Patched at the recipe layer (`reset-index: qdrant-up` dependency) but the underlying gap stands: there is no Python-side owner of the Qdrant process. The Tauri Settings page that's about to be built (reset / re-index / "what's indexed?" buttons) cannot rely on the user remembering to run a `just` command before clicking.

**What:** Make the Python sidecar own Qdrant's lifecycle end-to-end. A new `QdrantSupervisor` class wraps the binary as a child process; `src/server.py`'s FastAPI `lifespan` hook calls `start()` on app boot and `stop()` on shutdown. New endpoints (`/reset`, `/reindex`, `/qdrant-status`) expose what the Settings page needs. Leaf functions like `pipeline.reset()` stay process-manager-free.

**Why we want this:**

- **Closes the "did the user remember to `just qdrant-up`?" footgun for good.** Tauri users will never type `just` anything; they click buttons. The supervisor turns "Qdrant might not be running" from a runtime-error case into a startup-handled invariant.
- **Keeps `reset()` and friends pure.** A leaf function that spawns subprocesses is a testing nightmare and races with itself if multiple Magpie windows open. One named place (the supervisor) manages PIDs, SIGTERMs, and double-spawn prevention.
- **Sets the pattern Plan #10 (packaging) and Plan #13 (launchctl daemon) both need.** Packaged `.app` bundles have no shell to run `just qdrant-up`; OS services have no shell session to do it manually. The supervisor pattern survives both transitions; the `just` shim doesn't.
- **Natural home for the Plan #18 API key.** The supervisor is the one place that needs to read the per-install key file AND pass it both to the spawned Qdrant binary (`QDRANT__SERVICE__API_KEY=…`) AND to the in-process `QdrantClient(api_key=…)` constructor. Doing it anywhere else means duplicating the file-read.
- **Surfaces health in the UI.** The Settings page's "Qdrant: running on :6433" pill (or "Qdrant: not running — click to start") prevents the silent partial-completion class of bug the 2026-05-07 reset-index incident exposed.

**Why we did NOT do it now:**

- The Tauri Settings page itself doesn't exist yet. Building lifecycle plumbing for buttons that aren't there is speculative.
- `just qdrant-up` + the new `reset-index: qdrant-up` recipe-prereq covers the developer workflow today. Production users (who don't run `just`) are gated behind Plan #10 (packaging) anyway.
- The supervisor design overlaps with Plan #10 / Plan #13 / Plan #18; doing it once when one of those ships is cheaper than three half-baked iterations.

**Implementation sketch (for the future implementer):**

1. **`src/daemon/qdrant_supervisor.py`** (new) — class with `start()` / `stop()` / `is_healthy()` / `restart()`. Wraps `subprocess.Popen` with the same env block as `just qdrant-up` ([justfile:322-326](../justfile#L322-L326)): `QDRANT__STORAGE__STORAGE_PATH`, `QDRANT__SERVICE__HOST="127.0.0.1"`, `QDRANT__SERVICE__HTTP_PORT`, `QDRANT__SERVICE__GRPC_PORT`. Polls `GET /healthz` until 200 (typically <2s) before returning from `start()`. Tracks whether the supervisor *started* the process or merely *adopted* an already-running one — only sends SIGTERM at shutdown if it owns the spawn.
2. **FastAPI `lifespan` hook in [src/server.py](../src/server.py)** — `async with` context that calls `supervisor.start()` on enter, `supervisor.stop()` on exit. Replaces the implicit "Qdrant must already be running" assumption with an explicit invariant.
3. **New endpoints in [src/server.py](../src/server.py):**
   - `POST /reset` → `from src.pipeline import reset; return reset()`
   - `POST /reindex` → `ingest_from_manifest(force=True)` for "re-push existing summaries to Qdrant," OR a walker spawn for "re-summarize from source files." Decide which the Settings button means before wiring; consider both endpoints if the UI has both buttons.
   - `GET /qdrant-status` → `{running: bool, port: int, version: str, points: {summaries: int, fast_tier: int}, storage_dir: str}` for the Settings UI's health pill and disk-usage row.
4. **Don't auto-start inside leaf functions.** That's the whole point. `pipeline.reset()` stays as it is — assumes Qdrant is up, returns `qdrant_error` in the dict if not. The supervisor is the *one* place that owns lifecycle.
5. **Existing dev workflow stays intact.** `just qdrant-up` keeps working — supervisor's health check sees an already-running server and doesn't double-spawn (mode = "adopt"). `just qdrant-down` continues to work for developers who explicitly want the server off.
6. **Shutdown ordering matters.** When the Tauri app quits, the Rust shell sends SIGTERM to the Python sidecar; the sidecar's `lifespan` exit then calls `supervisor.stop()`. If Qdrant ignores the first SIGTERM (mid-flush), give it a 5-second grace period before SIGKILL — same pattern as `just qdrant-down` ([justfile:343-355](../justfile#L343-L355)).
7. **Don't put the supervisor inside `pipeline.py` or `db.py`.** It's daemon-tier code. `src/daemon/qdrant_supervisor.py` is the right home — sibling to `src/daemon/server.py`.

**When to revisit:**

- **Triggering event:** the Tauri Settings page's first Qdrant-touching button (reset, reindex, or the health pill) is about to be wired. That's the moment lifecycle ownership becomes a hard requirement, not a developer convenience.
- **Together with Plan #10 (packaging)** — the supervisor pattern survives packaging unchanged; the `just qdrant-up` shell shim does not. Both have to ship together to avoid a packaging release where Qdrant simply never starts.
- **Together with Plan #13 (launchctl/systemd daemon)** — the supervisor's parent moves from "FastAPI sidecar" to "OS-managed service," but the inner spawn/SIGTERM/health-check logic is identical.
- **Together with Plan #18 (Magpie Qdrant API key)** — the supervisor generates the key on first start, persists it, and passes it to both server + in-process client. Doing API auth before the supervisor exists means duplicating the key-read in two places.

**Risk if deferred:** every new `just` recipe that touches Qdrant accretes a `xxx: qdrant-up` dependency edge (today: `reset-index`; next: `ingest`, `search`, `recover-fast-tier`...). The recipe-prereq pattern is a band-aid that doesn't survive into the packaged app. The longer the supervisor is deferred, the more places quietly assume "Qdrant just is running" — and each silent assumption becomes a connection-refused stack trace the user has to translate into "oh, run `just qdrant-up`." Tauri users will hit the same wall with no `just` to run.

---

## 21. Surface drift events: warn before silently dropping vanished files / folders

**Tags:** ui · indexing

**What:** Today, when a sync detects that a file or whole folder the user
asked Magpie to index is gone from disk, the pipeline silently drops every
trace of it: the Qdrant points (file-level summary + per-row points for
CSVs + per-page ColPali patches), the on-disk summary markdown, and the
manifest entry. The walker's prune counter (`run_batch` in
[src/ingest/walker.py](../src/ingest/walker.py)) reports a number — "pruned
3 manifest entries" — but never names them. `just clean-stale-manifest`
behaves the same.

This plan: **before** dropping anything, enumerate what's about to be
removed (files, folders, summary markdowns, expected Qdrant point counts)
and surface that to the user with a clear warning. Two surfaces:

1. **CLI / `just sync` terminal output:** print a red-text block listing
   each vanished path with what'll be dropped. Default behavior stays
   "drop after warning" so unattended runs don't stall, but a flag
   (`--confirm-drops` or `JUST_SYNC_CONFIRM=1`) gates the drop on a
   `y/N` prompt for cautious users.

2. **Tauri UI (when the Plan #16 settings panel ships):** a notification
   row or modal listing the drift events the same way, with options
   "drop them" / "keep them" / "show me what was dropped." If the user
   says "keep them," the manifest entries stay (with `skip_reason="orphaned: source missing"`)
   and the user can investigate before re-running.

**Example terminal output:**

```
== walking /Users/mriddy/Desktop/notes ==
…
WARNING: 4 paths in the manifest no longer exist on disk —
they will be dropped from the index, summaries, and Qdrant
collections. If you renamed or moved them, restore them
before dropping (or use --keep-drift to leave the manifest entries
in place for a manual decision):

  - /Users/mriddy/Desktop/notes/old_paper.pdf  (3 Qdrant points,
        1 summary markdown, 12 ColPali pages)
  - /Users/mriddy/Desktop/notes/spring_archive/  (entire folder gone;
        87 manifest entries, 87 summaries, 2,341 row points)
  - /Users/mriddy/Desktop/notes/draft_v2.md  (1 Qdrant point,
        1 summary markdown)
  - /Users/mriddy/Desktop/notes/data/sales.csv  (1 file-level
        summary point + 1,200 row points + 1 summary markdown)

Dropping in 5 seconds (Ctrl-C to abort) …
```

**Why we want this:**

- **The biggest cost in a local-first RAG app is silent data loss the
  user didn't intend.** A user who renamed a folder won't realize
  their re-ingest will silently re-summarize 1,000 files (LLM calls,
  Qdrant churn, ~hour of wall time on local Gemma 4) and drop the old
  state with no recovery path. A 5-second pause + a clear message is
  the minimum dignity owed.
- **The current "manifest entry stat()s as missing → drop" rule
  doesn't distinguish between intentional deletion vs. mount unavailable
  vs. rename mid-walk vs. backup software temporarily moving files.**
  Surfacing the list lets the user judge whether the disappearance is
  real or a transient.
- **Folders are a natural unit:** one rename of a parent folder shows up
  as N orphan entries today, listed individually. Grouping by deepest
  surviving common prefix ("entire folder gone: spring_archive/")
  makes the warning legible. "I renamed `spring_archive/` to
  `spring_2025/`, please don't drop 87 summaries" is a one-glance
  decision.
- **Helps debug daemon mode (Plan #13 / pre-#13):** when the future
  watcher fires off-hours, the user comes back to "I lost
  87 summaries last night, why?" Today's silent log line gives no
  trace; a structured drift event ("at 2026-05-07 02:14, watcher
  observed `spring_archive/` removed → dropped 87 entries") preserves
  the audit trail.

**Why we did NOT do it now:**

- The packaging story (Plan #10) determines where the warning surfaces
  best — terminal-only is fine for developers running `just sync`
  manually but useless for non-developer Tauri users who never see a
  terminal. Doing the CLI piece without the UI piece means
  re-implementing once for each surface.
- The grouping / deepest-common-prefix logic ("entire folder gone")
  is a small but meaningful UX exercise — not just `os.path.commonpath`,
  because we want to distinguish "user removed all 87 files
  individually" (rare but possible — 87 individual messages) from
  "user removed the parent folder" (one folder-level message).
- The "skip / keep / re-confirm next time" UX needs design alongside
  the eventual indexing-rules settings panel (Plan #16) — it's a
  per-orphan decision that should persist somewhere the user can see
  later, not a one-shot terminal prompt that disappears.

**When to revisit:**

- Immediately after the daemon watcher (the future "react to file
  changes" piece, partially in Plan #13) — at that point silent drops
  start happening on a schedule the user didn't initiate, and lack
  of audit trail becomes a real complaint surface.
- Or sooner if any beta user reports "Magpie deleted my summaries
  when I just renamed a folder, and I had to re-summarize from
  scratch because there was no way to tell it the folder still
  existed under the new name."

**Implementation sketch:**

- Refactor the prune logic in `walker.run_batch` and
  `Manifest.clean_stale` (and `pipeline.reset`'s underlying
  cleanup helpers) into a single `compute_drift_events(manifest) ->
  list[DriftEvent]` that returns each vanished entry with: path,
  kind (file vs folder), Qdrant point count expected (file-level +
  row + page), summary markdown path, mtime of last successful
  ingest. **Read-only** — does not delete anything.
- New `apply_drift_events(events, *, dry_run=False)` actually performs
  the drops (Qdrant deletes, summary markdown unlinks, manifest row
  removal). All current call sites switch to `compute → present →
  apply`.
- CLI surface: `just sync` calls compute → prints the warning block
  → 5-second sleep (`Ctrl-C to abort`) → applies. With `--confirm-drops`,
  prompts y/N. With `--keep-drift`, prints the warning but skips
  the apply step.
- UI surface (when Plan #16 settings panel exists): the daemon's
  watcher posts drift events to a `/events/drift` endpoint; the UI
  shows them in a "Files no longer in your index" section with
  per-entry buttons. The same `apply_drift_events` is the action
  target — reused, not re-implemented.
- Grouping heuristic: when ≥10 manifest entries share a deepest
  common ancestor that is also gone from disk, render as one
  folder-level event instead of N file-level events. Threshold and
  exact rule (e.g. "≥80% of children gone") tunable; start simple,
  measure on real data.

---

## 22. Adding a new local LLM — playbook (Qwen2.5-VL, LFM2-VL, MiniCPM-V, …)

**Tags:** models · indexing

**What:** Concrete checklist for swapping or adding a new local model on top of the `llama-server` backend (PRs 1–4 of the migration; full design lives in [`Specs/llama_server_migration.md`](../Specs/llama_server_migration.md)). Today, only Gemma 4 E4B is wired — `LOCAL_MODEL=<some other repo>` in `.env` fails immediately because the model-downloader's filename dispatch and the launch-profile registry are both hardcoded to that one repo. This plan documents the seven concrete steps and the four common failure modes so the next person doesn't relearn them by hitting each one in production.

**Why this isn't already a feature:** every multi-modal family has small but real shape differences in (a) the GGUF / mmproj filename convention, (b) the chat template's thinking-mode flag (Gemma 4 reads `chat_template_kwargs.enable_thinking`; Qwen / LFM2 may use a different name), and (c) memory headroom. Hardcoding Gemma 4 was the right call for the first ship — it kept the migration tight and validated the architecture. Generalizing the dispatch is straightforward but has to be backed by per-model verification, not just config plumbing.

**Why we did NOT do it now:** no concrete second model to support yet. The infrastructure is ready (the spec calls out Qwen as opt-in for PR 2; the architecture is universal in llama.cpp's `--mmproj` system). Worth implementing the moment we have a real second model picked, not before — the abstraction is cleaner when it has a second concrete data point to abstract over rather than being designed in the abstract.

**When to revisit:** when any of these triggers fire — (a) a user reports OOM on Gemma 4 E4B and we need a smaller default (LFM2-VL-1.6B); (b) we measure receipt-summary quality on Gemma 4 and find it lacking vs. Qwen2.5-VL-7B on a RAM-rich machine; (c) we want Apache-2.0 licensing parity with LFM (Gemma's license has commercial-use restrictions); (d) Plan #9's LFM2 eval concludes one is worth shipping by default.

### The seven-step pipeline

For each new model, in order:

1. **Filename patterns** — `src/inference/model_downloader.py`. Add the new repo to `_filename_for(repo_id, quant)` and (if vision) `_mmproj_filename_for(repo_id, variant)`. Both currently dispatch on equality against `"unsloth/gemma-4-E4B-it-GGUF"`. Add an `elif repo_id == "<new-repo>": return "<pattern>"`. Verify the filename pattern against the repo's HuggingFace file listing — Unsloth's GGUF naming, Bartowski's, ggml-org's, and the model author's repos all differ.

2. **Profile registration** — `src/inference/profiles.py`. Add a `register(ModelProfile(...))` call with a clear name (e.g. `qwen-2.5-vl-7b-vision`, `lfm2-vl-1.6b-vision`). Reuse `LaunchArgs` defaults where they fit; override `ctx_size`, `temperature`, `mmproj_variant` per the model's needs. Keep `jinja=True` — every model in this class ships its chat template inside the GGUF.

3. **Default-profile decision** — leave `default_text_profile()` pointed at Gemma 4 unless this model is meant to replace it. Adding a profile doesn't change defaults; users opt in via `LLAMA_SERVER_TEXT_MODEL=<new-profile-name>` in `.env`. (See spec post-validation deviations log: the default is the *vision-capable* profile so one subprocess serves text and image. New default candidates must support that pattern.)

4. **Min-version pin** — confirm the new model's architecture is supported by the current `LLAMA_SERVER_MIN_VERSION` pin (today `b9049`). Check llama.cpp's release notes for `<arch> support added` — the spec's pin-bump deviation (b5400 → b9049 because `gemma4` arch wasn't in b5400) is the cautionary tale here. If the new model needs a newer pin, update `DEFAULT_MIN_VERSION` in `src/inference/llama_server_binary.py` AND `LLAMA_SERVER_VERSION` in `src/tools/install_llama_server.py`.

5. **Thinking-mode flag** — verify (or override) `chat_template_kwargs.enable_thinking`. Currently the request body always sends this flag (see spec deviations log re: Gemma 4's silent thinking-mode footgun). If the new model's chat template uses a different kwarg name (some templates use `thinking`, some `enable_reasoning`), either the model template will silently ignore ours and emit reasoning content into `content` (fine for us — `_extract_content`'s `reasoning_content` fallback covers the inverse case), or thinking still leaks. Test with `max_tokens=512` against a known-answer prompt; if the response is shorter than expected, check `reasoning_content` in the raw JSON to confirm.

6. **Validation tests** — extend `tests/inference/test_vision.py::test_vision_recovers_visible_text_from_fixture_image` (gated by `LLAMA_SERVER_VISION_INTEGRATION=1`) to optionally run against the new profile. Add a profile-specific parametrization or a new `test_<profile>_recovers_visible_text` so the gate catches model-specific regressions. Same for `tests/test_mlx_smoke.py` — its image / answer tests already use the profile resolved by `LLM_PROVIDER=local`, but the assertion list (`_FIXTURE_IMAGE_LABELS`) may need expanding if the new model paraphrases differently than Gemma 4 does. Don't loosen the assertion to "any non-empty string" — that re-opens the empty-content footgun.

7. **Real-corpus smoke** — `LLM_PROVIDER=local LLAMA_SERVER_TEXT_MODEL=<new-profile> just sync` against a small known folder before claiming the profile works. Inspect the resulting summary markdowns for image-derived content (not just file metadata) and reasonable JSON-repair success rate (parse failures = `(model output could not be parsed into Answer)` lines in the per-file logs). The vision integration test catches the obvious failure modes; the smoke catches the schema-mismatch + JSON-repair-too-aggressive failure modes that only show up on real prompts.

### The four common failure modes

Each one has bitten us at least once during the Gemma 4 work. Pre-empt by checking up-front:

- **Filename dispatch hardcoded → `ValueError: unknown GGUF repo`.** Step 1 above. Failure mode is loud and easy.
- **Min-version pin too old → `unknown model architecture: '<arch>'`.** Step 4. Caught only at first inference call (after model download), so cycle time to discover is ~5 min instead of seconds.
- **Thinking mode silently eats the token budget → `content: ''` even though `usage.completion_tokens` says full budget consumed.** Step 5. Reproducibly empty-output, integration test catches it if the assertion is "≥1 fixture label" rather than "non-empty."
- **`max_tokens` too low for thinking + content together.** Even with thinking suppressed, some prompts produce long answers. If a regression bumps thinking back on AND `max_tokens` is at LOCAL_MAX_TOKENS=2048, the content may still be truncated. Symptom: complete sentences cut off mid-word. Fix in caller, not here.

### Notes for the future implementer

- The pipeline order above is the minimum-cycle order. Steps 1–3 are mechanical; step 4 needs a llama.cpp release notes lookup; step 5 is the empirical-test step that's easy to skip and expensive to skip.
- Don't generalize `_filename_for` into a config table until there are ≥3 concrete entries. With one (Gemma 4 today) it'd be over-engineered; with three the pattern shape is clear.
- The architectural assumption — mmproj idle for text-only — is verified for Gemma 4 (spec post-validation deviations log) and *expected* for Qwen / LFM2 / MiniCPM-V from llama.cpp's [multimodal docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md), not separately verified. Step 7's real-corpus smoke is what closes that gap when adding a new family.
- If the new model is text-only (no vision), skip step 1's mmproj dispatch and the profile's `mmproj_repo_id` field. The pool's `_build_argv` already handles the "no mmproj" case for the legacy `gemma-4-e4b-text` profile.
- License check before defaulting: Gemma's license has commercial restrictions; LFM2 is Apache-2.0-derivative; Qwen is Tongyi Qianwen LICENSE (research-friendly, commercial restrictions over $10M ARR). Any profile we promote to the default needs license sign-off, not just technical sign-off.

---

## 23. MLX backend (Apple Silicon opt-in) for raw speed

**Tags:** models · config

**What:** Add Apple's [MLX](https://github.com/ml-explore/mlx) as a *parallel* local-inference backend for Mac users who want the extra throughput. Llama.cpp server stays the default and only cross-platform path; MLX runs alongside as an opt-in engine selected via `LLM_BACKEND=mlx` (or a Plan-#16 settings-UI dropdown). Both engines satisfy the existing `LocalLLM` Protocol, so callers (LocalAgent, /generate, the answer step) don't change.

**Why we'd do it.** Independent benchmarks (see [contracollective.com](https://contracollective.com/blog/llama-cpp-vs-mlx-ollama-vllm-apple-silicon-2026), [arxiv 2511.05502](https://arxiv.org/pdf/2511.05502)) show MLX delivering 20-40% higher autoregressive throughput than llama.cpp on Apple Silicon for models under ~14B parameters — the regime Magpie lives in. On an M1 Max running Gemma 4 E4B Q5_K_XL we measured ~22 tok/s under llama.cpp `b9049` (post llama-server-migration); MLX equivalent should land around 27-30 tok/s. For a 76-second answer-step run, that's ~55s instead — a real felt difference for users who do many Q&A turns per session. The advantage narrows to ~zero at 27B+ where memory bandwidth (273 GB/s on M2, 400 GB/s on M2 Ultra) becomes the bottleneck, but Magpie's defaults sit comfortably below that threshold.

**Why we did NOT do it now.**

- **Apple-only.** Magpie's portability claim is the table stakes. Llama.cpp serves Mac, Linux x86_64, Linux arm64, and Windows from one binary; MLX can't help Rahul on his Linux box. Adding MLX as the *default* would split the team's testing matrix; adding it as an *opt-in* keeps the matrix manageable but is still real fork maintenance.
- **Headline-vs-effective throughput trap.** [Famstack's analysis](https://famstack.dev/guides/mlx-vs-gguf-apple-silicon/) measured 51 tok/s reported but 3 tok/s wall-clock for Qwen3.5-35B at 8.5K context on M1 Max. The benchmark numbers above are mid-generation; Magpie's RAG workloads have heavy prefill (multiple file contents stuffed into the answer prompt). The real-world speedup may be far less than the benchmarks promise once prefill, KV-cache management, and image-encode time are counted. Doing this without measuring on Magpie's actual workload first is wasted effort.
- **Vision parity gap.** Llama.cpp's `--mmproj` is the universal pattern across Gemma 4 / Qwen-VL / LFM2-VL / MiniCPM-V (spec deviation log + Plan #22). MLX has working multimodal support but the API surface is different — would need a separate weights downloader, a separate vision adapter, separate per-model verification. The work isn't impossible but it's the same scope as PR 2 of the llama-server migration, repeated per family.
- **Bundling story differs.** Plan #10 (self-contained packaging) targets a single binary that ships in the .app. Llama.cpp is one C++ binary + GGUFs. MLX is a Python framework with its own compiled kernels, weight format, and pip-style dependency tree — packaging that into a notarized .app is meaningfully harder. Wait until Plan #10's macOS-specific build path is concrete before adding a Mac-specific runtime.

**When to revisit.** Any of these triggers fire:

- A Mac user (you, Rahul, or an early customer) reports answer latency or summary throughput as the bottleneck during real use — not as a hypothetical speedup. Should be measured on the actual Magpie workload (long-context RAG), not micro-benchmarks.
- Plan #10 ships a bifurcated build pipeline that already produces Mac-specific .app artifacts (vs. a single cross-platform binary). At that point a Mac-only second backend is a marginal cost increase on top of the bifurcation.
- A vision-capable MLX adapter for Gemma 4 / Qwen2.5-VL / LFM2-VL reaches parity with llama.cpp's mmproj in upstream MLX or community libraries (so we'd be wiring an existing adapter, not building one).
- We hit a llama.cpp issue that MLX dodges (e.g., a regression in Gemma 4 thinking-mode handling that's already fixed upstream in MLX). Specific motivation, specific fix.

**Scope sketch (~500-800 LOC if/when we do it):**

- New `src/inference/mlx_local_llm.py` — `MLXLocalLLM` class implementing the `LocalLLM` Protocol. Same `complete` / `complete_sync` / `stream(images=...)` surface as `LlamaServerLLM`. Internally calls `mlx_lm.generate` / `mlx_vlm.generate`.
- New `src/inference/mlx_weights.py` — analog of `model_downloader.py` for MLX weight format. MLX models are typically distributed as separate HF repos (e.g., `mlx-community/gemma-4-E4B-it-4bit`). Add the filename / variant dispatch table here, similar to Plan #22's pattern but for MLX.
- Backend selector at the singleton level — `get_local_llm()` reads `LLM_BACKEND` env var, returns either `LlamaServerLLM()` (default) or `MLXLocalLLM()`. Exists at one place; everything else is unchanged.
- No subprocess pool needed — MLX is in-process Python (no spawn / health-check / LRU machinery from `LlamaServerPool`). MLX has its own KV-cache management.
- Settings UI integration (depends on Plan #16): a "Backend" dropdown surfaces `llama-server` / `mlx (Apple Silicon only)`. Greyed out on non-Apple-Silicon hosts.
- Tests: new `tests/inference/test_mlx_local_llm.py` mocking `mlx_lm` / `mlx_vlm`. Real-spawn integration test gated by `LLAMA_SERVER_VISION_INTEGRATION` (or a new `MLX_VISION_INTEGRATION`) flag, same pattern as the llama.cpp one.

**Notes for the future implementer:**

- The `LocalLLM` Protocol was designed precisely so a swap like this doesn't ripple through callers — see [`Specs/llama_server_migration.md`](../Specs/llama_server_migration.md) Pre-flight audit. Verify that contract still holds before starting (the `images=` kwarg + `chat_template_kwargs.enable_thinking` body shape are post-2026-05 additions that MLX may need to mirror differently).
- Don't pin MLX as the default even on Apple Silicon. The opt-in flag is load-bearing — users on tight RAM, users mixing platforms across machines, and users running into MLX-specific bugs all need a one-flag escape hatch back to llama.cpp.
- Measure ONE specific thing first before committing: end-to-end answer-step latency on a typical Magpie corpus question (long retrieval prompt + Gemma 4-class model) under MLX vs. llama.cpp, on the same machine, with a warm pool. If the gap is < 15% wall-clock for our workload (not the benchmark workload), the engineering cost isn't justified — bail.
- License sanity check: MLX itself is MIT (Apple). MLX-LM is Apache-2.0. The MLX-format model weights typically inherit from the upstream model's license — same Gemma / Qwen / LFM2 license caveats as Plan #22.
- macOS-specific failure mode to watch: MLX requires macOS 13.5+. If we have users on older systems, the opt-in needs to gracefully reject + fall back to llama.cpp with a clear message.

---

## 24. Batch indexing — knobs, per-batch progress, error handling

**Tags:** ingest · ux · perf

**What:** Make the upsert phase of indexing more transparent (finer
progress in the GUI), more configurable (a settings knob, sane defaults
per backend), and more resilient (one bad summary should not poison its
batch). The current implementation is `BATCH_SIZE = 32` in
[src/stage2/db.py:304](../src/stage2/db.py) for summaries and
`BATCH_SIZE = 64` in [src/stage2/csv_ingest.py:12](../src/stage2/csv_ingest.py)
for CSV rows — both hardcoded constants with no live progress reporting
through to the GUI's onboard card.

**Why we'd do it.** Three drivers, all surfaced post-llama-server-migration:

- **Progress feels frozen during upsert phase.** After summarization
  finishes, `ingest_from_manifest` runs the upsert phase — but no
  progress callback is wired through to `_ingest_state["files_done"]`
  in [src/server.py](../src/server.py), so the spotlight onboard card
  sits at 100% / "Indexing N / N files…" while Qdrant is actually still
  receiving batches for another 30-90 seconds. On the Furman corpus
  (1,481 files) the upsert phase is ~46 batches at ~1-2s each —
  observable, but invisible.
- **One poisoned batch wastes 32 files of work.** `_upsert_with_retry`
  retries the whole batch; if the failure is deterministic (one
  malformed payload, an embedder OOM on one over-long text, a
  Qdrant payload-validation error), the batch keeps failing forever.
  The current behavior is to abort the run. Per-batch fallback to
  one-by-one on persistent failure would isolate the bad point and
  let the rest land.
- **Settings UX surface area.** Plan #16 (LLM/inference settings UI)
  proposes user-facing knobs for backend behavior. `BATCH_SIZE` is
  the kind of knob someone running on a 16GB Mac wants to lower
  (lower memory pressure on the embedder) and someone on a 96GB
  workstation wants to raise (higher throughput). It should not stay
  buried as a Python constant.

**Why we did NOT do it now.** The current setup is *correct* — the
embedder's batch parallelism is the load-bearing reason for non-1
batches; see the analysis below. What's missing is observability and
graceful degradation, not the batching itself. The right time to add
all of this is when Plan #16's settings UI lands, so the new knob has
a place to live.

**Numbers we know today.**

| Batch size | Embed phase (relative) | Qdrant phase | Total upsert (1500 files) | UI granularity |
|---:|---:|---:|---:|---|
| 1 | ~30× slower | ~5× slower (HTTP overhead) | ~30 min | Per-file |
| 8 | ~3× slower | ~1.2× slower | ~5 min | Every 8 files |
| **32 (current)** | baseline | baseline | **~1-2 min** | Every 32 files |
| 64 (csv default) | ~10% faster | ~5% faster | ~1.5 min | Every 64 files |
| 128 | marginal | marginal | ~1.5 min | Coarse |

The cliff is between batch=1 and batch=8: the dense+sparse embedders
(sentence-transformers + fastembed) pay a fixed per-call overhead
(kernel launch, tokenizer warmup, attention dispatch) that gets
amortized across the batch. Going below ~8 makes ingest dramatically
slower; going above ~32 has rapidly diminishing returns. This is
*not* a Qdrant-server cost — Qdrant is a persistent process and
[get_qdrant_client()](../src/stage2/db.py) caches the HTTP client,
so per-call HTTP overhead is small (~1-5 ms locally). The cost is
the embedder.

**Scope sketch (~150-300 LOC):**

- **Wire `on_batch_complete` through to the GUI.** The function in
  [src/stage2/db.py:307](../src/stage2/db.py) already accepts a
  callback that fires with the indices of the just-upserted batch.
  `ingest_from_manifest` in
  [src/stage2/__main__.py](../src/stage2/__main__.py) doesn't pass
  one; [src/server.py:_do_ingest](../src/server.py) needs to thread
  a callback that updates `_ingest_state["files_done"]` and
  `_ingest_state["current_file"]` during the upsert phase too —
  not just during summarization. Two-phase progress: phase A
  (summarize, file-level), phase B (upsert, batch-level).
  Distinguish in the GUI ("Summarizing 423 / 1,481…" vs.
  "Indexing 1,440 / 1,481…").
- **Per-batch one-by-one fallback on persistent failure.** Wrap
  `_upsert_with_retry`'s retry loop: if all retries on a 32-point
  batch fail with a deterministic-looking error (4xx from Qdrant,
  any non-network-y exception), split the batch in half and retry;
  recurse to single-point. Skip the one bad point with a clear
  log line and a structured entry on the manifest so the user can
  see "5 files failed during indexing" in Settings → Index Health.
  Keep network errors (timeouts, connection-refused) on the
  whole-batch retry path — splitting won't help.
- **Make `BATCH_SIZE` a setting.** Move the constant into
  `magpie_defaults.json` (ingest.summary_batch_size,
  ingest.csv_row_batch_size). Override per user via the settings
  endpoint added in Plan #16. Bound the range: [4, 128]. Default
  stays at 32 / 64 to preserve current behavior.
- **Per-backend defaults.** Cloud LLM ingest paths don't run an
  embedder at upsert time (different code path), so their batch
  cost is purely Qdrant HTTP — those can default to 64 or 128.
  Local-LLM users on lower-spec Macs may want to drop to 16 to
  reduce memory pressure during the dense+sparse embed step.
  Defaults table lives next to the constant.

**Notes for the future implementer:**

- Don't lower the default below 16. The cliff between batch=1 and
  batch=8 is the load-bearing reason this Plan exists *as a Plan*
  rather than as "just lower the constant." Users won't know what
  number to pick; defaults need to stay in the safe zone.
- The bisect-on-failure logic must short-circuit on the *first*
  network-shaped exception (`ConnectionError`, `ReadTimeout`) and
  fall back to whole-batch retry-with-backoff. Bisecting through a
  flaky network adds latency without helping. Reserve bisection for
  errors that look deterministic (Qdrant 400s, payload validation,
  `ValidationError`).
- The progress callback's `indices` argument is into `summaries`,
  not the manifest. The GUI's `files_done` counter wants
  manifest-relative numbering — call sites need to translate. See
  the existing `manifest.mark_ingested(...)` for how the indirection
  is handled today.
- "Two-phase progress" is honest UI but might confuse a non-technical
  user. The settings spec ([Specs/settings_window.md](../Specs/settings_window.md))
  says the user surface is "folders + files + questions + answers" —
  exposing "summarizing vs upserting" violates that. Internal terms
  for power users (visible in Settings → Index Health activity log)
  are fine; the spotlight onboard card should keep saying "Indexing
  N / N files…" but the *N* should advance through both phases.
- Consider deleting [src/stage2/csv_ingest.py:12](../src/stage2/csv_ingest.py)'s
  separate `BATCH_SIZE = 64` if the unified setting moves both. CSV
  rows are smaller payloads than file summaries (no markdown body,
  just a row dict), so a higher default is appropriate, but having
  two unrelated constants drift is a maintenance smell.

---

## 25. Answer-step output schema — empirically evaluate two open choices

**Tags:** models · answer · ux · evaluation

**What:** Two design choices made by hand for the v1 ask-bar
(`Specs/UI/ask_bar.md`) need empirical evaluation against the
Gemma 4 E4B local backend on real Magpie corpora. Both decisions
favored "what works on a 4B model today" over "what's most
type-safe in principle." When we have the eval infrastructure
to back-test alternatives — or when we move to a larger Local
model or default-Cloud — revisit them.

### Choice A — Flat-schema-with-`not_found`-boolean vs. discriminated union

**v1 picked:** flat schema with a `not_found: bool` discriminator
and optional `not_found_topic` field, validated by Pydantic but
not via a discriminated-union type.

```python
class AnswerResult(BaseModel):
    answer: str
    sources_used: list[SourceCitation]
    not_found: bool = False
    not_found_topic: str = ""
```

**The alternative considered:** a Pydantic-AI-native discriminated
union with two variants (`AnsweredResult` | `NotFoundResult`),
each with its own required fields, dispatched via `kind` literal.

**Why we picked the flat shape on Gemma 4 E4B.** Discriminated
unions are correct *type design*. They're also harder for small
models to *choose between* — empirically, 4B-class models tend to
default to "always answer" when asked to pick between variants,
even when retrieved sources don't contain the answer. The flat
schema has only three fields the model thinks about ("set
answer+sources OR set not_found+topic"), and the boolean
discriminator pattern already works reliably in our `FileSummary`
and other structured outputs. Server-side JSON-schema enforcement
catches malformed JSON in either approach; the difference is the
model's *decision* quality, not its parse correctness.

**What would change our minds.** Any of these:

- A third structured-output state appears (e.g., `partial_answer`,
  or `needs_clarification`). At that point the boolean breaks down
  and a tagged union is mandatory.
- We move the default Local model to a 12B+ class (Plan #22 family —
  Qwen2.5-VL, LFM2-VL larger, etc.) where the model can handle
  variant selection reliably.
- We adopt Cloud as default for free-tier users (the Search & AI
  spec's "Cloud — Our free model for faster answers" path) and
  the Cloud model is a frontier-class model that doesn't have the
  small-model-decision-defaulting problem.
- Empirical evidence: an A/B test on the existing benchmark sets
  (`benchmarks/student_notes`, `benchmarks/course_information`,
  `benchmarks/furman_directory`) shows discriminated-union prompts
  actually getting *better* not_found-recall than the flat
  schema. This is the cheapest experiment to run; should be ~50
  LOC of pipeline plumbing.

### Choice B — LLM-emitted citation markers vs. post-process matching

**v1 picked:** the LLM emits inline citation markers (`[1]`, `[2]`)
in its prose; the frontend renders them as numbered green pill
tags (matching the mockup at `Specs/UI/Screenshot 2026-05-07 at
10.28.51 PM.png`). The schema's `sources_used` is the indexed
list those numbers point at.

**The alternative considered:** the LLM emits prose without
markers; a deterministic post-process step matches phrases in the
answer to passages in the retrieved sources via embedding-cosine
or fuzzy matching, and inserts the citations programmatically.

**Why we picked LLM-emitted markers on Gemma 4 E4B.** It's how
Perplexity, Claude, ChatGPT all do it — the model has full context
on which source supported which claim, so it's the only entity
that can attribute correctly. Post-processing with cosine-match is
prone to false attribution: a passage about "Dr. Marquez" exists in
both `math-dept-2024.pdf` and `faculty-roster.csv`, and the
matcher has no idea which one the model was actually drawing from
when it wrote the sentence. We accept that small models sometimes
miss markers or fabricate them; we'd rather have an honest miss
than a false-precise post-hoc attribution.

**What would change our minds.** Any of these:

- Empirical evaluation shows Gemma 4 E4B miscites > ~10% of the
  time on the existing benchmarks. (The math-dept question on
  Furman is a good test: Dr. Marquez should cite `math-dept-2024.pdf`
  page 4, not `faculty-roster.csv`.) If miss/wrong-cite rates are
  high enough, post-processing might be a net win even with its
  own false-positive rate.
- We add a *second* post-process step anyway (e.g., snippet
  highlighting in the source row) and the matching infrastructure
  is already available. Reusing it for citations becomes free.
- A fast small reranker (Cohere-style) becomes available and can
  do citation grounding as a separate pass — different problem,
  different model, more reliable than asking the answer model to
  do everything in one shot.
- Frontier models from Cloud start over-citing (Claude does this
  occasionally — citing five sources for one sentence). At that
  point a post-process *de-duplication* step layered on top of
  the markers makes sense — a hybrid.

### Concrete eval harness needed

The cheapest path to revisit either choice is the same harness:

1. Take the existing eval files (`benchmarks/*/eval_answer_*.json`)
   and add ground-truth citation positions (which sources should
   each correct answer cite, ideally with page/row numbers).
2. Run the same questions twice — once under each schema/citation
   choice — capture answer + sources + cite positions.
3. Score: precision/recall on `not_found` detection, precision/recall
   on citations, answer correctness (existing rubric).
4. The model that wins both schemas/citations on the same
   benchmark is the right one. If results split, document which
   half of the workload favors which choice.

This harness doesn't exist yet but isn't far from
`benchmarks/student_notes/runner.py` — perhaps 200 LOC of
extension once we have ground-truth citation positions.

### When to do the eval

- After the first ~20 real users have used Magpie and we have
  question logs to validate the assumption that "not_found" cases
  are a meaningful fraction of asks.
- Before we add a Cloud default (because the Cloud model's
  schema-following will be different from the Local model's, and
  decisions made on the Local model may not transfer).
- Before any model swap on the Local backend.

### Notes for the future implementer

- These are *behavioral* choices, not architectural ones — both
  alternatives are within ~50 LOC of swapping in. The Plan exists
  so that "the right answer is empirical" is on the record;
  someone shouldn't quietly switch to discriminated unions because
  it's the more "correct" type without first running the eval.
- Whichever choice ships, the user-facing surface (`ask_bar.md`'s
  five states) is the same. This is a backend-quality concern,
  not a UX concern.
- The `recents.json` payload shape only stores what the LLM
  produced + the backend's `sources_scanned_count`. Both schema
  variants serialize cleanly; replays are unaffected by which
  variant is in use at ask time.

---

## 26. Bring-your-own cloud API key — Settings → Advanced → API Keys

**Tags:** ui · config · security

**What:** Expose `secrets.json`'s per-provider API keys (and
optionally the model fields) for end-user editing through the
Settings UI. Currently parked behind PR 3's "v1 is implicit Cloud"
decision: the Search & AI tab shows a binary Local/Cloud choice;
Cloud routes through whatever credentials shipped in the bundle
(via `bundled_key.txt`) or got bootstrapped from `.env` in dev. A
power user with their own OpenRouter or Moonshot account can't
swap in their key without editing `<APP_DATA_DIR>/secrets.json`
by hand.

**Why we'd do it.** Three drivers, in priority order:

- **Bundled-subsidy unsustainable.** If the build-time-baked
  OpenRouter key in `bundled_key.txt` gets rate-limited, banned,
  or the bill outruns marketing budget, we need users to be able
  to plug their own key in instantly — without a code release,
  without manual file editing.
- **Provider preference.** Some users have a Moonshot subscription
  with a higher quota than our free-tier OpenRouter default, or
  prefer a specific OpenRouter model. Today they can edit
  `secrets.json` directly; ergonomically that's a power-user
  trap (mode 0600 file, no validation, typo-prone).
- **Adding a third provider.** When Plan #16 expands the LLM/inference
  settings UI (or we add `magpie-cloud` as a real hosted backend),
  the per-provider key surface needs a UI home. Better to design
  it once than retrofit.

**Why we did NOT do it now.** PR 3's spec parks this as the
"Advanced" sidebar's first tab. Shipping it in v1 would: (a)
require a key-validation probe per provider (cost a real API call
per Save), (b) need careful UX around password-masked input
(never re-displayed, masked preview format), (c) blow up the v1
"binary Local/Cloud" simplicity goal that the user explicitly
chose. Build it once we have either the trigger above or a stable
v1 surface to layer on.

**Sketch (~300-500 LOC, mostly frontend):**

- **Endpoints** in `src/server.py` (mirror existing /settings/*
  pattern):

  ```
  GET    /settings/keys                    → per-provider {set, masked, valid}
  PUT    /settings/keys/{provider}         → { value }    — sets/replaces
  DELETE /settings/keys/{provider}         → clears the key
  POST   /settings/keys/{provider}/test    → probe call, returns {valid, error}
  ```

  - `GET` returns `{openrouter: {set: true, masked: "sk-or-…fcd10",
    last_validated_at: "...", valid: true}, moonshot: {set: false, ...}}`.
    Never returns the raw key — masking is applied server-side.
  - `PUT` validates with a single test call before persisting (no
    invalid keys in storage). Pydantic length / charset validation
    on the `value` field.
  - `POST .../test` is the same probe for keys already on disk.
    Useful for a "Re-test" button when a provider's auth changes.

- **Storage:** no new fields needed. `secrets.json` already has
  `openrouter_api_key` / `moonshot_api_key`. Add a parallel
  `last_validated_at_<provider>: datetime | null` for staleness
  hints, OR just call `POST /test` on UI mount.

- **Frontend (Settings → Advanced → API Keys tab):**
  - Per-provider row: provider name, status pill (Set / Not set /
    Invalid), masked preview (`sk-or-…fcd10`), last-tested time,
    Set/Replace/Remove/Test buttons.
  - Set/Replace input is password-masked, never re-displayed after
    save. On submit, call `PUT` (which validates server-side) and
    surface the result inline.
  - Remove confirmation: "Magpie won't be able to use OpenRouter
    until you add a key again." Single-button confirm.

- **Provider-test logic** (server side): a tiny probe per provider.
  OpenRouter: `GET /api/v1/auth/key` (returns `{data: {label,
  rate_limit, ...}}` — proves the key is live without consuming
  quota). Moonshot: a small `chat.completions` call with `max_tokens=1`
  on a cheap model. Both cap at 5s timeout.

- **Tests:**
  - `tests/test_keys_endpoints.py` — TestClient + monkeypatched
    httpx for the probe.
  - Unit test for the masking helper (`sk-or-v1-…fcd10` shape, no
    leading/trailing leak).

**Trigger to start.** Earliest of:
- We add a third cloud provider (Plan #16 expansion).
- A real user reports needing to swap in their own key.
- Bundled-subsidy bill / quota becomes a problem.

**Notes for the future implementer:**
- Don't store the validation timestamp in `secrets.json` (it's
  read-only-ish, mode 0600). Use a separate `keys_meta.json` at
  mode 0644 with `{provider: last_validated_at}` if that's wanted —
  keeps the secrets file scoped to credentials only.
- If/when we ship Magpie Cloud (Plan #16's `magpie-cloud` provider),
  the API key for that lives in the same surface but with a
  different UX (tied to a Magpie account, not a provider portal).
  The endpoint surface should be provider-agnostic — `/settings/keys/{provider}`
  works for `magpie-cloud` too.
- Consider OS keychain integration via Plan #19 *before* shipping
  this. Plan #19 moves secrets out of a flat JSON into the OS-managed
  Keychain (macOS) / Credential Locker (Windows) / Secret Service
  (Linux). If keychain lands first, Plan #26's storage shifts —
  same endpoints, different backing store.

---

## 27. Abort in-flight queries on retype / window blur (UI URGENT)

**Tags:** ui · perf · pipeline

**What:** When the user types something else mid-retrieval or
re-summons during an in-flight query, kill the underlying pipeline
work end-to-end — not just discard the response on the frontend.
Today the gen counter in MagpieWindow drops stale responses on
arrival, but the Python sidecar runs the full rewrite + retrieval +
answer LLM call regardless. On local Gemma 4 that's ~26s of wasted
GPU compute per cancellation, AND because llama-server processes
requests serially, the user's *next* ask waits for the cancelled
one to finish before its own LLM call starts — real felt latency.

**Why we'd do it.** Three drivers:

- **Local-LLM serial queue.** llama-server (one slot, one model
  loaded) processes one completion at a time. Stale-but-running
  completions block new asks. The user types Q2 mid-Q1; Q1 hogs
  the slot for 20+ seconds before Q2 even starts. Net: typing
  during retrieving feels responsive in the UI but slow in
  practice.
- **Cloud spend.** Once the bring-your-own-cloud-key flow lands
  (Plan #26), every cancelled query bills the user's account for
  the wasted tokens. Aborting saves real money.
- **Pipeline health.** Long-tail compute that nobody's reading
  the result of is just heat. Killing it tightens the system.

**Why we did NOT do it now.** The frontend gen-counter UX fix
covered the visible symptom in PR 4. End-to-end abort is invisible
to the user (they see the same responsive typing), but it's
non-trivial: needs AbortController plumbing through `postQuery`,
FastAPI disconnect detection through every `await` point in the
pipeline, and explicit cancellation propagation to llama-server's
streaming connection. Worth doing as a focused sweep, not bolted
onto PR 4.

**Scope sketch (~150-300 LOC):**

- **Frontend `postQuery`** ([frontend/src/api.ts](../frontend/src/api.ts))
  — accept an `AbortSignal` arg, pass to `fetch({ signal })`. The
  ask-bar's `submitQuestion` creates one per ask; the gen-counter
  mismatch path now also calls `controller.abort()`.
- **Backend `/query` handler** ([src/server.py](../src/server.py))
  — accept the `Request` object, check `request.is_disconnected()`
  at the start of each major pipeline phase (rewrite, retrieve,
  answer). Raise `asyncio.CancelledError` to propagate.
- **`src/pipeline.py:ask`** — accept an asyncio cancellation
  signal; propagate `CancelledError` from `answer_question` and
  `rewrite_query`.
- **`src/inference/local_llm.py`** — when the streaming HTTP
  connection to llama-server is closed (because the parent task
  was cancelled), llama-server detects the client disconnect
  and aborts the in-flight slot. Verify llama.cpp build's
  behavior here; may need to send an explicit `/slot/N?action=
  release` if natural disconnect doesn't free the slot.
- **`src/llm.py` cloud path** — pass abort signal through to
  `AsyncOpenAI` clients; OpenAI's SDK already supports `signal`
  parameter.

**Notes for the future implementer:**

- Verify llama.cpp behavior under client disconnect first. Some
  llama-server builds don't free the slot on disconnect, in which
  case the next ask waits anyway and the abort is cosmetic. Test
  with a stopwatch: cancel mid-completion, immediately ask again,
  measure latency to first token of the second ask. Should match
  cold-cache latency, not "wait for the cancelled completion to
  finish + cold-cache" latency.
- Order: ship the AbortController frontend wiring + FastAPI
  disconnect detection FIRST, even before the llama-server
  cancellation. That alone prevents the wasted compute on cloud
  providers (where the SDK + HTTP-2 stream aborts work cleanly)
  and provides obvious UX value once Plan #26 lands.
- Add a small visible indicator in the retrieving / answering
  state ("Press Esc to cancel") so the user has a deliberate
  cancel path beyond "type something else". Probably reuses the
  status-footer's keyboard-hint slot.
- The submit-disabled-while-loading prop on the QuestionCard's
  ⏎ button stays — once abort lands, the user can either
  retype-to-cancel-old-and-replace OR Esc-to-cancel-and-stay-in-
  typing. The submit button is the third path: only re-enables
  after a fresh edit.

**When to do it.** Marked **URGENT for UI** per the user — every
cancellation today wastes 20-30 seconds of LLM compute that the
user's NEXT ask sits behind. The current "gen counter drops stale
responses" UX is a frontend lie; the backend reality is much
slower than it feels.

---