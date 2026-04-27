# Tier 3 — LLM-distilled summary

> **What this doc is.** End-to-end walkthrough of the only ingest tier
> that hits a remote LLM: T3. One real corpus file, traced from disk →
> router → Kimi → Qdrant → user query → cited answer. Read this when
> you want a concrete picture of what "T3" actually means in code, why
> it's gated behind criticality / page-count rules, and what it
> actually costs in time + dollars.
>
> Companion to [IO - Tiers.md](IO%20-%20Tiers.md) (the overview of all
> five tiers), [IO - Tier 1.md](IO%20-%20Tier%201.md) (direct embed),
> and [IO - Tier 2.md](IO%20-%20Tier%202.md) (extract-then-embed). The
> deep engineering rationale lives in
> [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md).

---

## What T3 actually is

> **The bytes ARE text-extractable, but the text is full of look-alike
> noise. Send it to an LLM, get back structured discriminators, embed
> THAT.**

T3 is the path for files where the raw text is misleading to BM25 and
muddy to dense embedding — receipts, contracts, scanned-short PDFs,
bank statements. The actual content of a receipt is overwhelmingly
boilerplate ("Thank you for shopping with us", "Subtotal", "Tax",
"Total"); the *discriminators* (vendor name, date, transaction ID,
total amount) are a few dozen tokens buried in that boilerplate. Pure
T2 embedding would weight the boilerplate evenly with the useful bits.

T3 sends the file to **Moonshot Kimi** (or the configured provider)
with a tightly-prompted schema. The LLM returns a structured
`FileSummary` — `title`, `summary`, `keywords`, `key_entities`,
`identifiers` — where the discriminators are *promoted into their own
field*. The `identifiers` field becomes the BM25 gold for exact-match
retrieval ("invoice 2024-0812", "$247.50", "DL1492").

The tradeoff: T3 is **the only tier with a network round-trip and a
dollar cost per file**. ~3-15 seconds wall-clock per file, ~$0.001
per file at Kimi pricing. For a 10k-file corpus where every file went
T3, that's **~$10 and 5+ hours**. The router's whole job is to keep
T3 small — most files never need it.

## Who lands in T3

