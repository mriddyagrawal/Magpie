"""The magpie-cloud sidecar recovers (question, snippets) from the answer
message layout. Built from the real assembler so the contract cannot drift."""

from __future__ import annotations

import pytest

from src.answer import _build_answer_message
from src.cloud_provider import _parse_answer_message


@pytest.fixture(autouse=True)
def _cloud_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")   # exercises the JSON block too


def test_parses_question_and_snippets_from_the_real_layout() -> None:
    blocks = [("/x/best.pdf", ["Content type: pdf\n\n---\nbody A"]),
              ("/x/second.txt", ["Content type: txt\n\n---\nbody B"])]
    msg = _build_answer_message("How much?", blocks, [("q1", "a1")], enumerate_lists=False)
    question, snippets = _parse_answer_message(msg)
    assert question == "How much?"
    assert [s["path"] for s in snippets] == ["/x/second.txt", "/x/best.pdf"]   # best last
    assert snippets[0]["text"] == "Content type: txt\n\n---\nbody B"
    assert snippets[1]["text"] == "Content type: pdf\n\n---\nbody A"
    # nothing from the query zone leaks into the last snippet
    joined = "\n".join(s["text"] for s in snippets)
    for needle in ("Previous conversation", "Answer the question below", "Today:", "OUTPUT FORMAT", "How much?"):
        assert needle not in joined, needle


def test_images_are_skipped_not_stringified() -> None:
    class Img:
        data = b"\x89PNG"
        media_type = "image/png"

    msg = _build_answer_message("q", [("/x/a.png", [Img()])], None, enumerate_lists=False)
    question, snippets = _parse_answer_message(msg)
    assert question == "q"
    assert snippets == [{"path": "/x/a.png", "text": ""}]
