"""Minimal LLM client using pydantic-ai against OpenRouter.

Single provider for now (OpenRouter — gives access to Kimi, Claude,
GPT-4, Gemini through one API). To swap providers later, change the
`OpenAIProvider(base_url=...)` here and the env vars in settings; the
agent code doesn't change.
"""

from __future__ import annotations

import sys
from typing import Type, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from magpie_server.settings import settings


T = TypeVar("T", bound=BaseModel)


def _build_model(model_name: str) -> OpenAIChatModel:
    """OpenRouter via the OpenAI-compatible API."""
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not configured. Set it in server/.env or via "
            "the hosting provider's secrets manager."
        )
    return OpenAIChatModel(
        model_name=model_name,
        provider=OpenAIProvider(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        ),
    )


def build_agent(
    system_prompt: str,
    output_type: Type[T],
    model_name: str,
) -> Agent[None, T]:
    """Create a typed agent for one prompt + one output schema.

    Each request to `/llm/<endpoint>` builds a fresh agent; pydantic-ai
    handles connection pooling internally via the underlying httpx client.
    """
    return Agent(
        model=_build_model(model_name),
        output_type=output_type,
        system_prompt=system_prompt,
    )


def user_facing_error(exc: Exception) -> tuple[int, str]:
    """Map an internal LLM/provider exception to (HTTP status, user-safe message).

    Same pattern as the desktop sidecar's error mapper — never expose
    provider names, model names, or stack-trace fragments to the client.
    Real exception details are logged to stderr for debugging.
    """
    name = type(exc).__name__
    text = str(exc)
    print(f"[magpie-server] internal error {name}: {text}", file=sys.stderr)

    if "429" in text or "rate" in text.lower() or "quota" in text.lower():
        return 503, "Service is busy right now. Try again in a few seconds."
    if "401" in text or "403" in text or "unauthor" in text.lower() or "api key" in text.lower():
        return 502, "Backend authentication issue. Please report to support."
    if name in ("ConnectionError", "TimeoutError") or "connection" in text.lower():
        return 503, "Can't reach the LLM provider. Try again."
    if "validation" in text.lower() or "parse" in text.lower():
        return 502, "Got an unexpected response. Try again."
    return 500, "Something went wrong. Please try again."
