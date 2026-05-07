"""Unit tests for `LlamaServerLLM` (HTTP client) — no subprocess, no network.

Mocks the pool's URL resolution + httpx calls. Tests the HTTP request
shape and the SSE parsing logic.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.inference.local_llm import (
    LlamaServerLLM,
    _SSE_DONE,
    _parse_sse_chunk,
)


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line, expected",
    [
        ('data: {"choices":[{"delta":{"content":"Hello"}}]}', "Hello"),
        ('data: {"choices":[{"delta":{"content":" world"}}]}', " world"),
        ("data: [DONE]", _SSE_DONE),
        ("data: ", ""),  # blank payload
        ("", ""),  # blank line
        (": comment line", ""),
        ('data: {"choices":[{"delta":{}}]}', ""),  # delta without content
        ("data: {malformed json}", ""),  # graceful on parse error
    ],
)
def test_parse_sse_chunk(line, expected):
    assert _parse_sse_chunk(line) == expected


# ---------------------------------------------------------------------------
# Request body shape
# ---------------------------------------------------------------------------

def test_build_request_body_omits_none_max_tokens():
    """Keep llama-server defaults in play when the caller doesn't cap."""
    llm = LlamaServerLLM()
    body = llm._build_request_body(
        messages=[{"role": "user", "content": "hi"}],
        temperature=None,
        max_tokens=None,
        stream=False,
    )
    assert "max_tokens" not in body
    assert body["temperature"] == llm.default_temperature
    assert body["stream"] is False


def test_build_request_body_preserves_max_tokens():
    llm = LlamaServerLLM()
    body = llm._build_request_body(
        messages=[],
        temperature=0.0,
        max_tokens=512,
        stream=True,
    )
    assert body["max_tokens"] == 512
    assert body["temperature"] == 0.0
    assert body["stream"] is True


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def test_extract_content_handles_normal_response():
    payload = {
        "choices": [
            {"message": {"content": "the answer"}}
        ]
    }
    assert LlamaServerLLM._extract_content(payload) == "the answer"


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing choices
        {"choices": []},  # empty choices
        {"choices": [{}]},  # missing message
        {"choices": [{"message": {}}]},  # missing content
        {"choices": [{"message": {"content": None}}]},  # null content
    ],
)
def test_extract_content_returns_empty_on_malformed(payload):
    """Defensive: no IndexError / KeyError surfacing to the caller."""
    assert LlamaServerLLM._extract_content(payload) == ""


# ---------------------------------------------------------------------------
# complete() — async path with mocked httpx
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self, json_payload: dict):
        self._json = json_payload

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


def test_complete_calls_pool_and_posts_to_chat_completions():
    """End-to-end of the async complete path with a mocked client.

    Verifies:
      - get_pool().get_url_for(profile_name) is called
      - POST goes to <base_url>/v1/chat/completions
      - Body has the expected shape
      - Response.choices[0].message.content is returned
    """
    llm = LlamaServerLLM()
    fake_response = _MockResponse({
        "choices": [{"message": {"content": "hello back"}}]
    })

    async def run():
        with patch(
            "src.inference.local_llm.get_pool"
        ) as mock_pool:
            mock_pool.return_value.get_url_for.return_value = "http://127.0.0.1:9100"
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = False
            mock_client.post = AsyncMock(return_value=fake_response)
            with patch(
                "src.inference.local_llm.httpx.AsyncClient",
                return_value=mock_client,
            ):
                result = await llm.complete(
                    messages=[{"role": "user", "content": "hello"}]
                )
        return result, mock_pool, mock_client

    result, mock_pool, mock_client = asyncio.run(run())

    assert result == "hello back"
    mock_pool.return_value.get_url_for.assert_called_once_with(llm.profile_name)
    posted_url = mock_client.post.call_args.args[0]
    assert posted_url == "http://127.0.0.1:9100/v1/chat/completions"


def test_complete_marks_pool_dead_on_connection_error():
    """If httpx.ConnectError fires, drop the pool's registry entry so
    the next call respawns the subprocess. Don't silently swallow."""
    import httpx

    from src.inference.llama_server_pool import LlamaServerSpawnError

    llm = LlamaServerLLM()

    async def run():
        with patch("src.inference.local_llm.get_pool") as mock_pool:
            mock_pool.return_value.get_url_for.return_value = "http://127.0.0.1:9100"
            mock_pool.return_value.mark_dead = MagicMock()
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = False
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("connection refused")
            )
            with patch(
                "src.inference.local_llm.httpx.AsyncClient",
                return_value=mock_client,
            ):
                with pytest.raises(LlamaServerSpawnError):
                    await llm.complete(messages=[{"role": "user", "content": "hi"}])
            mock_pool.return_value.mark_dead.assert_called_once_with(llm.profile_name)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_get_local_llm_returns_same_instance():
    from src.inference.local_llm import get_local_llm

    a = get_local_llm()
    b = get_local_llm()
    assert a is b
    assert isinstance(a, LlamaServerLLM)
