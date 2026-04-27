# Tiers — the five lanes every file gets sorted into

> **What this doc is.** A plain-language map of the tiering system the
> router uses to decide *how* a file gets indexed. The deep engineering
> rationale lives in [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md);
> this doc is the developer-facing companion that walks one real file
> through the whole pipeline so the moving parts click together.
>
> Read this when: you're touching the router, debugging why a file landed
> in an unexpected tier, or trying to understand what "T0 + ripgrep" means
> in [src/answer.py:257](../src/answer.py#L257).

---

## Why tiers exist

Earlier versions of the system ran every file through one path: parse it,
ask Kimi for a summary, embed the summary, store it. **Same treatment for
a 2 KB markdown file as a 200 MB bank-statement CSV.** That's wasteful for
small files (no LLM needed), prohibitive for huge files (millions of LLM
tokens), and wrong for visual content (scanned PDFs lose all their layout
signal once you flatten them to text).

The router's job is to look at each file cheaply (a "peek") and dispatch
it to the cheapest path that will still produce a high-quality embedding.
**Most files never touch the LLM.** Only files where the LLM adds real
discriminator value (`bank statement`, `contract identifiers`,
`receipt totals`) pay that cost.

---

## The five tiers at a glance

| Tier | One-line description | LLM call? | Example file |
|---|---|---|---|
| **T0** | Too big to embed — register stub, ripgrep at answer time | No | 50 MB transactions.csv (300k rows) |
| **T1** | Small / native text — embed directly | No | A 5 KB README.md |
| **T2** | Container text — extract then embed | No | A 1 MB text-native PDF |
| **T3** | LLM-summarize discriminator-heavy content | **Yes** | A short receipt PDF, contract |
| **T4** | Visual — ColPali patch-level multi-vectors | No (uses GPU model) | A scanned 30-page PDF |

T3 is the only path that hits the network for an LLM call at ingest. The
others are local CPU/GPU work plus an embedding model call (also local for
the dense + sparse stack we use).

---

## How the router picks (the decision flow)

```
┌────────────────────────────────────────────────────────────────┐
│  walker discovers file: /path/to/something.ext                  │
└────────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  peek(): cheap inspection                                        │
│   • size_bytes                                                   │
│   • page_count, text_density, extractable (PDF / DOCX)           │
│   • image_ratio (DOCX layout signal)                             │
│   • row_count (CSV)                                              │
│   • image_dims (images)                                          │
│   • peek_text — first ~5 KB for sensitivity scoring              │
│  Cost: 10–50 ms per file. Never opens the LLM.                   │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  decide(): pure function of (peek, nasconfig, gpu, budget)       │
│  Branches by extension, then size / page-count / row-count       │
│  thresholds. Outputs a RouteDecision with .routes = ["T2"]       │
│  (or ["T3", "T4"] for criticality-bumped files).                 │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  tier worker runs: src/ingest/tier{0,1,2,3,4}.py                 │
│  Reads file → produces summary markdown OR ColPali multi-vectors │
│  Manifest is updated with tier + summary path + size + mtime     │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Stage 2 push: embeds the summary (or registers ColPali points)  │
│  into Qdrant. File is now searchable.                            │
└─────────────────────────────────────────────────────────────────┘
```

The router source is [src/router.py](../src/router.py); thresholds at lines 61-85.

---

## End-to-end example: a real corpus file

Walk through what happens to:

```
Test Content/syncdin_orgs/interfraternity-council/documents/2024/
  constitution_constitutionbylaws_2024.pdf      (1.7 MB)
```

### Step 1 — Walker discovers it

`python -m src.ingest "Test Content/"` recursively scans, hits this file.
`peek()` runs ([src/router.py peek()](../src/router.py)):

```
PeekResult(
    ext           = ".pdf",
    size_bytes    = 1_754_112,
    page_count    = 47,
    text_density  = 1840,    # chars per sampled page — clearly text-native
    extractable   = True,
    image_ratio   = 0.05,    # very few inline images
    row_count     = None,
    image_dims    = None,
    peek_text     = "ARTICLE I — NAME...",
)
```

Cost so far: ~30 ms.

### Step 2 — Router decides

Router walks through its decision branches:

```python
ext = ".pdf"
if ext in PDF_EXTS:                               # ✓
    if p.page_count == 0: skip                    # not zero, 47 pages
    if p.page_count <= 5: route to T3             # not short, 47 > 5
    if vs < 7 and extractable and density >= 100: # YES — text-native PDF
        if criticality == "critical": ["T3", "T2"]
        else:                          ["T2"]     # ← lands here
```

**Decision: T2** (text-native, non-critical PDF). No LLM call needed.
[src/router.py:917](../src/router.py#L917).

### Step 3 — T2 worker runs

`tier2.run()` extracts text via `pypdf` and `pymupdf`:

```
Extracted body (truncated):
"ARTICLE I — NAME
The name of this organization shall be the Interfraternity Council...
ARTICLE II — PURPOSE
The IFC exists to promote scholarship, leadership, brotherhood..."
... (47 pages of text) ...
```

Renders a summary markdown to
`Test Summaries/<hash>_t2.md` containing the title, the extracted body
(or a chunked subset), keywords, and identifiers. Manifest entry written
with `routes=["T2"]`, summary path, size, mtime.

### Step 4 — Stage 2 push

The walker auto-pushes (`autopush` feature) — the T2 summary markdown is
loaded, dense+sparse embeddings generated, one Qdrant point upserted into
the `summaries` collection. Filename / path tokens are part of the embedded
text, so `interfraternity-council`, `constitution`, `2024` all become
findable.

### Step 5 — User asks a question

Query: *"What does the IFC constitution say about chapter recognition?"*

Pipeline ([src/pipeline.py:45](../src/pipeline.py#L45)):

1. `raw_query()` builds a SearchQuery (no rewrite by default).
2. `run_search()` hybrid-searches Qdrant: dense + BM25 fused via RRF.
   Returns the constitution PDF in the top-k because its embedded summary
   mentions "chapter," "recognition," "IFC," etc.
3. `answer_question()` builds content blocks: `_is_t0(display)` returns
   **False** (it's T2, not T0), so the file is read in full via
   `build_content_blocks()`. The T2 summary is prepended as supplementary
   context.
4. Kimi receives the question + summary + raw PDF text, writes an answer
   citing the file.

**No ripgrep involved. T2 files are read whole at answer time.**

### Step 6 — What the user sees

```
Question: What does the IFC constitution say about chapter recognition?

Retrieved (top-k from Qdrant):
  1. [0.847] Test Content/syncdin_orgs/interfraternity-council/.../
              constitution_constitutionbylaws_2024.pdf

Answer:
  The IFC constitution requires fraternities seeking recognition to ...
  [grounded answer with quote]

Sources used:
  - constitution_constitutionbylaws_2024.pdf
```

---

## What WOULD have happened in other tiers

Same file, same question, different routing — to make the tiers concrete:

### If it had been **T0** (e.g., a 200 MB version of the same content)

- **Ingest:** No LLM, no full extraction. tier0 reads the first 2 KB
  ("ARTICLE I — NAME, The name of this organization...") and writes that
  plus the filename + size as the summary stub. One Qdrant point.
- **Search:** Embedding is dominated by the first 2 KB + filename. Question
  about "chapter recognition" might still hit because of filename tokens
  (`constitution`, `interfraternity`), but if the user asked about a topic
  in the *back half* of the document (e.g. "judicial procedure"), retrieval
  could miss entirely.
- **Answer:** If Qdrant returns the file, `_is_t0()` is True → ripgrep
  shells out on this one file with question tokens → returns up to 30
  matching lines → those go to Kimi. The full file is never sent to Kimi.

### If it had been **T3** (e.g., short PDF or `criticality=critical`)

- **Ingest:** Kimi reads the extracted text, writes a structured
  `FileSummary(title, summary, keywords, key_entities, identifiers)` —
  one LLM call, ~$0.001. Summary markdown stored.
- **Search:** Same hybrid retrieval, but the embedding is over the LLM's
  distilled summary rather than the raw bytes. Better discriminator
  recall (article numbers, signatory names get pushed into `identifiers`).
- **Answer:** Same as T2 — `_is_t0()` is False, full file is read.

### If it had been **T4** (e.g., scanned image-heavy PDF)

- **Ingest:** No text extraction. Each page is rendered to a 150-DPI image,
  encoded by ColPali / ColSmolVLM into ~1024 patch vectors of 128 dims each.
  Stored as a multi-vector point per page in the `fast_tier` Qdrant
  collection (separate from `summaries`).
- **Search:** A different retrieval lane — MaxSim late-interaction.
  Returns specific *pages* not whole files.
- **Answer:** The hit page is rendered and sent to Kimi (vision-capable
  model required) along with the question.

---

## The thresholds (and why they're set there)

[src/router.py:61-85](../src/router.py#L61):

| Constant | Value | Why this number |
|---|---|---|
| `TEXT_SIZE_T0_THRESHOLD` | 100 KB | Above this, plain text is usually a log/dump where embedding every chunk drowns retrieval |
| `CODE_SIZE_T0_THRESHOLD` | 500 KB | Source files almost never hit this; if they do (generated code, minified bundles) embedding adds no value |
| `CONFIG_SIZE_T0_THRESHOLD` | 50 KB | Configs over 50 KB are usually data dumps mislabeled as `.json`/`.yaml` |
| `CSV_ROWS_T1_MAX` | 1,000 | Below 1k rows, every row can be its own embedded chunk and search still works |
| `CSV_ROWS_T2_MAX` | 100,000 | 1k–100k: sample-based summary works; the LLM sees enough rows to characterize the file |
| `PDF_SHORT_PAGE_THRESHOLD` | 5 pages | Short PDFs are usually receipts/contracts/invoices — discriminator-heavy → T3 |
| `T4_MAX_STORAGE_MB_PER_FILE` | 50 MB | One ColPali file shouldn't dominate the corpus index |
| `T4_MAX_SECONDS_PER_FILE_GPU` | 30 s | Beyond this, the file probably wants T3 instead |
| `DEFAULT_T4_BUDGET_MB` | 5 GB | Corpus-wide cap; T4 is the storage-heavy tier and needs back-pressure |
| `T0_PREVIEW_BYTES` ([tier0.py:31](../src/ingest/tier0.py#L31)) | 2 KB | Enough for a CSV header + filename + first rows; small enough to avoid bloating Qdrant |
| `T0_CSV_PREVIEW_ROWS` | 100 rows | Header + 100 rows is enough to characterize most CSVs without reading the full file |
| `RIPGREP_DEFAULT_MAX_HITS` ([ripgrep.py:25](../src/ingest/ripgrep.py#L25)) | 30 lines | LLM context budget — 30 lines is enough to answer most questions about a T0 file |
| `subprocess timeout` ([ripgrep.py:79](../src/ingest/ripgrep.py#L79)) | 15 s | Cap on a stuck rg call; normal rg finishes in ms even on huge files |

---

## Where ripgrep fits — once and only once

Ripgrep runs in **exactly one place**: [answer.py:257-270](../src/answer.py#L257-L270),
inside an `if _is_t0(display):` branch. For every other tier, the file is
read in full at answer time.

This is the asymmetry: **T0 is the only tier where Qdrant has a stub but
not the file's content,** so ripgrep is the runtime mechanism that fills
the gap when a question lands on a T0 file. T1–T4 store enough at ingest
that no runtime grep is needed.

---

## Known weakness: T0 retrievability

The T0 design has one honest gap. The 2 KB / 100-row preview is what
gets embedded into Qdrant — and for **time-series files with generic
filenames** (e.g. `data.csv` containing 5 years of bank transactions),
that preview is unrepresentative of the file's full topic surface.

Consequence: a user asking "how much did I spend at Trader Joe's in 2024?"
might fail to retrieve `bank_export.csv` if Trader Joe's only appears in
the back 95% of the file that was never sampled. Ripgrep can't help — it
only fires *after* retrieval, and retrieval already missed.

**The fix is at ingest, not at query time.** Two options on the table:

1. **Sample throughout the file** at ingest — first 1 KB + middle 1 KB +
   last 1 KB + 30 random spots. Cheap, no LLM cost.
2. **Run one cheap LLM summary even for T0 files** — sample 100 rows
   from start/middle/end, ask the LLM for a 200-word summary, embed that.
   Stronger, costs one tiny LLM call per huge file at ingest.

Today neither is implemented. The corpus has no T0 files yet, so this is
deferred (see [Plans/backlog](../Plans/backlog_20Apr26.md)). When the first
real T0 file lands and we see retrieval fail, that's the trigger to ship
fix #2.

---

## What the system "thought of" (and what it didn't)

Designed-for cases:

- **Small text/code/markdown** → T1, no LLM, fast.
- **Mid-sized PDFs / DOCX / XLSX** → T2 if text-native, T3 if scanned/short, T4 if visual-heavy.
- **Receipts and short discriminator-heavy PDFs** → T3 forced (regardless of `visual_score`) so identifiers like invoice numbers and totals get surfaced verbatim.
- **Critical files** → routed to *both* T3 and the visual/text tier (`["T3", "T2"]`), so retrieval has both the LLM-distilled keywords and the raw text.
- **PowerPoints** → T4 with `pool_factor=2` (whitelisted in `tier4.POOL_SAFE_EXTS`) — slide-level signal tolerates pooling; everything else gets `pool_factor=1`.
- **Asset libraries** (folders ≥15 images, 0 docs) → images skipped wholesale via `siblingdensity` rule.
- **Thumbnails** (small bytes + small dims) → skipped via thumbnail filter.
- **GPU available?** → router picks ColPali model + batch size accordingly via `gpudetect`.
- **T4 budget exceeded?** → falls back to T3 with a `notes` audit line so the budget exhaustion is visible.
- **Sensitive content** (currency / legal / ID patterns in `peek_text`) → criticality auto-bumps to `critical`, which forces T3 even for files that would have been T2.

Known gaps:

- **T0 retrievability** for generic-filename time-series files (described above).
- **XLSX row count** isn't computed at peek time — only file size — so the threshold is a coarse `>10 MB → T0`. Refining to row-count would let medium XLSX go to T2.
- **No per-tier benchmarks yet** — the thresholds (100 KB, 1k rows, etc.) are reasoned defaults, not data-driven. Real corpora will likely re-tune them.
- **No re-routing on failure.** If T2 extraction silently produces gibberish (some edge-case PDFs), the file is embedded with bad text. There's no automatic fallback to T3 / T4.

---

## Cross-references

- [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md) — engineering source of truth
- [src/router.py](../src/router.py) — `peek()` + `decide()` implementation
- [src/ingest/tier0.py](../src/ingest/tier0.py) — register-only path
- [src/ingest/tier1.py](../src/ingest/tier1.py) — direct embed path
- [src/ingest/tier2.py](../src/ingest/tier2.py) — extract-then-embed path
- [src/ingest/tier3.py](../src/ingest/tier3.py) — LLM summary path
- [src/ingest/tier4.py](../src/ingest/tier4.py) — ColPali visual path
- [src/ingest/ripgrep.py](../src/ingest/ripgrep.py) — answer-time T0 line lookup
- [src/answer.py:257](../src/answer.py#L257) — the one place ripgrep is invoked
- [IO - Stage 1.md](IO%20-%20Stage%201.md) — summary generation flow (T2/T3 internals)
- [IO - Colpali.md](IO%20-%20Colpali.md) — T4 internals
- [IO - Stage 2.md](IO%20-%20Stage%202.md) — embedding + Qdrant push
