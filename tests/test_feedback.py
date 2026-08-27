"""Tests for src.feedback + the /feedback endpoint.

Nothing here touches the network: `_deliver` is always monkeypatched.
MAGPIE_DATA_DIR is pointed at tmp_path (fixture shape follows
tests/test_local_install_endpoints.py) so the outbox lands in the
test's own sandbox.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(tmp_path))
    # The dev .env (loaded by src.server import elsewhere) must not leak a
    # real webhook into these tests.
    monkeypatch.delenv("FEEDBACK_WEBHOOK_URL", raising=False)
    import src.manifest

    importlib.reload(src.manifest)
    import src.feedback as feedback

    importlib.reload(feedback)
    monkeypatch.setattr(feedback, "_bundled_webhook", lambda: "")
    try:
        yield feedback
    finally:
        monkeypatch.undo()
        importlib.reload(src.manifest)
        importlib.reload(feedback)


# ---------------------------------------------------------------------------
# Payload shaping
# ---------------------------------------------------------------------------

def test_discord_payload_shape_and_cap(fb):
    url = "https://discord.com/api/webhooks/123/abc"
    p = fb._shape_payload(url, "hi")
    assert p == {"content": "hi"}
    long = "x" * 5000
    assert len(fb._shape_payload(url, long)["content"]) <= 1990


def test_slack_payload_shape(fb):
    p = fb._shape_payload("https://hooks.slack.com/services/T/B/x", "hi")
    assert p == {"text": "hi"}


def test_generic_payload_shape(fb):
    p = fb._shape_payload("https://example.com/hook", "hi")
    assert p == {"message": "hi"}


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def test_format_includes_meta_but_not_context_by_default(fb):
    text = fb._format_text("love it", None)
    assert "love it" in text
    assert "Magpie v" in text  # version/OS/provider meta line
    assert "> Q:" not in text


def test_format_context_only_when_given_and_capped(fb):
    ctx = {"question": "q" * 2000, "answer": "a" * 2000}
    text = fb._format_text("msg", ctx)
    assert "> Q: " + "q" * 700 in text
    assert "q" * 701 not in text


# ---------------------------------------------------------------------------
# Store-and-forward
# ---------------------------------------------------------------------------

def test_submit_queues_on_delivery_failure(fb, monkeypatch):
    monkeypatch.setenv("FEEDBACK_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setattr(fb, "_deliver", lambda text: False)
    out = fb.submit("offline feedback")
    assert out == {"delivered": False, "queued": True}
    lines = fb._outbox_path().read_text().splitlines()
    assert len(lines) == 1
    assert "offline feedback" in json.loads(lines[0])["text"]


def test_flush_outbox_delivers_and_clears(fb, monkeypatch):
    monkeypatch.setenv("FEEDBACK_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setattr(fb, "_deliver", lambda text: False)
    fb.submit("one")
    fb.submit("two")
    assert len(fb._outbox_path().read_text().splitlines()) == 2

    sent: list[str] = []
    monkeypatch.setattr(fb, "_deliver", lambda text: (sent.append(text), True)[1])
    assert fb.flush_outbox() == 2
    assert not fb._outbox_path().exists()
    assert any("one" in t for t in sent) and any("two" in t for t in sent)


def test_flush_keeps_entries_that_still_fail(fb, monkeypatch):
    monkeypatch.setenv("FEEDBACK_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setattr(fb, "_deliver", lambda text: False)
    fb.submit("stuck")
    assert fb.flush_outbox() == 0
    assert len(fb._outbox_path().read_text().splitlines()) == 1


def test_submit_sends_backlog_along_with_fresh_message(fb, monkeypatch):
    monkeypatch.setenv("FEEDBACK_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setattr(fb, "_deliver", lambda text: False)
    fb.submit("older, typed offline")

    sent: list[str] = []
    monkeypatch.setattr(fb, "_deliver", lambda text: (sent.append(text), True)[1])
    out = fb.submit("fresh")
    assert out["delivered"] is True
    assert not fb._outbox_path().exists()
    assert any("older, typed offline" in t for t in sent)
    assert any("fresh" in t for t in sent)


def test_flush_is_a_noop_when_unconfigured(fb, monkeypatch):
    # No env var, no bundled file — must not attempt delivery at all.
    called = []
    monkeypatch.setattr(fb, "_deliver", lambda text: (called.append(1), True)[1])
    assert fb.flush_outbox() == 0
    assert called == []


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture
def client(fb, monkeypatch) -> Iterator[TestClient]:
    import src.server as server

    importlib.reload(server)
    with TestClient(server.app) as c:
        yield c
    importlib.reload(server)


def test_feedback_503_when_unconfigured(client, fb):
    r = client.post("/feedback", json={"message": "hello"})
    assert r.status_code == 503
    assert "no feedback destination" in r.json()["detail"]


def test_feedback_delivered_roundtrip(client, fb, monkeypatch):
    monkeypatch.setenv("FEEDBACK_WEBHOOK_URL", "https://example.com/hook")
    seen: list[str] = []
    monkeypatch.setattr(fb, "_deliver", lambda text: (seen.append(text), True)[1])
    r = client.post(
        "/feedback",
        json={"message": "great app", "context": {"question": "q?", "answer": "a."}},
    )
    assert r.status_code == 200
    assert r.json() == {"delivered": True, "queued": False}
    assert "great app" in seen[0] and "> Q: q?" in seen[0]


def test_feedback_queued_when_offline(client, fb, monkeypatch):
    monkeypatch.setenv("FEEDBACK_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setattr(fb, "_deliver", lambda text: False)
    r = client.post("/feedback", json={"message": "will arrive later"})
    assert r.status_code == 200
    assert r.json() == {"delivered": False, "queued": True}


def test_feedback_empty_message_rejected(client, fb, monkeypatch):
    monkeypatch.setenv("FEEDBACK_WEBHOOK_URL", "https://example.com/hook")
    r = client.post("/feedback", json={"message": "   "})
    assert r.status_code == 422
