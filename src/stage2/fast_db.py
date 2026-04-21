"""Qdrant fast-tier collection: per-page multi-vector points via ColPali.

This is the second collection in the two-tier design (see
`Plans/IO - Colpali.md`). Each point represents one page of one file:

    point.id     = md5("<source_path>::page:<N>") as UUID
    point.vector = float16/float32 tensor of shape (n_patches, 128)
    point.payload = {source_path, page_num}

The collection uses Qdrant's native multi-vector support with `MaxSim`
comparator (the ColBERT-style late-interaction scoring) and int8 scalar
quantization to keep storage around ~130 KB/page.

Stable point IDs let us upsert-to-overwrite on re-index, and `delete_path`
cleans up every page of a file at once when the source is deleted.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Sequence

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    MultiVectorComparator,
    MultiVectorConfig,
    PayloadSchemaType,
    PointStruct,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    VectorParams,
)

from src.stage2.db import get_qdrant_client

FAST_COLLECTION_NAME = "fast_tier"

# Late-interaction embedding dim. Both ColQwen2.5 and ColSmol project to
# 128-dim patch vectors; the patch count differs (1030 vs ~1139) but Qdrant's
# multi-vector is count-agnostic per point.
FAST_VECTOR_DIM = 128

# int8 scalar quantization: 4x compression vs float32 with ~1.5% recall loss.
# `always_ram=False` lets Qdrant decide where to keep the quantized blocks —
# essential for local embedded mode on a resource-constrained laptop (1 GB
# RAM tier, etc.). Cloud won't be hurt by the change either.
_QUANT_CONFIG = ScalarQuantization(
    scalar=ScalarQuantizationConfig(
        type=ScalarType.INT8,
        always_ram=False,
    )
)

# Keep the HNSW graph on disk rather than in RAM. Costs a few ms per query
# (mmap reads) but survives 1 GB RAM budgets. Cloud can also tolerate this
# fine — the OS page cache keeps hot graph segments resident anyway.
_HNSW_CONFIG = HnswConfigDiff(on_disk=True)


def _page_point_id(source_path: str, page_num: int) -> str:
    """Deterministic UUID for a (path, page) pair.

    Matches `db._point_id` formatting: MD5 hex laid out as 8-4-4-4-12. Stable
    across re-indexes, so upserts overwrite cleanly.
    """
    h = hashlib.md5(f"{source_path}::page:{page_num}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def ensure_fast_collection(*, recreate: bool = False) -> None:
    """Create the fast_tier collection if it doesn't exist.

    Also ensures a payload index on `source_path` — required for the
    `delete_path` filter-based delete to work (Qdrant rejects filters on
    non-indexed fields). Idempotent: re-running on an existing collection
    adds the index if it's missing.
    """
    client = get_qdrant_client()

    if recreate and client.collection_exists(FAST_COLLECTION_NAME):
        client.delete_collection(FAST_COLLECTION_NAME)
    if not client.collection_exists(FAST_COLLECTION_NAME):
        client.create_collection(
            collection_name=FAST_COLLECTION_NAME,
            vectors_config=VectorParams(
                size=FAST_VECTOR_DIM,
                distance=Distance.COSINE,
                multivector_config=MultiVectorConfig(
                    comparator=MultiVectorComparator.MAX_SIM,
                ),
                quantization_config=_QUANT_CONFIG,
                on_disk=True,
                hnsw_config=_HNSW_CONFIG,
            ),
        )

    # Always ensure the payload index exists (cheap no-op if already present).
    try:
        client.create_payload_index(
            collection_name=FAST_COLLECTION_NAME,
            field_name="source_path",
            field_schema=PayloadSchemaType.KEYWORD,
        )
    except Exception:  # pylint: disable=broad-except
        # Some Qdrant versions/clouds raise on "already exists" rather than
        # returning a no-op — ignoring is safe here.
        pass


def upsert_page(
    source_path: str,
    page_num: int,
    page_vectors: Sequence[Sequence[float]],
) -> None:
    """Upsert a single page. `page_vectors` must be a 2D list/array of
    shape `(n_patches, FAST_VECTOR_DIM)`. Caller is responsible for moving
    off-device + converting to list before calling.
    """
    client = get_qdrant_client()
    client.upsert(
        collection_name=FAST_COLLECTION_NAME,
        points=[
            PointStruct(
                id=_page_point_id(source_path, page_num),
                vector=list(page_vectors),  # pyright: ignore[reportArgumentType]
                payload={
                    "source_path": source_path,
                    "page_num": page_num,
                },
            )
        ],
    )


def upsert_pages_batch(
    pages: list[tuple[str, int, Sequence[Sequence[float]]]],
) -> int:
    """Batch upsert. `pages` items are `(source_path, page_num, vectors)`."""
    if not pages:
        return 0
    client = get_qdrant_client()
    points = [
        PointStruct(
            id=_page_point_id(src, pg),
            vector=list(vecs),  # pyright: ignore[reportArgumentType]
            payload={"source_path": src, "page_num": pg},
        )
        for src, pg, vecs in pages
    ]
    client.upsert(collection_name=FAST_COLLECTION_NAME, points=points)
    return len(points)


def search(
    query_vectors: Sequence[Sequence[float]],
    limit: int = 10,
) -> list[tuple[str, int, float]]:
    """MaxSim search. Returns `[(source_path, page_num, score), ...]`.

    `query_vectors` is the multi-vector output from `encode_queries` —
    shape `(n_query_tokens, FAST_VECTOR_DIM)`.
    """
    client = get_qdrant_client()
    hits = client.query_points(
        collection_name=FAST_COLLECTION_NAME,
        query=list(query_vectors),  # pyright: ignore[reportArgumentType]
        limit=limit,
        with_payload=True,
    ).points
    return [
        (h.payload["source_path"], h.payload["page_num"], float(h.score))
        for h in hits
    ]


def delete_path(source_path: str) -> int:
    """Remove every page point for a given source file.

    Used during sync when a file has been deleted on disk or re-indexed.
    Returns the count of points removed (best-effort — Qdrant doesn't always
    report the exact number).
    """
    client = get_qdrant_client()
    result = client.delete(
        collection_name=FAST_COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="source_path",
                    match=MatchValue(value=source_path),
                )
            ]
        ),
    )
    # Qdrant returns an UpdateResult; exact-count varies by provider.
    return getattr(result, "status", 0) or 0


def get_indexed_paths() -> set[str]:
    """Return the set of distinct source_paths currently in the fast tier."""
    client = get_qdrant_client()
    paths: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=FAST_COLLECTION_NAME,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            src = p.payload.get("source_path") if p.payload else None
            if src:
                paths.add(src)
        if offset is None:
            break
    return paths


# ---------------------------------------------------------------------------
# Smoke test: `uv run python -m src.stage2.fast_db <pdf-or-image>`
# Renders, encodes, upserts, queries. Prints the round-trip result.
# ---------------------------------------------------------------------------


def _smoke_test(path_arg: str) -> None:
    from dotenv import load_dotenv

    load_dotenv()

    path = Path(path_arg)
    if not path.is_file():
        sys.exit(f"error: no such file: {path}")

    from src.stage1_fast.model import encode_images, encode_queries

    print(f"ensuring collection '{FAST_COLLECTION_NAME}' exists...")
    ensure_fast_collection()

    # Render one page from the file.
    if path.suffix.lower() == ".pdf":
        import pymupdf
        from PIL import Image

        doc = pymupdf.open(path)
        pix = doc[0].get_pixmap(dpi=150)
        images = [Image.frombytes("RGB", (pix.width, pix.height), pix.samples)]
        doc.close()
    else:
        from PIL import Image
        images = [Image.open(path).convert("RGB")]

    print("encoding page...")
    tensor = encode_images(images)  # (1, n_patches, 128)
    page_vecs = tensor[0].float().cpu().tolist()
    print(f"  shape: ({len(page_vecs)}, {len(page_vecs[0])})")

    print("upserting...")
    upsert_page(str(path), page_num=0, page_vectors=page_vecs)

    print("querying with 'receipt total amount'...")
    q_tensor = encode_queries(["receipt total amount"])  # (1, n_tokens, 128)
    q_vecs = q_tensor[0].float().cpu().tolist()
    hits = search(q_vecs, limit=3)
    for src, pg, score in hits:
        print(f"  [{score:.3f}]  {src}  page={pg}")

    print("done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m src.stage2.fast_db <pdf-or-image>")
    _smoke_test(sys.argv[1])
