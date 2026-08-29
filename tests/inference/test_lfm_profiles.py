"""Unit tests for the shipped LFM2.5 launch profile + its filename patterns.

No subprocess, no network — these lock the things that are cheap to get
wrong and expensive to discover: the exact GGUF/mmproj filenames in
Liquid's repos (a typo only surfaces as a 404 after `just install`), the
sampler set the model card asks for, and the absolute-path escape hatch
that lets a machine with the weights already on disk skip a second copy.

History: an earlier draft of this file tested four LFM profiles
(1.2b-text / 2.6b-text / vl-1.6b / vl-3b) against a Gemma default. That
design was deliberately reverted — `profiles.py` now registers ONE
vision profile, on purpose, and says why. The assertions that survived
the revert are the ones below.
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
)


SHIPPED_PROFILE = "lfm25-vl-vision"


# ---------------------------------------------------------------------------
# Filename patterns — verified against the HF repo listings 2026-08-19
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "repo_id, quant, expected",
    [
        ("LiquidAI/LFM2.5-VL-3B-GGUF", "Q8_0", "LFM2.5-VL-3B-Q8_0.gguf"),
        ("LiquidAI/LFM2.5-VL-3B-GGUF", "Q6_K", "LFM2.5-VL-3B-Q6_K.gguf"),
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


def test_vl_3b_mmproj_filename():
    assert (
        _mmproj_filename_for("LiquidAI/LFM2.5-VL-3B-GGUF", "Q8_0")
        == "mmproj-LFM2.5-VL-3B-Q8_0.gguf"
    )


def test_unknown_repo_raises_rather_than_guessing():
    """Building a filename for an unwired repo would 404 several GB into
    a download; failing at resolution time keeps the cause visible."""
    with pytest.raises(ValueError):
        _filename_for("someone/not-wired-GGUF", "Q8_0")


# ---------------------------------------------------------------------------
# Profile registry — one profile, and it is the vision one
# ---------------------------------------------------------------------------

def test_the_shipped_profile_is_registered_and_default():
    assert SHIPPED_PROFILE in all_profiles()
    assert default_text_profile() == SHIPPED_PROFILE


def test_shipped_profile_declares_vision_from_its_own_repo():
    p = get_profile(SHIPPED_PROFILE)
    assert p.has_vision is True
    assert p.args.mmproj_repo_id == p.args.repo_id


def test_shipped_profile_keeps_jinja_on():
    """LFM2.5 ships its chat template inside the GGUF."""
    assert get_profile(SHIPPED_PROFILE).args.jinja is True


# ---------------------------------------------------------------------------
# Sampling — Liquid's card, not Gemma's leftovers
# ---------------------------------------------------------------------------

def test_profile_uses_liquids_recommended_sampler_set():
    """Liquid's card calls for temperature 0.1 / min_p 0.15 /
    repetition_penalty 1.05, not Gemma's 0.7 with llama.cpp's stock
    samplers. A small instruct model at 0.7 wanders on structured
    extraction, which is most of what Magpie asks it to do: the n=3 sweep
    of the 40-question eval scored {15, 11, 11} with ~8 questions flipping
    between runs on identical prompts."""
    args = get_profile(SHIPPED_PROFILE).args
    assert args.temperature == pytest.approx(0.1)
    assert args.min_p == pytest.approx(0.15)
    assert args.repeat_penalty == pytest.approx(1.05)


def test_sampler_set_reaches_the_llama_server_argv(tmp_path, monkeypatch):
    """A profile field nobody passes to the subprocess is decoration."""
    gguf = tmp_path / "LFM2.5-VL-3B-Q8_0.gguf"
    gguf.write_bytes(b"not really a gguf")
    mmproj = tmp_path / "mmproj-LFM2.5-VL-3B-Q8_0.gguf"
    mmproj.write_bytes(b"not really a projector")
    monkeypatch.setenv("LLAMA_SERVER_MODEL_PATH", str(gguf))
    monkeypatch.setenv("LLAMA_SERVER_MMPROJ_PATH", str(mmproj))
    argv = LlamaServerPool()._build_argv(get_profile(SHIPPED_PROFILE), 9199)
    assert argv[argv.index("--min-p") + 1] == "0.15"
    assert argv[argv.index("--repeat-penalty") + 1] == "1.05"
    assert argv[argv.index("--temp") + 1] == "0.1"


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

    argv = LlamaServerPool()._build_argv(get_profile(SHIPPED_PROFILE), 9199)

    assert argv[argv.index("--model") + 1] == str(gguf)
    assert argv[argv.index("--mmproj") + 1] == str(mmproj)


def test_subprocess_pipes_never_raise_on_bad_bytes():
    """llama-server emits progress bars and locale bytes that are not valid
    UTF-8. A decode error in the drain thread kills the thread, the stderr
    pipe fills, and llama-server BLOCKS on write — the server never reaches
    /health and every request hangs. Cost one eval run a 12-minute stall
    before it was found, and it had been raising in every log all session."""
    import inspect

    from src.inference import llama_server_pool

    src = inspect.getsource(llama_server_pool)
    spawn = src[src.index("stdout=subprocess.PIPE"):]
    assert 'errors="replace"' in spawn[:1200], "subprocess pipes must not raise on bad bytes"


def test_stderr_drain_failure_cannot_block_the_subprocess():
    """Draining is a logging convenience. If it dies it must keep emptying
    the pipe rather than let the subprocess deadlock behind a full buffer."""
    import inspect

    from src.inference.llama_server_pool import LlamaServerPool

    body = inspect.getsource(LlamaServerPool._drain_stderr)
    assert "except Exception" in body and "readline" in body


def test_solo_gate_hedges_by_one(monkeypatch):
    """The gate hands over the top TWO files, not one.

    Original design sent one, on the college_data finding that a >=2.0 margin
    meant the top hit was right 93% of the time. sem_4 breaks that premise:
    the gate fired on 18 of 25 questions and was right 56% of the time, vs
    86% on the questions it left alone — and the margin carried no signal
    (16.97 put the wrong file first; 2.21 put the right one first). In every
    failure the correct file sat at rank 2-4, already retrieved and then
    discarded."""
    from src.stage2.search import SearchResult, gate_to_solo

    monkeypatch.setenv("MAGPIE_FORCE_PROVIDER", "local")
    monkeypatch.delenv("LOCAL_SOLO_KEEP", raising=False)
    hits = [SearchResult(summary=f"s{i}", path=f"/f{i}", score=10.0 - 5 * i) for i in range(5)]
    kept = gate_to_solo(hits, question="what is the total?")
    assert len(kept) == 2, "a confident gate should still hedge by one file"
    assert [h.path for h in kept] == ["/f0", "/f1"]


def test_solo_gate_width_is_tunable(monkeypatch):
    from src.stage2.search import SearchResult, gate_to_solo

    monkeypatch.setenv("MAGPIE_FORCE_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_SOLO_KEEP", "1")
    hits = [SearchResult(summary=f"s{i}", path=f"/f{i}", score=10.0 - 5 * i) for i in range(5)]
    assert len(gate_to_solo(hits, question="what is the total?")) == 1
