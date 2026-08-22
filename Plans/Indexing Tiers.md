# Indexing Tiers — the router-driven ingest architecture

> **Status:** v0 source-of-truth for the router + tiering refactor. Supersedes
> the pre-router scattered logic in `src/content.py` and the parallel
> `src/stage1_fast/` lane. This document is intentionally opinionated — when
> we ship and benchmark, we'll revisit the choices below with real data in
> hand. Topics left for later: two-pass ingest (see "Future considerations"),
> transient T4 cleanup, `.alt` sidecar extension to non-video files.

## Why this exists

Today every file walks the same pipeline: a Kimi LLM call produces a
`FileSummary`, which is then embedded and upserted to Qdrant. This is
**uniform** but **wrong** for most file types — we pay an LLM call on files
that need none (code, markdown, text-native PDFs) and an identical call on
files where a visual-layout embedding would be strictly better (scanned PDFs,
images).

The fix is an **ingest router** that peeks each file cheaply and dispatches
it to one of five tiers. Most files never touch the LLM. Content that
genuinely needs structured LLM extraction (bank statements, contracts) still
gets it. Visual content gets ColPali's multi-vector layer instead. Every
decision is deterministic, logged, and auditable.

## The cost model we're actually optimizing

Previous instinct was to rank tiers by "output size." Wrong. Users wait on
**wall-clock time**, not bytes on disk. Storage is a one-time cost and is
mitigatable by quantization. Corrected model:

| Axis | Where it hurts | Dominant cost |
|---|---|---|
| Ingest wall-clock | ingest UX, rate limits | LLM calls (network + token latency) |
| Disk storage | long-term footprint | multi-vector embeddings (T4) |
| API $ | recurring | LLM calls (T3 when not on a local model) |
| Answer-time latency | query UX | ~tier-independent; Qdrant handles it |

**Implication:** the only genuinely *slow* tier is T3. Everything else
(T1/T2/T4-on-GPU/T0) runs in the seconds-per-many-files range. That shapes
the entire router policy.

## The five tiers

Each tier is a complete ingest path, not a partial step. The router chooses
one per file (sometimes two — see "Multi-tier per file").

### T0 — Register + on-demand ripgrep

**For:** files too large or too rowy to embed piece-by-piece
(huge CSVs >100k rows, log files >100 KB, giant JSON dumps, 500-MB textbooks).

**Ingest:** write a single file-level summary row (either one LLM
sample-summary call over the first ~100 rows/chars/lines, OR skip the LLM and
use filename + first 2 KB). One Qdrant point per file.

**Query behavior:** retrieval finds the summary. The answer step gets
`ripgrep_file(path, pattern)` as a tool and searches the raw file on demand
when the question needs specific rows/lines.

**Why this works:** large structured data (transaction logs, SEC filings,
logs) is better served by grep-at-answer-time than by embedding 10M rows that
all look semantically identical. Retrieval would drown.

### T1 — Direct embed

**For:** files whose bytes ARE the content — code, markdown, text, JSON,
YAML, TOML, small CSVs.

**Ingest:** read raw bytes → chunk (fixed-size windows with overlap, or
header-boundary for markdown) → encode with MiniLM + BM25 → upsert chunks.
No LLM call.

**Query behavior:** dense/sparse retrieval hits chunks directly. Answer step
reads the file.

**Why this works:** MiniLM was trained on code + prose; it encodes raw text
adequately. BM25 over raw text gets **exact** token matches (function names,
literal phrases) that an LLM paraphrase would have washed out.

### T2 — Extract-then-embed

**For:** text-native PDFs, DOCX, XLSX — content is text once we parse the
container.

**Ingest:** `pypdf` / `python-docx` / `openpyxl` extracts text → chunk →
encode with MiniLM + BM25 → upsert chunks. No LLM call.

**Query behavior:** same as T1.

**Why this works:** Same reasoning as T1 once we've peeled the container.

### T3 — LLM text summary

**For:** content where an LLM is actually adding structure the bytes don't
carry — receipts, bank statements, contracts, scanned short PDFs, critical
identifiers that retrieval needs to hit verbatim.

**Ingest:** current Stage 1 behavior — `FileSummary(title, summary, keywords,
key_entities, identifiers)` via Kimi (or local Ollama) → render as markdown
summary → upsert one dense+sparse point.

