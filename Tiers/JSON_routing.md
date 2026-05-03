# `.json` routing

Configuration / data file. Routed by size like the text and code paths, but
with the smallest threshold (50 KB → T0) — config files this large are
typically generated dumps, not hand-written.

**`.json` is in `_DATA_EXTS_DEFAULT_OFF` and is filtered out at the walker unless `--include-data` is passed.** Real-world corpora often carry thousands of config dumps and dataset exports that bloat the index without being what users typically query.

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | `_CONSIDERED_EXTS` (allowed). Default-skipped (in `_DATA_EXTS_DEFAULT_OFF`) unless `--include-data`. |
| peek function | `_peek_text_file` ([src/router.py:213](../src/router.py#L213)) |
| decide branch | CONFIG_EXTS ([src/router.py:918](../src/router.py#L918)) |
| Threshold | `CONFIG_SIZE_T0_THRESHOLD = 50 KB` |
| Tier worker(s) | `tier1.run` (small) or `tier0.run` (large) |
| Stage 2 downstream | `parse_summary_file` → dense + sparse embed → upsert into `summaries` collection (1 point per file). |

## Identical paths

These extensions take the **same** code path: `.yaml`, `.yml`, `.toml`.

## Flowchart

```mermaid
flowchart TD

    A0["Walker checks _DATA_EXTS_DEFAULT_OFF"] --> A0Q{"--include-data passed?"}
    A0Q -- "no" --> Z0["filtered: data file<br/>default-skipped"]
    A0Q -- "yes" --> A
        A["File: example.json"] --> B{"In .gitignore /<br/>.nasignore /<br/>default-ignore?"}
    B -- "yes" --> Z1["filtered by walker"]
    B -- "no" --> C{"Manifest:<br/>same size +<br/>already processed?"}
    C -- "yes" --> Z2["SKIP: unchanged"]
    C -- "no" --> D["router.peek →<br/>_peek_text_file"]
    D --> E["Read first 10 KB<br/>UTF-8 decode<br/>peek_text up to 5 KB"]
    E --> F["compute_visual_score = 0<br/>compute_sensitivity_score<br/>resolve criticality"]
    F --> G["router.decide<br/>CONFIG_EXTS branch"]
    G --> H{"size_bytes ≥ 50 KB?"}
    H -- "yes (large)" --> T0["Route: T0"]
    H -- "no (small)" --> T1["Route: T1"]
    T0 --> W0["tier0.run<br/>head 2 KB preview"]
    T1 --> W1["tier1.run<br/>full body, 8000-char cap<br/>content_type: config"]
    W0 --> M["render_summary_markdown"]
    W1 --> M
    M --> P["Write SUMMARIES_DIR/<br/>&lt;sha256[:16]&gt;_t0.md<br/>or _t1.md"]
    P --> Q["manifest.mark_summarized<br/>+ mark_routed"]
    Q --> R["End of walk →<br/>Stage 2 push"]
    R --> S["parse_summary_file"]
    S --> T["embed_dense + embed_sparse"]
    T --> U["Qdrant upsert into<br/>'summaries' collection<br/>1 point per file"]
    U --> V["manifest.mark_ingested"]

    classDef skip fill:#ffcccc,stroke:#990000,color:#000
    class Z0,Z1,Z2 skip
```

## Code references

- Walker filter list: [src/ingest/walker.py:116](../src/ingest/walker.py#L116)
- `_DATA_EXTS_DEFAULT_OFF`: [src/ingest/walker.py:137](../src/ingest/walker.py#L137)
- peek: [src/router.py:213](../src/router.py#L213)
- decide branch: [src/router.py:918](../src/router.py#L918)
- T0 worker: [src/ingest/tier0.py](../src/ingest/tier0.py)
- T1 worker: [src/ingest/tier1.py](../src/ingest/tier1.py) (writes `content_type: config`)
- Stage 2 push: [src/stage2/__main__.py:29](../src/stage2/__main__.py#L29)
