# IO — ColPali Fast-Tier Indexing

> **Status:** v0 plan. Active implementation — stages tracked inline below.

## The core problem

LLM-summarized indexing takes 5-35s per file. A user dropping their 1000-file
Downloads folder in waits **~6 hours** before they can search. That's a dead
product for anyone non-technical.

Late-interaction visual embeddings (ColPali / ColQwen) give us an alternate
indexing path that's **GPU-bound, not API-bound**: ~500 pages/min on a 4090,
~24 pages/min on Apple MPS, ~1-2s/page on CPU with a smaller model. Same
1000-file library onboards in minutes, not hours.

## The chosen route — two-tier indexing with RRF fan-out

Instead of replacing the summary pipeline, we run **two collections in
parallel** and merge at query time:

| Tier | What goes here | Index method | Storage |
|---|---|---|---|
| **Fast** | PDFs ≤50 pages, images (PNG/JPEG), receipts | ColQwen multi-vector, int8 scalar quantization | ~132 KB/page |
| **Summary** (existing) | PDFs >50 pages, .docx, .xlsx, .csv, code, markdown, text | LLM summary + dense + BM25 | ~4 KB/file |

At query time we fan out to both collections and merge with Reciprocal Rank
Fusion (RRF). Answer stage is unchanged — Kimi re-reads the original file
once it's retrieved.

## Why keep BOTH tiers instead of choosing one

This is the most important design decision. Summaries are cheap at query time
but slow to build. ColPali is fast to build but has no human-readable artifact.
The tiers cover complementary failure modes:

