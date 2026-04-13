"""End-to-end question pipeline: retrieve -> answer.

Glues stage 2/3 (search) and stage 4 (answer) together:

    question -> Kimi query rewrite -> Qdrant hybrid search (top-k)
             -> read the top-k files -> Kimi answer with source citation
             -> PipelineResult

This is the module a user-facing app (CLI, web, etc.) should import. It hides
whether retrieval is top-k over chunks or whole files, whether the answerer
has agentic fetch-more capability, etc. — it's the one stable interface.

CLI:

    uv run python3 -m src.pipeline "your question here" [--top-k 5]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

from src.answer import Answer, answer_question, build_answer_agent
from src.stage2.search import SearchQuery, SearchResult, rewrite_query, run_search


@dataclass
class PipelineResult:
    """What the full pipeline returns for a single question."""

    question: str
    search_query: SearchQuery          # Kimi's rewritten dense/BM25 query
    retrieved: list[SearchResult]       # Qdrant top-k (path, summary, score)
    answer: str                         # Kimi's final answer
    sources_used: list[str]             # Subset of retrieved paths Kimi cited


async def ask(question: str, *, top_k: int = 5) -> PipelineResult:
    """Run the full retrieve -> answer pipeline for one question.

    1. `rewrite_query(question)` — Kimi turns the raw question into a
       keyword-rich `SearchQuery`.
    2. `run_search(sq, top_k)` — Qdrant hybrid search (dense + BM25 via RRF)
       over the summary index.
    3. `answer_question(agent, question, paths)` — read the retrieved files,
       send them with the question to Kimi, get a grounded answer + citations.

    Keeping the two halves of search separate (rewrite, then search) lets us
    surface the rewritten query in `PipelineResult.search_query` for eval and
    debugging.
    """
    sq: SearchQuery = await asyncio.to_thread(rewrite_query, question)
    retrieved = await asyncio.to_thread(run_search, sq, top_k)
    if not retrieved:
        return PipelineResult(
            question=question,
            search_query=sq,
            retrieved=[],
            answer="No matching documents found in the index.",
            sources_used=[],
        )

    agent = build_answer_agent()
    paths = [r.path for r in retrieved if r.path]
    ans: Answer = await answer_question(agent, question, paths)

    return PipelineResult(
        question=question,
        search_query=sq,
        retrieved=retrieved,
        answer=ans.answer,
        sources_used=ans.sources_used,
    )


def ask_sync(question: str, *, top_k: int = 5) -> PipelineResult:
    return asyncio.run(ask(question, top_k=top_k))


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Ask a natural-language question; retrieve top-k files and answer (stages 3 + 4)."
    )
    parser.add_argument("question", help="The natural-language question.")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Number of files to retrieve from Qdrant (default: 5).")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of human-readable output.")
    args = parser.parse_args()

    result = ask_sync(args.question, top_k=args.top_k)

    if args.json:
        print(json.dumps({
            "question": result.question,
            "answer": result.answer,
            "sources_used": result.sources_used,
            "retrieved": [
                {"path": r.path, "score": r.score, "summary": r.summary}
                for r in result.retrieved
            ],
        }, indent=2, ensure_ascii=False))
        return

    print(f"Question: {result.question}\n")
    print("Retrieved (top-k from Qdrant):")
    for i, r in enumerate(result.retrieved, 1):
        print(f"  {i}. [{r.score:.3f}] {r.path}")
    print()
    print("Answer:")
    print(result.answer)
    print()
    if result.sources_used:
        print("Sources used:")
        for p in result.sources_used:
            print(f"  - {p}")
    else:
        print("Sources used: (none)")


if __name__ == "__main__":
    main()
