"""Visual-tier model selection (`src/stage1_fast/device.py`).

The selection matrix decides a 7.25 GB download versus a 0.93 GB one, and
gets it wrong in a way users cannot see: the wrong pick on a small machine
does not error, it downloads 7 GB and then thrashes. These tests pin the
matrix so that stays deliberate.

Everything is monkeypatched — no torch probe, no network, no model load.
"""

from __future__ import annotations

import sys
import types

import pytest

from src.stage1_fast import device as dev


def _fake_torch(*, cuda: bool, vram_gb: float = 0.0, mps: bool = False):
    """Minimal torch stand-in covering only what _detect_device_uncached calls."""
    t = types.SimpleNamespace()
    t.cuda = types.SimpleNamespace(
        is_available=lambda: cuda,
        mem_get_info=lambda _i: (0, int(vram_gb * 1024**3)),
    )
    t.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: mps)
    )
    return t


@pytest.fixture
def patched(monkeypatch):
    """Install a fake torch and a settable RAM probe."""
    def _apply(*, cuda=False, vram_gb=0.0, mps=False, ram_gb=None):
        monkeypatch.setitem(sys.modules, "torch",
                            _fake_torch(cuda=cuda, vram_gb=vram_gb, mps=mps))
        monkeypatch.setattr(dev, "_total_system_ram_gb", lambda: ram_gb)
        return dev._detect_device_uncached()
    return _apply


# ---------------------------------------------------------------------------
# CUDA — gated on DEDICATED vram
# ---------------------------------------------------------------------------

def test_cuda_with_ample_vram_gets_colqwen(patched):
    cfg = patched(cuda=True, vram_gb=24.0)
    assert cfg.device == "cuda"
    assert cfg.model_id == dev.COLQWEN_MODEL_ID
    assert cfg.model_family == "colqwen2_5"


def test_cuda_below_threshold_falls_back(patched):
    cfg = patched(cuda=True, vram_gb=6.0)
    assert cfg.device == "cuda"
    assert cfg.model_id == dev.COLSMOL_MODEL_ID
    assert cfg.batch_size == 1, "small slot = constrained machine; 2 was too much"


# ---------------------------------------------------------------------------
# MPS — gated on TOTAL system RAM, because unified memory is shared
# ---------------------------------------------------------------------------

def test_mps_with_lots_of_unified_memory_gets_colqwen(patched):
    cfg = patched(mps=True, ram_gb=64.0)
    assert cfg.device == "mps"
    assert cfg.model_id == dev.COLQWEN_MODEL_ID
    assert cfg.dtype == "float16", "MPS bfloat16 support is patchy"


def test_mps_on_a_small_mac_does_not_get_the_7gb_model(patched):
    """The regression this guard exists for.

    Before 2026-08 the MPS branch had no memory check at all, so an 8 GB Air
    downloaded 7.25 GB and then thrashed loading a ~7.5 GB model into memory
    shared with the OS. The CUDA branch had always guarded against exactly
    this; MPS just never got it."""
    cfg = patched(mps=True, ram_gb=8.0)
    assert cfg.device == "mps"
    assert cfg.model_id == dev.COLSMOL_MODEL_ID
    assert cfg.batch_size == 1


def test_mps_16gb_is_still_below_the_bar(patched):
    """16 GB is the interesting case, not 8. ColQwen (~7.5) plus llama-server
    (~3) plus the sidecar torch stack (~2) plus macOS lands around 18 GB, and
    both models ARE resident together whenever the walker indexes images
    while a T3 summarize runs."""
    cfg = patched(mps=True, ram_gb=16.0)
    assert cfg.model_id == dev.COLSMOL_MODEL_ID


def test_mps_unmeasurable_ram_prefers_the_capable_model(patched):
    """If psutil fails we cannot tell. Prefer ColQwen: silently downgrading a
    64 GB Mac is an invisible quality loss, while the reverse is visible and
    recoverable."""
    cfg = patched(mps=True, ram_gb=None)
    assert cfg.model_id == dev.COLQWEN_MODEL_ID


# ---------------------------------------------------------------------------
# CPU + invariants
# ---------------------------------------------------------------------------

def test_cpu_gets_the_small_model(patched):
    cfg = patched()
    assert cfg.device == "cpu"
    assert cfg.model_id == dev.COLSMOL_MODEL_ID
    assert cfg.dtype == "float32"
    assert cfg.batch_size == 1


def test_colmodernvbert_is_no_longer_selectable(patched):
    """ColModernVBERT held the small slot for ~2 commits before the DistilVDR
    reproduction (arXiv 2608.10636) showed it is the WEAKEST sub-1B option
    out-of-domain (42.5 avg vs colSmol-500M's 53.0 on ViDoRe v1-v3), not the
    strongest — its own paper's numbers were v1-only and v1 is saturated.
    Its family stays loadable in model.py for experiments, but nothing
    selects it."""
    for kwargs in ({"cuda": True, "vram_gb": 4.0},
                   {"mps": True, "ram_gb": 8.0},
                   {}):
        assert patched(**kwargs).model_family != "colmodernvbert"


def test_every_selectable_family_can_be_loaded():
    """A family string with no branch in model.py raises at load time — i.e.
    after the download, which is the worst place to find out."""
    from colpali_engine import models as cm

    for family, cls in (("colqwen2_5", "ColQwen2_5"),
                        ("colmodernvbert", "ColModernVBert"),
                        ("colidefics3", "ColIdefics3")):
        assert hasattr(cm, cls), f"{family} -> {cls} missing from colpali_engine"


def test_recorded_sizes_are_the_adapter_plus_its_base():
    """These constants drive what the download UI will promise the user.

    Both models are LoRA adapters whose base is resolved transitively by
    from_pretrained, so `model_id` alone understates the download by ~30x for
    ColQwen. Guard the pairing so the base cannot be dropped."""
    assert dev.COLQWEN_BASE_ID and dev.COLQWEN_BASE_ID != dev.COLQWEN_MODEL_ID
    assert dev.COLSMOL_BASE_ID != dev.COLSMOL_MODEL_ID
    assert dev.COLQWEN_TOTAL_GB > dev.COLSMOL_TOTAL_GB * 5


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------

def test_cache_written_before_the_matrix_changed_is_discarded(tmp_path, monkeypatch):
    """A cache without the current selector_version must be re-detected.

    The cache skips a 10-15s torch probe, but it also freezes the decision
    that was correct when it was written. A small Mac that cached
    'mps -> colqwen2.5' before the unified-memory guard existed would keep
    that pick forever and never receive the fix — the same shape as the stale
    .env bugs: old state silently overriding new logic."""
    p = tmp_path / "device.json"
    p.write_text('{"device":"mps","model_id":"vidore/colqwen2.5-v0.2",'
                 '"model_family":"colqwen2_5","dtype":"float16","batch_size":2}')
    monkeypatch.setattr(dev, "_CACHE_PATH", p)
    assert dev._read_cache() is None


def test_current_cache_round_trips(tmp_path, monkeypatch):
    p = tmp_path / "device.json"
    monkeypatch.setattr(dev, "_CACHE_PATH", p)
    cfg = dev.DeviceConfig(device="cpu", model_id=dev.COLSMOL_MODEL_ID,
                           model_family="colidefics3", dtype="float32",
                           batch_size=1)
    dev._write_cache(cfg)
    assert dev._read_cache() == cfg
