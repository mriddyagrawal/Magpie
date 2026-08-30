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

import asyncio
import json
import os
import re
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

import httpx
from pydantic import BaseModel

if TYPE_CHECKING:
    from pydantic_ai.models.openai import OpenAIChatModel


API_MAX_RETRIES = 5
# Per-request HTTP timeout for the direct cloud chat-completion call
# in `_CloudAgent`. Generous because some providers + models cold-start
# slowly on the first request of the day.
API_REQUEST_TIMEOUT_S = 90.0
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
        # 127.0.0.1, not localhost — Windows resolves localhost to ::1 first
        # and Ollama binds IPv4 only (same trap as stage2/db.py's Qdrant note).
        default_base_url="http://127.0.0.1:11434/v1",
    ),
    # In-process llama-cpp-python (cross-platform: Metal on macOS, CUDA on
    # Linux/Windows, CPU fallback). See Plans/Local LLM Plan.md. The
    # `model_env`/`default_model` here is the HF GGUF *repo*; the specific
    # quant is selected by `LOCAL_QUANT` (default Q6_K). Runtime knobs
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

    Resolution order:

      1. `settings.json` (UserSettings) — the user's choice via the
         Settings → Search & AI tab (Local vs Cloud). When
         provider="cloud", we dispatch to `cloud_provider` (e.g.,
         "openrouter") from secrets.json, paired with the credentials
         for that provider.
      2. `LLM_PROVIDER` env var — fallback only when settings.json is
         unavailable (degenerate test envs). In normal operation,
         settings.json is seeded from defaults on first launch and
         always carries a value, so env doesn't apply.
      3. Hardcoded fallback "openrouter" — last-resort.

    HISTORY: Earlier, env won absolutely so a dev's `LLM_PROVIDER=local`
    in `.env` overrode the user's Cloud-button click in Settings —
    silently. The env override was changed to a fallback on
    2026-05-08 so the UI choice actually controls routing. The
    justfile's `chat-cloud` recipe (which used `LLM_PROVIDER=magpie-cloud`)
    no longer routes via env; toggle Settings → Cloud or edit
    settings.json directly to test that path.
    """
    # MAGPIE_FORCE_PROVIDER: explicit programmatic override that beats even
    # settings.json. For evaluation harnesses and tests ONLY — never set it
    # in .env. Exists because Evaluations/run_eval.py's --provider flag
    # silently did nothing after the 2026-05-08 precedence flip below: it
    # set LLM_PROVIDER (a settings-unavailable fallback), settings.json
    # always exists, so a "cloud" eval run actually answered with the local
    # model under a cloud label (caught 2026-08-24, first eval run).
    forced = os.environ.get("MAGPIE_FORCE_PROVIDER", "").strip().lower()
    if forced:
        cfg = PROVIDERS.get(forced)
        if cfg is None:
            sys.exit(
                f"error: MAGPIE_FORCE_PROVIDER={forced!r} is unknown. "
                f"Valid: {sorted(PROVIDERS)}."
            )
        return cfg

    # Settings.json is the source of truth. Lazy import to avoid a
    # cold cycle on `from src.llm import ...` and to keep this module
    # importable in environments where the config layer isn't built yet.
    try:
        from src.config.settings import effective_settings
        s = effective_settings()
    except Exception:  # noqa: BLE001 — defensive, never block on settings
        s = None

    if s is not None:
        if s.provider == "cloud":
            # Cloud routing lives in secrets.json (paired with the
            # credentials). cloud_provider is constrained to the v1 set
            # (moonshot/openrouter) by Pydantic Literal, so this is safe.
            try:
                from src.config.secrets import load_secrets
                cloud_provider = load_secrets().cloud_provider
            except Exception:  # noqa: BLE001 — defensive, never block on secrets
                cloud_provider = "openrouter"
            cfg = PROVIDERS.get(cloud_provider)
            if cfg is None:
                sys.exit(
                    f"error: secrets.json cloud_provider={cloud_provider!r} "
                    f"is unknown. Valid: {sorted(PROVIDERS)}."
                )
            return cfg
        if s.provider == "local":
            return PROVIDERS["local"]

    # Settings layer unavailable — last-resort fallback through env.
    raw_env = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if raw_env and raw_env in PROVIDERS:
        return PROVIDERS[raw_env]
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
    secrets_key: str = ""
    secrets_model: str = ""
    if not api_key or not os.environ.get(cfg.model_env):
        # Bundled-app + per-provider fallback path. Production has no
        # `.env`; secrets.json holds the per-provider key + model. Lazy
        # import to keep cold-load cheap. Only consulted when the env
        # var is genuinely unset — env wins, secrets is the
        # second-chance lookup.
        try:
            from src.config.secrets import cloud_credentials_for
            secrets_key, secrets_model = cloud_credentials_for(cfg.name)
        except Exception:  # noqa: BLE001 — secrets layer must not block startup
            secrets_key = secrets_model = ""

    if not api_key:
        # Ollama's local server ignores the Authorization header; we pass a
        # placeholder so the OpenAI client doesn't refuse to send the request.
        if cfg.name == "ollama":
            api_key = "ollama"
        else:
            api_key = secrets_key.strip()
            if not api_key:
                sys.exit(
                    f"error: {cfg.api_key_env} not set for provider "
                    f"{cfg.name!r} (put it in .env, set it in Settings → "
                    f"Search & AI, or change LLM_PROVIDER)"
                )

    # Model resolution: env first, then secrets.json's per-provider
    # field, then the hardcoded ProviderConfig default. This lets
    # deployment swap models via `OPENROUTER_MODEL` env (dev) or
    # secrets.json edits (production) without code changes.
    model = (
        os.environ.get(cfg.model_env)
        or (secrets_model.strip() if secrets_model else "")
        or cfg.default_model
    )
    base_url = os.environ.get(cfg.base_url_env, cfg.default_base_url)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=API_MAX_RETRIES)

    # Disable structured-output `response_format` at the profile level.
    # Why: pydantic-ai's OpenAI client sends one of three things based on
    # the profile flags:
    #   - native mode + supports_json_schema_output → response_format =
    #     {"type": "json_schema", ...}
    #   - prompted mode + supports_json_object_output → response_format =
    #     {"type": "json_object"}
    #   - neither → no response_format field at all
    # OpenRouter routes our Gemma free traffic to Google AI Studio,
    # which silently rejects BOTH variants of response_format —
    # symptom is a malformed completion with id/choices/model/object
    # all None and pydantic-ai's validator throwing four "Input should
    # be a valid X" errors. We force the third path: no response_format,
    # rely on the SYSTEM_PROMPT's JSON-shape guidance + pydantic-ai's
    # PromptedOutput template injection to coax JSON out of the model,
    # then PydanticAI parses the text response.
    # When we eventually add direct provider integrations (Anthropic,
    # OpenAI), those CAN honor response_format and we should restore the
    # flags per-provider. For now, OpenRouter is our only cloud route.
    from pydantic_ai.profiles.openai import (
        OpenAIJsonSchemaTransformer, OpenAIModelProfile,
    )
    profile = OpenAIModelProfile(
        json_schema_transformer=OpenAIJsonSchemaTransformer,
        supports_json_schema_output=False,
        supports_json_object_output=False,
    )
    return OpenAIChatModel(
        model, provider=OpenAIProvider(openai_client=client), profile=profile,
    )


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


def _prepend_timestamp(message: list, *, after_first: bool = False) -> list:
    # `after_first` keeps a cacheable leading part (the answer step's file
    # text) at the very start; the timestamp changes every minute and would
    # otherwise make every prompt unique from token one.
    if after_first and message:
        return [message[0], _timestamp_prefix(), *message[1:]]
    return [_timestamp_prefix(), *message]


# Agents whose output describes a FILE, not a conversation. The timestamp is
# there so the answer step can resolve "this semester" or "is this receipt
# recent" — at index time it is just a plausible-looking date sitting in the
# context, and a 3B copies it. Measured on sem_4 after the prompt-example fix:
# `2026-08-27` (the run date) turned up as a claimed *document identifier* in
# a Cursor invoice, a finance handout and a VR storyboard, none of which
# contain it. Same copying failure as the Jane Doe example, different source.
_NO_TIMESTAMP_OUTPUTS = {"FileSummary"}


def _wants_timestamp(output_type: type | None) -> bool:
    return getattr(output_type, "__name__", "") not in _NO_TIMESTAMP_OUTPUTS


class ChatAgent(Protocol, Generic[T]):
    """Minimal agent surface used by call sites (summarize / rewrite / answer).

    `thinking=True` requests model-internal reasoning before the final
    response. Local agents (Gemma 4) honor it; cloud agents currently
    no-op + warn (see Plans/Future Plans.md #16 for the cross-provider
    unification work).
    """

    async def run(
        self, message: list, *, thinking: bool = False,
        temperature: float | None = None,
        kv_prefix: str | None = None,
    ) -> T: ...

    def run_sync(
        self, message: list, *, thinking: bool = False,
        temperature: float | None = None,
        kv_prefix: str | None = None,
    ) -> T: ...


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
    """Direct-HTTP cloud agent. Same .run()/.run_sync() shape as LocalAgent.

    HISTORY (2026-05-08): We previously used pydantic-ai's `Agent` with
    `PromptedOutput`. That sent `response_format={"type": "json_object"}`
    along with a pile of other fields (parallel_tool_calls, service_tier,
    reasoning_effort, etc.) that OpenRouter forwarded to upstream. Google
    AI Studio (which serves the free Gemma-4 line) rejected the request
    silently — the response body was an error envelope, the OpenAI SDK
    parsed it as a ChatCompletion, and pydantic-ai threw four "Input
    should be a valid X" errors with id/choices/model/object all None.

    Since the user's bare-curl test against the same model + key worked
    fine (clean OpenAI-shape response), the simplest fix is to mirror
    the bare-curl request: model, messages, optional temperature —
    nothing else. No tools, no response_format, no thinking, no service
    tier. Then parse the response with `parse_json_with_repair` (same
    helper LocalAgent uses). PromptedOutput's value (system-prompt JSON
    schema injection) is captured by our existing SYSTEM_PROMPT, which
    already lists the four required keys and emits worked examples.

    Pydantic-ai is still used for the Agent shape protocol (LocalAgent
    inherits ChatAgent[T]) but is no longer in the cloud request path.
    """

    def __init__(
        self,
        system_prompt: str,
        output_type: type[T],
        *,
        provider_override: str | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._output_type = output_type
        # Resolve credentials + base URL once. Same lookup as
        # build_chat_model: env wins, secrets.json is the second-chance
        # fallback (for bundled-app installs without a .env).
        cfg = (
            PROVIDERS[provider_override] if provider_override is not None
            else active_provider()
        )
        if cfg.name == "local":
            raise RuntimeError(
                "_CloudAgent shouldn't be constructed for the local provider."
            )
        self._provider_name = cfg.name
        api_key = os.environ.get(cfg.api_key_env, "").strip()
        model = os.environ.get(cfg.model_env, "").strip()
        if not api_key or not model:
            try:
                from src.config.secrets import cloud_credentials_for
                sk, sm = cloud_credentials_for(cfg.name)
                api_key = api_key or sk.strip()
                model = model or sm.strip()
            except Exception:  # noqa: BLE001
                pass
        if not api_key:
            sys.exit(
                f"error: {cfg.api_key_env} not set for cloud provider "
                f"{cfg.name!r}. Configure it in .env, secrets.json, or "
                f"Settings → Search & AI → switch to Local."
            )
        self._api_key = api_key
        self._model = model or cfg.default_model
        self._base_url = os.environ.get(cfg.base_url_env, cfg.default_base_url)

    # Per-provider fallback chains for OpenRouter's `models` field — the
    # provider's officially-recommended reliability pattern. When the
    # primary model is overloaded / rate-limited / 5xx, OpenRouter
    # automatically tries the next entry in order. Free Gemma routes are
    # known to flake (504 "operation was aborted" / 502 provider_unavailable);
    # the 31B fallback uses a different upstream so a same-time outage
    # of the 26B route doesn't blow up the user's query. See
    # https://openrouter.ai/docs/guides/routing/model-fallbacks
    _OPENROUTER_FALLBACKS: dict[str, list[str]] = {
        "google/gemma-4-26b-a4b-it:free": [
            "google/gemma-4-26b-a4b-it:free",
            "google/gemma-4-31b-it:free",
        ],
        "google/gemma-4-31b-it:free": [
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
        ],
    }

    def _build_body(
        self, message: list, temperature: float | None,
    ) -> dict[str, Any]:
        """Bare chat.completions request body — no tools, no
        response_format, no thinking knobs. Mirrors a known-good curl.

        For OpenRouter, also adds a `models` fallback chain when the
        primary is one we know flakes (free Gemma routes). OpenRouter
        cascades through the list automatically on upstream failure."""
        # Reuse the local-side flattener: pulls images off (we drop
        # them — vision through OpenRouter is provider-specific and
        # not wired today), concatenates text into one user message,
        # appends the JSON-shape reminder.
        msgs, _images_dropped = _flatten_message_for_local(
            _prepend_timestamp(message)
            if _wants_timestamp(self._output_type)
            else message,
            self._system_prompt
        )
        body: dict[str, Any] = {
            "model": self._model,
            "messages": msgs,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if self._provider_name == "openrouter":
            fallbacks = self._OPENROUTER_FALLBACKS.get(self._model)
            if fallbacks:
                body["models"] = fallbacks
        return body

    # Retry transient upstream failures. Free OpenRouter routes
    # frequently 502/504 ("provider_unavailable" / "operation was
    # aborted") for a few seconds, then recover. Two retries with
    # exponential backoff (1s, 2s) covers the common case without
    # making the user wait long on genuine outages.
    _CLOUD_RETRY_ATTEMPTS = 3
    _CLOUD_RETRY_BACKOFF_S = 1.0

    async def run(
        self, message: list, *, thinking: bool = False,
        temperature: float | None = None,
        kv_prefix: str | None = None,  # local-only; no equivalent on cloud
    ) -> T:
        from src.inference.llm_log import log_request, log_response

        if thinking:
            _warn_cloud_thinking_unsupported(self._provider_name)
        body = self._build_body(message, temperature)
        request_id = log_request(
            provider=self._provider_name,
            model=self._model,
            messages=body["messages"],
            system_prompt=self._system_prompt,
            temperature=temperature,
            extra={"models_fallback": body.get("models")},
        )
        last_err: Exception | None = None
        for attempt in range(self._CLOUD_RETRY_ATTEMPTS):
            t_start = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=API_REQUEST_TIMEOUT_S) as client:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=body,
                    )
                content, usage = self._parse_and_log(resp, request_id, t_start)
                return parse_json_with_repair(content, self._output_type, None)
            except RuntimeError as e:
                if not self._is_retryable(e):
                    log_response(
                        request_id=request_id,
                        provider=self._provider_name,
                        model=self._model,
                        latency_s=time.monotonic() - t_start,
                        error=str(e),
                    )
                    raise
                last_err = e
                if attempt < self._CLOUD_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(
                        self._CLOUD_RETRY_BACKOFF_S * (2 ** attempt)
                    )
        log_response(
            request_id=request_id, provider=self._provider_name,
            model=self._model, latency_s=0.0,
            error=f"all {self._CLOUD_RETRY_ATTEMPTS} attempts failed: {last_err}",
        )
        assert last_err is not None
        raise last_err

    def run_sync(
        self, message: list, *, thinking: bool = False,
        temperature: float | None = None,
        kv_prefix: str | None = None,
    ) -> T:
        from src.inference.llm_log import log_request, log_response

        if thinking:
            _warn_cloud_thinking_unsupported(self._provider_name)
        body = self._build_body(message, temperature)
        request_id = log_request(
            provider=self._provider_name,
            model=self._model,
            messages=body["messages"],
            system_prompt=self._system_prompt,
            temperature=temperature,
            extra={"models_fallback": body.get("models")},
        )
        last_err: Exception | None = None
        for attempt in range(self._CLOUD_RETRY_ATTEMPTS):
            t_start = time.monotonic()
            try:
                with httpx.Client(timeout=API_REQUEST_TIMEOUT_S) as client:
                    resp = client.post(
                        f"{self._base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=body,
                    )
                content, usage = self._parse_and_log(resp, request_id, t_start)
                return parse_json_with_repair(content, self._output_type, None)
            except RuntimeError as e:
                if not self._is_retryable(e):
                    from src.inference.llm_log import log_response
                    log_response(
                        request_id=request_id,
                        provider=self._provider_name,
                        model=self._model,
                        latency_s=time.monotonic() - t_start,
                        error=str(e),
                    )
                    raise
                last_err = e
                if attempt < self._CLOUD_RETRY_ATTEMPTS - 1:
                    time.sleep(self._CLOUD_RETRY_BACKOFF_S * (2 ** attempt))
        from src.inference.llm_log import log_response
        log_response(
            request_id=request_id, provider=self._provider_name,
            model=self._model, latency_s=0.0,
            error=f"all {self._CLOUD_RETRY_ATTEMPTS} attempts failed: {last_err}",
        )
        assert last_err is not None
        raise last_err

    @staticmethod
    def _is_retryable(err: Exception) -> bool:
        """5xx upstream errors are transient — retry. 4xx (auth, rate
        limits with retry-after, malformed body) are caller-driven —
        don't retry, surface immediately."""
        msg = str(err)
        # Match "HTTP 5xx" or upstream code 5xx in malformed-response branch.
        return "HTTP 5" in msg or "code': 5" in msg or "operation was aborted" in msg

    def _parse_and_log(
        self, resp: httpx.Response, request_id: str, t_start: float,
    ) -> tuple[str, dict | None]:
        """Validate the HTTP response, extract content + usage, log
        them. Returns `(content, usage)`. Surfaces upstream error
        envelopes as RuntimeError so the retry loop can decide whether
        to retry — the response log is written either way."""
        from src.inference.llm_log import log_response
        latency = time.monotonic() - t_start
        if resp.status_code != 200:
            try:
                payload = resp.json()
                err = payload.get("error") if isinstance(payload, dict) else None
                msg = err.get("message") if isinstance(err, dict) else str(payload)
            except Exception:  # noqa: BLE001
                msg = resp.text[:500]
            log_response(
                request_id=request_id, provider=self._provider_name,
                model=self._model, latency_s=latency,
                raw_status=resp.status_code, error=str(msg),
            )
            raise RuntimeError(
                f"{self._provider_name} returned HTTP {resp.status_code}: {msg}"
            )
        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log_response(
                request_id=request_id, provider=self._provider_name,
                model=self._model, latency_s=latency,
                raw_status=resp.status_code, error=f"non-JSON body: {resp.text[:500]}",
            )
            raise RuntimeError(
                f"{self._provider_name} returned non-JSON body: {resp.text[:500]}"
            ) from e
        if not isinstance(data, dict) or "choices" not in data:
            err = data.get("error") if isinstance(data, dict) else None
            log_response(
                request_id=request_id, provider=self._provider_name,
                model=self._model, latency_s=latency,
                raw_status=resp.status_code,
                error=f"no choices: {err if err else str(data)[:500]}",
            )
            raise RuntimeError(
                f"{self._provider_name} returned malformed response (no choices): "
                f"{err if err else str(data)[:500]}"
            )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            log_response(
                request_id=request_id, provider=self._provider_name,
                model=self._model, latency_s=latency,
                raw_status=resp.status_code, error=str(data)[:500],
            )
            raise RuntimeError(
                f"{self._provider_name} response missing choices[0].message.content: "
                f"{str(data)[:500]}"
            ) from e
        usage = data.get("usage") if isinstance(data, dict) else None
        log_response(
            request_id=request_id, provider=self._provider_name,
            model=self._model, latency_s=latency,
            raw_status=resp.status_code, content=content, usage=usage,
        )
        return content, usage


