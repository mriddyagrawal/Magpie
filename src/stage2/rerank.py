"""Cross-encoder reranker (backlog B4).

A second-pass ranker that scores `(query, document)` pairs with a small
purpose-built model and reorders the candidate set. Cross-encoders read both
the query and the document at the same time — much more discriminating than
the dense + BM25 fusion that fed them — at the cost of one model forward
pass per candidate.

Pipeline shape:
    1. Hybrid search (dense + BM25 + ColPali) returns top-N candidates (N=50).
    2. We feed (query, candidate.summary) pairs to the cross-encoder.
    3. Sort by cross-encoder score, return top-k.

We keep this **opt-in via flag**, default off. The rememex postmortem flagged
two ranking-regression bugs from always-on cross-encoder rerankers; the
canonical fix was "default off, expose the score, never silently drop
results below a threshold." Both rules followed here:
  - Disabled unless caller passes `rerank=True`.
  - We REPLACE `SearchResult.score` with the cross-encoder score so the REPL
    displays the value the user can audit, instead of an opaque RRF number.
  - No threshold filtering — every input candidate gets a score; truncation
    is by `top_k` only.

Default model: `cross-encoder/ms-marco-MiniLM-L-6-v2`. ~80 MB, English,
fast (~50-100 ms per (query, doc) pair on CPU; ~5-10 ms on GPU). Override
with the `RERANK_MODEL` env var if you want a stronger / multilingual
alternative like `BAAI/bge-reranker-v2-m3` (~600 MB).

Pure transformations (no Qdrant); pairs cleanly with the search layer.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

    from src.stage2.search import SearchResult


# ms-marco MiniLM is the well-tested baseline cross-encoder. Trained on
# Microsoft's MS-MARCO passage retrieval data — exactly the (query, passage)
# shape we need for reranking summaries. Tiny enough to download fast and
# run on CPU without dragging the REPL's per-query latency past a second.
DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _model_name() -> str:
    return os.environ.get("RERANK_MODEL", DEFAULT_MODEL)


@lru_cache(maxsize=1)
def _load_model() -> "CrossEncoder":
    """Lazy-load the cross-encoder on first use. Cached for the process lifetime.

    Deferred import: sentence-transformers pulls in transformers + torch,
    which is ~1 GB of code we shouldn't pay for unless rerank is opted in.
    """
    from sentence_transformers import CrossEncoder
    return CrossEncoder(_model_name())


def rerank(
    query: str,
    candidates: list["SearchResult"],
    top_k: int,
) -> list["SearchResult"]:
    """Reorder `candidates` by cross-encoder relevance to `query`, return top-k.

    Mutates each returned `SearchResult.score` to carry the cross-encoder's
    output score, so the REPL displays a meaningful, comparable number. The
    `tier` field is preserved for transparency.

    Empty input → empty output. Single candidate → returned unchanged
    (reranking a one-element list is a wasted forward pass). Otherwise:
    one model call with all pairs (sentence-transformers batches internally).
    """
    if not candidates:
        return []
    if len(candidates) == 1:
        return candidates[:top_k]

    model = _load_model()

    # Build (query, doc_text) pairs. Prefer the candidate's `summary` (which
    # is the LLM-distilled summary text from T0/T1/T2/T3) since it carries
    # the actual content the cross-encoder needs to score against. Fall back
    # to the path if a summary is missing (fast-tier-only hits show
    # `(visual match — page N)` as their summary; that's still informative).
    pairs = [(query, c.summary or c.path) for c in candidates]

    # `predict()` runs the cross-encoder over all pairs in one call (batched
    # internally per the model's max sequence length). Returns a numpy array.
    scores = model.predict(pairs)

    # Pair up, sort by cross-encoder score (higher = more relevant), then
    # rewrite each candidate's `score` so downstream display reflects the
    # reranking, not the original RRF number.
    scored: list[tuple["SearchResult", float]] = list(zip(candidates, scores))
    scored.sort(key=lambda kv: kv[1], reverse=True)

    kept: list["SearchResult"] = [cand for cand, _ in scored[:top_k]]

    # Retrieval-anchor guarantee (2026-08-24). The full re-sort + top-k
    # truncation above CAN silently drop the fusion top-1 — the very hit the
    # user's words matched hardest — which violates this module's own
    # "never silently drop results" rule one step later. Observed live:
    # "who are the professors I wrote to in Cornell university?" put
    # WHYUS_Cornell_essay.docx at fusion #1 (0.70), the ms-marco
    # cross-encoder demoted it below five CSS-Profile forms, the answer
    # stage never saw the essay, and the user got "answer not found" for a
    # question their own files answered. The anchor keeps its cross-encoder
    # score for display, so the audit trail stays honest about what the
    # reranker thought of it.
    anchor = candidates[0]
    if kept and anchor not in kept:
        kept[-1] = anchor

    cross_score = {id(c): float(s) for c, s in scored}
    for cand in kept:
        cand.score = cross_score[id(cand)]
    return kept
