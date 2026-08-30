"""Tests for tier1's CSV LLM-summarization path (Plan #17 Part A).

These verify the sampling logic + the dedup short-circuits without making
real LLM calls. Real-LLM tests live under `tests/inference/` (gated by
RUN_LOCAL_LLM_INTEGRATION_TESTS=1).
"""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import pytest

from src.ingest.tier1 import (
    CSV_SAMPLE_MAX_CHARS,
    CSV_SAMPLE_MAX_ROWS,
    _csv_sample,
    run_csv_async,
)


# ---------------------------------------------------------------------------
# _csv_sample
# ---------------------------------------------------------------------------

def _write_csv(tmp_path: Path, rows: list[list[str]]) -> Path:
    p = tmp_path / "test.csv"
    with p.open("w", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)
    return p


def test_csv_sample_keeps_header_first(tmp_path):
    p = _write_csv(tmp_path, [
        ["id", "name", "score"],
        ["1", "alice", "100"],
        ["2", "bob", "92"],
    ])
    text, n_rows = _csv_sample(p)
    lines = text.splitlines()
    assert lines[0] == "id,name,score"
    assert n_rows == 2


def test_csv_sample_caps_rows(tmp_path):
    rows = [["c1"]] + [[f"row{i}"] for i in range(100)]
    p = _write_csv(tmp_path, rows)
    _, n_rows = _csv_sample(p, max_rows=5, max_chars=10_000)
    assert n_rows == 5


def test_csv_sample_caps_chars_for_wide_rows(tmp_path):
    """Wide CSVs (many columns / long values) should hit the char cap
    before the row cap."""
    rows = [["col"]] + [["x" * 200] for _ in range(50)]
    p = _write_csv(tmp_path, rows)
    text, n_rows = _csv_sample(p, max_rows=50, max_chars=500)
    # Header + first row alone is ~210 chars, so we expect ~2-3 rows.
    assert n_rows < 50
    assert len(text) <= 500 + 200  # generous: cap is approximate (per-line check)


def test_csv_sample_unreadable_returns_empty(tmp_path):
    text, n_rows = _csv_sample(tmp_path / "does-not-exist.csv")
    assert text == ""
    assert n_rows == 0


def test_csv_sample_default_caps_match_constants(tmp_path):
    p = _write_csv(tmp_path, [["c"]] + [["v"] for _ in range(50)])
    _, n_rows = _csv_sample(p)
    # Defaults: cap at CSV_SAMPLE_MAX_ROWS rows.
    assert n_rows == CSV_SAMPLE_MAX_ROWS
    assert CSV_SAMPLE_MAX_CHARS == 1000  # documented value


# ---------------------------------------------------------------------------
# run_csv_async (mocked agent — no real LLM)
# ---------------------------------------------------------------------------

class _FakeAgent:
    """Minimal stand-in for ChatAgent[FileSummary]. Returns a canned summary
    that exercises every render_markdown branch (keywords, entities,
    identifiers all populated)."""

    def __init__(self):
        self.calls: list[list] = []

    async def run(self, message, *, thinking=False):
        self.calls.append(message)
        from src.stage1.summarize import FileSummary
        return FileSummary(
            title="Test Catalog",
            summary="A small catalog of test rows.",
            content_type="other",
            keywords=["test", "catalog"],
            key_entities=["Test"],
            identifiers=["catalog.csv"],
        )

    def run_sync(self, message, *, thinking=False):
        return asyncio.get_event_loop().run_until_complete(self.run(message))


@pytest.fixture
def reloaded_data_dir(tmp_path, monkeypatch):
    """Set MAGPIE_DATA_DIR + reload modules that snapshot APP_DATA_DIR at
    import time, so the test's tmp_path is what the tier sees.

    MUST reload BACK on teardown: the old helper left src.manifest pointed
    at the (deleted) tmp dir for the rest of the session, which made
    unrelated later tests construct empty Manifests (order-dependent
    failures in stage2/test_pending_resummarize - triage 2026-08-30)."""
    import importlib, src.manifest, src.ingest.common, src.ingest.tier1
    mods = (src.manifest, src.ingest.common, src.ingest.tier1)
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(tmp_path))
    for mod in mods:
        importlib.reload(mod)
    yield tmp_path
    monkeypatch.undo()
    for mod in mods:
        importlib.reload(mod)


def test_run_csv_async_writes_real_summary(tmp_path, monkeypatch, reloaded_data_dir):
    """The summary markdown body should contain the LLM-rendered FileSummary
    (title, summary, keywords, key entities, identifiers) — NOT raw CSV
    bytes like the old T1 path."""
    p = _write_csv(tmp_path, [
        ["id", "name", "dept"],
        ["1", "alice", "physics"],
        ["2", "bob", "chemistry"],
    ])

    import src.manifest
    from src.ingest.tier1 import run_csv_async as run_csv_reloaded

    agent = _FakeAgent()
    outcome = asyncio.run(run_csv_reloaded(p, "test.csv", agent))

    assert outcome.summary_file_rel is not None
    assert outcome.content_hash is not None
    assert not outcome.deduped

    # Agent saw the sample (header + the two rows).
    assert len(agent.calls) == 1
    sample_text = agent.calls[0][1]
    assert "id,name,dept" in sample_text
    assert "alice" in sample_text

    # Summary markdown contains the LLM-rendered FileSummary, not raw CSV
    # bytes. (`render_markdown` formats sections like "**Keywords:**".)
    summary_path = src.manifest.APP_DATA_DIR / outcome.summary_file_rel
    body = summary_path.read_text(encoding="utf-8")
    assert "Test Catalog" in body
    assert "A small catalog of test rows." in body
    assert "test" in body  # keywords rendered
    # Negative: raw rows should NOT appear verbatim in the summary body.
    assert "alice,physics" not in body


def test_run_csv_async_dedup_existing_summary(tmp_path, monkeypatch, reloaded_data_dir):
    """If `<digest>_t1.md` already exists, skip the LLM call entirely
    and return a deduped outcome."""
    p = _write_csv(tmp_path, [["c"], ["v"]])
    agent = _FakeAgent()

    from src.ingest.tier1 import run_csv_async as run_csv_reloaded

    # First call: real run.
    out1 = asyncio.run(run_csv_reloaded(
        p, "test.csv", agent,
        inflight={}, inflight_lock=asyncio.Lock(),
    ))
    assert not out1.deduped
    assert len(agent.calls) == 1

    # Second call (same content, fresh inflight map): hits the on-disk
    # dedup short-circuit; no new LLM call.
    out2 = asyncio.run(run_csv_reloaded(
        p, "test.csv", agent,
        inflight={}, inflight_lock=asyncio.Lock(),
    ))
    assert out2.deduped
    assert len(agent.calls) == 1  # unchanged
    assert out2.content_hash == out1.content_hash
