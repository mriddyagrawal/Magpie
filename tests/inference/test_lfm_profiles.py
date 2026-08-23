"""Unit tests for the LFM2.5 launch profiles + their filename patterns.

No subprocess, no network — these lock the two things that are cheap to
get wrong and expensive to discover: the exact GGUF/mmproj filenames in
Liquid's repos (a typo only surfaces as a 404 after `just install`), and
the fact that adding these profiles did not move any default.
"""

from __future__ import annotations

import pytest

from src.inference.llama_server_pool import (
    LlamaServerPool,
    LlamaServerSpawnError,
    _path_override,
)
from src.inference.model_downloader import _filename_for, _mmproj_filename_for
from src.inference.profiles import (
    all_profiles,
    default_text_profile,
    get_profile,
    short_model_name,
)


LFM_PROFILE_NAMES = [
    "lfm2.5-1.2b-text",
    "lfm2.5-2.6b-text",
    "lfm2.5-vl-1.6b-vision",
    "lfm2.5-vl-3b-vision",
]


# ---------------------------------------------------------------------------
# Filename patterns — verified against the HF repo listings 2026-08-19
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "repo_id, quant, expected",
    [
        (
            "LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
            "Q8_0",
            "LFM2.5-1.2B-Instruct-Q8_0.gguf",
        ),
        # Liquid's quantization-aware-distilled 4-bit build rides the same
        # pattern — it is a quant name, not a separate filename shape.
        (
            "LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
            "QAD-Q4_0",
            "LFM2.5-1.2B-Instruct-QAD-Q4_0.gguf",
        ),
        ("LiquidAI/LFM2.5-2.6B-GGUF", "Q4_K_M", "LFM2.5-2.6B-Q4_K_M.gguf"),
        ("LiquidAI/LFM2.5-VL-1.6B-GGUF", "Q8_0", "LFM2.5-VL-1.6B-Q8_0.gguf"),
        ("LiquidAI/LFM2.5-VL-3B-GGUF", "Q8_0", "LFM2.5-VL-3B-Q8_0.gguf"),
        # Gemma must keep resolving exactly as before.
        (
            "unsloth/gemma-4-E4B-it-GGUF",
            "Q5_K_XL",
            "gemma-4-E4B-it-UD-Q5_K_XL.gguf",
        ),
    ],
)
def test_gguf_filename_patterns(repo_id, quant, expected):
    assert _filename_for(repo_id, quant) == expected


def test_lfm_mmproj_filenames_disagree_on_capitalisation():
    """The 1.6B repo spells its weights `...VL-1.6B-...` and its projector
    `...VL-1.6b-...`; the 3B repo uses `3B` in both. Same publisher, one
    character apart. Getting either wrong is a 404 several GB into a
    download, so both are pinned."""
    assert (
        _mmproj_filename_for("LiquidAI/LFM2.5-VL-1.6B-GGUF", "BF16")
        == "mmproj-LFM2.5-VL-1.6b-BF16.gguf"
    )
    assert (
        _mmproj_filename_for("LiquidAI/LFM2.5-VL-3B-GGUF", "Q8_0")
        == "mmproj-LFM2.5-VL-3B-Q8_0.gguf"
    )


def test_text_only_lfm_repos_have_no_projector():
    """Membership in the GGUF table implies nothing about the mmproj
    table — asking for a projector on a text-only repo must raise, not
    silently build a filename that 404s."""
    with pytest.raises(ValueError, match="unknown mmproj repo"):
        _mmproj_filename_for("LiquidAI/LFM2.5-1.2B-Instruct-GGUF", "BF16")


def test_unknown_repo_still_names_the_wired_ones():
    with pytest.raises(ValueError, match="LiquidAI/LFM2.5-2.6B-GGUF"):
        _filename_for("someone/not-wired-GGUF", "Q8_0")


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", LFM_PROFILE_NAMES)
def test_lfm_profiles_registered(name):
    assert name in all_profiles()


def test_adding_lfm_did_not_move_the_default():
    """Plan #22 step 3: a new profile is opt-in via LLAMA_SERVER_TEXT_MODEL.
    Registering these must not change what a user with no env var gets."""
    assert default_text_profile() == "gemma-4-e4b-vision"


@pytest.mark.parametrize("name", LFM_PROFILE_NAMES)
def test_lfm_profiles_use_liquids_recommended_temperature(name):
    """Liquid's cards call for 0.1, not Gemma's 0.7. A small instruct
    model at 0.7 wanders on structured extraction, which is most of what
    Magpie asks it to do."""
    assert get_profile(name).args.temperature == pytest.approx(0.1)


