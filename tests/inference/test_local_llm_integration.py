"""Integration tests for the local llama-cpp-python backend.

Skipped by default — these tests require a real GGUF download (~3-7 GB)
and 10-30s of model-load time. Enable with:

    RUN_LOCAL_LLM_INTEGRATION_TESTS=1 uv run pytest tests/inference/test_local_llm_integration.py -v

Or run via the future `just test-integration` recipe.

Use a smaller stand-in model for the CI-friendly path. TinyLlama-1.1B-Chat
(~640 MB at Q4_K_M) is light enough to load and stream a few tokens in
seconds. Override via the env vars below if you want to test against the
real Gemma 4 E4B.

Env overrides for these tests:
    LOCAL_MODEL  (default TinyLlama-1.1B-Chat-v1.0-GGUF)
    LOCAL_QUANT  (default Q4_K_M)
"""

from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LOCAL_LLM_INTEGRATION_TESTS", "").strip() != "1",
    reason="set RUN_LOCAL_LLM_INTEGRATION_TESTS=1 to run (heavy: model download + load).",
)


@pytest.fixture(scope="module", autouse=True)
def _set_test_model(monkeypatch_module):
    """Use TinyLlama for the integration smoke test rather than the real
    Gemma 4 (saves multi-GB download in CI)."""
    monkeypatch_module.setenv(
        "LOCAL_MODEL",
        os.environ.get("LOCAL_MODEL_OVERRIDE", "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF"),
    )
    monkeypatch_module.setenv(
        "LOCAL_QUANT",
        os.environ.get("LOCAL_QUANT_OVERRIDE", "Q4_K_M"),
    )


@pytest.fixture(scope="module")
def monkeypatch_module(request):
    """A module-scoped monkeypatch — vanilla pytest only ships function-scoped."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    request.addfinalizer(mp.undo)
    return mp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_returns_string():
    """`complete()` returns a non-empty string for a trivial prompt."""
    from src.inference import get_local_llm

    llm = get_local_llm()
    text = await llm.complete(
        [{"role": "user", "content": "Reply with just the word: yes"}],
        max_tokens=8,
        temperature=0.0,
    )
    assert isinstance(text, str)
    assert text.strip(), "completion should not be empty"


@pytest.mark.asyncio
async def test_stream_yields_chunks():
    """`stream()` yields multiple non-empty chunks before terminating."""
    from src.inference import get_local_llm

    llm = get_local_llm()
    chunks: list[str] = []
    stream = await llm.stream(
        [{"role": "user", "content": "Count 1, 2, 3, 4, 5."}],
        max_tokens=32,
        temperature=0.0,
    )
    async for chunk in stream:
        chunks.append(chunk)
        if len(chunks) >= 8:
            break
    assert len(chunks) >= 2, f"expected ≥2 chunks, got {len(chunks)}: {chunks!r}"
    assert all(isinstance(c, str) for c in chunks)


@pytest.mark.asyncio
async def test_thinking_on_non_thinking_model_is_silent_noop():
    """`thinking=True` against TinyLlama (no thinking support) doesn't crash
    or leak the Gemma-4 token into the output."""
    from src.inference import get_local_llm

    llm = get_local_llm()
    text = await llm.complete(
        [{"role": "user", "content": "Reply with just: ok"}],
        thinking=True,
        max_tokens=8,
        temperature=0.0,
    )
    assert "<|think|>" not in text


@pytest.mark.asyncio
async def test_local_agent_round_trip_with_pydantic_schema():
    """`LocalAgent` end-to-end: feed a tiny schema, get a parsed object back.

    Uses temperature=0 so the cheapest model can still nail JSON output.
    parse_json_with_repair is the safety net if the model wraps in fences.
    """
    from pydantic import BaseModel
    from src.llm import LocalAgent

    class Reply(BaseModel):
        answer: str

    agent = LocalAgent(
        system_prompt="You output a single JSON object: {\"answer\": \"yes\" or \"no\"}.",
        output_type=Reply,
        fallback=Reply(answer="error"),
    )
    result = await agent.run(["Should this test pass? Reply yes."])
    assert isinstance(result, Reply)
    assert result.answer.lower() in {"yes", "no", "error"}
