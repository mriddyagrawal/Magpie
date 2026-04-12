"""Hybrid search: Kimi query rewriting + dense/sparse Qdrant retrieval."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from qdrant_client.models import FusionQuery, Prefetch, SparseVector

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
    "intent in keyword-rich language, and a `keywords` list of 3-8 specific terms "
    "(names, amounts, dates, document types) that should match exactly. "
    "Do not answer the question — only produce the search query."
)


def _build_rewrite_agent() -> Agent[None, SearchQuery]:
    api_key = os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        sys.exit("error: MOONSHOT_API_KEY not set (put it in .env)")
    model_name = os.environ.get("MOONSHOT_MODEL", "kimi-k2.5")
    base_url = os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
    model = OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )
    return Agent(model, output_type=NativeOutput(SearchQuery), system_prompt=REWRITE_SYSTEM_PROMPT)


def rewrite_query(question: str) -> SearchQuery:
    """Send a raw user question to Kimi and get back a structured SearchQuery."""
    agent = _build_rewrite_agent()
    result = agent.run_sync(question)
    return result.output


# ---------------------------------------------------------------------------
# Qdrant hybrid search
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """Three-column output: summary, path, score."""

    summary: str
    path: str
    score: float


def search_summaries(question: str, top_k: int = 5) -> list[SearchResult]:
    """Full pipeline: rewrite the question via Kimi, then hybrid search Qdrant.

    Returns up to top_k results ranked by Reciprocal Rank Fusion of
    dense (semantic) and sparse (BM25) scores.
    """
    sq = rewrite_query(question)

    # Combine the rewritten query with keywords for a richer embedding input.
    dense_text = sq.query + " " + " ".join(sq.keywords)
    dense_vec = embed_dense_query(dense_text)

    # Keywords feed the sparse/BM25 side for exact-match boosting.
    sparse_text = sq.query + " " + " ".join(sq.keywords)
    sparse_idx, sparse_val = embed_sparse_query(sparse_text)

    client = get_qdrant_client()

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=dense_vec, using="dense", limit=top_k * 2),
            Prefetch(
                query=SparseVector(indices=sparse_idx, values=sparse_val),
                using="sparse",
                limit=top_k * 2,
            ),
        ],
        query=FusionQuery(fusion="rrf"),
        limit=top_k,
        with_payload=["summary", "source_path"],
    )

    return [
        SearchResult(
            summary=point.payload.get("summary", ""),
            path=point.payload.get("source_path", ""),
            score=point.score,
        )
        for point in results.points
    ]
