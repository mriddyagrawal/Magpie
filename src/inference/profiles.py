"""Model launch profiles for the llama-server pool.

Each profile is a recipe for spawning a `llama-server` subprocess with a
specific GGUF + mmproj + flags combo. Adding a new model = adding a new
entry here. Spec: `Specs/llama_server_migration.md`.

The profile registry is intentionally small in PR 1:

  - `gemma-4-e4b-text` — text-only Gemma 4 E4B, the path that today's
    `LlamaCppLLM` already serves. PR 1's parity target.

PR 2 adds `gemma-4-e4b-vision` (same GGUF + mmproj-BF16.gguf projector).
PR 3 wires the vision profile into the answer step.

Profile field meanings track llama-server's CLI flags closely so the
mapping is obvious — each `LaunchArgs` field maps to one llama-server
argument. `extra_args` is the escape hatch for one-off flags.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Defaults — env-var overridable, mirror existing LOCAL_* knobs
# ---------------------------------------------------------------------------

DEFAULT_REPO = "unsloth/gemma-4-E4B-it-GGUF"
DEFAULT_QUANT = "Q5_K_XL"
DEFAULT_N_CTX = 8192
DEFAULT_TEMPERATURE = 0.7

# llama-server uses `-ngl` (number of GPU layers). 999 = "offload all,"
# the standard idiom across llama.cpp documentation. Equivalent to
# llama-cpp-python's n_gpu_layers=-1.
DEFAULT_NGL = 999


# ---------------------------------------------------------------------------
# Profile dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LaunchArgs:
    """The set of llama-server flags a profile needs.

    Maps 1:1 to llama-server's CLI args. The pool manager translates
    this dataclass into argv when spawning the subprocess. New flags
    rare enough that we'd add a field here per addition.
    """

    # `--model` — path to the GGUF file. Resolved by the model_downloader
    # at spawn time from `repo_id` + `quant`.
    repo_id: str = DEFAULT_REPO
    quant: str = DEFAULT_QUANT

    # `--mmproj` — path to a multimodal projector .gguf. None for
    # text-only profiles. PR 2 sets this for vision profiles.
    mmproj: Optional[str] = None

    # `-ngl` — layers offloaded to GPU. 999 = all (recommended on
    # Metal/CUDA), 0 = pure CPU.
    ngl: int = DEFAULT_NGL

    # `-c` / `--ctx-size` — context window in tokens.
    ctx_size: int = DEFAULT_N_CTX

    # `-b` / `--batch-size` — physical batch size for prompt processing.
    # llama-server defaults to 2048; some vision models (Gemma 4) need
    # this kept high for the image-token expansion. PR 1 leaves None
    # (server default); PR 2 overrides for vision.
    batch_size: Optional[int] = None
    ubatch_size: Optional[int] = None

    # `-t` / `--threads` — CPU threads. None = server default (auto-detect).
    threads: Optional[int] = None

    # `--jinja` — apply the GGUF's embedded Jinja chat template
    # server-side. We need this on for Gemma 4's chat formatting.
    # Without it, llama-server defaults to a generic template that
    # doesn't match what Gemma expects.
    jinja: bool = True

    # Sampling defaults. The HTTP client overrides these per-call when
    # the caller passes temperature/max_tokens. These set the server's
    # baseline.
    temperature: float = DEFAULT_TEMPERATURE

    # Escape hatch for one-off flags we don't want to canonicalize yet.
    # Items are passed verbatim after the canonical args. Useful for
    # experimentation; promote to a typed field once stable.
    extra_args: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ModelProfile:
    """A named launch recipe. The pool manager looks up profiles by name."""

    name: str
    args: LaunchArgs
    # Human-readable description for diagnostics + future settings UI.
    description: str = ""
    # True when the profile requires an mmproj projector (vision-capable).
    # Used by retrieval / answer paths to decide whether to forward
    # image content blocks.
    has_vision: bool = False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROFILES: dict[str, ModelProfile] = {}


def register(profile: ModelProfile) -> None:
    """Add a profile to the registry. Idempotent."""
    _PROFILES[profile.name] = profile


def get_profile(name: str) -> ModelProfile:
    """Return the registered profile, or raise KeyError with a list of
    valid names so the message is useful at startup."""
    if name not in _PROFILES:
        raise KeyError(
            f"unknown model profile {name!r}. "
            f"Registered profiles: {sorted(_PROFILES)}"
        )
    return _PROFILES[name]


def all_profiles() -> dict[str, ModelProfile]:
    """For the diagnostics endpoint and tests."""
    return dict(_PROFILES)


# ---------------------------------------------------------------------------
# Built-in profiles (PR 1 scope)
# ---------------------------------------------------------------------------

# `gemma-4-e4b-text` — the parity target for PR 1. Same GGUF the
# existing `LlamaCppLLM` loads. Reads model + quant + ctx + temperature
# from env so users keep their current `.env` knobs working.
register(
    ModelProfile(
        name="gemma-4-e4b-text",
        description=(
            "Gemma 4 E4B (text-only). Parity target for the "
            "llama-cpp-python → llama-server migration. Matches what "
            "Magpie shipped 2026-05 via LlamaCppLLM."
        ),
        has_vision=False,
        args=LaunchArgs(
            repo_id=os.environ.get("LOCAL_MODEL", DEFAULT_REPO),
            quant=os.environ.get("LOCAL_QUANT", DEFAULT_QUANT),
            mmproj=None,
            ngl=DEFAULT_NGL,
            ctx_size=int(os.environ.get("LOCAL_N_CTX", DEFAULT_N_CTX)),
            temperature=float(os.environ.get("LOCAL_TEMPERATURE", DEFAULT_TEMPERATURE)),
            jinja=True,
        ),
    )
)


# ---------------------------------------------------------------------------
# Default-name resolution
# ---------------------------------------------------------------------------


def default_text_profile() -> str:
    """Profile name for text-only inference. Env-overridable so future
    profiles (LFM2.5, Qwen text-only, etc.) can be made the default
    without code change."""
    return os.environ.get("LLAMA_SERVER_TEXT_MODEL", "gemma-4-e4b-text")


def default_vision_profile() -> Optional[str]:
    """Profile name for vision inference. PR 1 has no vision profile;
    returns None when none is registered yet. PR 2 changes the default
    to `gemma-4-e4b-vision`."""
    name = os.environ.get("LLAMA_SERVER_VISION_MODEL", "")
    if name and name in _PROFILES:
        return name
    return None
