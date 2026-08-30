# Tier 1 — Direct embed

> **What this doc is.** End-to-end walkthrough of the simplest tier: T1.
> One real corpus file, traced from disk → router → tier worker →
> Qdrant → user query → cited answer. Read this when you want a concrete
> picture of what "T1" actually means in code.
>
> Companion to [IO - Tiers.md](IO%20-%20Tiers.md) (the overview of all
> five tiers). The deep engineering rationale lives in
> [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md).

---

## What T1 actually is

> **The file IS the content. Read its bytes, embed them, done.**

No LLM call. No PDF parsing. No image rendering. The content is already
text the embedding model can consume directly — markdown, code, configs,
small text files. Stage 2 reads the bytes verbatim and pushes one Qdrant
point per file.

The tradeoff: T1 is the cheapest, fastest path. But it only works for
files that are *already plain text under 100 KB*. Anything bigger goes
to T0 (preview-only); anything that needs parsing (PDF, DOCX, XLSX) goes
to T2/T3.

## Who lands in T1

| Extension | Routes to T1 if … |
|---|---|
| `.txt`, `.md`, `.markdown`, `.log` | size < 100 KB |
| `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.c`, `.cpp`, `.sh`, `.sql`, etc. | size < 500 KB |
| `.json`, `.yaml`, `.yml`, `.toml` | size < 50 KB |
| `.csv` | row count ≤ 1,000 |
| `.bashrc`, `.zshrc`, `.vimrc`, `.gitconfig`, `.tmux.conf`, etc. | size < 100 KB (useful dotfiles allowlist) |

