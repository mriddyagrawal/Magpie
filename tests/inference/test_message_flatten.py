"""Unit tests for `_flatten_message_for_local` in src.llm — no model load.

Verifies the desktop-side message list (heterogeneous strings + binary
blocks for vision) is converted correctly to chat-completion format. Image
binary blocks are now collected into the second tuple element (forwarded
to the local vision profile via `complete(images=...)`); only non-image
binary blocks are dropped with a one-time warning.
"""

from __future__ import annotations

import pytest

from src.llm import _flatten_message_for_local


def test_strings_only_message() -> None:
    msgs, images = _flatten_message_for_local(
        ["hello", "world"], system_prompt="be helpful"
    )
    assert images == []
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "be helpful"
    assert msgs[1]["role"] == "user"
    assert "hello" in msgs[1]["content"]
    assert "world" in msgs[1]["content"]
    # Plus the JSON-output instruction we always append.
    assert "JSON" in msgs[1]["content"]


def test_image_binary_blocks_are_collected() -> None:
    """Image-typed BinaryContent blocks ride through to `images=[...]`
    so the local vision profile (Gemma 4 + mmproj) gets the bytes."""

    class FakeImage:
        data = b"\x89PNG\r\n\x1a\nfake-png-bytes"
        media_type = "image/png"

    msgs, images = _flatten_message_for_local(
        ["framing text", FakeImage(), "more text"],
        system_prompt="sys",
    )
    user_content = msgs[1]["content"]
    assert "framing text" in user_content
    assert "more text" in user_content
    # The image bytes don't leak into the text prompt.
    assert "PNG" not in user_content
    # And they show up in the second return value verbatim.
    assert images == [b"\x89PNG\r\n\x1a\nfake-png-bytes"]


def test_non_image_binary_blocks_are_dropped_with_warning() -> None:
    """Audio / arbitrary binary blocks aren't supported by the local
    backend yet — they get dropped with a one-time warning."""

    class FakeAudio:
        data = b"\x00\x01\x02"
        media_type = "audio/wav"

    with pytest.warns(UserWarning, match="non-image binary"):
        msgs, images = _flatten_message_for_local(
            ["framing text", FakeAudio()],
            system_prompt="sys",
        )
    assert images == []
    assert "framing text" in msgs[1]["content"]


def test_empty_message_list_yields_just_json_hint() -> None:
    msgs, images = _flatten_message_for_local([], system_prompt="sys")
    assert images == []
    assert msgs[0] == {"role": "system", "content": "sys"}
    # User message is just the JSON-output instruction (no actual content).
    assert "JSON" in msgs[1]["content"]
