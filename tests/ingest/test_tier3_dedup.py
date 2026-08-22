"""Tests for Phase A T3 content-hash dedup.

Concrete proof of behavior:
  - Two byte-identical files should fire the LLM exactly once.
  - The second file's TierOutcome should report deduped=True.
  - Both files should land at the same `<digest>_t3.md` summary path.
  - The cross-walk path (summary already on disk) should also fire 0 LLMs.

Without dedup, both files would fire the LLM (the second overwriting the
first's identical output). Phase A short-circuits the second call.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.ingest import tier3
from src.ingest.common import SUMMARIES_DIR, hash_file
from src.stage1.summarize import FileSummary


def _make_fake_agent(summary_text: str = "stub summary"):
    """A ChatAgent stand-in whose .run() returns a parsed FileSummary.
    The mock counts calls so we can assert the LLM fired once vs twice.
    """
    agent = AsyncMock()
    agent.run = AsyncMock(return_value=FileSummary(
        title="Stub",
        summary=summary_text,
        keywords=["stub"],
        key_entities=[],
        identifiers=[],
        content_type="text",
    ))
    agent.run_sync = lambda *a, **kw: agent.run.return_value
    return agent


def _patch_run_with_retry(monkeypatch, agent):
    """Replace `_run_with_retry` so the test doesn't need a real LLM client.

    Returns a list that gets appended to once per call — assert against len().
    """
    calls: list[str] = []

    async def fake_retry(_agent, message, name):
        calls.append(name)
        return await agent.run([message])

    monkeypatch.setattr(tier3, "_run_with_retry", fake_retry)
    return calls


def test_dedup_two_identical_files_one_llm_call(tmp_path: Path, monkeypatch):
    """Two paths, identical bytes → exactly ONE LLM call."""
    fake_summaries = tmp_path / "Test Summaries"
    fake_summaries.mkdir()
    monkeypatch.setattr(tier3, "SUMMARIES_DIR", fake_summaries)

    payload = b"This is a test PDF stand-in. Content is identical between file A and B."
    file_a = tmp_path / "A.txt"
    file_b = tmp_path / "B.txt"
    file_a.write_bytes(payload)
    file_b.write_bytes(payload)
    assert hash_file(file_a) == hash_file(file_b)

    agent = _make_fake_agent()
    calls = _patch_run_with_retry(monkeypatch, agent)

    async def go():
        inflight: dict[str, asyncio.Event] = {}
        inflight_lock = asyncio.Lock()
        outcome_a = await tier3.run_async(
            file_a, "A.txt", agent,
            inflight=inflight, inflight_lock=inflight_lock,
        )
        outcome_b = await tier3.run_async(
            file_b, "B.txt", agent,
            inflight=inflight, inflight_lock=inflight_lock,
        )
        return outcome_a, outcome_b

    outcome_a, outcome_b = asyncio.run(go())

    assert len(calls) == 1, f"expected 1 LLM call, got {len(calls)}: {calls}"
    assert outcome_a.deduped is False
    assert outcome_b.deduped is True
    assert outcome_a.summary_file_rel == outcome_b.summary_file_rel
    assert outcome_a.content_hash == outcome_b.content_hash


def test_dedup_concurrent_two_workers_one_llm_call(tmp_path: Path, monkeypatch):
    """Two workers racing on the same digest → still one LLM call.

    First to acquire the inflight_lock claims the digest. The second
    awaits the Event and reuses the on-disk summary the first wrote.
    """
    fake_summaries = tmp_path / "Test Summaries"
    fake_summaries.mkdir()
    monkeypatch.setattr(tier3, "SUMMARIES_DIR", fake_summaries)

    payload = b"Identical content for the concurrency race test."
    file_a = tmp_path / "A.txt"
    file_b = tmp_path / "B.txt"
    file_a.write_bytes(payload)
    file_b.write_bytes(payload)

    agent = _make_fake_agent()
    calls = _patch_run_with_retry(monkeypatch, agent)

    # Make _do_summarize sleep briefly inside the LLM call so the second
    # worker definitely arrives while the first is still computing.
    real_do_summarize = tier3._do_summarize

    async def slow_do_summarize(*args, **kwargs):
        await asyncio.sleep(0.05)
        return await real_do_summarize(*args, **kwargs)

    monkeypatch.setattr(tier3, "_do_summarize", slow_do_summarize)

    async def go():
        inflight: dict[str, asyncio.Event] = {}
        inflight_lock = asyncio.Lock()
        return await asyncio.gather(
            tier3.run_async(file_a, "A.txt", agent, inflight=inflight, inflight_lock=inflight_lock),
            tier3.run_async(file_b, "B.txt", agent, inflight=inflight, inflight_lock=inflight_lock),
        )

    outcomes = asyncio.run(go())
    assert len(calls) == 1, f"expected 1 LLM call, got {len(calls)}: {calls}"
    deduped = [o for o in outcomes if o.deduped]
    assert len(deduped) == 1


def test_dedup_cross_walk_existing_file(tmp_path: Path, monkeypatch):
    """Summary already on disk from a previous walk → 0 LLM calls."""
    fake_summaries = tmp_path / "Test Summaries"
    fake_summaries.mkdir()
    monkeypatch.setattr(tier3, "SUMMARIES_DIR", fake_summaries)

    payload = b"This file was processed in a previous walk."
    file_a = tmp_path / "A.txt"
    file_a.write_bytes(payload)

    # Pretend a prior walk already wrote the summary at `<digest>_t3.md`.
    digest = hash_file(file_a)
    pre_existing = fake_summaries / f"{digest}_t3.md"
    pre_existing.write_text("Source: A.txt\n\n# old summary\n", encoding="utf-8")

    agent = _make_fake_agent()
    calls = _patch_run_with_retry(monkeypatch, agent)

    async def go():
        inflight: dict[str, asyncio.Event] = {}
        inflight_lock = asyncio.Lock()
        return await tier3.run_async(
            file_a, "A.txt", agent,
            inflight=inflight, inflight_lock=inflight_lock,
        )

    outcome = asyncio.run(go())
    assert len(calls) == 0
    assert outcome.deduped is True
    assert outcome.content_hash == digest


def test_no_dedup_without_inflight(tmp_path: Path, monkeypatch):
    """Backward compatibility: legacy callers (no inflight kwargs) get the old behavior."""
    fake_summaries = tmp_path / "Test Summaries"
    fake_summaries.mkdir()
    monkeypatch.setattr(tier3, "SUMMARIES_DIR", fake_summaries)

    payload = b"Two identical files but the caller didn't pass inflight."
    file_a = tmp_path / "A.txt"
    file_b = tmp_path / "B.txt"
    file_a.write_bytes(payload)
    file_b.write_bytes(payload)

    agent = _make_fake_agent()
    calls = _patch_run_with_retry(monkeypatch, agent)

    async def go():
        await tier3.run_async(file_a, "A.txt", agent)
        await tier3.run_async(file_b, "B.txt", agent)

    asyncio.run(go())
    assert len(calls) == 2
