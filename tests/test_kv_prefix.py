"""Prefix caching and the extractive fast path — no model, no server.

The answer step's message now leads with the file text so the same
retrieved files give llama-server the same prompt prefix. These pin the
pieces that make that true: the timestamp moves behind the prefix, the
cache key is stable, the LRU trims to its cap, and the factoid router only
fires on questions whose answer is a phrase in the text.
"""

from __future__ import annotations

import os
import time

from src.llm import _prepend_timestamp


def test_timestamp_goes_after_the_cacheable_first_part():
    msg = ["--- File 1: a.md ---\ntext", "Current question: x"]
    out = _prepend_timestamp(msg, after_first=True)
    assert out[0] == msg[0]
    assert out[1].startswith("Current date and time:")
    assert out[2] == msg[1]


def test_timestamp_still_leads_by_default():
    out = _prepend_timestamp(["hello"])
    assert out[0].startswith("Current date and time:")
    assert out[1] == "hello"


def test_cache_key_is_stable_and_model_specific():
    from src.kv_cache import cache_key

    a = cache_key("m::q6", "sys", "--- File 1 ---\nbody\n\n")
    assert a == cache_key("m::q6", "sys", "--- File 1 ---\nbody\n\n")
    assert a != cache_key("m::q8", "sys", "--- File 1 ---\nbody\n\n")
    assert a != cache_key("m::q6", "sys", "--- File 1 ---\nother\n\n")
    assert a.endswith(".bin") and len(a) == 36


def test_lru_eviction_drops_the_oldest_first(tmp_path, monkeypatch):
    import src.kv_cache as kv

    monkeypatch.setattr(kv, "kv_slot_dir", lambda: tmp_path)
    monkeypatch.setattr(kv, "CACHE_CAP_MB", 1)
    for i, name in enumerate(["old.bin", "mid.bin", "new.bin"]):
        p = tmp_path / name
        p.write_bytes(b"x" * 600_000)
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    kv._evict_over_cap()
    left = sorted(p.name for p in tmp_path.glob("*.bin"))
    assert left == ["new.bin"]


def test_factoid_router_fires_on_short_answer_questions():
    from src.extractive import is_factoid

    assert is_factoid("How many elements does the panel have?")
    assert is_factoid("When was the venue booked?")
    assert is_factoid("What is the sampling rate of the acoustic setup?")
    assert is_factoid("Who chairs the math department?")
    assert is_factoid("On what date did I shop at INDAH GIFT?")
    assert is_factoid("Which shop issued the receipt for 33.90 on 12-01-19?")
    assert is_factoid("What is the address printed on the receipt from YONGFATT?")
    assert not is_factoid("What is the PhyLL project about?")
    assert not is_factoid("Explain how the negative pass works")
    assert not is_factoid("List all my receipts from March")


def test_windows_cover_the_whole_text_with_overlap():
    from src.extractive import WINDOW_CHARS, WINDOW_STEP, _windows

    text = "a" * (WINDOW_STEP * 3 + 10)
    wins = _windows(text)
    assert wins[0] == text[:WINDOW_CHARS]
    assert "".join(w[: WINDOW_STEP] for w in wins[:-1]) + wins[-1] == text
    assert all(len(w) <= WINDOW_CHARS for w in wins)


def test_extract_reads_only_the_best_windows(monkeypatch):
    """The reader is the expensive part; it must see the keyword-bearing
    windows and nothing else, and it must not be built when no window
    shares a word with the question."""
    import src.extractive as ex

    seen = []

    def fake_read(question, context):
        seen.append(context)
        if "256" in context:
            return 0.9, "256 elements"
        return 0.1, ""

    monkeypatch.setattr(ex, "_read", fake_read)
    files = [
        ("a.md", "The metasurface panel has 256 elements in a 16x16 grid."),
        ("b.md", "Nothing relevant here at all."),
    ]
    hit = ex.extract("How many elements does the metasurface panel have?", files)
    assert hit == (0.9, "256 elements", "a.md")
    assert seen == [files[0][1]]

    monkeypatch.setattr(ex, "_read", lambda q, c: (_ for _ in ()).throw(AssertionError("reader ran")))
    assert ex.extract("zzz qqq", files) is None


