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
        # ColSmol — the small-slot model.
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
    # didn't.
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


def _cast_batch_floats(batch: Any, target_dtype: Any) -> Any:
    """In-place cast every float tensor in `batch` to `target_dtype`.

    Why this exists: `processor.process_images` (and `process_queries`) return
    pixel-value tensors as float32 regardless of how the model was loaded.
    When the model is loaded with `torch_dtype=bfloat16` / `float16` (the
    default on CUDA / MPS), the forward pass blows up. On CUDA it surfaces as
    a readable Python error::

        RuntimeError: expected mat1 and mat2 to have the same dtype,
                      got: float != c10::Half

    On Apple MPS it is worse — an abort inside Metal that kills the whole
    process, with no Python traceback::

        MPSNDArrayMatrixMultiplication.mm:5813: failed assertion
        `Destination NDArray and Accumulator NDArray cannot have different
        datatype in MPSNDArrayMatrixMultiplication'

    The fix is to align the input dtype with the model's. We only touch
    floating-point tensors — int tensors (`input_ids`, `attention_mask`,
    `pixel_attention_mask`) MUST stay int, otherwise the model breaks
    elsewhere.

    HISTORY: this function was added 2026-04-26 for the CUDA symptom, then
    removed in 40667b5 ("fix: sysfiles regex, indexer, ranking") — apparently
    by accident, since tests/test_stage1_fast_dtype.py was left behind and has
    failed to import ever since. That failing import was the only signal, and
    it sat inside the pre-existing-failures pile until an MPS user hit the
    Metal abort. Restored, and applied to BOTH encode paths this time.
    """
    import torch

    for key, value in list(batch.items()):
        if (
            isinstance(value, torch.Tensor)
            and value.is_floating_point()
            and value.dtype != target_dtype
        ):
            batch[key] = value.to(target_dtype)
    return batch


def encode_images(images: list["Image.Image"]) -> Any:
    """Encode a batch of PIL page images into per-page multi-vectors.

    Returns a tensor of shape `(len(images), n_patches, dim)` — float on the
    detected device. Caller moves to CPU and quantizes before Qdrant upsert.
    """
    import torch

    model, processor, cfg = get_model()
    target_dtype = _torch_dtype(cfg.dtype)
    batch = processor.process_images(images).to(cfg.device)
    batch = _cast_batch_floats(batch, target_dtype)
    with torch.no_grad():
        embeddings = model(**batch)
    return embeddings


def encode_queries(queries: list[str]) -> Any:
    """Encode text queries into the same multi-vector space as pages."""
    import torch

    model, processor, cfg = get_model()
    target_dtype = _torch_dtype(cfg.dtype)
    batch = processor.process_queries(queries).to(cfg.device)
    # Same cast as encode_images. `process_queries` builds a dummy image
    # internally, so this path carries float32 pixel_values too — it would
    # abort identically the first time anyone ran a visual search, which is
    # later and rarer than indexing and so even easier to miss.
    batch = _cast_batch_floats(batch, target_dtype)
    with torch.no_grad():
        embeddings = model(**batch)
    return embeddings
