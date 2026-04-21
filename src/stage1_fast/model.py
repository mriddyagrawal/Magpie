"""Cached singleton loader for the fast-tier embedding model.

Model instantiation is expensive (6 GB of weights + CUDA init), so we load
once per process and reuse. Importing colpali_engine / transformers is also
slow; deferred until first call so CLI subcommands that don't need the model
(e.g. `ns --reset`) don't pay the cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.stage1_fast.device import DeviceConfig, detect_device

if TYPE_CHECKING:
    from PIL import Image

_cache: tuple[Any, Any, DeviceConfig] | None = None


def _torch_dtype(name: str) -> Any:
    import torch

    return {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }[name]


def _load_model(cfg: DeviceConfig) -> tuple[Any, Any]:
    if cfg.model_family == "colqwen2_5":
        from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor
        model_cls, proc_cls = ColQwen2_5, ColQwen2_5_Processor
    elif cfg.model_family == "colidefics3":
        from colpali_engine.models import ColIdefics3, ColIdefics3Processor
        model_cls, proc_cls = ColIdefics3, ColIdefics3Processor
    else:
        raise ValueError(f"unknown model family: {cfg.model_family}")

    model = model_cls.from_pretrained(
        cfg.model_id,
        torch_dtype=_torch_dtype(cfg.dtype),
        device_map=cfg.device,
    ).eval()

    # colpali_engine's own processor adds `process_images` / `process_queries`
    # that return model-ready batches with the right prefix tokens for
    # late-interaction retrieval. The generic transformers AutoProcessor
    # doesn't — that was my bug in the first pass.
    processor = proc_cls.from_pretrained(cfg.model_id)
    return model, processor


def get_model() -> tuple[Any, Any, DeviceConfig]:
    """Return (model, processor, device_config), loading on first call."""
    global _cache
    if _cache is not None:
        return _cache
    cfg = detect_device()
    model, processor = _load_model(cfg)
    _cache = (model, processor, cfg)
    return _cache


def encode_images(images: list["Image.Image"]) -> Any:
    """Encode a batch of PIL page images into per-page multi-vectors.

    Returns a tensor of shape `(len(images), n_patches, dim)` — float on the
    detected device. Caller moves to CPU and quantizes before Qdrant upsert.
    """
    import torch

    model, processor, cfg = get_model()
    batch = processor.process_images(images).to(cfg.device)
    with torch.no_grad():
        embeddings = model(**batch)
    return embeddings


def encode_queries(queries: list[str]) -> Any:
    """Encode text queries into the same multi-vector space as pages."""
    import torch

    model, processor, cfg = get_model()
    batch = processor.process_queries(queries).to(cfg.device)
    with torch.no_grad():
        embeddings = model(**batch)
    return embeddings
