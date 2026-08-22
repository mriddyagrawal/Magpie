# `.java` routing

Source-code file. Same shape as the text path but with a **larger size threshold**
(500 KB) — code files tend to be longer than prose files of equivalent semantic
density, and the body is what we want to embed verbatim for BM25 to catch
identifier strings (function names, class names, error codes).

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | `_CONSIDERED_EXTS` (allowed). Not in `_DATA_EXTS_DEFAULT_OFF`. |
| peek function | `_peek_text_file` ([src/router.py:213](../src/router.py#L213)) |
| decide branch | CODE_EXTS ([src/router.py:908](../src/router.py#L908)) |
| Threshold | `CODE_SIZE_T0_THRESHOLD = 500 KB` |
| Tier worker(s) | `tier1.run` (small) or `tier0.run` (large) |
| Stage 2 downstream | `parse_summary_file` → dense + sparse embed → upsert into `summaries` collection (1 point per file). |

## Identical paths

These extensions take the **same** code path: `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.go`, `.rs`, `.c`, `.cpp`, `.h`, `.hpp`, `.cs`, `.rb`, `.swift`, `.kt`, `.sh`, `.sql`.

## Flowchart

```mermaid
flowchart TD
    A["File: example.java"] --> B{"In .gitignore /<br/>.nasignore /<br/>default-ignore?"}
    B -- "yes" --> Z1["filtered by walker"]
    B -- "no" --> C{"Manifest:<br/>same size +<br/>already processed?"}
    C -- "yes" --> Z2["SKIP: unchanged"]
    C -- "no" --> D["router.peek →<br/>_peek_text_file"]
    D --> E["Read first 10 KB<br/>UTF-8 decode<br/>peek_text up to 5 KB<br/>extractable check"]
    E --> F["compute_visual_score = 0<br/>compute_sensitivity_score<br/>resolve criticality"]
    F --> G["router.decide<br/>CODE_EXTS branch"]
    G --> H{"size_bytes ≥ 500 KB?"}
    H -- "yes (large)" --> T0["Route: T0"]
    H -- "no (small)" --> T1["Route: T1"]
    T0 --> W0["tier0.run<br/>head 2 KB preview<br/>title: filename + KB<br/>content_type: text-large<br/>identifiers: filename + bytes"]
    T1 --> W1["tier1.run<br/>full body, 8000-char cap<br/>content_type: code<br/>keywords: filename, code"]
    W0 --> M["render_summary_markdown"]
    W1 --> M
    M --> P["Write SUMMARIES_DIR/<br/>&lt;sha256[:16]&gt;_t0.md<br/>or _t1.md"]
    P --> Q["manifest.mark_summarized<br/>+ mark_routed"]
    Q --> R["End of walk →<br/>Stage 2 push"]
    R --> S["parse_summary_file"]
    S --> T["embed_dense + embed_sparse<br/>(BM25 captures function /<br/>class names verbatim)"]
    T --> U["Qdrant upsert into<br/>'summaries' collection<br/>1 point per file<br/>id = md5(source_rel)"]
    U --> V["manifest.mark_ingested"]

    classDef skip fill:#ffcccc,stroke:#990000,color:#000
    class Z1,Z2 skip
```

## Code references

- Walker filter list: [src/ingest/walker.py:116](../src/ingest/walker.py#L116)
- peek: [src/router.py:213](../src/router.py#L213)
- decide branch: [src/router.py:908](../src/router.py#L908)
- T0 worker: [src/ingest/tier0.py](../src/ingest/tier0.py)
- T1 worker: [src/ingest/tier1.py](../src/ingest/tier1.py) (writes `content_type: code`)
- Stage 2 push: [src/stage2/__main__.py:29](../src/stage2/__main__.py#L29)
