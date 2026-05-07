"""Unit tests for the model-profile registry. No subprocess, no network."""

from __future__ import annotations

import pytest

from src.inference.profiles import (
    LaunchArgs,
    ModelProfile,
    all_profiles,
    default_text_profile,
    get_profile,
    register,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_both_text_and_vision_profiles_registered_at_import():
    """Both built-in profiles register when the module loads. The
    text-only profile is kept around as an opt-in memory-saver
    (`LLAMA_SERVER_TEXT_MODEL=gemma-4-e4b-text`); the vision profile
    is the default for everything since 2026-05-07."""
    profiles = all_profiles()
    assert "gemma-4-e4b-text" in profiles
    assert "gemma-4-e4b-vision" in profiles


def test_default_text_profile_is_vision_capable():
    """Default points at the vision profile so the same subprocess serves
    text and image requests with no LRU swap. The mmproj costs ~946 MB
    resident but zero inference cost on text-only calls."""
    profile = get_profile(default_text_profile())
    assert profile.args.repo_id.startswith("unsloth/gemma-4")
    assert profile.args.jinja is True  # Gemma 4 chat template requires it
    assert profile.has_vision is True
    assert profile.args.mmproj_repo_id is not None  # mmproj is loaded


def test_text_only_profile_kept_for_opt_in():
    """Users on tight memory budgets can opt out of the projector by
    setting LLAMA_SERVER_TEXT_MODEL=gemma-4-e4b-text in .env. Verifies
    the text-only profile is still registered and still has no mmproj."""
    profile = get_profile("gemma-4-e4b-text")
    assert profile.args.mmproj is None
    assert profile.args.mmproj_repo_id is None
    assert profile.has_vision is False


def test_unknown_profile_raises_with_helpful_message():
    """Bad profile names should fail loud at startup with the list of
    valid options — not silently fall back."""
    with pytest.raises(KeyError) as exc:
        get_profile("does-not-exist")
    assert "does-not-exist" in str(exc.value)
    assert "Registered profiles" in str(exc.value)
    assert "gemma-4-e4b-text" in str(exc.value)


def test_register_is_idempotent():
    """Re-registering with the same name overwrites — no exception."""
    custom = ModelProfile(
        name="test-profile",
        args=LaunchArgs(repo_id="x/y", quant="Q4_K_M"),
    )
    register(custom)
    again = ModelProfile(
        name="test-profile",
        args=LaunchArgs(repo_id="x/y", quant="Q5_K_M"),
    )
    register(again)
    assert get_profile("test-profile").args.quant == "Q5_K_M"


# ---------------------------------------------------------------------------
# LaunchArgs invariants
# ---------------------------------------------------------------------------

def test_launch_args_defaults_match_text_profile():
    """LaunchArgs defaults should keep the existing LOCAL_* env behavior
    working without any code-path changes for callers."""
    args = LaunchArgs()
    assert args.ngl == 999
    assert args.jinja is True
    assert args.mmproj is None
    assert args.batch_size is None  # server default
    assert args.threads is None
    assert args.extra_args == ()


def test_env_override_propagates_to_default_text_profile(monkeypatch):
    """`LLAMA_SERVER_TEXT_MODEL` env var swaps the default text profile
    name. Critical for letting users set a custom profile via .env
    without code change."""
    monkeypatch.setenv("LLAMA_SERVER_TEXT_MODEL", "test-profile")
    register(ModelProfile(
        name="test-profile",
        args=LaunchArgs(repo_id="x/y", quant="Q4_K_M"),
    ))
    assert default_text_profile() == "test-profile"
    monkeypatch.delenv("LLAMA_SERVER_TEXT_MODEL")
    # Default fallback is the vision-capable profile (post-2026-05-07
    # decision: load mmproj once, idle for text-only).
    assert default_text_profile() == "gemma-4-e4b-vision"
