"""Local inference — llama-cpp-python + GGUF.

See `Plans/Local LLM Plan.md`. Two surfaces share one engine:

  - `LocalLLM` Protocol + `LlamaCppLLM` impl exposes `complete()` /
    `stream()` for raw chat completion. Used by the `POST /generate`
    endpoint and by future agentic loops.
  - `src/llm.py:LocalAgent` is rewritten on top of `LocalLLM` and adds
    JSON-repair + Pydantic parsing for the structured-output call sites
    (T3 summarize, query rewrite, answer synthesis).

Hardware accel is determined at install time — `just install-llama`
rebuilds the wheel with `-DGGML_METAL=on` on Apple Silicon, `-DGGML_CUDA=on`
on Linux+CUDA, plain CPU otherwise. The Python code is identical across
all three; only the underlying C++ binary differs.
"""

from src.inference.local_llm import LlamaCppLLM, LocalLLM, get_local_llm

__all__ = ["LlamaCppLLM", "LocalLLM", "get_local_llm"]
