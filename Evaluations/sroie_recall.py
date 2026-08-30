"""Eyes-only scoring against ICDAR 2019 SROIE ground truth.

SROIE ships, per receipt image `X.jpg`, a `X.txt` with one OCR line per row
(`x1,y1,x2,y2,x3,y3,x4,y4,text`) and, for the key-information task, a JSON
with four fields: company, date, address, total. That is third-party truth
for exactly the receipt case Magpie is built for, so the transcriber
comparison should be run on it and not only on our own image block.

Two numbers per transcripts folder:
  - field recall, strict: for each receipt, is each of the four key values
    present verbatim in the transcript (case-insensitive, whitespace and
    thousands separators flattened, `$`/`RM` stripped)? Reported per field
    and as "all four".
  - field recall, soft: at least 80% of the field's tokens are present. A
    company name with one wrong letter ('SDN BND' for 'SDN BHD') fails
    strict and passes soft; a field that is simply not there fails both.
    The gap between the two columns is the transcriber's garble rate.
  - word recall: fraction of ground-truth OCR words (len >= 3) that appear
    in the transcript. A lossy-digit transcriber shows up here first.

    uv run python Evaluations/sroie_recall.py --corpus /path/to/sroie \\
        ocr=/data/transcripts/ocr-sroie vlm3b=/data/transcripts/vlm3b-sroie

Ground truth is read from `--gt-root` (default: the ICDAR mirror on this
box) as `box/<id>.csv` (or .txt) and `key/<id>.json`, where `<id>` is the image stem
with a `receipt_` prefix stripped — Magpie's eval copy is
`receipt_000.jpg` for the mirror's `img/000.jpg` (verified byte-identical
2026-08-29). Any other layout falls back to a same-stem search under the
corpus itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIELDS = ("company", "date", "address", "total")
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"(?<=\d),(?=\d)", "", s)
    s = re.sub(r"\b(rm|usd)\b|\$", "", s)
    return re.sub(r"[^a-z0-9.]+", " ", s).strip()


def transcript_text(tdir: Path, path: Path) -> str | None:
    key = hashlib.sha256(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:16]
    f = tdir / f"{key}.md"
    if not f.exists():
        return None
    t = f.read_text(encoding="utf-8")
    return t.split("## Page", 1)[1] if "## Page" in t else ""


GT_ROOT = Path("/mnt/astavaknew/sroie/ICDAR-2019-SROIE-master/data")


def find_gt(corpus: Path, stem: str, gt_root: Path | None) -> tuple[dict | None, list[str]]:
    """(key-field dict, OCR words) for one receipt."""
    keys, words = None, []
    rid = re.sub(r"^receipt_", "", stem)
    candidates = []
    if gt_root and (gt_root / "key" / f"{rid}.json").exists():
        candidates = [gt_root / "key" / f"{rid}.json", gt_root / "box" / f"{rid}.csv", gt_root / "box" / f"{rid}.txt"]
    else:
        candidates = list(corpus.rglob(f"{stem}.*"))
    for f in candidates:
        if not f.exists():
            continue
        if f.suffix.lower() not in (".json", ".txt", ".csv"):
            continue
        raw = f.read_text(encoding="utf-8", errors="ignore").strip()
        if raw.startswith("{"):
            try:
                d = json.loads(raw)
                if any(k in d for k in FIELDS):
                    keys = {k: str(d.get(k, "")) for k in FIELDS}
                    continue
            except json.JSONDecodeError:
                pass
        for line in raw.splitlines():
            parts = line.split(",", 8)
            if len(parts) == 9 and all(p.strip().lstrip("-").isdigit() for p in parts[:8]):
                words += [w for w in norm(parts[8]).split() if len(w) >= 3]
    return keys, words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--gt-root", default=str(GT_ROOT))
    ap.add_argument("folders", nargs="+", help="name=/path/to/transcripts ...")
    args = ap.parse_args()
    corpus = Path(args.corpus)
    gt_root = Path(args.gt_root) if args.gt_root and Path(args.gt_root).is_dir() else None
    folders = [(f.split("=", 1)[0], Path(f.split("=", 1)[1])) for f in args.folders]

    images = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in IMAGE_EXTS)
    gts = {p: find_gt(corpus, p.stem, gt_root) for p in images}
    with_keys = [p for p in images if gts[p][0]]
    print(f"{len(images)} receipts, {len(with_keys)} with key-field truth, "
          f"{sum(1 for p in images if gts[p][1])} with OCR-line truth\n")

    for name, tdir in folders:
        hits = {k: 0 for k in FIELDS}
        soft = {k: 0 for k in FIELDS}
        n_keys = 0
        all4 = 0
        all4_soft = 0
        word_recalls = []
        missing = 0
        for p in images:
            t = transcript_text(tdir, p)
            if t is None:
                missing += 1
                continue
            nt = norm(t)
            keys, words = gts[p]
            if keys:
                n_keys += 1
                got = {k: bool(norm(v)) and norm(v) in nt for k, v in keys.items()}
                got_soft = {}
                for k, v in keys.items():
                    toks = norm(v).split()
                    got_soft[k] = bool(toks) and sum(t in nt for t in toks) / len(toks) >= 0.8
                for k in FIELDS:
                    hits[k] += got[k]
                    soft[k] += got_soft[k]
                all4 += all(got.values())
                all4_soft += all(got_soft.values())
            if words:
                word_recalls.append(sum(w in nt for w in words) / len(words))
        print(f"== {name}  ({tdir})")
        if missing:
            print(f"   {missing} receipts have no transcript in this folder")
        if n_keys:
            print("   strict: " + "  ".join(f"{k} {hits[k]}/{n_keys}" for k in FIELDS)
                  + f"  | all four {all4}/{n_keys}")
            print("   soft:   " + "  ".join(f"{k} {soft[k]}/{n_keys}" for k in FIELDS)
                  + f"  | all four {all4_soft}/{n_keys}")
        if word_recalls:
            print(f"   word recall: median {statistics.median(word_recalls):.3f}, "
                  f"mean {statistics.mean(word_recalls):.3f} over {len(word_recalls)} receipts")
        tf = tdir / "_timings.jsonl"
        if tf.exists():
            rows = [json.loads(l) for l in tf.read_text().splitlines() if l.strip()]
            if rows:
                print(f"   cost: median {statistics.median(r['seconds'] for r in rows):.2f} s/receipt "
                      f"over {len(rows)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