def test_budget_note_is_returned_separately_from_the_file_text():
    """The omitted-files note must not live in the cached prefix: the same
    four files with a different fifth file dropped would otherwise miss."""
    from src.answer import _trim_blocks_to_budget

    blocks = [("a.md", ["x" * 100]), ("b.md", ["y" * 100]), ("c.md", ["z" * 100])]
    kept, note = _trim_blocks_to_budget(blocks, 150)
    # a.md fits; b.md would need truncating below the 500-char floor, so it
    # and c.md are dropped and named in the note
    assert [d for d, _ in kept] == ["a.md"]
    assert all("Context note" not in b for _d, bs in kept for b in bs)
    assert note is not None and "b.md" in note and "c.md" in note
    kept, note = _trim_blocks_to_budget(blocks, 10_000)
    assert len(kept) == 3 and note is None


def test_aggregation_questions_stay_off_the_extractive_route():
    from src.answer import _AGGREGATE_RE

    for q in [
        "How much did I spend in March?",
        "How much did I spend on groceries last month?",
        "How many invoices did I receive in Q1?",
        "How many deposits were made in 2025?",
        "What is the total amount of the bank transactions in March?",
    ]:
        assert _AGGREGATE_RE.search(q), q
    for q in [
        "How many individually controllable elements does the panel have?",
        "What is the operating temperature of the microwave cavity?",
        "Who chairs the math department?",
    ]:
        assert not _AGGREGATE_RE.search(q), q


def test_prompt_order_follows_the_slot(tmp_path, monkeypatch):
    """Cold ask (no slot on disk): question first, no prefix, slot built in
    the background. Warm ask (slot present): files first with the prefix."""
    import asyncio

    import src.inference
    import src.kv_cache as kv
    from src.answer import Answer, answer_question

    doc = tmp_path / "notes.md"
    doc.write_text("The panel has 256 elements.\n" * 30, encoding="utf-8")
    monkeypatch.setenv("MAGPIE_FORCE_PROVIDER", "local")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("MAGPIE_PROMPT_ORDER", "auto")

    class FakeLLM:
        model_id = "m::q"

        def _base_url(self):
            return "http://127.0.0.1:1"

    monkeypatch.setattr(src.inference, "get_local_llm", lambda: FakeLLM())
    built = []
    monkeypatch.setattr(kv, "build_in_background", lambda *a: built.append(a))

    class FakeAgent:
        _system_prompt = "sys"

        def __init__(self):
            self.calls = []

        async def run(self, message, *, thinking=False, temperature=None, kv_prefix=None):
            self.calls.append((message, kv_prefix))
            return Answer(answer="256", sources_used=["1"], not_found=False, not_found_topic="")

    monkeypatch.setattr(kv, "slot_exists", lambda *a: False)
    agent = FakeAgent()
    ans = asyncio.run(answer_question(agent, "How many elements?", [str(doc)]))
    message, prefix = agent.calls[0]
    assert prefix is None
    assert message[0].startswith("Current question: How many elements?")
    assert "files below" in message[0]
    assert message[1].startswith("--- File 1: ")
    assert len(built) == 1  # queued for next time
    assert ans.sources_used == [str(doc)]  # "1" resolved to the path

    monkeypatch.setattr(kv, "slot_exists", lambda *a: True)
    agent = FakeAgent()
    asyncio.run(answer_question(agent, "How many elements?", [str(doc)]))
    message, prefix = agent.calls[0]
    assert message[0].startswith("--- File 1: ")
    assert prefix == message[0] + "\n\n"
    assert "files above" in message[1]

