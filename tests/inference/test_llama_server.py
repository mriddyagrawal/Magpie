"""Unit tests for `LlamaServerLLM` (HTTP client) — no subprocess, no network.

Mocks the pool's URL resolution + httpx calls. Tests the HTTP request
shape and the SSE parsing logic.
"""

from __future__ import annotations

import asyncio
import json
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


def test_build_request_body_disables_thinking_by_default():
    """Regression gate: Gemma 4's chat template auto-enables thinking
    via --jinja, which routes 90%+ of the token budget into
    `reasoning_content` and leaves `content` mostly empty. The body
    must explicitly pass `chat_template_kwargs.enable_thinking=False`
    to suppress this. Validated against b9049 + Gemma 4 E4B
    (vision integration test was empty-content without this fix)."""
    llm = LlamaServerLLM()
    body = llm._build_request_body(
        messages=[{"role": "user", "content": "hi"}],
        temperature=None,
        max_tokens=None,
        stream=False,
    )
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_build_request_body_thinking_true_propagates():
    """When the caller asks for thinking, propagate it to llama-server's
    chat template. Mirrors the `thinking=True` kwarg on complete()."""
    llm = LlamaServerLLM()
    body = llm._build_request_body(
        messages=[],
        temperature=None,
        max_tokens=None,
        stream=False,
        thinking=True,
    )
    assert body["chat_template_kwargs"] == {"enable_thinking": True}


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


def test_extract_content_falls_back_to_reasoning_when_content_empty():
    """Belt-and-suspenders: if a future llama-server build renames
    `enable_thinking` and our suppression silently breaks, callers
    should still see *something* (the reasoning) rather than an
    empty string + a degraded JSON-repair fallback."""
    payload = {
        "choices": [{
            "message": {
                "content": "",
                "reasoning_content": "[the reasoning trace happens here]",
            }
        }]
    }
    assert (
        LlamaServerLLM._extract_content(payload)
        == "[the reasoning trace happens here]"
    )


def test_extract_content_prefers_content_over_reasoning():
    """When both are present (normal case), `content` is the answer
    and `reasoning_content` is the model's scratchpad — never surface
    the scratchpad if real content is available."""
    payload = {
        "choices": [{
            "message": {
                "content": "the answer",
                "reasoning_content": "scratchpad",
            }
        }]
    }
    assert LlamaServerLLM._extract_content(payload) == "the answer"


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


class _FakeStreamResponse:
    """Stands in for the `async with client.stream(...) as resp` object:
    a status, raise_for_status, and the SSE lines llama-server would send."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def test_stream_forwards_grammar_and_yields_deltas_and_timings():
    """The streaming path is the same request as complete() with
    stream=true: grammar / response_format ride along, each delta is
    yielded as it arrives, and the final chunk's timings are kept."""
    llm = LlamaServerLLM()
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": '{"answer": '}}]}),
        "",
        ": keep-alive comment",
        "data: " + json.dumps({
            "choices": [{"delta": {"content": '"hi"}'}}],
            "timings": {"prompt_n": 12, "predicted_n": 5},
        }),
        "",
        "data: [DONE]",
    ]
    captured: dict = {}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, json):
            captured["method"] = method
            captured["url"] = url
            captured["body"] = json
            return _FakeStreamResponse(lines)

    async def run():
        with patch("src.inference.local_llm.get_pool") as mock_pool:
            mock_pool.return_value.get_url_for.return_value = "http://127.0.0.1:9100"
            with patch("src.inference.local_llm.httpx.AsyncClient", FakeClient):
                it = await llm.stream(
                    [{"role": "user", "content": "hello"}],
                    grammar='root ::= "x"',
                    max_tokens=64,
                )
                return [piece async for piece in it]

    pieces = asyncio.run(run())
    assert pieces == ['{"answer": ', '"hi"}']
    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:9100/v1/chat/completions"
    assert captured["body"]["stream"] is True
    assert captured["body"]["grammar"] == 'root ::= "x"'
    assert captured["body"]["max_tokens"] == 64
    assert llm.last_timings == {"prompt_n": 12, "predicted_n": 5}


def test_stream_marks_pool_dead_on_connection_error():
    """Same recovery contract as complete(): a vanished subprocess drops
    the registry entry and surfaces as LlamaServerSpawnError."""
    import httpx

    from src.inference.llama_server_pool import LlamaServerSpawnError

    llm = LlamaServerLLM()

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, json):
            raise httpx.ConnectError("connection refused")

    async def run():
        with patch("src.inference.local_llm.get_pool") as mock_pool:
            mock_pool.return_value.get_url_for.return_value = "http://127.0.0.1:9100"
            mock_pool.return_value.mark_dead = MagicMock()
            with patch("src.inference.local_llm.httpx.AsyncClient", FakeClient):
                it = await llm.stream([{"role": "user", "content": "hi"}])
                with pytest.raises(LlamaServerSpawnError):
                    async for _ in it:
                        pass
            mock_pool.return_value.mark_dead.assert_called_once_with(llm.profile_name)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Pool stderr-mirror filter (quiet by default)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line, is_signal",
    [
        # high-signal lines — always surface in quiet mode
        ("ERROR: failed to load model", True),
        ("warning: out of memory", True),
        ("model loaded", True),
        ("main: server is listening on http://127.0.0.1:9100", True),
        ("common_init_result: failed to load model", True),
        # low-signal per-inference noise — only shown with VERBOSE=1
        ("slot update_slots: id  3 | task 0 | prompt processing", False),
        ("ggml_metal_init: allocating", False),
        ("sched_reserve: reserving ...", False),
        ("srv  process_chun: image processed in 1572 ms", False),
        ("[llama-server] llama_model_loader: - kv  17:                         gemma4.block_count", False),
    ],
)
def test_drain_filter_keeps_errors_drops_per_inference_noise(line, is_signal):
    """Pool's stderr drain hides ~30 noisy lines per inference but always
    surfaces errors / warnings / model-loaded / server-listening lines.
    Keeps `just sync` walker tqdm readable while preserving the lines
    that matter when something breaks."""
    from src.inference.llama_server_pool import _is_high_signal
    assert _is_high_signal(line) is is_signal


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_get_local_llm_returns_same_instance():
    from src.inference.local_llm import get_local_llm

    a = get_local_llm()
    b = get_local_llm()
    assert a is b
    assert isinstance(a, LlamaServerLLM)
