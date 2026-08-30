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

def test_two_profiles_are_registered_and_vision_is_first():
    """Two profiles ship: the vision-capable default, and `text-only` for
    the eyes-vs-brain reader arms (2026-08-29). The default stays the
    vision profile — `--mmproj` is a spawn-time flag, an idle projector
    costs no inference time, and swapping profiles is a full cold reload —
    so `text-only` is opt-in via LLAMA_SERVER_TEXT_MODEL, never the
    fallback. Order matters: the first registered name is what diagnostics
    list first."""
    profiles = all_profiles()
    assert list(profiles) == ["lfm25-vl-vision", "text-only"]


def test_text_only_profile_has_no_projector():
    """`text-only` must never try to download or pass an mmproj: it is
    pointed at pure-text GGUF repos (Qwen2.5-*-Instruct, LFM2.5-1.2B) whose
    file listings have no projector, and `ensure_mmproj` would raise."""
    profile = get_profile("text-only")
    assert profile.has_vision is False
    assert profile.args.mmproj is None
    assert profile.args.mmproj_repo_id is None
    assert profile.args.jinja is True


def test_default_text_profile_is_vision_capable():
    """Default points at the vision profile so the same subprocess serves
    text and image requests with no LRU swap. The projector costs 0.54 GB
    resident but zero inference cost on text-only calls."""
    profile = get_profile(default_text_profile())
    assert profile.args.repo_id == "LiquidAI/LFM2.5-VL-3B-GGUF"
    assert profile.args.jinja is True  # the LFM2.5 chat template requires it
    assert profile.has_vision is True
    assert profile.args.mmproj_repo_id is not None  # mmproj is loaded


def test_default_quant_and_projector_variant_exist_upstream():
    """Guards the two values that silently 404 if mistyped.

    The projector ships a NARROWER quant set than the model (Q8_0/F16/BF16
    versus the model's seven), so a variant that is valid for the weights
    can still be invalid for the projector. Both names are formatted into
    download URLs, and a typo surfaces only as a 404 at first inference —
    long after the mistake."""
    from src.inference.model_downloader import _filename_for, _mmproj_filename_for

    args = get_profile(default_text_profile()).args
    assert _filename_for(args.repo_id, args.quant) == "LFM2.5-VL-3B-Q6_K.gguf"
    assert (
        _mmproj_filename_for(args.mmproj_repo_id, args.mmproj_variant)
        == "mmproj-LFM2.5-VL-3B-Q8_0.gguf"
    )


def test_legacy_gemma_repo_still_resolves():
    """A user with LOCAL_MODEL pointed at the old Gemma repo should keep
    working rather than hitting a hard 'unknown repo' error. Gemma is no
    longer a registered profile, but its filename convention stays in the
    downloader registry."""
    from src.inference.model_downloader import _filename_for

    assert (
        _filename_for("unsloth/gemma-4-E4B-it-GGUF", "Q5_K_XL")
        == "gemma-4-E4B-it-UD-Q5_K_XL.gguf"
    )


def test_stale_env_override_falls_back_instead_of_crashing(monkeypatch):
    """A profile name that no longer exists must degrade, not raise.

    The pre-LFM2.5 README instructed users to put
    `LLAMA_SERVER_TEXT_MODEL=gemma-4-e4b-vision` in .env, and load_dotenv()
    restores it on every start — so a hard KeyError here would break local
    inference for exactly the people who followed the docs, and would do it
    at first inference rather than at startup."""
    import src.inference.profiles as profiles_mod

    monkeypatch.setattr(profiles_mod, "_WARNED_OVERRIDES", set())
    monkeypatch.setenv("LLAMA_SERVER_TEXT_MODEL", "gemma-4-e4b-vision")

    name = default_text_profile()
    assert name == "lfm25-vl-vision"
    get_profile(name)  # must not raise


def test_unknown_profile_raises_with_helpful_message():
    """Bad profile names should fail loud at startup with the list of
    valid options — not silently fall back."""
    with pytest.raises(KeyError) as exc:
        get_profile("does-not-exist")
    assert "does-not-exist" in str(exc.value)
    assert "Registered profiles" in str(exc.value)
    assert "lfm25-vl-vision" in str(exc.value)


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
    assert default_text_profile() == "lfm25-vl-vision"
