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

---

## 8. Smarter T0 / large-CSV retrieval (the ripgrep-at-answer-time approach is leaving signal on the floor)

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