# `.xlsx` routing

Excel spreadsheet. The decision splits on **size**: spreadsheets > 10 MB go to
T0 (preview only), the rest go to T2 (extract every sheet's cells via
openpyxl). Critical-tagged files add a T3 sibling.

`.xlsx` and `.xlsm` share this path identically — XLSM is just XLSX with
macros, irrelevant to extraction.

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | `_CONSIDERED_EXTS` (allowed). |
| peek function | `_peek_xlsx` via openpyxl ([src/router.py:392](../src/router.py#L392)) |
| decide branch | XLSX_EXTS ([src/router.py:1059](../src/router.py#L1059)) |
| Threshold | size > 10 MB → T0; else T2 (or T3+T2 if critical) |
| Tier worker(s) | `tier0.run` / `tier2.run` / `tier3.run_async` |
| Stage 2 downstream | parse → embed → upsert into `summaries` collection (1 point per file). |

## Identical paths

These extensions take the **same** code path: `.xlsm`.

## Flowchart

```mermaid
flowchart TD
    A["File: example.xlsx"] --> B{"In ignore rules?"}
    B -- "yes" --> Z1["filtered"]
    B -- "no" --> C{"Manifest unchanged?"}
    C -- "yes" --> Z2["SKIP: unchanged"]
    C -- "no" --> D["router.peek →<br/>_peek_xlsx via openpyxl"]
    D --> E["Count sheets (n_sheets)<br/>Concat first cells per row<br/>up to 5 KB peek_text"]
    E --> F["scores + criticality"]
    F --> G["router.decide<br/>XLSX_EXTS branch"]
    G --> H{"peek_error?"}
    H -- "yes" --> Z3["SKIP: xlsx unreadable"]
    H -- "no" --> I{"size_bytes > 10 MB?"}
    I -- "yes (huge)" --> R0["Route: T0<br/>(sample-summary only)"]
    I -- "no" --> J{"criticality == critical?"}
    J -- "yes" --> R32["Route: T3 + T2"]
    J -- "no" --> R2["Route: T2"]

    R0 --> W0["tier0.run<br/>(treats .xlsx as 'text-large':<br/>2 KB head preview,<br/>but openpyxl is NOT used here —<br/>just byte-level head)"]
    R32 --> W3["tier3.run_async<br/>(walker primary = T3)"]
    R2 --> W2["tier2.run"]

    W3 --> D1["content-hash dedup<br/>build_content_blocks:<br/>extract_xlsx_text<br/>'Content type: xlsx' block<br/>cap 120K chars"]
    D1 --> D2["LLM → FileSummary"]
    D2 --> D3["render_markdown<br/>→ &lt;hash16&gt;_t3.md"]

    W2 --> X1["extract_xlsx_text<br/>iterate every sheet:<br/>'## Sheet: name'<br/>+ each row joined as CSV<br/>cap 8000 chars"]
    X1 --> X2["render_summary_markdown<br/>→ &lt;hash16&gt;_t2.md"]

    W0 --> Y1["render_summary_markdown<br/>→ &lt;hash16&gt;_t0.md"]

    D3 --> SP["End of walk → Stage 2 push"]
    X2 --> SP
    Y1 --> SP
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

- peek: [src/router.py:392](../src/router.py#L392)
- decide branch: [src/router.py:1059](../src/router.py#L1059)
- T2 extractor: [src/content.py:395](../src/content.py#L395) (`extract_xlsx_text`)
- T3 worker: [src/ingest/tier3.py](../src/ingest/tier3.py)
- Stage 2 push: [src/stage2/__main__.py:29](../src/stage2/__main__.py#L29)
