"""Model launch profiles for the llama-server pool.

Each profile is a recipe for spawning a `llama-server` subprocess with a
specific GGUF + mmproj + flags combo. Adding a new model = adding a new
entry here. Spec: `Specs/llama_server_migration.md`.

One profile is registered: `lfm25-vl-vision` — LFM2.5-VL-3B plus its
mmproj projector. It serves BOTH text and image requests from a single
loaded subprocess; see `default_text_profile()` for why there is no
text-only variant.

Gemma 4 E4B was the previous default and was removed in 2026-08. Its
filename convention is still registered in `model_downloader._REPO_PATTERNS`
so an existing `LOCAL_MODEL=unsloth/gemma-4-E4B-it-GGUF` override keeps
resolving rather than hard-failing.

Profile field meanings track llama-server's CLI flags closely so the
mapping is obvious — each `LaunchArgs` field maps to one llama-server
argument. `extra_args` is the escape hatch for one-off flags.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Defaults — env-var overridable, mirror existing LOCAL_* knobs
# ---------------------------------------------------------------------------

# LFM2.5-VL-3B — the shipped local model (replaced Gemma 4 E4B, 2026-08).
#
# Chosen over Gemma on three counts: ~2.8 GB total download against ~7.6 GB,
# a 128K context window against Gemma's 8K default, and — per Liquid's own
# model card — it "answers directly instead of reasoning," which is the right
# behavior for a search bar. (Do not substitute LFM2.5-2.6B or
# LFM2.5-1.2B-Thinking here; both are reasoning models that always emit
# <think> blocks, which would wreck first-token latency.)
#
# Requires llama.cpp >= b10502-era — see DEFAULT_VERSION in
# src/tools/install_llama_server.py for why an older build silently breaks
# grammar-constrained output for this family.
DEFAULT_REPO = "LiquidAI/LFM2.5-VL-3B-GGUF"

# Q6_K: 2.22 GB, effectively lossless against Q8_0 (2.87 GB) at 3B.
DEFAULT_QUANT = "Q6_K"

# The GGUF declares lfm2.context_length = 128000. We do not open it that far
# by default: KV-cache grows linearly with context, and a 3B model does not
# reason well across 128K anyway (Liquid explicitly does not recommend it for
# long-context work). 16K comfortably fits the answer step's top-k file
# payload while keeping the cache small, and it is what every eval run
# measures (envctl pins it). Pin another value via LOCAL_N_CTX.
DEFAULT_N_CTX = 16384


_WARNED_CTX_CLAMP: set[tuple[str, int]] = set()


def resolve_n_ctx(default: int = DEFAULT_N_CTX) -> int:
    """The REQUESTED context window: LOCAL_N_CTX when set, else `default` -
    the same 16K on every machine.

    Until 2026-09-03 an unset LOCAL_N_CTX sized the window to total RAM
    (8K/16K/32K/49K tiers). That shipped a different system than the evals
    measure (the harness pins 16K) and made answers depend on the buyer's
    RAM. Owner decision: one window everywhere; a larger tier
    (LOCAL_N_CTX_BIG) only after an eval arm at that size shows a win.

    The ceiling is NOT a constant here: llama-server clamps -c to the
    served GGUF's declared context_length, and that value changed between
    two Hugging Face revisions of the same repo in one week. See
    effective_ctx_size(), which reads the header of the file that will
    actually be served. Unparseable values fall back to the default.
    """
    raw = os.environ.get("LOCAL_N_CTX", "").strip()
    try:
        n = int(raw) if raw else default
    except ValueError:
        print(f"  warning: LOCAL_N_CTX={raw!r} is not an integer; using {default}",
              file=sys.stderr)
        n = default
    return max(2048, n)


def clamp_ctx_to_model(requested: int, gguf_path: "Path | str | None", *, label: str = "") -> int:
    """min(requested, the GGUF's declared context_length) - the exact rule
    llama-server applies to -c, applied on OUR side so the answer budget
    (src/answer.py) and the server agree. Warns once per (file, value)."""
    if gguf_path is None:
        return requested
    from src.inference.gguf_meta import declared_context_length

    declared = declared_context_length(gguf_path)
    if declared is None or requested <= declared:
        return requested
    key = (str(gguf_path), requested)
    if key not in _WARNED_CTX_CLAMP:
        _WARNED_CTX_CLAMP.add(key)
        print(f"  warning: LOCAL_N_CTX={requested} exceeds the served model's declared "
              f"context ({declared}{' - ' + label if label else ''}); llama-server would "
              f"clamp it and the answer budget would overshoot the real window - "
              f"using {declared}", file=sys.stderr)
    return declared


def _cached_gguf_path(args: "LaunchArgs") -> "Path | None":
    """Path of the profile's GGUF if it is already in the HF cache (never
    downloads; the pool downloads at spawn)."""
    try:
        from huggingface_hub import try_to_load_from_cache

        from src.inference.model_downloader import _filename_for, _pinned

        hit = try_to_load_from_cache(
            repo_id=args.repo_id, filename=_filename_for(args.repo_id, args.quant),
            revision=_pinned(args.repo_id, args.revision),
        )
        return Path(hit) if isinstance(hit, str) else None
    except Exception:  # noqa: BLE001
        return None


def effective_ctx_size(profile_name: Optional[str] = None) -> int:
    """The context window the server will really run for this profile:
    args.ctx_size clamped to the cached GGUF's declared context_length.
    Used by the answer budget so it never assumes a window the model
    cannot open; the pool applies the same clamp from the resolved path
    at spawn. Before the model is downloaded there is nothing to clamp
    against (and no server either), so the requested size is returned."""
    prof = get_profile(profile_name or default_text_profile())
    return clamp_ctx_to_model(prof.args.ctx_size, _cached_gguf_path(prof.args),
                              label=prof.args.repo_id)


# Sampling defaults come from Liquid's own model card for the LFM2.5
# family: temperature 0.1, min_p 0.15, repetition_penalty 1.05. Magpie ran
# 0.7 with llama.cpp's stock samplers until 2026-08-27, which is a Gemma-era
# leftover — and the answer step is an extraction task, not prose. The
# measured cost was variance: an n=3 sweep of the 40-question set scored
# {15, 11, 11} with ~8 questions flipping correct<->wrong between runs on
# byte-identical prompts (Evaluations/college_data/REPORT.md).
#
# A 2026-08-24 trial of temperature 0.2 was rejected after degenerate
# generations (a lone `{`, a 726s loop). That trial set temperature ALONE:
# no min_p floor and no repetition penalty, which is precisely the
# configuration those two failures describe. The temperature was blamed for
# the sampler set's absence.
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MIN_P = 0.15
DEFAULT_REPEAT_PENALTY = 1.05

# llama-server uses `-ngl` (number of GPU layers). 999 = "offload all,"
# the standard idiom across llama.cpp documentation. Equivalent to
# llama-cpp-python's n_gpu_layers=-1.
DEFAULT_NGL = 999

# Profile-override names already warned about, so a stale .env value logs
# once per process rather than on every spawn.
_WARNED_OVERRIDES: set[str] = set()


def _env_model_repo() -> str:
    """Resolve LOCAL_MODEL, announcing it when it is not the shipped default.

    Pointing LOCAL_MODEL somewhere else is a legitimate escape hatch, so this
    honors it. It does NOT do so silently. The pre-LFM2.5 README told users
    to write `LOCAL_MODEL=unsloth/gemma-4-E4B-it-GGUF` into .env, and
    load_dotenv() restores it every start — so on upgrade that stale line
    quietly pins the whole app to the old 6.66 GB model. Someone would
    "install LFM2.5", watch Gemma download instead, and have no way to tell
    why. Print the divergence so it is visible in the first ten lines of any
    install or spawn.
    """
    repo = os.environ.get("LOCAL_MODEL", "").strip()
    if not repo:
        return DEFAULT_REPO
    if repo != DEFAULT_REPO and repo not in _WARNED_OVERRIDES:
        _WARNED_OVERRIDES.add(repo)
        print(
            f"  note: LOCAL_MODEL={repo!r} overrides the shipped default "
            f"({DEFAULT_REPO!r}). If you did not set this deliberately it is "
            f"probably a stale .env line from before the LFM2.5 migration — "
            f"remove it to use the shipped model.",
            file=sys.stderr,
        )
    return repo


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
    # text-only profiles. Two ways to specify it on a vision profile:
    #   - `mmproj` set to an absolute path → spawn passes it verbatim
    #     (test-friendly: lets a pinned local file override discovery).
    #   - `mmproj_repo_id` set → pool calls
    #     `ensure_mmproj(repo_id, variant)` at spawn time, downloading
    #     once and caching to <APP_DATA_DIR>/cache/hub/.
    # The variant ("BF16" / "F16" / "Q8_0" etc.) selects which projector
    # quant Unsloth's repo ships.
    mmproj: Optional[str] = None
    mmproj_repo_id: Optional[str] = None
    mmproj_variant: str = "BF16"

    # Hugging Face revision (commit sha) for repo_id / mmproj_repo_id. None
    # = the validated pin in src/drift/pins.py (or HF main for repos that
    # have no pin, e.g. a LOCAL_MODEL override).
    revision: Optional[str] = None

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
    # `--min-p` — floor a token's probability at min_p x P(top token).
    # At low temperature this is what keeps the tail from collapsing to a
    # single token and looping; llama.cpp's stock 0.05 is looser than
    # Liquid asks for.
    min_p: float = DEFAULT_MIN_P
    # `--repeat-penalty` — llama.cpp ships 1.0 (off). The 726s generation
    # in the rejected temp-0.2 trial is what "off" looks like.
    repeat_penalty: float = DEFAULT_REPEAT_PENALTY

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

# A text-only variant is deliberately NOT registered.
#
# There is no such thing as attaching a projector to a running llama-server:
# `--mmproj` is a spawn-time argv flag, so "text-only now, vision later"
# is really "kill the process and cold-load a second one". The projector
# also costs nothing while idle — its tensors are not in the forward pass
# when no image is attached, so a text call against a vision-loaded process
# runs at full speed.
#
# That leaves 0.54 GB of resident memory as the entire upside of a
# text-only profile, against a full process restart every time a mixed
# corpus alternates between a PDF and a scanned receipt. The trade was
# arguable at Gemma's 946 MB projector; at LFM2.5's 0.54 GB it isn't, so
# the option is gone rather than merely non-default. One profile, one
# process, one load.


# `lfm25-vl-vision` — the only profile. GGUF plus the Q8_0 projector.
# The projector downloads on first spawn via `ensure_mmproj` in the pool's
# argv builder, or ahead of time via `just install-llama-server`.
#
# mmproj variant is Q8_0, not BF16: LFM2.5-VL ships Q8_0 / F16 / BF16, and
# Q8_0 is 0.54 GB against 0.80 GB for the other two with no measurable
# vision-quality cost at this size. Note the projector's quant set is
# narrower than the model's — LOCAL_MMPROJ_VARIANT=Q6_K would 404.
register(
    ModelProfile(
        name="lfm25-vl-vision",
        description=(
            "LFM2.5-VL-3B + mmproj-Q8_0 projector. Default profile: serves "
            "both text and image requests from one loaded subprocess."
        ),
        has_vision=True,
        args=LaunchArgs(
            repo_id=_env_model_repo(),
            quant=os.environ.get("LOCAL_QUANT", DEFAULT_QUANT),
            mmproj_repo_id=os.environ.get("LOCAL_MMPROJ_REPO", _env_model_repo()),
            mmproj_variant=os.environ.get("LOCAL_MMPROJ_VARIANT", "Q8_0"),
            ngl=DEFAULT_NGL,
            # One window everywhere (16K) unless LOCAL_N_CTX pins another;
            # clamped to the model's trained context. See resolve_n_ctx.
            ctx_size=resolve_n_ctx(),
            temperature=float(os.environ.get("LOCAL_TEMPERATURE", DEFAULT_TEMPERATURE)),
            # Env-readable like LOCAL_TEMPERATURE above, for the same
            # reason: an A/B run has to be able to reproduce the old
            # sampler set without editing code between arms.
            min_p=float(os.environ.get("LOCAL_MIN_P", DEFAULT_MIN_P)),
            repeat_penalty=float(
                os.environ.get("LOCAL_REPEAT_PENALTY", DEFAULT_REPEAT_PENALTY)
            ),
            jinja=True,
        ),
    )
)


# ---------------------------------------------------------------------------
# Default-name resolution
# ---------------------------------------------------------------------------


def default_text_profile() -> str:
    """Profile name used for **all** inference (text and vision) by default.

    Despite the name, this returns the vision-capable profile. Reasoning:
    Gemma 4 (and Qwen2.5-VL, LFM2-VL — same llama.cpp `--mmproj` pattern)
    is one set of weights with an optional image-encoder bolted on. When
    the projector is loaded but the request has no `image_url` blocks,
    the projector tensors sit idle — zero inference cost. The only cost
    is the projector's resident memory (0.54 GB for LFM2.5-VL mmproj-Q8_0).

    Avoiding the LRU swap between a text-only and a text+vision profile is
    worth far more than that memory on a laptop-class machine — a single
    swap is a full cold load, and a mixed walker corpus can swap several
    times. This held for Gemma 4 E4B + b9049 (verified 2026-05-07:
    text-only `complete()` against a vision-loaded subprocess returned
    identical results at full speed) and is a stronger argument for
    LFM2.5-VL, whose projector is a third the size.

    There is no text-only profile to fall back to, by design. `--mmproj`
    is a spawn-time flag, so the projector cannot be attached to or
    detached from a live process — the only way to "save" its 0.54 GB is
    to cold-load a second subprocess on every text<->image transition.
    """
    return _resolve_override("LLAMA_SERVER_TEXT_MODEL", "lfm25-vl-vision")


def _resolve_override(env_var: str, fallback: str) -> str:
    """Return the profile named by `env_var`, or `fallback` if it is unset
    or names a profile that no longer exists.

    An unresolvable override MUST NOT raise. The profile names changed when
    Gemma 4 was replaced by LFM2.5-VL (2026-08), and the previous README
    actively instructed users to put `LLAMA_SERVER_TEXT_MODEL=gemma-4-e4b-vision`
    in their `.env`. `load_dotenv()` puts that stale value back into the
    environment on every start, so treating a dead override as fatal would
    turn a routine upgrade into a hard KeyError on the first local
    inference — for exactly the users who followed the documentation.

    Warn once and carry on with the current default instead.
    """
    name = os.environ.get(env_var, "").strip()
    if not name:
        return fallback
    if name in _PROFILES:
        return name
    if name not in _WARNED_OVERRIDES:
        _WARNED_OVERRIDES.add(name)
        print(
            f"  warning: {env_var}={name!r} names a profile that is not "
            f"registered (known: {sorted(_PROFILES)}). This usually means an "
            f"old value left in .env from before the LFM2.5 migration. "
            f"Falling back to {fallback!r}.",
            file=sys.stderr,
        )
    return fallback


def default_vision_profile() -> Optional[str]:
    """Profile name for vision inference. Defaults to `lfm25-vl-vision`
    when registered; env-overridable via `LLAMA_SERVER_VISION_MODEL`.
    Returns None if neither the override nor the default is in the registry,
    so callers can degrade gracefully to a text-only summary."""
    name = _resolve_override("LLAMA_SERVER_VISION_MODEL", "lfm25-vl-vision")
    return name if name in _PROFILES else None
