# ColPali Fast Tier — Full IO Flow

Two-tier indexing + RRF fan-out retrieval, end to end. For the feature plan
and v1.1 backlog, see `Plans/IO - Colpali.md`.

---

## A. Indexing: filesystem → two Qdrant collections

```
                    ┌─────────────────────────────┐
                    │  User's documents on disk   │
                    │  (PDFs, images, .docx,      │
                    │   .xlsx, .csv, code, .md)   │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │  ns --sync <dir>            │
                    │  walks recursively          │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │  Router  (router.py)        │
                    │  IN:  file path             │
                    │  OUT: "fast" | "summary"    │
                    │                             │
                    │  rules:                     │
                    │   PDF  ≤50 pages → fast     │
                    │   PDF  >50 pages → summary  │
                    │   PNG/JPG/WEBP   → fast     │
                    │   everything else→ summary  │
                    └──────┬─────────────┬────────┘
                           │             │
                 ┌─────────┘             └─────────┐
                 ▼                                 ▼
    ┌─────────────────────────┐        ┌─────────────────────────┐
    │  FAST TIER              │        │  SUMMARY TIER           │
    │  (stage1_fast/index.py) │        │  (stage1/summarize.py)  │
    └────────────┬────────────┘        └────────────┬────────────┘
                 │                                  │
                 ▼                                  ▼
    ┌─────────────────────────┐        ┌─────────────────────────┐
    │  Page rendering         │        │  Content extraction     │
    │  PDF → pymupdf @150dpi  │        │  (content.py)           │
    │  IMG → PIL.open         │        │  text/PDF bytes →       │
    │  IN:  file path         │        │    text blocks          │
    │  OUT: list[PIL.Image]   │        │  image → vision blocks  │
    └────────────┬────────────┘        └────────────┬────────────┘
                 │                                  │
                 ▼                                  ▼
    ┌─────────────────────────┐        ┌─────────────────────────┐
    │  Device detect          │        │  LLM summarize (Kimi)   │
    │  CUDA ≥8GB → ColQwen2.5 │        │  IN:  filename +        │
    │  CUDA <8GB → ColSmol-   │        │       content blocks    │
    │              500M       │        │  OUT: FileSummary JSON  │
    │  MPS       → ColQwen2.5 │        │       {title, summary,  │
    │  CPU       → ColSmol    │        │        keywords,        │
    │  IN:  -                 │        │        identifiers}     │
    │  OUT: model, processor, │        └────────────┬────────────┘
    │       DeviceConfig      │                     │
    └────────────┬────────────┘                     │
                 │                                  │
                 ▼                                  ▼
    ┌─────────────────────────┐        ┌─────────────────────────┐
    │  ColPali forward pass   │        │  Render to .md          │
    │  IN:  PIL images batch  │        │  Test Summaries/        │
    │  OUT: tensor            │        │   <hash>.md             │
    │   (B, n_patches, 128)   │        │  Source: <path>         │
    │   ColSmol: ~1139 patches│        │  # title                │
    │   ColQwen: ~1030 patches│        │  summary text...        │
    └────────────┬────────────┘        └────────────┬────────────┘
                 │                                  │
                 ▼                                  ▼
    ┌─────────────────────────┐        ┌─────────────────────────┐
    │  int8 quantize + upsert │        │  MiniLM + BM25 embed    │
    │  (fast_db.py)           │        │  (stage2/embeddings.py) │
    │  point_id =             │        │  IN:  title+summary+    │
    │    md5(path + page_N)   │        │       keywords text     │
    │  payload:               │        │  OUT: dense (384d) +    │
    │   {source_path,         │        │       sparse (BM25)     │
    │    page_num}            │        │                         │
    │  vector: (1139, 128)    │        └────────────┬────────────┘
    │    multi-vector         │                     │
    └────────────┬────────────┘                     │
                 │                                  ▼
                 ▼                     ┌─────────────────────────┐
    ┌─────────────────────────┐        │  Upsert to Qdrant       │
    │  Qdrant collection:     │        │  Collection: summaries  │
    │  fast_tier              │        │  point_id = md5(path)   │
    │  vector: 128d multi-vec │        │  payload:               │
    │  comparator: MaxSim     │        │   {summary,             │
    │  quantization: int8     │        │    source_path}         │
    │  ~132 KB/page on disk   │        │  vector: {dense, sparse}│
    └─────────────────────────┘        └─────────────────────────┘
                 │                                  │
                 └──────────────┬───────────────────┘
                                │
                                ▼
                 ┌─────────────────────────┐
                 │  Manifest update        │
                 │  (Test Summaries/       │
                 │   _manifest.json)       │
                 │  fast_indexed_at +      │
                 │  summarized_at +        │
                 │  ingested_at timestamps │
                 └─────────────────────────┘
```

