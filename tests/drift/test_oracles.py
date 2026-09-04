"""Oracles: each verdict derived from a faked upstream response; cache
round-trip; idle scheduling never runs against a busy server."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

from src.drift import oracles


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(oracles, "DRIFT_DIR", tmp_path)
    oracles._scheduled.clear()
    yield
    oracles._scheduled.clear()


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_server(monkeypatch: pytest.MonkeyPatch, handler):
    """Route urlopen through `handler(body_dict) -> response_dict`."""
    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data)
        return _FakeResp(json.dumps(handler(body)).encode())
    monkeypatch.setattr(oracles.urllib.request, "urlopen", fake_urlopen)


# ---- synthetic png ---------------------------------------------------------


def test_synthetic_png_has_declared_dimensions() -> None:
    from src.answer import _image_dimensions

    assert _image_dimensions(oracles.synthetic_png(1024, 768)) == (1024, 768)


# ---- image_tokens ----------------------------------------------------------


def _tokens_handler(measured_by_size: dict[tuple[int, int], int], base: int = 11):
    from src.answer import _image_dimensions
    import base64

    def handler(body):
        content = body["messages"][0]["content"]
        n = base
        for part in content:
            if part.get("type") == "image_url":
                b64 = part["image_url"]["url"].split(",", 1)[1]
                dims = _image_dimensions(base64.b64decode(b64))
                n += measured_by_size[dims]
        return {"usage": {"prompt_tokens": n}}
    return handler


def test_image_oracle_passes_when_estimates_cover_measurements(monkeypatch) -> None:
    from src.answer import estimate_image_tokens

    measured = {s: estimate_image_tokens(*s) - 5 for s in oracles.IMAGE_ORACLE_SIZES}
    _fake_server(monkeypatch, _tokens_handler(measured))
    r = oracles.oracle_image_tokens("http://fake")
    assert r.ok and r.name == "image_tokens"
    assert len(r.data["rows"]) == len(oracles.IMAGE_ORACLE_SIZES)


def test_image_oracle_fails_on_any_underestimate(monkeypatch) -> None:
    from src.answer import estimate_image_tokens

    measured = {s: estimate_image_tokens(*s) - 5 for s in oracles.IMAGE_ORACLE_SIZES}
    bad = oracles.IMAGE_ORACLE_SIZES[1]
    measured[bad] = estimate_image_tokens(*bad) + 300   # upstream now costs more
    _fake_server(monkeypatch, _tokens_handler(measured))
    r = oracles.oracle_image_tokens("http://fake")
    assert not r.ok
    assert f"{bad[0]}x{bad[1]}" in r.detail and "UNDER" in r.detail


def test_image_oracle_probe_failure_is_a_failed_verdict(monkeypatch) -> None:
    def boom(req, timeout=0):
        raise OSError("connection refused")
    monkeypatch.setattr(oracles.urllib.request, "urlopen", boom)
    r = oracles.oracle_image_tokens("http://fake")
    assert not r.ok and "probe failed" in r.detail


# ---- grammar ---------------------------------------------------------------


def _reply(text: str):
    return lambda body: {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 1}}


def test_grammar_oracle_passes_on_schema_shaped_json(monkeypatch) -> None:
    _fake_server(monkeypatch, _reply('{"answer": "The sea is vast.", "ok": true}'))
    assert oracles.oracle_grammar("http://fake").ok


def test_grammar_oracle_fails_when_server_ignores_schema(monkeypatch) -> None:
    _fake_server(monkeypatch, _reply("The sea is vast and blue. It never sleeps."))
    r = oracles.oracle_grammar("http://fake")
    assert not r.ok and "IGNORED" in r.detail


def test_grammar_probe_sends_what_the_product_sends(monkeypatch) -> None:
    """The oracle must exercise exactly the constraint the product sends: a
    compiled GBNF `grammar` and NO response_format. Two earlier cuts got
    this wrong (response_format only -> ignored; both -> double constraint,
    reply truncated mid-string) and reported false failures on a build the
    product works on."""
    seen = {}

    def handler(body):
        seen.update(body)
        return {"choices": [{"message": {"content": '{"answer": "x", "ok": true}'},
                             "finish_reason": "stop"}]}
    _fake_server(monkeypatch, handler)
    r = oracles.oracle_grammar("http://fake")
    assert r.ok and r.data["finish_reason"] == "stop"
    assert "grammar" in seen and "root" in seen["grammar"]      # GBNF text
    assert "response_format" not in seen


def test_grammar_oracle_distinguishes_truncation_from_ignored(monkeypatch) -> None:
    _fake_server(monkeypatch, lambda body: {"choices": [{"message": {"content": '{"answer": "The sea'},
                                                          "finish_reason": "length"}]})
    r = oracles.oracle_grammar("http://fake")
    assert not r.ok and "cut off" in r.detail


def test_grammar_oracle_fails_on_wrong_keys(monkeypatch) -> None:
    _fake_server(monkeypatch, _reply('{"text": "x"}'))
    r = oracles.oracle_grammar("http://fake")
    assert not r.ok and "keys" in r.detail


# ---- vector_dims -----------------------------------------------------------


class _Cfg:
    def __init__(self, size):
        self.size = size


class _FakeClient:
    def __init__(self, dense=None, fast=None):
        self._c = {}
        if dense is not None:
            self._c["summaries"] = {"dense": _Cfg(dense)}
        if fast is not None:
            self._c["fast_tier"] = _Cfg(fast)

    def collection_exists(self, name):
        return name in self._c

    def get_collection(self, name):
        class _P:  # mimic client.get_collection(...).config.params.vectors
            pass
        info = _P(); info.config = _P(); info.config.params = _P()
        info.config.params.vectors = self._c[name]
        return info


def test_vector_dims_pass_when_widths_match() -> None:
    from src.stage2.embeddings import DENSE_VECTOR_SIZE
    from src.stage2.fast_db import FAST_VECTOR_DIM

    r = oracles.oracle_vector_dims(_FakeClient(DENSE_VECTOR_SIZE, FAST_VECTOR_DIM))
    assert r.ok and r.data["dense"]["stored"] == DENSE_VECTOR_SIZE


def test_vector_dims_fail_on_mismatch() -> None:
    from src.stage2.embeddings import DENSE_VECTOR_SIZE

    r = oracles.oracle_vector_dims(_FakeClient(DENSE_VECTOR_SIZE + 1, None))
    assert not r.ok and "summaries.dense" in r.detail


def test_vector_dims_missing_collections_pass_with_note() -> None:
    r = oracles.oracle_vector_dims(_FakeClient())
    assert r.ok and "not created yet" in r.detail


# ---- run_all / cache -------------------------------------------------------


def test_run_all_without_server_skips_server_oracles() -> None:
    results = oracles.run_all(None, client=_FakeClient())
    names = [r.name for r in results]
    assert names == ["image_tokens", "grammar", "vector_dims"]
    assert results[0].data.get("skipped") and results[0].ok


def test_cache_round_trip_and_ensure(tmp_path: Path, monkeypatch) -> None:
    calls = {"n": 0}

    def fake_run_all(base_url, client=None):
        calls["n"] += 1
        return [oracles.OracleResult("x", True, "fine", {})]
    monkeypatch.setattr(oracles, "run_all", fake_run_all)

    rec = oracles.ensure_for_fingerprint("abc123", None)
    assert rec["ok"] and calls["n"] == 1
    assert oracles.load_cached("abc123")["results"][0]["name"] == "x"
    oracles.ensure_for_fingerprint("abc123", None)          # cached
    assert calls["n"] == 1
    oracles.ensure_for_fingerprint("abc123", None, force=True)
    assert calls["n"] == 2


# ---- idle scheduling -------------------------------------------------------


def test_schedule_waits_for_idle_and_runs_once(monkeypatch) -> None:
    ran = []
    monkeypatch.setattr(oracles, "ensure_for_fingerprint",
                        lambda fp, url, force=False: (ran.append(url) or {"ok": True, "results": []}))
    idle = {"v": 0.0}
    assert oracles.schedule_after_idle("fp1", "vision", "http://s", lambda p: idle["v"],
                                       min_idle_s=0.05) is True
    # a second schedule for the same fingerprint is a no-op
    assert oracles.schedule_after_idle("fp1", "vision", "http://s", lambda p: idle["v"]) is False
    time.sleep(0.1)
    assert ran == []                       # busy server: nothing ran yet
    idle["v"] = 1.0
    for _ in range(50):
        if ran:
            break
        time.sleep(0.1)
    assert ran == ["http://s"]


def test_schedule_skips_when_already_cached(tmp_path: Path) -> None:
    oracles.save("fp2", [oracles.OracleResult("x", True, "ok", {})])
    assert oracles.schedule_after_idle("fp2", "vision", "http://s", lambda p: 100.0) is False


def test_schedule_gives_up_when_server_evicted(monkeypatch) -> None:
    ran = []
    monkeypatch.setattr(oracles, "ensure_for_fingerprint",
                        lambda fp, url, force=False: ran.append(url))
    assert oracles.schedule_after_idle("fp3", "vision", "http://s", lambda p: None,
                                       min_idle_s=0.05) is True
    time.sleep(0.2)
    assert ran == [] and "fp3" not in oracles._scheduled
