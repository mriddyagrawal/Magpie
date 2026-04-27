"""Tests for the FALLBACK_LLM_PROVIDER fallback path in src/stage1/summarize.py.

Covers:
  - Fallback fires when primary raises UnexpectedModelBehavior (the OpenRouter
    free-tier-exhaustion symptom we hit on 2026-04-24).
  - Fallback fires after the primary exhausts 429 retries.
  - Fallback does NOT fire if FALLBACK_LLM_PROVIDER is unset / equals
    LLM_PROVIDER / names an unknown provider.
  - When the fallback also fails, both errors are surfaced (chained).

Async tests wrap their bodies in `asyncio.run` because the project doesn't
ship pytest-asyncio. Matches the existing pattern in tests/ingest/test_walker.py.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _reset_fallback_cache():
    """Reset the module-level fallback cache so each test starts fresh."""
    import src.stage1.summarize as s
    s._fallback_agent_cache = None
    s._fallback_checked = False


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Clear fallback cache + relevant env vars between tests."""
    _reset_fallback_cache()
    monkeypatch.delenv("FALLBACK_LLM_PROVIDER", raising=False)


# ---------------------------------------------------------------------------
# get_fallback_agent (sync)
# ---------------------------------------------------------------------------

def test_get_fallback_agent_returns_none_when_unset():
    from src.stage1.summarize import get_fallback_agent
    assert get_fallback_agent() is None


def test_get_fallback_agent_returns_none_when_same_as_active(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("FALLBACK_LLM_PROVIDER", "openrouter")
    from src.stage1.summarize import get_fallback_agent
    assert get_fallback_agent() is None


def test_get_fallback_agent_returns_none_for_unknown_provider(
    monkeypatch, capsys
):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("FALLBACK_LLM_PROVIDER", "made-up-provider")
    from src.stage1.summarize import get_fallback_agent
    assert get_fallback_agent() is None
    err = capsys.readouterr().err
    assert "FALLBACK_LLM_PROVIDER" in err and "unknown" in err


def test_get_fallback_agent_caches_after_first_call(monkeypatch):
    """Subsequent calls don't rebuild the agent — cached on a global."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("FALLBACK_LLM_PROVIDER", "ollama")

    sentinel = MagicMock(name="fallback_agent")
    with patch(
        "src.stage1.summarize._build_chat_agent", return_value=sentinel
    ) as build_mock:
        from src.stage1.summarize import get_fallback_agent
        a = get_fallback_agent()
        b = get_fallback_agent()

    assert a is sentinel
    assert b is sentinel
    assert build_mock.call_count == 1
    _, kwargs = build_mock.call_args
    assert kwargs.get("provider_override") == "ollama"


# ---------------------------------------------------------------------------
# _run_with_retry — fallback firing behavior
# ---------------------------------------------------------------------------

def test_fallback_rescues_on_unexpected_model_behavior(monkeypatch):
    """The OpenRouter-free-tier-exhaustion symptom: primary raises, fallback succeeds."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("FALLBACK_LLM_PROVIDER", "ollama")

    from pydantic_ai.exceptions import UnexpectedModelBehavior

    primary = MagicMock()
    primary.run = AsyncMock(side_effect=UnexpectedModelBehavior("bad json"))

    rescued = MagicMock(name="rescued_summary")
    fallback = MagicMock()
    fallback.run = AsyncMock(return_value=rescued)

    with patch(
        "src.stage1.summarize.get_fallback_agent", return_value=fallback
    ):
        from src.stage1.summarize import _run_with_retry
        result = asyncio.run(_run_with_retry(primary, ["msg"], "test-file.pdf"))

    assert result is rescued
    primary.run.assert_called_once()
    fallback.run.assert_called_once_with(["msg"])


def test_no_fallback_propagates_primary_error(monkeypatch):
    """Without FALLBACK_LLM_PROVIDER, primary failure still propagates as before."""
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    primary = MagicMock()
    err = UnexpectedModelBehavior("bad json")
    primary.run = AsyncMock(side_effect=err)

    with patch("src.stage1.summarize.get_fallback_agent", return_value=None):
        from src.stage1.summarize import _run_with_retry
        with pytest.raises(UnexpectedModelBehavior):
            asyncio.run(_run_with_retry(primary, ["msg"], "test-file.pdf"))

    primary.run.assert_called_once()


def test_fallback_failure_is_chained_from_primary(monkeypatch):
    """Both providers down → fallback's exception is raised, primary stays as `__cause__`."""
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    primary = MagicMock()
    primary_err = UnexpectedModelBehavior("primary down")
    primary.run = AsyncMock(side_effect=primary_err)

    fallback = MagicMock()
    fallback_err = RuntimeError("ollama unreachable")
    fallback.run = AsyncMock(side_effect=fallback_err)

    with patch("src.stage1.summarize.get_fallback_agent", return_value=fallback):
        from src.stage1.summarize import _run_with_retry
        with pytest.raises(RuntimeError) as excinfo:
            asyncio.run(_run_with_retry(primary, ["msg"], "test-file.pdf"))

    assert "ollama unreachable" in str(excinfo.value)
    assert excinfo.value.__cause__ is primary_err


def test_429_still_retries_primary_before_falling_back(monkeypatch):
    """429 retries on primary first; only after exhaustion does fallback fire."""
    from pydantic_ai.exceptions import ModelHTTPError

    err = ModelHTTPError(
        status_code=429,
        model_name="openrouter/test",
        body={"metadata": {"raw": '{"retryDelay": "0s"}'}},
    )
    primary = MagicMock()
    primary.run = AsyncMock(side_effect=err)

    rescued = MagicMock(name="rescued")
    fallback = MagicMock()
    fallback.run = AsyncMock(return_value=rescued)

    with patch("src.stage1.summarize.get_fallback_agent", return_value=fallback), \
         patch("src.stage1.summarize.MAX_429_RETRIES", 2):
        from src.stage1.summarize import _run_with_retry
        result = asyncio.run(_run_with_retry(primary, ["msg"], "test-file.pdf"))

    # Primary was retried until exhausted, then fallback fired once.
    assert primary.run.call_count == 2
    fallback.run.assert_called_once()
    assert result is rescued


def test_primary_success_skips_fallback(monkeypatch):
    """Happy path — primary returns, fallback is never even queried."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("FALLBACK_LLM_PROVIDER", "ollama")

    expected = MagicMock(name="primary_result")
    primary = MagicMock()
    primary.run = AsyncMock(return_value=expected)

    with patch("src.stage1.summarize.get_fallback_agent") as get_mock:
        from src.stage1.summarize import _run_with_retry
        result = asyncio.run(_run_with_retry(primary, ["msg"], "test-file.pdf"))

    assert result is expected
    get_mock.assert_not_called()