---

## B. Query: user question → RRF-merged answer

```
┌─────────────────────────────┐
│  User types a question in   │
│  ns REPL                    │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Optional: Kimi rewrite     │
│  (.rewrite on)              │
│  IN:  raw question          │
│  OUT: SearchQuery           │
│   {query, keywords[]}       │
└──────────────┬──────────────┘
               │
               ├──────────────────┐
               ▼                  ▼
┌─────────────────────┐  ┌─────────────────────┐
│ Summary-tier embed  │  │ Fast-tier embed     │
│ IN:  query+keywords │  │ IN:  query+keywords │
│ MiniLM → 384d dense │  │ ColPali encode →    │
│ BM25  → sparse      │  │   (n_tokens, 128)   │
│ OUT: (dense, sparse)│  │ OUT: multi-vector   │
└──────────┬──────────┘  └──────────┬──────────┘
           │                        │
           ▼                        ▼
┌─────────────────────┐  ┌─────────────────────┐
│ Qdrant: summaries   │  │ Qdrant: fast_tier   │
│ hybrid RRF search   │  │ MaxSim search       │
│ (dense + BM25)      │  │ over page vectors   │
│ limit = top_k * 2   │  │ limit = top_k * 2   │
│ OUT:                │  │ OUT:                │
│  [(path, summary,   │  │  [(path, page_num,  │
│    score), ...]     │  │    score), ...]     │
└──────────┬──────────┘  └──────────┬──────────┘
           │                        │
           │                        ▼
           │             ┌─────────────────────┐
           │             │ Dedupe by path      │
           │             │ (keep best page)    │
           │             └──────────┬──────────┘
           │                        │
           └──────────┬─────────────┘
                      ▼
           ┌─────────────────────────┐
           │  RRF merge              │
           │  (search.py)            │
           │  IN:  summary_hits[],   │
           │       fast_hits[]       │
           │  score[path] = Σ        │
           │    1 / (60 + rank_i)    │
           │  tier = "summary"|      │
           │         "fast"|"both"   │
           │  OUT: top_k merged      │
           │       SearchResults     │
           └──────────┬──────────────┘
                      │
                      ▼
           ┌─────────────────────────┐
           │  Answer stage (Kimi)    │
           │  (answer.py)            │
           │  IN:  question +        │
           │       retrieved paths   │
           │  reads the ORIGINAL     │
           │   files, not summaries  │
           │   or page images        │
           │  OUT: Answer {answer,   │
           │       sources_used}     │
           └──────────┬──────────────┘
                      │
                      ▼
           ┌─────────────────────────┐
           │  CLI display            │
           │  (display.py)           │
           │  - Retrieved table      │
           │    w/ tier color tag    │
           │  - Answer panel         │
           │  - Sources list         │
           └─────────────────────────┘
```

---

## C. Where each piece lives

| Concern                  | File                              |
|--------------------------|-----------------------------------|
| Device detection         | `src/stage1_fast/device.py`       |
| Model loader (cached)    | `src/stage1_fast/model.py`        |
| File routing             | `src/stage1_fast/router.py`       |
| Fast-tier batch indexer  | `src/stage1_fast/index.py`        |
| Fast Qdrant collection   | `src/stage2/fast_db.py`           |
| Summary Qdrant collection| `src/stage2/db.py`                |
| Summary batch indexer    | `src/stage1/summarize.py`         |
| Query rewrite + search   | `src/stage2/search.py`            |
| RRF merge                | `src/stage2/search.py` `_rrf_merge` |
| Answer stage             | `src/answer.py`                   |
| Pipeline orchestration   | `src/pipeline.py`                 |
| CLI flags + banner       | `cli/magpie_cli/repl.py` + `display.py` |
| Persistent state         | `src/manifest.py`                 |

---

## D. Signals that tell you the fast tier is live

1. **Banner line:** `Fast tier: vidore/colSmol-500M on cuda (...)`
2. **Sync output:** `fast tier: N files indexed (P pages)`
3. **Query results per-row:** each retrieved document shows a `Tier` column
   with `summary` / `fast` / `both`. `fast` means ColPali alone produced the
   hit; `both` means both collections ranked the file.
4. **Collection existence:**
   ```bash
   uv run python -c "
   from src.stage2.db import get_qdrant_client
   c = get_qdrant_client()
   print('fast_tier:', c.collection_exists('fast_tier'))
   print('summaries:', c.collection_exists('summaries'))
   "
   ```

If you see `summary` exclusively in the Tier column, the fast tier isn't
contributing — either the collection is empty, the model failed to load, or
the file routing didn't send anything there. Run `ns --sync=<dir> --fast-only`
to populate it.
