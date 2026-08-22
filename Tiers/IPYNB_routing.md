# `.ipynb` routing

Jupyter notebook. The peek parses the JSON, counts cells, and extracts cell
sources (skipping outputs). Once parsed, notebooks behave like text-native
documents — T2 by default, T3+T2 if critical.

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | `_CONSIDERED_EXTS` (allowed). |
| peek function | `_peek_ipynb` (parse JSON + iterate cells) ([src/router.py:541](../src/router.py#L541)) |
| decide branch | IPYNB_EXTS ([src/router.py:1139](../src/router.py#L1139)) |
| Threshold | n_cells > 0; else SKIP |
| Tier worker(s) | `tier2.run` (default) / `tier3.run_async` (critical adds T3) |
| Stage 2 downstream | parse → embed → upsert into `summaries` collection (1 point per file). |

## Identical paths

_(none — only `.ipynb` takes this path)_

## Flowchart

```mermaid
flowchart TD
    A["File: example.ipynb"] --> B{"In ignore rules?"}
    B -- "yes" --> Z1["filtered"]
    B -- "no" --> C{"Manifest unchanged?"}
    C -- "yes" --> Z2["SKIP: unchanged"]
    C -- "no" --> D["router.peek →<br/>_peek_ipynb"]
    D --> E["json.loads(file)<br/>iterate nb.cells<br/>collect first cell sources<br/>up to 5 KB peek_text"]
    E --> F["scores + criticality"]
    F --> G["router.decide<br/>IPYNB_EXTS branch"]
    G --> H{"peek_error?"}
    H -- "yes" --> Z3["SKIP: ipynb unreadable"]
    H -- "no" --> I{"page_count (cells) == 0?"}
    I -- "yes" --> Z4["SKIP: ipynb has no cells"]
    I -- "no" --> J{"criticality == critical?"}
    J -- "yes" --> R32["Route: T3 + T2"]
    J -- "no" --> R2["Route: T2"]

    R32 --> W3["tier3.run_async<br/>(walker primary = T3)"]
    R2 --> W2["tier2.run"]

    W3 --> D1["content-hash dedup<br/>build_content_blocks:<br/>extract_ipynb_text<br/>cap 120K chars<br/>'Content type: ipynb' block"]
    D1 --> D2["LLM → FileSummary"]
    D2 --> D3["render_markdown<br/>→ &lt;hash16&gt;_t3.md"]

    W2 --> X1["extract_ipynb_text<br/>per cell:<br/>'# Cell N (type)' header<br/>+ source<br/>(outputs SKIPPED)<br/>cap 8000 chars"]
    X1 --> X2["render_summary_markdown<br/>→ &lt;hash16&gt;_t2.md"]

    D3 --> SP["End of walk → Stage 2 push"]
    X2 --> SP
    SP --> SP1["parse_summary_file"]
    SP1 --> SP2["embed_dense + embed_sparse"]
    SP2 --> SP3["Qdrant upsert into<br/>'summaries' collection<br/>1 point per file"]
    SP3 --> SP4["manifest.mark_ingested"]

    classDef skip fill:#ffcccc,stroke:#990000,color:#000
    class Z1,Z2,Z3,Z4 skip
    classDef llm fill:#cce5ff,stroke:#0044aa,color:#000
    class D2,D3 llm
```

## Code references

- peek: [src/router.py:541](../src/router.py#L541)
- decide branch: [src/router.py:1139](../src/router.py#L1139)
- T2 extractor: [src/content.py:361](../src/content.py#L361) (`extract_ipynb_text`)
- T3 worker: [src/ingest/tier3.py](../src/ingest/tier3.py)
- Stage 2 push: [src/stage2/__main__.py:29](../src/stage2/__main__.py#L29)
