"""Turn a pixels-only file into a text transcript, once, at index time.

Scanned PDFs, photographed receipts, screenshots and flyers carry no text
layer, so `content.py` used to hand their pixels to the answering model on
every question. The 2026-08-25 spike showed that reading pixels at answer
time is both the slow path (an image is 1-2K tokens and can never be
prefix-cached) and the inaccurate one (1/12 locally), while a transcript
written ONCE at index time and read as text scored 7/12 in cloud mode.

This module is the one place that pixel->text conversion lives. Two
backends produce the same file format so they can be swapped and compared:

  - `ocr`: RapidOCR (PaddleOCR detection + recognition models, ONNX
    runtime, CPU). Character-level recognizer: strong on printed digits,
    tenths of a second per page, ~100 MB of wheels, no llama-server. Words
    are regrouped into lines by their box geometry, so a table row stays
    one line.
  - `vlm`: the local vision-language model through llama-server (whatever
    `LLAMA_SERVER_VISION_MODEL` resolves to — LFM2.5-VL-3B by default,
    450M / 1.6B by env override). Reads handwriting and skewed phone
    photos; seconds per page; known to garble digits occasionally.

Transcripts land in `content.transcript_path_for(path)` (honours
`MAGPIE_TRANSCRIPTS_DIR`), and `content.build_content_blocks` serves them
to the answer stage instead of pixels for both scanned PDFs and standalone
images. The eyes-only comparison of the two backends is
`Evaluations/transcript_recall.py`.
"""

from __future__ import annotations

import io
import os
import statistics
import time
from pathlib import Path

from src.content import IMAGE_EXTS, PDF_EXTS, transcript_path_for

BACKENDS = ("ocr", "vlm")

# Pages per file. Receipts and forms are 1-3 pages; the cap keeps a
# 40-page scanned booklet from monopolising index time. Env-overridable for
# a full-corpus sweep.
MAX_PAGES = int(os.environ.get("MAGPIE_TRANSCRIBE_MAX_PAGES", "8"))
DPI = 200
OCR_THREADS = int(os.environ.get("MAGPIE_OCR_THREADS", "4"))

# The VLM prompt asks for markdown tables where the page HAS a table — a
# 5-column bank statement cannot be represented as label/value lines, and the
# reader handles pipe tables far better than comma soup. But the first
# wording ("write any table as a markdown table") made LFM2.5-VL-3B emit
# ONLY the item table and drop the receipt header — company, address, date
# went missing on most SROIE receipts (2026-08-29, 14:xx run: date 37/60,
# company 32/60 while total was 57/60). So: everything first, tables where
# they occur. MAGPIE_VLM_PROMPT overrides for experiments.
VLM_PROMPT = os.environ.get("MAGPIE_VLM_PROMPT") or (
    "Transcribe ALL the text on this page, top to bottom, faithfully and "
    "completely: every heading, name, address, date, phone number, line item, "
    "amount, and footer, exactly as printed or handwritten. Where a region of "
    "the page is a table, write that region as a markdown table with a header "
    "row; write everything else as plain lines. If part is illegible, write "
    "[illegible] rather than guessing. Output only the transcription."
)


def is_pixel_file(path: Path) -> bool:
    """True for files that have no text layer to extract: images always, PDFs
    only when text extraction comes back empty."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return True
    if ext in PDF_EXTS:
        from src.content import extract_pdf_text

        try:
            return not (extract_pdf_text(path, 4000) or "").strip()
        except Exception:  # noqa: BLE001 — unreadable counts as scanned
            return True
    return False


def render_pages(path: Path, max_pages: int = MAX_PAGES, dpi: int = DPI) -> tuple[list[bytes], int]:
    """PNG bytes per page (an image is one page) and the file's total page
    count, so the transcript header can say '3 of 12'."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        from PIL import Image

        with Image.open(path) as im:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="PNG")
        return [buf.getvalue()], 1
    if ext in PDF_EXTS:
        import pymupdf

        doc = pymupdf.open(str(path))
        pages = [doc[i].get_pixmap(dpi=dpi).tobytes("png") for i in range(min(len(doc), max_pages))]
        return pages, len(doc)
    raise ValueError(f"not a pixel file: {path}")


# --- backends ---------------------------------------------------------------

_ocr_engine = None


