"""Wire-protocol roundtrip tests — pickle through multiprocessing.connection.

These verify that a daemon and client process can exchange every defined
request/response shape without losing fields or hitting unpickle errors.
The actual transport (Listener/Client) is exercised by test_lifecycle.py;
here we just check the dataclasses serialize cleanly.
"""

from __future__ import annotations

import pickle

from src.daemon import protocol as proto


def test_ping_request_roundtrip():
    msg = proto.PingRequest()
    out = pickle.loads(pickle.dumps(msg))
    assert isinstance(out, proto.PingRequest)
    assert out.protocol_version == proto.PROTOCOL_VERSION


def test_ping_response_roundtrip():
    msg = proto.PingResponse(
        ok=True, protocol_version=1, pid=42,
        uptime_sec=12.5, idle_timeout_sec=900, last_activity_ago_sec=3.2,
    )
    out = pickle.loads(pickle.dumps(msg))
    assert out == msg


def test_ask_request_roundtrip():
    msg = proto.AskRequest(
        question="what was on my receipts last March?",
        top_k=10, rewrite=True, rerank=True,
        history=[("prev q", "prev a")],
    )
    out = pickle.loads(pickle.dumps(msg))
    assert out == msg
    assert out.history == [("prev q", "prev a")]


def test_ask_response_success_roundtrip():
    msg = proto.AskResponse(
        ok=True, question="q", answer="a",
        sources_used=["src/foo.md"],
        retrieved=[{"path": "x.pdf", "score": 0.9, "tier": "summary", "summary": "..."}],
    )
    out = pickle.loads(pickle.dumps(msg))
    assert out == msg


def test_ask_response_error_roundtrip():
    msg = proto.AskResponse(
        ok=False, error="boom", error_type="RuntimeError",
    )
    out = pickle.loads(pickle.dumps(msg))
    assert out == msg
    assert out.answer == ""  # default-empty


def test_shutdown_roundtrip():
    req = pickle.loads(pickle.dumps(proto.ShutdownRequest()))
    resp = pickle.loads(pickle.dumps(proto.ShutdownResponse(ok=True)))
    assert isinstance(req, proto.ShutdownRequest)
    assert resp.ok is True


def test_protocol_error_carries_server_version():
    msg = proto.ProtocolError(error="bad request type", server_protocol_version=99)
    out = pickle.loads(pickle.dumps(msg))
    assert out.server_protocol_version == 99
