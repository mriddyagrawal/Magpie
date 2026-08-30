"""Tests for the CURRENT profiles registry + GGUF filename conventions.

Rewritten 2026-08-30 (test-suite triage): the previous file asserted a
four-profile registry (lfm2.5-{1.2b,2.6b}-text, lfm2.5-vl-{1.6b,3b}-vision)
and helpers (`_path_override`, `short_model_name`, LLAMA_SERVER_MODEL_PATH)
that were all removed when profiles consolidated to the single shipped
`lfm25-vl-vision` profile - 26 of its 29 tests could never pass again.
"""

from __future__ import annotations

import pytest

from src.inference.model_downloader import _filename_for, _mmproj_filename_for
from src.inference.profiles import (
    all_profiles,
    default_text_profile,
    get_profile,
)


def test_shipped_profile_is_registered():
    p = get_profile("lfm25-vl-vision")
    assert p.name == "lfm25-vl-vision"
    assert p.args.repo_id  # resolves (env override or default LFM repo)


def test_default_text_profile_resolves_to_a_registered_profile():
    name = default_text_profile()
    assert name in all_profiles()


def test_all_profiles_returns_a_copy():
    a = all_profiles()
    a["fake"] = None
    assert "fake" not in all_profiles()


def test_unknown_profile_raises_with_known_names():
    with pytest.raises(KeyError, match="lfm25-vl-vision"):
        get_profile("definitely-not-a-profile")


def test_lfm_gguf_filename_convention():
    assert _filename_for("LiquidAI/LFM2.5-VL-3B-GGUF", "Q6_K") \
        == "LFM2.5-VL-3B-Q6_K.gguf"


def test_gemma_gguf_filename_convention():
    assert _filename_for("unsloth/gemma-4-E4B-it-GGUF", "Q4_K_M") \
        == "gemma-4-E4B-it-UD-Q4_K_M.gguf"


def test_mmproj_filename_convention():
    assert _mmproj_filename_for("LiquidAI/LFM2.5-VL-3B-GGUF", "Q8_0") \
        == "mmproj-LFM2.5-VL-3B-Q8_0.gguf"


def test_unknown_repo_error_names_the_wired_repos():
    with pytest.raises(ValueError, match="LiquidAI/LFM2.5-VL-3B-GGUF"):
        _filename_for("nobody/unknown-model-GGUF", "Q4_0")
