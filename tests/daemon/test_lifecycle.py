"""Daemon lifecycle tests — spawn, ping, ask, shutdown.

These run the daemon in a thread (not a subprocess) for speed and so we
can mock the underlying pipeline. The real subprocess spawn path is
exercised by `test_subprocess_smoke.py` (slower, separate file so CI can
skip it on constrained runners).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.daemon import protocol as proto
from src.daemon import server as srv
from src.daemon.client import (
    DaemonUnreachableError,
    _try_connect,
    ping_daemon,
    request_shutdown,
)


@pytest.fixture
def isolated_daemon_state(monkeypatch, tmp_path: Path):
    """Each test gets its own state dir so daemons don't collide."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    # Reset module-level state since the daemon module uses globals.
    srv._shutdown_requested.clear()
    srv._listener = None
    yield tmp_path
    # Best-effort cleanup if a test left a daemon thread running.
    srv._shutdown_requested.set()
    srv._shutdown_listener()


def _start_daemon_thread() -> threading.Thread:
    """Spawn server.run() in a daemon thread, returning the thread handle."""
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    # Poll for socket to appear.
    from src.daemon.spawn import wait_for_socket
    assert wait_for_socket(timeout_sec=5), "daemon socket never appeared"
    return t


def test_ping_returns_pid_and_uptime(isolated_daemon_state):
    _start_daemon_thread()
    info = ping_daemon()
    assert info.ok is True
    assert info.pid > 0
    assert info.uptime_sec >= 0
    assert info.protocol_version == proto.PROTOCOL_VERSION


def test_shutdown_request_terminates_daemon(isolated_daemon_state):
    _start_daemon_thread()
    request_shutdown()
    # Give the daemon a moment to exit its accept loop.
    time.sleep(0.3)
    # Subsequent ping should fail since the listener is gone.
    with pytest.raises(DaemonUnreachableError):
        ping_daemon()


def test_ask_with_mocked_pipeline_returns_answer(isolated_daemon_state):
    """End-to-end: mock the pipeline.ask path so the daemon doesn't
    actually load real models / hit Qdrant. Verifies the request shape
    arrives intact and the response wires back correctly."""
    from src.daemon.client import _connect_or_spawn

    # Patch the imports inside _handle_ask. The daemon imports them
    # lazily, so monkey-patching the modules works even though the
    # daemon thread will re-import them on first request.
    from src.stage2.search import SearchQuery, SearchResult

    mock_sq = SearchQuery(query="mocked", keywords=[])
    mock_results = [SearchResult(summary="hi", path="mock.md", score=0.9, tier="summary")]

    class _MockAns:
        answer = "the mocked answer"
        sources_used = ["mock.md"]

    async def fake_ask_inner(*args, **kwargs):
        return _MockAns()

    with patch("src.stage2.search.run_search", return_value=mock_results), \
         patch("src.stage2.search.raw_query", return_value=mock_sq), \
         patch("src.answer.build_answer_agent", return_value=object()), \
         patch("src.answer.answer_question", new=fake_ask_inner):
        _start_daemon_thread()

        # Speak the protocol directly so we don't pull in ask_via_daemon's
        # fallback logic for this test.
        handle = _connect_or_spawn(allow_spawn=False)
        assert handle is not None
        with handle as conn:
            conn.send(proto.AskRequest(question="what?", top_k=3))
            response = conn.recv()

        assert isinstance(response, proto.AskResponse)
        assert response.ok is True
        assert response.answer == "the mocked answer"
        assert response.sources_used == ["mock.md"]
        assert len(response.retrieved) == 1
        assert response.retrieved[0]["path"] == "mock.md"


def test_ask_handler_catches_pipeline_exceptions(isolated_daemon_state):
    """If the inner pipeline raises, the daemon should return ok=False
    rather than crashing the whole process."""
    from src.daemon.client import _connect_or_spawn
    from src.stage2.search import SearchQuery

    def boom(*args, **kwargs):
        raise ValueError("simulated failure")

    with patch("src.stage2.search.raw_query", return_value=SearchQuery(query="x", keywords=[])), \
         patch("src.stage2.search.run_search", side_effect=boom):
        _start_daemon_thread()

        handle = _connect_or_spawn(allow_spawn=False)
        assert handle is not None
        with handle as conn:
            conn.send(proto.AskRequest(question="x"))
            response = conn.recv()

        assert isinstance(response, proto.AskResponse)
        assert response.ok is False
        assert "simulated failure" in response.error
        assert response.error_type == "ValueError"


def test_unknown_request_type_returns_protocol_error(isolated_daemon_state):
    """Future request types not yet recognized → ProtocolError, not crash."""
    from src.daemon.client import _connect_or_spawn

    # Send a plain dict (not one of our dataclasses) to provoke the fallback.
    _start_daemon_thread()
    handle = _connect_or_spawn(allow_spawn=False)
    assert handle is not None
    with handle as conn:
        conn.send({"op": "made_up_op"})
        response = conn.recv()

    assert isinstance(response, proto.ProtocolError)
    assert response.server_protocol_version == proto.PROTOCOL_VERSION


def test_ping_when_no_daemon_raises(isolated_daemon_state):
    """Without a running daemon, ping must fail loudly."""
    with pytest.raises(DaemonUnreachableError):
        ping_daemon()
