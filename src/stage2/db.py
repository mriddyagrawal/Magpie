"""Qdrant Cloud client setup and collection operations."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Modifier,
    NamedSparseVector,
    NamedVector,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from src.manifest import APP_DATA_DIR
from src.stage2.embeddings import DENSE_VECTOR_SIZE, embed_dense, embed_sparse
from src.stage2.parser import ParsedSummary

COLLECTION_NAME = "summaries"

_DEFAULT_LOCAL_PATH = APP_DATA_DIR / "qdrant_data"

_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """Return a cached Qdrant client.

    Selected by `QDRANT_PROVIDER` env var (default: ``cloud``):

    - ``cloud``   — Qdrant server reachable over HTTP(S) — either Qdrant Cloud
                    (paid, remote) or a self-hosted server you spawned locally
                    (e.g. via `just qdrant-up`, Docker, or systemd).
                    Required: ``QDRANT_CLUSTER_ENDPOINT``.
                    Optional: ``QDRANT_API_KEY`` — required for Cloud, ignored
                    for self-hosted-localhost (auth is off by default there).
    - ``local``   — embedded Python Qdrant shim persisted to a SQLite DB. No
                    server, no network. Directory from ``QDRANT_LOCAL_PATH``
                    (default: ``./qdrant_data``). NOTE: this Python library
                    silently drops every advanced feature — quantization, fp16,
                    binary, snapshots — because it is not the real Rust server.
                    Use ``cloud`` mode pointing at ``http://localhost:6333``
                    when storage compression matters. See backlog E4.
    """
    global _client
    if _client is not None:
        return _client

    provider = os.environ.get("QDRANT_PROVIDER", "cloud").strip().lower()

    if provider == "local":
        path = Path(os.environ.get("QDRANT_LOCAL_PATH") or _DEFAULT_LOCAL_PATH)
        if not path.is_absolute():
            path = _REPO_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        _client = QdrantClient(path=str(path))
        return _client

    if provider != "cloud":
        sys.exit(
            f"error: QDRANT_PROVIDER={provider!r} is unknown. "
            f"Valid values: cloud, local."
        )

    url = os.environ.get("QDRANT_CLUSTER_ENDPOINT")
    if not url:
        sys.exit(
            "error: QDRANT_CLUSTER_ENDPOINT must be set in .env "
            "(or set QDRANT_PROVIDER=local to use the embedded Python shim)."
        )

    # API key is required for Qdrant Cloud (anything not on a private host) but
    # optional for a self-hosted server reachable on localhost — those default
    # to no auth. Treat empty/whitespace as "no auth" for the localhost case.
    api_key = os.environ.get("QDRANT_API_KEY", "").strip() or None
    if api_key is None and not _is_localhost_url(url):
        sys.exit(
            f"error: QDRANT_API_KEY must be set for non-local QDRANT_CLUSTER_ENDPOINT "
            f"(got {url!r}). Set the key, or point at http://localhost:6333."
        )

    # The qdrant-client default timeout (5s) is too tight for large
    # multi-vector batches — ColPali pages are ~200 KB each int8-quantized,
    # so a 32-page batch is ~6 MB plus indexing time. On a busy local server
    # mid-ingest this can occasionally spike past 5s. 60s is generous but
    # only blocks when Qdrant is genuinely slow. Override via env var if
    # your server / network needs more.
    timeout_s = int(os.environ.get("QDRANT_TIMEOUT_S", "60"))
    _client = QdrantClient(url=url, api_key=api_key, timeout=timeout_s)
    return _client


_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _upsert_with_retry(
    client: QdrantClient,
    collection_name: str,
    points: list,
    *,
    max_attempts: int = 3,
) -> None:
    """Upsert with retry on transient timeouts.

    A single timeout shouldn't kill a 99k-file ingest. We retry up to
    `max_attempts` times with exponential backoff (1s, 2s, 4s) on the
    qdrant-client's `ResponseHandlingException` (which wraps `TimeoutError`,
    connection errors, etc.). Other exceptions propagate immediately —
    those usually mean a real problem (validation, dim mismatch, etc.).
    """
    import time
    from qdrant_client.http.exceptions import ResponseHandlingException

    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            client.upsert(collection_name=collection_name, points=points)
            return
        except ResponseHandlingException as e:
            last_err = e
            if attempt == max_attempts:
                raise
            wait = 2 ** (attempt - 1)
            from tqdm import tqdm
            tqdm.write(
                f"  qdrant {type(e.source).__name__ if hasattr(e, 'source') else 'timeout'} "
                f"on upsert (attempt {attempt}/{max_attempts}); retrying in {wait}s"
            )
            time.sleep(wait)
    if last_err is not None:
        raise last_err


def _is_localhost_url(url: str) -> bool:
    """True if `url`'s host resolves to the loopback (auth optional there)."""
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOCALHOST_HOSTS


