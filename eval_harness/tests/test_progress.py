"""Progress sidecar: must report faithfully and must NEVER hurt a run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / "harness"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for p in (str(HARNESS), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import progress  # noqa: E402
from eval_watch import _LOG_NAME, _RUN_ID, tail_bytes  # noqa: E402


def _read(raw: Path) -> dict:
    return json.loads((raw / "progress.json").read_text(encoding="utf-8"))


def test_update_creates_and_merges_phases(tmp_path: Path) -> None:
    progress.update(tmp_path, run_id="r1", status="running")
    progress.update(tmp_path, phase="answer", done=0, total=120)
    progress.update(tmp_path, done=37, current="rcpt-05-typed")
    state = _read(tmp_path)
    assert state["run_id"] == "r1"
    assert state["phase"] == "answer"
    rec = state["phases"]["answer"]
    assert (rec["done"], rec["total"], rec["current"]) == (37, 120, "rcpt-05-typed")
    assert rec["state"] == "running"


def test_phase_transition_closes_previous_phase(tmp_path: Path) -> None:
    progress.update(tmp_path, phase="answer", done=120, total=120)
    progress.update(tmp_path, phase="retrieve", done=0, total=120)
    state = _read(tmp_path)
    assert state["phases"]["answer"]["state"] == "done"
    assert state["phases"]["retrieve"]["state"] == "running"
    assert state["phase"] == "retrieve"


def test_phase_done_records_extras(tmp_path: Path) -> None:
    progress.update(tmp_path, phase="index")
    progress.phase_done(tmp_path, "index", manifest_entries=545)
    rec = _read(tmp_path)["phases"]["index"]
    assert rec["state"] == "done"
    assert rec["manifest_entries"] == 545


def test_corrupt_file_is_replaced_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "progress.json").write_text("{half a json", encoding="utf-8")
    progress.update(tmp_path, phase="enrich")
    assert _read(tmp_path)["phase"] == "enrich"


def test_no_tmp_droppings(tmp_path: Path) -> None:
    progress.update(tmp_path, phase="answer", done=1, total=2)
    assert [p.name for p in tmp_path.iterdir()] == ["progress.json"]


def test_never_raises_even_when_unwritable(tmp_path: Path) -> None:
    # a FILE where the dir should be — mkdir/replace must fail internally
    target = tmp_path / "raw"
    target.write_text("i am a file, not a directory", encoding="utf-8")
    progress.update(target / "sub")  # must swallow, not raise
    progress.phase_done(target / "sub", "answer")
    progress.write_latest(target / "sub", "r1")


def test_write_latest(tmp_path: Path) -> None:
    progress.write_latest(tmp_path, "20260830T-foo")
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "20260830T-foo"


# ---- eval_watch server helpers ------------------------------------------


def test_tail_bytes_returns_exactly_the_tail(tmp_path: Path) -> None:
    log = tmp_path / "w.log"
    log.write_bytes(b"A" * 1000 + b"THE-END")
    assert tail_bytes(log, 7) == b"THE-END"
    assert tail_bytes(log, 10_000) == log.read_bytes()  # n > size = whole file
    assert tail_bytes(log, 0) == b""


def test_tail_bytes_caps_request_size(tmp_path: Path) -> None:
    log = tmp_path / "w.log"
    log.write_bytes(b"x" * 100)
    assert len(tail_bytes(log, 10**9)) == 100  # capped, no OverflowError


def test_route_validators_reject_traversal() -> None:
    assert _RUN_ID.match("20260830T095758Z-custom_dataset_rahul_Aug30-x")
    assert not _RUN_ID.match("../../etc")
    assert not _RUN_ID.match("a/b")
    assert _LOG_NAME.match("worker_answer.log")
    assert not _LOG_NAME.match("../run.json")
    assert not _LOG_NAME.match("worker_answer.log/../x")
    assert not _LOG_NAME.match("run.json")
