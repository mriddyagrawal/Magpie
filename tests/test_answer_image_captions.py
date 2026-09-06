"""Per-image captions in the answer prompt (multi-image files only)."""

from __future__ import annotations

from src.answer import _captioned


class _Img:
    def __init__(self, tag: str) -> None:
        self.data = tag.encode()
        self.media_type = "image/png"


def test_single_image_file_gets_no_caption() -> None:
    blocks = ["Content type: image", _Img("only")]
    assert _captioned(blocks, 3) == blocks


def test_text_only_file_is_untouched() -> None:
    blocks = ["Content type: pdf\n\n---\nbody"]
    assert _captioned(blocks, 1) == blocks


def test_multi_page_scan_gets_numbered_captions_in_order() -> None:
    p1, p2, p3 = _Img("1"), _Img("2"), _Img("3")
    out = _captioned(["Content type: pdf (scanned)", p1, p2, p3], 2)
    assert out == [
        "Content type: pdf (scanned)",
        "[File 2, image 1 of 3]", p1,
        "[File 2, image 2 of 3]", p2,
        "[File 2, image 3 of 3]", p3,
    ]
