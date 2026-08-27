"""doc2query v3 (2026-08-26): index-time question generation with a
DISK CACHE and GLOBAL cross-file near-duplicate dedup — the fix for why
spikes v1/v2 failed (lookalike questions from many files crowded the
RRF pool; per-file filtering could not see the collisions).

Three phases, run separately:

    # 1. generate (local LLM, resume-safe, caches to disk — reruns free)
    uv run python Evaluations/doc2query_v3.py --generate \
        --corpus "C:\\ranjan_documents\\college data"

    # 2. dedup + upsert survivors into Qdrant (tagged hype:true)
    uv run python Evaluations/doc2query_v3.py --index

    # 3. rollback
    uv run python Evaluations/doc2query_v3.py --remove

Dedup rule (keep-best-owner, from the plan card): embed every cached
question; any pair from DIFFERENT files with cosine >= 0.90 forms a
cluster; keep only the question whose tokens overlap its OWN file-name
entities the most; on a tie, drop the whole cluster (cross-file
lookalikes are the measured poison). Same-file near-dupes keep first.

Cache: Evaluations/college_data/hype_questions_cache.json (gitignored
with the rest of college_data).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

CACHE = REPO_ROOT / "Evaluations" / "college_data" / "hype_questions_cache.json"
SIM_THRESHOLD = 0.90

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


def _name_entities(name: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z0-9']+", name)
            if len(t) > 3 and t.lower() not in _GENERIC}


def _entities(name: str, content: str) -> set[str]:
    ents = _name_entities(name)
    for m in re.findall(r"\b(?:[A-Z][a-zA-Z]{2,}|\d[\d,./%-]{2,})\b", content):
        if m.lower() not in _GENERIC:
            ents.add(m.lower())
    return ents


def _questions_for(llm, name: str, content: str) -> list[str]:
    raw = llm.complete_sync(
        [{"role": "user", "content": PROMPT.format(name=name, content=content[:6000])}],
        temperature=0.3, max_tokens=300,
    )
    ents = _entities(name, content)
    out = []
    for line in raw.splitlines():
        line = re.sub(r"^\s*(?:[-*\d.)\]]+\s*)?", "", line).strip()
        if not (line.endswith("?") and 15 <= len(line) <= 200):
            continue
        qt = {t.lower() for t in re.findall(r"[A-Za-z0-9']+", line)}
        if qt & ents:
            out.append(line)
    return out[:5]


def load_cache() -> dict[str, list[str]]:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def generate(corpus_root: str) -> int:
    from src.content import build_content_blocks
    from src.inference.local_llm import get_local_llm
    from src.manifest import Manifest

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

    cache = load_cache()
    todo = [p for p in targets if str(p) not in cache]
    print(f"{len(targets)} text-bearing files; {len(cache)} cached, "
          f"{len(todo)} to generate", flush=True)
    if not todo:
        return 0
    llm = get_local_llm()
    t0 = time.time()
    for i, path in enumerate(todo, 1):
        try:
            blocks = build_content_blocks(path, max_chars=6000, max_pdf_pages=3)
            content = " ".join(b for b in blocks if isinstance(b, str)).strip()
            qs = _questions_for(llm, path.name, content) if len(content) >= 200 else []
            cache[str(path)] = qs
            if i % 5 == 0 or qs:
                print(f"[{i}/{len(todo)}] ({(time.time()-t0)/60:.1f}min) "
                      f"{path.name}: {len(qs)} questions", flush=True)
        except Exception as e:  # noqa: BLE001
            cache[str(path)] = []
            print(f"[{i}/{len(todo)}] SKIP {path.name}: {type(e).__name__}: {e}",
                  flush=True)
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    n = sum(len(v) for v in cache.values())
    print(f"\ndone: {n} questions cached from {len(cache)} files", flush=True)
    return 0


def index() -> int:
    import numpy as np

    from qdrant_client.models import PointStruct, SparseVector

    from src.stage2.db import COLLECTION_NAME, _point_id, get_qdrant_client
    from src.stage2.embeddings import embed_dense, embed_sparse

    cache = load_cache()
    items = [(path, q) for path, qs in cache.items() for q in qs]
    if not items:
        print("cache empty — run --generate first")
        return 1
    print(f"{len(items)} cached questions from {len(cache)} files", flush=True)

    vecs = np.array(embed_dense([q for _, q in items]), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    sim = vecs @ vecs.T

    owner_score = [
        len({t.lower() for t in re.findall(r"[A-Za-z0-9']+", q)}
            & _name_entities(Path(path).name))
        for path, q in items
    ]
    drop = [False] * len(items)
    cross_clusters = kept_best = 0
    for i in range(len(items)):
        if drop[i]:
            continue
        cluster = [j for j in range(len(items))
                   if j != i and not drop[j] and sim[i, j] >= SIM_THRESHOLD]
        cross = [j for j in cluster if items[j][0] != items[i][0]]
        for j in cluster:
            if items[j][0] == items[i][0]:
                drop[j] = True  # same-file near-dupe: keep first (i)
        if not cross:
            continue
        cross_clusters += 1
        group = [i] + cross
        best = max(group, key=lambda j: owner_score[j])
        ties = [j for j in group if owner_score[j] == owner_score[best]]
        if len(ties) > 1:
            for j in group:
                drop[j] = True  # ambiguous owner: the measured poison
        else:
            kept_best += 1
            for j in group:
                drop[j] = j != best

    survivors = [(p, q) for (p, q), d in zip(items, drop) if not d]
    print(f"global dedup: {len(items)} -> {len(survivors)} "
          f"({cross_clusters} cross-file clusters, {kept_best} kept-best, "
          f"rest dropped)", flush=True)

    client = get_qdrant_client()
    qs = [q for _, q in survivors]
    dense = embed_dense(qs)
    sparse = embed_sparse(qs)
    points = [
        PointStruct(
            id=_point_id(f"{p}::hype{j}"),
            vector={"dense": dv, "sparse": SparseVector(indices=si, values=sv)},
            payload={"source_path": p, "hype": True, "hype_question": q},
        )
        for j, ((p, q), dv, (si, sv)) in enumerate(zip(survivors, dense, sparse))
    ]
    for start in range(0, len(points), 256):
        client.upsert(collection_name=COLLECTION_NAME,
                      points=points[start:start + 256])
    print(f"upserted {len(points)} question points (hype:true)", flush=True)
    return 0


def remove() -> int:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from src.stage2.db import COLLECTION_NAME, get_qdrant_client

    client = get_qdrant_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(key="hype", match=MatchValue(value=True))]),
    )
    print("all hype-tagged points deleted")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--corpus", type=str, default=None)
    args = ap.parse_args()
    if args.remove:
        return remove()
    if args.index:
        return index()
    if args.generate:
        if not args.corpus:
            ap.error("--corpus required with --generate")
        return generate(args.corpus)
    ap.error("pick one of --generate / --index / --remove")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
