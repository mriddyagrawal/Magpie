"""Shared LLM client construction for all agents (summarize / rewrite / answer).

Which provider is used is selected by the `LLM_PROVIDER` env var (default:
`moonshot`). Three providers are supported:

- `moonshot` — Moonshot Kimi via OpenAI-compatible API
- `openrouter` — OpenRouter (Gemma, Claude, GPT, etc.) via OpenAI-compatible API
- `local` — Local Apple-Silicon inference via `mlx-vlm` (Gemma 3n E4B 4-bit by default)

Call sites use `build_agent(system_prompt, output_type, fallback)` which
returns a `ChatAgent` with `.run(message)` / `.run_sync(message)`. The factory
dispatches on the active provider: cloud providers wrap PydanticAI's `Agent`
against an OpenAI-compatible `OpenAIChatModel`; `local` returns a `LocalAgent`
that drives `mlx-vlm` directly and parses structured output with a JSON-repair
fallback.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import platform
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from pydantic_ai.models.openai import OpenAIChatModel


API_MAX_RETRIES = 5
LOCAL_MAX_TOKENS = 2048


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
        # Gemini 2.0 Flash on the free tier: vision-capable, structured output
        # support works well with pydantic-ai, ~20 RPM quota.
        default_model="google/gemini-2.0-flash-exp:free",
        default_base_url="https://openrouter.ai/api/v1",
    ),
    # Local Ollama daemon on Linux / Windows / Intel-Mac (anything with
    # an OpenAI-compatible local server). No API key needed — the daemon
    # ignores auth. Default model is a 3B vision-capable Qwen that fits
    # alongside ColPali on a 6 GB GPU.
    "ollama": ProviderConfig(
        name="ollama",
        api_key_env="OLLAMA_API_KEY",
        model_env="OLLAMA_MODEL",
        base_url_env="OLLAMA_BASE_URL",
        default_model="qwen2.5vl:3b",
        default_base_url="http://localhost:11434/v1",
    ),
    "local": ProviderConfig(
        name="local",
        api_key_env="",
        model_env="LOCAL_MODEL",
        base_url_env="",
        default_model="mlx-community/gemma-3n-E2B-it-4bit",
        default_base_url="",
    ),
}


def active_provider() -> ProviderConfig:
    """Return the `ProviderConfig` pointed at by the current `LLM_PROVIDER`."""
    name = os.environ.get("LLM_PROVIDER", "openrouter").strip().lower()
    if name not in PROVIDERS:
        sys.exit(
            f"error: LLM_PROVIDER={name!r} is unknown. "
            f"Valid values: {sorted(PROVIDERS)}."
        )
    return PROVIDERS[name]


def active_model_name() -> str:
    """The model string the active provider would use for its next call."""
    cfg = active_provider()
    return os.environ.get(cfg.model_env, cfg.default_model)


def build_chat_model() -> OpenAIChatModel:
    """Build an OpenAI-compatible chat model for the active cloud provider.

    Raises for `LLM_PROVIDER=local` — the local branch of `build_agent` does
    not go through this path.
    """
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    cfg = active_provider()
    if cfg.name == "local":
        raise RuntimeError(
            "build_chat_model() is for cloud providers; "
            "local inference uses LocalAgent directly (see build_agent)."
        )
    api_key = os.environ.get(cfg.api_key_env)
    if not api_key:
        # Ollama's local server ignores the Authorization header; we pass a
        # placeholder so the OpenAI client doesn't refuse to send the request.
        if cfg.name == "ollama":
            api_key = "ollama"
        else:
            sys.exit(
                f"error: {cfg.api_key_env} not set for provider {cfg.name!r} "
                f"(put it in .env or change LLM_PROVIDER)"
            )
    model = os.environ.get(cfg.model_env, cfg.default_model)
    base_url = os.environ.get(cfg.base_url_env, cfg.default_base_url)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=API_MAX_RETRIES)
    return OpenAIChatModel(model, provider=OpenAIProvider(openai_client=client))


# ---------------------------------------------------------------------------
# ChatAgent protocol + factory
# ---------------------------------------------------------------------------

T = TypeVar("T", bound=BaseModel)


def _timestamp_prefix() -> str:
    """Short 'Current date and time: ...' line prepended to every LLM call.

    Local time with timezone so the model can reason about 'today', 'this
    semester', 'is this receipt recent', etc. Evaluated per-call, not baked
    into the system prompt.
    """
    now = datetime.now().astimezone()
    return f"Current date and time: {now.strftime('%A, %Y-%m-%d %H:%M %Z')}"


def _prepend_timestamp(message: list) -> list:
    return [_timestamp_prefix(), *message]


class ChatAgent(Protocol, Generic[T]):
    """Minimal agent surface used by call sites (summarize / rewrite / answer)."""

    async def run(self, message: list) -> T: ...

    def run_sync(self, message: list) -> T: ...


class _CloudAgent(Generic[T]):
    """Thin adapter around a PydanticAI Agent so cloud and local share a shape.

    `.run()` / `.run_sync()` return the parsed Pydantic object directly (i.e.
    `result.output`), matching what `LocalAgent` returns.
    """

    def __init__(self, system_prompt: str, output_type: type[T]) -> None:
        from pydantic_ai import Agent, NativeOutput

        self._agent: Agent[None, T] = Agent(
            build_chat_model(),
            output_type=NativeOutput(output_type),
            system_prompt=system_prompt,
            retries=3,
        )

    async def run(self, message: list) -> T:
        result = await self._agent.run(_prepend_timestamp(message))
        return result.output

    def run_sync(self, message: list) -> T:
        result = self._agent.run_sync(_prepend_timestamp(message))
        return result.output


def build_agent(
    system_prompt: str,
    output_type: type[T],
    fallback: T | None,
) -> ChatAgent[T]:
    """Construct a ChatAgent for the active provider.

    - `system_prompt` — instructions (identical across providers).
    - `output_type` — Pydantic BaseModel subclass for the structured output.
    - `fallback` — optional instance of `output_type` used by the local path
      when the model emits unparseable JSON. Pass `None` to force the local
      path to raise `JSONParseError` instead (matches the cloud behavior
      where a file is skipped rather than indexed with a placeholder).
      Ignored by cloud providers (PydanticAI's native validation either
      succeeds or raises).
    """
    cfg = active_provider()
    if cfg.name == "local":
        return LocalAgent(system_prompt, output_type, fallback)
    return _CloudAgent(system_prompt, output_type)


# ---------------------------------------------------------------------------
# Local MLX backend
# ---------------------------------------------------------------------------

_model_cache: tuple[Any, Any, Any] | None = None


def _require_apple_silicon() -> None:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        sys.exit(
            "error: LLM_PROVIDER=local requires an Apple Silicon Mac "
            f"(got platform={sys.platform!r}, machine={platform.machine()!r}). "
            "Set LLM_PROVIDER=moonshot or LLM_PROVIDER=openrouter instead."
        )


def get_model() -> tuple[Any, Any, Any]:
    """Load (on first call) and return the cached (model, processor, config).

    The load is several seconds on a warm machine, several minutes on first
    run (while the weights download from Hugging Face). Cached for the
    lifetime of the process — all subsequent calls are free.
    """
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    _require_apple_silicon()
    from mlx_vlm import load
    from mlx_vlm.utils import load_config

    model_name = active_model_name()
    print(f"  loading local model: {model_name} (first run may take a few minutes)", file=sys.stderr)
    model, processor = load(model_name)
    config = load_config(model_name)
    _model_cache = (model, processor, config)
    print(f"  model loaded", file=sys.stderr)
    return _model_cache


# ---------------------------------------------------------------------------
# JSON parsing with repair
# ---------------------------------------------------------------------------

_FENCE_OPEN = re.compile(r"^\s*```(?:json)?\s*\n?", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"\n?\s*```\s*$")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class JSONParseError(RuntimeError):
    """Raised when model output can't be coerced into the requested schema
    and the caller did not provide a fallback.

    Carries the raw output on `.raw` so callers can log or inspect it.
    """

    def __init__(self, message: str, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


def parse_json_with_repair(raw: str, schema: type[T], fallback: T | None) -> T:
    """Parse `raw` into `schema`, trying progressively more aggressive cleanups.

    If all attempts fail:
    - `fallback is not None` → log to stderr, return the fallback.
    - `fallback is None` → raise `JSONParseError(..., raw)`. Use this when the
      caller prefers to skip the unit of work (e.g. summarization of one file)
      rather than ingest a placeholder.
    """
    try:
        return schema.model_validate_json(raw)
    except Exception:
        pass

    # Strip ```json / ``` fences
    stripped = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", raw.strip()))
    if stripped != raw:
        try:
            return schema.model_validate_json(stripped)
        except Exception:
            pass

    # Extract first {...} by non-greedy brace match
    match = _JSON_OBJECT.search(stripped)
    if match:
        try:
            return schema.model_validate_json(match.group(0))
        except Exception:
            pass

    # Log the raw output on every hard failure — this is the primary
    # diagnostic. Useful whether we raise or fall back.
    truncated = raw[:2000] + ("...(truncated)" if len(raw) > 2000 else "")
    print(
        f"  warn: {schema.__name__} JSON repair failed.\n"
        f"  raw output:\n{truncated}",
        file=sys.stderr,
    )

    if fallback is None:
        raise JSONParseError(
            f"{schema.__name__} JSON repair failed (raw output logged above)",
            raw,
        )
    return fallback


# ---------------------------------------------------------------------------
# LocalAgent
# ---------------------------------------------------------------------------

class LocalAgent(Generic[T]):
    """MLX-backed agent. Same .run()/.run_sync() shape as _CloudAgent."""

    def __init__(
        self,
        system_prompt: str,
        output_type: type[T],
        fallback: T | None,
    ) -> None:
        self._system_prompt = system_prompt
        self._output_type = output_type
        self._fallback = fallback

    async def run(self, message: list) -> T:
        return await asyncio.to_thread(self._run_sync_impl, _prepend_timestamp(message))

    def run_sync(self, message: list) -> T:
        # If an event loop is already running (async context), delegate via
        # asyncio.run_coroutine_threadsafe pattern isn't needed here because
        # all sync callers (search.rewrite_query) come from non-async code.
        return self._run_sync_impl(_prepend_timestamp(message))

    def _run_sync_impl(self, message: list) -> T:
        prompt_text, images = self._serialize_message(message)
        model, processor, config = get_model()

        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        formatted = apply_chat_template(
            processor, config, prompt_text, num_images=len(images)
        )
        # Prefill the opening brace so the model's first generated token is
        # already inside a JSON object. Small models ignore "output JSON" as
        # an instruction but reliably continue a pattern once started.
        formatted = formatted + "{"
        output = generate(
            model,
            processor,
            formatted,
            images if images else None,
            max_tokens=LOCAL_MAX_TOKENS,
            verbose=False,
        )
        # `generate` historically returns a string in newer versions of mlx-vlm
        # but may return a GenerateResult object. Normalise to the text.
        raw = getattr(output, "text", output)
        if not isinstance(raw, str):
            raw = str(raw)
        # Re-attach the prefilled `{` so the parser sees a full JSON object.
        raw = "{" + raw
        return parse_json_with_repair(raw, self._output_type, self._fallback)

    def _serialize_message(self, message: list) -> tuple[str, list]:
        """Split the incoming message list into (prompt_text, [PIL images]).

        Duck-types `BinaryContent` by checking for `.data` and `.media_type`.
        Keeps system prompt as a prefix.
        """
        from PIL import Image

        text_parts: list[str] = [self._system_prompt]
        images: list = []
        for block in message:
            if isinstance(block, str):
                text_parts.append(block)
            elif hasattr(block, "data") and hasattr(block, "media_type"):
                try:
                    img = Image.open(io.BytesIO(block.data))
                    img.load()  # force decode before BytesIO goes out of scope
                    images.append(img)
                except Exception as e:
                    text_parts.append(f"[image could not be decoded: {e}]")
            else:
                text_parts.append(str(block))
        return "\n\n".join(text_parts), images
