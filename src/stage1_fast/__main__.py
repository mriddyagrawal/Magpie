"""Smoke-test the fast-tier model: embed pages of a PDF or one image.

Usage:
    uv run python -m src.stage1_fast <path-to-pdf-or-image>

Prints the detected device, model, and the output tensor shape for the first
few pages. A successful run means stages 0-1 are wired correctly end-to-end.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


MAX_PAGES_PREVIEW = 3


def _render_pdf_pages(path: Path, max_pages: int) -> list:
    from PIL import Image
    import pymupdf

    doc = pymupdf.open(path)
    images: list[Image.Image] = []
    for i in range(min(len(doc), max_pages)):
        pix = doc[i].get_pixmap(dpi=150)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    doc.close()
    return images


def _load_image(path: Path) -> list:
    from PIL import Image

    return [Image.open(path).convert("RGB")]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="PDF or image file to embed")
    parser.add_argument("--pages", type=int, default=MAX_PAGES_PREVIEW,
                        help=f"Max pages to render (default {MAX_PAGES_PREVIEW})")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.is_file():
        sys.exit(f"error: no such file: {path}")

    from src.stage1_fast.device import COLQWEN_MODEL_ID, detect_device
    from src.stage1_fast.model import encode_images, get_model

    # Make HF hub progress bars verbose even when running non-interactively.
    import os
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "info")

    cfg = detect_device()
    size_hint = "~6 GB" if cfg.model_id == COLQWEN_MODEL_ID else "~1 GB"

    # Quick detection of free VRAM so we can show it in the banner.
    vram_info = ""
    try:
        import torch
        if cfg.device == "cuda":
            free_b, total_b = torch.cuda.mem_get_info(0)
            vram_info = f" | VRAM {free_b / 1024**3:.1f}/{total_b / 1024**3:.1f} GB free"
    except Exception:  # pylint: disable=broad-except
        pass

    bar = "─" * 72
    print(bar)
    print(f"  Fast-tier model: {cfg.model_id}")
    print(f"  Device:          {cfg.device}{vram_info}")
    print(f"  Dtype:           {cfg.dtype}   Batch size: {cfg.batch_size}")
    print(f"  Cache location:  {os.environ.get('HF_HOME', os.path.expanduser('~/.cache/huggingface'))}")
    print(bar)
    print(f"loading model (first run downloads {size_hint} from HuggingFace)...")
    t0 = time.monotonic()
    _, _, _ = get_model()
    print(f"  loaded in {time.monotonic() - t0:.1f}s")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        images = _render_pdf_pages(path, args.pages)
    elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        images = _load_image(path)
    else:
        sys.exit(f"error: unsupported suffix {suffix}")

    print(f"rendered {len(images)} page(s) from {path.name}")

    t0 = time.monotonic()
    embeddings = encode_images(images)
    elapsed = time.monotonic() - t0
    shape = tuple(embeddings.shape) if hasattr(embeddings, "shape") else "(unknown)"
    print(f"encoded in {elapsed:.2f}s ({elapsed / len(images):.2f}s/page)")
    print(f"  output shape: {shape}")
    print(f"  dtype:        {embeddings.dtype}")


if __name__ == "__main__":
    main()
