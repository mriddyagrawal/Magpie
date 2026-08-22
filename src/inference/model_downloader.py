"""GGUF model + mmproj downloader — wraps `huggingface_hub.hf_hub_download`.

`ensure_model(repo_id, quant)` returns a `Path` to a local GGUF file,
downloading on first use and reusing the HF cache on subsequent calls.
`ensure_mmproj(repo_id, variant)` does the same for the multi-modal
projector that pairs with a vision-capable GGUF (Gemma 4 E4B + BF16
mmproj is Magpie's default vision stack).

SHA verification is automatic (huggingface_hub re-checks ETag and
filesize against the remote on every call; corrupted/partial files
re-download).

Cache lives under `<APP_DATA_DIR>/cache/hub/` because `src/manifest.py`
sets `HF_HOME` and `HF_HUB_CACHE` at module import time. Magpie writes
nothing outside `APP_DATA_DIR`; this includes model weights.

Filename convention is per-repo. Unsloth's Gemma 4 GGUFs follow:

    gemma-4-E4B-it-UD-{QUANT}.gguf
    mmproj-{VARIANT}.gguf            (paired projector, same repo)

The `UD` prefix is Unsloth's Dynamic-2.0 variant — selectively higher
precision on critical layers, generally on the Pareto frontier vs.
non-UD quants of the same size. We default to it; a future "use raw
gguf for repo X" override would land here as a `pattern=` kwarg.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Importing this triggers the HF_HOME redirect set up in src/manifest.py.
# Models land under APP_DATA_DIR/cache/hub/, NOT in the user's shared
# ~/.cache/huggingface/. Keeps everything Magpie writes under one tree.
from src.manifest import APP_DATA_DIR  # noqa: F401  (side-effect import)


# Per-repo filename conventions. Every GGUF publisher names files
# differently, and there is no metadata endpoint that tells you the
# convention — you read the repo's file list once and record it here.
#
# `gguf` is formatted with `quant=`, `mmproj` with `variant=`. A repo with
# no `mmproj` entry is text-only and `ensure_mmproj` will refuse it.
_REPO_PATTERNS: dict[str, dict[str, str]] = {
    # LFM2.5-VL-3B — the shipped local model. Weights and projector live in
    # the same repo. Verified 2026-08 against the repo file listing:
    #   LFM2.5-VL-3B-{Q4_0,Q4_K_M,Q5_K_M,Q6_K,Q8_0,BF16,F16}.gguf
    #   mmproj-LFM2.5-VL-3B-{Q8_0,F16,BF16}.gguf
    # Note the projector's quant set is NARROWER than the model's — asking
    # for mmproj Q6_K would 404, which is why the two are validated apart.
    "LiquidAI/LFM2.5-VL-3B-GGUF": {
        "gguf": "LFM2.5-VL-3B-{quant}.gguf",
        "mmproj": "mmproj-LFM2.5-VL-3B-{variant}.gguf",
    },
    # Unsloth's Gemma 4 E4B. No longer the default — kept because a user
    # may still have it cached and pointed at via LOCAL_MODEL, and because
    # deleting it would turn a working override into a hard error.
    "unsloth/gemma-4-E4B-it-GGUF": {
        "gguf": "gemma-4-E4B-it-UD-{quant}.gguf",
        "mmproj": "mmproj-{variant}.gguf",
    },
}


def _known_repos() -> str:
    return ", ".join(sorted(_REPO_PATTERNS))


def _filename_for(repo_id: str, quant: str) -> str:
    """Resolve the GGUF filename for a (repo_id, quant) pair."""

    entry = _REPO_PATTERNS.get(repo_id)
    if entry is None:
        raise ValueError(
            f"unknown GGUF repo {repo_id!r}. Known repos: {_known_repos()}. "
            "Add its filename convention to _REPO_PATTERNS in "
            "src/inference/model_downloader.py before pointing LOCAL_MODEL at it "
            "— the convention cannot be derived, it has to be read off the "
            "repo's file listing."
        )
    return entry["gguf"].format(quant=quant)


def _mmproj_filename_for(repo_id: str, variant: str) -> str:
    """Resolve the mmproj (vision projector) filename for a repo."""

    entry = _REPO_PATTERNS.get(repo_id)
    if entry is None:
        raise ValueError(
            f"unknown mmproj repo {repo_id!r}. Known repos: {_known_repos()}. "
            "Add its filename convention to _REPO_PATTERNS in "
            "src/inference/model_downloader.py."
        )
    pattern = entry.get("mmproj")
    if not pattern:
        raise ValueError(
            f"repo {repo_id!r} is text-only — it ships no mmproj projector. "
            "Point the vision profile at a vision-capable repo, or register "
            "only a text profile for this model."
        )
    return pattern.format(variant=variant)


def ensure_model(repo_id: str, quant: str) -> Path:
    """Return the local path to a GGUF, downloading if missing.

    First call on a new (repo_id, quant) triggers a multi-GB download
    with a progress bar to stderr. Subsequent calls hit the cache and
    return immediately. Raises `RuntimeError` if `huggingface_hub` isn't
    installed (it's a pyproject.toml dep, so this is a smoke test).
    """

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is required for local LLM weight downloads "
            "but isn't installed. Run `just sync-environment` to install."
        ) from e

    filename = _filename_for(repo_id, quant)
    print(
        f"  resolving local model: {repo_id} :: {filename} "
        f"(first run downloads ~5-9 GB to {os.environ.get('HF_HUB_CACHE', '<cache>')})",
        file=sys.stderr,
    )
    # `token=None` is fine — for non-gated repos. Unsloth's Gemma 4 GGUFs
    # are non-gated (the gating is on Google's source repo, but
    # Unsloth ships derivative quants under their own license-compliant
    # repo). If LOCAL_MODEL is later pointed at a gated repo, the user's
    # `HF_TOKEN` env var is read automatically by huggingface_hub.
    path = hf_hub_download(repo_id=repo_id, filename=filename)
    return Path(path)


def ensure_mmproj(repo_id: str, variant: str = "BF16") -> Path:
    """Return the local path to a multi-modal projector .gguf, downloading
    if missing.

    The projector pairs with a base GGUF to enable vision. For Gemma 4 E4B
    + the BF16 mmproj this is a one-time ~946 MB download. The progress
    bar streams to stderr — be mindful of slow connections (the
    install-llama-server recipe pre-downloads this so the first inference
    call doesn't hang).
    """

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is required for mmproj downloads "
            "but isn't installed. Run `just sync-environment` to install."
        ) from e

    filename = _mmproj_filename_for(repo_id, variant)
    print(
        f"  resolving mmproj projector: {repo_id} :: {filename} "
        f"(first run downloads ~900 MB to {os.environ.get('HF_HUB_CACHE', '<cache>')})",
        file=sys.stderr,
    )
    path = hf_hub_download(repo_id=repo_id, filename=filename)
    return Path(path)
