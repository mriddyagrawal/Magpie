"""Register ANY folder of files as an eval dataset corpus.

The generic counterpart of prepare_receipts.py: point it at a folder, get the
two things every dataset needs before a run —

  eval_harness/datasets/<name>/manifest.json            (committed; sha256s +
                                                         corpus-relative paths)
  eval_harness/datasets/<name>/corpus_root.local.json   (untracked, per-machine)

golden.json / qrels.tsv are NOT written here: questions come from agents that
read the files (the /magpie-eval skill, Phase 2).

Corpus location, two supported conventions:
  1. In-tree (simplest): put files under eval_harness/datasets/<name>/corpus/
     and run with just --name. The corpus/ dir is gitignored; the pointer
     still gets written so the runner has one code path.
  2. Anywhere else: pass --corpus-dir /path/to/files (big or private corpora
     that should not live inside a git checkout).

Usage:
  uv run python eval_harness/scripts/register_corpus.py --name mynotes \
      [--corpus-dir ~/Documents/my-notes]
  uv run python eval_harness/scripts/register_corpus.py --name mynotes --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATASETS = REPO / "eval_harness" / "datasets"

# Same families the walker considers; a corpus of only unindexable files is
# a config mistake worth failing loudly on at registration time.
_EXTS = {
    ".txt", ".md", ".markdown", ".log", ".pdf", ".docx", ".xlsx", ".xlsm",
    ".pptx", ".html", ".htm", ".ipynb", ".png", ".jpg", ".jpeg", ".webp",
    ".gif", ".heic", ".py", ".js", ".ts", ".go", ".rs", ".java", ".c",
    ".cpp", ".rb", ".swift", ".sh", ".sql", ".json", ".yaml", ".yml",
    ".toml", ".csv",
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(corpus_dir: Path) -> list[dict]:
    files = []
    for p in sorted(corpus_dir.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in _EXTS:
            continue
        files.append({
            "name": p.name,
            "path": p.relative_to(corpus_dir).as_posix(),
            "sha256": sha256_file(p),
        })
    return files


def verify(ds_dir: Path, corpus_dir: Path) -> int:
    manifest = json.loads((ds_dir / "manifest.json").read_text(encoding="utf-8"))
    bad = 0
    for entry in manifest["files"]:
        p = corpus_dir / entry.get("path", entry["name"])
        if not p.exists():
            hits = list(corpus_dir.rglob(entry["name"]))
            p = hits[0] if hits else None
        if p is None or not p.exists():
            print(f"MISSING {entry['name']}")
            bad += 1
        elif sha256_file(p) != entry["sha256"]:
            print(f"HASH MISMATCH {entry['name']}")
            bad += 1
    print(f"verify: {len(manifest['files']) - bad}/{len(manifest['files'])} files OK")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="dataset name (datasets/<name>/)")
    ap.add_argument("--corpus-dir", default=None,
                    help="folder holding the files; default: datasets/<name>/corpus/")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    ds_dir = DATASETS / args.name
    corpus_dir = (Path(args.corpus_dir).expanduser().resolve()
                  if args.corpus_dir else ds_dir / "corpus")

    if args.verify:
        raise SystemExit(verify(ds_dir, corpus_dir))

    if not corpus_dir.is_dir():
        sys.exit(f"register_corpus: {corpus_dir} is not a directory - create it "
                 f"and put the corpus files there, or pass --corpus-dir")

    files = collect(corpus_dir)
    if not files:
        sys.exit(f"register_corpus: no indexable files under {corpus_dir} "
                 f"(considered extensions: {len(_EXTS)} types)")
    basenames = [f["name"] for f in files]
    if len(basenames) != len(set(basenames)):
        dupes = sorted({b for b in basenames if basenames.count(b) > 1})
        sys.exit("register_corpus: duplicate basenames (the harness anchors "
                 f"gold matching on basenames - rename these): {dupes[:10]}")

    ds_dir.mkdir(parents=True, exist_ok=True)
    (ds_dir / "manifest.json").write_text(json.dumps({
        "dataset": args.name,
        "source": "local corpus (register_corpus.py)",
        "n_files": len(files),
        "files": files,
    }, indent=2) + "\n", encoding="utf-8")
    (ds_dir / "corpus_root.local.json").write_text(
        json.dumps({"corpus_root": str(corpus_dir)}, indent=2) + "\n",
        encoding="utf-8")
    print(f"registered {args.name}: {len(files)} files from {corpus_dir}")
    print(f"manifest + local pointer under {ds_dir}")
    print("next: /magpie-eval generates golden.json by reading the files")


if __name__ == "__main__":
    main()
