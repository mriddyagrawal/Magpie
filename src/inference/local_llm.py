"""LocalLLM — HTTP client for llama-server subprocess(es).

Two surfaces, one engine:

  - `complete(messages, ...)` → full-response string (await-able).
  - `stream(messages, ...)` → async iterator of token-string chunks.

Both make HTTP POST calls against `/v1/chat/completions` on a
llama-server instance managed by `LlamaServerPool`. The pool spawns
the subprocess on demand, health-checks it, and hands back the base
URL — this class is a thin OpenAI-compatible client on top.

Vision (PR 2): when `complete(...)` is called with `images=[...]`, the
client transparently switches to the registered vision profile (default
`lfm25-vl-vision`) for that call only — the pool handles spawn /
LRU eviction. With the shipped single-profile setup the instance is
already vision-bound, so no switch actually occurs. Image bytes are base64-encoded and sent as OpenAI-style
`image_url` content blocks attached to the last user message. With
`MAX_LOADED_MODELS=1`, switching between text and vision profiles
incurs a model-reload cost; raise the cap if both are hot.

Construction is lazy through `get_local_llm()` (singleton). The first
call that triggers `pool.get_url_for(profile)` causes the subprocess
to spawn and the model to load (a few seconds for the 2.2 GB GGUF on Apple
Silicon). All subsequent calls reuse the running instance — that's
the whole point of the pool.

Configuration via env vars (also documented in `.env.example`):
  LOCAL_MODEL                  HF repo id (e.g. LiquidAI/LFM2.5-VL-3B-GGUF)
  LOCAL_QUANT                  GGUF quant name (e.g. Q6_K)
  LOCAL_N_CTX                  context window
  LOCAL_TEMPERATURE            sampling temp
  LLAMA_SERVER_PATH            override binary path
  LLAMA_SERVER_MIN_VERSION     refuse to start older binaries
  LLAMA_SERVER_BASE_PORT       first port to allocate (default 9100)
  LLAMA_SERVER_MAX_LOADED_MODELS  LRU cap; default 1 on local
  LLAMA_SERVER_IDLE_TIMEOUT_S  unload-after-idle in seconds
  LLAMA_SERVER_STARTUP_TIMEOUT_S  health-check timeout
  LLAMA_SERVER_VISION_MODEL    profile name for image-bearing requests

Migration note (2026-05): replaces the previous `LlamaCppLLM`
in-process backend. Same Protocol surface, same call sites, same
chat-template helper — only the underlying engine changed. See
`Specs/llama_server_migration.md`.
"""

from __future__ import annotations

import base64
import json
import threading
from typing import Any, AsyncIterator, Optional, Protocol, Sequence

import httpx

from src.inference.chat_template import apply_thinking_to_messages
from src.inference.llama_server_pool import LlamaServerSpawnError, get_pool
from src.inference.profiles import (
    default_text_profile,
    default_vision_profile,
    get_profile,
)


# Per-call HTTP timeout. Long enough to cover prompt eval + generation
# on slow CPU paths; bounded so a stuck server doesn't hang the sidecar
# forever. Override via `LLAMA_SERVER_REQUEST_TIMEOUT_S` if a user has
# unusually large prompts at low ngl.
_DEFAULT_REQUEST_TIMEOUT_S = 600.0


# ---------------------------------------------------------------------------
# Protocol — the public surface (used by callers + tests via duck typing)
# ---------------------------------------------------------------------------


