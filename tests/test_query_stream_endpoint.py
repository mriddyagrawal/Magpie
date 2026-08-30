"""`/query/stream` end to end through FastAPI's TestClient, with retrieval
and the answer step stubbed: checks the SSE frame order the frontend
relies on — sources, then answer text as it is written, then the checked
answer, then the cited paths, then done — and the not-found shape where
streamed text must be thrown away."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    # same isolation as the other endpoint tests: config under a tmp dir,
    # no .env, and the modules that captured the data dir reloaded
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    import src.manifest
    importlib.reload(src.manifest)
    import src.config.indexing_rules as ir
    importlib.reload(ir)
    import src.config.settings as st
    importlib.reload(st)
    import src.config.secrets as sec
    importlib.reload(sec)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        yield tmp_path
    finally:
        monkeypatch.undo()
        importlib.reload(src.manifest)
        importlib.reload(ir)
        importlib.reload(st)
        importlib.reload(sec)


@pytest.fixture
def client(isolated_app_data: Path) -> TestClient:
    import src.server as server
    importlib.reload(server)
    return TestClient(server.app)


def _frames(resp) -> list[tuple[str, dict]]:
    """Split an SSE body into (event, payload) pairs."""
    out = []
    for block in resp.text.split("\n\n"):
        event, data = None, None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if event:
            out.append((event, data))
    return out


def _stub_retrieval(monkeypatch, tmp_path: Path) -> str:
    """One retrieved file; no Qdrant, no embeddings, no reranker."""
    import src.manifest as manifest_mod
    import src.recents as recents_mod
    import src.stage2.search as search_mod

    doc = tmp_path / "receipt.txt"
    doc.write_text("Total: $143.50\n", encoding="utf-8")
    hit = SimpleNamespace(path=str(doc), summary="a receipt", score=0.9, chunk_index=None)
    monkeypatch.setattr(search_mod, "run_search", lambda *a, **k: [hit])
    monkeypatch.setattr(search_mod, "gate_to_solo", lambda hits, **k: hits)
    monkeypatch.setattr(manifest_mod, "Manifest", lambda: SimpleNamespace(entries={str(doc): 1}))
    monkeypatch.setattr(recents_mod, "add_recent", lambda **k: SimpleNamespace(id="recent-1"))
    return str(doc)


def test_answer_streams_then_final_then_sources(client: TestClient, monkeypatch, tmp_path):
    import src.answer as answer_mod

    doc = _stub_retrieval(monkeypatch, tmp_path)
    monkeypatch.setattr(answer_mod, "build_answer_agent", lambda **k: object())

    async def fake_answer_question(agent, question, paths, *, on_answer_text=None, **kw):
        for piece in ["The total ", "is $143.50", "[1]."]:
            on_answer_text(piece)
            await asyncio.sleep(0)
        return answer_mod.Answer(
            answer="The total is $143.50[1].", sources_used=[paths[0]],
            not_found=False, not_found_topic="",
        )

    monkeypatch.setattr(answer_mod, "answer_question", fake_answer_question)

    resp = client.post("/query/stream", json={"question": "How much was the receipt?", "rewrite": False})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = _frames(resp)

    assert [e for e, _ in frames] == [
        "sources", "answer_chunk", "answer_chunk", "answer_chunk",
        "answer_final", "sources_used", "done",
    ]
    sources = frames[0][1]
    assert sources["retrieved"][0]["path"] == doc
    assert sources["retrieved"][0]["cited"] is False
    assert sources["sources_scanned_count"] == 1
    streamed = "".join(d["text"] for e, d in frames if e == "answer_chunk")
    assert streamed == "The total is $143.50[1]."
    assert frames[4][1] == {"text": "The total is $143.50[1]."}
    assert frames[5][1] == {"paths": [doc]}
    assert frames[6][1] == {"recent_id": "recent-1"}


def test_not_found_after_streamed_text(client: TestClient, monkeypatch, tmp_path):
    """The grounding guard can refuse an answer the model already wrote:
    chunks went out, then not_found_topic — and no answer_final."""
    import src.answer as answer_mod

    _stub_retrieval(monkeypatch, tmp_path)
    monkeypatch.setattr(answer_mod, "build_answer_agent", lambda **k: object())

    async def fake_answer_question(agent, question, paths, *, on_answer_text=None, **kw):
        on_answer_text("An invented total of $999")
        await asyncio.sleep(0)
        return answer_mod.Answer(
            answer="", sources_used=[], not_found=True, not_found_topic="the receipt total",
        )

    monkeypatch.setattr(answer_mod, "answer_question", fake_answer_question)

    resp = client.post("/query/stream", json={"question": "How much was the receipt?", "rewrite": False})
    frames = _frames(resp)
    assert [e for e, _ in frames] == ["sources", "answer_chunk", "not_found_topic", "done"]
    assert frames[2][1] == {"topic": "the receipt total"}


def test_answer_error_after_streamed_text(client: TestClient, monkeypatch, tmp_path):
    import src.answer as answer_mod

    _stub_retrieval(monkeypatch, tmp_path)
    monkeypatch.setattr(answer_mod, "build_answer_agent", lambda **k: object())

    async def fake_answer_question(agent, question, paths, *, on_answer_text=None, **kw):
        on_answer_text("The tot")
        await asyncio.sleep(0)
        raise RuntimeError("model fell over")

    monkeypatch.setattr(answer_mod, "answer_question", fake_answer_question)

    resp = client.post("/query/stream", json={"question": "How much was the receipt?", "rewrite": False})
    frames = _frames(resp)
    assert [e for e, _ in frames] == ["sources", "answer_chunk", "error", "done"]
    assert frames[2][1]["phase"] == "answer"
    assert "fell over" not in frames[2][1]["detail"]  # user-safe wording only
