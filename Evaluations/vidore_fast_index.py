"""Build ONLY the ColPali fast tier for a folder of page images.

The walker runs one primary tier per file and ranks T3 above T4, so a page
routed `[T3, T4]` gets a VLM caption and never a ColPali point — which is
what happened to the first ViDoRe trial (5 files: T3=5, T4=0, no fast_tier
collection). For the retrieval comparison the fast tier has to exist on its
own terms, so this drives `tier4.run` file by file: same ColSmol/ColQwen
model selection, same Qdrant collection, same manifest bookkeeping, no LLM.

    MAGPIE_DATA_DIR=... QDRANT_CLUSTER_ENDPOINT=... \\
        uv run python Evaluations/vidore_fast_index.py --corpus /mnt/astavaknew/vidore/infovqa/pages
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    from src.ingest import tier4
    from src.manifest import DEFAULT_MANIFEST_PATH, Manifest
    from src.stage1_fast.device import detect_device

    manifest = Manifest(DEFAULT_MANIFEST_PATH)
    files = sorted(p for p in a.corpus.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if a.limit:
        files = files[: a.limit]
    try:
        print(f"device: {detect_device()}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"device: ? ({e})", flush=True)
    times = []
    t0 = time.time()
    pages_total = 0
    for i, p in enumerate(files, 1):
        rel = str(p.resolve())
        t = time.perf_counter()
        try:
            out = tier4.run(p, rel, manifest)
            pages_total += out.body_chars or 0
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(files)}] FAIL {p.name}: {type(e).__name__}: {e}", flush=True)
            continue
        times.append(time.perf_counter() - t)
        if i % 25 == 0 or i == len(files):
            manifest.save()
            print(f"[{i}/{len(files)}] {(time.time()-t0)/60:.1f} min, last {times[-1]:.1f}s/file", flush=True)
    manifest.save()
    import statistics
    print(json.dumps({"files": len(files), "pages": pages_total, "median_s": round(statistics.median(times), 2) if times else None,
                      "total_min": round((time.time() - t0) / 60, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