class DenseDimMismatchError(RuntimeError):
    """Raised when the configured embedding model's dimension differs from
    the dimension stored in the existing Qdrant collection.

    This is a silent-corruption class of bug — if you swap the embedding model
    (e.g., MiniLM-384 → E5-base-768) and try to query an index built with the
    old model, every search either errors with a cryptic Qdrant message OR,
    worse, silently returns garbage when the client truncates/zero-pads
    vectors to fit. The fix is to fail loudly with a re-index instruction.
    """

    def __init__(self, expected: int, found: int, collection: str) -> None:
        super().__init__(
            f"dense vector dim mismatch in collection {collection!r}: "
            f"current embedding model produces {expected}-d vectors, but the "
            f"existing collection stores {found}-d. The dense model was "
            f"changed; the index is incompatible. Run "
            f"`python -m src.stage2 ingest --force` to drop and recreate "
            f"the collection with the new model."
        )
        self.expected = expected
        self.found = found
        self.collection = collection


def assert_dense_dim_match(
    client: QdrantClient | None = None,
    collection: str = COLLECTION_NAME,
) -> None:
    """Verify the stored collection's dense dim matches `DENSE_VECTOR_SIZE`.

    No-op when the collection doesn't exist yet (first run); the upcoming
    `create_collection` call will use the right dim. When the collection DOES
    exist, mismatch raises `DenseDimMismatchError` with a clear remediation.

    `client` is optional; when omitted the cached client from
    `get_qdrant_client()` is used. Callers that already have a client should
    pass it through so test mocks aren't bypassed (and so we don't construct
    a second client just for the dim check).
    """
    if client is None:
        client = get_qdrant_client()
    if not client.collection_exists(collection):
        return
    info = client.get_collection(collection)
    # Multi-named-vectors layout: vectors is a dict keyed by name.
    vectors = info.config.params.vectors
    if isinstance(vectors, dict):
        dense_cfg = vectors.get("dense")
    else:
        dense_cfg = vectors  # single-vector legacy
    if dense_cfg is None:
        return  # collection has no dense vectors at all; nothing to check
    found_size = getattr(dense_cfg, "size", None)
    # Only raise when we have a CONCRETE integer size that disagrees. Anything
    # else (None, MagicMock, missing attribute) → no-op. Defensive against
    # collection configs we don't fully understand and against test mocks
    # that don't provide a real config shape.
    if not isinstance(found_size, int) or found_size == DENSE_VECTOR_SIZE:
        return
    raise DenseDimMismatchError(
        expected=DENSE_VECTOR_SIZE, found=found_size, collection=collection
    )


def create_collection(*, recreate: bool = False) -> None:
    """Create the summaries collection with dense + sparse vector config.

    If recreate is True, drops and recreates the collection. Otherwise asserts
    that any existing collection's dense dim matches the current model — if
    it doesn't, raises `DenseDimMismatchError` rather than letting cryptic
    Qdrant errors leak through downstream upsert / search.
    """
    client = get_qdrant_client()

    if recreate:
        client.delete_collection(COLLECTION_NAME)
    elif client.collection_exists(COLLECTION_NAME):
        # Existing collection: enforce dim match before returning. Silent
        # mismatch would corrupt every subsequent upsert / search.
        assert_dense_dim_match(client, COLLECTION_NAME)
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": VectorParams(
                size=DENSE_VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(
                index=SparseIndexParams(on_disk=False),
                modifier=Modifier.IDF,
            ),
        },
    )


