"""Calibrate `src.answer.estimate_image_tokens` against a live llama-server.

The estimator mirrors llama.cpp's LFM2 mtmd tiling math (build 10502). That
math is upstream code we don't control, so this script is the drift check:
it sends one synthetic PNG per size to a running llama-server with the
vision model + mmproj loaded, subtracts a text-only baseline from
`usage.prompt_tokens`, and compares with the estimator. Exit code 1 on ANY
under-estimate (that is the failure that becomes an HTTP 400 in
production); over-estimates are reported but pass.

    # boot a throwaway server first (any free port), e.g.
    #   ~/Library/Application\\ Support/Magpie/bin/llama-server \\
    #       -m <LFM2.5-VL-3B-Q6_K.gguf> --mmproj <mmproj-...-Q8_0.gguf> \\
    #       --port 9187 -c 32768
    uv run python eval_harness/scripts/calibrate_image_tokens.py --port 9187

Stdlib only (PNGs are written by hand): runs in under a minute.
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import urllib.request
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.answer import estimate_image_tokens  # noqa: E402

# Sizes chosen to cover: untiled (< 512²×2 px), each grid family up to 10
# tiles, both orientations, extreme aspects, common screen/scan/photo sizes.
# The six marked * are where per-dimension rounding (the first cut of the
# estimator) under-counted by 18-55% — regression guards.
DEFAULT_SIZES: list[tuple[int, int]] = [
    (184, 326), (591, 688), (800, 600), (1024, 768),   # *
    (1024, 1024), (1080, 1920), (1200, 1200),          # *
    (1280, 960), (1280, 1280), (1366, 768),            # * * *
    (700, 1100),                                       # *
    (1500, 1500), (3000, 1000), (1000, 4000),
    (1275, 1650), (1240, 1754), (2016, 1103), (1025, 300),
    (6913, 5382), (2560, 1440), (3840, 2160), (512, 512), (1024, 1025),
]


def synthetic_png(w: int, h: int) -> bytes:
    """A valid RGB PNG of the given size (content is irrelevant to token
    count; a cheap deterministic pattern keeps the file small)."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
    row = bytes([0]) + bytes((x * 7 + 13) & 0xFF for x in range(w * 3))
    raw = row * h
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1))
            + chunk(b"IEND", b""))


def prompt_tokens(port: int, content: list) -> int:
    body = {"messages": [{"role": "user", "content": content}],
            "max_tokens": 1, "temperature": 0}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["usage"]["prompt_tokens"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9187)
    ap.add_argument("--sizes", help="comma list like 1024x768,800x600 (default: built-in set)")
    args = ap.parse_args()

    sizes = DEFAULT_SIZES
    if args.sizes:
        sizes = [tuple(int(v) for v in s.lower().split("x")) for s in args.sizes.split(",")]

    text = "Describe."
    base = prompt_tokens(args.port, [{"type": "text", "text": text}])
    print(f"text-only baseline: {base} tokens\n")
    print(f"{'size':>10} {'measured':>8} {'estimate':>8} {'ratio':>6}")
    under = 0
    for w, h in sizes:
        b64 = base64.b64encode(synthetic_png(w, h)).decode()
        n = prompt_tokens(args.port, [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]) - base
        est = estimate_image_tokens(w, h)
        flag = "  <-- UNDER" if est < n else ""
        under += est < n
        print(f"{w}x{h:<5} {n:>8} {est:>8} {est / n:>6.2f}{flag}")
    print()
    if under:
        print(f"FAIL: {under} size(s) under-estimated - the tiling math has drifted "
              f"from llama.cpp; update src/answer.py estimate_image_tokens")
        return 1
    print("OK: estimator >= measured for every size")
    return 0


if __name__ == "__main__":
    sys.exit(main())
