# Port — running this on my own computer, with my own data

> **Status:** v0 porting notes. Goal: two-phase path from "uses cloud today"
> to "fully local, offline, on a 2–4 GB budget." Written against the
> current `src/llm.py` `ChatAgent` / `build_agent` abstraction (already in
> place in `answer.py`), so the swap is small and reversible.

## The product on my own box — what "testing it" means

I want to run this pipeline against my *actual* documents and videos on my
laptop. That means two separate capabilities that can be unlocked
independently:

1. **Real-data ingest.** Point Stage 1 / Stage 3 at my real folders on
   disk. Get summaries, get a Qdrant index, ask questions.
2. **Offline / private.** No API calls off my machine. Summaries, query
   rewriting, and answers all run on a local small-LLM. Vector DB also
   local.

Phase 1 delivers capability #1 with **zero code changes**. Phase 2
delivers capability #2 and needs a small, confined swap.

---

## Phase 1 — cloud stack, real data (do this first)

### Why first

Before I judge whether a local 3B model is "good enough," I need to know
what *great* looks like on my data. Kimi-grade output on my own documents
is the quality bar I'm measuring against. If I skip Phase 1 and go
straight to local, I'll mistake local-model floor for product ceiling.

### What runs

| Piece | Where | Cost |
|---|---|---|
| Summaries (Stage 1 LLM calls) | Moonshot Kimi | pennies per file |
| Query rewrite + answer generation | Moonshot Kimi | pennies per query |
| Dense embeddings (all-MiniLM-L6-v2) | **local** (already) | free |
| Sparse BM25 (fastembed) | **local** (already) | free |
| Vector DB (Qdrant) | Qdrant Cloud | free tier |

### Steps

```bash
# 1. Docs: summarize + register everything I actually have
uv run python -m src.stage1.summarize "/path/to/my/documents"

# 2. Videos: walk .alt files and register them
uv run python -m src.stage3 "/path/to/videos-with-alt"

# 3. Append to Qdrant Cloud (NO --force — that drops the collection)
uv run python -m src.stage2 ingest

# 4. Before pushing, sanity check what's about to go up
uv run python -c "from src.manifest import Manifest; m=Manifest(); \
  print(sum(1 for v in m.entries.values() if v.ingested_at is None), 'rows pending')"

# 5. Query
uv run python -m src.pipeline "my question"
# or the REPL:
ns
```

### What "testing" looks like

- Pick 10–20 real questions I'd actually ask about my own files.
- Note which ones the pipeline nails, which ones hallucinate, which
  ones retrieve the wrong file.
- Failure modes to watch for: discriminator bleed-through (picks the
  wrong receipt), video scene retrieval ignoring timecodes, queries
  that should have filters instead of similarity.
- Those failures inform what I tune BEFORE porting — porting a broken
  pipeline just means a broken local pipeline.

---

## Phase 2 — fully local, 2–4 GB budget

### What's already local (no change needed)

- Dense embeddings (`sentence-transformers/all-MiniLM-L6-v2`, 80 MB)
- Sparse BM25 (fastembed, small)
- `.alt` parsing + Stage 3 transcoding (no LLM)
- The entire Stage 2 ingest code path

### What needs to move off the cloud

Two things. Only two.

#### 1. Vector DB: Qdrant Cloud → local Qdrant container

```bash
docker run -d -p 6333:6333 -p 6334:6334 \
  -v ~/qdrant-data:/qdrant/storage \
  --name qdrant qdrant/qdrant
```

Change `.env`:

```
# QDRANT_CLUSTER_ENDPOINT=https://<your-cloud>.qdrant.tech
QDRANT_CLUSTER_ENDPOINT=http://localhost:6333
# QDRANT_API_KEY=<remove; local container doesn't need one>
```

`qdrant-client` talks to local-Docker Qdrant with identical Python code.
Zero code change. Re-run `ingest` to rebuild the local collection.

#### 2. LLM: Kimi → local small-model

This is where the 2–4 GB budget matters. Options, worst-to-best within budget:

| Model | Quantized size | Strength | Pull |
|---|---|---|---|
| Gemma 2 2B (Q4) | ~1.6 GB | passable; cheapest to run | `ollama pull gemma2:2b` |
| **Qwen 2.5 3B Instruct** (Q4) | ~2.0 GB | **solid default — strong on structured JSON output, which our Pydantic schemas need** | `ollama pull qwen2.5:3b` |
| Llama 3.2 3B (Q4) | ~2.0 GB | good; reasoning slightly weaker than Qwen | `ollama pull llama3.2:3b` |
| Phi-3.5 Mini 3.8B (Q4) | ~2.3 GB | strong for size | `ollama pull phi3.5` |
| **Qwen 2.5 7B Instruct** (Q4) | ~4.4 GB | **notably better — my pick if I can spare the RAM** | `ollama pull qwen2.5:7b` |

**Apple Silicon note:** `mlx-vlm` is now in `pyproject.toml` (guarded by
`sys_platform == 'darwin'`). That's the vision-capable side of MLX —
useful later for auto-generating `.alt` from raw video frames on Mac.
For text-only summarization / answering, Ollama is simpler and covers
every platform.

