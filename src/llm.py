"""Shared LLM client construction for all agents (summarize / rewrite / answer).

Which provider is used is selected by the `LLM_PROVIDER` env var (default:
`openrouter`). Supported providers:

- `moonshot` — Moonshot Kimi via OpenAI-compatible API
- `openrouter` — OpenRouter (Gemma, Claude, GPT, etc.) via OpenAI-compatible API
- `ollama` — Local Ollama OpenAI-compatible server (Linux/Win/Intel-Mac)
- `local` — In-process local inference via llama-cpp-python + GGUF
- `magpie-cloud` — Magpie's hosted backend (`server/magpie_server`)

Call sites use `build_agent(system_prompt, output_type, fallback)` which
returns a `ChatAgent` with `.run(message)` / `.run_sync(message)`. The factory
dispatches on the active provider: cloud providers wrap PydanticAI's `Agent`
against an OpenAI-compatible `OpenAIChatModel`; `local` returns a `LocalAgent`
that drives `llama-cpp-python` directly and parses structured output via
JSON-repair (no native structured-output support in raw chat completion).

`thinking` is a per-call kwarg on `run`/`run_sync`. Local honors it (Gemma 4
`<|think|>` token); cloud agents accept it but no-op with a one-time warning
until per-provider reasoning APIs are wired (see Plans/Future Plans.md #16).
"""

from __future__ import annotations

import json
import os
import re
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

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
    # Ollama daemon on Linux / Windows / Intel-Mac (anything with an
    # OpenAI-compatible local server). No API key needed — the daemon
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
    # In-process llama-cpp-python (cross-platform: Metal on macOS, CUDA on
    # Linux/Windows, CPU fallback). See Plans/Local LLM Plan.md. The
    # `model_env`/`default_model` here is the HF GGUF *repo*; the specific
    # quant is selected by `LOCAL_QUANT` (default Q5_K_XL). Runtime knobs
    # (`LOCAL_N_CTX`, `LOCAL_N_GPU_LAYERS`, `LOCAL_TEMPERATURE`) are read
    # by `src.inference.local_llm`.
    "local": ProviderConfig(
        name="local",
        api_key_env="",
        model_env="LOCAL_MODEL",
        base_url_env="",
        default_model="unsloth/gemma-4-E4B-it-GGUF",
        default_base_url="",
    ),
    # Magpie Cloud — hosted backend that holds the prompts and proxies
    # LLM calls (server/magpie_server). The desktop sends questions +
    # snippets; the cloud server returns structured answers. No
    # OpenAI-compatible base URL — communication uses our own /llm/* JSON
    # endpoints, dispatched by `src/cloud_provider.py`.
    "magpie-cloud": ProviderConfig(
        name="magpie-cloud",
        api_key_env="MAGPIE_INVITE_CODE",
        model_env="",                          # model is chosen server-side
        base_url_env="MAGPIE_CLOUD_URL",
        default_model="(server-decided)",
        default_base_url="http://127.0.0.1:8000",
    ),
}


def active_provider() -> ProviderConfig:
    """Return the `ProviderConfig` pointed at by the current settings.

    Resolution order (matches `Plans/UI/Implementation Plan.md` PR 3):

      1. `LLM_PROVIDER` env var — explicit override, wins absolutely.
         Preserves today's dev-mode behavior (`LLM_PROVIDER=openrouter
         just chat` keeps working).
      2. `settings.json` (UserSettings) — the user's choice via the
         Settings UI (Local vs Cloud). When provider="cloud", we
         dispatch to `cloud_provider` (e.g., "openrouter") from
         AppDefaults; the user never sees the provider name in the
         UI.
      3. Hardcoded fallback "openrouter" — preserves pre-PR-3 behavior
         when neither env nor settings.json have been touched.
    """
    raw_env = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if raw_env:
        if raw_env not in PROVIDERS:
            sys.exit(
                f"error: LLM_PROVIDER={raw_env!r} is unknown. "
                f"Valid values: {sorted(PROVIDERS)}."
            )
        return PROVIDERS[raw_env]

    # No env override → consult settings.json. Lazy import to avoid a
    # cold cycle on `from src.llm import ...` and to keep this module
    # importable in environments where the config layer isn't built yet.
    try:
        from src.config.settings import effective_settings
        s = effective_settings()
    except Exception:  # noqa: BLE001 — defensive, never block on settings
        s = None

    if s is not None:
        if s.provider == "cloud":
            cfg = PROVIDERS.get(s.cloud_provider)
            if cfg is None:
                sys.exit(
                    f"error: settings.json cloud_provider={s.cloud_provider!r} "
                    f"is unknown. Valid: {sorted(PROVIDERS)}."
                )
            return cfg
        if s.provider == "local":
            return PROVIDERS["local"]

    return PROVIDERS["openrouter"]


