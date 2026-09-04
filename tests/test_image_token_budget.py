"""Image token budgeting (answer.py): dimension parsing, the calibrated
tile-math estimator, and the trimmer honoring resolution-dependent costs.

The estimator anchors are pinned to a llama-server calibration run
(2026-09-03, LFM2.5-VL-3B Q6_K + Q8_0 mmproj) — if the constants change,
re-run the calibration before updating the expected values here.
"""

from __future__ import annotations

from src.answer import (
    _block_cost_chars,
    _image_dimensions,
    _trim_blocks_to_budget,
    estimate_image_tokens,
)


# ---- header builders (no image library needed) ----------------------------


def _png(w: int, h: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big") + b"IHDR"
        + w.to_bytes(4, "big") + h.to_bytes(4, "big")
        + bytes(5)
    )


def _gif(w: int, h: int) -> bytes:
    return b"GIF89a" + w.to_bytes(2, "little") + h.to_bytes(2, "little") + bytes(20)


def _jpeg(w: int, h: int) -> bytes:
    # SOI + SOF0 frame header carrying (height, width).
    return (
        b"\xff\xd8\xff\xc0"
        + (17).to_bytes(2, "big") + b"\x08"
        + h.to_bytes(2, "big") + w.to_bytes(2, "big")
        + b"\x03" + bytes(12)
    )


def _webp_vp8x(w: int, h: int) -> bytes:
    return (
        b"RIFF" + (22).to_bytes(4, "little") + b"WEBP"
        + b"VP8X" + (10).to_bytes(4, "little")
        + bytes(4)
        + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    )


# ---- _image_dimensions -----------------------------------------------------


def test_dimensions_from_each_supported_header() -> None:
    assert _image_dimensions(_png(1080, 1920)) == (1080, 1920)
    assert _image_dimensions(_gif(640, 480)) == (640, 480)
    assert _image_dimensions(_jpeg(6913, 5382)) == (6913, 5382)
    assert _image_dimensions(_webp_vp8x(800, 600)) == (800, 600)


def test_dimensions_garbage_and_truncated_return_none() -> None:
    assert _image_dimensions(b"") is None
    assert _image_dimensions(b"not an image at all") is None
    assert _image_dimensions(_png(1080, 1920)[:12]) is None
    assert _image_dimensions(b"\xff\xd8" + b"\xff" * 40) is None


# ---- estimate_image_tokens (calibration anchors) ---------------------------


def test_estimator_matches_calibration_anchors() -> None:
    # measured image tokens on llama-server: 2304 / 1287 / 2290 / 1797 / 240
    assert estimate_image_tokens(1080, 1920) == 2419   # 8 tiles + thumb
    assert estimate_image_tokens(1024, 1024) == 1344   # 4 tiles + thumb
    assert estimate_image_tokens(2016, 1103) == 2419   # downscale is a no-op-ish
    assert estimate_image_tokens(6913, 5382) == 1881   # 37 MP → downscaled, 7 tiles
    assert estimate_image_tokens(591, 688) == 268      # single tile, no thumb


def test_estimator_never_underestimates_anchors() -> None:
    measured = {
        (1080, 1920): 2304, (1024, 1024): 1287, (2016, 1103): 2290,
        (6913, 5382): 1797, (591, 688): 240, (184, 326): 79,
    }
    for (w, h), tokens in measured.items():
        assert estimate_image_tokens(w, h) >= tokens


def test_estimator_invalid_dims_fall_back_conservatively() -> None:
    assert estimate_image_tokens(0, 0) == int(2560 * 1.05)
    assert estimate_image_tokens(-5, 100) == int(2560 * 1.05)


# ---- _block_cost_chars -----------------------------------------------------


class _FakeBinary:
    def __init__(self, data: bytes | None):
        self.data = data


def test_block_cost_text_is_length() -> None:
    assert _block_cost_chars("hello") == 5


def test_block_cost_image_uses_dimensions() -> None:
    cost = _block_cost_chars(_FakeBinary(_png(1080, 1920)))
    assert cost == int(2419 * 3.2)  # tokens × _CHARS_PER_TOKEN
    small = _block_cost_chars(_FakeBinary(_png(400, 300)))
    assert small == int(268 * 3.2)
    assert small < cost


def test_block_cost_unparseable_image_uses_fallback() -> None:
    assert _block_cost_chars(_FakeBinary(b"mystery bytes")) == int(int(2560 * 1.05) * 3.2)
    assert _block_cost_chars(_FakeBinary(None)) == int(int(2560 * 1.05) * 3.2)


# ---- trimmer integration ---------------------------------------------------


def test_trimmer_drops_whole_image_that_busts_budget() -> None:
    big_img = _FakeBinary(_png(1080, 1920))          # ~7,740 chars
    files = [
        ("a.txt", ["x" * 3_000]),
        ("b.jpg", [big_img]),
    ]
    kept = _trim_blocks_to_budget(files, budget_chars=5_000)
    names = [d for d, _ in kept]
    assert names == ["a.txt"]
    # the omission note names the dropped file
    note = kept[-1][1][-1]
    assert "b.jpg" in note and "omitted" in note


def test_trimmer_keeps_images_that_fit() -> None:
    small_img = _FakeBinary(_png(400, 300))          # ~857 chars
    files = [("a.jpg", [small_img]), ("b.jpg", [small_img])]
    kept = _trim_blocks_to_budget(files, budget_chars=5_000)
    assert [d for d, _ in kept] == ["a.jpg", "b.jpg"]


def test_trimmer_budget_reflects_resolution_not_flat_cost() -> None:
    # Two 1080p-class images (~7.7K chars each) must NOT both fit a 10K
    # budget — under the old flat 6,000 guess they would have, and the
    # request would have 400'd at the server instead.
    big = _FakeBinary(_png(1080, 1920))
    files = [("a.jpg", [big]), ("b.jpg", [big])]
    kept = _trim_blocks_to_budget(files, budget_chars=10_000)
    assert [d for d, _ in kept] == ["a.jpg"]
