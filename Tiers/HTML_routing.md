# `.html` routing

HTML page. Trafilatura strips boilerplate (nav, header/footer, scripts, ads)
and yields clean article text. If extraction yields nothing — typical of
JavaScript-only SPAs that render server-side empty — the file is skipped.

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | `_CONSIDERED_EXTS` (allowed). |
| peek function | `_peek_html` via trafilatura ([src/router.py:507](../src/router.py#L507)) |
| decide branch | HTML_EXTS ([src/router.py:1125](../src/router.py#L1125)) |
| Threshold | extractable AND density > 0; else SKIP |
| Tier worker(s) | `tier2.run` (default) / `tier3.run_async` (critical adds T3) |
| Stage 2 downstream | parse → embed → upsert into `summaries` collection (1 point per file). |

## Identical paths

These extensions take the **same** code path: `.htm`.

## Flowchart

```mermaid
flowchart TD
    A["File: example.html"] --> B{"In ignore rules?"}
    B -- "yes" --> Z1["filtered"]
    B -- "no" --> C{"Manifest unchanged?"}
    C -- "yes" --> Z2["SKIP: unchanged"]
    C -- "no" --> D["router.peek →<br/>_peek_html via trafilatura"]
    D --> E["trafilatura.extract<br/>strip nav/header/footer/scripts/ads<br/>5 KB peek_text"]
    E --> F["scores + criticality"]
    F --> G["router.decide<br/>HTML_EXTS branch"]
    G --> H{"extractable AND<br/>text_density > 0?"}
    H -- "no" --> Z3["SKIP: html extracted empty<br/>(likely JS-only SPA)"]
    H -- "yes" --> I{"criticality == critical?"}
    I -- "yes" --> R32["Route: T3 + T2"]
    I -- "no" --> R2["Route: T2"]

    R32 --> W3["tier3.run_async<br/>(walker primary = T3)"]
    R2 --> W2["tier2.run"]

    W3 --> D1["content-hash dedup<br/>build_content_blocks:<br/>extract_html_text<br/>cap 120K chars"]
    D1 --> D2["LLM → FileSummary"]
    D2 --> D3["render_markdown<br/>→ &lt;hash16&gt;_t3.md"]

    W2 --> X1["extract_html_text<br/>via trafilatura<br/>(include_tables=True,<br/>include_comments=False)<br/>cap 8000 chars"]
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
```

## Code references

- peek: [src/router.py:507](../src/router.py#L507)
- decide branch: [src/router.py:1125](../src/router.py#L1125)
- T2 extractor: [src/content.py:332](../src/content.py#L332) (`extract_html_text`)
- T3 worker: [src/ingest/tier3.py](../src/ingest/tier3.py)
- Stage 2 push: [src/stage2/__main__.py:29](../src/stage2/__main__.py#L29)
