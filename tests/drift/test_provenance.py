"""Provenance: stable fingerprints, cached hashing, offline-safe probes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.drift import provenance


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(provenance, "DRIFT_DIR", tmp_path)
    monkeypatch.setattr(provenance, "_HASH_CACHE", tmp_path / "hashes.json")
    monkeypatch.setattr(provenance, "_cached", None)
    yield


def _prov(**over) -> dict:
    base = {
        "llama_server": {"build": 10502, "commit": "0adcc3bb5"},
        "qdrant": {"version": "1.17.1"},
        "models": {"repo": "LiquidAI/LFM2.5-VL-3B-GGUF", "quant": "Q6_K",
                   "gguf": {"sha256": "a" * 64, "path": "/x/model.gguf"},
                   "mmproj": {"sha256": "b" * 64, "path": "/x/mmproj.gguf"}},
        "col_model": {"model_id": "vidore/colqwen2.5-v0.2"},
        "deps": {"uv_lock_sha256": "c" * 64},
        "platform": {"system": "Darwin", "machine": "arm64", "gpu_backend": "metal", "release": "25.4.0"},
        "magpie": {"git_sha": "1234567890ab"},
    }
    base.update(over)
    return base


def test_fingerprint_ignores_magpie_git_sha() -> None:
    a = provenance.fingerprint_of(_prov())
    b = provenance.fingerprint_of(_prov(magpie={"git_sha": "different"}))
    assert a == b and len(a) == 16


def test_fingerprint_ignores_qdrant_reachability_and_version() -> None:
    """The startup probe races Tauri's Qdrant spawn: down at startup, up
    when the pool hook fingerprints later. Both must hash identically or
    every install runs the oracles twice and keeps two cache files."""
    base = provenance.fingerprint_of(_prov())
    assert provenance.fingerprint_of(_prov(qdrant={"version": None, "reachable": False})) == base
    assert provenance.fingerprint_of(_prov(qdrant={"version": "1.18.0"})) == base


def test_fingerprint_changes_with_each_runtime_input() -> None:
    base = provenance.fingerprint_of(_prov())
    assert provenance.fingerprint_of(_prov(llama_server={"build": 10600, "commit": "x"})) != base
    models = _prov()["models"]
    models = {**models, "gguf": {"sha256": "d" * 64, "path": "/x/model.gguf"}}
    assert provenance.fingerprint_of(_prov(models=models)) != base
    assert provenance.fingerprint_of(_prov(col_model={"model_id": "vidore/colSmol-500M"})) != base
    assert provenance.fingerprint_of(_prov(deps={"uv_lock_sha256": "e" * 64})) != base


def test_fingerprint_falls_back_to_path_when_unhashed() -> None:
    models = _prov()["models"]
    models = {**models, "gguf": {"sha256": None, "path": "/x/model.gguf"}}
    a = provenance.fingerprint_of(_prov(models=models))
    models2 = {**models, "gguf": {"sha256": None, "path": "/y/other.gguf"}}
    assert provenance.fingerprint_of(_prov(models=models2)) != a


def test_sha256_file_is_cached_by_size_and_mtime(tmp_path: Path) -> None:
    f = tmp_path / "blob.bin"
    f.write_bytes(b"hello world" * 1000)
    first = provenance._sha256_file(f)
    cache = json.loads((tmp_path / "hashes.json").read_text(encoding="utf-8"))
    assert cache[str(f)]["sha256"] == first
    # tamper with the cache: an unchanged file must return the CACHED value
    cache[str(f)]["sha256"] = "cached-sentinel"
    (tmp_path / "hashes.json").write_text(json.dumps(cache), encoding="utf-8")
    assert provenance._sha256_file(f) == "cached-sentinel"
    # a changed file (size differs) must be rehashed
    f.write_bytes(b"changed")
    assert provenance._sha256_file(f) not in ("cached-sentinel", first)


def test_sha256_missing_file_is_none(tmp_path: Path) -> None:
    assert provenance._sha256_file(tmp_path / "nope") is None


def test_summary_shape() -> None:
    p = _prov()
    p["fingerprint"] = provenance.fingerprint_of(p)
    s = provenance.summary(p)
    assert s["llama_server"] == "b10502"
    assert s["model"] == "LiquidAI/LFM2.5-VL-3B-GGUF:Q6_K"
    assert s["gguf_sha256"] == "a" * 12
    assert s["magpie_git_sha"] == "1234567890ab"


def test_runtime_fingerprint_is_offline_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every probe failing must still yield a record with a fingerprint."""
    monkeypatch.setattr(provenance, "_llama_server", lambda: {"build": None, "error": "no binary"})
    monkeypatch.setattr(provenance, "_qdrant", lambda: {"version": None, "reachable": False})
    monkeypatch.setattr(provenance, "_models", lambda hash_models: {"profile": None})
    monkeypatch.setattr(provenance, "_col_model", lambda: {"family": None, "model_id": None})
    prov = provenance.runtime_fingerprint(refresh=True)
    assert len(prov["fingerprint"]) == 16
    assert prov["llama_server"]["build"] is None
    # second call is served from the in-process cache
    assert provenance.runtime_fingerprint() is prov
