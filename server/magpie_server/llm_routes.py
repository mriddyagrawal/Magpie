"""FastAPI router for the three LLM endpoints.

All three:
  1. Receive a typed request from the desktop app
  2. Build the user message (combine prompt context with the request)
  3. Call the LLM with the appropriate system prompt + output schema
  4. Return the typed structured response

Each endpoint is wrapped with the invite-code auth dependency at the
router level (see main.py). On any LLM/provider failure, the friendly
error mapper returns a user-safe message and logs the real exception
server-side.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from magpie_server import prompts
from magpie_server.auth import require_invite
from magpie_server.llm_client import build_agent, user_facing_error
from magpie_server.schemas import (
    Answer,
    AnswerRequest,
    AnswerResponse,
    FileSummary,
    RewriteRequest,
    RewriteResponse,
    SearchQuery,
    SummarizeRequest,
    SummarizeResponse,
)
from magpie_server.settings import settings


router = APIRouter()


# ---------------------------------------------------------------------------
# /llm/rewrite — query expansion for retrieval
# ---------------------------------------------------------------------------

@router.post("/rewrite", response_model=RewriteResponse)
async def rewrite(
    req: RewriteRequest,
    _invite: str = Depends(require_invite),
) -> RewriteResponse:
    # Build the user message: just the question, plus prior turns if any.
    parts: list[str] = []
    if req.history:
        parts.append("Prior conversation:")
        for q, a in req.history:
            parts.append(f"User: {q}")
            parts.append(f"Assistant: {a}")
        parts.append("")
    parts.append(f"Question: {req.question}")
    message = "\n".join(parts)

    try:
        agent = build_agent(prompts.REWRITE_PROMPT, SearchQuery, settings.rewrite_model)
        result = await agent.run(message)
    except Exception as e:  # pylint: disable=broad-except
        status_code, detail = user_facing_error(e)
        raise HTTPException(status_code=status_code, detail=detail) from e

    sq = result.output
    return RewriteResponse(
        query=sq.query,
        keywords=sq.keywords,
        prompt_version=prompts.PROMPT_VERSIONS["rewrite"],
    )


# ---------------------------------------------------------------------------
# /llm/answer — grounded answering
# ---------------------------------------------------------------------------

@router.post("/answer", response_model=AnswerResponse)
async def answer(
    req: AnswerRequest,
    _invite: str = Depends(require_invite),
) -> AnswerResponse:
    # Compose the user message: question, optional history, then each retrieved
    # snippet under a `--- File N: <path> ---` header. The path is what the
    # answer prompt instructs the LLM to copy verbatim into `sources_used`.
    parts: list[str] = []
    if req.history:
        parts.append("Prior conversation:")
        for q, a in req.history:
            parts.append(f"User: {q}")
            parts.append(f"Assistant: {a}")
        parts.append("")

    parts.append(f"Question: {req.question}")
    parts.append("")
    for i, snippet in enumerate(req.snippets, 1):
        parts.append(f"--- File {i}: {snippet.path} ---")
        parts.append(snippet.text)
        parts.append("")
    message = "\n".join(parts)

    try:
        agent = build_agent(prompts.ANSWER_PROMPT, Answer, settings.answer_model)
        result = await agent.run(message)
    except Exception as e:  # pylint: disable=broad-except
        status_code, detail = user_facing_error(e)
        raise HTTPException(status_code=status_code, detail=detail) from e

    a = result.output
    return AnswerResponse(
        answer=a.answer,
        sources_used=a.sources_used,
        prompt_version=prompts.PROMPT_VERSIONS["answer"],
    )


# ---------------------------------------------------------------------------
# /llm/summarize — T3 cloud summarization
# ---------------------------------------------------------------------------

@router.post("/summarize", response_model=SummarizeResponse)
async def summarize(
    req: SummarizeRequest,
    _invite: str = Depends(require_invite),
) -> SummarizeResponse:
    message = f"Filename: {req.filename}\nSummarize this file.\n\n{req.text}"

    try:
        agent = build_agent(prompts.SUMMARIZE_PROMPT, FileSummary, settings.summarize_model)
        result = await agent.run(message)
    except Exception as e:  # pylint: disable=broad-except
        status_code, detail = user_facing_error(e)
        raise HTTPException(status_code=status_code, detail=detail) from e

    return SummarizeResponse(
        summary=result.output,
        prompt_version=prompts.PROMPT_VERSIONS["summarize"],
    )
