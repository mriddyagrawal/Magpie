"""Answer streaming: the JSON scanner that picks the `answer` value out of
the token stream, the callback → iterator bridge, and the hook in
answer_question. No model, no server."""

from __future__ import annotations

import asyncio
import json
import random

import pytest

from src.answer_stream import AnswerFieldStreamer, stream_answer


def _stream(raw: str, pieces: list[int] | None = None) -> tuple[list[str], AnswerFieldStreamer]:
    """Feed `raw` through a streamer in chunks of the given sizes (or one
    char at a time) and return what it emitted."""
    got: list[str] = []
    st = AnswerFieldStreamer(got.append)
    if pieces is None:
        for ch in raw:
            st.feed(ch)
    else:
        i = 0
        for n in pieces:
            st.feed(raw[i:i + n])
            i += n
        st.feed(raw[i:])
    return got, st


LOCAL_REPLY = json.dumps({
    "evidence": ["Total: $143.50", "Flight to Hartford, March 3"],
    "answer": "The flight to Hartford cost $143.50[1].\nBooked March 3.",
    "sources_used": ["1"],
    "not_found": False,
    "not_found_topic": "",
})


def test_emits_only_the_answer_value_decoded():
    got, st = _stream(LOCAL_REPLY)
    assert "".join(got) == json.loads(LOCAL_REPLY)["answer"]
    assert st.text == "".join(got)
    assert st.done


def test_char_at_a_time_and_random_chunking_agree():
    expected = json.loads(LOCAL_REPLY)["answer"]
    rng = random.Random(7)
    for _ in range(50):
        sizes = [rng.randint(1, 9) for _ in range(len(LOCAL_REPLY) // 3)]
        got, _ = _stream(LOCAL_REPLY, sizes)
        assert "".join(got) == expected


def test_escapes_split_across_chunks():
    raw = '{"answer": "a\\nb\\u00e9c \\"q\\" \\\\ \\ud83d\\ude00!", "not_found": false}'
    expected = json.loads(raw)["answer"]
    # cut inside the \n, inside the é, between the surrogate halves
    for cut in range(1, len(raw)):
        got, _ = _stream(raw, [cut])
        assert "".join(got) == expected, f"cut at {cut}"


def test_evidence_containing_the_answer_key_does_not_fool_it():
    raw = json.dumps({
        "evidence": ['the file says "answer": "wrong" here', "{\"answer\": \"nope\"}"],
        "answer": "right",
        "sources_used": [],
        "not_found": False,
        "not_found_topic": "",
    })
    got, _ = _stream(raw)
    assert "".join(got) == "right"


def test_nested_answer_key_is_ignored():
    raw = '{"meta": {"answer": "inner"}, "answer": "outer"}'
    got, _ = _stream(raw)
    assert "".join(got) == "outer"


def test_preamble_and_fences_are_skipped():
    raw = 'Sure! Here is the JSON:\n```json\n{"answer": "yes", "not_found": false}\n```\n'
    got, _ = _stream(raw)
    assert "".join(got) == "yes"


def test_whitespace_around_the_colon():
    got, _ = _stream('{ "answer"   :   "spaced" }')
    assert "".join(got) == "spaced"


def test_empty_answer_emits_nothing():
    got, st = _stream('{"answer": "", "sources_used": [], "not_found": true, "not_found_topic": "x"}')
    assert got == []
    assert st.done


def test_no_answer_field_emits_nothing():
    got, st = _stream('{"summary": "no answer here", "keywords": ["answer"]}')
    assert got == []
    assert not st.done


def test_non_string_answer_emits_nothing():
    got, _ = _stream('{"answer": null, "other": "x"}')
    assert got == []
    got, _ = _stream('{"answer": ["list"], "other": "x"}')
    assert got == []


def test_text_after_the_answer_is_ignored():
    got, st = _stream('{"answer": "done", "not_found_topic": "answer"} trailing "answer": "x"')
    assert "".join(got) == "done"
    assert st.done


def test_emits_once_per_feed_call():
    got: list[str] = []
    st = AnswerFieldStreamer(got.append)
    st.feed('{"answer": "hello ')
    st.feed('world"}')
    assert got == ["hello ", "world"]


def test_stream_answer_yields_pieces_then_the_result():
    async def start(on_answer_text):
        async def run():
            on_answer_text("a")
            await asyncio.sleep(0)
            on_answer_text("b")
            return {"answer": "ab"}
        return await run()

    async def collect():
        return [item async for item in stream_answer(start)]

    items = asyncio.run(collect())
    assert items == [("text", "a"), ("text", "b"), ("answer", {"answer": "ab"})]


def test_stream_answer_raises_after_delivering_pieces():
    async def start(on_answer_text):
        on_answer_text("partial")
        await asyncio.sleep(0)
        raise RuntimeError("model fell over")

    async def collect():
        got = []
        with pytest.raises(RuntimeError, match="fell over"):
            async for item in stream_answer(start):
                got.append(item)
        return got

    assert asyncio.run(collect()) == [("text", "partial")]


def test_stream_answer_cancels_the_call_when_the_consumer_stops():
    cancelled = asyncio.Event()

    async def start(on_answer_text):
        on_answer_text("a")
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "never"

    async def consume_one():
        gen = stream_answer(start)
        first = await gen.__anext__()
        await gen.aclose()
        await asyncio.sleep(0)
        return first

    assert asyncio.run(consume_one()) == ("text", "a")
    assert cancelled.is_set()


def test_answer_question_streams_the_answer_field(tmp_path, monkeypatch):
    from src.answer import Answer, answer_question

    doc = tmp_path / "notes.md"
    doc.write_text("The panel has 256 elements.\n", encoding="utf-8")
    monkeypatch.setenv("MAGPIE_FORCE_PROVIDER", "local")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("MAGPIE_KV_CACHE", "0")
    monkeypatch.setenv("MAGPIE_GROUNDING", "off")

    raw = json.dumps({
        "answer": "It has 256 elements[1].",
        "sources_used": ["1"],
        "not_found": False,
        "not_found_topic": "",
    })

    class FakeAgent:
        _system_prompt = "sys"

        async def run(self, message, *, on_text=None, **kw):
            # the raw JSON leaves the model in pieces; the streamer in
            # answer_question should turn them into answer text
            for i in range(0, len(raw), 5):
                on_text(raw[i:i + 5])
            return Answer.model_validate_json(raw)

    pieces: list[str] = []
    ans = asyncio.run(answer_question(
        FakeAgent(), "How many elements?", [str(doc)], on_answer_text=pieces.append,
    ))
    assert "".join(pieces) == "It has 256 elements[1]."
    assert len(pieces) > 1
    assert ans.answer == "It has 256 elements[1]."
    assert ans.sources_used == [str(doc)]


def test_answer_question_without_callback_does_not_pass_on_text(tmp_path, monkeypatch):
    from src.answer import Answer, answer_question

    doc = tmp_path / "notes.md"
    doc.write_text("The panel has 256 elements.\n", encoding="utf-8")
    monkeypatch.setenv("MAGPIE_FORCE_PROVIDER", "local")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("MAGPIE_KV_CACHE", "0")
    monkeypatch.setenv("MAGPIE_GROUNDING", "off")

    class StrictFakeAgent:
        _system_prompt = "sys"

        # no on_text in the signature — a bare double must keep working
        async def run(self, message, *, thinking=False, temperature=None, kv_prefix=None):
            return Answer(answer="256", sources_used=["1"], not_found=False, not_found_topic="")

    ans = asyncio.run(answer_question(StrictFakeAgent(), "How many elements?", [str(doc)]))
    assert ans.answer == "256"
