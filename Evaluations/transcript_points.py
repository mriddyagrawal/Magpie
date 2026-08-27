"""Transcript index points (spike, 2026-08-26): give scanned documents'
vision transcripts a BM25-ONLY presence in the summaries collection.

Why: scanned files' summaries carry the prose gist but not the form
metadata (submission dates, fee amounts, confirmation numbers) — q40's
Duke supplement ranks >30 for its own question while its transcript
literally contains 'Submitted: 01/03/2023'. Transcript text is REAL
extracted content (unlike doc2query's 3B-generated questions, measured
noisy the same day), but to eliminate semantic-drift displacement the
points get a ZERO dense vector: they can only surface via the sparse
(BM25) prefetch on exact term matches, never via dense similarity.

A file matched by both its summary point and its transcript point gets
a small RRF agreement boost — desirable.

Reversible: --remove deletes every transcript-tagged point.

Usage (repo root, Qdrant up):
    uv run python Evaluations/transcript_points.py --index
    uv run python Evaluations/transcript_points.py --remove
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

CHUNK_CHARS = 2500
MAX_CHUNKS = 3  # forms/receipts are short; essays' prose gist is already indexed


def index() -> int:
    from qdrant_client.models import PointStruct, SparseVector

    from src.manifest import APP_DATA_DIR
    from src.stage2.db import COLLECTION_NAME, _point_id, get_qdrant_client
    from src.stage2.embeddings import embed_dense, embed_sparse

    tdir = Path(APP_DATA_DIR) / "transcripts"
    files = sorted(tdir.glob("*.md"))
    if not files:
        print(f"no transcripts under {tdir}")
        return 1

    dense_dim = len(embed_dense(["probe"])[0])
    zero_dense = [0.0] * dense_dim

    client = get_qdrant_client()
    points = []
    skipped = 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^Source: (.+)$", text, re.MULTILINE)
        if not m:
            skipped += 1
            continue
        source_path = m.group(1).strip()
        body = text[m.end():].strip()
        chunks = [body[i:i + CHUNK_CHARS]
                  for i in range(0, min(len(body), CHUNK_CHARS * MAX_CHUNKS),
                                 CHUNK_CHARS)]
        chunks = [c for c in chunks if len(c) > 100]
        if not chunks:
            skipped += 1
            continue
        sparse = embed_sparse(chunks)
        for j, (chunk, (si, sv)) in enumerate(zip(chunks, sparse)):
            points.append(PointStruct(
                id=_point_id(f"{source_path}::transcript{j}"),
                vector={"dense": zero_dense,
                        "sparse": SparseVector(indices=si, values=sv)},
                payload={"source_path": source_path, "transcript": True},
            ))
    for start in range(0, len(points), 256):
        client.upsert(collection_name=COLLECTION_NAME,
                      points=points[start:start + 256])
    print(f"upserted {len(points)} transcript points from "
          f"{len(files) - skipped} transcripts ({skipped} skipped)")
    return 0


def remove() -> int:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from src.stage2.db import COLLECTION_NAME, get_qdrant_client

    client = get_qdrant_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(key="transcript", match=MatchValue(value=True))]),
    )
    print("all transcript-tagged points deleted")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()
    if args.remove:
        return remove()
    if args.index:
        return index()
    ap.error("pick --index or --remove")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
