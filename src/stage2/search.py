"""Hybrid search: Kimi query rewriting + dense/sparse Qdrant retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field
from qdrant_client.models import FusionQuery, Prefetch, SparseVector

from src.llm import ChatAgent, build_agent
from src.stage2.db import COLLECTION_NAME, get_qdrant_client
from src.stage2.embeddings import embed_dense_query, embed_sparse_query


# ---------------------------------------------------------------------------
# Kimi query rewriting
# ---------------------------------------------------------------------------

class SearchQuery(BaseModel):
    """Structured search query produced by Kimi from a raw user question."""

    query: str = Field(
        description="Clean, keyword-rich search string optimized for semantic embedding."
    )
    keywords: list[str] = Field(
        description="3-8 explicit keywords or entity names for exact-match boosting."
    )


REWRITE_SYSTEM_PROMPT = (
    "You are a search-query optimizer. Given a user's natural-language question "
    "about their personal documents (invoices, receipts, notes, contracts, etc.), "
    "rewrite it into a SearchQuery: a dense `query` string that captures the full "
    "intent in keyword-rich language, and a `keywords` list of 5-12 terms — "
    "include the user's specific values verbatim (names, amounts, dates, course "
    "codes, document types) AND the likely synonyms, abbreviations, alternate "
    "vocabulary, and paraphrases the documents themselves may use for the same "
    "concept. Do not answer the question — only produce the search query. "
    "If prior conversation turns are provided, use them to resolve pronouns and "
    "references in the current question (e.g. 'what about its prerequisites?' → "
    "the subject from the previous turn). The rewrite should be self-contained: "
    "a search engine seeing only the rewritten query must have enough context. "
    "DATE NORMALIZATION: if the user mentions a date or month, include all "
    "common formats in `keywords` so exact-match retrieval (BM25 + ripgrep at "
    "answer time) hits regardless of how the file represents it. "
    "Examples: 'May 25 2022' → also include `25 May 2022`, `2022-05-25`, "
    "`05/25/22`, `05/25/2022`, `05-25-22`. "
    "'last May' → include the month name AND `05/`, `2024-05`, etc. given the "
    "current-date hint at the top of the message. Be liberal — extra date "
    "variants are cheap; missing the format the file uses is expensive. "
    "Output RAW JSON only — do not wrap the response in markdown code fences "
    "like ```json, and do not include any prose before or after the JSON object."
)


_REWRITE_FALLBACK = SearchQuery(query="", keywords=[])


_rewrite_agent: ChatAgent[SearchQuery] | None = None


def _build_rewrite_agent() -> ChatAgent[SearchQuery]:
    return build_agent(REWRITE_SYSTEM_PROMPT, SearchQuery, _REWRITE_FALLBACK)


def _build_rewrite_prompt(
    question: str,
    history: list[tuple[str, str]] | None,
) -> str:
    if not history:
        return question
    lines = ["Previous conversation turns:"]
    for i, (q, a) in enumerate(history, 1):
        lines.append(f"[Turn {i}] Q: {q}")
        lines.append(f"[Turn {i}] A: {a}")
    lines.append("")
    lines.append(f"Current question: {question}")
    return "\n".join(lines)


def rewrite_query(
    question: str,
    history: list[tuple[str, str]] | None = None,
) -> SearchQuery:
    """Send a raw user question to the LLM and get back a structured SearchQuery.

    If `history` is provided (list of (question, answer) tuples from prior turns),
    prepend it as context so the rewriter can resolve references like 'it',
    'that course', 'the same thing' to the actual subject.
    """
    global _rewrite_agent
    if _rewrite_agent is None:
        _rewrite_agent = _build_rewrite_agent()
    sq = _rewrite_agent.run_sync([_build_rewrite_prompt(question, history)])
    # Fallback tweak: if parse failed, empty `query` is unhelpful; substitute the raw question.
    if not sq.query:
        sq = SearchQuery(query=question, keywords=sq.keywords)
    return sq


async def rewrite_query_async(
    question: str,
    history: list[tuple[str, str]] | None = None,
) -> SearchQuery:
    """Async variant of rewrite_query — safe to call inside an existing event loop."""
    global _rewrite_agent
    if _rewrite_agent is None:
        _rewrite_agent = _build_rewrite_agent()
    sq = await _rewrite_agent.run([_build_rewrite_prompt(question, history)])
    if not sq.query:
        sq = SearchQuery(query=question, keywords=sq.keywords)
    return sq


# ---------------------------------------------------------------------------
# Qdrant hybrid search
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """One retrieval hit. `tier` indicates which collection contributed:
    "summary", "fast", or "both" (after RRF merge across both tiers).
    """

    summary: str
    path: str
    score: float
    tier: str = "summary"


def _search_summary_tier(sq: SearchQuery, limit: int) -> list[SearchResult]:
    """Hybrid (dense + BM25) search of the summaries collection.

    Returns an empty list if the collection doesn't exist yet (e.g. fresh
    setup, or the user has only run --fast-only syncs).
    """
    client = get_qdrant_client()
    if not client.collection_exists(COLLECTION_NAME):
        return []

    dense_text = sq.query + " " + " ".join(sq.keywords)
    dense_vec = embed_dense_query(dense_text)
    sparse_idx, sparse_val = embed_sparse_query(dense_text)

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=dense_vec, using="dense", limit=limit),
            Prefetch(
                query=SparseVector(indices=sparse_idx, values=sparse_val),
                using="sparse",
                limit=limit,
            ),
        ],
        query=FusionQuery(fusion="rrf"),
        limit=limit,
        with_payload=["summary", "source_path"],
    )
    return [
        SearchResult(
            summary=(p.payload or {}).get("summary", ""),
            path=(p.payload or {}).get("source_path", ""),
            score=p.score,
            tier="summary",
        )
        for p in results.points
    ]


def _search_fast_tier(query_text: str, limit: int) -> list[SearchResult]:
    """ColPali MaxSim search of the fast_tier collection, deduped to one
    result per file (best-matching page wins).

    Returns an empty list if the collection doesn't exist or the fast-tier
    model can't be loaded (e.g. in CI or on a machine without colpali-engine).
    """
    from src.stage2.fast_db import FAST_COLLECTION_NAME

    client = get_qdrant_client()
    if not client.collection_exists(FAST_COLLECTION_NAME):
        return []

    try:
        from src.stage1_fast.model import encode_queries
        from src.stage2.fast_db import search as fast_search
    except ImportError:
        return []

    try:
        q_tensor = encode_queries([query_text])
        q_vecs = q_tensor[0].float().cpu().tolist()
    except Exception:  # pylint: disable=broad-except
        # Model load failure (no GPU, missing weights, etc.) — fall through.
        return []

    hits = fast_search(q_vecs, limit=limit)

    # A single file can have multiple matching pages. Collapse to best page.
    best_by_path: dict[str, tuple[int, float]] = {}
    for path, page, score in hits:
        prev = best_by_path.get(path)
        if prev is None or score > prev[1]:
            best_by_path[path] = (page, score)

    return [
        SearchResult(
            summary=f"(visual match — page {page})",
            path=path,
            score=score,
            tier="fast",
        )
        for path, (page, score) in sorted(
            best_by_path.items(), key=lambda kv: kv[1][1], reverse=True
        )
    ]


RRF_K = 60  # standard RRF constant; higher = flatter fusion curve


def _rrf_merge(
    summary_hits: list[SearchResult],
    fast_hits: list[SearchResult],
    top_k: int,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion of two result lists, keyed by source_path.

    Each path's RRF score is sum over each list of `1 / (RRF_K + rank)`,
    where rank is 1-indexed. Missing from a list contributes 0. When a
    path appears in both lists we keep the summary-tier entry — it
    surfaces the file as a whole rather than as a per-page anchor, which
    is what the UI source row wants to display.
    """
    scores: dict[str, float] = {}
    chosen: dict[str, SearchResult] = {}
    seen_in: dict[str, set[str]] = {}

    for rank, r in enumerate(summary_hits, start=1):
        if not r.path:
            continue
        scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (RRF_K + rank)
        chosen[r.path] = r  # show the file, not a specific page
        seen_in.setdefault(r.path, set()).add("summary")

    for rank, r in enumerate(fast_hits, start=1):
        if not r.path:
            continue
        scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (RRF_K + rank)
        chosen.setdefault(r.path, r)  # only fill if summary didn't already
        seen_in.setdefault(r.path, set()).add("fast")

    ordered = sorted(chosen.values(), key=lambda r: scores[r.path], reverse=True)
    # Overwrite each result's score with its RRF score so callers see fused ranking.
    for r in ordered:
        r.score = scores[r.path]
        tiers = seen_in.get(r.path, set())
        r.tier = "both" if len(tiers) == 2 else next(iter(tiers), r.tier)
    return ordered[:top_k]