- **Fast tier catches what summaries miss.** Summaries are prose; they can
  lose layout-heavy signal — a chart, a table cell, a figure caption, a
  handwritten note on a scanned receipt. ColPali encodes the page *as a
  page*, so queries that target visual structure ("the column with the
  totals", "the signed form") can hit pages that the summary text never
  mentioned.
- **Summary tier catches what ColPali misses.** Non-visual files (.docx
  bodies, .xlsx cells, code, markdown) never go through ColPali. They only
  exist in the summary tier.
- **Fast tier onboards instantly; summaries come later.** For a fresh
  library, fast tier is searchable in minutes. Summaries stream in over the
  next hours (or never, if the user chose `--fast-only`). RRF degrades
  gracefully — if one tier has no hits, the other tier's results dominate
  with no code branch.
- **Different retrieval signals on the same file.** A 20-page PDF exists in
  *both* tiers. A query hitting just the summary tier (keyword match on the
  title) vs just the fast tier (visual layout match on page 7) both return
  the same file. Having both means more ways for the right file to surface.
- **Answer stage is source-of-truth, not retrieval.** ColPali "retrieves" at
  the page level, but the answer stage still reads the original file. So
  even though the fast tier doesn't store human-readable summaries, it
  never produces degraded answers — it just points Kimi at the right PDF.

Put simply: **summaries are for retrieval over text meaning; ColPali is for
retrieval over visual structure. Different channels. RRF mixes them.**

## Worked example — end-to-end on one file

User drops `Flight_Receipt_DL1492.pdf` (2-page scanned PDF) into their
indexed folder, then runs `ns --sync`.

**1. Router classifies** it: `is_pdf=True`, `pages=2`, `pages <= 50`, so it
goes to **both** fast tier (ColPali) and summary tier.

**2. Fast tier (ColPali) indexing** — ~250 ms on CUDA:
- pymupdf renders each page to a 448×448 PIL image
- Each page runs through `vidore/colqwen2.5-v0.2` → one multi-vector per page:
  shape `(1030, 128)` float16
- int8 quantize → ~132 KB/page
- Upsert to Qdrant `fast_tier` collection as two points:
  ```
  Point 1: {path: "...DL1492.pdf", page: 1, vectors: <1030×128 int8>}
  Point 2: {path: "...DL1492.pdf", page: 2, vectors: <1030×128 int8>}
  ```

**3. Summary tier indexing** — ~8 s on Kimi (API call):
- Existing pipeline: build_content_blocks → Kimi vision → FileSummary JSON
- Writes `Test Summaries/<hash>.md`:
  ```
  Source: Flight_Receipt_DL1492.pdf
  # Delta flight DL1492 Atlanta → Hartford - Jane Doe
  Delta Airlines flight receipt for passenger Jane Doe...
  Identifiers: DL1492, 25 May 2022, ABC123, $247.50
  ```
- Embeds title+summary → one dense vector + BM25 sparse vector
- Upsert to Qdrant `summaries` collection

**4. User queries:** `"how much was the flight to Hartford?"`

- Fast-tier search: ColQwen encodes the question → MaxSim across both
  pages → page 1 scores 0.72 (the printed total). Returns
  `(path, page=1, score=0.72)`.
- Summary-tier search: MiniLM encodes the question → dense search hits
  the summary with "Hartford" + "$247.50". Returns
  `(path, summary, score=0.81)`.
- RRF merge: same `path` from both channels → combined rank boost.
  Only one path goes to the answer stage.

**5. Answer stage** (unchanged from today):
- Kimi reads `Flight_Receipt_DL1492.pdf` via `build_content_blocks`
- Generates: *"The flight to Hartford (DL1492) was $247.50."*

The fast tier made the file findable before the summary existed. The summary
tier added a keyword anchor. Both pointed at the same PDF, and the answer
stage did what it always does.

**What if the user had dropped a flight receipt with no printed total
amount, only a QR code?** The summary wouldn't catch "$247.50" because it
doesn't exist as text. ColPali might still match the visual layout of a
receipt. Fast tier catches this; summary tier doesn't. That's the point.

## Model fallback chain

Detect hardware at startup; load the appropriate model:

```
CUDA GPU   → vidore/colqwen2.5-v0.2  (~6 GB, ~500 pages/min on 4090)
Apple MPS  → vidore/colqwen2.5-v0.2  (~24 pages/min)
CPU only   → vidore/colSmol-500M     (~1 GB, ~1-2 pages/sec)
```

One-time model download per machine, cached in `~/.cache/huggingface/`.

## File routing rules (ingest-time)

```python
if is_pdf(f):
    pages = count_pages(f)
    if pages <= 50:  tier = "fast"   # also queued for background summary
    else:            tier = "summary"  # too big for fast-tier storage budget
elif is_image(f):    tier = "fast"   # single page; no summary pipeline
else:                tier = "summary"  # docx/xlsx/csv/code/markdown
```

## Storage envelope (int8 quantization, ~1030 patches × 128 dims)

| Library size | Fast-tier storage |
|---|---|
| 500 pages | 66 MB |
| 5000 pages | 660 MB |
| 10,000 pages | 1.3 GB |

Acceptable for a desktop product. Pooling becomes relevant only past 10k
pages (see v1.1 backlog).

## Query-time flow

```
question ─▶ embed (ColQwen text encoder for fast tier;
           │      MiniLM+BM25 for summary tier)
           ├─▶ fast_tier.search   (MaxSim, top-K)     ─┐
           └─▶ summary_tier.search (dense+BM25, top-K) ─┤
                                                        ▼
                                   RRF merge → top-K deduped paths
                                                        ▼
                                   answer stage (Kimi reads file)
```

RRF adds ~50 ms over current single-collection search.

## Command surface

| Command | Behavior |
|---|---|
| `ns --sync` | Default. Fast tier now, summary tier after (foreground, progress split by tier) |
| `ns --sync --fast-only` | Skip LLM summaries entirely (minimum cost, MVP onboarding) |
| `ns --sync --summary-only` | Skip ColPali (legacy path, for debug or no-GPU machines) |
| `ns --sync --pool-factor N` | v1.0 escape hatch — enable token pooling (default: 1 = off) |

---

## Implementation stages

- [x] **Stage 0** — deps + skeleton. `colpali-engine>=0.3` added; `src/stage1_fast/` created.
- [ ] **Stage 1** — `device.py` + `model.py`: detect CUDA/MPS/CPU, load ColQwen or ColSmol, cache singleton. Checkpoint: embed one PDF page, print vector shape.
- [ ] **Stage 2** — `src/stage2/fast_db.py`: create `fast_tier` Qdrant collection with `MaxSim` + int8 scalar quantization. Checkpoint: upsert one page, query roundtrip.
- [ ] **Stage 3** — `src/stage1_fast/index.py`: batch indexer. Renders PDF pages via pymupdf, routes by file type + page count, updates manifest with `fast_indexed_at`.
- [ ] **Stage 4** — wire into `src/pipeline.py::sync_files`. CLI flags `--fast-only` / `--summary-only`. Split progress bars.
- [ ] **Stage 5** — `src/stage2/search.py`: RRF merge across both collections.

## v1.1+ backlog

### Token pooling (decided: flag-gated, default off)

`colpali-engine` v0.3.15 ships `HierarchicalTokenPooler`. At `pool_factor=2`,
50% vector reduction with 100.6% recall retention (basically free).
At `pool_factor=3`, 66.7% reduction with 97.8-99% recall.

**Why it's a flag, not default:**

The pooling paper (Clavié et al. 2024) flags **FIQA (financial domain)
degrades noticeably faster** than other datasets under pooling. Our
CLAUDE.md core use case — "how much was the bank transaction on a specific
date" — is a FIQA-style fine-grained numeric lookup. Turning pooling on by
default risks a silent recall drop on exactly the queries we're built for.

**Rollout:**
1. v1.0 — `--pool-factor N` CLI flag, default 1 (off)
2. Build a small test set of bank-statement queries + expected answers
3. Measure recall at pool_factor=1/2/3 on the test set
4. If pool_factor=2 holds on financial queries, flip the default

### Lazy background summaries

For multi-page PDFs in fast tier, generate an LLM summary in the background
so summary-tier coverage fills in without blocking onboarding. Single-page
images skip summary forever (ColPali alone is sufficient).

### Model upgrades to track

- `nvidia/nemotron-colembed-vl-4b-v2` — currently #3 on ViDoRe V3, 4B params.
  Watch for a sub-3B version.
- `TomoroAI/tomoro-colqwen3-embed-4b` — ColQwen3 with 320-dim embeddings
  (smaller storage). Upgrade candidate if storage becomes a concern before
  pooling does.

### Token pooling ablation tooling

Before flipping pool_factor=2 on by default, ship a `ns --benchmark-pooling`
command that re-indexes a subset with different pool factors and reports
recall@10 against a saved test set. Lets us make the default flip data-driven.

### Hybrid routing by query type

Instead of always fanning out to both collections, classify the query:
- "show me the [visual thing]" → fast-tier only
- "summarize [X]" → summary-tier only
- default → both + RRF

Savings: skip half the query latency on unambiguous queries. Needs a small
classifier or heuristic; defer until we have query-log data.
