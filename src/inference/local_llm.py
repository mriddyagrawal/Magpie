"""LocalLLM — llama-cpp-python wrapper.

Two surfaces, one engine:

  - `complete(messages, ...)` → full-response string (await-able).
  - `stream(messages, ...)` → async iterator of token-string chunks.

Both wrap `llama_cpp.Llama.create_chat_completion`. The synchronous
llama-cpp call is offloaded via `asyncio.to_thread` for `complete`. For
`stream`, an `asyncio.Queue` + a producer thread bridges the sync
generator into an async iterator — `to_thread` alone can't do that.

Construction is lazy through `get_local_llm()` (singleton). The first
call resolves the GGUF path via `model_downloader.ensure_model` (downloads
on cache miss), then loads the model into memory (~10–20s for a 5–7 GB
GGUF on Apple Silicon). All subsequent calls reuse the loaded model —
that's the whole point of the singleton.

Configuration via env vars (also documented in `.env.example`):
  LOCAL_MODEL          HF repo id           default unsloth/gemma-4-E4B-it-GGUF
  LOCAL_QUANT          GGUF quant name      default Q5_K_XL
  LOCAL_N_CTX          context window       default 8192
  LOCAL_N_GPU_LAYERS   layers on GPU        default -1 (all)
  LOCAL_TEMPERATURE    sampling temp        default 0.7
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import Any, AsyncIterator, Optional, Protocol

from src.inference.chat_template import apply_thinking_to_messages
from src.inference.model_downloader import ensure_model


# ---------------------------------------------------------------------------
# Defaults — overridden per-instance via env at construction time
# ---------------------------------------------------------------------------

DEFAULT_REPO = "unsloth/gemma-4-E4B-it-GGUF"
DEFAULT_QUANT = "Q5_K_XL"
DEFAULT_N_CTX = 8192
DEFAULT_N_GPU_LAYERS = -1   # -1 = offload everything (Metal/CUDA), 0 = pure CPU
DEFAULT_TEMPERATURE = 0.7


# ---------------------------------------------------------------------------
# Protocol — the public surface (used by callers + tests via duck typing)
# ---------------------------------------------------------------------------

class LocalLLM(Protocol):
    """Async chat completion over a local LLM. Implementations: LlamaCppLLM."""

    model_id: str  # for logging / chat-template dispatch

    async def complete(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str: ...

    def complete_sync(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
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
# LlamaCppLLM
# ---------------------------------------------------------------------------

class LlamaCppLLM:
    """The default LocalLLM impl. Wraps a single `llama_cpp.Llama` instance.

    Thread-unsafety: `Llama.create_chat_completion` is not safe to call
    concurrently. We serialize calls under `_llm_lock` so two coroutines
    can't trample each other's KV cache. The lock is held only while
    the C++ call runs; queueing latency under load is fine for a desktop
    RAG app — typical concurrency here is "search yields to ingest,"
    not "100 simultaneous queries."
    """

    def __init__(
        self,
        *,
        repo_id: Optional[str] = None,
        quant: Optional[str] = None,
        n_ctx: Optional[int] = None,
        n_gpu_layers: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> None:
        self.repo_id = repo_id or os.environ.get("LOCAL_MODEL", DEFAULT_REPO)
        self.quant = quant or os.environ.get("LOCAL_QUANT", DEFAULT_QUANT)
        self.n_ctx = int(
            n_ctx if n_ctx is not None
            else os.environ.get("LOCAL_N_CTX", DEFAULT_N_CTX)
        )
        self.n_gpu_layers = int(
            n_gpu_layers if n_gpu_layers is not None
            else os.environ.get("LOCAL_N_GPU_LAYERS", DEFAULT_N_GPU_LAYERS)
        )
        self.default_temperature = float(
            temperature if temperature is not None
            else os.environ.get("LOCAL_TEMPERATURE", DEFAULT_TEMPERATURE)
        )
        # `model_id` is the public identifier callers (and the chat-template
        # helper) use to know which model is loaded — repo + quant uniquely
        # identifies a specific GGUF.
        self.model_id = f"{self.repo_id}::{self.quant}"
        self._llm: Any = None  # llama_cpp.Llama; loaded lazily
        self._llm_lock = threading.Lock()  # serialize C++ calls (KV cache)
        self._load_lock = threading.Lock()  # only one thread loads weights

    # ----- loading -----------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load the GGUF on first use. Idempotent + thread-safe."""
        if self._llm is not None:
            return
        with self._load_lock:
            if self._llm is not None:
                return
            try:
                from llama_cpp import Llama  # deferred — slow import
            except ImportError as e:
                raise RuntimeError(
                    "llama-cpp-python is not installed. Run "
                    "`just sync-environment && just install-llama` first."
                ) from e
            gguf_path = ensure_model(self.repo_id, self.quant)
            print(
                f"  loading local LLM: {self.model_id} "
                f"(n_ctx={self.n_ctx}, n_gpu_layers={self.n_gpu_layers})",
                file=sys.stderr,
            )
            self._llm = Llama(
                model_path=str(gguf_path),
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                # Flash-attention dramatically speeds up prompt eval on Metal
                # and CUDA — at 65K context we'd otherwise spend 30-60s just
                # ingesting an 8-file answer prompt. `True` is safe across
                # supported backends; on the rare CPU build that doesn't
                # implement it the kernel falls back transparently.
                flash_attn=True,
                # `verbose=False` silences the wall of llama.cpp init logs
                # on every load. Errors still propagate as exceptions.
                verbose=False,
            )
            print("  local LLM loaded", file=sys.stderr)

    # ----- complete ----------------------------------------------------------

    async def complete(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Run a non-streaming chat completion. Returns the full response text.

        `thinking=True` injects the Gemma 4 `<|think|>` token via
        `apply_thinking_to_messages`. For non-Gemma-4 models, that helper
        is a no-op — the kwarg is preserved across model swaps without
        special-casing in callers.
        """

        prepared = apply_thinking_to_messages(
            messages, thinking=thinking, model_repo_or_path=self.model_id
        )
        return await asyncio.to_thread(
            self._raw_complete, prepared, temperature, max_tokens
        )

    def complete_sync(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Synchronous variant of `complete()`. Same arguments, no event loop.

        Used by `LocalAgent.run_sync` (called from non-async paths like
        `src.stage2.search.rewrite_query`). Avoids the `asyncio.run` /
        nested-loop awkwardness of wrapping `complete()` in a sync caller.
        """

        prepared = apply_thinking_to_messages(
            messages, thinking=thinking, model_repo_or_path=self.model_id
        )
        return self._raw_complete(prepared, temperature, max_tokens)

    def _raw_complete(
        self,
        messages: list[dict],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        self._ensure_loaded()
        with self._llm_lock:
            resp = self._llm.create_chat_completion(
                messages=messages,
                temperature=(
                    temperature if temperature is not None
                    else self.default_temperature
                ),
                max_tokens=max_tokens,  # None = no cap (model decides)
                stream=False,
            )
        # The OpenAI-shaped response: choices[0].message.content
        return resp["choices"][0]["message"]["content"] or ""

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

        The producer runs `create_chat_completion(stream=True)` on a
        background thread and pushes each chunk's text delta into an
        asyncio.Queue. The async iterator drains the queue. Sentinel
        `None` marks end-of-stream; an exception in the producer is
        re-raised to the consumer.
        """

        prepared = apply_thinking_to_messages(
            messages, thinking=thinking, model_repo_or_path=self.model_id
        )
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)

        def producer() -> None:
            try:
                self._ensure_loaded()
                with self._llm_lock:
                    iterator = self._llm.create_chat_completion(
                        messages=prepared,
                        temperature=(
                            temperature if temperature is not None
                            else self.default_temperature
                        ),
                        max_tokens=max_tokens,
                        stream=True,
                    )
                    for chunk in iterator:
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content")
                        if text:
                            asyncio.run_coroutine_threadsafe(
                                queue.put(text), loop
                            ).result()
            except BaseException as e:  # pylint: disable=broad-except
                asyncio.run_coroutine_threadsafe(queue.put(e), loop).result()
                return
            asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

        threading.Thread(target=producer, daemon=True).start()

        async def _gen() -> AsyncIterator[str]:
            while True:
                item = await queue.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item

        return _gen()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_singleton: Optional[LlamaCppLLM] = None
_singleton_lock = threading.Lock()


def get_local_llm() -> LlamaCppLLM:
    """Return the process-wide LocalLLM singleton.

    Idempotent — first call constructs (no weight load yet, that's lazy
    in `_ensure_loaded`); subsequent calls return the same instance.
    Use this anywhere inference happens in-process so we don't end up
    with two copies of the GGUF in RAM.
    """
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = LlamaCppLLM()
        return _singleton