Sources: [src/router.py:61-66](../src/router.py#L61-L66) for size thresholds,
[src/router.py:48-65](../src/router.py#L48-L65) for the dotfile allowlist.

## The flow

```
┌──────────────────────────────────────────────────────────────────┐
│  Walker discovers: Plans/backlog_20Apr26.md (23 KB markdown)     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  peek(): cheap inspection                                         │
│   • ext = ".md"                                                   │
│   • size_bytes = 23,169                                           │
│   • text_density (chars/file) = ~22,000 (since whole file is text)│
│   • extractable = True                                            │
│   Cost: <10 ms. No LLM, no parsing.                               │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  decide(): pure function                                          │
│   ext in TEXT_EXTS  ✓                                             │
│   size_bytes (23,169) < TEXT_SIZE_T0_THRESHOLD (100 * 1024) ✓     │
│   → routes = ["T1"]                                               │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  tier1.run(path, source_rel)                                      │
│   1. raw = path.read_text(encoding="utf-8")                       │
│   2. body = raw[:8_000].strip()    ← cap at DEFAULT_BODY_MAX_CHARS│
│   3. content_type = "markdown"                                    │
│   4. md = render_summary_markdown(...)                            │
│   5. write_summary(Test Summaries/<hash>_t1.md, md)               │
│   Cost: ~10 ms. No LLM, no embedding yet.                         │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Manifest update: mark_summarized(rel, size, summary_file_rel)    │
│   • size = 23169                                                  │
│   • summary_file = "Test Summaries/<hash>_t1.md"                  │
│   • ingested_at = None  (Qdrant push hasn't happened yet)         │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼ (every 100 files OR end-of-walk)
┌──────────────────────────────────────────────────────────────────┐
│  Stage 2 push: ingest_from_manifest()                             │
│   1. parse_summary_file(<hash>_t1.md) → ParsedSummary             │
│   2. embed_dense(body)   → 384-dim MiniLM vector                  │
│   3. embed_sparse(body)  → BM25 sparse vector                     │
│   4. upsert_summaries([point])                                    │
│      point.id      = md5("Plans/backlog_20Apr26.md")              │
│      point.vectors = {"dense": [...], "sparse": [...]}            │
│      point.payload = {"summary": body, "source_path": rel}        │
│   5. mark_ingested(rel) → ingested_at stamped                     │
└──────────────────────────────────────────────────────────────────┘
```

## End-to-end with a real file

Take `Plans/backlog_20Apr26.md` (23 KB, exists in your corpus right now).

### Step 1 — Walker discovers it

`just walk /mnt/hardisk/Magpie/` runs.
[walker.py:107 find_candidates()](../src/ingest/walker.py#L107) calls `root.rglob("*")`,
collects every file with a considered extension, applies ignore rules.
This file passes — `.md` is in `_CONSIDERED_EXTS`, no `.gitignore` rule
matches, not a hidden path.

### Step 2 — peek + decide

`peek()` runs at [src/router.py peek()](../src/router.py). For a `.md`
file it calls `_peek_text_file(path)` which reads up to 5 KB to compute
text_density and extracts a `peek_text` slice for sensitivity scoring.

```python
PeekResult(
    path=Path("Plans/backlog_20Apr26.md"),
    ext=".md",
    size_bytes=23169,
    page_count=0,            # not paginated
    text_density=22000,      # chars/file for plain-text
    extractable=True,
    image_ratio=0.0,
    row_count=None,
    image_dims=None,
    peek_text="# Backlog — 2026-04-20\n\n> Snapshot of everything we've...",
)
```

`decide()` walks its branch table:

```python
ext = ".md"
if ext in TEXT_EXTS:                               # ✓
    tier = "T0" if p.size_bytes >= TEXT_SIZE_T0_THRESHOLD else "T1"
    # 23169 < 102400 → tier = "T1"
    return RouteDecision(routes=["T1"], ...)
```

**Decision: T1.** Total cost so far: <10 ms. No LLM, no network.

### Step 3 — tier1.run

[tier1.py:26](../src/ingest/tier1.py#L26) executes:

```python
def run(path: Path, source_rel: str) -> TierOutcome:
    raw = path.read_text(encoding="utf-8")     # 23,169 chars
    body = raw[:8_000].strip()                 # cap at DEFAULT_BODY_MAX_CHARS
    # ... content_type detection ...
    md = render_summary_markdown(
        source_rel="Plans/backlog_20Apr26.md",
        title="backlog 20Apr26 (backlog_20Apr26.md)",
        body=body,
        content_type="markdown",
        keywords=["backlog_20Apr26.md", "markdown"],
        entities=[],
        identifiers=["backlog_20Apr26.md"],
    )
    out = summary_output_path(path, "t1")    # → Test Summaries/d732225775d7604c_t1.md
    write_summary(out, md)
    return TierOutcome(summary_file_rel="Test Summaries/d732225775d7604c_t1.md", body_chars=8000)
```

**Note the cap.** Even though the file is 23,169 chars, only the **first
8,000 chars** ([common.py:13](../src/ingest/common.py#L13) —
`DEFAULT_BODY_MAX_CHARS = 8_000`) get embedded. Same cap applies to all
T1 files. Anything past character 8,000 is effectively invisible to
search. For most well-organized files this is fine (the title, intro,
first chapter all fit); for a 23 KB scratch-pad with topics scattered
throughout, the back half won't be findable.

### Step 4 — The summary markdown on disk

`Test Summaries/d732225775d7604c_t1.md`:

```
Source: Plans/backlog_20Apr26.md

# backlog 20Apr26 (backlog_20Apr26.md)

# Backlog — 2026-04-20

> Snapshot of everything we've agreed to, designed, or flagged but not yet
> shipped. Grouped by theme, not priority — the "Next up" section at the end
> is the priority list.

## A. Ingest

### A1. Asset-library detection
Folder with ≥15 images and 0 documents → skip wholesale.
... (about 8 KB of body content) ...

**Content type:** markdown

**Keywords:** backlog_20Apr26.md, markdown

**Key entities:** —

**Identifiers:** backlog_20Apr26.md
```

This is the *exact* shape Stage 2's parser expects
([common.py:55](../src/ingest/common.py#L55)). The title carries the
filename so BM25 hits filename-like queries; the body carries the raw
text for dense embedding.

### Step 5 — Manifest update

[walker.py:243](../src/ingest/walker.py#L243):

```python
manifest.mark_summarized(
    rel="Plans/backlog_20Apr26.md",
    size=23169,
    summary_file_rel="Test Summaries/d732225775d7604c_t1.md",
)
```

Sets `ingested_at = None` — telling Stage 2 "this row needs to be pushed."

### Step 6 — Stage 2 push (every 100 files OR end-of-walk)

The chunk-flush mechanism (added 2026-04-27) calls `ingest_from_manifest`
between chunks. For our file:

1. **Parse** the markdown back into a `ParsedSummary` struct.
2. **Embed dense:** `embed_dense_query(body + " " + " ".join(keywords))` →
   384-dim float vector via `sentence-transformers/all-MiniLM-L6-v2`.
3. **Embed sparse:** `embed_sparse_query(body)` → sparse BM25 vector
   (term IDs + weights).
4. **Upsert:**

```python
PointStruct(
    id=_point_id("Plans/backlog_20Apr26.md"),         # md5-derived UUID
    vector={
        "dense":  [0.012, -0.041, ..., 0.083],         # 384 dims
        "sparse": SparseVector(indices=[12, 47, ...], values=[1.4, 0.9, ...]),
    },
    payload={
        "summary": "# backlog 20Apr26 ... (full body) ...",
        "source_path": "Plans/backlog_20Apr26.md",
    },
)
```

5. **Mark ingested:** `ingested_at = "2026-04-27T03:14:00Z"`. This file
   won't be re-pushed unless the manifest flag is cleared (e.g.
   `--force`) or the file size changes.

**Cost so far for this file: still ~50 ms total.** No LLM call.

## Step 7 — User asks a question

Query: *"What was on the backlog for fast-tier orphan cleanup?"*

[src/pipeline.py:45 ask()](../src/pipeline.py#L45):

1. `raw_query()` → `SearchQuery(query="What was on the backlog for fast-tier orphan cleanup?", keywords=[])`.
2. `run_search()` does hybrid retrieval at
   [src/stage2/search.py:261](../src/stage2/search.py#L261):
   - Dense: `embed_dense_query(...)` → 384-dim vector.
   - Sparse: BM25 keywords from the question text.
   - Qdrant `query_points()` with `FusionQuery(fusion="rrf")` returns top-5.
   - Our backlog file ranks high — its body contains the literal phrase
     "fast-tier orphan cleanup" so BM25 dominates; the `backlog` keyword
     in the title also helps the dense match.
3. `answer_question()` reads the actual file (not the summary —
   [answer.py:271](../src/answer.py#L271) builds content blocks from the
   raw file). Since this is T1, **`_is_t0(display)` returns False**, so
   the file is read whole, capped at `ANSWER_MAX_CHARS_PER_FILE`. The
   T1 summary is also prepended via `_summary_supplement` if available.
4. Kimi answers, citing `Plans/backlog_20Apr26.md`.

### What the user sees

```
Question: What was on the backlog for fast-tier orphan cleanup?

Retrieved (top-k from Qdrant):
  1. [0.812] Plans/backlog_20Apr26.md
  2. [0.346] src/ingest/walker.py
  ...

Answer:
  The backlog flagged fast-tier orphan cleanup as item A4: drop ColPali
  points whose source_path no longer exists in the manifest. The fix was
  to mirror the summary-collection orphan sweep into the fast tier so
  asset-library skips and `--rebuild` don't leave zombie multi-vectors
  on disk.

Sources used:
  - Plans/backlog_20Apr26.md
```

## What T1 is good at

- **Exact-token search.** BM25 over the raw body means an invoice
  number `X7QK2M` matches verbatim. An LLM-summarized version (T3) would
  paraphrase that away.
- **Code search.** Function names, error strings, log lines — all
  preserved verbatim. Your `def run_search(` signature is findable; a
  Kimi summary saying "the search runner function" wouldn't be.
- **Cheap.** No LLM calls means thousands of T1 files cost zero in API
  fees and complete in seconds.

## What T1 is weak at

- **The 8 KB body cap.** Files bigger than ~8 KB only get their first
  8,000 chars embedded. The rest is invisible to retrieval until the
  user asks about it specifically — at which point the answer step
  reads the full file from disk. This means *retrieval* may miss a
  back-half topic, but *answering* won't (once the file is found).
- **No semantic distillation.** T1 stores the file's bytes as-is. A
  100-line Python file with one critical line buried in the middle will
  match queries about boilerplate first, the critical line second. T3
  fixes this by having the LLM extract identifiers + keywords. T1
  doesn't try.
- **Filename only carries so far.** A file named `notes.md` containing
  recipes will match "notes" but not "recipes" until the body fits in
  the 8 KB cap.

## Differences from T2 / T3

| Property | **T1** | T2 | T3 |
|---|---|---|---|
| LLM call at ingest | ❌ none | ❌ none | ✅ Kimi summarize |
| File parsing | Read bytes | pypdf / openpyxl / etc. | LLM reads extracted text |
| Body in summary | First 8 KB raw | Extracted text (capped) | LLM-distilled summary |
| Identifiers field | filename only | filename only | LLM-pulled (invoice #s, names, dates) |
| Best for | Markdown, code, configs | Text-native PDFs / DOCX / XLSX | Receipts, contracts, scanned-short PDFs |
| Cost per file | ~50 ms | ~100 ms - 1 s | ~3-15 s + ~$0.001 LLM |

## When the router *upgrades* T1 to a higher tier

There's one path where a file that would normally be T1 gets bumped:
**criticality.** [src/router.py](../src/router.py) scans `peek_text`
for currency / legal / ID patterns. If a `.md` file contains text like
`$1,234.56` or `Invoice #2024-0812`, criticality is set to `critical`
and the routing changes from `["T1"]` to `["T3", "T1"]` — both tiers
run. The LLM summary surfaces the discriminator into `identifiers` so
exact-match retrieval hits.

This is rare for genuine T1 content (markdown notes, code) — the
heuristic is tuned for cases where someone saved a receipt or invoice
as a `.txt` file.

## Cross-references

- [src/ingest/tier1.py](../src/ingest/tier1.py) — the worker, ~65 lines
- [src/ingest/common.py](../src/ingest/common.py) — `render_summary_markdown`, `DEFAULT_BODY_MAX_CHARS = 8_000`
- [src/router.py:850-858](../src/router.py#L850-L858) — text-file decision branch
- [src/router.py:860-868](../src/router.py#L860-L868) — code-file decision branch
- [src/router.py:870-878](../src/router.py#L870-L878) — config-file decision branch
- [src/stage2/__main__.py ingest_from_manifest](../src/stage2/__main__.py) — Stage 2 push
- [src/stage2/parser.py](../src/stage2/parser.py) — markdown → `ParsedSummary`
- [src/stage2/embeddings.py](../src/stage2/embeddings.py) — dense + sparse encoders
- [IO - Tiers.md](IO%20-%20Tiers.md) — overview of all five tiers
- [IO - Stage 1.md](IO%20-%20Stage%201.md) — original (T3-only) summarization flow
- [IO - Stage 2.md](IO%20-%20Stage%202.md) — embed + Qdrant push