@pytest.mark.parametrize("name", LFM_PROFILE_NAMES)
def test_lfm_profiles_keep_jinja_on(name):
    """Every model in this class ships its chat template inside the GGUF."""
    assert get_profile(name).args.jinja is True


def test_only_the_vl_profiles_declare_vision():
    for name in ("lfm2.5-vl-1.6b-vision", "lfm2.5-vl-3b-vision"):
        assert get_profile(name).has_vision is True
        assert get_profile(name).args.mmproj_repo_id is not None
    for name in ("lfm2.5-1.2b-text", "lfm2.5-2.6b-text"):
        assert get_profile(name).has_vision is False
        assert get_profile(name).args.mmproj_repo_id is None


@pytest.mark.parametrize(
    "name", ["lfm2.5-vl-1.6b-vision", "lfm2.5-vl-3b-vision"]
)
def test_vl_profiles_load_their_projector_from_their_own_repo(name):
    """Liquid ships weights and projector in one repo, same as Unsloth
    does for Gemma — no second repo to resolve."""
    args = get_profile(name).args
    assert args.mmproj_repo_id == args.repo_id


@pytest.mark.parametrize("name", LFM_PROFILE_NAMES)
def test_lfm_profiles_pass_liquids_sampling_flags(name):
    """The recommended repetition penalty rides in `extra_args` because
    LaunchArgs has no typed field for it. If that ever moves to a real
    field, this test is the reminder to update the profiles too."""
    assert "--repeat-penalty" in get_profile(name).args.extra_args


# ---------------------------------------------------------------------------
# Labelling — an A/B run that mislabels its own report is worse than useless
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "profile_name, expected",
    [
        ("lfm2.5-vl-1.6b-vision", "LFM2.5-VL-1.6B"),
        ("lfm2.5-1.2b-text", "LFM2.5-1.2B-Instruct"),
        ("gemma-4-e4b-vision", "gemma-4-E4B-it"),
    ],
)
def test_short_model_name_drops_owner_and_gguf_suffix(profile_name, expected):
    assert short_model_name(get_profile(profile_name)) == expected


# ---------------------------------------------------------------------------
# Absolute-path weight overrides
# ---------------------------------------------------------------------------

def test_path_override_is_none_when_unset(monkeypatch):
    monkeypatch.delenv("LLAMA_SERVER_MODEL_PATH", raising=False)
    assert _path_override("LLAMA_SERVER_MODEL_PATH") is None


def test_path_override_returns_an_existing_file(tmp_path, monkeypatch):
    gguf = tmp_path / "some-model.gguf"
    gguf.write_bytes(b"not really a gguf")
    monkeypatch.setenv("LLAMA_SERVER_MODEL_PATH", str(gguf))
    assert _path_override("LLAMA_SERVER_MODEL_PATH") == str(gguf)


def test_path_override_rejects_a_missing_file(tmp_path, monkeypatch):
    """A typo here would otherwise surface as llama-server "exited during
    startup" with the real cause buried in its load log."""
    monkeypatch.setenv("LLAMA_SERVER_MODEL_PATH", str(tmp_path / "nope.gguf"))
    with pytest.raises(LlamaServerSpawnError, match="does not point at a file"):
        _path_override("LLAMA_SERVER_MODEL_PATH")


def test_path_override_beats_the_profile_repo(tmp_path, monkeypatch):
    """The whole point: evaluate weights already on disk without paying
    for a second copy in Magpie's HF cache. If this regresses, the pool
    silently downloads several GB instead of using the pinned file."""
    gguf = tmp_path / "LFM2.5-VL-3B-Q8_0.gguf"
    gguf.write_bytes(b"not really a gguf")
    mmproj = tmp_path / "mmproj-LFM2.5-VL-3B-Q8_0.gguf"
    mmproj.write_bytes(b"not really a projector")
    monkeypatch.setenv("LLAMA_SERVER_MODEL_PATH", str(gguf))
    monkeypatch.setenv("LLAMA_SERVER_MMPROJ_PATH", str(mmproj))

    pool = LlamaServerPool()
    argv = pool._build_argv(get_profile("lfm2.5-vl-3b-vision"), 9199)

    assert argv[argv.index("--model") + 1] == str(gguf)
    assert argv[argv.index("--mmproj") + 1] == str(mmproj)
