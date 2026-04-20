"""Hardware detection + model selection for fast-tier indexing.

Fallback chain: CUDA → Apple MPS → CPU. CUDA/MPS pick the full-fat
ColQwen2.5; CPU falls back to ColSmol-500M so a non-GPU user still gets
usable speed (~1-2 pages/sec) instead of 10+ seconds per page.
"""

from __future__ import annotations

from dataclasses import dataclass


COLQWEN_MODEL_ID = "vidore/colqwen2.5-v0.2"
COLSMOL_MODEL_ID = "vidore/colSmol-500M"

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


def detect_device() -> DeviceConfig:
    """Pick the best available backend and matching model."""
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
