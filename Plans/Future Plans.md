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
