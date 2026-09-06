"""Unit tests for `_flatten_message_for_local` in src.llm — no model load.

Verifies the desktop-side message list (heterogeneous strings + binary
blocks for vision) is converted correctly to chat-completion format. Image
binary blocks become inline `{"type": "image"}` parts in document order
(rendered under their file header by `local_llm._prepare`); only non-image
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


def test_image_binary_blocks_become_inline_parts_in_document_order() -> None:
    """Image-typed BinaryContent blocks become `{"type": "image"}` parts
    at their own position, so the transport renders each one under its
    file header instead of after all the text."""

    class FakeImage:
        data = b"\x89PNG\r\n\x1a\nfake-png-bytes"
        media_type = "image/png"

    msgs, images = _flatten_message_for_local(
        ["framing text", FakeImage(), "more text"],
        system_prompt="sys",
    )
    parts = msgs[1]["content"]
    assert [p["type"] for p in parts] == ["text", "image", "text"]
    assert parts[0]["text"] == "framing text"
    assert parts[1] == {"type": "image", "data": FakeImage.data, "media_type": "image/png"}
    assert parts[2]["text"].startswith("more text")
    assert "JSON" in parts[2]["text"]          # the hint rides on the last text run
    assert images == [FakeImage.data]


def test_images_keep_document_order_across_files() -> None:
    class Img:
        media_type = "image/png"

        def __init__(self, data: bytes) -> None:
            self.data = data

    msgs, images = _flatten_message_for_local(
        ["q", "--- File 1 ---", Img(b"one"), "--- File 2 ---", Img(b"two"), "again q"],
        system_prompt="sys",
    )
    assert images == [b"one", b"two"]
    parts = msgs[1]["content"]
    assert [p["type"] for p in parts] == ["text", "image", "text", "image", "text"]
    assert parts[0]["text"] == "q\n\n--- File 1 ---"      # adjacent strings merge
    assert parts[1]["data"] == b"one"
    assert parts[2]["text"] == "--- File 2 ---"
    assert parts[3]["data"] == b"two"


def test_trailing_image_still_gets_the_json_hint_after_it() -> None:
    class Img:
        data = b"x"
        media_type = "image/png"

    msgs, _ = _flatten_message_for_local(["look", Img()], system_prompt="sys")
    parts = msgs[1]["content"]
    assert [p["type"] for p in parts] == ["text", "image", "text"]
    assert "JSON" in parts[2]["text"]


def test_inline_images_off_yields_plain_string_and_reports_dropped_blobs() -> None:
    """Transports that drop the images (OpenRouter raw HTTP, a LocalAgent
    with no vision profile) get the old text-only string."""
    class Img:
        data = b"x"
        media_type = "image/png"

    msgs, images = _flatten_message_for_local(
        ["a", Img(), "b"], system_prompt="sys", inline_images=False,
    )
    assert images == [b"x"]
    assert isinstance(msgs[1]["content"], str)
    assert msgs[1]["content"].startswith("a\n\nb")


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
