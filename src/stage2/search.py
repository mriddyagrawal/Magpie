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

    Asserts the configured embedding model's dim matches the collection's
    stored dim before issuing the query — if you swap the dense model
    (e.g. MiniLM-384 → E5-base-768) the index becomes incompatible, and
    silently sending a 768-d vector at a 384-d collection either errors
    cryptically or returns garbage. Fail loudly with re-index instructions.
    """
    from src.stage2.db import assert_dense_dim_match

    client = get_qdrant_client()
    if not client.collection_exists(COLLECTION_NAME):
        return []
    assert_dense_dim_match(client, COLLECTION_NAME)

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
    where rank is 1-indexed. Missing from a list contributes 0. The kept
    SearchResult prefers the summary-tier entry (it has a real summary)
    when a path appears in both lists.
    """
    scores: dict[str, float] = {}
    chosen: dict[str, SearchResult] = {}
    seen_in: dict[str, set[str]] = {}

    for rank, r in enumerate(summary_hits, start=1):
        if not r.path:
            continue
        scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (RRF_K + rank)
        chosen[r.path] = r  # summary-tier entries have human-readable summaries
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


RERANK_OVERSAMPLE = 10
"""When reranking, how many RRF-fused candidates to feed the cross-encoder.

A factor of 10 means top_k=5 fetches 50 candidates from RRF before reranking
down to 5. Standard practice in RAG papers; balances recall headroom against
the cross-encoder's per-pair cost."""


def run_search(
    sq: SearchQuery,
    top_k: int = 5,
    *,
    question: str | None = None,
    rerank: bool = False,
    skip_fast: bool = False,
) -> list[SearchResult]:
    """Run hybrid search across both the summary and fast-tier collections.

    Each tier returns its top `top_k * 2` candidates; results are merged via
    Reciprocal Rank Fusion keyed on `source_path`. Either tier being empty
    (missing collection, disabled, etc.) is tolerated — the other tier's
    results pass through unchanged.

    Adaptive routing: if `question` is provided, the raw user text is
    classified (list/enumeration vs general) and the per-class top_k can
    override the caller's default. The caller's `top_k` still wins if it's
    larger — explicit user override (e.g. `.top-k 50` in the REPL) is
    respected. See `src.stage2.query_classify`.

    Optional cross-encoder rerank (`rerank=True`): pulls `top_k *
    RERANK_OVERSAMPLE` RRF-fused candidates, scores each `(question, doc)`
    pair with a small cross-encoder model, then returns the top-k by that
    score. Default off because cross-encoders occasionally regress factoid
    queries (rememex postmortem). Enable in the REPL with `.rerank on`.
    See `src.stage2.rerank`.
    """
    from src.stage2.query_classify import QueryClass, classify_and_config

    if question is not None:
        klass, cfg = classify_and_config(question)
        # Adaptive routing only **widens** top_k, never narrows. We bump the
        # caller's value only when (a) the class is one with a real
        # widening preference and (b) the class wants more than the caller
        # asked for. Explicit small caller values (e.g. tests passing
        # top_k=3) and explicit large caller values (e.g. `.top-k 50` in the
        # REPL) are both respected — the classifier just helps the default
        # case where caller didn't customize.
        if klass is QueryClass.LIST_ALL and cfg.top_k > top_k:
            print(
                f"  query_class={klass.value}  top_k {top_k}→{cfg.top_k}  "
                f"({cfg.notes})"
            )
            top_k = cfg.top_k

        # Cross-encoder rerank regresses LIST_ALL queries — proper-noun /
        # receipt / enumeration lookups. The cross-encoder over-weights
        # rich semantic prose (e.g. project context docs) against terse
        # receipt-style summaries, pushing the actually-relevant files out
        # of the top-K. Auto-disable rerank for this class even when the
        # caller toggled it on. Empirically validated 2026-04-25:
        # "find me all my uber/lodging receipts" with rerank=on → 0 receipts
        # in top-20; same query with rerank=off → 11 receipts in top-20.
        # GENERAL queries (Hamiltonian, music 101, Romantic era) keep rerank.
        if rerank and klass is QueryClass.LIST_ALL:
            print(
                f"  query_class={klass.value}  rerank suppressed "
                f"(cross-encoder regresses list/enumeration queries)"
            )
            rerank = False

    # If reranking, fetch a wider RRF-fused candidate pool so the cross-encoder
    # has real options to reorder. Otherwise stick with the original top_k.
    fetch_k = top_k * RERANK_OVERSAMPLE if rerank else top_k

    summary_hits = _search_summary_tier(sq, fetch_k * 2)
    # Feed the raw dense-query text (same as summary tier) to ColPali; it
    # handles multi-token query encoding internally.
    # When `skip_fast=True`, bypass ColPali entirely — saves the ~30s first-
    # query model load and ~1s/query encode for sessions that only need text
    # retrieval. The REPL exposes this via `.fast on/off`.
    if skip_fast:
        fast_hits: list[SearchResult] = []
    else:
        query_text = (sq.query + " " + " ".join(sq.keywords)).strip()
        fast_hits = _search_fast_tier(query_text, fetch_k * 2)
    fused = _rrf_merge(summary_hits, fast_hits, fetch_k)

    if rerank and len(fused) > 1:
        from src.stage2.rerank import rerank as cross_encoder_rerank
        # Use the raw user question for reranking when available — it
        # carries the user's actual intent, where the LLM rewrite is
        # paraphrased. Fall back to the rewritten query for non-question
        # callers (programmatic use without `question=`).
        rerank_text = question if question is not None else sq.query
        return cross_encoder_rerank(rerank_text, fused, top_k)

    return fused[:top_k]


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
