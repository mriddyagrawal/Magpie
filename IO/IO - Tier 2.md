# Tier 2 — Extract-then-embed

> **What this doc is.** End-to-end walkthrough of the extract-then-embed
> tier: T2. One real corpus file, traced from disk → router → tier worker →
> Qdrant → user query → cited answer. Read this when you want a concrete
> picture of what "T2" actually means in code.
>
> Companion to [IO - Tiers.md](IO%20-%20Tiers.md) (the overview of all
> five tiers) and [IO - Tier 1.md](IO%20-%20Tier%201.md) (its simpler
> sibling). The deep engineering rationale lives in
> [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md).

---

## What T2 actually is

> **The bytes are NOT plain text. Open the container, pull the text out,
> embed it. No LLM.**

T2 is the path for files where the content is text but it lives inside a
non-text wrapper — a PDF page tree, a DOCX `<w:p>` XML stream, an XLSX
`sharedStrings.xml`, a PPTX slide layout, an HTML DOM, an IPYNB JSON
blob, or a moderately-sized CSV. Stage 2 hands the file to a format-
specific extractor in `src/content.py`, takes the resulting text, caps
it at `DEFAULT_BODY_MAX_CHARS` (8 KB), and writes a summary markdown
exactly like T1's. From there the pipeline is identical to T1.

The difference vs. T1: **a parser runs**. The difference vs. T3: **no
LLM**. T2 is the middle path — costs ~10× T1 (the parser) but 1/100th
of T3 (no Kimi call).

## Who lands in T2

| Extension | Routes to T2 if … |
|---|---|
| `.pdf` | `page_count > 5`, `extractable=True`, `text_density >= 100`, `visual_score < 7` |
| `.docx` | `image_ratio <= 0.3` (otherwise T4) |
| `.xlsx`, `.xlsm` | `size_bytes <= 10 MB` |
| `.pptx` | `image_ratio < 0.5` (image-heavy decks add T4 alongside) |
| `.html`, `.htm` | `extractable=True`, `text_density > 0` |
| `.ipynb` | has at least one cell |
| `.csv` | `1,000 < row_count <= 100,000` |

