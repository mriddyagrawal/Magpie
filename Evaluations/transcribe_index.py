"""Index-time vision transcription for scanned PDFs (spike).

For every PDF under a corpus root whose text extraction comes back empty
(scanned/image-only), render each page and have the local VL model write a
faithful text transcript. Saved to <APP_DATA_DIR>/transcripts/<key>.md;
src/content.py serves the transcript to the answer stage instead of pixels.

Reversible: --remove deletes the transcripts directory. Measurement plan:
re-run the scanned-question eval block and compare (pre-registered gate in
the session log: local >= 5/12 with no text-question regression).

Usage:
    uv run python Evaluations/transcribe_index.py --corpus "C:\\...\\college data"
    uv run python Evaluations/transcribe_index.py --remove
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

MAX_PAGES = 8
DPI = 200

PROMPT = (
    "Transcribe this document page into plain text, faithfully and completely. "
    "Include every number, name, date, amount, and table value exactly as "
    "printed or handwritten. Preserve table structure with simple lines "
    "('Label: value'). If part is illegible, write [illegible] rather than "
    "guessing. Output only the transcription."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=str, default=None)
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    from src.manifest import APP_DATA_DIR

    tdir = APP_DATA_DIR / "transcripts"
    if args.remove:
        shutil.rmtree(tdir, ignore_errors=True)
        print("transcripts directory removed")
        return 0
    if not args.corpus:
        ap.error("--corpus required unless --remove")

    import pymupdf

    from src.content import extract_pdf_text, transcript_path_for
    from src.inference.local_llm import get_local_llm

    root = Path(args.corpus)
    pdfs = sorted(root.rglob("*.pdf")) + sorted(root.rglob("*.PDF"))
    llm = get_local_llm()
    tdir.mkdir(parents=True, exist_ok=True)

    done = skipped = failed = 0
    t0 = time.time()
    for i, path in enumerate(pdfs, 1):
        out = transcript_path_for(path)
        if out.exists():
            skipped += 1
            continue
        try:
            text = ""
            try:
                text = (extract_pdf_text(path) or "").strip()
            except Exception:  # noqa: BLE001 — treat unreadable as scanned
                text = ""
            if text:
                skipped += 1  # real text layer — no transcript needed
                continue
            doc = pymupdf.open(str(path))
            pages = []
            for pno in range(min(len(doc), MAX_PAGES)):
                png = doc[pno].get_pixmap(dpi=DPI).tobytes("png")
                page_text = llm.complete_sync(
                    [{"role": "user", "content": PROMPT}],
                    images=[png], temperature=0.1, max_tokens=900,
                )
                pages.append(f"## Page {pno + 1}\n\n{page_text.strip()}")
            if not pages:
                skipped += 1
                continue
            body = (
                f"# Vision transcript\n\nSource: {path}\n"
                f"Pages transcribed: {len(pages)} of {len(doc)}\n\n"
                + "\n\n".join(pages) + "\n"
            )
            out.write_text(body, encoding="utf-8")
            done += 1
            print(f"[{i}/{len(pdfs)}] ({(time.time()-t0)/60:.1f}min) "
                  f"transcribed {path.name} ({len(pages)}p)", flush=True)
        except Exception as e:  # noqa: BLE001 — skip and continue
            failed += 1
            print(f"[{i}/{len(pdfs)}] FAIL {path.name}: {type(e).__name__}: {e}",
                  flush=True)
    print(f"\ndone: {done} transcribed, {skipped} skipped (text or existing), "
          f"{failed} failed, {(time.time()-t0)/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