def build_agent(
    system_prompt: str,
    output_type: type[T],
    fallback: T | None,
    *,
    provider_override: str | None = None,
    schema_exclude: "tuple[str, ...] | frozenset[str]" = (),
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
    - `schema_exclude` — field names left OUT of the local grammar. The
      pydantic model keeps them (with their defaults); the sampler is just
      never asked to emit them. Lets an optional field such as
      `Answer.evidence` cost nothing when its mode is off.
    """
    cfg = (
        PROVIDERS[provider_override] if provider_override is not None
        else active_provider()
    )
    if cfg.name == "local":
        return LocalAgent(system_prompt, output_type, fallback, schema_exclude=schema_exclude)
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


def _flatten_unknown_payload(payload: dict) -> dict | None:
    """Render a JSON object whose keys match nothing in the schema as prose.

    Only scalars and lists of scalars are flattened; a nested object means we
    cannot tell prose from structure, and guessing there is how a rescue turns
    into a fabrication. `sources_used` is taken from an aliased key when the
    model used one, else left empty — an answer with no citations is honest
    about what it is.
    """
    alias = next(
        (k for k in ("sources", "source_files", "files", "sources_cited")
         if isinstance(payload.get(k), list)),
        None,
    )
    sources = [str(x) for x in payload[alias]] if alias else []

    lines: list[str] = []
    for key, value in payload.items():
        if key == alias:
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"{_humanize_key(key)}: {value}")
        elif isinstance(value, list) and all(
            isinstance(v, (str, int, float, bool)) for v in value
        ):
            joined = ", ".join(str(v) for v in value)
            lines.append(f"{_humanize_key(key)}: {joined}")
        else:
            return None
    if not lines:
        return None
    return _complete_answer_payload(
        {"answer": "\n".join(lines), "sources_used": sources}
    )


def _humanize_key(key: str) -> str:
    """`transaction_date` -> `Transaction date`. The key names the model
    invents are usually the best label for the value it put there."""
    text = str(key).replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else str(key)


def _complete_answer_payload(rescued: dict) -> dict:
    """Fill the verdict fields a rescue cannot know.

    Every field on `Answer` is required, so a rescue that returns only
    `answer` + `sources_used` fails validation and throws away the text it
    just recovered. We reached this code because the model produced content,
    so the verdict is not-found=False.
    """
    rescued.setdefault("not_found", False)
    rescued.setdefault("not_found_topic", "")
    return rescued


def _close_truncated_json(text: str) -> str | None:
    """Close a JSON object that generation cut off mid-flight.

    Under a GBNF grammar the model cannot emit malformed JSON — but it CAN
    run into `max_tokens` halfway through a string, and the result parses no
    better than garbage. Observed on enumeration answers, which are the
    longest ones we ask for. Walking the text and appending the closers the
    stack still owes turns a lost answer into a truncated one.

    Returns None when nothing was open (the text was not truncated) or when
    the text is not object-shaped.
    """
    if not text.startswith("{"):
        return None
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    if not in_string and not stack:
        return None

    out = _escape_control_chars_in_strings(text)
    if escaped:
        out = out[:-1]
    if in_string:
        out += '"'
    for opener in reversed(stack):
        out += "}" if opener == "{" else "]"
    return out


def _escape_control_chars_in_strings(text: str) -> str:
    """Escape raw newlines/tabs that appear inside JSON strings.

    Older grammars (and every un-grammared cloud reply) can put a literal
    newline inside a string, which JSON forbids — so the payload fails to
    parse for a reason that has nothing to do with its content.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string and not escaped and ch in "\n\r\t":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
            continue
        out.append(ch)
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
    return "".join(out)


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
    if not isinstance(payload, dict) or not payload:
        return None
    if "sources_used" not in payload and "answer" in payload:
        # Half-drifted: the prose field landed correctly and only the
        # citation key wandered (`sources`, `files`, ...). Keep the model's
        # own answer text rather than flattening it into labelled lines.
        alias = next(
            (k for k in ("sources", "source_files", "files", "sources_cited")
             if isinstance(payload.get(k), list)),
            None,
        )
        rescued = {
            "answer": str(payload["answer"]),
            "sources_used": [str(x) for x in payload[alias]] if alias else [],
        }
        for passthrough in ("not_found", "not_found_topic"):
            if passthrough in payload:
                rescued[passthrough] = payload[passthrough]
        return _complete_answer_payload(rescued)
    if "sources_used" not in payload:
        # Fully-drifted payload: the model answered in valid JSON but named
        # every key after the question ({"transaction_date": ...,
        # "customer_reference": ...}). Measured on the sem6 baseline arm,
        # this was 25 of 25 local answers — several of them factually
        # correct and thrown away for their key names. Flatten the whole
        # object into prose rather than losing it. Cloud has no grammar to
        # fall back on, so this net matters there permanently.
        return _flatten_unknown_payload(payload)
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
    return _complete_answer_payload(
        {"answer": answer_value, "sources_used": payload["sources_used"]}
    )


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

    # Truncation rescue. Last resort before giving up: if generation ran out
    # of tokens mid-object, close what is still open and try again. A
    # partial answer beats "(model output could not be parsed into Answer)".
    closed = _close_truncated_json(stripped)
    if closed is not None:
        try:
            return schema.model_validate_json(closed)
        except Exception:
            if "answer" in getattr(schema, "model_fields", {}):
                coerced = _coerce_field_name_drift(closed)
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


# Seconds the last answer call spent restoring or building its prompt prefix,
# read by answer.py into its sub-timings.
LAST_KV_SECONDS: dict[str, float] = {"seconds": 0.0}


def _ensure_kv_prefix(llm, msgs: list[dict], system_prompt: str, kv_prefix: str) -> None:
    """Restore (or build and save) the server-side state for the part of
    the user message that repeats across questions. See src/kv_cache.py.
    Only when the flattened message really does start with that text —
    otherwise the saved state would not line up with the prompt."""
    from src.kv_cache import ensure_prefix

    LAST_KV_SECONDS["seconds"] = 0.0
    user_text = msgs[-1].get("content") if msgs else None
    if not isinstance(user_text, str) or not user_text.startswith(kv_prefix):
        print("  kv-cache: prefix does not lead the message; skipped", file=sys.stderr)
        return
    t = time.monotonic()
    status = ensure_prefix(
        llm._base_url(), getattr(llm, "model_id", "local"), system_prompt, kv_prefix
    )
    LAST_KV_SECONDS["seconds"] = time.monotonic() - t
    print(f"  kv-cache: {status} ({LAST_KV_SECONDS['seconds']:.2f}s)", file=sys.stderr)


class LocalAgent(Generic[T]):
    """llama-cpp-python-backed agent. Same .run()/.run_sync() shape as _CloudAgent.

    Uses the singleton `LocalLLM` (one engine, two surfaces — also serves
    the `/generate` endpoint). Structured-output is constrained at
    generation time via llama-server's `response_format={"type":
    "json_schema", ...}` — the schema is compiled to GBNF and the
    sampler enforces it token-by-token, so the model literally cannot
    produce invalid JSON or stray prose around the object. We retain
    `parse_json_with_repair` as a defense-in-depth net (in case the
    grammar compiler is ever defeated by a complex schema or a model
    swap that doesn't honor the parameter), but the repair path
    should be vestigial in practice.
    """

    def __init__(
        self,
        system_prompt: str,
        output_type: type[T],
        fallback: T | None,
        schema_exclude: "tuple[str, ...] | frozenset[str]" = (),
    ) -> None:
        self._system_prompt = system_prompt
        self._output_type = output_type
        self._fallback = fallback
        # Pre-compute the response_format payload once per agent. Pydantic
        # model_json_schema() emits standard JSON Schema; llama-server's
        # `json_schema_to_grammar` handles the common subset (objects,
        # arrays, strings, ints, bools, enums, $defs/$ref). `strict: true`
        # asks for full enforcement; if a future schema gets exotic
        # enough to break the compiler, drop strict and fall back to
        # `json_object` (loose JSON) or skip response_format entirely.
        #
        # We ensure `additionalProperties: false` — OpenAI strict mode
        # requires it (and llama-server's strict json_schema follows the
        # same convention), but pydantic v2 doesn't add it by default.
        # Without it, the model could legally emit extra fields and the
        # grammar wouldn't reject them.
        schema = output_type.model_json_schema()
        for name in schema_exclude:
            (schema.get("properties") or {}).pop(name, None)
            if name in (schema.get("required") or []):
                schema["required"] = [r for r in schema["required"] if r != name]
        if schema.get("type") == "object" and "additionalProperties" not in schema:
            schema["additionalProperties"] = False
        self._response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": output_type.__name__,
                "schema": schema,
                "strict": True,
            },
        }
        # ...and the grammar that actually enforces it. `response_format` is
        # a no-op on llama-server b9049 (accepted, ignored — measured), so
        # the schema is compiled to GBNF here and sent as `grammar`, which
        # the sampler does honor. Unsupported schema shapes fall back to
        # response_format + parse_json_with_repair, which is exactly where
        # this code stood before, so a compiler gap can never be worse than
        # the status quo.
        from src.inference.gbnf import UnsupportedSchema, schema_to_gbnf

        try:
            # LOCAL_GRAMMAR=0 turns the constraint off. Same rationale as
            # LOCAL_MIN_P in profiles.py: an A/B run has to be able to
            # reproduce the old (unconstrained) behavior without a code edit
            # between arms.
            if os.environ.get("LOCAL_GRAMMAR", "1").strip() == "0":
                raise UnsupportedSchema("disabled via LOCAL_GRAMMAR=0")
            self._grammar: str | None = schema_to_gbnf(schema)
        except UnsupportedSchema as e:
            self._grammar = None
            if "LOCAL_GRAMMAR" in str(e):
                pass  # deliberate A/B disable, not a problem to report
            else:
                warnings.warn(
                    f"no GBNF grammar for {output_type.__name__} ({e}); local "
                    "structured output falls back to prompt + JSON repair",
                    stacklevel=2,
                )

    async def run(
        self, message: list, *, thinking: bool = False,
        temperature: float | None = None,
        kv_prefix: str | None = None,
    ) -> T:
        from src.inference import default_vision_profile, get_local_llm
        from src.inference.llm_log import log_request, log_response

        msgs, images = _flatten_message_for_local(
            _prepend_timestamp(message, after_first=bool(kv_prefix))
            if _wants_timestamp(self._output_type)
            else message,
            self._system_prompt
        )
        # Drop images when no vision profile is registered (rather than
        # raising), so users without the mmproj installed still get a
        # text-only summary instead of a hard failure.
        if images and default_vision_profile() is None:
            images = []
        llm = get_local_llm()
        # Put the processed prefix in the server's slot before the request
        # goes out, so the prompt is read from where the prefix ends. Done
        # off the loop — it is one or three small HTTP calls to the server.
        if kv_prefix and not images:
            await asyncio.to_thread(
                _ensure_kv_prefix, llm, msgs, self._system_prompt, kv_prefix
            )
        request_id = log_request(
            provider="local",
            model=getattr(llm, "model_id", "local"),
            messages=msgs,
            system_prompt=self._system_prompt,
            temperature=temperature,
            response_format=self._response_format,
            extra={"images": len(images), "thinking": thinking},
        )
        t_start = time.monotonic()
        try:
            raw = await llm.complete(
                msgs,
                thinking=thinking,
                temperature=temperature,
                max_tokens=LOCAL_MAX_TOKENS,
                images=images or None,
                response_format=self._response_format,
                grammar=self._grammar,
            )
        except Exception as e:
            log_response(
                request_id=request_id, provider="local",
                model=getattr(llm, "model_id", "local"),
                latency_s=time.monotonic() - t_start, error=str(e),
            )
            raise
        log_response(
            request_id=request_id, provider="local",
            model=getattr(llm, "model_id", "local"),
            latency_s=time.monotonic() - t_start, content=raw,
            # llama-server's prompt_n / prompt_ms / predicted_n / predicted_ms
            usage=getattr(llm, "last_timings", None),
        )
        return parse_json_with_repair(raw, self._output_type, self._fallback)

    def run_sync(
        self, message: list, *, thinking: bool = False,
        temperature: float | None = None,
        kv_prefix: str | None = None,
    ) -> T:
        from src.inference import default_vision_profile, get_local_llm
        from src.inference.llm_log import log_request, log_response

        msgs, images = _flatten_message_for_local(
            _prepend_timestamp(message, after_first=bool(kv_prefix))
            if _wants_timestamp(self._output_type)
            else message,
            self._system_prompt
        )
        if images and default_vision_profile() is None:
            images = []
        llm = get_local_llm()
        if kv_prefix and not images:
            _ensure_kv_prefix(llm, msgs, self._system_prompt, kv_prefix)
        request_id = log_request(
            provider="local",
            model=getattr(llm, "model_id", "local"),
            messages=msgs,
            system_prompt=self._system_prompt,
            temperature=temperature,
            response_format=self._response_format,
            extra={"images": len(images), "thinking": thinking},
        )
        t_start = time.monotonic()
        try:
            raw = llm.complete_sync(
                msgs,
                thinking=thinking,
                temperature=temperature,
                max_tokens=LOCAL_MAX_TOKENS,
                images=images or None,
                response_format=self._response_format,
                grammar=self._grammar,
            )
        except Exception as e:
            log_response(
                request_id=request_id, provider="local",
                model=getattr(llm, "model_id", "local"),
                latency_s=time.monotonic() - t_start, error=str(e),
            )
            raise
        log_response(
            request_id=request_id, provider="local",
            model=getattr(llm, "model_id", "local"),
            latency_s=time.monotonic() - t_start, content=raw,
            # llama-server's prompt_n / prompt_ms / predicted_n / predicted_ms
            usage=getattr(llm, "last_timings", None),
        )
        return parse_json_with_repair(raw, self._output_type, self._fallback)
