"""Image token budgeting (answer.py): dimension parsing, the exact mirror
of llama.cpp's LFM2 tiling math, and the trimmer honoring
resolution-dependent costs.

MEASURED anchors below were read off a live llama-server (build 10502,
LFM2.5-VL-3B Q6_K + Q8_0 mmproj, 2026-09-03) via
eval_harness/scripts/calibrate_image_tokens.py — synthetic PNG per size,
text-only baseline subtracted from usage.prompt_tokens. The estimator is
expected to be token-exact before its 5% pad; re-run the script (not this
file) if a llama-server or model upgrade changes the numbers.
"""

from __future__ import annotations

import pytest

from src.answer import (
    _IMG_FALLBACK_TOKENS,
    _IMG_TOKEN_PAD,
    _block_cost_chars,
    _image_dimensions,
    _trim_blocks_to_budget,
    estimate_image_tokens,
)

# (width, height) -> image tokens measured on llama-server. Includes the six
# sizes (marked) where the first-cut per-dimension rounding under-counted.
MEASURED: dict[tuple[int, int], int] = {
    (184, 326): 79,
    (591, 688): 240,
    (800, 600): 236,
    (1024, 768): 1779,     # under-counted by v1 (0.76×)
    (1024, 1024): 1287,
    (1080, 1920): 2311,
    (1200, 1200): 2572,    # under-counted by v1 (0.52×)
    (1280, 960): 1779,     # under-counted by v1 (0.76×)
    (1280, 1280): 2572,    # under-counted by v1 (0.52×)
    (1366, 768): 2290,     # under-counted by v1 (0.82×)
    (700, 1100): 1785,     # under-counted by v1 (0.45×)
    (1500, 1500): 2572,
    (3000, 1000): 1017,
    (1000, 4000): 1287,
    (1275, 1650): 1797,    # 150-dpi US letter
    (1240, 1754): 1792,    # 150-dpi A4
    (2016, 1103): 2290,
    (1025, 300): 234,
    (6913, 5382): 1797,    # 37 MP scan
    (2560, 1440): 2311,
    (3840, 2160): 2311,
    (512, 512): 258,
    (1024, 1025): 1271,
}


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


# ---- estimate_image_tokens: exact mirror + pad -----------------------------


@pytest.mark.parametrize(("size", "measured"), sorted(MEASURED.items()))
def test_estimator_is_measured_times_pad(size: tuple[int, int], measured: int) -> None:
    w, h = size
    assert estimate_image_tokens(w, h) == int(measured * _IMG_TOKEN_PAD)


def test_estimator_never_underestimates_any_measured_size() -> None:
    for (w, h), measured in MEASURED.items():
        assert estimate_image_tokens(w, h) >= measured, (w, h)


def test_estimator_decomposition_examples() -> None:
    # 1080×1920: 8 tiles×256 + thumbnail 12×21=252 + markers 8+3 = 2,311
    assert int(2311 * _IMG_TOKEN_PAD) == estimate_image_tokens(1080, 1920)
    # 800×600: untiled — thumbnail 18×13=234 + 2 markers = 236
    assert int(236 * _IMG_TOKEN_PAD) == estimate_image_tokens(800, 600)


def test_estimator_invalid_dims_use_ceiling_fallback() -> None:
    ceiling = int(_IMG_FALLBACK_TOKENS * _IMG_TOKEN_PAD)
    assert _IMG_FALLBACK_TOKENS == 2829  # 10 tiles + 256 thumbnail + 13 markers
    assert estimate_image_tokens(0, 0) == ceiling
    assert estimate_image_tokens(-5, 100) == ceiling
    # the ceiling really is above every measured size
    assert ceiling >= max(MEASURED.values())


# ---- _block_cost_chars -----------------------------------------------------


class _FakeBinary:
    def __init__(self, data: bytes | None):
        self.data = data


def test_block_cost_text_is_length() -> None:
    assert _block_cost_chars("hello") == 5


def test_block_cost_image_uses_dimensions() -> None:
    big = _block_cost_chars(_FakeBinary(_png(1080, 1920)))
    assert big == int(int(2311 * _IMG_TOKEN_PAD) * 3.2)  # tokens × _CHARS_PER_TOKEN
    small = _block_cost_chars(_FakeBinary(_png(800, 600)))
    assert small == int(int(236 * _IMG_TOKEN_PAD) * 3.2)
    assert small < big


def test_block_cost_unparseable_image_uses_ceiling() -> None:
    expected = int(int(_IMG_FALLBACK_TOKENS * _IMG_TOKEN_PAD) * 3.2)
    assert _block_cost_chars(_FakeBinary(b"mystery bytes")) == expected
    assert _block_cost_chars(_FakeBinary(None)) == expected


# ---- trimmer integration ---------------------------------------------------


def test_trimmer_drops_whole_image_that_busts_budget() -> None:
    big_img = _FakeBinary(_png(1080, 1920))          # ~7,760 chars
    files = [
        ("a.txt", ["x" * 3_000]),
        ("b.jpg", [big_img]),
    ]
    kept = _trim_blocks_to_budget(files, budget_chars=5_000)
    assert [d for d, _ in kept] == ["a.txt"]
    note = kept[-1][1][-1]
    assert "b.jpg" in note and "omitted" in note


def test_trimmer_keeps_images_that_fit() -> None:
    small_img = _FakeBinary(_png(800, 600))          # ~790 chars
    files = [("a.jpg", [small_img]), ("b.jpg", [small_img])]
    kept = _trim_blocks_to_budget(files, budget_chars=5_000)
    assert [d for d, _ in kept] == ["a.jpg", "b.jpg"]


def test_trimmer_budget_reflects_resolution_not_flat_cost() -> None:
    # Two 1080p-class images (~7.8K chars each) must NOT both fit a 10K
    # budget — under the old flat 6,000 guess they would have, and the
    # request would have 400'd at the server instead.
    big = _FakeBinary(_png(1080, 1920))
    files = [("a.jpg", [big]), ("b.jpg", [big])]
    kept = _trim_blocks_to_budget(files, budget_chars=10_000)
    assert [d for d, _ in kept] == ["a.jpg"]


def test_xga_screenshot_budget_matches_real_tokens() -> None:
    # The reviewer's scenario: 1024×768 measured 1,779 tokens but v1
    # estimated 1,344, so v1 would have packed 9 of them into the 13,384-token
    # document budget (16,384 ctx - 3,000 reserve) — 16,011 real tokens, a
    # guaranteed HTTP 400. The exact estimator keeps 7 (13,069 padded).
    budget_chars = int(13_384 * 3.2)
    img = _FakeBinary(_png(1024, 768))
    files = [(f"{i}.png", [img]) for i in range(8)]
    kept = _trim_blocks_to_budget(files, budget_chars=budget_chars)
    assert len(kept) == 7
    assert 7 * int(1779 * _IMG_TOKEN_PAD) <= 13_384 < 8 * int(1779 * _IMG_TOKEN_PAD)