**Query behavior:** retrieval hits the summary (one point per file). Answer
step reads the source file.

**Why this works:** for discriminator-heavy content ("$170.45", "R2NDSL",
"Invoice #2024-0812"), the LLM reliably surfaces these into the `identifiers`
field so BM25 can match them verbatim. Raw text extraction alone often
fragments them across the document.

### T4 — ColPali multi-vector (visual)

**For:** scanned PDFs, standalone images, figure-heavy DOCX — anything where
the information is in the **layout** as much as in any text.

**Ingest:** run the existing `colpali-engine` pipeline from `src/stage1_fast/`
per page → emit ~700–1024 patch vectors of 128 dims each, **int8
quantization** applied at upsert → store in the `pages` multivector collection.
**Never pool patches.**

**Query behavior:** MaxSim late-interaction retrieval. Returns specific page
hits with visual-patch-level match scores.

**Why this works:** for a scanned receipt, MaxSim can match a query's
"signature" token to the exact patch that contains the signature. Text-only
retrieval would miss this entirely.

**Why int8 and never binary pooling:**
- Int8 quantization: ~4× storage reduction (200 KB/page vs 800 KB/page), <2%
  recall loss.
- Binary quantization with rescoring: ~32× reduction, used only if a user
  opts into a "tiny disk" mode. Default is int8.
- **Never mean-pool or attention-pool patches — by default.** The value of
  ColPali is that the signal lives in specific patches (the cell with the
  total, the corner with the signature). Pooling averages discriminators
  into noise — the exact failure mode we're avoiding on financial docs.

