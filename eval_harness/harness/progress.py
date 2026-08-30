"""Live-progress sidecar: the harness writes the truth as data, a dumb page
renders it. No Claude, no tqdm scraping, no terminal parsing.

Every long-running loop (run.py phase transitions, worker answer/retrieve
questions, judge start/end) calls `update()`, which read-merge-writes
`<run>/raw/progress.json` atomically. `write_latest()` maintains
`eval_harness/runs/latest.json` so the watch page can find the current run
without being told. Both files are gitignored (raw/ wholesale; latest.json
by name).

Contract: progress reporting must NEVER take a run down. Every public
function swallows every exception — a full disk or a permissions quirk
costs the progress bar, not the eval.

Writers are sequential by construction (run.py and the phase worker are
different processes but never write concurrently; the judge runs after),
so read-modify-write with an atomic rename is race-free in practice.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROGRESS_NAME = "progress.json"
LATEST_NAME = "latest.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile in the same dir so os.replace stays same-filesystem
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt = start fresh
        return {}


def update(
    raw_dir: Path | str,
    *,
    phase: str | None = None,
    done: int | None = None,
    total: int | None = None,
    current: str | None = None,
    status: str | None = None,
    note: str | None = None,
    run_id: str | None = None,
) -> None:
    """Merge one progress observation into `<raw_dir>/progress.json`.

    `phase` names the stage now running (index/answer/retrieve/enrich/judge);
    `done`/`total` are its counters when the loop is countable, absent when
    indeterminate (index, judge). `status` is run-level (running/complete/
    failed). Per-phase history accumulates under "phases" with first/last
    timestamps so the page can show wall-clock per stage.
    """
    try:
        raw = Path(raw_dir)
        path = raw / PROGRESS_NAME
        state = _load(path)
        now = _now()
        state["updated_utc"] = now
        state.setdefault("started_utc", now)
        if run_id is not None:
            state["run_id"] = run_id
        if status is not None:
            state["status"] = status
        if phase is not None:
            prev = state.get("phase")
            state["phase"] = phase
            phases: dict[str, Any] = state.setdefault("phases", {})
            rec = phases.setdefault(phase, {"first_utc": now})
            rec["last_utc"] = now
            if prev and prev != phase and prev in phases:
                # a new phase starting implies the old one ended; only a
                # still-"running" record flips (explicit states are kept)
                if phases[prev].get("state") == "running":
                    phases[prev]["state"] = "done"
            rec["state"] = "running"
        target = state.get("phase")
        if target and target in state.get("phases", {}):
            rec = state["phases"][target]
            rec["last_utc"] = now
            if done is not None:
                rec["done"] = int(done)
            if total is not None:
                rec["total"] = int(total)
            if current is not None:
                rec["current"] = str(current)
            if note is not None:
                rec["note"] = str(note)
        _atomic_write_json(path, state)
    except Exception:  # noqa: BLE001 — see module docstring
        pass


def phase_done(raw_dir: Path | str, phase: str, **extra: Any) -> None:
    """Mark `phase` finished (state=done) and record any extra fields."""
    try:
        raw = Path(raw_dir)
        path = raw / PROGRESS_NAME
        state = _load(path)
        now = _now()
        state["updated_utc"] = now
        rec = state.setdefault("phases", {}).setdefault(phase, {"first_utc": now})
        rec["last_utc"] = now
        rec["state"] = "done"
        for k, v in extra.items():
            rec[k] = v
        _atomic_write_json(path, state)
    except Exception:  # noqa: BLE001
        pass


def write_latest(runs_dir: Path | str, run_id: str) -> None:
    """Point `runs/latest.json` at the run that most recently started."""
    try:
        runs = Path(runs_dir)
        _atomic_write_json(runs / LATEST_NAME, {
            "run_id": run_id,
            "updated_utc": _now(),
        })
    except Exception:  # noqa: BLE001
        pass
