"""doc2query / HyPE spike: index-time question generation (experiment).

For every text-bearing file in the manifest under a corpus root, ask the
LOCAL model for 3-5 questions the file can answer, embed those questions,
and upsert them into the `summaries` collection as EXTRA points tagged
`hype: true`. Search then matches user questions against question-space
as well as summary-space; RRF dedupes by source_path, and the answer
stage resolves a question-point hit to the same source file — no
downstream changes needed.

Why local generation: privacy parity with indexing (file content never
leaves the machine), and it measures what the shipped product could do.

Reversible: `python Evaluations/hype_index.py --remove` deletes every
tagged point. Measurement plan: re-run the eval afterward and compare
recall@k / MRR / correctness against the baseline (REPORT.md).

Usage:
    uv run python Evaluations/hype_index.py --corpus "C:\\ranjan_documents\\college data"
    uv run python Evaluations/hype_index.py --remove
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

PROMPT = """You index personal documents for search. Below is content from one file.
Write 4 short questions this file can answer. Rules:
- Each question must be answerable from THIS text alone.
- Every question MUST contain at least one specific name, number, or title
  copied exactly from the text (a school, person, project, course code,
  amount). Questions that could apply to any file are forbidden — never
  write e.g. "Which professors are mentioned?" without naming the school.
- One question per line. No numbering, no prefixes, no answers.

File name: {name}

File content:
{content}
"""

# Specificity filter (v2, 2026-08-24). V1 of this experiment indexed
# generic questions ("Which professors are mentioned?") from many files;
# in question-space those collide, and the RRF pool filled with lookalikes
# — the Cornell essay lost retrieval entirely on the q01 sentinel
# (recall@k 87% → 73%). A generated question now only enters the index if
# it shares at least one file-specific entity (filename token, capitalized
# name, or number) with its own file. Generic vocabulary never counts.
_GENERIC = {
    "what", "which", "who", "whom", "when", "where", "how", "why", "does",
    "did", "was", "were", "this", "that", "file", "document", "documents",
    "mentioned", "mention", "mentions", "name", "names", "named", "list",
    "lists", "describe", "described", "professor", "professors", "student",
    "students", "university", "universities", "college", "colleges",
    "essay", "essays", "letter", "letters", "recommendation", "author",
    "wrote", "written", "content", "contents", "about", "many", "much",
    "there", "their", "these", "those", "with", "from", "into", "have",
}


def _entities(name: str, content: str) -> set[str]:
    ents: set[str] = set()
    for t in re.findall(r"[A-Za-z0-9']+", name):
        if len(t) > 3 and t.lower() not in _GENERIC:
            ents.add(t.lower())
    for m in re.findall(r"\b(?:[A-Z][a-zA-Z]{2,}|\d[\d,./%-]{2,})\b", content):
        if m.lower() not in _GENERIC:
            ents.add(m.lower())
    return ents


def _is_specific(q: str, ents: set[str]) -> bool:
    q_tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9']+", q)}
    return bool(q_tokens & ents)


def _questions_for(llm, name: str, content: str) -> list[str]:
    raw = llm.complete_sync(
        [{"role": "user", "content": PROMPT.format(name=name, content=content[:6000])}],
        temperature=0.3,
        max_tokens=300,
    )
    ents = _entities(name, content)
    out, rejected = [], 0
    for line in raw.splitlines():
        line = re.sub(r"^\s*(?:[-*\d.)\]]+\s*)?", "", line).strip()
        if not (line.endswith("?") and 15 <= len(line) <= 200):
            continue
        if _is_specific(line, ents):
            out.append(line)
        else:
            rejected += 1
    if rejected:
        print(f"    (specificity filter rejected {rejected})", flush=True)
    return out[:5]


def build(corpus_root: str) -> int:
    from src.manifest import Manifest, REPO_ROOT as DATA_ROOT
    from src.content import build_content_blocks
    from src.inference.local_llm import get_local_llm
    from src.stage2.db import get_qdrant_client, COLLECTION_NAME, _point_id
    from src.stage2.embeddings import embed_dense, embed_sparse
    from qdrant_client.models import PointStruct, SparseVector

    corpus = str(Path(corpus_root).resolve()).lower()
    manifest = Manifest()
    targets = []
    for rel, entry in manifest.entries.items():
        p = Path(rel)
        if not str(p.resolve()).lower().startswith(corpus):
            continue
        if entry.skip_reason or not entry.summary_file:
            continue
        if p.suffix.lower() not in (".docx", ".pdf", ".txt", ".md", ".pptx", ".xlsx"):
            continue
        targets.append(p)
    print(f"{len(targets)} text-bearing files under corpus", flush=True)

    llm = get_local_llm()
    client = get_qdrant_client()
    total_points = 0
    t0 = time.time()
    for i, path in enumerate(targets, 1):
        try:
            blocks = build_content_blocks(path, max_chars=6000, max_pdf_pages=3)
            content = " ".join(b for b in blocks if isinstance(b, str)).strip()
            if len(content) < 200:
                continue
            qs = _questions_for(llm, path.name, content)
            if not qs:
                continue
            dense = embed_dense(qs)
            sparse = embed_sparse(qs)
            points = [
                PointStruct(
                    id=_point_id(f"{path}::hype{j}"),
                    vector={
                        "dense": dv,
                        "sparse": SparseVector(indices=si, values=sv),
                    },
                    payload={
                        "source_path": str(path),
                        "hype": True,
                        "hype_question": q,
                    },
                )
                for j, (q, dv, (si, sv)) in enumerate(zip(qs, dense, sparse))
            ]
            client.upsert(collection_name=COLLECTION_NAME, points=points)
            total_points += len(points)
            print(f"[{i}/{len(targets)}] ({(time.time()-t0)/60:.1f}min) "
                  f"{path.name}: {len(qs)} questions", flush=True)
        except Exception as e:  # noqa: BLE001 — skip and continue
            print(f"[{i}/{len(targets)}] SKIP {path.name}: {type(e).__name__}: {e}",
                  flush=True)
    print(f"\ndone: {total_points} question points in "
          f"{(time.time()-t0)/60:.1f} min", flush=True)
    return 0


def remove() -> int:
    from src.stage2.db import get_qdrant_client, COLLECTION_NAME
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client = get_qdrant_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(key="hype", match=MatchValue(value=True))]
        ),
    )
    print("all hype-tagged points deleted")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=str, default=None)
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()
    if args.remove:
        return remove()
    if not args.corpus:
        ap.error("--corpus required unless --remove")
    return build(args.corpus)


if __name__ == "__main__":
    raise SystemExit(main())
