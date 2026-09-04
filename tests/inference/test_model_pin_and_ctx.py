"""Model revision pinning and the metadata-driven context clamp."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.drift import pins
from src.inference import model_downloader, profiles


# ---- revision pin --------------------------------------------------------------


def test_default_repo_is_pinned() -> None:
    assert pins.model_revision(profiles.DEFAULT_REPO) == "3e0e828198e2abb75a957ad823f5d691c13f0f28"
    assert pins.model_revision("someone/other-repo") is None


def test_ensure_model_passes_the_pinned_revision(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = {}

    def fake_download(**kw):
        seen.update(kw)
        return str(tmp_path / "m.gguf")
    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    model_downloader.ensure_model(profiles.DEFAULT_REPO, profiles.DEFAULT_QUANT)
    assert seen["revision"] == pins.model_revision(profiles.DEFAULT_REPO)
    model_downloader.ensure_mmproj(profiles.DEFAULT_REPO, "Q8_0")
    assert seen["revision"] == pins.model_revision(profiles.DEFAULT_REPO)


def test_explicit_revision_beats_the_pin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = {}
    monkeypatch.setattr("huggingface_hub.hf_hub_download",
                        lambda **kw: seen.update(kw) or str(tmp_path / "m.gguf"))
    model_downloader.ensure_model(profiles.DEFAULT_REPO, profiles.DEFAULT_QUANT, revision="abc123")
    assert seen["revision"] == "abc123"


def test_unpinned_repo_follows_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = {}
    monkeypatch.setattr("huggingface_hub.hf_hub_download",
                        lambda **kw: seen.update(kw) or str(tmp_path / "m.gguf"))
    monkeypatch.setitem(model_downloader._REPO_PATTERNS, "x/unpinned", {"gguf": "u-{quant}.gguf"})
    model_downloader.ensure_model("x/unpinned", "Q4")
    assert seen["revision"] is None


def test_check_pins_flags_a_served_snapshot_that_differs() -> None:
    prov = {"llama_server": {"build": pins.LLAMA_SERVER_BUILD}, "qdrant": {"version": None},
            "models": {"repo": profiles.DEFAULT_REPO, "snapshot": "6f730e9a2c454e8af9adc29db58e638e01e5957f"}}
    out = pins.check_pins(prov)
    assert [m["component"] for m in out] == [f"model {profiles.DEFAULT_REPO}"]
    assert out[0]["installed"] == "6f730e9a2c45"


def test_check_pins_quiet_when_snapshot_matches() -> None:
    prov = {"llama_server": {"build": pins.LLAMA_SERVER_BUILD}, "qdrant": {"version": None},
            "models": {"repo": profiles.DEFAULT_REPO, "snapshot": pins.model_revision(profiles.DEFAULT_REPO)}}
    assert pins.check_pins(prov) == []


# ---- metadata clamp ------------------------------------------------------------


def test_clamp_uses_the_files_declared_context(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    profiles._WARNED_CTX_CLAMP.clear()
    monkeypatch.setattr("src.inference.gguf_meta.declared_context_length", lambda p: 32768)
    assert profiles.clamp_ctx_to_model(65536, "/m.gguf", label="repo") == 32768
    assert "exceeds the served model's declared context (32768" in capsys.readouterr().err
    assert profiles.clamp_ctx_to_model(65536, "/m.gguf") == 32768
    assert capsys.readouterr().err == ""                  # warned once per (file, value)
    assert profiles.clamp_ctx_to_model(16384, "/m.gguf") == 16384


def test_clamp_is_a_no_op_without_a_file_or_header(monkeypatch: pytest.MonkeyPatch) -> None:
    assert profiles.clamp_ctx_to_model(65536, None) == 65536
    monkeypatch.setattr("src.inference.gguf_meta.declared_context_length", lambda p: None)
    assert profiles.clamp_ctx_to_model(65536, "/m.gguf") == 65536


def test_no_hardcoded_model_ceiling_remains() -> None:
    assert not hasattr(profiles, "LFM25_MAX_N_CTX")


def test_effective_ctx_size_clamps_against_the_cached_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_N_CTX", "65536")
    monkeypatch.setattr(profiles, "_cached_gguf_path", lambda args: Path("/cached/m.gguf"))
    monkeypatch.setattr("src.inference.gguf_meta.declared_context_length", lambda p: 32768)
    prof = profiles.get_profile(profiles.default_text_profile())
    # the registered profile captured its ctx_size at import; clamp applies on read
    assert profiles.clamp_ctx_to_model(prof.args.ctx_size, "/cached/m.gguf") <= 32768
    assert profiles.effective_ctx_size() <= 32768
