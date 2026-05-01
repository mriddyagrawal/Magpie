"""Hardware detection + model selection for fast-tier indexing.

Fallback chain: CUDA → Apple MPS → CPU. CUDA/MPS pick the full-fat
ColQwen2.5; CPU falls back to ColSmol-500M so a non-GPU user still gets
usable speed (~1-2 pages/sec) instead of 10+ seconds per page.

The detection itself imports torch and initializes CUDA — together ~10-15s
on first call. The result is cached at `~/.cache/notspotlight/device.json`
so repeat REPL launches don't pay that cost. Hardware doesn't change
between invocations; if the user moves machines they can `rm` the cache
or set `NS_REDETECT=1`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


COLQWEN_MODEL_ID = "vidore/colqwen2.5-v0.2"
COLSMOL_MODEL_ID = "vidore/colSmol-500M"

_CACHE_PATH = Path.home() / ".cache" / "notspotlight" / "device.json"

# ColQwen2.5 is ~3B params × bf16 ≈ 6 GB weights; +activations puts it at
# ~7-8 GB real VRAM usage. Below this threshold we fall back to ColSmol
# even on CUDA — still far faster than CPU, just a smaller model.
COLQWEN_VRAM_MIN_GB = 8.0


@dataclass(frozen=True)
class DeviceConfig:
    """Hardware-specific indexing config resolved at startup."""

    device: str           # "cuda" | "mps" | "cpu"
    model_id: str         # HuggingFace model repo
    model_family: str     # "colqwen2_5" | "colidefics3" (ColSmol)
    dtype: str            # "bfloat16" | "float16" | "float32"
    batch_size: int       # pages per forward pass


def detect_device(*, use_cache: bool = True) -> DeviceConfig:
    """Pick the best available backend and matching model.

    First call (or when `NS_REDETECT=1`) imports torch + probes CUDA — adds
    ~10-15s to the calling process. Result is then written to
    `~/.cache/notspotlight/device.json`; subsequent calls in any process
    return the cached value in <1ms. Pass `use_cache=False` to force a
    fresh detection (e.g. after a hardware change).
    """
    if use_cache and not os.environ.get("NS_REDETECT"):
        cached = _read_cache()
        if cached is not None:
            return cached

    cfg = _detect_device_uncached()
    _write_cache(cfg)
    return cfg


def _read_cache() -> "DeviceConfig | None":
    if not _CACHE_PATH.exists():
        return None
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        # Drop any extra fields (e.g. _cached_at) to stay forward-compatible.
        return DeviceConfig(
            device=data["device"],
            model_id=data["model_id"],
            model_family=data["model_family"],
            dtype=data["dtype"],
            batch_size=data["batch_size"],
        )
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _write_cache(cfg: DeviceConfig) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(cfg)
        _CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort; ignore filesystem failures.


def _detect_device_uncached() -> DeviceConfig:
    """The actual detection — imports torch and probes hardware."""
    import torch  # deferred: heavy import, keep CLI snappy

    if torch.cuda.is_available():
        free_b, total_b = torch.cuda.mem_get_info(0)
        total_gb = total_b / (1024 ** 3)
        if total_gb >= COLQWEN_VRAM_MIN_GB:
            return DeviceConfig(
                device="cuda",
                model_id=COLQWEN_MODEL_ID,
                model_family="colqwen2_5",
                dtype="bfloat16",
                batch_size=4,
            )
        # GPU too small for ColQwen; run ColSmol on CUDA instead — still
        # ~10× faster than CPU, just a smaller model.
        return DeviceConfig(
            device="cuda",
            model_id=COLSMOL_MODEL_ID,
            model_family="colidefics3",
            dtype="float16",
            batch_size=2,
        )

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return DeviceConfig(
            device="mps",
            model_id=COLQWEN_MODEL_ID,
            model_family="colqwen2_5",
            dtype="float16",  # MPS bfloat16 support is patchy
            batch_size=2,
        )

    return DeviceConfig(
        device="cpu",
        model_id=COLSMOL_MODEL_ID,
        model_family="colidefics3",
        dtype="float32",
        batch_size=1,
    )
