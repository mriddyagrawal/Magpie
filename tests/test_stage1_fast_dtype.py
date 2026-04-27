"""Tests for the float-tensor dtype cast in src/stage1_fast/model.py.

The bug: processor.process_images returns pixel_values as float32 regardless
of how the model was loaded. When the model is on GPU/MPS with bfloat16 or
float16 weights, the matmul blows up:
    RuntimeError: expected mat1 and mat2 to have the same dtype,
                  got: float != c10::Half

The fix (`_cast_batch_floats`): cast every float-typed tensor in the batch
to the target dtype before the forward pass. Int tensors are untouched.

Real-world trigger 2026-04-26: ~10 PNGs in /home/astavak/Downloads (all
post-removebg / app screenshots) crashed T4 with this error. The dot-folder
prune from earlier today caught the .antigravity case but didn't help these.
"""

from __future__ import annotations

import torch

from src.stage1_fast.model import _cast_batch_floats


def test_cast_floats_to_half_leaves_ints_alone():
    batch = {
        "pixel_values": torch.randn(1, 3, 224, 224, dtype=torch.float32),
        "input_ids": torch.tensor([[1, 2, 3]], dtype=torch.long),
        "attention_mask": torch.tensor([[1, 1, 1]], dtype=torch.long),
    }
    out = _cast_batch_floats(batch, torch.float16)
    assert out["pixel_values"].dtype == torch.float16
    assert out["input_ids"].dtype == torch.long       # untouched
    assert out["attention_mask"].dtype == torch.long  # untouched


def test_cast_floats_to_bfloat16_handles_mixed_dtypes():
    batch = {
        "pixel_values": torch.randn(2, 3, 64, 64, dtype=torch.float32),
        "pixel_mask": torch.randn(2, 64, 64, dtype=torch.float64),  # also float
        "labels": torch.tensor([0, 1], dtype=torch.int32),           # int — keep
    }
    _cast_batch_floats(batch, torch.bfloat16)
    assert batch["pixel_values"].dtype == torch.bfloat16
    assert batch["pixel_mask"].dtype == torch.bfloat16
    assert batch["labels"].dtype == torch.int32


def test_cast_noop_when_already_target():
    """No-op if tensor's already at target dtype — avoids spurious copies."""
    t = torch.randn(2, 2, dtype=torch.bfloat16)
    batch = {"pixel_values": t}
    _cast_batch_floats(batch, torch.bfloat16)
    # Same tensor (not a copy)
    assert batch["pixel_values"] is t


def test_cast_handles_non_tensor_values():
    """Real processor outputs sometimes include non-tensor metadata."""
    batch = {
        "pixel_values": torch.randn(1, 3, 8, 8, dtype=torch.float32),
        "image_sizes": [(8, 8)],   # plain Python list, not a tensor
        "extra_meta": None,
    }
    _cast_batch_floats(batch, torch.float16)
    assert batch["pixel_values"].dtype == torch.float16
    assert batch["image_sizes"] == [(8, 8)]
    assert batch["extra_meta"] is None


def test_cast_to_float32_is_supported():
    """CPU path uses float32 — cast must work even when 'casting' to float32."""
    batch = {
        "pixel_values": torch.randn(1, 3, 4, 4, dtype=torch.float16),
    }
    _cast_batch_floats(batch, torch.float32)
    assert batch["pixel_values"].dtype == torch.float32
