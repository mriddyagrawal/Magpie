"""Unit tests for the controlled-environment contract (PLAN.md §3)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import envctl  # noqa: E402


def test_env_is_built_from_scratch_not_inherited(monkeypatch):
    """Ambient vars — including the exact ones being swept — must not leak."""
    monkeypatch.setenv("LLM_PROVIDER", "moonshot")
    monkeypatch.setenv("LOCAL_TEMPERATURE", "0.9")
    monkeypatch.setenv("LOCAL_SOLO_MARGIN", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-should-never-appear")
    monkeypatch.setenv("LOCAL_N_CTX", "12345")
    monkeypatch.setenv("RANDOM_AMBIENT_THING", "boo")

    env = envctl.build_env(Path("/tmp/x"), {"provider": "local"}, envctl.Ports.for_slot(0))

    assert env["LLM_PROVIDER"] == "local"
    assert env["LOCAL_TEMPERATURE"] == "0.0"
    assert env["LOCAL_SOLO_MARGIN"] == "2.0"
    assert "OPENROUTER_API_KEY" not in env
    # ALWAYS pinned: an unset var would be filled from repo .env by
    # load_dotenv, so "unset" is not a real option for swept knobs.
    assert env["LOCAL_N_CTX"] == "16384"
    assert "RANDOM_AMBIENT_THING" not in env


def test_cache_contract_present_and_offline():
    env = envctl.build_env(Path("/tmp/x"), {"provider": "local"}, envctl.Ports.for_slot(0))
    cache = str(envctl.SHARED_MODEL_CACHE)
    assert env["HF_HOME"] == cache
    assert env["HF_HUB_CACHE"] == cache + "/hub"
    assert env["TRANSFORMERS_CACHE"] == cache
    assert env["FASTEMBED_CACHE_PATH"] == cache + "/fastembed"
    assert "HF_HUB_OFFLINE" not in env  # online like production; zero-download enforced post-hoc
    assert env["MAGPIE_DATA_DIR"] == "/tmp/x"


def test_ports_offset_away_from_live_app():
    p = envctl.Ports.for_slot(0)
    assert p.qdrant_http != 6433  # live app default
    assert p.llama_base != 9100   # live app default
    env = envctl.build_env(Path("/tmp/x"), {"provider": "local"}, p)
    assert env["QDRANT_CLUSTER_ENDPOINT"].endswith(str(p.qdrant_http))
    assert env["LLAMA_SERVER_BASE_PORT"] == str(p.llama_base)


def test_params_reach_env():
    env = envctl.build_env(
        Path("/tmp/x"),
        {"provider": "local", "solo_margin": 0, "temperature": 0.0, "local_n_ctx": 16384},
        envctl.Ports.for_slot(1),
    )
    assert env["LOCAL_SOLO_MARGIN"] == "0"
    assert env["LOCAL_N_CTX"] == "16384"


def test_snapshot_redacts_secrets_stably():
    env = {"OPENROUTER_API_KEY": "sk-abc", "HF_TOKEN": "hf_x", "PLAIN": "v"}
    snap1 = envctl.snapshot_env(env)
    snap2 = envctl.snapshot_env(env)
    assert snap1["PLAIN"] == "v"
    assert "sk-abc" not in str(snap1) and "hf_x" not in str(snap1)
    assert snap1["OPENROUTER_API_KEY"].startswith("<redacted sha256:")
    assert snap1 == snap2  # stable across calls -> comparable across runs


def test_base_passthrough_minimal():
    env = envctl.build_env(Path("/tmp/x"), {"provider": "local"}, envctl.Ports.for_slot(0))
    allowed_ambient = set(envctl._BASE_PASSTHROUGH)
    constructed = {
        "MAGPIE_DATA_DIR", "HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE",
        "FASTEMBED_CACHE_PATH", "HF_HUB_OFFLINE", "QDRANT_CLUSTER_ENDPOINT",
        "LLAMA_SERVER_BASE_PORT", "LLAMA_SERVER_PATH", "LLM_PROVIDER",
        "MAGPIE_FORCE_PROVIDER", "LOCAL_TEMPERATURE", "LOCAL_SOLO_MARGIN",
        "LOCAL_N_CTX", "LLAMA_SERVER_STARTUP_TIMEOUT_S",
    }
    for key in env:
        assert key in allowed_ambient or key in constructed, f"unexpected env var {key}"


def test_os_environ_untouched_by_build():
    before = dict(os.environ)
    envctl.build_env(Path("/tmp/x"), {"provider": "local"}, envctl.Ports.for_slot(0))
    assert dict(os.environ) == before


def test_build_env_requires_resolved_provider():
    import pytest
    with pytest.raises(ValueError, match="resolved provider"):
        envctl.build_env(Path("/tmp/x"), {}, envctl.Ports.for_slot(0))


def test_resolver_raises_on_unknown_and_unpinned():
    import pytest
    with pytest.raises(ValueError, match="unknown model_config"):
        envctl.resolve_model_config({"model_config": "gpt5-magic"})
    with pytest.raises(ValueError, match="unknown model_config"):
        envctl.resolve_model_config({})
    with pytest.raises(NotImplementedError, match="local_model"):
        envctl.resolve_model_config({"model_config": "gemma26b-local"})
    r = envctl.resolve_model_config({"model_config": "lfm-local"})
    assert r["provider"] == "local" and r["grammar"] is True


def test_unmanaged_dotenv_name_fails_loudly(monkeypatch):
    monkeypatch.setattr(envctl, "dotenv_names", lambda root: {"TOTALLY_NEW_KNOB"})
    import pytest
    with pytest.raises(RuntimeError, match="TOTALLY_NEW_KNOB"):
        envctl.build_env(Path("/tmp/x"), {"provider": "local"}, envctl.Ports.for_slot(0))


def test_current_repo_dotenv_fully_classified():
    """The real .env must contain no unmanaged names (build_env succeeds)."""
    envctl.build_env(Path("/tmp/x"), {"provider": "local"}, envctl.Ports.for_slot(0))


def test_non_secret_strips_secrets():
    out = envctl.non_secret({"A_API_KEY": "x", "PLAIN": "y"})
    assert out == {"PLAIN": "y"}
