"""Unit tests for `_flatten_message_for_local` in src.llm — no model load.

Verifies that the desktop-side message list (heterogeneous strings + binary
blocks for vision) is converted correctly to llama-cpp-python's chat-completion
format, with binary blocks dropped (and a one-time warning emitted).
"""

from __future__ import annotations

import pytest

from src.llm import _flatten_message_for_local


def test_strings_only_message() -> None:
    msgs = _flatten_message_for_local(
        ["hello", "world"], system_prompt="be helpful"
    )
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "be helpful"
    assert msgs[1]["role"] == "user"
    assert "hello" in msgs[1]["content"]
    assert "world" in msgs[1]["content"]
    # Plus the JSON-output instruction we always append.
    assert "JSON" in msgs[1]["content"]


def test_drops_binary_content_blocks() -> None:
    """Anything that isn't a string (BinaryContent, dict, etc.) gets dropped.

    Vision support for the local backend is a follow-up; until then T3
    image-bearing files end up with the framing text but no image content.
    """

    class FakeBinary:
        data = b"\xff\xd8"
        media_type = "image/jpeg"

    with pytest.warns(UserWarning, match="non-text content"):
        msgs = _flatten_message_for_local(
            ["framing text", FakeBinary(), "more text"],
            system_prompt="sys",
        )
    user_content = msgs[1]["content"]
    assert "framing text" in user_content
    assert "more text" in user_content
    # No bytes survived into the prompt.
    assert "\\xff" not in user_content
    assert "FakeBinary" not in user_content


def test_empty_message_list_yields_just_json_hint() -> None:
    msgs = _flatten_message_for_local([], system_prompt="sys")
    assert msgs[0] == {"role": "system", "content": "sys"}
    # User message is just the JSON-output instruction (no actual content).
    assert "JSON" in msgs[1]["content"]