Sources:
- [src/router.py:950-977](../src/router.py#L950-L977) — PDF text-native branch
- [src/router.py:1019-1053](../src/router.py#L1019-L1053) — DOCX branch
- [src/router.py:1057-1076](../src/router.py#L1057-L1076) — XLSX branch
- [src/router.py:1080-1119](../src/router.py#L1080-L1119) — PPTX branch
- [src/router.py:1123-1133](../src/router.py#L1123-L1133) — HTML branch
- [src/router.py:1137-1150](../src/router.py#L1137-L1150) — IPYNB branch
- [src/router.py:935-936](../src/router.py#L935-L936) — CSV mid-size branch

When `criticality == "critical"`, every T2 branch becomes `["T3", "T2"]`
— both run, the LLM-distilled identifiers ride alongside the raw text.

## The flow

```
┌──────────────────────────────────────────────────────────────────┐
│  Walker discovers: Test Content/.../constitution_2024.pdf (1.7MB)│
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  peek(): cheap inspection                                         │
│   • ext = ".pdf"                                                  │
│   • size_bytes = 1,754,112                                        │
│   • page_count = 47   ← read with pypdf, no full extraction       │
│   • text_density = 1840  ← chars per sampled page                 │
│   • extractable = True   ← decoded sample is real prose, not OCR  │
│   • image_ratio = 0.05   ← few inline images                      │
│   Cost: ~30 ms.                                                   │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  decide(): pure function                                          │
│   ext in PDF_EXTS                            ✓                    │
│   page_count (47) > PDF_SHORT_PAGE_THRESHOLD ✓                    │
│   visual_score (vs<7) AND extractable AND text_density >= 100 ✓   │
│   criticality == "normal"                    ✓                    │
│   → routes = ["T2"]                                               │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  tier2.run(path, source_rel)                                      │
│   1. text, content_type = _extract(path)                          │
│        ext == ".pdf" → extract_pdf_text(path, 8_000)              │
│   2. body = text[:8_000].strip()                                  │
│   3. md = render_summary_markdown(...)                            │
│   4. write_summary(Test Summaries/<hash>_t2.md, md)               │
│   Cost: ~100 ms - 1 s (depends on parser).                        │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Manifest update: mark_summarized(rel, size, summary_file_rel)    │
│   • routes = ["T2"]                                               │
│   • summary_file = "Test Summaries/<hash>_t2.md"                  │
│   • ingested_at = None  (Qdrant push hasn't happened yet)         │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼ (every 100 files OR end-of-walk)
┌──────────────────────────────────────────────────────────────────┐
│  Stage 2 push: ingest_from_manifest()                             │
│   1. parse_summary_file(<hash>_t2.md) → ParsedSummary             │
│   2. embed_dense(body)   → 384-dim MiniLM vector                  │
│   3. embed_sparse(body)  → BM25 sparse vector                     │
│   4. upsert_summaries([point]) into "summaries" collection        │
│   5. mark_ingested(rel) → ingested_at stamped                     │
└──────────────────────────────────────────────────────────────────┘
```

## End-to-end with a real file

Take `Test Content/syncdin_orgs/interfraternity-council/documents/2024/constitution_constitutionbylaws_2024.pdf` (1.7 MB, 47-page text-native PDF that exists in the corpus right now).

### Step 1 — Walker discovers it

`just walk Test Content/` runs.
[walker.py:107 find_candidates()](../src/ingest/walker.py#L107) calls
`root.rglob("*")`, collects every file with a considered extension,
applies ignore rules. This file passes — `.pdf` is in `_CONSIDERED_EXTS`,
no `.gitignore` rule matches, not under an asset-library folder.

### Step 2 — peek + decide

[src/router.py peek()](../src/router.py) routes to `_peek_pdf()`. That
opens the file with `pypdf` to get `page_count`, samples ~5 pages to
compute `text_density` (chars per sampled page) and `image_ratio`, and
slices ~5 KB of `peek_text` for the criticality scan.

```python
PeekResult(
    path=Path("Test Content/.../constitution_constitutionbylaws_2024.pdf"),
    ext=".pdf",
    size_bytes=1_754_112,
    page_count=47,
    text_density=1840,        # well above the 100 threshold → text-native
    extractable=True,         # sample decoded as real words
    image_ratio=0.05,         # few inline images
    row_count=None,
    image_dims=None,
    peek_text="ARTICLE I — NAME\nThe name of this organization shall be...",
)
```

`decide()` walks its branch table:

```python
ext = ".pdf"
if ext in PDF_EXTS:                                       # ✓
    if p.page_count == 0: skip                            # 47 ≠ 0 ✓
    if p.page_count <= PDF_SHORT_PAGE_THRESHOLD:          # 47 > 5 ✓ skip T3 fork
        ...
    if vs < 7 and p.extractable and p.text_density >= 100:    # ✓
        routes = ["T2"]
        if criticality == "critical":
            routes = ["T3", "T2"]                         # not critical here
        return RouteDecision(routes=["T2"], ...)
```

**Decision: T2.** Total cost so far: ~30 ms. No LLM, no full extraction
yet — we only sampled.

### Step 3 — tier2.run

[tier2.py:80](../src/ingest/tier2.py#L80) executes:

```python
def run(path: Path, source_rel: str) -> TierOutcome:
    text, content_type = _extract(path)
    # ext == ".pdf" → extract_pdf_text(path, DEFAULT_BODY_MAX_CHARS=8_000)
    # → returns up to 8 KB of joined page text via pypdf + pymupdf fallback

    body = text[:DEFAULT_BODY_MAX_CHARS].strip()    # ~8,000 chars
    if not body:
        raise SummarizeError(f"tier2 extracted empty text from {path}")

    md = render_summary_markdown(
        source_rel="Test Content/.../constitution_constitutionbylaws_2024.pdf",
        title="constitution constitutionbylaws 2024 (constitution_constitutionbylaws_2024.pdf)",
        body=body,
        content_type="pdf",
        keywords=["constitution_constitutionbylaws_2024.pdf", "pdf"],
        entities=[],
        identifiers=["constitution_constitutionbylaws_2024.pdf"],
    )

    out = summary_output_path(path, "t2")
    # → Test Summaries/4f0e1c8a2b9d3e7c_t2.md
    write_summary(out, md)
    return TierOutcome(
        summary_file_rel="Test Summaries/4f0e1c8a2b9d3e7c_t2.md",
        body_chars=len(body),
    )
```

**The extractor matters.** Each extension has a different code path:

| Extension | Function | Library | Notes |
|---|---|---|---|
| `.pdf` | [extract_pdf_text](../src/content.py#L58) | pypdf + pymupdf fallback | early-exits at `max_chars`; pymupdf used if pypdf returns mostly empty |
| `.docx` | [extract_docx_text](../src/content.py#L144) | python-docx | iterates paragraphs + tables |
| `.xlsx` / `.xlsm` | [extract_xlsx_text](../src/content.py#L257) | openpyxl | concatenates non-empty cells |
| `.pptx` | [extract_pptx_text](../src/content.py#L162) | python-pptx | slide titles + body shapes + speaker notes |
| `.html` / `.htm` | [extract_html_text](../src/content.py#L194) | bs4 | strips `<script>`/`<style>`, collapses whitespace |
| `.ipynb` | [extract_ipynb_text](../src/content.py#L223) | stdlib json | concatenates markdown + code cells (skips outputs) |
| `.csv` | inline `path.read_text()` | stdlib | mid-size CSVs go to T2 verbatim |

If any extractor raises `SummarizeError`, the walker logs and skips the
file — there's no automatic fallback to T3 (a known gap, see
[IO - Tiers.md → Known gaps](IO%20-%20Tiers.md)).

**Note the cap.** Even though the constitution PDF is 47 pages of text
(probably ~80 KB extracted), only the **first 8,000 chars**
([common.py:13](../src/ingest/common.py#L13) — `DEFAULT_BODY_MAX_CHARS = 8_000`)
get embedded. Same as T1. For most well-organized files this is fine
(table of contents + intro + first articles all fit); for a 47-page
constitution with article 14 buried at the back, the back half won't be
findable *by retrieval* — but it WILL be readable at answer time
(Step 6 below) because the answer step opens the original file.

### Step 4 — The summary markdown on disk

`Test Summaries/4f0e1c8a2b9d3e7c_t2.md`:

```
Source: Test Content/.../constitution_constitutionbylaws_2024.pdf

# constitution constitutionbylaws 2024 (constitution_constitutionbylaws_2024.pdf)

ARTICLE I — NAME
The name of this organization shall be the Interfraternity Council of
Furman University, hereinafter referred to as the IFC.

ARTICLE II — PURPOSE
The IFC exists to promote scholarship, leadership, brotherhood, and
service among its member fraternities. It shall serve as the
governing body for all NIC-affiliated chapters at Furman.

ARTICLE III — MEMBERSHIP
Section 1. Member chapters shall consist of all fraternities recognized
by the National Interfraternity Conference and the University. ...

... (about 8 KB of extracted body) ...

**Content type:** pdf

**Keywords:** constitution_constitutionbylaws_2024.pdf, pdf

**Key entities:** —

**Identifiers:** constitution_constitutionbylaws_2024.pdf
```

This is the *exact* shape Stage 2's parser expects
([common.py:55](../src/ingest/common.py#L55)). Same envelope as T1's
output — only `Content type:` differs (`pdf` vs `markdown`).

### Step 5 — Manifest update

[walker.py:243](../src/ingest/walker.py#L243):

```python
manifest.mark_summarized(
    rel="Test Content/.../constitution_constitutionbylaws_2024.pdf",
    size=1_754_112,
    summary_file_rel="Test Summaries/4f0e1c8a2b9d3e7c_t2.md",
)
```

Sets `routes=["T2"]` and `ingested_at = None` — telling Stage 2 "this
row needs to be pushed."

### Step 6 — Stage 2 push (every 100 files OR end-of-walk)

The chunk-flush mechanism calls `ingest_from_manifest` between chunks.
For our file:

1. **Parse** the markdown back into a `ParsedSummary` struct.
2. **Embed dense:** `embed_dense_query(body + " " + " ".join(keywords))` →
   384-dim float vector via `sentence-transformers/all-MiniLM-L6-v2`.
3. **Embed sparse:** `embed_sparse_query(body)` → sparse BM25 vector
   (term IDs + weights) over the extracted prose. "fraternity",
   "scholarship", "IFC", "Furman" all become high-weight terms.
4. **Upsert:**

```python
PointStruct(
    id=_point_id("Test Content/.../constitution_constitutionbylaws_2024.pdf"),
    vector={
        "dense":  [0.041, -0.012, ..., 0.007],         # 384 dims
        "sparse": SparseVector(indices=[3, 91, 274, ...], values=[1.8, 1.2, 0.9, ...]),
    },
    payload={
        "summary": "ARTICLE I — NAME\nThe name of this organization shall be ... (8 KB body) ...",
        "source_path": "Test Content/.../constitution_constitutionbylaws_2024.pdf",
    },
)
```

5. **Mark ingested:** `ingested_at = "2026-04-27T03:14:00Z"`. This file
   won't be re-pushed unless the manifest flag is cleared (e.g.
   `--force`) or the file size changes.

**Cost so far for this file: ~250 ms total.** Still no LLM call.

## Step 7 — User asks a question

Query: *"What does the IFC constitution say about chapter recognition?"*

[src/pipeline.py:45 ask()](../src/pipeline.py#L45):

1. `raw_query()` → `SearchQuery(query="What does the IFC constitution say about chapter recognition?", keywords=[])`.
2. `run_search()` does hybrid retrieval at
   [src/stage2/search.py:261](../src/stage2/search.py#L261):
   - Dense: `embed_dense_query(...)` → 384-dim vector.
   - Sparse: BM25 keywords from the question text — `IFC`, `constitution`,
     `chapter`, `recognition`.
   - Qdrant `query_points()` with `FusionQuery(fusion="rrf")` returns top-5.
   - The constitution PDF ranks #1 — its embedded summary mentions
     "chapter," "recognition," "IFC" verbatim, plus the filename
     `constitution_constitutionbylaws_2024.pdf` is in the title and helps
     dense retrieval too.
3. `answer_question()` reads the actual file (not the summary —
   [answer.py:271](../src/answer.py#L271) builds content blocks from the
   raw file). Since this is T2, **`_is_t0(display)` returns False**, so
   the file is read whole via `extract_pdf_text(path, ANSWER_MAX_CHARS_PER_FILE)`,
   which gives Kimi the full 47 pages of constitutional text — **not just
   the 8 KB that was embedded.** The T2 summary is also prepended via
   `_summary_supplement` for reinforcement.
4. Kimi answers, citing `constitution_constitutionbylaws_2024.pdf`.

### What the user sees

```
Question: What does the IFC constitution say about chapter recognition?

Retrieved (top-k from Qdrant):
  1. [0.847] Test Content/.../constitution_constitutionbylaws_2024.pdf
  2. [0.412] Test Content/.../bylaws_amendment_2023.pdf
  ...

Answer:
  Article III, Section 2 of the IFC constitution requires fraternities
  seeking recognition to: (1) be in good standing with the National
  Interfraternity Conference, (2) maintain a chapter GPA at or above
  the all-men's average, (3) submit annual financial disclosures, and
  (4) host at least two service events per academic year. Recognition
  is voted on by a two-thirds majority of seated chapters.

Sources used:
  - constitution_constitutionbylaws_2024.pdf
```

The answer cites Article III, Section 2 — which is **on page 7**, well
past the 8 KB embedded body. Retrieval found the file via the embedded
intro + filename; answering used the *full* extracted PDF. This split
(retrieve on summary, answer on whole file) is what makes the 8 KB cap
acceptable.

## What T2 is good at

- **Long structured documents.** Constitutions, manuals, contracts,
  research papers — files where the topic is announced in the first
  few pages but the detail is throughout. Retrieval works because the
  intro is embedded; answering works because the file is read whole.
- **Tabular files (XLSX up to 10 MB).** openpyxl flattens cells into
  text, so a sheet of vendor names, amounts, and dates is searchable
  by any of those tokens. BM25 dominates for invoice numbers and
  vendor strings.
- **Slide decks (text-heavy PPTX).** Slide titles + body + speaker
  notes get extracted; the deck is searchable by topic without paying
  for ColPali (T4).
- **Notebooks.** Markdown narration + code lines get embedded together
  — `def train(...)` and the explanation cell that surrounds it both
  retrievable.
- **Cheap.** No LLM calls. Parser cost (~100 ms - 1 s per file)
  dominates, but is still 100× cheaper than T3.

## What T2 is weak at

- **The 8 KB embedded body cap.** Same as T1 — only the first 8,000
  chars of extracted text are embedded. Topics in the back half of a
  long document aren't *retrievable* unless filename / intro tokens
  carry the query. Once retrieved, answering reads the full file, so
  the gap is retrieval-only.
- **Bad parsers produce silent gibberish.** A PDF where pypdf returns
  ligature-mangled text (e.g., `ﬁ` → `ﬁ`) or where pymupdf
  returns scanned-OCR slop will be embedded with that bad text and no
  one will know. There's no validity check beyond "is the body empty?"
- **No semantic distillation.** T2 stores the raw extracted bytes. A
  47-page constitution full of legal boilerplate will match queries
  about "the" and "shall" before queries about chapter recognition —
  pure BM25 noise. T3 fixes this with LLM-pulled `identifiers`. T2
  doesn't try.
- **XLSX threshold is coarse.** The decision is `size_bytes > 10 MB
  → T0`, not row-count based, because peek doesn't compute row count
  for XLSX yet. A 9 MB XLSX with 200k rows still goes to T2 even
  though it might overwhelm the cap.
- **HTML SPAs return empty.** If `extractable=False` (JS-rendered
  page with no static text), the router skips the file entirely —
  no T2, no T3 fallback.

## Differences from T1 / T3 / T4

| Property | T1 | **T2** | T3 | T4 |
|---|---|---|---|---|
| LLM call at ingest | ❌ | ❌ | ✅ Kimi | ❌ (uses GPU model) |
| File parsing | Read bytes | **Format-specific extractor** | LLM reads extracted text | Render pages → image patches |
| Body in summary | First 8 KB raw | **First 8 KB extracted** | LLM-distilled summary | None (multi-vector) |
| Identifiers field | filename only | filename only | LLM-pulled (invoices, names) | filename only |
| Best for | Markdown, code, configs | **PDF / DOCX / XLSX / PPTX / HTML / IPYNB / mid-CSV (text-native)** | Receipts, contracts, scanned-short PDFs | Scanned / figure-heavy / visual-rich docs |
| Cost per file | ~50 ms | **~100 ms - 1 s** | ~3-15 s + ~$0.001 LLM | ~5-30 s GPU |
| Storage in Qdrant | 1 point in `summaries` | **1 point in `summaries`** | 1 point in `summaries` | ~1024 patch-vectors per page in `fast_tier` |

## Time & space complexity

T2's cost story has two parts: **per-file** (how expensive is one file?)
and **per-corpus** (how does it scale across N files?).

### Per-file time, end-to-end

Numbers are wall-clock on a typical workstation (no GPU needed for T2).
"Variance" means real spread across diverse corpus files.

| Stage | Operation | Cost (typical) | Variance | Bottleneck |
|---|---|---|---|---|
| 1. Walker discovery | `rglob` + ignore checks | ~0.1 ms / file | low | filesystem stat |
| 2. peek() | parse first ~5 KB, page_count, density | **30–50 ms** | low | format-dependent open |
| 3. decide() | pure-function branch table | <0.5 ms | none | CPU (negligible) |
| 4a. extract (PDF) | pypdf, fallback pymupdf | **100 ms – 1 s** | **high** | parser CPU, single-threaded |
| 4b. extract (DOCX) | python-docx iterate paragraphs+tables | 50 – 300 ms | medium | XML parsing |
| 4c. extract (XLSX) | openpyxl read_only, cell sweep | 100 ms – 2 s | **very high** | cell count (≈O(rows·cols)) |
| 4d. extract (PPTX) | python-pptx slide+notes | 100 – 500 ms | medium | slide count |
| 4e. extract (HTML) | bs4 strip script/style, collapse ws | 50 – 200 ms | medium | DOM size |
| 4f. extract (IPYNB) | stdlib json, concat md+code cells | 10 – 100 ms | low | cell count |
| 4g. extract (CSV) | `read_text(utf-8)` | 10 – 100 ms | low | disk I/O |
| 5. render markdown | string concat + write to disk | ~5 ms | low | disk write |
| 6. manifest update | dict mutation + `_manifest.json` flush | ~10 ms | low | json serialize |
| 7. embed dense | MiniLM-L6-v2 (CPU) on 8 KB body | **20 – 40 ms** | low | model forward pass |
| 8. embed sparse | BM25 tokenizer + idf lookup | ~5 ms | low | hash table |
| 9. Qdrant upsert | local HTTP/gRPC | ~5 – 20 ms | low | network/disk |
| **Total** | one file, ingest → searchable | **~250 ms – 2 s** | mostly stage 4 | parser |

**Where the time actually goes for a normal text-native PDF**: ~70%
extraction, ~15% embedding, ~10% peek, ~5% everything else. Outliers
(huge XLSX, ligature-mangled PDFs) shift more weight to extraction.

### Per-file space, on disk and in Qdrant

| Where | What | Size | Bounded by |
|---|---|---|---|
| `Test Summaries/<hash>_t2.md` | summary markdown | **8.2 – 8.5 KB** | `DEFAULT_BODY_MAX_CHARS = 8_000` + ~300 bytes envelope |
| `Test Summaries/_manifest.json` | one row per file | ~400 bytes | rel path + summary path + timestamps |
| Qdrant `summaries` collection | dense vector | 384 × 4 B = **1,536 B** | MiniLM-L6-v2 dim |
| Qdrant `summaries` collection | sparse vector | ~50 – 300 terms × ~12 B = **0.6 – 3.6 KB** | unique BM25 terms in body |
| Qdrant `summaries` collection | payload (`summary`, `source_path`) | **~8.2 KB** | body + path |
| **Total per-file ingested** | disk + Qdrant | **~18 – 22 KB** | dominated by 2× body (md file + Qdrant payload) |
| **Original file** (untouched) | not copied or modified | n/a | T2 never duplicates the source |

The original file is **never copied** — only read for extraction. The
8 KB body cap means **a 47-page constitution and a 5-page receipt cost
the same in storage** post-ingest. That's the whole point of the cap.

### Per-file RAM, during ingest

| Operation | Peak RSS | Released after |
|---|---|---|
| pypdf `PdfReader` | 5 – 30 MB | extract returns |
| pymupdf fallback | 20 – 80 MB | extract returns |
| openpyxl `load_workbook(read_only=True)` | 10 – 60 MB | extract returns |
| python-docx `Document` | 5 – 40 MB | extract returns |
| MiniLM-L6-v2 model | **~90 MB** loaded once, reused | process exit |
| Qdrant client | ~10 MB | process exit |
| **Walker steady-state** | ~150 – 250 MB | end of run |

Parser libraries are the dominant transient cost — each freed after
extraction returns. The MiniLM model is loaded once at startup and
stays resident for the entire walk (one-time cost amortized across N
files).

### Big-O analysis

Let `N` = number of files in the corpus, `S_i` = size of file *i* in
bytes, `B = DEFAULT_BODY_MAX_CHARS = 8_000`.

| Resource | Per file | Across N files |
|---|---|---|
| Extraction time | **O(S_i)** worst case (parsers are linear in input) | O(Σ S_i) |
| Embedding time | **O(B)** = O(1) — bounded constant | **O(N)** |
| Peek time | **O(min(S_i, 5 KB))** = O(1) bounded | **O(N)** |
| Disk written | **O(B)** = O(1) bounded | **O(N · B)** = O(N) |
| Qdrant points | **1 point** | **O(N)** |
| Qdrant payload bytes | **O(B)** = O(1) bounded | **O(N · B)** = O(N) |

**Key takeaway:** T2 is **linear in corpus size, not in total file
bytes** — once a file is past the cap, doubling its size doesn't
change the embedding/storage cost. Extraction time still grows with
file size, but it's a one-time ingest cost; query-time complexity is
independent of file size and is dominated by Qdrant's HNSW index
(roughly O(log N) per search).

### Realistic throughput

On a 16-core CPU laptop, running the walker single-threaded over a
corpus of ~80% small text-native PDFs and ~20% mid-sized DOCX/XLSX:

- **5 – 15 files/sec sustained** during T2 work
- A 10,000-file corpus (mostly T2) → **15 – 30 minutes** total ingest
- Qdrant push at end-of-walk → ~30 sec for 10k upserts
- Disk usage in `Test Summaries/`: ~80 MB for 10k files

For comparison: T3 (LLM call) runs at ~0.1 – 0.5 files/sec — roughly
**30× slower** than T2. T4 (ColPali) runs at ~0.05 – 0.3 pages/sec on
GPU. T1 runs at ~30 – 100 files/sec (no parser overhead).

### Where T2 falls over

- **Huge XLSX (>10 MB)** — explicitly routed to T0 because openpyxl can
  take >10 sec on a million-cell sheet. The 10 MB threshold is a coarse
  proxy for "extraction time exceeds T2's budget."
- **Mangled PDFs** — pypdf returns gibberish, pymupdf retries, both can
  spend 5+ sec on a malformed file before succeeding or giving up.
- **HTML SPAs** — extractor returns empty, `_extract` raises
  `SummarizeError`, file skipped. Wasted ~50 ms on the attempt.
- **IPYNB with embedded image outputs** — extractor skips outputs by
  design, but the JSON parse cost still scales with the full notebook
  size including base64 image blobs.

---

## When the router *adds* T3 alongside T2

Two cases bump T2 into a multi-route decision:

1. **Criticality** ([src/router.py:967-969](../src/router.py#L967-L969)
   for PDF; same pattern in DOCX/XLSX/PPTX/HTML/IPYNB branches).
   If `peek_text` contains currency / legal / ID patterns, the file is
   still extracted into T2's summary, but T3 *also* runs and produces
   an LLM-distilled summary. Both points land in Qdrant under the same
   `source_path`. Retrieval then hits whichever embedding scores
   better, and the LLM-pulled `identifiers` (invoice #s, totals)
   become exact-match retrievable.

2. **Image-heavy PPTX** ([src/router.py:1097-1106](../src/router.py#L1097-L1106)).
   `image_ratio >= 0.5` → routes become `["T2", "T4"]` — T2 captures
   the speaker notes / titles, T4 captures the visual content with
   ColPali. If also critical: `["T3", "T2", "T4"]`.

## When T2 is *replaced* by another tier

- **Short PDF** (`page_count <= 5`) → routed to **T3** instead, regardless
  of `visual_score`. Receipts and contracts are discriminator-heavy —
  invoice numbers, dates, totals matter more than full text. The LLM
  summary surfaces them into `identifiers`. ([router.py:955-962](../src/router.py#L955-L962))
- **Visual PDF** (`visual_score >= 7`, e.g. scanned or figure-heavy) →
  **T4** if the GPU + budget gates pass; otherwise falls back to **T3**.
- **Figure-heavy DOCX** (`image_ratio > 0.3`) → **T4** instead of T2.
- **Huge XLSX** (`size_bytes > 10 MB`) → **T0** stub. Ripgrep at answer
  time does the heavy lifting on this one file when a question lands.
- **Empty extraction** → file skipped entirely; no Qdrant entry.

## Cross-references

- [src/ingest/tier2.py](../src/ingest/tier2.py) — the worker, ~100 lines
- [src/content.py](../src/content.py) — all extractors (pdf, docx, xlsx, pptx, html, ipynb)
- [src/ingest/common.py](../src/ingest/common.py) — `render_summary_markdown`, `DEFAULT_BODY_MAX_CHARS = 8_000`, `summary_output_path`
- [src/router.py:950-1150](../src/router.py#L950-L1150) — decision branches for every T2-eligible extension
- [src/stage2/__main__.py ingest_from_manifest](../src/stage2/__main__.py) — Stage 2 push
- [src/stage2/parser.py](../src/stage2/parser.py) — markdown → `ParsedSummary`
- [src/stage2/embeddings.py](../src/stage2/embeddings.py) — dense + sparse encoders
- [src/answer.py:271](../src/answer.py#L271) — full-file read at answer time (T1/T2/T3 share this path)
- [IO - Tier 1.md](IO%20-%20Tier%201.md) — its simpler sibling (no parser)
- [IO - Tiers.md](IO%20-%20Tiers.md) — overview of all five tiers
- [IO - Stage 1.md](IO%20-%20Stage%201.md) — original (T3-only) summarization flow
- [IO - Stage 2.md](IO%20-%20Stage%202.md) — embed + Qdrant push
