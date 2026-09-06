"""The answer-step user turn: files first, query zone last, one question copy.

Pins the 2026-09-06 order so the prefix (system + files) stays stable for
llama-server's prompt cache and the question sits in the recency zone.
"""

from __future__ import annotations

import os

import pytest

from src.answer import _build_answer_message


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
    assert msg[-1] == "Now answer this question: What is X?"          # the task is last
    assert msg[-2].startswith("\nToday: ")                            # clock directly above it
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


def test_only_the_answer_step_carries_a_clock() -> None:
    """The summariser copied the run date into file identifiers and the
    rewriter copied it into search queries, so src.llm no longer adds a
    clock to anything; the answer step places its own."""
    import src.llm as llm
    from src.stage2.search import _build_rewrite_prompt
    assert not hasattr(llm, "_append_timestamp") and not hasattr(llm, "_wants_timestamp")
    assert "Today:" not in _build_rewrite_prompt("receipts from last month", None)


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
    assert last_img < msg.index("Now answer this question: q")


def test_prefix_is_identical_across_questions_over_the_same_files() -> None:
    """The cache argument: same files, different question -> same head."""
    blocks = [("a.txt", ["Content type: txt\n\n---\nbody"])]
    m1 = _build_answer_message("first?", blocks, None, enumerate_lists=False)
    m2 = _build_answer_message("second?", blocks, None, enumerate_lists=False)
    assert m1[:2] == m2[:2]            # header + block identical
    assert m1[-1] != m2[-1]
    assert m1[-2].startswith("\nToday: ") and m2[-2].startswith("\nToday: ")


def test_clock_sits_between_guidance_and_question() -> None:
    blocks = [("a.txt", ["Content type: txt\n\n---\nbody"])]
    msg = _build_answer_message("q?", blocks, None, enumerate_lists=False)
    texts = _texts(msg)
    i_clock = next(i for i, t in enumerate(texts) if t.startswith("\nToday: "))
    # the element before the clock is the tail of the query zone: guidance,
    # or the cloud JSON contract when the active provider is not local
    assert texts[i_clock - 1].lstrip().startswith(
        ("Answer the question below", "Previous conversation", "OUTPUT FORMAT"))
    assert texts[i_clock + 1] == "Now answer this question: q?"
    assert i_clock + 1 == len(texts) - 1
