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

### `src/stage2/parser.py` — Summary Markdown Parser
- Reads `Summaries/*.md` → `ParsedSummary` dataclass
- Extracts: source_path, title, summary, content_type, keywords, key_entities

### `src/stage2/embeddings.py` — Embedding Models
- Dense: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, cosine)
- Sparse: `Qdrant/bm25` via fastembed (IDF-weighted)
- Lazy-loaded, cached as singletons

### `src/stage2/db.py` — Qdrant Cloud Operations
- Connects via `QDRANT_CLUSTER_ENDPOINT` + `QDRANT_API_KEY` from `.env`
- Creates collection with named dense + sparse vector config
- Upserts summaries with payload: `{summary, source_path}`
- Deterministic point IDs from filename hash (safe to re-run, no duplicates)

### `src/stage2/search.py` — Hybrid Search
- `rewrite_query()` — Kimi rewrites user question into `SearchQuery` (opt-in, off by default)
- `raw_query()` — pass-through when rewrite is off
- `run_search()` — embeds query (dense + sparse), runs hybrid search via RRF
- `search_summaries()` — top-level: rewrite (optional) → search → return results

### `src/stage2/__main__.py` — Stage 2 CLI Entrypoint

```
<<<<<<< Updated upstream
# Ingest all summaries into Qdrant
python -m src.stage2 ingest [--force]

# Search documents
python -m src.stage2 search "your question" [--top-k 5] [--rewrite]
||||||| Stash base
# Ingest all summaries into Qdrant
python -m notanotherspotlight ingest [--summaries-dir "Test Summaries"] [--force]

# Search documents
python -m notanotherspotlight search "your question" [--top-k 5]
=======
python -m src.stage2 ingest [--summaries-dir "Summaries"] [--force]
python -m src.stage2 search "your question" [--top-k 5] [--rewrite]
>>>>>>> Stashed changes
```

<<<<<<< Updated upstream
| Command | What it does |
|---|---|
| `ingest` | **Manifest-driven and incremental.** Walks `Test Summaries/_manifest.json`, upserts only rows whose `ingested_at` is unset (new summaries + Stage-1 re-summarizations). Embeds via MiniLM + BM25. After upsert, any Qdrant point whose ID isn't in the manifest gets hard-deleted (orphan cleanup). Point IDs are keyed on **source path** (stable across re-summarizations), stored as dashed UUIDs. `--force` drops the collection, clears every `ingested_at`, then re-ingests from scratch. |
| `search` | Sends question to Kimi for query rewriting (if `--rewrite`; off by default — saves ~20s/call), embeds the query, runs hybrid search in Qdrant, prints top-K results as summary + path + score. |
||||||| Stash base
| Command | What it does |
|---|---|
| `ingest` | Parses `Test Summaries/*.md`, embeds via MiniLM + BM25, upserts into Qdrant Cloud. Skips collection creation if it already exists unless `--force` is passed (drops + recreates). |
| `search` | Sends question to Kimi for query rewriting, embeds the rewritten query, runs hybrid search in Qdrant, prints top-K results as summary + path + score. |
=======
### `src/pipeline.py` — Full Pipeline (Stage 2 + Stage 4)
- Orchestrates: question → rewrite → search → read files → Kimi answer → `PipelineResult`
- `PipelineResult` contains: question, search_query, retrieved, answer, sources_used
>>>>>>> Stashed changes

<<<<<<< Updated upstream
| Flag | Default | Description |
|---|---|---|
| `--force` | off | Drop + recreate the Qdrant collection, reset manifest's `ingested_at`, then ingest everything. |
| `--top-k` | `5` | Number of search results to return. |
| `--rewrite` | off | Enable Kimi query rewriting in `search` (adds ~20s per call). |
||||||| Stash base
| Flag | Default | Description |
|---|---|---|
| `--summaries-dir` | `Test Summaries` | Path to the directory containing summary `.md` files. |
| `--force` | off | Drop and recreate the Qdrant collection before ingesting. |
| `--top-k` | `5` | Number of search results to return. |
=======
### `cli/notspotlight/` — Interactive CLI (separate package)
- `repl.py` — prompt_toolkit REPL loop with step-by-step progress display
- `display.py` — rich-based output (panels, tables, spinners)
- Entry points: `notspotlight`, `ns`, `nas`
- Dot-commands: `.help`, `.rewrite on/off`, `.top-k N`, `.clear`
- Install globally: `just install`
>>>>>>> Stashed changes

## Project Layout

```
NotAnotherSpotlight/
├── src/
│   ├── stage1/
│   │   └── summarize.py               (Stage 1 — co-founder)
│   ├── stage2/
│   │   ├── __init__.py                (lazy imports)
│   │   ├── __main__.py                (CLI: ingest / search)
│   │   ├── parser.py                  (summary markdown → ParsedSummary)
│   │   ├── embeddings.py              (dense MiniLM + sparse BM25)
│   │   ├── db.py                      (Qdrant Cloud client + operations)
│   │   └── search.py                  (Kimi query rewrite + hybrid search)
│   ├── content.py                     (shared file extraction)
│   ├── answer.py                      (Stage 4: grounded answer generation)
│   └── pipeline.py                    (full pipeline orchestration)
├── cli/
│   ├── pyproject.toml                 (separate package)
│   └── notspotlight/
│       ├── __init__.py
│       ├── repl.py                    (interactive REPL)
│       └── display.py                 (rich output formatting)
├── tests/
│   ├── stage1/
│   └── stage2/
│       ├── test_parser.py
│       ├── test_db.py
│       ├── test_embeddings.py
│       └── test_search.py
├── Summaries/                         (generated by Stage 1)
├── Plans/                             (architecture docs)
├── IO/                                (input/output diagrams)
├── Test Questions/                    (evaluation data)
├── justfile                           (command runner)
├── spinup.md                          (local dev reference)
├── pyproject.toml                     (main dependencies)
└── .env                               (credentials, gitignored)
```

## Dependencies

Main (`pyproject.toml`):
- `qdrant-client>=1.9` — Qdrant Python client
- `sentence-transformers>=3.0` — dense embedding model
- `fastembed>=0.4` — BM25 sparse encoding

CLI (`cli/pyproject.toml`):
- `prompt-toolkit>=3.0` — interactive REPL
- `rich>=13.0` — output formatting

## Acceptance Criteria

1. `just ingest` ingests all summaries into Qdrant Cloud without errors
2. `just search "flight receipt"` returns the Breeze Airways summary + path
3. `just search "Plato education"` returns Republic/artwork summaries
4. `just search "club budget spending"` returns DS/ML club budget
5. `just chat` launches interactive CLI with banner, suggestions, and dot-commands
6. Asking a question in the CLI shows step-by-step progress and returns answer + sources
7. Re-running ingest doesn't create duplicate points
8. `just install` registers `notspotlight`, `ns`, `nas` as global commands
