"""Unit tests for src.inference.chat_template — no model load, fast.

These verify the thinking-mode token injection logic and Gemma 4 detection
heuristic without loading any model. Always runs.
"""

from __future__ import annotations

import pytest

from src.inference.chat_template import (
    apply_thinking_to_messages,
    is_gemma4,
    strip_thinking_from_response,
)


# ---------------------------------------------------------------------------
# is_gemma4
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "model_id, expected",
    [
        ("unsloth/gemma-4-E4B-it-GGUF", True),
        ("google/gemma-4-31B-it", True),
        ("mlx-community/gemma-4-e4b-it-4bit", True),
        ("gemma4-something", True),
        ("mlx-community/gemma-3n-E4B-it-4bit", False),
        ("google/gemma-2-9b-it", False),
        ("meta-llama/Llama-3-8B", False),
        ("", False),
    ],
)
def test_is_gemma4(model_id: str, expected: bool) -> None:
    assert is_gemma4(model_id) is expected


# ---------------------------------------------------------------------------
# apply_thinking_to_messages
# ---------------------------------------------------------------------------

GEMMA4_REPO = "unsloth/gemma-4-E4B-it-GGUF"
NON_GEMMA4_REPO = "TinyLlama/TinyLlama-1.1B-Chat-v1.0-GGUF"
THINK_TOKEN = "<|think|>"


def test_thinking_off_is_passthrough() -> None:
    msgs = [{"role": "system", "content": "be helpful"}, {"role": "user", "content": "hi"}]
    out = apply_thinking_to_messages(msgs, thinking=False, model_repo_or_path=GEMMA4_REPO)
    assert out == msgs


def test_thinking_on_gemma4_prepends_token_to_existing_system() -> None:
    msgs = [{"role": "system", "content": "be helpful"}, {"role": "user", "content": "hi"}]
    out = apply_thinking_to_messages(msgs, thinking=True, model_repo_or_path=GEMMA4_REPO)
    # The token ends up *before* the existing system content.
    assert out[0]["role"] == "system"
    assert out[0]["content"].startswith(THINK_TOKEN)
    assert "be helpful" in out[0]["content"]
    # User message untouched.
    assert out[1] == {"role": "user", "content": "hi"}


def test_thinking_on_gemma4_creates_system_when_missing() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    out = apply_thinking_to_messages(msgs, thinking=True, model_repo_or_path=GEMMA4_REPO)
    assert len(out) == 2
    assert out[0]["role"] == "system"
    assert out[0]["content"] == THINK_TOKEN


def test_thinking_on_non_gemma4_is_noop() -> None:
    """Non-Gemma-4 models silently get no thinking token — the kwarg passes
    through to keep call sites consistent across model swaps without
    leaking unsupported tokens."""
    msgs = [{"role": "system", "content": "be helpful"}, {"role": "user", "content": "hi"}]
    out = apply_thinking_to_messages(msgs, thinking=True, model_repo_or_path=NON_GEMMA4_REPO)
    assert out == msgs


def test_thinking_idempotent_on_gemma4() -> None:
    """Re-applying thinking=True doesn't stack tokens."""
    msgs = [{"role": "system", "content": "be helpful"}, {"role": "user", "content": "hi"}]
    once = apply_thinking_to_messages(msgs, thinking=True, model_repo_or_path=GEMMA4_REPO)
    twice = apply_thinking_to_messages(once, thinking=True, model_repo_or_path=GEMMA4_REPO)
    assert once == twice
    assert once[0]["content"].count(THINK_TOKEN) == 1


def test_apply_does_not_mutate_input() -> None:
    msgs = [{"role": "system", "content": "x"}]
    snapshot = [dict(m) for m in msgs]
    _ = apply_thinking_to_messages(msgs, thinking=True, model_repo_or_path=GEMMA4_REPO)
    assert msgs == snapshot


# ---------------------------------------------------------------------------
# strip_thinking_from_response
# ---------------------------------------------------------------------------

def test_strip_thinking_removes_thought_block() -> None:
    raw = "<|channel|>thought\nlet me think about this<channel|>\nThe answer is 42."
    assert strip_thinking_from_response(raw) == "The answer is 42."


def test_strip_thinking_no_block_passthrough() -> None:
    raw = "Just a plain answer with no thinking trace."
    assert strip_thinking_from_response(raw) == raw


def test_strip_thinking_handles_empty() -> None:
    assert strip_thinking_from_response("") == ""
