import csv
import hashlib
from pathlib import Path
from typing import Generator

from qdrant_client.models import PointStruct, SparseVector
from tqdm import tqdm

from src.stage2.db import _point_id, get_qdrant_client, COLLECTION_NAME
from src.stage2.embeddings import embed_dense, embed_sparse

BATCH_SIZE = 64

def _row_point_id(source_path: str, row_idx: int) -> str:
    """Deterministic UUID for a specific row in a CSV."""
    h = hashlib.md5(f"{source_path}::row:{row_idx}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

def stream_csv_rows(path: Path) -> Generator[str, None, None]:
    """Yield a string representation of each row for embedding."""
    with path.open(encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        for row in reader:
            # Create a "sentence" out of the row: "Key: Value, Key: Value..."
            yield " | ".join(f"{k}: {v}" for k, v in row.items() if v)

def ingest_csv_rows(path: Path, source_rel: str) -> int:
    """Break a CSV into rows and push each as a point to Qdrant."""
    client = get_qdrant_client()
    rows = list(stream_csv_rows(path))
    total = 0
    
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        dense_vectors = embed_dense(batch)
        sparse_vectors = embed_sparse(batch)
        
        points = []
        for j, (text, dense_vec, (sparse_idx, sparse_val)) in enumerate(zip(batch, dense_vectors, sparse_vectors)):
            row_idx = i + j
            points.append(
                PointStruct(
                    id=_row_point_id(source_rel, row_idx),
                    vector={
                        "dense": dense_vec,
                        "sparse": SparseVector(indices=sparse_idx, values=sparse_val),
                    },
                    payload={
                        "summary": text, # In row-mode, the "summary" is the row data itself
                        "source_path": source_rel,
                        "row_index": row_idx
                    },
                )
            )
        
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        total += len(points)
        
    return total
