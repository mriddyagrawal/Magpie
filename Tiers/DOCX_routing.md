# `.docx` routing

Word document. The decision is **figure-heavy vs text-heavy**: image_ratio
(images / paragraphs) > 0.3 routes to T4 (ColPali) if cost gates fit and
ColPali isn't disabled; otherwise T2 with the standard `python-docx` text
extractor.

> **Note**: the router happily routes figure-heavy DOCX to T4, but
> [src/stage1_fast/index.py:42](../src/stage1_fast/index.py#L42) currently only
> renders **PDF and image** files. A DOCX routed to T4 would raise
> `ValueError("unsupported file for fast tier")` inside the worker. In
> practice DOCX nearly always lands at T2 (or T3+T2 if critical).

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | `_CONSIDERED_EXTS` (allowed). |
| peek function | `_peek_docx` via python-docx ([src/router.py:333](../src/router.py#L333)) |
| decide branch | DOCX_EXTS ([src/router.py:1023](../src/router.py#L1023)) |
| Threshold | `image_ratio > 0.3` → visual path |
| Tier worker(s) | `tier2.run` (default) / `tier3.run_async` (critical adds T3) / `tier4.run` (figure-heavy) |
| Stage 2 downstream | parse → embed → upsert into `summaries` collection (1 point per file). |

## Identical paths

_(none — only `.docx` takes this path)_

## Flowchart

```mermaid
flowchart TD
    A["File: example.docx"] --> B{"In ignore rules?"}
    B -- "yes" --> Z1["filtered"]
    B -- "no" --> C{"Manifest unchanged?"}
    C -- "yes" --> Z2["SKIP: unchanged"]
    C -- "no" --> D["router.peek →<br/>_peek_docx via python-docx"]
    D --> E["Count paragraphs (n_para)<br/>Count image rels (n_image)<br/>image_ratio = n_image / n_para<br/>5 KB peek_text"]
    E --> F["scores + criticality + t4 cost"]
    F --> G["router.decide<br/>DOCX_EXTS branch"]
    G --> H{"peek_error?"}
    H -- "yes" --> Z3["SKIP: docx unreadable"]
    H -- "no" --> I{"image_ratio > 0.3<br/>AND not colpali=never<br/>AND T4 cost gates fit?"}
    I -- "yes (figure-heavy)" --> J{"criticality == critical?"}
    J -- "yes" --> R34["Route: T3 + T4"]
    J -- "no" --> R4["Route: T4"]
    I -- "no (text-heavy)" --> K{"criticality == critical?"}
    K -- "yes" --> R32["Route: T3 + T2"]
    K -- "no" --> R2["Route: T2"]

    R34 --> W3
    R4 --> W4["tier4.run<br/>(currently raises:<br/>stage1_fast doesn't<br/>render .docx)"]
    R32 --> W3["tier3.run_async<br/>(walker primary = T3)"]
    R2 --> W2["tier2.run"]

    W3 --> D1["content-hash dedup<br/>build_content_blocks:<br/>extract_docx_text<br/>cap 120K chars<br/>'Content type: docx' block"]
    D1 --> D2["LLM → FileSummary"]
    D2 --> D3["render_markdown<br/>→ &lt;hash16&gt;_t3.md"]

    W2 --> X1["extract_docx_text<br/>paragraphs + table rows<br/>tab-joined<br/>cap 8000 chars"]
    X1 --> X2["render_summary_markdown<br/>→ &lt;hash16&gt;_t2.md"]

    D3 --> SP["End of walk → Stage 2 push"]
    X2 --> SP
    SP --> SP1["parse_summary_file"]
    SP1 --> SP2["embed_dense + embed_sparse"]
    SP2 --> SP3["Qdrant upsert into<br/>'summaries' collection<br/>1 point per file"]
    SP3 --> SP4["manifest.mark_ingested"]

    classDef skip fill:#ffcccc,stroke:#990000,color:#000
    class Z1,Z2,Z3 skip
    classDef llm fill:#cce5ff,stroke:#0044aa,color:#000
    class D2,D3 llm
    classDef warn fill:#ffe5b4,stroke:#aa6600,color:#000
    class W4 warn
```

## Code references

- peek: [src/router.py:333](../src/router.py#L333)
- decide branch: [src/router.py:1023](../src/router.py#L1023)
- T2 extractor: [src/content.py:282](../src/content.py#L282) (`extract_docx_text`)
- T3 worker: [src/ingest/tier3.py](../src/ingest/tier3.py)
- T4 worker (incomplete for docx): [src/stage1_fast/index.py:42](../src/stage1_fast/index.py#L42)
- Stage 2 push: [src/stage2/__main__.py:29](../src/stage2/__main__.py#L29)
