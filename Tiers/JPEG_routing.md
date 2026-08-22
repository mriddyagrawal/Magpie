# `.jpeg` routing

Standalone image. Three end states:

1. **Thumbnail skip**: bytes < 50 KB AND both dims < 600 px → skipped (UI assets).
2. **T4 (default)**: ColPali on the single rendered image, with cost gates and
   T4 budget cap. **T3 + T4** if criticality is critical.
3. **T3 fallback**: when ColPali is disabled (`colpali: never`) or the budget /
   per-file cost gate denies T4.

T3 for an image sends the raw bytes to a vision-capable LLM as `BinaryContent`
(no text extract is possible for raw images).

The `_asset_library_folders` rule is a structural pre-filter: a folder
containing **≥ 15 images and 0 documents** is treated as an asset library and
**all** its images are dropped wholesale before reaching the router.

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | `_CONSIDERED_EXTS` (allowed). Asset-library structural filter applied. |
| peek function | `_peek_image` via PIL ([src/router.py:579](../src/router.py#L579)) |
| decide branch | IMAGE_EXTS ([src/router.py:1156](../src/router.py#L1156)) |
| Thresholds | thumbnail: bytes < 50 KB AND dims < 600 × 600. T4 cost gates: ≤ 50 MB/file, ≤ 30s GPU / 10s CPU/file, corpus-budget. |
| Tier worker(s) | `tier4.run` (default) / `tier3.run_async` (when T4 gated off or critical) |
| Stage 2 downstream | T3 → summary upsert. T4 → patches in `fast_tier`. |

## Identical paths

These extensions take the **same** code path: `.png`, `.jpg`, `.webp`, `.gif`.

## Flowchart

```mermaid
flowchart TD
    A["File: example.jpeg"] --> AL{"Folder has ≥ 15 images<br/>AND 0 documents?<br/>(asset library)"}
    AL -- "yes" --> Z0["dropped wholesale<br/>(asset_library_skipped)"]
    AL -- "no" --> B{"In ignore rules?"}
    B -- "yes" --> Z1["filtered"]
    B -- "no" --> C{"Manifest unchanged?"}
    C -- "yes" --> Z2["SKIP: unchanged"]
    C -- "no" --> D["router.peek →<br/>_peek_image via PIL"]
    D --> E["Image.open → image_dims (w, h)"]
    E --> F["compute_visual_score<br/>(+4 if w,h ≥ 600;<br/>+1 for extreme aspect)<br/>compute_sensitivity_score = 0<br/>(no peek_text for image)<br/>estimate_t4_cost"]
    F --> G["router.decide<br/>IMAGE_EXTS branch"]
    G --> H{"size < 50 KB AND<br/>both dims < 600 px?"}
    H -- "yes" --> Z3["SKIP: thumbnail<br/>(bytes + dims both small)"]
    H -- "no" --> I{"colpali = never?"}
    I -- "yes" --> R3a["Route: T3<br/>(vision LLM)"]
    I -- "no" --> J{"T4 cost gates fit?<br/>t4_mb ≤ 50<br/>AND t4_s ≤ 30 (GPU) / 10 (CPU)<br/>AND budget OK"}
    J -- "no" --> R3b["Route: T3 fallback"]
    J -- "yes" --> K{"criticality == critical?"}
    K -- "yes" --> R34["Route: T3 + T4"]
    K -- "no" --> R4["Route: T4"]

    R3a --> W3
    R3b --> W3
    R34 --> W3["tier3.run_async<br/>(walker primary = T3)"]
    R4 --> W4["tier4.run"]

    W3 --> D1["content-hash dedup<br/>build_content_blocks:<br/>BinaryContent(<br/> data=path.read_bytes(),<br/> media_type=image/...)"]
    D1 --> D2["LLM call (vision-required)<br/>FileSummary schema"]
    D2 --> D3["render_markdown<br/>→ &lt;hash16&gt;_t3.md"]

    W4 --> F1["src.stage1_fast.index.index_file<br/>PIL.Image.open(path).convert('RGB')<br/>1 page"]
    F1 --> F2["ColPali multi-vector encode<br/>~700 patches<br/>int8-quantized<br/>POOL_FACTOR = 1"]
    F2 --> F3["Qdrant upsert into<br/>'fast_tier' collection<br/>multivector point"]
    F3 --> F4["manifest.fast_indexed_at +<br/>fast_pages = 1"]

    D3 --> SP["End of walk → Stage 2 push"]
    SP --> SP1["parse_summary_file"]
    SP1 --> SP2["embed_dense + embed_sparse"]
    SP2 --> SP3["Qdrant upsert into<br/>'summaries' collection<br/>1 point per file"]
    SP3 --> SP4["manifest.mark_ingested"]

    F4 --> F5["fast_tier already populated;<br/>Stage 2 sees<br/>summary_file=None +<br/>fast_indexed_at=set<br/>→ marks ingested,<br/>no new upsert"]

    classDef skip fill:#ffcccc,stroke:#990000,color:#000
    class Z0,Z1,Z2,Z3 skip
    classDef llm fill:#cce5ff,stroke:#0044aa,color:#000
    class D2,D3 llm
    classDef colpali fill:#ddeedd,stroke:#226633,color:#000
    class F1,F2,F3 colpali
```

## Code references

- Asset-library filter: [src/ingest/walker.py:175](../src/ingest/walker.py#L175)
- peek: [src/router.py:579](../src/router.py#L579)
- decide branch: [src/router.py:1156](../src/router.py#L1156)
- T3 worker: [src/ingest/tier3.py](../src/ingest/tier3.py)
- T3 image content block: [src/content.py:444](../src/content.py#L444)
- T4 worker: [src/ingest/tier4.py](../src/ingest/tier4.py) → [src/stage1_fast/index.py](../src/stage1_fast/index.py)
- Stage 2 push: [src/stage2/__main__.py:29](../src/stage2/__main__.py#L29)
