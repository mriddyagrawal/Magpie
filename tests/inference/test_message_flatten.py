"""Unit tests for `_flatten_message_for_local` in src.llm — no model load.

Verifies the desktop-side message list (heterogeneous strings + binary
blocks for vision) is converted correctly to chat-completion format. Image
binary blocks are now collected into the second tuple element (forwarded
to the local vision profile via `complete(images=...)`); only non-image
binary blocks are dropped with a one-time warning.
"""

from __future__ import annotations

import pytest

from src.inference.image_slots import split_slots
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
    # The image's POSITION survives as a slot marker between its
    # neighbours, so the transport can put it back under its file header.
    pieces = split_slots(user_content)
    assert pieces[0] == "framing text\n\n" and pieces[1] == 0
    assert pieces[2].startswith("\n\nmore text")


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
    pieces = split_slots(msgs[1]["content"])
    assert [p for p in pieces if isinstance(p, int)] == [0, 1]
    assert pieces.index(0) < pieces.index("\n\n--- File 2 ---\n\n") < pieces.index(1)


def test_inline_images_off_leaves_no_markers() -> None:
    """Transports that drop the images (OpenRouter raw HTTP) must not
    ship a stray marker to the cloud model."""
    class Img:
        data = b"x"
        media_type = "image/png"

    msgs, images = _flatten_message_for_local(
        ["a", Img(), "b"], system_prompt="sys", inline_images=False,
    )
    assert images == [b"x"]
    assert "\x00" not in msgs[1]["content"]


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