class LocalLLM(Protocol):
    """Async chat completion over a local LLM. Implementations: LlamaServerLLM.

    Kept as a Protocol (not an ABC) so test fakes don't have to inherit.
    The two surfaces (`complete`/`complete_sync` for full responses,
    `stream` for incremental output) are independent — implementations
    may serialize them under a single connection or fan out per-call.
    """

    model_id: str  # for logging / chat-template dispatch

    async def complete(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        images: Optional[Sequence[bytes]] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> str: ...

    def complete_sync(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        images: Optional[Sequence[bytes]] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> str: ...

    async def stream(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]: ...


# ---------------------------------------------------------------------------
# LlamaServerLLM — HTTP client against the pool
# ---------------------------------------------------------------------------


class LlamaServerLLM:
    """The default `LocalLLM` impl. Routes all calls through the
    subprocess pool to a `llama-server` HTTP endpoint.

    Concurrency: HTTP calls are inherently safe to make concurrently
    against llama-server (its own internal scheduling handles
    serialization). We don't lock here.

    Profile dispatch: each instance is bound to a single profile name
    (default: text profile from env). Swapping profiles per-call is
    a future feature — today, the singleton pattern means there's
    one LlamaServerLLM per process bound to the text profile, and
    PR 2 adds a separate vision-bound instance.
    """

    def __init__(
        self,
        *,
        profile_name: Optional[str] = None,
        request_timeout_s: float = _DEFAULT_REQUEST_TIMEOUT_S,
    ) -> None:
        self.profile_name = profile_name or default_text_profile()
        profile = get_profile(self.profile_name)
        # `model_id` is the public identifier callers (and the chat-template
        # helper) use to know which model is loaded. Same shape as the
        # previous LlamaCppLLM so chat_template.is_gemma4(model_id) still works.
        self.model_id = f"{profile.args.repo_id}::{profile.args.quant}"
        self.default_temperature = profile.args.temperature
        self.request_timeout_s = request_timeout_s

    # ----- pool-resolved URL -------------------------------------------------

    def _base_url(self, profile_name: Optional[str] = None) -> str:
        """Resolve the running llama-server's base URL, spawning it
        on first call. Per-call so LRU eviction across profiles
        respawns transparently. `profile_name` overrides the instance
        default for image-bearing requests that need the vision model."""
        return get_pool().get_url_for(profile_name or self.profile_name)

    def _ensure_loaded(self) -> None:
        """Force the subprocess to spawn + model to load now (without
        making an inference request). Used by the walker's pre-load
        before the tqdm bar starts so the cold-load is visible.

        Same name as the old in-process method so `src/stage1/summarize.py`
        keeps working unchanged."""
        self._base_url()  # side-effect: pool.get_url_for spawns if needed

    def _select_profile(self, images: Optional[Sequence[bytes]]) -> str:
        """Pick the right profile for this request.

        - No images → instance default.
        - Images + instance is already vision-capable → reuse it (avoids
          a model swap when callers explicitly bound to vision).
        - Images + instance is text → switch to the registered vision
          profile. Raises if none is registered (fail loudly so callers
          can fall back, rather than silently dropping image content).
        """
        if not images:
            return self.profile_name
        instance_profile = get_profile(self.profile_name)
        if instance_profile.has_vision:
            return self.profile_name
        vision = default_vision_profile()
        if vision is None:
            raise LlamaServerSpawnError(
                "complete(images=...) was called but no vision profile "
                "is registered. Set LLAMA_SERVER_VISION_MODEL or register "
                "one via src.inference.profiles.register(...)."
            )
        return vision

    # ----- complete ----------------------------------------------------------

    async def complete(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        images: Optional[Sequence[bytes]] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> str:
        """Run a non-streaming chat completion. Returns the response text.

        `thinking=True` injects the Gemma 4 `<|think|>` token via
        `apply_thinking_to_messages`. For non-Gemma-4 models, that
        helper is a no-op — the kwarg is preserved across model swaps
        without special-casing in callers.

        `images=[bytes, ...]` attaches one or more raw image blobs to the
        last user message. Routes to the vision profile transparently;
        the pool's LRU may unload the text model on the first vision
        request when `MAX_LOADED_MODELS=1`.

        `response_format` is forwarded verbatim to llama-server. The
        OpenAI shape `{"type": "json_schema", "json_schema": {"schema":
        ..., "strict": true}}` is the high-value case: llama-server
        compiles the schema to a GBNF grammar and constrains generation
        token-by-token, so the model literally cannot emit invalid
        JSON. Far more reliable than relying on the prompt + post-hoc
        repair. None means "no constraint" (free-form chat).
        """

        profile_name = self._select_profile(images)
        prepared = apply_thinking_to_messages(
            messages, thinking=thinking, model_repo_or_path=self.model_id
        )
        if images:
            prepared = _attach_images_to_last_user(prepared, images)
        body = self._build_request_body(
            prepared, temperature, max_tokens, stream=False, thinking=thinking,
            response_format=response_format,
        )
        url = self._base_url(profile_name) + "/v1/chat/completions"
        async with httpx.AsyncClient(timeout=self.request_timeout_s) as client:
            resp = await self._post_with_pool_recovery(client, url, body, profile_name)
        return self._extract_content(resp.json())

    def complete_sync(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        images: Optional[Sequence[bytes]] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> str:
        """Synchronous variant. Used by `LocalAgent.run_sync` from
        non-async paths (`src.stage2.search.rewrite_query`).

        Avoids the asyncio.run / nested-loop awkwardness of wrapping
        `complete()` in a sync caller. `response_format` semantics
        match `complete()` — see that docstring.
        """

        profile_name = self._select_profile(images)
        prepared = apply_thinking_to_messages(
            messages, thinking=thinking, model_repo_or_path=self.model_id
        )
        if images:
            prepared = _attach_images_to_last_user(prepared, images)
        body = self._build_request_body(
            prepared, temperature, max_tokens, stream=False, thinking=thinking,
            response_format=response_format,
        )
        url = self._base_url(profile_name) + "/v1/chat/completions"
        with httpx.Client(timeout=self.request_timeout_s) as client:
            resp = self._post_with_pool_recovery_sync(client, url, body, profile_name)
        return self._extract_content(resp.json())

    # ----- stream ------------------------------------------------------------

    async def stream(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Yield response chunks as they're generated.

        Uses llama-server's native SSE response on `/v1/chat/completions`
        with `stream=true`. Each `data: { ... }\\n\\n` event carries an
        OpenAI-shaped delta; we extract `choices[0].delta.content` and
        yield. The server's terminal `data: [DONE]\\n\\n` ends the
        iterator cleanly.

        On HTTP error mid-stream we propagate the exception to the
        consumer; the caller's `except` block decides what to surface
        to the user.
        """

        prepared = apply_thinking_to_messages(
            messages, thinking=thinking, model_repo_or_path=self.model_id
        )
        body = self._build_request_body(prepared, temperature, max_tokens, stream=True)
        url = self._base_url() + "/v1/chat/completions"

        async def _gen() -> AsyncIterator[str]:
            try:
                async with httpx.AsyncClient(timeout=self.request_timeout_s) as client:
                    async with client.stream("POST", url, json=body) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            text = _parse_sse_chunk(line)
                            if text == _SSE_DONE:
                                return
                            if text:
                                yield text
            except httpx.ConnectError as e:
                # Subprocess vanished mid-stream — drop registry entry
                # so the next call respawns cleanly.
                get_pool().mark_dead(self.profile_name)
                raise RuntimeError(
                    f"llama-server connection failed mid-stream: {e}"
                ) from e

        return _gen()

    # ----- internals ---------------------------------------------------------

    def _build_request_body(
        self,
        messages: list[dict],
        temperature: Optional[float],
        max_tokens: Optional[int],
        *,
        stream: bool,
        thinking: bool = False,
        response_format: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """OpenAI-compatible chat-completions request body. We omit
        fields with None values so llama-server's defaults stay in
        play (especially `max_tokens`, where None = no client-side cap).

        Gemma 4's embedded chat template auto-enables thinking mode
        when rendered via `--jinja`. With thinking on, the model spends
        most of its token budget in `reasoning_content` and leaves
        `content` mostly empty — exactly the wrong default for our
        structured-output callers. We pass
        `chat_template_kwargs.enable_thinking` to llama-server so the
        template emits the no-thinking variant when our caller passes
        `thinking=False`. Validated empirically against b9049 + Gemma 4
        E4B 2026-05-07 — without this the vision integration test
        regressed (content empty, all 512 tokens went to reasoning).
        """
        body: dict[str, Any] = {
            "messages": messages,
            "stream": stream,
            "temperature": (
                temperature if temperature is not None else self.default_temperature
            ),
            # The template kwarg is harmless on models whose templates
            # don't read it (the Jinja renderer just ignores undefined
            # vars). Always set it so the explicit choice is visible in
            # the request — never rely on the model's default.
            "chat_template_kwargs": {"enable_thinking": bool(thinking)},
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            # llama-server (b3000+ at least) reads `response_format`
            # with type `json_object` (loose) or `json_schema` (strict —
            # compiles the schema to a GBNF grammar and constrains
            # generation token-by-token).
            body["response_format"] = response_format
        return body

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        """Pull the assistant message content out of an OpenAI-shaped
        response. Defensive against null fields (some models emit
        `content: null` when the response is purely a tool call —
        not relevant today, but harmless to handle).

        Fallback: if `content` is empty AND `reasoning_content` is
        present, surface the reasoning. Belt-and-suspenders against
        the Gemma 4 thinking-mode footgun — even if a future build's
        `enable_thinking` kwarg gets renamed and our suppression
        silently breaks, callers see *some* output rather than empty
        strings + degraded JSON-repair fallback paths.
        """
        try:
            msg = payload["choices"][0]["message"]
            content = msg.get("content") or ""
            if content:
                return content
            return msg.get("reasoning_content") or ""
        except (KeyError, IndexError, TypeError):
            return ""

    async def _post_with_pool_recovery(
        self,
        client: httpx.AsyncClient,
        url: str,
        body: dict[str, Any],
        profile_name: Optional[str] = None,
    ) -> httpx.Response:
        """POST that converts llama-server connection failures into a
        pool 'mark dead' so the next call respawns the subprocess.
        `profile_name` defaults to the instance's default — image-bearing
        calls override it so the right vision profile is cleared."""
        target = profile_name or self.profile_name
        try:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError as e:
            get_pool().mark_dead(target)
            raise LlamaServerSpawnError(
                f"llama-server connection failed: {e}. "
                f"The subprocess may have crashed; the pool has cleared "
                f"its registry, so the next request will respawn it."
            ) from e

    def _post_with_pool_recovery_sync(
        self,
        client: httpx.Client,
        url: str,
        body: dict[str, Any],
        profile_name: Optional[str] = None,
    ) -> httpx.Response:
        """Sync mirror of `_post_with_pool_recovery`."""
        target = profile_name or self.profile_name
        try:
            resp = client.post(url, json=body)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError as e:
            get_pool().mark_dead(target)
            raise LlamaServerSpawnError(
                f"llama-server connection failed: {e}. "
                f"The subprocess may have crashed; the pool has cleared "
                f"its registry, so the next request will respawn it."
            ) from e


# ---------------------------------------------------------------------------
# Multi-modal helpers (module-level for unit-test mockability)
# ---------------------------------------------------------------------------


def _detect_image_media_type(data: bytes) -> str:
    """Sniff a small set of common image formats from magic bytes.

    Defaults to `image/png` when nothing matches. The set is intentionally
    minimal — we only need it for the formats Magpie's content extractor
    produces (png from PDF render + png/jpeg/etc. for raw images on disk).
    Adding webp/heic later is a one-liner if a user reports it.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _attach_images_to_last_user(
    messages: list[dict],
    images: Sequence[bytes],
) -> list[dict]:
    """Re-shape the message list to include image content blocks.

    OpenAI / llama-server's chat completions API accepts a content list of
    typed parts on user messages: `{"type": "text", "text": ...}` and
    `{"type": "image_url", "image_url": {"url": "data:<media>;base64,..."}}`.
    We promote the last user message's plain string content into that
    list and append one `image_url` block per image. Earlier messages
    (system, prior user/assistant turns) are left as plain strings.

    Returns a NEW list — does not mutate `messages`.
    """
    if not images:
        return messages

    # Find the index of the last user message — that's where vision input
    # belongs. If there isn't one (a system-only request, very unusual),
    # skip the rewrite and return messages as-is.
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx < 0:
        return messages

    new_messages = list(messages)
    user = dict(new_messages[last_user_idx])
    text = user.get("content", "") or ""
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    for blob in images:
        media = _detect_image_media_type(blob)
        b64 = base64.b64encode(blob).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{media};base64,{b64}"},
            }
        )
    user["content"] = parts
    new_messages[last_user_idx] = user
    return new_messages


# ---------------------------------------------------------------------------
# SSE parsing helpers (module-level for unit-test mockability)
# ---------------------------------------------------------------------------


_SSE_DONE = "<<DONE>>"  # internal sentinel — never appears in real chunks


def _parse_sse_chunk(line: str) -> str:
    """Extract the assistant content delta from one SSE line.

    Returns:
      - empty string for non-data lines (heartbeats, blank separators)
      - `_SSE_DONE` sentinel for the terminal `[DONE]` line
      - the actual delta content otherwise

    llama-server's SSE shape:
        data: {"choices": [{"delta": {"content": "Hello"}, ...}], ...}
        data: [DONE]
    """
    if not line.startswith("data: "):
        return ""
    payload = line[len("data: "):].strip()
    if payload == "[DONE]":
        return _SSE_DONE
    try:
        chunk = json.loads(payload)
        return chunk["choices"][0].get("delta", {}).get("content") or ""
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


_singleton: Optional[LlamaServerLLM] = None
_singleton_lock = threading.Lock()


def get_local_llm() -> LlamaServerLLM:
    """Return the process-wide LocalLLM singleton.

    Idempotent — first call constructs (no subprocess spawn yet, that's
    lazy in `_base_url()`); subsequent calls return the same instance.
    Use this anywhere inference happens so we don't end up with two
    HTTP clients pointing at separate subprocesses.

    Future (PR 2): a separate `get_vision_llm()` will return a second
    LlamaServerLLM bound to the vision profile, sharing the same pool.
    """
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = LlamaServerLLM()
        return _singleton
