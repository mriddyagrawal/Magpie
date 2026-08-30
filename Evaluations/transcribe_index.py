"""Index-time transcription for pixels-only files: scanned PDFs and images.

Walks a corpus root, finds every file with no text layer (images always;
PDFs whose extraction comes back empty), and writes a text transcript with
the chosen backend to `MAGPIE_TRANSCRIPTS_DIR` (or the app's default
transcripts folder). `src/content.py` then serves the transcript to the
answer stage instead of pixels. The backends and the line-regrouping live in
`src/transcribe.py`; this is only the sweep.

Each sweep appends one line per file to `<out-dir>/_timings.jsonl` (backend,
seconds, pages, chars) — the per-page cost numbers the eyes-vs-brain
comparison needs. Resume-safe: existing transcripts are skipped.

Usage:
    # classical OCR, CPU only, into its own folder
    MAGPIE_TRANSCRIPTS_DIR=/data/transcripts_ocr \\
        uv run python Evaluations/transcribe_index.py --backend ocr --corpus /mnt/hardisk/sem6

    # the local VLM (whatever LLAMA_SERVER_VISION_MODEL / *_MODEL_PATH resolve to)
    MAGPIE_TRANSCRIPTS_DIR=/data/transcripts_vlm3b \\
        uv run python Evaluations/transcribe_index.py --backend vlm --corpus /mnt/hardisk/sem6

    # only files whose path contains a substring (quick spot checks)
    uv run python Evaluations/transcribe_index.py --backend ocr --corpus ... --only sps/

    uv run python Evaluations/transcribe_index.py --remove   # delete the transcripts folder
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=str, default=None)
    ap.add_argument("--backend", choices=("ocr", "vlm"), default="ocr")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--no-images", action="store_true", help="scanned PDFs only")
    ap.add_argument("--no-pdfs", action="store_true", help="images only")
    ap.add_argument("--only", type=str, default=None,
                    help="substring a file's path must contain")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    from src.content import IMAGE_EXTS, PDF_EXTS, transcripts_dir, transcript_path_for
    from src.transcribe import MAX_PAGES, is_pixel_file, write_transcript

    tdir = transcripts_dir()
    if args.remove:
        shutil.rmtree(tdir, ignore_errors=True)
        print(f"removed {tdir}")
        return 0
    if not args.corpus:
        ap.error("--corpus required unless --remove")

    root = Path(args.corpus)
    exts = set()
    if not args.no_pdfs:
        exts |= PDF_EXTS
    if not args.no_images:
        exts |= set(IMAGE_EXTS)
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in exts
        and ".venv" not in p.parts and "node_modules" not in p.parts
        and (args.only is None or args.only in str(p))
    )
    tdir.mkdir(parents=True, exist_ok=True)
    timings = (tdir / "_timings.jsonl").open("a", encoding="utf-8")
    max_pages = args.max_pages or MAX_PAGES
    print(f"backend={args.backend} out={tdir} candidates={len(files)}", flush=True)

    done = skipped = failed = 0
    t0 = time.time()
    for i, path in enumerate(files, 1):
        if transcript_path_for(path).exists():
            skipped += 1
            continue
        try:
            if not is_pixel_file(path):
                skipped += 1  # real text layer — no transcript needed
                continue
            _out, r = write_transcript(path, args.backend, max_pages)
            timings.write(json.dumps({
                "file": str(path), "backend": args.backend, "seconds": round(r["seconds"], 3),
                "pages": r["pages"], "total_pages": r["total_pages"], "chars": r["chars"],
            }) + "\n")
            timings.flush()
            done += 1
            print(f"[{i}/{len(files)}] ({(time.time()-t0)/60:.1f}min) {r['seconds']:.1f}s "
                  f"{r['pages']}p {r['chars']}ch  {path.relative_to(root)}", flush=True)
        except Exception as e:  # noqa: BLE001 — skip and continue
            failed += 1
            print(f"[{i}/{len(files)}] FAIL {path.name}: {type(e).__name__}: {e}", flush=True)
    print(f"\ndone: {done} transcribed, {skipped} skipped (text or existing), "
          f"{failed} failed, {(time.time()-t0)/60:.1f} min -> {tdir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