| Trigger | Routes | Source |
|---|---|---|
| Short PDF (`page_count ≤ 5`) — receipts, invoices, contracts | `["T3"]` | [router.py:955-962](../src/router.py#L955-L962) |
| Visual PDF, T4 disabled or gated off (per-file or budget) | `["T3"]` | [router.py:1009-1017](../src/router.py#L1009-L1017) |
| Image with ColPali disabled by config | `["T3"]` | [router.py:1156-1163](../src/router.py#L1156-L1163) |
| Image, T4 gated off (no GPU + over CPU budget) | `["T3"]` | router.py — image branch |
| DOCX / XLSX / PPTX / HTML / IPYNB / mid-CSV with `criticality == "critical"` | `["T3", "T2"]` (both run) | router.py — each ext branch |
| Text-native PDF + critical | `["T3", "T2"]` | [router.py:967-969](../src/router.py#L967-L969) |
| Image-heavy PPTX + critical | `["T3", "T2", "T4"]` | router.py — pptx branch |

**Criticality is determined cheaply**: [router.py compute_sensitivity](../src/router.py)
scans the first ~5 KB `peek_text` for currency patterns (`$1,234.56`,
`USD 247.50`), legal patterns (`Article`, `hereinafter`, `pursuant`),
and ID patterns (`Invoice #`, `Order #`, IBAN/SSN-shaped tokens). If
the score crosses the threshold OR the file lives under a folder
flagged in `nasconfig.criticality_paths`, criticality flips to
`"critical"` and T3 is added to whatever tier the content would
normally route to.

## The flow

```
┌──────────────────────────────────────────────────────────────────┐
│  Walker discovers: Test Content/receipts/united_DL1492.pdf (3pp) │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  peek(): cheap inspection                                         │
│   • ext = ".pdf"                                                  │
│   • size_bytes = 84,221                                           │
│   • page_count = 3                                                │
│   • text_density = 1820                                           │
│   • extractable = True                                            │
│   • peek_text contains "$247.50", "DL1492", "25 May 2022"         │
│     → criticality bumped to "critical" (currency + ID patterns)   │
│   Cost: ~30 ms.                                                   │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  decide(): pure function                                          │
│   ext in PDF_EXTS                                  ✓              │
│   page_count (3) ≤ PDF_SHORT_PAGE_THRESHOLD (5)    ✓              │
│   → routes = ["T3"]   (short-PDF branch wins before vs check)     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  tier3.run_async(path, source_rel, agent)                         │
│   1. digest = sha256(file)[:16]      (for stable summary filename)│
│   2. message = build_user_message(path)                           │
│        → ["Filename: united_DL1492.pdf\nSummarize this file.",    │
│           ContentBlock(text=<extracted PDF text>, ...)]           │
│   3. summary: FileSummary = await _run_with_retry(agent, message) │
│        → ONE network call to Kimi with NativeOutput(FileSummary)  │
│        → 429 backoff loop (up to 6 retries)                       │
│        → Optional fallback to FALLBACK_LLM_PROVIDER on failure    │
│   4. md = render_markdown(summary, source_rel)                    │
│   5. write_summary(Test Summaries/<digest>_t3.md, md)             │
│   Cost: ~3-15 s wall-clock, ~$0.001 at Kimi pricing.              │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Manifest update: mark_summarized(rel, size, summary_file_rel)    │
│   • routes = ["T3"]                                               │
│   • summary_file = "Test Summaries/<digest>_t3.md"                │
│   • ingested_at = None  (Qdrant push hasn't happened yet)         │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼ (every 100 files OR end-of-walk)
┌──────────────────────────────────────────────────────────────────┐
│  Stage 2 push: ingest_from_manifest()                             │
│   1. parse_summary_file(<digest>_t3.md) → ParsedSummary           │
│   2. embed_dense(title + summary + keywords + identifiers)        │
│   3. embed_sparse(same)  → BM25 sparse vector                     │
│      ↑ identifiers are HERE — exact-match tokens like "DL1492"    │
│        are part of the BM25 vocabulary for this file              │
│   4. upsert_summaries([point]) into "summaries" collection        │
│   5. mark_ingested(rel) → ingested_at stamped                     │
└──────────────────────────────────────────────────────────────────┘
```

## End-to-end with a real file

Take `Test Content/receipts/united_DL1492.pdf` — a 3-page Delta flight
receipt for $247.50 (a typical short-PDF / discriminator-heavy file).

### Step 1 — Walker discovers it

`just walk Test Content/` runs.
[walker.py:107 find_candidates()](../src/ingest/walker.py#L107) calls
`root.rglob("*")`, collects every file with a considered extension,
applies ignore rules. This file passes — `.pdf`, no `.gitignore` hit,
not under an asset-library folder.

### Step 2 — peek + decide

[src/router.py peek()](../src/router.py) routes to `_peek_pdf()`. That
opens the file with `pypdf` for `page_count`, samples ~5 pages for
`text_density` and `image_ratio`, and slices ~5 KB of `peek_text` for
the criticality scan.

```python
PeekResult(
    path=Path("Test Content/receipts/united_DL1492.pdf"),
    ext=".pdf",
    size_bytes=84_221,
    page_count=3,                # short PDF
    text_density=1820,
    extractable=True,
    image_ratio=0.10,
    row_count=None,
    image_dims=None,
    peek_text=(
        "Delta Airlines - Flight Receipt\n"
        "Passenger: Jane Doe\n"
        "Flight DL1492, Atlanta ATL -> Hartford BDL, 25 May 2022\n"
        "Confirmation code: ABC123\n"
        "Total charged: $247.50\n..."
    ),
)
```

`compute_sensitivity()` finds `$247.50` (currency) and `Confirmation
code: ABC123` (ID pattern). Score crosses the threshold, criticality
flips to `"critical"` (`source = "content"`).

`decide()` walks its branch table:

```python
ext = ".pdf"
if ext in PDF_EXTS:                                       # ✓
    if p.page_count == 0: skip                            # 3 ≠ 0 ✓
    if p.page_count <= PDF_SHORT_PAGE_THRESHOLD:          # 3 ≤ 5 ✓
        return RouteDecision(routes=["T3"], ...)          # ← lands here
    # text-native and visual branches never reached
```

**Decision: T3.** The short-PDF rule fires *before* the text-native
check, so even though this PDF is text-native, it goes to T3 — short
PDFs are presumed to be discriminator-heavy regardless. Criticality
didn't change the routing here (T3 was already going to run); for a
*non-short* critical file the routing would have been `["T3", "T2"]`.

Total cost so far: ~30 ms. Still no LLM call.

### Step 3 — tier3.run_async

[tier3.py:35](../src/ingest/tier3.py#L35) executes:

```python
async def run_async(path, source_rel, agent: ChatAgent[FileSummary]) -> TierOutcome:
    digest = await asyncio.to_thread(hash_file, path)
    # → "9f4a23c10b7d8e6f"  (sha256(file)[:16])

    out_path = SUMMARIES_DIR / f"{digest}_t3.md"
    # → Test Summaries/9f4a23c10b7d8e6f_t3.md

    message = await asyncio.to_thread(build_user_message, path)
    # build_user_message at stage1/summarize.py:189:
    #   header = "Filename: united_DL1492.pdf\nSummarize this file."
    #   blocks = build_content_blocks(path,
    #              max_chars=MAX_TEXT_CHARS=120_000,
    #              max_pdf_pages=PDF_VISION_MAX_PAGES=20)
    # For this PDF: blocks = [PDFContent(extracted_text="Delta Airlines\n..."),]
    # PDFs ≤ 20 pages can be sent as vision content too if the provider supports it.

    summary = await _run_with_retry(agent, message, path.name)
    # ↓ network round-trip to Kimi
    #   PydanticAI's NativeOutput enforces FileSummary schema
    #   429 retries: up to 6 attempts with server-suggested or 2^n backoff
    #   Optional fallback to FALLBACK_LLM_PROVIDER (e.g. ollama) if primary fails

    body_markdown = render_markdown(summary, source_rel)
    await asyncio.to_thread(write_summary, out_path, body_markdown)
    return TierOutcome(
        summary_file_rel="Test Summaries/9f4a23c10b7d8e6f_t3.md",
        body_chars=len(body_markdown),
    )
```

**The LLM call.** Kimi receives the system prompt
([summarize.py:80-101](../src/stage1/summarize.py#L80-L101) — explicit
instructions to preserve discriminators verbatim), the filename header,
and the extracted PDF text. It returns a `FileSummary`:

```python
FileSummary(
    title="Delta flight DL1492 Atlanta to Hartford - Jane Doe",
    summary=(
        "Delta Airlines flight receipt for passenger Jane Doe. "
        "Flight DL1492 from Atlanta ATL to Hartford BDL on 25 May 2022. "
        "Confirmation code ABC123. Total charged: $247.50."
    ),
    content_type="pdf",
    keywords=["flight", "receipt", "airline", "delta", "travel"],
    key_entities=["Delta Airlines", "Jane Doe", "Atlanta ATL", "Hartford BDL"],
    identifiers=["DL1492", "25 May 2022", "ABC123", "$247.50"],
)
```

Compare this to what T2 would have done with the same file: the entire
8 KB extracted body would be embedded, with "Delta Airlines" appearing
*next to* "Thank you for choosing Delta," "Cancel anytime within 24
hours," and pages of fare-class boilerplate. T3's `identifiers` field
strips that signal-to-noise problem at the embedding stage.

**Note the cap.** `MAX_TEXT_CHARS = 120_000`
([summarize.py:40](../src/stage1/summarize.py#L40)). That's the cap on
text sent *to the LLM*, not the embedded body. Kimi sees up to 120 KB
of extracted text (vs. T2's 8 KB embedded). Long-tail PDFs that exceed
this get truncated, but in practice T3 receives short files (≤5 pages),
so the cap is rarely hit.

### Step 4 — The summary markdown on disk

`Test Summaries/9f4a23c10b7d8e6f_t3.md` (rendered by
[render_markdown](../src/stage1/summarize.py#L200)):

```
Source: Test Content/receipts/united_DL1492.pdf

# Delta flight DL1492 Atlanta to Hartford - Jane Doe

Delta Airlines flight receipt for passenger Jane Doe. Flight DL1492
from Atlanta ATL to Hartford BDL on 25 May 2022. Confirmation code
ABC123. Total charged: $247.50.

**Content type:** pdf

**Keywords:** flight, receipt, airline, delta, travel

**Key entities:** Delta Airlines, Jane Doe, Atlanta ATL, Hartford BDL

**Identifiers:** DL1492, 25 May 2022, ABC123, $247.50
```

This is the *exact* shape Stage 2's parser expects
([common.py:55](../src/ingest/common.py#L55)). Same envelope as T1/T2,
but the body is now a *3-7 sentence prose summary* and the
**Identifiers** field carries the BM25 gold.

### Step 5 — Manifest update

[walker.py:243](../src/ingest/walker.py#L243):

```python
manifest.mark_summarized(
    rel="Test Content/receipts/united_DL1492.pdf",
    size=84_221,
    summary_file_rel="Test Summaries/9f4a23c10b7d8e6f_t3.md",
)
```

Sets `routes=["T3"]` and `ingested_at = None`.

### Step 6 — Stage 2 push (every 100 files OR end-of-walk)

The chunk-flush mechanism calls `ingest_from_manifest`. For our file:

1. **Parse** the markdown back into a `ParsedSummary` struct.
2. **Embed dense:** `embed_dense_query(title + summary + keywords + identifiers)`
   → 384-dim float vector via `sentence-transformers/all-MiniLM-L6-v2`.
   Because the identifiers are part of the embedded text, "DL1492" and
   "$247.50" contribute to the dense vector — BUT the dense model has
   no special intuition for ID strings, so this mostly helps with
   semantic queries about "Delta flight" or "airline receipt."
3. **Embed sparse:** `embed_sparse_query(same text)` → sparse BM25
   vector. **This is where T3 shines.** "DL1492", "ABC123", "$247.50",
   "25 May 2022" all become high-weight BM25 terms — verbatim, no
   tokenization drift. A future query containing any of those strings
   will hit this file with near-perfect precision.
4. **Upsert:**

```python
PointStruct(
    id=_point_id("Test Content/receipts/united_DL1492.pdf"),
    vector={
        "dense":  [0.027, -0.054, ..., 0.011],         # 384 dims
        "sparse": SparseVector(
            indices=[42, 1207, 88, 951, ...],
            values=[2.4, 2.1, 1.9, 1.8, ...],          # high weights for identifiers
        ),
    },
    payload={
        "summary": (
            "# Delta flight DL1492 Atlanta to Hartford - Jane Doe\n\n"
            "Delta Airlines flight receipt for passenger Jane Doe...\n\n"
            "**Identifiers:** DL1492, 25 May 2022, ABC123, $247.50\n"
        ),
        "source_path": "Test Content/receipts/united_DL1492.pdf",
    },
)
```

5. **Mark ingested:** `ingested_at = "2026-04-27T03:14:00Z"`. This file
   won't be re-pushed unless the manifest flag is cleared (`--force`)
   or the file size changes.

**Cost so far for this file: ~3-15 sec total** (LLM dominates), plus
**~$0.001 in API spend** at Kimi pricing.

## Step 7 — User asks a question

Query: *"How much was the United flight to Hartford?"*

Note the question has **a typo** — the user wrote "United" but the
receipt is from Delta. Watch how T3's structured fields handle this.

[src/pipeline.py:45 ask()](../src/pipeline.py#L45):

1. `raw_query()` → `SearchQuery(query="How much was the United flight to Hartford?", keywords=[])`.
2. `run_search()` does hybrid retrieval at
   [src/stage2/search.py:261](../src/stage2/search.py#L261):
   - Dense: `embed_dense_query(...)` → 384-dim vector. The query
     embedding for "flight to Hartford" is semantically close to the
     Delta receipt's embedding because both mention "Hartford,"
     "flight," "airline" — even though "United" ≠ "Delta," the dense
     model is fuzzy enough to still rank it high.
   - Sparse: BM25 over query tokens. `Hartford` is a strong match (it's
     in `key_entities`). `flight` is a keyword. The mismatched `United`
     is a miss but doesn't dominate.
   - Qdrant `query_points()` with `FusionQuery(fusion="rrf")` returns
     top-5. Delta receipt ranks #1 because:
     - Dense: semantic neighborhood overlap (~0.74)
     - Sparse: 2 of 4 query tokens match (`Hartford`, `flight`)
     - RRF fusion blends both → strong combined score.
3. `answer_question()` reads the actual file (not the summary —
   [answer.py:271](../src/answer.py#L271) builds content blocks from
   the raw PDF). Since this is T3, **`_is_t0(display)` returns False**,
   so the file is read in full. The T3 summary is also prepended via
   `_summary_supplement` — Kimi sees the structured discriminators
   alongside the raw PDF text, which is what lets it correct the
   typo and quote the exact total.
4. Kimi answers, citing `united_DL1492.pdf`.

### What the user sees

```
Question: How much was the United flight to Hartford?

Retrieved (top-k from Qdrant):
  1. [0.789] Test Content/receipts/united_DL1492.pdf
  2. [0.421] Test Content/receipts/hertz_atlanta_2022.pdf
  ...

Answer:
  The flight wasn't on United — the receipt is from Delta Airlines
  (DL1492 from Atlanta ATL to Hartford BDL on 25 May 2022, passenger
  Jane Doe, confirmation code ABC123). The total charged was $247.50.

Sources used:
  - united_DL1492.pdf
```

Two things worked. **(a)** The filename `united_DL1492.pdf` happens to
start with `united` (probably the user named it that by mistake), so
even the misspelled query got a sparse-token assist from the path. But
**(b)** the *answer* is correct because Kimi sees the T3 summary's
identifiers (`DL1492`, `$247.50`, `Delta Airlines`) prepended as
context, which let it self-correct the question's typo and cite the
exact total. This is the failure mode T3 is designed for: discriminators
that the user may not even spell correctly need to be retrievable AND
verbatim in the answer context.

## What T3 is good at

- **Receipts and invoices.** Vendor name, date, amount, transaction ID,
  SKU — all promoted into `identifiers` and `key_entities`. BM25 hits
  these verbatim regardless of how the user phrases the question.
- **Contracts and short legal docs.** Article numbers, section
  references, party names, signing dates — the LLM pulls them out so
  retrieval can match exact references.
- **Scanned-short PDFs.** When a PDF's text extraction is partial
  (image-PDF with a thin OCR layer), the LLM can still produce a usable
  summary from the partial text. Better than T2 (which would just
  embed the partial raw text).
- **Critical files alongside T2.** When `criticality == "critical"`, T3
  runs *in addition* to whatever tier the content normally got. The
  result: **two Qdrant points for the same source path** — one with the
  raw extracted text, one with the LLM-distilled identifiers. Retrieval
  hits whichever is a better match.
- **Disambiguation under noisy queries.** Because the summary is prose
  written by an LLM that knows what a flight receipt looks like, the
  embedding ends up in a useful semantic neighborhood — better than
  embedding the boilerplate-heavy raw text.

## What T3 is weak at

- **Cost.** ~3-15 s wall-clock per file, ~$0.001 each. A 10k-file
  corpus running fully on T3 would be ~5 hours and ~$10. The router's
  job is to keep this small (most corpora have <5% T3 files).
- **API failures.** Kimi 429s, OpenRouter quota exhaustion,
  intermittent network errors — all real. Mitigated by the 6-attempt
  retry loop with server-suggested backoff
  ([summarize.py:307-368](../src/stage1/summarize.py#L307-L368)) and
  the optional `FALLBACK_LLM_PROVIDER` (e.g. fall back from cloud Kimi
  to local Gemma on persistent failure). On final failure, the file is
  skipped — manifest untouched — and the next `--sync` will retry it.
- **Hallucinated identifiers.** The system prompt is strict
  ("Do not invent content that is not present"), but LLMs occasionally
  emit a plausible-but-wrong invoice number. Hard to detect at ingest;
  shows up as a retrieval miss when the user asks for an ID that
  *should* exist but doesn't match.
- **120 KB cap on input.** Files larger than that get truncated before
  being sent to Kimi. In practice T3 only gets short files (≤5 pages
  for PDFs), but a 100-page critical contract routed to `["T3", "T2"]`
  would have its T3 summary based only on the first ~120 KB.
- **Latency dominates ingest time.** T3 wall-clock is ~30× T2 and ~100×
  T1. Walking a corpus with many T3 files takes much longer than the
  same corpus with the same total bytes but fewer T3-eligible files.

## Differences from T1 / T2 / T4

| Property | T1 | T2 | **T3** | T4 |
|---|---|---|---|---|
| LLM call at ingest | ❌ | ❌ | **✅ Kimi (or configured provider)** | ❌ (uses GPU model) |
| Network required | ❌ | ❌ | **✅** (unless local provider) | ❌ |
| Body in summary | First 8 KB raw | First 8 KB extracted | **LLM-distilled prose summary** | None (multi-vector) |
| Identifiers field | filename only | filename only | **LLM-pulled (verbatim discriminators)** | filename only |
| Best for | Markdown, code, configs | Long text-native PDF/DOCX/etc. | **Receipts, invoices, short contracts, scanned-short PDFs** | Scanned / figure-heavy / visual-rich docs |
| Cost per file | ~50 ms | ~100 ms - 1 s | **~3 - 15 s + ~$0.001** | ~5 - 30 s GPU |
| Retry / fallback | n/a | n/a | **6× 429 backoff + optional provider fallback** | n/a |
| Storage in Qdrant | 1 point in `summaries` | 1 point in `summaries` | **1 point in `summaries`** | ~1024 patch-vectors per page in `fast_tier` |

## Time & space complexity

T3's cost story is dominated by **one number**: the LLM round-trip.
Everything else is rounding error.

### Per-file time, end-to-end

| Stage | Operation | Cost (typical) | Variance | Bottleneck |
|---|---|---|---|---|
| 1. Walker discovery | `rglob` + ignore checks | ~0.1 ms / file | low | filesystem stat |
| 2. peek() | parse first ~5 KB, page_count, density, sensitivity | **30 - 50 ms** | low | format-dependent open |
| 3. decide() | pure-function branch table | <0.5 ms | none | CPU (negligible) |
| 4. hash_file() | sha256 over full file | **1 - 30 ms** | linear in size | disk I/O (rare for short PDFs) |
| 5. build_user_message → build_content_blocks | extract text via `src/content.py` | 100 ms - 1 s | medium | parser CPU |
| 6. **agent.run() — LLM call** | network → Kimi → schema-validated parse | **3 - 15 s typical, up to 60 s tail** | **very high** | **remote LLM** |
| 7. 429 retry (if hit) | exponential or server-suggested wait | 1 - 60 s × up to 6 attempts | rare | provider quota |
| 8. render_markdown | string concat | <1 ms | none | CPU |
| 9. write_summary | file write | ~5 ms | low | disk |
| 10. manifest update | dict mutation + json flush | ~10 ms | low | json serialize |
| 11. embed dense | MiniLM-L6-v2 (CPU) on summary | 20 - 40 ms | low | model forward pass |
| 12. embed sparse | BM25 tokenizer + idf lookup | ~5 ms | low | hash table |
| 13. Qdrant upsert | local HTTP/gRPC | 5 - 20 ms | low | network/disk |
| **Total** | one file, ingest → searchable | **~3 - 16 s typical** (steady state) | LLM-bound | step 6 |

**Where the time goes for a typical receipt PDF**: ~95% LLM round-trip,
~3% extraction, ~2% everything else. If a 429 retry hits, those
percentages don't change; the file just takes longer in absolute terms.

### Per-file dollar cost

At Moonshot Kimi pricing (Apr 2026):

| Component | Quantity | Cost |
|---|---|---|
| Input tokens | typical short PDF (~5 KB extracted text) → ~1,500 input tokens | ~$0.0003 |
| Output tokens | FileSummary JSON (~200-400 tokens) | ~$0.0006 |
| **Per file** | typical receipt | **~$0.001** |
| **10,000 T3 files** | full corpus, T3-only run | **~$10** |
| **Per file (max)** | 120 KB input + long output | **~$0.01** |

If you switch `LLM_PROVIDER` to a local provider (e.g. Gemma 3n via
ollama), dollar cost is $0 but wall-clock per file balloons to **~10 - 60 s**
depending on hardware. For batch ingest of large corpora,
local providers are usually slower in wall-clock than cloud.

### Per-file space, on disk and in Qdrant

| Where | What | Size | Bounded by |
|---|---|---|---|
| `Test Summaries/<digest>_t3.md` | LLM summary markdown | **0.5 - 2 KB** | summary length (3-7 sentences + lists), much smaller than T1/T2's 8 KB body |
| `Test Summaries/_manifest.json` | one row per file | ~400 bytes | rel path + summary path + timestamps |
| Qdrant `summaries` collection | dense vector | 384 × 4 B = **1,536 B** | MiniLM-L6-v2 dim |
| Qdrant `summaries` collection | sparse vector | ~30 - 80 terms × ~12 B = **0.4 - 1 KB** | unique BM25 terms (T3 has fewer than T2 because the LLM produces tighter prose) |
| Qdrant `summaries` collection | payload (`summary`, `source_path`) | **0.5 - 2 KB** | summary length |
| **Total per-file ingested** | disk + Qdrant | **~3 - 6 KB** | LLM summary is far more compact than raw text |
| **Original file** (untouched) | not copied or modified | n/a | T3 never duplicates the source |

T3 produces the **smallest summary footprint** of any tier because the
LLM compresses the file to a few hundred tokens. T2 stores 8 KB of raw
text per file; T3 stores 0.5-2 KB of distilled prose. Ironically, the
most expensive tier to *produce* yields the cheapest summaries to
*store*.

### Per-file RAM, during ingest

| Operation | Peak RSS | Released after |
|---|---|---|
| pypdf `PdfReader` (for build_content_blocks) | 5 - 30 MB | extract returns |
| HTTP client + response buffer | ~5 MB | LLM call returns |
| MiniLM-L6-v2 model | **~90 MB** loaded once, reused | process exit |
| Qdrant client | ~10 MB | process exit |
| **Walker steady-state** | ~150 MB + concurrency-many parser instances | end of run |

Lower peak RAM than T2 because the LLM call itself doesn't allocate
much in the walker process — the heavy work is on the provider's
servers.

### Big-O analysis

Let `N` = number of T3-eligible files in the corpus, `S_i` = size of
file *i* in bytes, `B_T3 ≈ 1 KB` = typical T3 summary size.

| Resource | Per file | Across N files |
|---|---|---|
| Extraction time | **O(min(S_i, 120 KB))** = bounded | O(N) |
| LLM round-trip | **O(1) wall-clock** (network-bound, not CPU-bound) | **O(N)** wall-clock — sequential by default; concurrency helps |
| Embedding time | **O(B_T3)** = O(1) bounded | **O(N)** |
| Disk written | **O(B_T3)** = O(1) bounded | **O(N)** |
| Qdrant points | **1 point** | **O(N)** |
| **API dollar cost** | **O(input_tokens + output_tokens)** ≈ O(min(S_i, 120 KB)) | **O(N · avg_size)** — **the only tier where corpus size hits your wallet linearly** |

**Key takeaway:** T3 is **linear in N for both wall-clock and money**.
The `concurrency` flag (`run_batch(... concurrency=8)`) lets you
parallelize the LLM round-trips, turning O(N) wall-clock into roughly
O(N / concurrency) — at the cost of more 429s if you exceed the
provider's RPM limit. Default is 1 (sequential, safe).

### Realistic throughput

On a residential broadband + Kimi cloud:

- **0.1 - 0.5 files/sec** at concurrency=1 (sequential)
- **1 - 4 files/sec** at concurrency=8 (parallel, watching for 429s)
- A **1,000 T3 file corpus** at concurrency=8: **~5 - 15 minutes**, **~$1**
- A **10,000 T3 file corpus** at concurrency=8: **~50 - 150 minutes**, **~$10**

Compare:
- T1: ~30 - 100 files/sec (no parser, no LLM, no network)
- T2: ~5 - 15 files/sec (parser CPU-bound)
- T3: **~0.1 - 4 files/sec** (LLM network-bound)
- T4: ~0.05 - 0.3 pages/sec (GPU-bound, multi-page per file)

T3 is **30-100× slower than T2 per file** in wall-clock, even with
concurrency. The router's job is to gate it tightly — and it does:
typical corpora see <5% of files routed to T3.

### Where T3 falls over

- **Provider quota exhaustion.** If Kimi 429s the 6th retry, the file
  is skipped. With `FALLBACK_LLM_PROVIDER=ollama` configured, one
  last-ditch local attempt happens before giving up. Without fallback,
  the file lands in the `errors` bucket and waits for the next sync.
- **Slow tail.** Some LLM calls take 30-60 s for no obvious reason
  (long network path, queueing on the provider side). The walker
  doesn't time out at the per-file level — only the underlying HTTP
  client's timeout applies. A pathological file can stall a worker
  slot for a minute.
- **Ratchet effect on `--force`.** `ns sync --force` re-runs T3 on
  every file regardless of size. On a corpus with 10k T3 files, this
  is ~$10 every time. Don't `--force` casually.
- **Hallucinated identifiers** as discussed in "What T3 is weak at."

---

## When T3 is co-routed (runs alongside other tiers)

Three patterns:

1. **Critical PDF, non-short** ([router.py:967-969](../src/router.py#L967-L969))
   → `["T3", "T2"]`. The PDF gets *both* an LLM summary (for
   discriminators) and a full extracted-text summary (for the back
   half of the document). Two Qdrant points share the same
   `source_path`.
2. **Critical DOCX/XLSX/PPTX/HTML/IPYNB/mid-CSV** → `["T3", "T2"]` for
   the same reason. Configured in each ext branch of `decide()`.
3. **Critical image-heavy PPTX** → `["T3", "T2", "T4"]`. The slide
   deck gets LLM identifiers (T3), text extraction (T2), and ColPali
   patch vectors (T4) — three Qdrant rows. Maximum recall, maximum
   cost.

In all co-routing cases, the walker runs each tier sequentially per
file (T3 first, then T2). Failure of one doesn't abort the others —
the manifest is updated only with successful tiers.

## When T3 is *replaced* by another tier

- **Long, text-native, non-critical PDF** → **T2**. No LLM needed; raw
  extraction + 8 KB body cap suffices.
- **Long, text-native, critical PDF** → **T3 + T2** (co-routed, see
  above).
- **Visual-heavy PDF, T4 enabled** → **T4** (or **T3 + T4** if
  critical). LLM gets skipped because ColPali captures the visual
  signal directly.
- **CSV ≥ 100k rows** → **T0**. Too big to summarize; ripgrep at
  answer time.

## Cross-references

- [src/ingest/tier3.py](../src/ingest/tier3.py) — the worker, ~60 lines
- [src/stage1/summarize.py](../src/stage1/summarize.py) — `FileSummary`, prompts, `_run_with_retry`, `build_user_message`, `render_markdown`
- [src/llm.py](../src/llm.py) — `ChatAgent`, provider registry, `build_agent`
- [src/content.py](../src/content.py) — `build_content_blocks` (text + vision blocks for the LLM)
- [src/router.py:955-962](../src/router.py#L955-L962) — short-PDF → T3
- [src/router.py:1009-1017](../src/router.py#L1009-L1017) — visual PDF fallback → T3
- [src/router.py:1156-1163](../src/router.py#L1156-L1163) — image, ColPali disabled → T3
- [src/router.py compute_sensitivity](../src/router.py) — currency / legal / ID pattern scan that bumps criticality
- [src/stage2/__main__.py ingest_from_manifest](../src/stage2/__main__.py) — Stage 2 push
- [src/stage2/parser.py](../src/stage2/parser.py) — markdown → `ParsedSummary`
- [src/stage2/embeddings.py](../src/stage2/embeddings.py) — dense + sparse encoders
- [src/answer.py:271](../src/answer.py#L271) — full-file read at answer time (T1/T2/T3 share this path)
- [IO - Tier 1.md](IO%20-%20Tier%201.md) — direct embed (no parser, no LLM)
- [IO - Tier 2.md](IO%20-%20Tier%202.md) — extract-then-embed (parser, no LLM)
- [IO - Tiers.md](IO%20-%20Tiers.md) — overview of all five tiers
- [IO - Stage 1.md](IO%20-%20Stage%201.md) — original (T3-only) summarization flow, predates the tiering system
- [IO - Stage 2.md](IO%20-%20Stage%202.md) — embed + Qdrant push
- [IO - Colpali.md](IO%20-%20Colpali.md) — T4 (ColPali) internals
