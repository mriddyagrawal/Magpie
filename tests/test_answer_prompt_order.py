"""The answer-step user turn: files first, query zone last, one question copy.

Pins the 2026-09-06 order so the prefix (system + files) stays stable for
llama-server's prompt cache and the question sits in the recency zone.
"""

from __future__ import annotations

import os

import pytest

from src.answer import _build_answer_message
from src.llm import _append_timestamp


class _Img:
    def __init__(self, tag: str) -> None:
        self.data = tag.encode()
        self.media_type = "image/png"


def _texts(message: list) -> list[str]:
    return [m for m in message if isinstance(m, str)]


@pytest.fixture(autouse=True)
def _local_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "local")  # no cloud JSON block


def test_files_come_first_and_the_question_only_at_the_end() -> None:
    blocks = [("best.pdf", ["Content type: pdf\n\n---\nbody A"]),
              ("second.txt", ["Content type: txt\n\n---\nbody B"])]
    msg = _build_answer_message("What is X?", blocks, None, enumerate_lists=False)
    joined = "\n".join(_texts(msg))
    assert msg[0].lstrip().startswith("--- File 1: second.txt ---")   # best-ranked LAST
    assert "--- File 2: best.pdf ---" in joined
    assert joined.count("What is X?") == 1                            # no top copy
    assert msg[-1] == "\nNow answer this question: What is X?"
    assert "Current question:" not in joined
    # guidance sits AFTER the last file and speaks of "the files above"
    guidance_at = joined.index("Answer the question below from the files above")
    assert guidance_at > joined.index("--- File 2: best.pdf ---")


def test_history_is_in_the_query_zone_after_the_files() -> None:
    blocks = [("a.txt", ["Content type: txt\n\n---\nbody"])]
    msg = _build_answer_message("follow-up?", blocks, [("q1", "a1")], enumerate_lists=False)
    joined = "\n".join(_texts(msg))
    assert joined.index("Previous conversation turns:") > joined.index("--- File 1: a.txt ---")
    assert joined.index("[Turn 1] Q: q1") < joined.index("Now answer this question")


def test_images_stay_inline_under_their_header_with_captions_for_multi_image_files() -> None:
    p1, p2 = _Img("1"), _Img("2")
    blocks = [("scan.pdf", ["Content type: pdf (scanned)", p1, p2]),
              ("photo.png", [_Img("solo")])]
    msg = _build_answer_message("q", blocks, None, enumerate_lists=False)
    # reversed: photo.png is File 1, scan.pdf is File 2
    i_photo = msg.index("\n--- File 1: photo.png ---")
    assert not isinstance(msg[i_photo + 1], str)                    # lone image, no caption
    i_scan = msg.index("\n--- File 2: scan.pdf ---")
    assert msg[i_scan + 2] == "[File 2, image 1 of 2]" and msg[i_scan + 3] is p1
    assert msg[i_scan + 4] == "[File 2, image 2 of 2]" and msg[i_scan + 5] is p2
    # the last image precedes the whole query zone
    last_img = max(i for i, m in enumerate(msg) if not isinstance(m, str))
    assert last_img < msg.index("\nNow answer this question: q")


def test_prefix_is_identical_across_questions_over_the_same_files() -> None:
    """The cache argument: same files, different question -> same head."""
    blocks = [("a.txt", ["Content type: txt\n\n---\nbody"])]
    m1 = _build_answer_message("first?", blocks, None, enumerate_lists=False)
    m2 = _build_answer_message("second?", blocks, None, enumerate_lists=False)
    assert m1[:2] == m2[:2]            # header + block identical
    assert m1[-1] != m2[-1]


def test_timestamp_is_the_last_element_of_the_turn() -> None:
    out = _append_timestamp(["files", "\nNow answer this question: q"])
    assert out[:2] == ["files", "\nNow answer this question: q"]
    assert out[-1].startswith("Current date and time: ")
