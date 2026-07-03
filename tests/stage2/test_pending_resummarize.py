"""Tests for Stage 2 ingest's tolerance of `clean-stale-summaries` intermediate state.

`just clean-stale-summaries` clears `summary_file`/`summarized_at`/`ingested_at`
on rows whose markdowns went missing, so the walker re-summarizes them on the
next run. Stage 2 ingest used to hard-error on this state ("the router did not
produce a summary for it"), blocking every other valid row from pushing.

Now Stage 2 logs a single rollup line and skips those rows — they get picked
up automatically when the user runs `python -m src.ingest <root>` next.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src import manifest as manifest_mod
from src.manifest import Entry, Manifest


@pytest.fixture
def isolated_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mpath = tmp_path / "_manifest.json"
    monkeypatch.setattr(manifest_mod, "DEFAULT_MANIFEST_PATH", mpath)
    monkeypatch.setattr(Manifest.__init__, "__defaults__", (mpath,))
    return mpath


def test_pending_rows_are_skipped_not_raised(isolated_manifest, capsys):
    """Rows with summary_file=None / fast_indexed_at=None / skip_reason=None
    used to RAISE; now they warn-and-skip so other rows can still push."""
    from src.stage2.__main__ import ingest_from_manifest

    m = Manifest()
    # One row in "pending re-summarization" state (the clean_missing_summaries
    # output)
    m.entries["pending.pdf"] = Entry(
        size=100,
        summary_file=None,
        summarized_at="",
        ingested_at=None,
    )
    m.save()

    # Mock out everything Qdrant-related so we don't need a server
    with patch("src.stage2.db.create_collection"), \
         patch("src.stage2.db.upsert_summaries", return_value=0) as mock_upsert, \
         patch("src.stage2.db.get_all_point_ids", return_value=set()), \
         patch("src.stage2.db.delete_points", return_value=0):
        # Should NOT raise
        stats = ingest_from_manifest(force=False)

    out = capsys.readouterr()
    # Helpful warning printed, with the recovery instruction
    assert "pending re-summarization" in out.err
    assert "python -m src.ingest" in out.err
    # Nothing was upserted (the only row was skipped)
    mock_upsert.assert_not_called()
    assert stats["upserted"] == 0


def test_pending_rows_dont_block_valid_rows(
    isolated_manifest, tmp_path, capsys, monkeypatch
):
    """A pending row alongside a valid one — valid one still pushes."""
    from src.stage2.__main__ import ingest_from_manifest

    # Set up REPO_ROOT so summary_file resolves under tmp_path
    monkeypatch.setattr(manifest_mod, "REPO_ROOT", tmp_path)

    summary_dir = tmp_path / "Test Summaries"
    summary_dir.mkdir()
    real_summary = summary_dir / "good.md"
    real_summary.write_text(
        "Source: real.pdf\n\n# Real Doc\n\nSome content.\n\n"
        "**Content type:** pdf\n\n**Keywords:** —\n\n"
        "**Key entities:** —\n\n**Identifiers:** —\n",
        encoding="utf-8",
    )

    m = Manifest()
    # Pending (broken) row
    m.entries["pending.pdf"] = Entry(size=100, summary_file=None)
    # Valid row with a real summary on disk
    m.entries["real.pdf"] = Entry(
        size=200, summary_file="Test Summaries/good.md",
    )
    m.save()

    with patch("src.stage2.db.create_collection"), \
         patch("src.stage2.db.upsert_summaries", return_value=1) as mock_upsert, \
         patch("src.stage2.db.get_all_point_ids", return_value=set()), \
         patch("src.stage2.db.delete_points", return_value=0):
        stats = ingest_from_manifest(force=False)

    # The valid row got upserted; the pending row was skipped with a warning
    assert mock_upsert.call_count == 1
    upserted_summaries = mock_upsert.call_args.args[0]
    paths = [s.source_path for s in upserted_summaries]
    assert "real.pdf" in paths
    assert "pending.pdf" not in paths

    out = capsys.readouterr()
    assert "pending re-summarization" in out.err


def test_no_warning_when_no_pending_rows(isolated_manifest, capsys):
    """No spurious warning when every row is in a valid state."""
    from src.stage2.__main__ import ingest_from_manifest

    m = Manifest()
    # Skip-only row (router said skip — different intermediate state)
    m.entries["thumb.png"] = Entry(size=100, skip_reason="thumbnail")
    m.save()

    with patch("src.stage2.db.create_collection"), \
         patch("src.stage2.db.upsert_summaries", return_value=0), \
         patch("src.stage2.db.get_all_point_ids", return_value=set()), \
         patch("src.stage2.db.delete_points", return_value=0):
        ingest_from_manifest(force=False)

    out = capsys.readouterr()
    assert "pending re-summarization" not in out.err
