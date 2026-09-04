"""The tripwire compares predicted vs server-reported prompt tokens, trips
past an absolute+relative margin, logs to jsonl, counts, and never raises."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.drift import tripwire


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tripwire, "LOG_PATH", tmp_path / "tripwires.jsonl")
    monkeypatch.setattr(tripwire, "DRIFT_DIR", tmp_path)
    tripwire._reset_for_tests()
    yield
    tripwire._reset_for_tests()


def test_margin_is_absolute_plus_relative() -> None:
    assert tripwire.margin(0) == tripwire.ABS_MARGIN
    assert tripwire.margin(10_000) == tripwire.ABS_MARGIN + 100


def test_within_margin_does_not_trip(tmp_path: Path) -> None:
    assert tripwire.record(1000, 1000 + tripwire.margin(1000)) is False
    s = tripwire.summary()
    assert s["checks"] == 1 and s["trips"] == 0
    assert not (tmp_path / "tripwires.jsonl").exists()


def test_over_margin_trips_logs_and_counts(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert tripwire.record(1000, 1000 + tripwire.margin(1000) + 1, context="unit") is True
    s = tripwire.summary()
    assert (s["checks"], s["trips"]) == (1, 1)
    assert s["last_trip"]["context"] == "unit"
    rec = json.loads((tmp_path / "tripwires.jsonl").read_text(encoding="utf-8").strip())
    assert rec["excess"] == rec["allowed"] + 1 and rec["exact_text"] is True
    assert "under-predicted" in capsys.readouterr().err


def test_twenty_percent_image_undercount_trips_at_scale() -> None:
    """The reviewer's bar: ~10K chars of text (exact) + one 1,000-token image
    the estimator under-counts by 20% must trip - at any prompt size the
    window allows."""
    for text_tokens in (2_500, 10_000, 13_000):
        expected = text_tokens + 1_000
        actual = text_tokens + 1_200 + 30      # true image cost + framing
        assert tripwire.record(expected, actual) is True, text_tokens


def test_framing_alone_never_trips() -> None:
    # exact text, exact images, ~30 tokens of chat template on a tiny prompt
    assert tripwire.record(120, 150) is False


def test_estimated_text_widens_the_margin() -> None:
    assert tripwire.record(1000, 1000 + tripwire.margin(1000) + 50, exact_text=True) is True
    assert tripwire.record(1000, 1000 + tripwire.margin(1000) + 50, exact_text=False) is False


def test_missing_values_are_ignored() -> None:
    assert tripwire.record(None, 500) is False
    assert tripwire.record(500, None) is False
    assert tripwire.record(0, 500) is False
    assert tripwire.summary()["checks"] == 0


def test_max_excess_tracks_worst_case() -> None:
    tripwire.record(100, 105)
    tripwire.record(100, 150)
    tripwire.record(100, 120)
    assert tripwire.summary()["max_excess"] == 50


def test_unwritable_log_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(tripwire, "DRIFT_DIR", blocker)
    monkeypatch.setattr(tripwire, "LOG_PATH", blocker / "tripwires.jsonl")
    assert tripwire.record(100, 300) is True  # tripped, logged nowhere, no exception