> **Carve-out (shipped 2026-04-21):** `.pptx` files route through T4 with
> `pool_factor=2` (HierarchicalTokenPooler — ~50% storage reduction at
> ~100% recall retention per Clavié et al. 2024). Everything else still
> routes with `pool_factor=1` — no pooling. Educational slide decks tolerate
> pooling because the signal is slide-level semantic ("which slide explains
> X"), not patch-level discriminator. The whitelist lives at
> [src/ingest/tier4.py:POOL_SAFE_EXTS](../src/ingest/tier4.py); expanding
> it is gated on a real-data recall benchmark (see [backlog G4](backlog_20Apr26.md)).

## The router — how a file gets to its tier

The router is deterministic: peek each file, compute three scores, apply a
decision table, record the outcome. No ML, no heuristics beyond these
scores.

### Peek signals (computed once per file)

1. **`size`** — `stat().st_size`. Free.
2. **`text_density`** — for PDF/DOCX: three-point sample (first, middle, last
   page/paragraph) → `chars_per_page` after extraction. Why three-point: book
   TOC is sparse, body is dense — first-page-only misleads.
3. **`extractable`** — did extraction return real-word tokens (non-UTF-8 ratio
   low, word-like structure present)? Boolean.
4. **`row_count`** — CSVs only, streamed.
5. **`image_ratio`** — DOCX only, `#images / #paragraphs`.

### Derived scores

**`visual_score` (0–10)** — how much does this file need the visual lane?

| Signal | Points |
|---|---|
| `text_density < 50 chars/page` | +5 |
| `text_density 50–500 chars/page` | +2 |
| `extractable == false` | +3 |
| DOCX `image_ratio > 0.3` | +2 |
| File is pure image (PNG/JPG/webp/gif), non-thumbnail | +4 |
| Page aspect ratio suggests form/receipt (< 0.65 or > 1.6) | +1 |

**`sensitivity_score` (0–10)** — does inaccuracy here hurt?

Computed on peeked text. **Filenames are never used.** (Users name files
`scan_001.pdf`; filename regex is noise.)

| Signal | Points |
|---|---|
| Currency pattern `[\$€£¥]\s?\d+[.,]\d{2}`, ≥3 occurrences | +2 |
| Totals vocabulary (`total`, `subtotal`, `balance`, `amount due`) ≥2 | +2 |
| Masked account number (`****1234`) | +3 |
| Date+amount table pattern, ≥3 rows | +3 |
| Legal/contract tokens (`hereby`, `witnesseth`, `effective date`) | +2 |
| ID tokens (`passport`, `license no`, `SSN`, `EIN`, `tax id`) | +3 |

Sum ≥ 4 → **sensitivity = critical**. Conservative threshold; false positives
cost one LLM call, false negatives cost a missed bank-statement match.

When text isn't extractable (scanned, pure image), `sensitivity_score` is
undefined → treat as critical by default. We never assume "scanned =
casual."

**`t4_cost_estimate`** — storage (MB) + wall-clock (s) for T4 on this file.

```
storage_mb  = pages × 0.2                   # ~200 KB/page int8
time_s_gpu  = pages × 1.0
time_s_cpu  = pages × 10.0
```

### Decision table (one tier chosen per file, occasionally two)

| Ext + peek | visual_score | sensitivity | Route |
|---|---|---|---|
| Text file (`.txt .md .json .yaml .toml`), size <100 KB | — | — | **T1** |
| Text file, size ≥100 KB | — | — | **T0** |
| Code file, size <500 KB | — | — | **T1** |
| Code file, size ≥500 KB | — | — | **T0** |
| CSV, <1k rows | — | — | **T1** (row-level embed) |
| CSV, 1k–100k rows | — | — | **T2** (sample summary + row BM25 entries) |
| CSV, >100k rows | — | — | **T0** (sample summary only) |
| PDF / DOCX / XLSX, text-native | <3 | <5 | **T2** |
| PDF / DOCX / XLSX, text-native | <3 | ≥5 | **T3 + T2** (additive) |
| PDF / DOCX, text-native | 3–6 | <5 | **T2** |
| PDF / DOCX, text-native | 3–6 | ≥5 | **T3 + T2** |
| PDF / DOCX, text-native, short (≤5 pages) | any | any | **T3** (short = typically discriminator-heavy) |
| PDF / DOCX, scanned or figure-heavy | ≥7 | <5, GPU | **T4** |
| PDF / DOCX, scanned or figure-heavy | ≥7 | ≥5, GPU | **T3 + T4** |
| PDF / DOCX, scanned | ≥7, no GPU | any | **T3** (T4 too slow on CPU) |
| Image PNG/JPG/webp/gif, normal | ≥7 | <5, GPU | **T4** |
| Image, normal | ≥7 | ≥5 | **T3 + T4** (on GPU) or **T3** (no GPU) |
| Image thumbnail (<50 KB or <200×200 px) | — | — | **skip** |

### Hard gates (non-negotiable)

Applied *after* the decision table. Any gate failure demotes T4 → T3 (or
T4 → skip if T3 also infeasible).

1. **Per-file T4 cap:** `t4_cost_estimate.storage_mb ≤ 50 MB` AND
   `t4_cost_estimate.time_s ≤ 30 s` (GPU) or `≤ 10 s` (CPU). Kills
   400-page textbook-to-ColPali before it starts.
2. **Corpus T4 budget:** running total of T4 storage ≤ **5 GB** by default.
   Raisable in `.nasrc`. Once hit, T4 stops for new files; router logs
   `skip_reason: "budget_exhausted"`.
3. **GPU detection:** on startup, check for CUDA / MPS. If absent, per-file
   T4 time cap drops to 10 s AND T4 is demoted to T3 for non-critical files.
4. **Criticality never downgrades.** `.nasconfig.yaml` can upgrade a folder
   to "critical" (forces T3 on everything in it), but cannot suppress T3 on
   content that triggers sensitivity detectors. Auto-criticality always
   wins.

### What the router does NOT do

- It doesn't use filename regex for criticality (filenames are noise).
- It doesn't ML-classify files (non-deterministic, hard to debug).
- It doesn't run any LLM call during peeking.
- It doesn't look at user history or query logs.

All signals are one-shot, deterministic, cheap, auditable.

## One-pass ingest

Every file walks exactly **one** route to completion. No "fast first pass
then re-do later." No throwaway state. No quality fluctuation as background
work lands.

```
[walker] → [router.peek(path)] → [router.decide()] → [one of T0..T4]
                                        ↓
                                  possibly additive T3
                                        ↓
                                  [manifest.mark_indexed]
                                        ↓
                                  [qdrant.upsert()]
```

**Only T3 is slow.** Since the router routes most files away from T3 (only
sensitive files get it), the primary ingest time on a typical 10k-file
corpus collapses from ~3 hours to ~30–40 minutes even with T3 inline:

- 6,000 text/code files → T1 → ~5 min
- 2,500 text-native PDFs → T2 → ~15 min
- 500 scanned/image PDFs → T4 on GPU → ~10 min
- 200 sensitivity-triggered → T3 → ~15 min
- Parallel where possible → total wall-clock ~30–40 min

Contrast with today: 10k × 3s LLM each = 8+ hours serial, ~2.5 hours at
concurrency=3. Even a naive one-pass router shrinks that by ~4–6×.

### Why not two-pass

A two-pass model ("quick raw-chunk embed NOW, correct tier LATER") would
only buy us the "instant search" feel if the correct tiers were all slow.
They're not — T1, T2, T4-on-GPU are fast. The do-over cost (processing every
file twice, writing then deleting Pass-1 artifacts, managing a state
machine) outweighs the minute-1 "ready" illusion. One-pass is simpler,
produces stable quality at done-time, and is predictable to debug.