def _point_id(key: str) -> str:
    """Deterministic point ID from a string key, formatted as a dashed UUID.

    Callers pass the **source path** (repo-relative), not the summary file name.
    Source paths are stable across re-summarizations; summary filenames change
    (the filename is the content digest). A stable point ID means Qdrant
    upsert cleanly overwrites in place on content change instead of leaking
    an orphan point at the old digest.

    We emit the MD5 as a dashed UUID (8-4-4-4-12) because that's how Qdrant
    canonicalizes IDs it stores; returning the dashed form here keeps
    `_point_id(...)` and `str(scrolled_point.id)` comparable in set math.
    """
    h = hashlib.md5(key.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _build_embedding_text(s: ParsedSummary) -> str:
    """Combine fields into a single string for both dense + BM25 embedding.

    Includes key_entities and identifiers so BM25 can match exact tokens
    (order numbers, dates, product names) that dense embeddings tend to wash out.
    """
    parts = [s.title, s.summary]
    if s.keywords:
        parts.append(", ".join(s.keywords))
    if s.key_entities:
        parts.append(", ".join(s.key_entities))
    if s.identifiers:
        parts.append(", ".join(s.identifiers))
    return " ".join(parts)


BATCH_SIZE = 32


def upsert_summaries(
    summaries: list[ParsedSummary],
    *,
    on_batch_complete=None,
    verbose: bool = False,
) -> int:
    """Embed and upsert parsed summaries into Qdrant in batches with progress.

    Returns the number of points upserted.

    `on_batch_complete(indices: list[int])` is called after each successful
    batch upsert with the indices into `summaries` that were just persisted
    to Qdrant. Used by callers to mark per-row progress (e.g.
    `manifest.mark_ingested`) so a Ctrl-C mid-ingest doesn't lose every
    batch's work — points are already in Qdrant; the next run just needs
    to know they're done. See `src/stage2/__main__.py:ingest_from_manifest`.

    `verbose` prints the source path of each successfully upserted summary
    via `tqdm.write` so the bar isn't garbled. Use for debugging slow runs
    or to confirm specific files made it in.
    """
    from tqdm import tqdm

    if not summaries:
        return 0

    client = get_qdrant_client()
    total = 0

    bar = tqdm(range(0, len(summaries), BATCH_SIZE), desc="ingesting", unit="batch")
    for i in bar:
        batch = summaries[i : i + BATCH_SIZE]
        texts = [_build_embedding_text(s) for s in batch]
        dense_vectors = embed_dense(texts)
        sparse_vectors = embed_sparse(texts)

        points = []
        for s, dense_vec, (sparse_idx, sparse_val) in zip(
            batch, dense_vectors, sparse_vectors
        ):
            points.append(
                PointStruct(
                    id=_point_id(s.source_path),
                    vector={
                        "dense": dense_vec,
                        "sparse": SparseVector(indices=sparse_idx, values=sparse_val),
                    },
                    payload={
                        # Path-only payload (2026-05). The summary prose
                        # for display is reconstructed at query time by
                        # re-reading the markdown at <APP_DATA_DIR>/
                        # summaries/<hash>_<tier>.md (looked up via
                        # the manifest entry's `summary_file`). Saves
                        # significant Qdrant payload bytes at scale.
                        "source_path": s.source_path,
                    },
                )
            )

        _upsert_with_retry(client, COLLECTION_NAME, points)
        total += len(points)
        if verbose:
            for s in batch:
                tqdm.write(f"  upserted {s.source_path}")
        if on_batch_complete is not None:
            on_batch_complete(list(range(i, min(i + BATCH_SIZE, len(summaries)))))

    return total


def get_all_point_ids() -> set[str]:
    """Return the set of all point IDs currently in the collection.

    Used for orphan cleanup: after incremental ingest, any point whose ID
    isn't in the expected set (from the manifest) gets hard-deleted.
    """
    client = get_qdrant_client()
    ids: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=512,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        ids.update(str(p.id) for p in points)
        if offset is None:
            break
    return ids


def delete_points(ids: list[str]) -> int:
    """Hard-delete the given point IDs. Returns count deleted."""
    if not ids:
        return 0
    client = get_qdrant_client()
    client.delete(collection_name=COLLECTION_NAME, points_selector=ids)
    return len(ids)
