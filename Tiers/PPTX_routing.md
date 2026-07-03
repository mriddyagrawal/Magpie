# `.pptx` routing

PowerPoint deck. The decision is **image-heavy vs text-heavy**: image_ratio
(picture shapes / text paragraphs) ≥ 0.5 → routes T2 + T4 (ColPali on rendered
slides); otherwise T2 alone (or T3+T2 if critical). PPTX is the **only**
extension where T4 patch pooling is enabled (`POOL_FACTOR = 2`) — lecture decks
are query-shaped semantically, so half-resolution patches retain ~100% recall.

> **Note**: the router routes image-heavy PPTX to T4, but
> [src/stage1_fast/index.py:42](../src/stage1_fast/index.py#L42) currently only
> renders **PDF and image** files. PPTX routed to T4 would raise
> `ValueError("unsupported file for fast tier")`. In practice PPTX nearly
> always lands at T2 (or T3+T2 if critical).

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | `_CONSIDERED_EXTS` (allowed). |
| peek function | `_peek_pptx` via python-pptx ([src/router.py:452](../src/router.py#L452)) |
| decide branch | PPTX_EXTS ([src/router.py:1082](../src/router.py#L1082)) |
| Threshold | `image_ratio ≥ 0.5` → image-heavy path |
| Tier worker(s) | `tier2.run` (default) / `tier3.run_async` (critical) / `tier4.run` (image-heavy, with POOL_FACTOR=2) |
| Stage 2 downstream | parse → embed → upsert into `summaries`. T4 patches in `fast_tier`. |

## Identical paths

_(none — only `.pptx` takes this path)_

## Flowchart

```mermaid
flowchart TD
    A["File: example.pptx"] --> B{"In ignore rules?"}
    B -- "yes" --> Z1["filtered"]
    B -- "no" --> C{"Manifest unchanged?"}
    C -- "yes" --> Z2["SKIP: unchanged"]
    C -- "no" --> D["router.peek →<br/>_peek_pptx via python-pptx"]
    D --> E["Count slides (n_slides)<br/>Count picture shapes<br/>Count text paragraphs<br/>image_ratio = pics / paragraphs<br/>5 KB peek_text"]
    E --> F["scores + criticality + t4 cost"]
    F --> G["router.decide<br/>PPTX_EXTS branch"]
    G --> H{"peek_error or<br/>page_count == 0?"}
    H -- "yes" --> Z3["SKIP: pptx unreadable / empty"]
    H -- "no" --> I{"image_ratio ≥ 0.5<br/>AND not colpali=never<br/>AND T4 cost gates fit?"}

    I -- "yes (image-heavy)" --> J{"criticality == critical?"}
    J -- "yes" --> R324["Route: T3 + T2 + T4"]
    J -- "no" --> R24["Route: T2 + T4"]

    I -- "no (text-heavy<br/>OR T4 gated off)" --> K{"criticality == critical?"}
    K -- "yes" --> R32["Route: T3 + T2"]
    K -- "no" --> R2["Route: T2"]

    R324 --> W3
    R24 --> W2["tier2.run<br/>(walker primary = T2)"]
    R24 -.->|"deferred"| W4["tier4.run<br/>(currently raises:<br/>stage1_fast doesn't<br/>render .pptx)"]
    R32 --> W3["tier3.run_async<br/>(walker primary = T3)"]
    R32 -.->|"deferred"| W2
    R2 --> W2

    W3 --> D1["content-hash dedup<br/>build_content_blocks:<br/>extract_pptx_text<br/>cap 120K chars<br/>'Content type: pptx' block"]
    D1 --> D2["LLM → FileSummary"]
    D2 --> D3["render_markdown<br/>→ &lt;hash16&gt;_t3.md"]

    W2 --> X1["extract_pptx_text<br/>per slide:<br/>'## Slide N' header<br/>+ shape text<br/>+ '[notes] ...' speaker notes<br/>cap 8000 chars"]
    X1 --> X2["render_summary_markdown<br/>→ &lt;hash16&gt;_t2.md"]

    W4 --> F1["src.stage1_fast.index.index_file<br/>POOL_FACTOR = 2 (only ext)"]
    F1 --> F2["ColPali multi-vector encode<br/>patches pooled 2x"]
    F2 --> F3["Qdrant upsert into<br/>'fast_tier' collection"]
    F3 --> F4["manifest.fast_indexed_at +<br/>fast_pages"]

    D3 --> SP["End of walk → Stage 2 push"]
    X2 --> SP
    SP --> SP1["parse_summary_file"]
    SP1 --> SP2["embed_dense + embed_sparse"]
    SP2 --> SP3["Qdrant upsert into<br/>'summaries' collection<br/>1 point per file"]
    SP3 --> SP4["manifest.mark_ingested"]

    F4 --> SP

    classDef skip fill:#ffcccc,stroke:#990000,color:#000
    class Z1,Z2,Z3 skip
    classDef llm fill:#cce5ff,stroke:#0044aa,color:#000
    class D2,D3 llm
    classDef colpali fill:#ddeedd,stroke:#226633,color:#000
    class F1,F2,F3 colpali
    classDef warn fill:#ffe5b4,stroke:#aa6600,color:#000
    class W4 warn
```

## Code references

- peek: [src/router.py:452](../src/router.py#L452)
- decide branch: [src/router.py:1082](../src/router.py#L1082)
- T2 extractor: [src/content.py:300](../src/content.py#L300) (`extract_pptx_text`)
- T3 worker: [src/ingest/tier3.py](../src/ingest/tier3.py)
- T4 POOL_FACTOR=2: [src/ingest/tier4.py:43](../src/ingest/tier4.py#L43)
- Stage 2 push: [src/stage2/__main__.py:29](../src/stage2/__main__.py#L29)
