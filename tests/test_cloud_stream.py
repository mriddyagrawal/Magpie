"""_CloudAgent.run(on_text=...): the OpenAI-style SSE stream from
OpenRouter / Moonshot, parsed without a network — deltas forwarded as they
arrive, usage taken from the last chunk, a 5xx before any data retried,
an error after text has gone out NOT retried."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel


class Out(BaseModel):
    answer: str


def _sse(obj) -> str:
    return "data: " + json.dumps(obj)


class _FakeStreamResponse:
    def __init__(self, lines, status_code=200, body=b""):
        self._lines = lines
        self.status_code = status_code
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _fake_client(responses: list[_FakeStreamResponse], calls: list[dict]):
    """An httpx.AsyncClient stand-in; each stream() call pops the next
    canned response and records the request body."""

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, headers=None, json=None):
            calls.append({"method": method, "url": url, "headers": headers, "json": json})
            return responses.pop(0)

    return FakeClient


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    from src.llm import _CloudAgent

    a = _CloudAgent("You answer in JSON.", Out, provider_override="openrouter")
    monkeypatch.setattr(a, "_CLOUD_RETRY_BACKOFF_S", 0.0)
    return a


def test_deltas_are_forwarded_and_the_reply_parsed(agent, monkeypatch):
    import src.llm as llm_mod

    lines = [
        ": OPENROUTER PROCESSING",
        _sse({"choices": [{"delta": {"content": '{"answer": "Dr. '}}]}),
        "",
        _sse({"choices": [{"delta": {"content": 'Marquez"}'}}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 40, "completion_tokens": 9}}),
        "data: [DONE]",
    ]
    calls: list[dict] = []
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _fake_client([_FakeStreamResponse(lines)], calls))

    pieces: list[str] = []
    out = asyncio.run(agent.run(["Who chairs the department?"], on_text=pieces.append))

    assert pieces == ['{"answer": "Dr. ', 'Marquez"}']
    assert out == Out(answer="Dr. Marquez")
    assert calls[0]["json"]["stream"] is True
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["url"].endswith("/chat/completions")


def test_5xx_before_any_text_is_retried(agent, monkeypatch):
    import src.llm as llm_mod

    first = _FakeStreamResponse(
        [], status_code=502,
        body=json.dumps({"error": {"code": 502, "message": "provider_unavailable"}}).encode(),
    )
    second = _FakeStreamResponse([
        _sse({"choices": [{"delta": {"content": '{"answer": "ok"}'}}]}),
        "data: [DONE]",
    ])
    calls: list[dict] = []
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _fake_client([first, second], calls))

    pieces: list[str] = []
    out = asyncio.run(agent.run(["q"], on_text=pieces.append))
    assert out == Out(answer="ok")
    assert pieces == ['{"answer": "ok"}']
    assert len(calls) == 2


def test_error_after_text_went_out_is_not_retried(agent, monkeypatch):
    import src.llm as llm_mod

    lines = [
        _sse({"choices": [{"delta": {"content": '{"answer": "half'}}]}),
        _sse({"error": {"code": 502, "message": "upstream reset"}}),
    ]
    calls: list[dict] = []
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _fake_client([_FakeStreamResponse(lines)], calls))

    pieces: list[str] = []
    with pytest.raises(RuntimeError, match="HTTP 502 mid-stream"):
        asyncio.run(agent.run(["q"], on_text=pieces.append))
    assert pieces == ['{"answer": "half']
    assert len(calls) == 1  # text reached the caller; a retry would duplicate it


def test_without_on_text_the_plain_post_path_is_used(agent, monkeypatch):
    """No callback → the existing one-shot request, byte for byte."""
    import src.llm as llm_mod

    posted: list[dict] = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"answer": "plain"}'}}]}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            posted.append(json)
            return FakeResp()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", FakeClient)
    out = asyncio.run(agent.run(["q"]))
    assert out == Out(answer="plain")
    assert "stream" not in posted[0]


def test_connection_errors_propagate_unchanged(agent, monkeypatch):
    import src.llm as llm_mod

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *a, **kw):
            raise httpx.ConnectError("no route")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", FakeClient)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(agent.run(["q"], on_text=lambda _p: None))