**When we'd reconsider:** if benchmarking shows that T3-heavy corpora (a
small-business customer whose sensitive-file detection fires on >50% of
files) regularly take >2 hours, a targeted two-pass where T3 runs in the
background while T1/T2/T4 stream into the index might be worth the
complexity. We'll know after we measure. See "Future considerations."

## Multi-tier per file

A file can live in **two tiers simultaneously** — most commonly `T3 + T2`
(discriminators + chunks) or `T3 + T4` (discriminators + visual layout).
Each tier produces its own Qdrant points in its own collection. At query
time, all collections are searched; results fused via RRF alongside the
existing dense/sparse fusion.

**Rules:**

- T3 is additive — it never replaces T2 or T4 points.
- T2 and T4 are mutually exclusive (a file is either text-native or visual,
  not both, as far as the primary tier is concerned).
- T1 and T4 are mutually exclusive (code isn't visual).
- T0 stands alone (huge files don't get multi-tier treatment).

## Qdrant collection layout

Three collections, one per retrieval "shape":

| Collection | Vectors | Contents | Routes that write here |
|---|---|---|---|
| `summaries` | 1 dense (384-d) + 1 sparse (BM25) per file | file-level summary points (T0, T1, T2, T3) | T0, T1, T2, T3 |
| `fast_tier` | multi-vector (128-d × ~700–1024 patches), int8 | per-page visual embeddings | T4 |

> **v1 simplification:** T1/T2 currently write a single file-level summary
> point into `summaries` (body = raw or extracted text, capped at ~8 KB).
> A dedicated `chunks` collection with per-chunk points is deferred; BM25
> over the full body already gets us most of the exact-token retrieval
> benefit for a fraction of the implementation cost.

All three are queried in parallel and fused at the search layer. Point IDs
remain deterministic functions of manifest keys (as today in
`src/stage2/db.py:_point_id`), so orphan cleanup continues to work
identically per-collection.

## Ripgrep as a query-time tool

T0 files and large T2 files aren't exhaustively embedded. For detail
lookups, the answer step gets a new agent tool:

```python
def ripgrep_file(path: str, pattern: str, max_hits: int = 20) -> list[Hit]:
    """Run ripgrep on `path` with `pattern` and return matching lines."""
```

The Stage 4 answer agent decides when to call it: if retrieval hands it a
huge CSV and the question asks "how much on May 4?", the agent ripgreps the
CSV for `05/04` and feeds matching rows to the LLM. Complements — doesn't
replace — semantic retrieval.

## User overrides

A `.nasconfig.yaml` at any folder level is read on ingest and applies
recursively. Only two knobs:

```yaml
# .nasconfig.yaml
accuracy: critical      # forces T3 on everything in this folder.
                        # Can also be "casual" (does nothing — can't downgrade).
t4_budget_gb_override: 20  # raise the corpus T4 storage cap (default 5 GB)
```

User config can **upgrade** criticality but never downgrade. Sensitive
content always gets T3 regardless of folder config.

## Manifest schema changes

New fields on `Entry` in `src/manifest.py`:

```python
@dataclass
class Entry:
    size: int
    summary_file: str | None = None
    summarized_at: str = ""
    ingested_at: str | None = None
    row_count: int | None = None

    # NEW — router audit trail
    routes: list[str] = field(default_factory=list)       # ["T3", "T2"]
    visual_score: int = 0
    sensitivity_score: int = 0
    t4_cost_mb: float = 0.0
    t4_cost_s: float = 0.0
    criticality_source: str = "default"                   # "user" | "auto" | "default"
    skip_reason: str | None = None                        # "budget_exhausted" etc.
```

`ns why <file>` (future CLI command) can surface this record for debugging:
"why did this bank statement skip T4?" → see `skip_reason: "budget_exhausted"`
→ raise the cap or free space.

## Implementation order

Ordered so each step is individually testable and shippable:

1. **`src/router.py`** — pure functions for peek + score + decide. Unit
   tests with fixtures for scanned PDF, text PDF, huge CSV, figure-heavy
   DOCX, pure image. No side effects yet.
2. **`src/manifest.py`** — extend `Entry` with the new fields. Migration:
   default values for existing rows on load.
3. **`src/ingest/`** (new package) — per-tier workers: `tier0.py`,
   `tier1.py`, `tier2.py`, `tier3.py` (= current Stage 1 summarize),
   `tier4.py` (= current `stage1_fast`). Each exports a single
   `run(path, entry) -> Result`.
4. **Walker + dispatch** — replace `src/stage1/summarize.py:run_batch` with
   a router-first walker that calls `router.decide(path)` then the
   appropriate tier worker.
5. **CSV routing** — convert `src/stage1/summarize.py`'s CSV branch into
   T0/T1/T2 per row-count bracket; retire the unconditional
   `upsert_csv_rows` path.
6. **Ripgrep tool** — add `ripgrep_file` as a tool on the Stage 4 answer
   agent; wire it for T0 and large-T2 retrieval results.
7. **Qdrant `pages` collection** — separate collection for T4, wired into
   query-side fusion in `src/stage2/search.py`.
8. **`.nasconfig.yaml` parsing** — folder-level overrides applied in router.
9. **`ns why <file>` CLI** — read manifest row, print the audit record.

Steps 1–4 are the MVP that delivers the new architecture. 5–6 are the
first quality wins on realistic corpora. 7–9 polish it into a product.

## What is NOT in this plan (parked)

- **Video / audio / `.alt` sidecars** — lives in `Plans/Stage 3 - Videos.md`.
  Not touched in this refactor.
- **Two-pass ingest** — revisit only after benchmarking shows one-pass's
  T3-heavy case hurts.
- **Transient T4 retirement** (delete T4 points once T3 exists for
  low-visual-score files) — orthogonal storage optimization, add later.
- **Agentic retrieval loop** — tracked in `Plans/Future Plans.md` #3.
- **Cross-encoder reranker** — `Plans/Future Plans.md` #6. Layers on top of
  the fused tier results.
- **HyDE** — `Plans/Future Plans.md` #2. Query-side, independent of ingest
  tiering.
- **Filesystem watcher** — UX concern, not a tier concern. Tracked in the
  master todo.

## Future considerations (revisit after first benchmark)

- **Two-pass ingest** if T3-heavy corpora dominate our real-world usage.
- **Transient T4 retirement** if corpus T4 storage budget proves too tight.
- **Per-query tier weighting** (currently static RRF) if some query classes
  consistently prefer one tier over another.
- **Local T3 via Ollama** (already in `Plans/Port.md`) — would make T3
  approximately as fast as T4-on-GPU, changing the cost calculus.
- **Adaptive budget** — grow/shrink T4 corpus cap based on actual disk free
  space instead of a hard number.

## Success criteria for the router refactor

Before we call this done, all of:

1. Ingest time on a 10k mixed corpus drops to ≤45 minutes wall-clock with
   a GPU, ≤90 minutes without.
2. `tests/retrieval_eval.py` recall@5 does NOT regress on existing queries
   (measured before and after).
3. Storage for a 10k corpus stays under 1 GB total (summaries + chunks +
   pages with int8 T4) without the budget cap kicking in.
4. `ns why <file>` surfaces a complete audit record for every ingested
   file.
5. Router unit tests cover: scanned PDF, text PDF (short / long), image
   thumbnail (skipped), huge CSV, figure-heavy DOCX, pure image, sensitive
   bank-statement PDF, non-sensitive code file. All pass.
