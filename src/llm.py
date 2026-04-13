"""Shared LLM client construction for all agents (summarize / rewrite / answer).

Which provider is used is selected by the `LLM_PROVIDER` env var (default:
`moonshot`). Each provider has its own set of env vars so keys can coexist
without stepping on each other — flipping `LLM_PROVIDER` is enough to swap.

Adding another OpenAI-compatible provider is a matter of adding one entry
to `PROVIDERS`; no changes at the agent-building call sites are required.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


API_MAX_RETRIES = 5


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key_env: str
    model_env: str
    base_url_env: str
    default_model: str
    default_base_url: str


PROVIDERS: dict[str, ProviderConfig] = {
    "moonshot": ProviderConfig(
        name="moonshot",
        api_key_env="MOONSHOT_API_KEY",
        model_env="MOONSHOT_MODEL",
        base_url_env="MOONSHOT_BASE_URL",
        default_model="kimi-k2.5",
        default_base_url="https://api.moonshot.ai/v1",
    ),
    "openrouter": ProviderConfig(
        name="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        model_env="OPENROUTER_MODEL",
        base_url_env="OPENROUTER_BASE_URL",
        default_model="google/gemma-4-26b-a4b-it:free",
        default_base_url="https://openrouter.ai/api/v1",
    ),
}


def active_provider() -> ProviderConfig:
    """Return the `ProviderConfig` pointed at by the current `LLM_PROVIDER`."""
    name = os.environ.get("LLM_PROVIDER", "moonshot").strip().lower()
    if name not in PROVIDERS:
        sys.exit(
            f"error: LLM_PROVIDER={name!r} is unknown. "
            f"Valid values: {sorted(PROVIDERS)}."
        )
    return PROVIDERS[name]


def build_chat_model() -> OpenAIChatModel:
    """Build an `OpenAIChatModel` for the currently selected provider.

    Reads the provider's api-key / model / base-url env vars, falling back to
    sensible defaults for the latter two. Exits with a clear error if the
    required API key is missing.
    """
    cfg = active_provider()
    api_key = os.environ.get(cfg.api_key_env)
    if not api_key:
        sys.exit(
            f"error: {cfg.api_key_env} not set for provider {cfg.name!r} "
            f"(put it in .env or change LLM_PROVIDER)"
        )
    model = os.environ.get(cfg.model_env, cfg.default_model)
    base_url = os.environ.get(cfg.base_url_env, cfg.default_base_url)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=API_MAX_RETRIES)
    return OpenAIChatModel(model, provider=OpenAIProvider(openai_client=client))


def active_model_name() -> str:
    """The model string the next `build_chat_model()` call would use.

    Useful for logging / reports / eval markdown headers.
    """
    cfg = active_provider()
    return os.environ.get(cfg.model_env, cfg.default_model)
