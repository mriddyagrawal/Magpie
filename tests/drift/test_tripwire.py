"""The tripwire compares predicted vs server-reported prompt tokens, trips
above RATIO, logs to jsonl, counts, and never raises."""

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


def test_within_ratio_does_not_trip(tmp_path: Path) -> None:
    assert tripwire.record(1000, 1050) is False
    s = tripwire.summary()
    assert s["checks"] == 1 and s["trips"] == 0
    assert not (tmp_path / "tripwires.jsonl").exists()


def test_over_ratio_trips_logs_and_counts(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert tripwire.record(1000, 1200, context="unit") is True
    s = tripwire.summary()
    assert (s["checks"], s["trips"]) == (1, 1)
    assert s["last_trip"]["actual"] == 1200 and s["last_trip"]["context"] == "unit"
    line = (tmp_path / "tripwires.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["ratio"] == 1.2
    assert "under-predicted" in capsys.readouterr().err


def test_exact_ratio_boundary() -> None:
    assert tripwire.record(1000, 1100) is False   # == RATIO is not a trip
    assert tripwire.record(1000, 1101) is True


def test_missing_values_are_ignored() -> None:
    assert tripwire.record(None, 500) is False
    assert tripwire.record(500, None) is False
    assert tripwire.record(0, 500) is False
    assert tripwire.summary()["checks"] == 0


def test_max_ratio_tracks_worst_case() -> None:
    tripwire.record(100, 105)
    tripwire.record(100, 150)
    tripwire.record(100, 120)
    assert tripwire.summary()["max_ratio"] == 1.5


def test_unwritable_log_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(tripwire, "DRIFT_DIR", blocker)
    monkeypatch.setattr(tripwire, "LOG_PATH", blocker / "tripwires.jsonl")
    assert tripwire.record(100, 200) is True  # tripped, logged nowhere, no exception