### The code swap

`src/llm.py` already exposes `build_agent(system_prompt, output_type,
fallback)` and a `ChatAgent` wrapper. Add a branch there that picks
cloud vs. local from an env var:

```
LLM_BACKEND=kimi    # (default today)
LLM_BACKEND=ollama  # local; base_url=http://localhost:11434/v1, model=qwen2.5:7b
```

Ollama exposes an **OpenAI-compatible** endpoint, so the underlying
PydanticAI / OpenAI-style client stays; only `base_url` + `model` +
(dummy) `api_key` differ. No call-site changes in `answer.py`,
`summarize.py`, `search.py`.

**Structured-output caveat:** our Pydantic `FileSummary`, `Answer`,
`SearchQuery` use `NativeOutput`. Ollama supports JSON schema
constraints through the `/api/chat` `format` field and through the
OpenAI-compat layer's `response_format`. Qwen 2.5 and Llama 3.2 follow
schemas reliably at 3B+; smaller models (2B) sometimes drift. If I see
malformed JSON at 3B, the existing `_ANSWER_FALLBACK` handler in
`answer.py` already covers it — but I should expect more retries than
with Kimi.

### Hardware budget breakdown

A rough map of what fits in common machines:

| Laptop spec | Realistic LLM | Notes |
|---|---|---|
| 8 GB RAM, integrated GPU | Qwen 2.5 3B Q4 | ~5–15 tok/s on CPU; don't run with 20 tabs open |
| 16 GB RAM, integrated GPU | Qwen 2.5 7B Q4 | ~8–20 tok/s on CPU; comfortable |
| 16 GB Apple Silicon (M1+) | Qwen 2.5 7B Q4 via Ollama or MLX | **fastest per watt** by a lot; 30–60 tok/s |
| 32 GB + dedicated GPU | Qwen 2.5 14B Q4 | overkill for this app; marginal gain |

### What I should *not* try to run locally (yet)

- **Vision LLMs** for scanned-PDF fallback and image summarization. The
  current Kimi-vision path is hard to replace at 2–4 GB. If I need
  truly-offline scanned-doc support, the right answer is **Marker**
  (OSS layout-aware OCR, see `Plans/Future Plans.md` item #1) — not a
  small vision LLM. Keep Kimi-vision for images and scanned PDFs until
  Marker lands, OR accept that offline mode skips those files.
- **Auto-generating `.alt` from raw video.** `ffprobe` + keyframe grid
  + a small vision LLM is doable with Qwen2-VL 2B / Moondream, but
  that's a Phase 3 pipeline, not a Phase 2 swap.

---

## Quality expectations — honest version

A 3B model is **visibly worse** than Kimi on:

- Exact-discriminator grounding (invoice numbers, dates, named
  entities). Dense+BM25 retrieval still finds the right file; the
  answer step's paraphrase gets fuzzier.
- Long-context synthesis ("summarize all my receipts from May 2022") —
  smaller context windows.
- Multi-step reasoning in one shot. Chain-of-thought helps but costs
  tokens.

A 3B model is **roughly equivalent** on:

- Short factual Q&A where the answer is verbatim in one retrieved file.
- Structured JSON output for `FileSummary` / `Answer` (with retries).
- Query rewriting (short rewrite target, easy task).

A 7B model **closes most of the gap** for short-to-medium Q&A. If I'm
serious about offline use, 7B is the threshold where "local feels like
a real product" instead of "local feels like a demo."

---

## The decision tree

```
Start
  │
  ├── Just want to try it on my data?           → Phase 1 (cloud), zero changes
  │
  ├── Need offline + my budget is 2 GB?         → Phase 2 (Qwen 2.5 3B + local Qdrant)
  │                                                expect quality regression on details
  │
  ├── Need offline + my budget is 4+ GB?        → Phase 2 (Qwen 2.5 7B + local Qdrant)
  │                                                good daily-driver quality
  │
  └── Need offline + vision too?                → Phase 3 (not planned yet) —
                                                    Marker for docs, local VLM for .alt
```

## What's NOT in this plan

- Automatic model download / bundling into the CLI install.
- A `--backend=local` flag on every command (nice-to-have; add after
  the `LLM_BACKEND` env-var swap proves out).
- GPU acceleration setup instructions (Ollama autodetects; if it
  doesn't, that's a platform-specific ticket, not this plan).
- Benchmarks. After Phase 2 lands, re-run `tests/retrieval_eval.py`
  and `tests/run_pipeline_eval.py` against the local backend and
  document the delta. That's where the *real* quality answer lives —
  not in this plan.

## Open questions

1. **Embedding model swap too?** Could go from MiniLM to a
   question-doc asymmetric model (`bge-small-en`, `e5-small`) while
   we're in there. Tracked already in `Future Plans.md` item #2; keep
   separate from the port.
2. **Per-platform installer story.** A ~one-command bootstrap that
   pulls Docker Qdrant + Ollama + the default model is what turns this
   from "works on my machine" into "shippable." Not blocking Phase 2
   but shapes how I document it.
3. **Does the REPL need a backend indicator?** Probably yes — a tiny
   status line so I never wonder whether I'm about to send my private
   documents to a cloud API.
