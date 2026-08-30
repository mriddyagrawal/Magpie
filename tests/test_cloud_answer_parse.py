"""The magpie-cloud provider re-parses the desktop's answer message into
(question, snippets). The message leads with the files since 2026-08-28,
so the question is no longer the first prose line — it must be found by its
marker wherever it sits, and prose after the files must not be glued onto
the last file's text."""

from __future__ import annotations

from src.cloud_provider import _parse_answer_message


FILES = (
    "--- File 1: /docs/a.pdf ---\n\nContent type: pdf\n\n---\nbaud rate is 9600\n\n"
    "--- File 2: /docs/b.md ---\n\nsecond file body"
)


def test_question_found_after_the_files():
    msg = [
        FILES,
        "Current question: what is the baud rate?\n\nAnswer the current question from the files above.",
        "\nOUTPUT FORMAT: respond with JSON",
        "\nNow answer this question: what is the baud rate?",
    ]
    question, snippets = _parse_answer_message(msg)
    assert question == "what is the baud rate?"
    assert [s["path"] for s in snippets] == ["/docs/a.pdf", "/docs/b.md"]
    assert snippets[0]["text"].endswith("baud rate is 9600")
    assert snippets[1]["text"] == "second file body"
    assert "OUTPUT FORMAT" not in snippets[1]["text"]


def test_old_question_first_order_still_parses():
    msg = ["Current date and time: x", "Question: how many?", "--- File 1: /f.txt ---\nbody"]
    question, snippets = _parse_answer_message(msg)
    assert question == "how many?"
    assert snippets == [{"path": "/f.txt", "text": "body"}]