def run_search(sq: SearchQuery, top_k: int = 5) -> list[SearchResult]:
    """Run hybrid search across both the summary and fast-tier collections.

    Each tier returns its top `top_k * 2` candidates; results are merged via
    Reciprocal Rank Fusion keyed on `source_path`. Either tier being empty
    (missing collection, disabled, etc.) is tolerated — the other tier's
    results pass through unchanged.
    """
    summary_hits = _search_summary_tier(sq, top_k * 2)
    # Feed the raw dense-query text (same as summary tier) to ColPali; it
    # handles multi-token query encoding internally.
    query_text = (sq.query + " " + " ".join(sq.keywords)).strip()
    fast_hits = _search_fast_tier(query_text, top_k * 2)
    return _rrf_merge(summary_hits, fast_hits, top_k)


def raw_query(question: str) -> SearchQuery:
    """Build a SearchQuery from the raw user question, skipping the Kimi rewrite.

    Useful when rewrite latency dominates and the raw question is already
    keyword-rich. Pair with the Future-Plans item on asymmetric search /
    HyDE when quality regresses on vague queries.
    """
    return SearchQuery(query=question, keywords=[])


def search_summaries(
    question: str,
    top_k: int = 5,
    *,
    rewrite: bool = True,
) -> list[SearchResult]:
    """Retrieve top-k summaries from Qdrant for a user question.

    If `rewrite` is True (default): Kimi expands the question into a dense
    keyword-rich query + explicit keyword list, then hybrid search.
    If False: the raw question goes directly to the embedders. Saves ~20s
    (one LLM round-trip) per call but may hurt recall on short / vague queries.

    Returns up to top_k results ranked by Reciprocal Rank Fusion of dense
    (semantic) and sparse (BM25) scores.

    Passes the raw `question` through to `run_search` so the adaptive
    classifier can widen top_k for enumeration-shaped queries.
    """
    sq = rewrite_query(question) if rewrite else raw_query(question)
    return run_search(sq, top_k, question=question)
