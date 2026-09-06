"""The request log records inline image parts by size, never by pixels."""

from src.inference.llm_log import _truncate


def test_image_bytes_are_replaced_by_size_placeholder() -> None:
    rec = _truncate([{"role": "user", "content": [
        {"type": "text", "text": "t"},
        {"type": "image", "data": b"\x89PNG" * 100, "media_type": "image/png"},
    ]}])
    part = rec[0]["content"][1]
    assert part["data"] == "<400 bytes>"
    assert part["media_type"] == "image/png"
