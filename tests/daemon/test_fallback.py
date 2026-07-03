"""Fallback tests — when the daemon is unreachable, ask_via_daemon
must transparently run the in-process pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.daemon.client import ask_via_daemon, DaemonUnreachableError


@pytest.fixture
def isolated_state(monkeypatch, tmp_path: Path):
    """Different state dir per test so we don't accidentally hit a real
    daemon left running on the dev machine."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    # Disable daemon auto-spawn so tests stay fast and deterministic.
    monkeypatch.setenv("NS_DAEMON_DISABLED", "1")
    yield tmp_path


def test_disabled_via_env_uses_inprocess(isolated_state, monkeypatch):
    """NS_DAEMON_DISABLED=1 → never tries the daemon, runs in-process."""
    from src.pipeline import PipelineResult
    from src.stage2.search import SearchQuery

    fake_result = PipelineResult(
        question="hello", search_query=SearchQuery(query="hello", keywords=[]),
        retrieved=[], answer="from-inprocess", sources_used=[],
    )
    with patch("src.daemon.client._inprocess_fallback", return_value=fake_result) as fp:
        result = ask_via_daemon("hello")
    fp.assert_called_once()
    assert result.answer == "from-inprocess"


def test_unreachable_daemon_falls_back(isolated_state, monkeypatch):
    """Daemon unreachable AND fallback enabled → in-process is used."""
    monkeypatch.delenv("NS_DAEMON_DISABLED", raising=False)
    from src.pipeline import PipelineResult
    from src.stage2.search import SearchQuery

    fake_result = PipelineResult(
        question="x", search_query=SearchQuery(query="x", keywords=[]),
        retrieved=[], answer="fb", sources_used=[],
    )

    # Block both spawn paths so we deterministically can't reach a daemon.
    with patch("src.daemon.client._connect_or_spawn", return_value=None), \
         patch("src.daemon.client._inprocess_fallback", return_value=fake_result) as fp:
        result = ask_via_daemon("x")
    fp.assert_called_once()
    assert result.answer == "fb"


def test_unreachable_daemon_raises_when_fallback_off(isolated_state, monkeypatch):
    """Caller can opt out of the fallback (e.g. for strict-mode debugging)."""
    monkeypatch.delenv("NS_DAEMON_DISABLED", raising=False)
    with patch("src.daemon.client._connect_or_spawn", return_value=None):
        with pytest.raises(DaemonUnreachableError):
            ask_via_daemon("x", fallback_to_inprocess=False)
