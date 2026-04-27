"""Tests for QdrantClient timeout configuration + upsert retry-on-timeout.

The default qdrant-client timeout is 5s, which times out on big multi-vector
batches when the local Qdrant server is busy mid-ingest. We bump it to 60s
(env-var overridable) and wrap upserts with retry-on-ResponseHandlingException
so a single transient timeout doesn't kill a 99k-file ingest.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.stage2 import db as db_mod


# ---------------------------------------------------------------------------
# Timeout config
# ---------------------------------------------------------------------------

def _reset_client_cache():
    db_mod._client = None


def test_default_timeout_is_60_seconds(monkeypatch):
    """No QDRANT_TIMEOUT_S env var → 60-second default."""
    _reset_client_cache()
    monkeypatch.setenv("QDRANT_PROVIDER", "cloud")
    monkeypatch.setenv("QDRANT_CLUSTER_ENDPOINT", "http://localhost:6333")
    monkeypatch.delenv("QDRANT_TIMEOUT_S", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)

    with patch.object(db_mod, "QdrantClient") as MockClient:
        db_mod.get_qdrant_client()
        kwargs = MockClient.call_args.kwargs
        assert kwargs.get("timeout") == 60


def test_env_var_overrides_timeout(monkeypatch):
    _reset_client_cache()
    monkeypatch.setenv("QDRANT_PROVIDER", "cloud")
    monkeypatch.setenv("QDRANT_CLUSTER_ENDPOINT", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_TIMEOUT_S", "300")

    with patch.object(db_mod, "QdrantClient") as MockClient:
        db_mod.get_qdrant_client()
        assert MockClient.call_args.kwargs.get("timeout") == 300


def test_local_provider_does_not_pass_timeout(monkeypatch, tmp_path):
    """`QDRANT_PROVIDER=local` uses the in-process shim — no HTTP timeout
    applies. Verify we don't pass `timeout=` (would be wasted/confusing)."""
    _reset_client_cache()
    monkeypatch.setenv("QDRANT_PROVIDER", "local")
    monkeypatch.setenv("QDRANT_LOCAL_PATH", str(tmp_path / "qdrant_local"))

    with patch.object(db_mod, "QdrantClient") as MockClient:
        db_mod.get_qdrant_client()
        kwargs = MockClient.call_args.kwargs
        # Local mode constructs with `path=...`, no timeout kwarg.
        assert "timeout" not in kwargs
        assert "path" in kwargs


# ---------------------------------------------------------------------------
# Upsert retry behavior
# ---------------------------------------------------------------------------

def test_upsert_with_retry_succeeds_on_first_try():
    """Happy path: no retries needed, no sleep."""
    client = MagicMock()
    client.upsert = MagicMock()  # succeeds
    db_mod._upsert_with_retry(client, "collection", points=[])
    assert client.upsert.call_count == 1


def test_upsert_with_retry_recovers_after_one_timeout(monkeypatch):
    """First call times out, second succeeds — total 2 attempts, 1 sleep."""
    from qdrant_client.http.exceptions import ResponseHandlingException
    monkeypatch.setattr(time, "sleep", lambda _: None)  # don't actually wait

    call_count = {"n": 0}

    def upsert(**_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ResponseHandlingException(TimeoutError("timed out"))
        return None

    client = MagicMock()
    client.upsert.side_effect = upsert
    db_mod._upsert_with_retry(client, "collection", points=[])
    assert client.upsert.call_count == 2


def test_upsert_with_retry_gives_up_after_max_attempts(monkeypatch):
    """All retries fail → raises the original ResponseHandlingException."""
    from qdrant_client.http.exceptions import ResponseHandlingException
    monkeypatch.setattr(time, "sleep", lambda _: None)

    client = MagicMock()
    client.upsert.side_effect = ResponseHandlingException(TimeoutError("timed out"))

    with pytest.raises(ResponseHandlingException):
        db_mod._upsert_with_retry(
            client, "collection", points=[], max_attempts=3,
        )
    assert client.upsert.call_count == 3


def test_upsert_with_retry_does_not_retry_other_exceptions(monkeypatch):
    """Non-timeout errors (validation, dim mismatch) propagate immediately."""
    monkeypatch.setattr(time, "sleep", lambda _: None)

    client = MagicMock()
    client.upsert.side_effect = ValueError("invalid vector size")

    with pytest.raises(ValueError):
        db_mod._upsert_with_retry(client, "collection", points=[])
    # Only one call — we don't retry on non-timeout errors
    assert client.upsert.call_count == 1
