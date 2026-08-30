"""Index a folder of transcripts into the summaries collection as real text points.

The 2026-08-26 `transcript_points.py` spike gave transcripts a BM25-only
presence (zero dense vector) to avoid displacing summaries. For the ViDoRe
retrieval comparison the text tier must be a fair opponent to ColPali, so
this variant embeds every transcript chunk with the same dense + sparse
models the summaries use. Payload matches what `_search_summary_tier`
reads (`source_path`, `chunk_index`); `transcript: True` marks the points
for `--remove`.

    MAGPIE_DATA_DIR=... QDRANT_CLUSTER_ENDPOINT=http://127.0.0.1:6481 \\
    MAGPIE_TRANSCRIPTS_DIR=/mnt/astavaknew/magpie-transcripts/ocr-vidore-infovqa \\
        uv run python Evaluations/vidore_text_index.py --index
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
MAX_CHUNKS = 4


def index() -> int:
    from qdrant_client.models import PointStruct, SparseVector

    from src.content import transcripts_dir
    from src.stage2.db import COLLECTION_NAME, _point_id, create_collection, get_qdrant_client
    from src.stage2.embeddings import embed_dense, embed_sparse

    files = sorted(transcripts_dir().glob("*.md"))
    if not files:
        print(f"no transcripts under {transcripts_dir()}")
        return 1
    create_collection()
    client = get_qdrant_client()
    texts, keys, payloads = [], [], []
    skipped = 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^Source: (.+)$", text, re.MULTILINE)
        if not m or "## Page" not in text:
            skipped += 1
            continue
        source_path = m.group(1).strip()
        body = text.split("## Page", 1)[1]
        chunks = [body[i:i + CHUNK_CHARS] for i in range(0, min(len(body), CHUNK_CHARS * MAX_CHUNKS), CHUNK_CHARS)]
        chunks = [c for c in chunks if len(c.strip()) > 20]
        if not chunks:
            skipped += 1
            continue
        for j, c in enumerate(chunks):
            texts.append(c)
            keys.append(f"{source_path}::transcript{j}")
            payloads.append({"source_path": source_path, "chunk_index": j, "transcript": True})
    n = 0
    for start in range(0, len(texts), 64):
        batch = texts[start:start + 64]
        dense = embed_dense(batch)
        sparse = embed_sparse(batch)
        points = [
            PointStruct(id=_point_id(keys[start + i]),
                        vector={"dense": dense[i], "sparse": SparseVector(indices=sparse[i][0], values=sparse[i][1])},
                        payload=payloads[start + i])
            for i in range(len(batch))
        ]
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        n += len(points)
        print(f"  {n}/{len(texts)} points", flush=True)
    print(f"upserted {n} transcript points from {len(files) - skipped} transcripts ({skipped} skipped)")
    return 0


def remove() -> int:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from src.stage2.db import COLLECTION_NAME, get_qdrant_client

    get_qdrant_client().delete(collection_name=COLLECTION_NAME,
                               points_selector=Filter(must=[FieldCondition(key="transcript", match=MatchValue(value=True))]))
    print("transcript points deleted")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args()
    return remove() if a.remove else index()


if __name__ == "__main__":
    raise SystemExit(main())
