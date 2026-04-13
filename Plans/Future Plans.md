# Future Plans

Ideas we've decided against doing *right now* but want to revisit. Every entry must include **why** we'd make the change — not just the change itself — so future-us can judge whether the reason still applies.

---

## 1. Swap Kimi-vision PDF fallback for Marker (layout-aware OSS OCR)

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
