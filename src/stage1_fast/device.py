"""Hardware detection + model selection for fast-tier indexing.

Fallback chain: CUDA → Apple MPS → CPU. ColQwen2.5 (7.25 GB) is used only
where there is memory for it — >=8 GB dedicated VRAM on CUDA, or >=24 GB
unified on Apple silicon. Everything else gets ColSmol-500M (0.93 GB) — the strongest sub-1B retriever
in the DistilVDR third-party reproduction (arXiv 2608.10636).

Exactly one model is usable per machine: this picks it, and nothing
downstream offers a choice. Switching would invalidate the whole `fast_tier`
collection, since the two produce incompatible vectors and the query encoder
must match whatever built the index.

The detection itself imports torch and initializes CUDA — together ~10-15s
on first call. The result is cached at `~/.cache/magpie/device.json`
so repeat REPL launches don't pay that cost. Hardware doesn't change
between invocations; if the user moves machines they can `rm` the cache
or set `MAGPIE_REDETECT=1` (legacy `NS_REDETECT` still honored).
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

# ColSmol-500M is the small-slot model. It briefly lost this slot to
# ColModernVBERT (2026-08-20, for about two commits) on the strength of
# ModernVBERT's own Table 3, which put it 0.6 nDCG behind ColPali on ViDoRe
# v1+v2. A third-party reproduction with a single evaluation harness
# (DistilVDR, arXiv 2608.10636) inverted that conclusion: on v1+v2+v3,
# colSmol-500M averages 53.0 — "the strongest reproduced sub-1B baseline",
# the paper's words — while ColModernVBERT averages 42.5, collapsing to 17.5
# on v3 (the 26K-page multilingual industrial benchmark). v1 is saturated;
# self-reported v1-heavy numbers flatter small models that overfit it.
# ColModernVBERT's celebrated latency edge is also CPU-only — on GPU it is
# the SLOWEST sub-1B encoder in the reproduction (61.8ms vs colSmol's 22.6).
#
# Lesson recorded so it is not re-learned: a vendor's own table plus the
# incumbent's absent numbers is not evidence enough to swap a default.
COLSMOL_MODEL_ID = "vidore/colSmol-500M"
COLSMOL_BASE_ID = "vidore/ColSmolVLM-Instruct-500M-base"
COLSMOL_TOTAL_GB = 0.93

_CACHE_PATH = Path.home() / ".cache" / "magpie" / "device.json"
# Pre-rename location (2026-08-30). Read-migrated once, never written again.
_LEGACY_CACHE_PATH = Path.home() / ".cache" / "notspotlight" / "device.json"

# Bumped whenever the selection MATRIX changes, not when hardware does. The
# cache exists to skip a 10-15s torch probe, but it also freezes whatever
# decision was correct at write time — so a machine that cached
# "mps -> colqwen2.5" before the unified-memory guard existed would keep that
# pick forever and never benefit from the fix. A cache older than this
# version is discarded and re-detected.
#
#   1  pre-2026-08: ColQwen/ColSmol, no MPS memory guard
#   2  ColModernVBERT replaces ColSmol; MPS gated on >=24 GB unified
#   3  ColSmol restored (third-party repro: best sub-1B on ViDoRe v1-v3);
#      small-slot batch_size dropped to 1 for constrained machines
_SELECTOR_VERSION = 3

# ColQwen2.5 is ~3.75B params; fp16 weights plus activations land around
# 7-8 GB resident. Below this we use ColSmol-500M instead.
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
    model_family: str     # "colqwen2_5" | "colidefics3" (ColSmol)
    dtype: str            # "bfloat16" | "float16" | "float32"
    batch_size: int       # pages per forward pass


def detect_device(*, use_cache: bool = True) -> DeviceConfig:
    """Pick the best available backend and matching model.

    First call (or when `MAGPIE_REDETECT=1`) imports torch + probes CUDA — adds
    ~10-15s to the calling process. Result is then written to
    `~/.cache/magpie/device.json`; subsequent calls in any process
    return the cached value in <1ms. Pass `use_cache=False` to force a
    fresh detection (e.g. after a hardware change).
    """
    if use_cache and not (
        os.environ.get("MAGPIE_REDETECT") or os.environ.get("NS_REDETECT")
    ):
        cached = _read_cache()
        if cached is not None:
            return cached

    cfg = _detect_device_uncached()
    _write_cache(cfg)
    return cfg


def _read_cache() -> "DeviceConfig | None":
    path = _CACHE_PATH
    if not path.exists():
        if _LEGACY_CACHE_PATH.exists():
            path = _LEGACY_CACHE_PATH  # migrated below on successful read
        else:
            return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("selector_version") != _SELECTOR_VERSION:
            return None  # stale matrix — re-detect rather than honor an old pick
        # Drop any extra fields (e.g. _cached_at) to stay forward-compatible.
        cfg = DeviceConfig(
            device=data["device"],
            model_id=data["model_id"],
            model_family=data["model_family"],
            dtype=data["dtype"],
            batch_size=data["batch_size"],
        )
        if path is _LEGACY_CACHE_PATH:
            _write_cache(cfg)  # one-time migration to the magpie path
        return cfg
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
        # GPU too small for ColQwen; run ColSmol on CUDA instead — still far
        # faster than CPU, just a smaller model. batch_size=1: the small slot
        # exists precisely because the machine is constrained, and the
        # Idefics3 image splitter emits 10+ sub-images per page, so per-page
        # activation cost is much larger than the 500M weight count suggests.
        return DeviceConfig(
            device="cuda",
            model_id=COLSMOL_MODEL_ID,
            model_family="colidefics3",
            dtype="float16",
            batch_size=1,
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
            model_id=COLSMOL_MODEL_ID,
            model_family="colidefics3",
            dtype="float16",
            batch_size=1,
        )

    return DeviceConfig(
        device="cpu",
        model_id=COLSMOL_MODEL_ID,
        model_family="colidefics3",
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