def active_model_name() -> str:
    """The model string the active provider would use for its next call."""
    cfg = active_provider()
    return os.environ.get(cfg.model_env, cfg.default_model)


def build_chat_model(*, provider_override: str | None = None) -> OpenAIChatModel:
    """Build an OpenAI-compatible chat model.

    Without `provider_override`, builds against `LLM_PROVIDER` (the active
    provider). With `provider_override`, builds against that named provider
    instead — used by the fallback path in `src/stage1/summarize.py` to spin
    up a parallel local-or-different-cloud agent without mutating the env.

    Raises for `local` — the llama-cpp path does not go through this builder
    (see `LocalAgent`).
    """
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    if provider_override is not None:
        if provider_override not in PROVIDERS:
            sys.exit(
                f"error: provider_override={provider_override!r} is unknown. "
                f"Valid values: {sorted(PROVIDERS)}."
            )
        cfg = PROVIDERS[provider_override]
    else:
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
            # Bundled-app fallback: in production there's no `.env`; the
            # cloud key lives in `<APP_DATA_DIR>/secrets.json`. Lazy import
            # to keep cold-load cheap. Only consulted when the env var is
            # genuinely unset — env wins, secrets is the second-chance lookup.
            try:
                from src.config.secrets import load_secrets
                api_key = (load_secrets().cloud_api_key or "").strip()
            except Exception:  # noqa: BLE001 — secrets layer must not block startup
                api_key = ""
            if not api_key:
                sys.exit(
                    f"error: {cfg.api_key_env} not set for provider "
                    f"{cfg.name!r} (put it in .env, set it in Settings → "
                    f"Search & AI, or change LLM_PROVIDER)"
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
    """Minimal agent surface used by call sites (summarize / rewrite / answer).

    `thinking=True` requests model-internal reasoning before the final
    response. Local agents (Gemma 4) honor it; cloud agents currently
    no-op + warn (see Plans/Future Plans.md #16 for the cross-provider
    unification work).
    """

    async def run(self, message: list, *, thinking: bool = False) -> T: ...

    def run_sync(self, message: list, *, thinking: bool = False) -> T: ...


# Track that we've already warned about cloud thinking-mode this process,
# so a hot loop doesn't drown stderr in the same warning.
_cloud_thinking_warned = False


def _warn_cloud_thinking_unsupported(provider_name: str) -> None:
    global _cloud_thinking_warned
    if _cloud_thinking_warned:
        return
    _cloud_thinking_warned = True
    warnings.warn(
        f"thinking=True was requested but the active provider {provider_name!r} "
        f"doesn't yet expose a unified reasoning toggle. Continuing without it. "
        f"See Plans/Future Plans.md #16 for the cross-provider thinking-mode plan.",
        stacklevel=3,
    )


class _CloudAgent(Generic[T]):
    """Thin adapter around a PydanticAI Agent so cloud and local share a shape.

    `.run()` / `.run_sync()` return the parsed Pydantic object directly (i.e.
    `result.output`), matching what `LocalAgent` returns.
    """

    def __init__(
        self,
        system_prompt: str,
        output_type: type[T],
        *,
        provider_override: str | None = None,
    ) -> None:
        from pydantic_ai import Agent, NativeOutput

        self._agent: Agent[None, T] = Agent(
            build_chat_model(provider_override=provider_override),
            output_type=NativeOutput(output_type),
            system_prompt=system_prompt,
            retries=3,
        )
        self._provider_name = (
            provider_override
            if provider_override is not None
            else active_provider().name
        )

    async def run(self, message: list, *, thinking: bool = False) -> T:
        if thinking:
            _warn_cloud_thinking_unsupported(self._provider_name)
        result = await self._agent.run(_prepend_timestamp(message))
        return result.output

    def run_sync(self, message: list, *, thinking: bool = False) -> T:
        if thinking:
            _warn_cloud_thinking_unsupported(self._provider_name)
        result = self._agent.run_sync(_prepend_timestamp(message))
        return result.output


def build_agent(
    system_prompt: str,
    output_type: type[T],
    fallback: T | None,
    *,
    provider_override: str | None = None,
) -> ChatAgent[T]:
    """Construct a ChatAgent for the active provider (or an override).

    - `system_prompt` — instructions (identical across providers).
    - `output_type` — Pydantic BaseModel subclass for the structured output.
    - `fallback` — optional instance of `output_type` used by the local path
      when the model emits unparseable JSON. Pass `None` to force the local
      path to raise `JSONParseError` instead (matches the cloud behavior
      where a file is skipped rather than indexed with a placeholder).
      Ignored by cloud providers (PydanticAI's native validation either
      succeeds or raises).
    - `provider_override` — build against a specific provider name instead
      of `LLM_PROVIDER`. Used by the fallback path so we can spin up a
      backup agent (e.g. Ollama) without mutating env vars.
    """
    cfg = (
        PROVIDERS[provider_override] if provider_override is not None
        else active_provider()
    )
    if cfg.name == "local":
        return LocalAgent(system_prompt, output_type, fallback)
    if cfg.name == "magpie-cloud":
        # Cloud-managed path: prompts live server-side, the desktop just
        # POSTs questions/snippets to /llm/* endpoints. system_prompt and
        # fallback are both ignored — the server controls them. See
        # `src/cloud_provider.py` for the dispatch logic.
        from src.cloud_provider import build_cloud_agent
        return build_cloud_agent(output_type)  # type: ignore[return-value]
    return _CloudAgent(system_prompt, output_type, provider_override=provider_override)


# ---------------------------------------------------------------------------
# JSON parsing with repair
# ---------------------------------------------------------------------------

_FENCE_OPEN = re.compile(r"^\s*```(?:json)?\s*\n?", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"\n?\s*```\s*$")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _coerce_field_name_drift(json_text: str) -> dict | None:
    """Rescue payloads where the model wrote `{<some-name>: ..., sources_used: [...]}`
    instead of `{answer: ..., sources_used: [...]}`. Returns a dict with
    `answer` filled in from the misnamed key, or None if the input doesn't
    match the rescuable shape.

    Rescue is intentionally narrow — fires only when:
      - the JSON parses cleanly to a dict
      - the dict has exactly one key besides `sources_used`
      - the misnamed key's value is a string OR a list (we join lists into
        bulleted prose so the schema's `answer: str` validates)
    Anything more ambiguous (multiple unknown keys, mismatched types) falls
    through to the existing fallback / JSONParseError path.
    """
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "sources_used" not in payload:
        return None
    other_keys = [k for k in payload if k != "sources_used"]
    if len(other_keys) != 1:
        return None
    answer_value = payload[other_keys[0]]
    if isinstance(answer_value, str):
        pass
    elif isinstance(answer_value, list):
        # Render as bulleted prose so it validates as `answer: str`. Items
        # cast to str defensively (model occasionally embeds nested objects).
        answer_value = "\n".join(f"- {item}" for item in answer_value)
    elif isinstance(answer_value, (int, float, bool)):
        # Numeric / boolean answer (e.g. count questions). Coerce to string.
        answer_value = str(answer_value)
    else:
        # Dicts, None, anything else — too ambiguous to flatten safely.
        # Let the diagnostic path log the raw output.
        return None
    return {"answer": answer_value, "sources_used": payload["sources_used"]}


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

    # Field-name-drift rescue. Small local models reliably get the structural
    # field (`sources_used`) right but rename the prose field to something
    # question-flavored (`courses_mentioned`, `result`, `findings`, etc.).
    # If the payload has `sources_used` plus exactly one other key, AND the
    # schema declares an `answer: str` field, coerce the wrong-named key into
    # `answer`. Only fires when the schema actually expects `answer` — won't
    # silently corrupt other Pydantic models routed through this helper.
    if match and "answer" in getattr(schema, "model_fields", {}):
        coerced = _coerce_field_name_drift(match.group(0))
        if coerced is not None:
            try:
                return schema.model_validate(coerced)
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
# LocalAgent — llama-cpp-python (cross-platform)
# ---------------------------------------------------------------------------

# Tracked once-per-process: when image content arrives on the local
# backend, we forward the bytes to the vision profile (Gemma 4 + mmproj
# via llama-server). Non-image binary blocks (audio, etc.) still get
# dropped with a one-time warning.
_local_image_drop_warned = False


def _flatten_message_for_local(
    message: list,
    system_prompt: str,
) -> tuple[list[dict], list[bytes]]:
    """Convert the desktop-side message list into chat-completion format.

    The desktop builds messages as a heterogeneous list — strings interleaved
    with `BinaryContent` for image-bearing T3 calls. We:

      - Pull the system prompt out as its own message
      - Concatenate all string parts into one user message
      - Collect image bytes from `BinaryContent` blocks (via duck-typed
        `data` + `media_type` attributes) for the LocalLLM `images` kwarg
      - Drop any non-image binary blocks with a one-time warning

    Returns `(messages, images)`. `images` is `[]` when the file is text-only.
    The caller decides whether to forward `images` based on whether a
    vision profile is registered.
    """

    global _local_image_drop_warned

    text_parts: list[str] = []
    image_blobs: list[bytes] = []
    n_dropped = 0
    for block in message:
        if isinstance(block, str):
            text_parts.append(block)
            continue
        # BinaryContent is duck-typed here so we don't import pydantic_ai —
        # the local backend keeps that dep optional.
        data = getattr(block, "data", None)
        media = getattr(block, "media_type", "") or ""
        if isinstance(data, (bytes, bytearray)) and media.startswith("image/"):
            image_blobs.append(bytes(data))
        else:
            n_dropped += 1

    if n_dropped > 0 and not _local_image_drop_warned:
        _local_image_drop_warned = True
        warnings.warn(
            f"local LLM backend dropped {n_dropped} non-image binary content "
            f"block(s). Image blocks ARE forwarded to the local vision profile; "
            f"audio / other binary types are not yet supported. For full "
            f"multimodal use LLM_PROVIDER=openrouter or moonshot.",
            stacklevel=4,
        )

    # Add a hint that the model should output JSON only — small models often
    # don't otherwise. parse_json_with_repair handles failures, but a clean
    # JSON-only response is faster + less noisy.
    user_text = "\n\n".join(text_parts).strip() + (
        "\n\nRespond with a single valid JSON object that matches the "
        "requested schema. Do not include any prose before or after."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ], image_blobs


class LocalAgent(Generic[T]):
    """llama-cpp-python-backed agent. Same .run()/.run_sync() shape as _CloudAgent.

    Uses the singleton `LocalLLM` (one engine, two surfaces — also serves
    the `/generate` endpoint). Structured-output is achieved by
    JSON-repair after-the-fact; small models don't reliably honor
    schema instructions, so the repair pipeline (strip fences → extract
    object → validate) is required.
    """

    def __init__(
        self,
        system_prompt: str,
        output_type: type[T],
        fallback: T | None,
    ) -> None:
        self._system_prompt = system_prompt
        self._output_type = output_type
        self._fallback = fallback

    async def run(self, message: list, *, thinking: bool = False) -> T:
        from src.inference import default_vision_profile, get_local_llm

        msgs, images = _flatten_message_for_local(
            _prepend_timestamp(message), self._system_prompt
        )
        # Drop images when no vision profile is registered (rather than
        # raising), so users without the mmproj installed still get a
        # text-only summary instead of a hard failure.
        if images and default_vision_profile() is None:
            images = []
        llm = get_local_llm()
        raw = await llm.complete(
            msgs,
            thinking=thinking,
            max_tokens=LOCAL_MAX_TOKENS,
            images=images or None,
        )
        return parse_json_with_repair(raw, self._output_type, self._fallback)

    def run_sync(self, message: list, *, thinking: bool = False) -> T:
        from src.inference import default_vision_profile, get_local_llm

        msgs, images = _flatten_message_for_local(
            _prepend_timestamp(message), self._system_prompt
        )
        if images and default_vision_profile() is None:
            images = []
        llm = get_local_llm()
        raw = llm.complete_sync(
            msgs,
            thinking=thinking,
            max_tokens=LOCAL_MAX_TOKENS,
            images=images or None,
        )
        return parse_json_with_repair(raw, self._output_type, self._fallback)
