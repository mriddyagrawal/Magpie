"""Local inference — llama-server (HTTP) + GGUF.

See `Specs/llama_server_migration.md` for the full design.

Two surfaces share one engine:

  - `LocalLLM` Protocol + `LlamaServerLLM` impl exposes `complete()` /
    `stream()` for raw chat completion. Used by the `POST /generate`
    endpoint and by future agentic loops.
  - `src/llm.py:LocalAgent` is built on top of `LocalLLM` and adds
    JSON-repair + Pydantic parsing for the structured-output call sites
    (T3 summarize, query rewrite, answer synthesis).

Hardware accel comes from the llama-server binary itself — Metal on
Apple Silicon, CUDA on Linux/Windows-NVIDIA, CPU otherwise. `just
install-llama-server` downloads the right build for the host platform
from llama.cpp's GitHub releases.

Migration history (2026-05): the previous in-process backend
(`LlamaCppLLM` via `llama-cpp-python`) was replaced wholesale. The
HTTP path opens vision (Gemma 4 + mmproj), grammar-constrained
structured output, and a clean bundling story (one binary, no
platform-specific Python wheel).
"""

from src.inference.llama_server_pool import (
    LlamaServerCrashError,
    LlamaServerPool,
    LlamaServerSpawnError,
    get_pool,
)
from src.inference.local_llm import LlamaServerLLM, LocalLLM, get_local_llm
from src.inference.profiles import (
    LaunchArgs,
    ModelProfile,
    all_profiles,
    default_text_profile,
    default_vision_profile,
    get_profile,
    register,
)

__all__ = [
    # Protocol + impl
    "LocalLLM",
    "LlamaServerLLM",
    "get_local_llm",
    # Pool
    "LlamaServerPool",
    "LlamaServerSpawnError",
    "LlamaServerCrashError",
    "get_pool",
    # Profiles
    "LaunchArgs",
    "ModelProfile",
    "all_profiles",
    "default_text_profile",
    "default_vision_profile",
    "get_profile",
    "register",
]
