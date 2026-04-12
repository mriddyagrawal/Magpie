# Stage 2 — Vector Database & Semantic Search

## Goal

Take the summaries produced by Stage 1 and make them searchable. A user asks a natural language question, the system finds the most relevant documents, and returns their summaries + source paths.

## Architecture

```
User question ("what was my flight cost?")
        ↓
Kimi rewrites it into an optimized search query
        ↓
  ┌─────────────────────────────────┐
  │  SearchQuery (from Kimi)        │
  │  query: "Breeze Airways flight  │
  │         receipt booking cost"   │
  │  keywords: ["flight", "receipt",│
  │    "Breeze Airways", "cost"]    │
  └─────────────────────────────────┘
        ↓
Dense embed (all-MiniLM-L6-v2) + Sparse embed (BM25)
        ↓
Qdrant hybrid search (RRF fusion of dense + sparse)
        ↓
Three-column output: summary, path, score
```

## Key Decision: AI-Assisted Query Rewriting

**Decision:** User questions go through Kimi before embedding.

**Why:** Raw user questions are messy ("hey what was that flight thing I booked?"). An LLM can:
1. Extract the actual intent
2. Produce clean, keyword-rich text that embeds better
3. Generate explicit keywords that boost BM25 exact-match scoring

**What Kimi returns** — a structured `SearchQuery` object (Pydantic model, same pattern as `FileSummary` in Stage 1):

| Field | Type | Purpose |
|---|---|---|
| `query` | `str` | Clean, dense search string optimized for semantic embedding. |
| `keywords` | `list[str]` | 3-8 explicit keywords/entities to boost BM25 sparse matching. |

**Why two fields, not one:**
- `query` feeds the dense vector (captures meaning)
- `keywords` get appended to boost the sparse/BM25 side (catches exact names, IDs, amounts)
- Example: user asks "how much did Mridul pay for the flight?"
  - `query`: "Breeze Airways flight receipt booking transaction total cost"
  - `keywords`: ["Mridul Agrawal", "flight", "receipt", "cost", "Breeze Airways"]

**Reuses the same Kimi setup** from `summarize.py` — same `MOONSHOT_API_KEY`, same model, same `PydanticAI Agent` pattern with `output_type=SearchQuery`.

## Three-Column Output Spec

Per collaborator spec, search output returns exactly:

| Column | Description |
|---|---|
| `summary` | The summary text from the matched document |
| `path` | Source document path (from `Source:` line in summary file) |
| `score` | Relevance score from Qdrant |

Internal payload (title, keywords, entities, content_type) is used for match quality but is **not** exposed in search results.

## Modules

### `notanotherspotlight/parser.py` — Summary Markdown Parser
- Reads `Summaries/*.md` → `ParsedSummary` dataclass
- Extracts: source_path, title, summary, content_type, keywords, key_entities

### `notanotherspotlight/embeddings.py` — Embedding Models
- Dense: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, cosine)
- Sparse: `Qdrant/bm25` via fastembed (IDF-weighted)
- Lazy-loaded, cached as singletons

### `notanotherspotlight/db.py` — Qdrant Cloud Operations
- Connects via `Qdrant_CLUSTER_ENDPOINT` + `Qdrant_API_KEY` from `.env`
- Creates collection with named dense + sparse vector config
- Upserts summaries with full payload (used internally for matching)
- Deterministic point IDs from filename hash (safe to re-run)

### `notanotherspotlight/search.py` — Hybrid Search
- Builds a `PydanticAI Agent` with Kimi to rewrite user questions into `SearchQuery`
- Embeds the rewritten query (dense + sparse)
- Runs hybrid search in Qdrant with Reciprocal Rank Fusion (RRF)
- Returns three-column results: summary, path, score

### `notanotherspotlight/__main__.py` — CLI Entrypoint

Callable as `python -m notanotherspotlight <command>`. Lazy imports per command so startup is fast.

```
# Ingest all summaries into Qdrant
python -m notanotherspotlight ingest [--summaries-dir Summaries] [--force]

# Search documents
python -m notanotherspotlight search "your question" [--top-k 5]
```

| Command | What it does |
|---|---|
| `ingest` | Parses `Summaries/*.md`, embeds via MiniLM + BM25, upserts into Qdrant Cloud. Skips collection creation if it already exists unless `--force` is passed (drops + recreates). |
| `search` | Sends question to Kimi for query rewriting, embeds the rewritten query, runs hybrid search in Qdrant, prints top-K results as summary + path + score. |

| Flag | Default | Description |
|---|---|---|
| `--summaries-dir` | `Summaries` | Path to the directory containing summary `.md` files. |
| `--force` | off | Drop and recreate the Qdrant collection before ingesting. |
| `--top-k` | `5` | Number of search results to return. |

## Project Layout After Stage 2

```
NotAnotherSpotlight/
├── .claude/
├── CLAUDE.md
├── .env / .env.example
├── .gitignore
├── .python-version
├── pyproject.toml
├── log.md
├── plans/
│   ├── Stage 1 - Summary.md
│   ├── Stage 2 - Search.md
│   ├── Pipeline.txt
│   └── Future Plans.md
├── summarize.py                       (Stage 1 — co-founder)
├── notanotherspotlight/               (Stage 2 — this work)
│   ├── __init__.py                    (lazy imports, __version__)
│   ├── __main__.py                    (CLI: ingest / search)
│   ├── parser.py                      (summary markdown → ParsedSummary)
│   ├── embeddings.py                  (dense MiniLM + sparse BM25)
│   ├── db.py                          (Qdrant Cloud client + operations)
│   └── search.py                      (Kimi query rewrite + hybrid search)
├── Summaries/                         (generated by Stage 1)
└── Test Content/                      (input, gitignored)
```

## Dependencies (added to pyproject.toml)

- `qdrant-client>=1.9` — Qdrant Python client
- `sentence-transformers>=3.0` — dense embedding model
- `fastembed>=0.4` — BM25 sparse encoding

## Acceptance Criteria

1. `python -m notanotherspotlight ingest` ingests all summaries from `Summaries/` into Qdrant Cloud without errors
2. `python -m notanotherspotlight search "flight receipt"` returns the Breeze Airways summary + path
3. `python -m notanotherspotlight search "Plato education"` returns Republic/artwork summaries
4. `python -m notanotherspotlight search "club budget spending"` returns DS/ML club budget
5. `python -m notanotherspotlight search "how much did Mridul pay for the flight?"` finds the flight receipt (tests query rewriting)
6. Re-running ingest doesn't create duplicate points
