"""GGUF model downloader — wraps `huggingface_hub.hf_hub_download`.

`ensure_model(repo_id, quant)` returns a `Path` to a local GGUF file,
downloading on first use and reusing the HF cache on subsequent calls.
SHA verification is automatic (huggingface_hub re-checks ETag and
filesize against the remote on every call; corrupted/partial files
re-download).

Cache lives under `<APP_DATA_DIR>/cache/hub/` because `src/manifest.py`
sets `HF_HOME` and `HF_HUB_CACHE` at module import time. Magpie writes
nothing outside `APP_DATA_DIR`; this includes model weights.

Filename convention is per-repo. Unsloth's Gemma 4 GGUFs follow:

    gemma-4-E4B-it-UD-{QUANT}.gguf

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


# Unsloth's GGUF filename pattern for Gemma 4 E4B. Verified 2026-05 on
# https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF.
_UNSLOTH_GEMMA4_E4B_PATTERN = "gemma-4-E4B-it-UD-{quant}.gguf"


def _filename_for(repo_id: str, quant: str) -> str:
    """Resolve the GGUF filename for a (repo_id, quant) pair.

    Today there's exactly one pattern (Unsloth's UD-prefixed Gemma 4 E4B).
    When other repos / families come online, branch here or accept an
    explicit override kwarg. Keeping the dispatch simple until that
    expansion is forced.
    """

    if repo_id == "unsloth/gemma-4-E4B-it-GGUF":
        return _UNSLOTH_GEMMA4_E4B_PATTERN.format(quant=quant)
    raise ValueError(
        f"unknown GGUF repo {repo_id!r}; "
        "the model_downloader has only been wired for unsloth/gemma-4-E4B-it-GGUF. "
        "Add a filename pattern in src/inference/model_downloader.py:_filename_for "
        "before pointing LOCAL_MODEL at a different repo."
    )


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