def ocr_page(png: bytes) -> str:
    """RapidOCR over one page, words regrouped into reading-order lines.

    The engine returns one box per detected text fragment in no particular
    order. Fragments whose vertical centres sit within ~60% of the median
    box height are one line; each line is sorted left-to-right. That keeps
    a table row on one line and a two-column layout from interleaving too
    badly (a column gap wider than three spaces is rendered as ' | ' so the
    reader sees the cell boundary).
    """
    global _ocr_engine
    if _ocr_engine is None:
        import tempfile

        import cv2
        from rapidocr_onnxruntime import RapidOCR
        from rapidocr_onnxruntime.main import DEFAULT_CFG_PATH

        # RapidOCR's shipped config gives each of its three ONNX sessions
        # intra_op_num_threads -1 (= every core). On a 16-core box that is
        # ~50 threads fighting over the CPU: measured 17-41 s per receipt at a
        # load average of 48 (2026-08-29), where the same page takes about a
        # second with a few threads. Cap it; MAGPIE_OCR_THREADS overrides.
        text = Path(DEFAULT_CFG_PATH).read_text(encoding="utf-8")
        text = text.replace(
            "intra_op_num_threads: &intra_nums -1", f"intra_op_num_threads: &intra_nums {OCR_THREADS}"
        ).replace("inter_op_num_threads: &inter_nums -1", "inter_op_num_threads: &inter_nums 1")
        cfg = Path(tempfile.gettempdir()) / f"magpie_rapidocr_{OCR_THREADS}t.yaml"
        cfg.write_text(text, encoding="utf-8")
        cv2.setNumThreads(OCR_THREADS)
        _ocr_engine = RapidOCR(config_path=str(cfg))

    import numpy as np
    from PIL import Image

    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    result, _elapsed = _ocr_engine(arr)
    if not result:
        return ""

    frags = []
    for box, text, _score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        frags.append({
            "x0": min(xs), "x1": max(xs),
            "yc": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys),
            "text": text.strip(),
        })
    frags = [f for f in frags if f["text"]]
    if not frags:
        return ""

    tol = statistics.median(f["h"] for f in frags) * 0.6
    frags.sort(key=lambda f: f["yc"])
    lines: list[list[dict]] = [[frags[0]]]
    for f in frags[1:]:
        line_yc = statistics.mean(g["yc"] for g in lines[-1])
        if abs(f["yc"] - line_yc) <= tol:
            lines[-1].append(f)
        else:
            lines.append([f])

    # a gap wider than ~3 character widths marks a column boundary
    char_w = statistics.median(
        (f["x1"] - f["x0"]) / max(len(f["text"]), 1) for f in frags
    )
    out = []
    for line in lines:
        line.sort(key=lambda f: f["x0"])
        pieces = [line[0]["text"]]
        for prev, cur in zip(line, line[1:]):
            sep = " | " if cur["x0"] - prev["x1"] > 3 * char_w else " "
            pieces.append(sep + cur["text"])
        out.append("".join(pieces))
    return "\n".join(out)


def vlm_page(png: bytes) -> str:
    from src.inference.local_llm import get_local_llm

    return get_local_llm().complete_sync(
        [{"role": "user", "content": VLM_PROMPT}],
        images=[png], temperature=0.1, max_tokens=1200,
    ).strip()


# --- the one entry point ----------------------------------------------------

def transcribe(path: Path, backend: str, max_pages: int = MAX_PAGES) -> dict:
    """Transcribe `path` with `backend`; returns {text, pages, total_pages,
    seconds}. Does not write anything — `write_transcript` does."""
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS}, got {backend!r}")
    t0 = time.perf_counter()
    pngs, total = render_pages(path, max_pages)
    read = ocr_page if backend == "ocr" else vlm_page
    pages = [read(png) for png in pngs]
    body = "\n\n".join(
        f"## Page {i}\n\n{text}" for i, text in enumerate(pages, 1) if text.strip()
    )
    return {
        "text": body,
        "pages": len(pages),
        "total_pages": total,
        "seconds": time.perf_counter() - t0,
        "chars": len(body),
    }


def write_transcript(path: Path, backend: str, max_pages: int = MAX_PAGES) -> tuple[Path, dict]:
    """Transcribe and save to `transcript_path_for(path)`. An empty result
    (a photo with no text) still writes a stub so the file is not retried on
    every sweep; `content.transcript_for` treats an empty body as None."""
    result = transcribe(path, backend, max_pages)
    out = transcript_path_for(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Transcript ({backend})\n\nSource: {path}\n"
        f"Pages transcribed: {result['pages']} of {result['total_pages']}\n\n"
    )
    out.write_text(header + result["text"] + ("\n" if result["text"] else ""), encoding="utf-8")
    return out, result
