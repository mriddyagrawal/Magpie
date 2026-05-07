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
    monkeypatch.setenv("QDRANT_CLUSTER_ENDPOINT", "http://localhost:6433")
    monkeypatch.delenv("QDRANT_TIMEOUT_S", raising=False)

    with patch.object(db_mod, "QdrantClient") as MockClient:
        db_mod.get_qdrant_client()
        kwargs = MockClient.call_args.kwargs
        assert kwargs.get("timeout") == 60


def test_env_var_overrides_timeout(monkeypatch):
    _reset_client_cache()
    monkeypatch.setenv("QDRANT_CLUSTER_ENDPOINT", "http://localhost:6433")
    monkeypatch.setenv("QDRANT_TIMEOUT_S", "300")

    with patch.object(db_mod, "QdrantClient") as MockClient:
        db_mod.get_qdrant_client()
        assert MockClient.call_args.kwargs.get("timeout") == 300


def test_default_endpoint_is_localhost_6433(monkeypatch):
    """Magpie defaults to its non-default port to avoid OpenWhispr / other
    apps that ship Qdrant on the canonical 6333."""
    _reset_client_cache()
    monkeypatch.delenv("QDRANT_CLUSTER_ENDPOINT", raising=False)

    with patch.object(db_mod, "QdrantClient") as MockClient:
        db_mod.get_qdrant_client()
        assert MockClient.call_args.kwargs.get("url") == "http://localhost:6433"


def test_non_localhost_endpoint_hard_errors(monkeypatch):
    """Magpie is local-first by design — remote Qdrant clusters would
    silently leak the user's index off-machine. Reject at startup."""
    _reset_client_cache()
    monkeypatch.setenv("QDRANT_CLUSTER_ENDPOINT", "https://my-cluster.qdrant.io")

    with pytest.raises(SystemExit) as exc_info:
        db_mod.get_qdrant_client()
    assert "not a localhost URL" in str(exc_info.value)


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
