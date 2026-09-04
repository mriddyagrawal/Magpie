"""Image token cost through the LFM2.5-VL mmproj - an exact mirror of
llama.cpp's LFM2 tiling math, shared by the answer-time context budget
(src/answer.py) and the drift tripwire (src/inference/local_llm.py).

Lives here, not in answer.py, because the transport layer must price the
images it is about to send without importing the answer stage above it.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Image token estimation (2026-09-03). The old flat 6,000-char guess
# (~1,875 tokens) undershot reality: LFM2.5-VL's mmproj tiles images into
# 512px patches (SigLIP2-NaFlex + pixel-unshuffle), so the token bill is
# resolution-DEPENDENT — a 1080×1920 screenshot measured 2,341 prompt
# tokens against llama-server (8 tiles × 256 + 256 thumbnail + text).
# Under-budgeting made the planner think 7 images fit a 16K window when
# they didn't: three eval questions died as HTTP 400s at 16.5-17.8K
# tokens. The estimator below is an exact mirror of llama.cpp's mtmd LFM2
# tiling (a first cut that rounded each side to a tile count under-counted
# common 4:3 and square sizes by 18-55% — review, 2026-09-03), verified
# token-exact on 23 sizes, and errs HIGH only via a 5% pad and a
# ceiling-valued fallback — the failure mode of guessing high is one fewer
# file in the prompt, not a rejected request.
# ---------------------------------------------------------------------------

# Constants mirror llama.cpp tools/mtmd (build 10502, commit 0adcc3bb5) for
# PROJECTOR_TYPE_LFM2 with LFM2.5-VL's processor_config: tile 512, patch 16,
# n_merge 2 (so align = 32 and 256 tokens per 512² tile), 2..10 tiles,
# image_max_pixels 512² with tolerance 2.0, thumbnail bounded to
# [64K, 256K] px. Re-verify with eval_harness/scripts/calibrate_image_tokens.py
# whenever the llama-server build or the model changes.
_IMG_TILE_PX = 512
_IMG_ALIGN = 32                       # patch_size × n_merge
_IMG_TOKENS_PER_TILE = 256            # (512/32)²
_IMG_MIN_TILES, _IMG_MAX_TILES = 2, 10
_IMG_TILE_AREA_TRIGGER = _IMG_TILE_PX * _IMG_TILE_PX * 2.0   # image_max_pixels × tolerance
_IMG_THUMB_MIN_PX = 64 * 1024         # image_min_pixels
_IMG_THUMB_MAX_PX = 256 * 1024        # image_max_pixels
_IMG_TOKEN_PAD = 1.05                 # insurance against upstream drift only
# Unparseable bytes → charge the true ceiling: 10 tiles + max thumbnail +
# markers (2,560 + 256 + 13). Worst case we drop one file too many, never a 400.
_IMG_FALLBACK_TOKENS = _IMG_MAX_TILES * _IMG_TOKENS_PER_TILE + 256 + _IMG_MAX_TILES + 3


def _image_dimensions(data: bytes) -> tuple[int, int] | None:
    """(width, height) from raw image bytes, header-only — no decoder.

    Covers the formats build_content_blocks emits (content.IMAGE_EXTS:
    png/jpeg/webp/gif) plus the PNGs render_pdf_pages_as_png produces.
    Returns None when the header doesn't parse; callers fall back to a
    conservative constant."""
    try:
        if len(data) < 24:
            return None
        # PNG: 8-byte signature, then IHDR chunk — width/height at 16..24.
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(data[16:20], "big")
            h = int.from_bytes(data[20:24], "big")
            return (w, h) if w and h else None
        # GIF: "GIF87a"/"GIF89a", then 16-bit LE logical screen size.
        if data[:6] in (b"GIF87a", b"GIF89a"):
            w = int.from_bytes(data[6:8], "little")
            h = int.from_bytes(data[8:10], "little")
            return (w, h) if w and h else None
        # WEBP: RIFF container; VP8X carries 24-bit LE dims minus one.
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X" and len(data) >= 30:
                w = int.from_bytes(data[24:27], "little") + 1
                h = int.from_bytes(data[27:30], "little") + 1
                return (w, h)
            if chunk == b"VP8 " and len(data) >= 30:
                w = int.from_bytes(data[26:28], "little") & 0x3FFF
                h = int.from_bytes(data[28:30], "little") & 0x3FFF
                return (w, h) if w and h else None
            if chunk == b"VP8L" and len(data) >= 25:
                bits = int.from_bytes(data[21:25], "little")
                w = (bits & 0x3FFF) + 1
                h = ((bits >> 14) & 0x3FFF) + 1
                return (w, h)
            return None
        # JPEG: walk the marker segments to the first SOFn frame header.
        if data[:2] == b"\xff\xd8":
            i = 2
            n = len(data)
            while i + 9 < n:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
                # SOF0-15 minus DHT(C4)/JPG(C8)/DAC(CC): frame header with dims
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h = int.from_bytes(data[i + 5 : i + 7], "big")
                    w = int.from_bytes(data[i + 7 : i + 9], "big")
                    return (w, h) if w and h else None
                i += 2 + seg_len
            return None
    except Exception:  # noqa: BLE001 — a parse failure must never break answering
        return None
    return None


def _thumbnail_size(width: int, height: int) -> tuple[int, int]:
    """mtmd's calc_size_preserved_ratio for the overview image: round each
    side to the 32-px grid, then scale into [64K, 256K] px preserving
    aspect (floor when shrinking, ceil when growing)."""
    import math
    rnd = lambda x: max(_IMG_ALIGN, int(round(x / _IMG_ALIGN)) * _IMG_ALIGN)  # noqa: E731
    w_bar, h_bar = rnd(width), rnd(height)
    if w_bar * h_bar > _IMG_THUMB_MAX_PX:
        beta = math.sqrt(width * height / _IMG_THUMB_MAX_PX)
        w_bar = max(_IMG_ALIGN, int(math.floor(width / beta / _IMG_ALIGN)) * _IMG_ALIGN)
        h_bar = max(_IMG_ALIGN, int(math.floor(height / beta / _IMG_ALIGN)) * _IMG_ALIGN)
    elif w_bar * h_bar < _IMG_THUMB_MIN_PX:
        beta = math.sqrt(_IMG_THUMB_MIN_PX / (width * height))
        w_bar = int(math.ceil(width * beta / _IMG_ALIGN)) * _IMG_ALIGN
        h_bar = int(math.ceil(height * beta / _IMG_ALIGN)) * _IMG_ALIGN
    return w_bar, h_bar


def _best_grid(width: int, height: int) -> tuple[int, int]:
    """mtmd's find_closest_aspect_ratio over every (cols, rows) with
    2 <= cols*rows <= 10: closest aspect ratio wins; on an exact tie the
    larger grid wins only if the image covers more than half its area."""
    aspect = width / height
    area = width * height
    best, best_diff = (1, 1), float("inf")
    candidates: list[tuple[int, int]] = []
    for n in range(_IMG_MIN_TILES, _IMG_MAX_TILES + 1):
        for cols in range(1, n + 1):
            for rows in range(1, n + 1):
                if _IMG_MIN_TILES <= cols * rows <= _IMG_MAX_TILES and (cols, rows) not in candidates:
                    candidates.append((cols, rows))
    candidates.sort(key=lambda g: g[0] * g[1])
    for cols, rows in candidates:
        diff = abs(aspect - cols / rows)
        if diff < best_diff:
            best, best_diff = (cols, rows), diff
        elif diff == best_diff and area > 0.5 * _IMG_TILE_PX * _IMG_TILE_PX * cols * rows:
            best = (cols, rows)
    return best


def estimate_image_tokens(width: int, height: int) -> int:
    """Predicted LM token cost of one image through the LFM2.5-VL mmproj —
    an exact mirror of llama.cpp's LFM2 tiling, plus a 5% pad.

    Untiled (rounded area <= 512² × 2): one overview image costing
    thumbnail tokens + 2 markers (79..258 tokens). Tiled: the closest-aspect
    grid of 2..10 tiles at 256 tokens each, plus the thumbnail, plus one
    marker per tile and 3 more.

    Verified token-exact against llama-server on 23 sizes from 184×326 to
    6913×5382 (2026-09-03; see calibrate_image_tokens.py). E.g. 1080×1920 =
    8×256 + 252 + 11 = 2,311; 1024×768 = 6×256 + 234 + 9 = 1,779;
    800×600 = 234 + 2 = 236.
    """
    if width <= 0 or height <= 0:
        return int(_IMG_FALLBACK_TOKENS * _IMG_TOKEN_PAD)
    tw, th = _thumbnail_size(width, height)
    thumb = (tw // _IMG_ALIGN) * (th // _IMG_ALIGN)
    rnd = lambda x: max(_IMG_ALIGN, int(round(x / _IMG_ALIGN)) * _IMG_ALIGN)  # noqa: E731
    if rnd(width) * rnd(height) <= _IMG_TILE_AREA_TRIGGER:
        return int((thumb + 2) * _IMG_TOKEN_PAD)
    cols, rows = _best_grid(width, height)
    tiles = cols * rows
    tokens = tiles * _IMG_TOKENS_PER_TILE + thumb + tiles + 3
    return int(tokens * _IMG_TOKEN_PAD)
