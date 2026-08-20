"""Hardware detection + model selection for fast-tier indexing.

Fallback chain: CUDA → Apple MPS → CPU. ColQwen2.5 (7.25 GB) is used only
where there is memory for it — >=8 GB dedicated VRAM on CUDA, or >=24 GB
unified on Apple silicon. Everything else gets ColModernVBERT (0.97 GB),
which lands within ~0.6 nDCG of ColPali at 12x fewer parameters.

Exactly one model is usable per machine: this picks it, and nothing
downstream offers a choice. Switching would invalidate the whole `fast_tier`
collection, since the two produce incompatible vectors and the query encoder
must match whatever built the index.

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


# Both retrievers are PEFT LoRA adapters, NOT standalone checkpoints. The
# adapter is small; the weight is in a base model that `from_pretrained`
# resolves transitively at load time and that appears nowhere else in this
# codebase. Naming the bases here is what makes the real download size
# knowable — reading `model_id` alone suggests colqwen2.5 is a 0.24 GB
# download when it actually pulls 7.25 GB.
COLQWEN_MODEL_ID = "vidore/colqwen2.5-v0.2"
COLQWEN_BASE_ID = "vidore/colqwen2.5-base"
COLQWEN_TOTAL_GB = 7.25

# ColModernVBERT replaced ColSmol-500M in 2026-08. A 250M-parameter encoder
# purpose-built for document retrieval rather than a chat VLM finetuned into
# the job, which is why it wins on size so decisively. Per arXiv 2510.01149
# Table 3 (ViDoRe nDCG@5, avg of v1+v2): ColModernVBERT 68.6 at 0.25B vs
# ColPali 69.2 at 2.92B — within 0.6 points of a model 12x its size, at 7x
# lower query latency (0.032s vs 0.222s CPU). ColSmol published no ViDoRe
# numbers at all and is strictly dominated on size, speed and quality.
COLMODERNVBERT_MODEL_ID = "ModernVBERT/colmodernvbert"
COLMODERNVBERT_BASE_ID = "ModernVBERT/colmodernvbert-base"
COLMODERNVBERT_TOTAL_GB = 0.97

_CACHE_PATH = Path.home() / ".cache" / "notspotlight" / "device.json"

# Bumped whenever the selection MATRIX changes, not when hardware does. The
# cache exists to skip a 10-15s torch probe, but it also freezes whatever
# decision was correct at write time — so a machine that cached
# "mps -> colqwen2.5" before the unified-memory guard existed would keep that
# pick forever and never benefit from the fix. A cache older than this
# version is discarded and re-detected.
#
#   1  pre-2026-08: ColQwen/ColSmol, no MPS memory guard
#   2  ColModernVBERT replaces ColSmol; MPS gated on >=24 GB unified
_SELECTOR_VERSION = 2

# ColQwen2.5 is ~3.75B params; fp16 weights plus activations land around
# 7-8 GB resident. Below this we use ColModernVBERT instead.
#
# CUDA and MPS need DIFFERENT thresholds because the numbers mean different
# things. CUDA VRAM is dedicated — nothing else competes for it. Apple's
# unified memory is shared with the OS, the browser, and our own
# llama-server, and there is no mps.mem_get_info() to ask. Budget when both
# models are resident (which happens whenever the walker indexes images while
# a T3 summarize runs): ColQwen ~7.5 + llama-server ~3.0 + sidecar torch
# stack ~2.0 + Qdrant ~0.2 + macOS ~5.0 = ~18 GB. A 16 GB Mac swaps; 24 GB is
# the floor, not a conservative guess.
COLQWEN_VRAM_MIN_GB = 8.0
COLQWEN_UNIFIED_MIN_GB = 24.0


@dataclass(frozen=True)
class DeviceConfig:
    """Hardware-specific indexing config resolved at startup."""

    device: str           # "cuda" | "mps" | "cpu"
    model_id: str         # HuggingFace model repo
    model_family: str     # "colqwen2_5" | "colmodernvbert" | "colidefics3" (legacy ColSmol)
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
        if data.get("selector_version") != _SELECTOR_VERSION:
            return None  # stale matrix — re-detect rather than honor an old pick
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
        payload["selector_version"] = _SELECTOR_VERSION
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
        # GPU too small for ColQwen; run ColModernVBERT on CUDA instead —
        # still far faster than CPU, and within ~7 nDCG of ColQwen at 1/6 the
        # download.
        return DeviceConfig(
            device="cuda",
            model_id=COLMODERNVBERT_MODEL_ID,
            model_family="colmodernvbert",
            dtype="float16",
            batch_size=2,
        )

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        # Unified memory, so gate on TOTAL system RAM rather than a GPU-only
        # figure. This branch previously had no memory check at all: every
        # Apple silicon machine got ColQwen unconditionally, so an 8 GB Air
        # would download 7.25 GB and then thrash loading a ~7.5 GB model into
        # memory it shares with the OS. The CUDA branch above was written to
        # prevent exactly that; MPS simply never got the guard.
        total_gb = _total_system_ram_gb()
        if total_gb is None or total_gb >= COLQWEN_UNIFIED_MIN_GB:
            # `None` means we could not measure. Prefer the capable model in
            # that case — misdetecting a 64 GB Mac down to the small model is
            # a silent quality regression, whereas the reverse is visible and
            # recoverable.
            return DeviceConfig(
                device="mps",
                model_id=COLQWEN_MODEL_ID,
                model_family="colqwen2_5",
                dtype="float16",  # MPS bfloat16 support is patchy
                batch_size=2,
            )
        return DeviceConfig(
            device="mps",
            model_id=COLMODERNVBERT_MODEL_ID,
            model_family="colmodernvbert",
            dtype="float16",
            batch_size=2,
        )

    return DeviceConfig(
        device="cpu",
        model_id=COLMODERNVBERT_MODEL_ID,
        model_family="colmodernvbert",
        dtype="float32",
        batch_size=1,
    )


def _total_system_ram_gb() -> "float | None":
    """Total physical RAM in GB, or None if it cannot be determined.

    psutil is already a dependency (the daemon's backpressure probes use it).
    Returns None rather than raising so a probe failure degrades to a
    judgement call at the call site instead of breaking device detection.
    """
    try:
        import psutil

        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:  # noqa: BLE001 — any failure means "unknown"
        return None
