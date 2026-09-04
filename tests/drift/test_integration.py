"""Integration seams of the drift guard: the LocalLLM tripwire hook, the
pool's on_server_ready filter, and the /drift + /status routes."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.drift import oracles, tripwire
from src.inference.image_tokens import estimate_image_tokens


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tripwire, "LOG_PATH", tmp_path / "tripwires.jsonl")
    monkeypatch.setattr(tripwire, "DRIFT_DIR", tmp_path)
    monkeypatch.setattr(oracles, "DRIFT_DIR", tmp_path)
    tripwire._reset_for_tests()
    oracles._scheduled.clear()
    yield
    tripwire._reset_for_tests()
    oracles._scheduled.clear()


def _png(w: int, h: int) -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
            + w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes(5))


# ---- LocalLLM._tripwire_after -------------------------------------------------


def _llm(monkeypatch, token_count):
    from src.inference.local_llm import LlamaServerLLM

    llm = LlamaServerLLM.__new__(LlamaServerLLM)   # no server, no profiles
    monkeypatch.setattr(llm, "_count_tokens", lambda profile, text: token_count, raising=False)
    return llm


def test_tripwire_hook_trips_on_a_20pct_image_undercount(monkeypatch) -> None:
    """The reviewer's scenario end-to-end: 10K chars of text counted
    exactly, one 1080x1920 image whose real cost is 20% above the
    estimate -> the server-reported total must trip."""
    text = "word " * 2_000                           # ~10K chars
    text_tokens = 2_500
    llm = _llm(monkeypatch, text_tokens)
    est = estimate_image_tokens(1080, 1920)
    prepared = [{"role": "system", "content": "sys"},
                {"role": "user", "content": [{"type": "text", "text": text},
                                             {"type": "image_url", "image_url": {"url": "data:..."}}]}]
    payload = {"usage": {"prompt_tokens": text_tokens + int(est * 1.2) + 30}}
    assert llm._tripwire_after("vision", prepared, [_png(1080, 1920)], payload,
                               run_async=False) is True
    assert tripwire.summary()["trips"] == 1


def test_tripwire_hook_quiet_when_estimate_holds(monkeypatch) -> None:
    llm = _llm(monkeypatch, 2_500)
    est = estimate_image_tokens(1080, 1920)
    prepared = [{"role": "user", "content": "x" * 10_000}]
    payload = {"usage": {"prompt_tokens": 2_500 + est + 30}}   # exact + framing
    assert llm._tripwire_after("vision", prepared, [_png(1080, 1920)], payload,
                               run_async=False) is False


def test_tripwire_hook_falls_back_when_tokenize_fails(monkeypatch) -> None:
    llm = _llm(monkeypatch, None)                   # /tokenize unavailable
    prepared = [{"role": "user", "content": "x" * 4_000}]
    # chars/4 guess = 1,000; margin widened 5x -> +384 allowed at this size
    assert llm._tripwire_after("text", prepared, None,
                               {"usage": {"prompt_tokens": 1_300}}, run_async=False) is False
    assert "estimated" in tripwire.summary()["last_trip"]["context"] if tripwire.summary()["trips"] else True


def test_tripwire_hook_ignores_payload_without_usage(monkeypatch) -> None:
    llm = _llm(monkeypatch, 10)
    assert llm._tripwire_after("text", [{"role": "user", "content": "hi"}], None,
                               {"choices": []}, run_async=False) is None
    assert tripwire.summary()["checks"] == 0


def test_tripwire_hook_async_never_blocks_or_raises(monkeypatch) -> None:
    llm = _llm(monkeypatch, 5)
    t0 = time.monotonic()
    assert llm._tripwire_after("text", [{"role": "user", "content": "hi"}], None,
                               {"usage": {"prompt_tokens": 500}}) is None
    assert time.monotonic() - t0 < 0.5
    for _ in range(50):                             # thread lands shortly
        if tripwire.summary()["checks"]:
            break
        time.sleep(0.02)
    assert tripwire.summary()["checks"] == 1


# ---- pool hook -----------------------------------------------------------------


def test_on_server_ready_only_schedules_for_the_vision_profile(monkeypatch) -> None:
    scheduled = []
    monkeypatch.setattr(oracles, "schedule_after_idle",
                        lambda fp, prof, url, idle, **kw: scheduled.append(prof) or True)
    monkeypatch.setattr("src.inference.profiles.default_vision_profile", lambda: "vision-prof")
    monkeypatch.setattr("src.drift.provenance.runtime_fingerprint",
                        lambda: {"fingerprint": "fp", "oracle_key": "ok1"})
    oracles.on_server_ready("text-only-prof", "http://s", lambda p: 0.0)
    oracles.on_server_ready("vision-prof", "http://s", lambda p: 0.0)
    for _ in range(50):
        if scheduled:
            break
        time.sleep(0.02)
    assert scheduled == ["vision-prof"]


# ---- server routes --------------------------------------------------------------


def test_drift_routes_before_and_after_probe(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    import src.server as server

    monkeypatch.setattr(server, "_drift_state",
                        {"provenance": None, "pins": None, "checking": False, "error": None})
    client = TestClient(server.app)

    r = client.get("/drift")
    assert r.status_code == 200 and r.json()["ready"] is False
    assert r.json()["oracles"] is None and r.json()["tripwire"]["checks"] == 0

    prov = {"fingerprint": "abc", "oracle_key": "abc-launch", "llama_server": {"build": 10502},
            "qdrant": {"version": None}, "models": {}, "col_model": {}, "magpie": {}}
    server._drift_state["provenance"] = prov
    server._drift_state["pins"] = []
    oracles.save("abc-launch", [oracles.OracleResult("x", True, "ok", {})])

    r = client.get("/drift")
    body = r.json()
    assert body["ready"] is True and body["oracles"]["ok"] is True
    assert body["pin_mismatches"] == []

    summ = server._drift_summary()
    assert summ["fingerprint"] == "abc" and summ["oracles"] == "ok"
    assert summ["pin_mismatches"] == 0 and summ["llama_server"] == "b10502"


def test_drift_check_is_single_flight(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import src.server as server

    monkeypatch.setattr(server, "_drift_state",
                        {"provenance": None, "pins": None, "checking": True, "error": None})
    client = TestClient(server.app)
    r = client.post("/drift/check")
    assert r.status_code == 202 and r.json()["status"] == "already running"


# ---- streaming path keeps tripwire coverage ---------------------------------


def test_stream_body_requests_usage_and_usage_line_parses() -> None:
    from src.inference.local_llm import _parse_sse_usage

    assert _parse_sse_usage('data: {"choices": [], "usage": {"prompt_tokens": 1234, "completion_tokens": 7}}') \
        == {"prompt_tokens": 1234, "completion_tokens": 7}
    assert _parse_sse_usage('data: {"choices": [{"delta": {"content": "hi"}}]}') is None
    assert _parse_sse_usage("data: [DONE]") is None
    assert _parse_sse_usage(": heartbeat") is None
    assert _parse_sse_usage("data: not json") is None


def test_stream_requests_include_usage(monkeypatch) -> None:
    """The streaming request must ask llama-server for the usage chunk, or
    the tripwire is blind on that path."""
    import asyncio

    from src.inference.local_llm import LlamaServerLLM

    llm = LlamaServerLLM.__new__(LlamaServerLLM)
    llm.model_id = "test::Q0"
    llm.profile_name = "text"
    llm.request_timeout_s = 1.0
    built: dict = {}

    def fake_build(prepared, temperature, max_tokens, *, stream, thinking=False,
                   response_format=None, grammar=None):
        built.update({"messages": prepared, "stream": stream})
        return built                                   # same dict the method mutates
    monkeypatch.setattr(llm, "_build_request_body", fake_build, raising=False)
    monkeypatch.setattr(llm, "_base_url", lambda profile=None: "http://127.0.0.1:1", raising=False)
    monkeypatch.setattr("src.inference.local_llm.apply_thinking_to_messages",
                        lambda m, thinking=False, model_repo_or_path=None: m)

    asyncio.run(llm.stream([{"role": "user", "content": "hi"}]))   # body built eagerly
    assert built["stream"] is True
    assert built["stream_options"] == {"include_usage": True}
