"""Production self-check for the prompt budget.

`answer.py` predicts how many tokens a prompt will cost (text by chars,
images by the mirrored llama.cpp tiling math) and trims files to fit the
context window on that prediction. llama-server then reports the REAL
count in `usage.prompt_tokens` on every response. Comparing the two on
every request turns ordinary usage into a continuous calibration: the day
an upstream change moves the token math, the first few queries log it -
not an eval three weeks later, and not an HTTP 400 in front of a user.

Trips (actual > predicted * RATIO) go to stderr and to
<APP_DATA_DIR>/drift/tripwires.jsonl; in-process counters feed /status.
Nothing here raises.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from typing import Optional

from src.drift.provenance import DRIFT_DIR

RATIO = 1.10
LOG_PATH = DRIFT_DIR / "tripwires.jsonl"

_lock = threading.Lock()
_state: dict = {"checks": 0, "trips": 0, "last_trip": None, "max_ratio": 0.0}


def record(expected: Optional[int], actual: Optional[int], *, context: str = "answer") -> bool:
    """Compare a predicted prompt-token count with the server-reported one.
    Returns True when the prediction was exceeded by more than RATIO."""
    if not expected or not actual or expected <= 0:
        return False
    ratio = actual / expected
    tripped = ratio > RATIO
    with _lock:
        _state["checks"] += 1
        _state["max_ratio"] = max(_state["max_ratio"], ratio)
        if tripped:
            _state["trips"] += 1
            rec = {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "context": context,
                "expected": int(expected),
                "actual": int(actual),
                "ratio": round(ratio, 3),
            }
            _state["last_trip"] = rec
    if tripped:
        print(
            f"  drift: prompt budget under-predicted - expected ~{expected} tokens, "
            f"llama-server counted {actual} ({ratio:.2f}x). The image/text token "
            f"math may have drifted from the installed llama.cpp; run `just check-drift`.",
            file=sys.stderr,
        )
        _append(rec)
    return tripped


def _append(rec: dict) -> None:
    try:
        DRIFT_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def summary() -> dict:
    with _lock:
        return {
            "checks": _state["checks"],
            "trips": _state["trips"],
            "max_ratio": round(_state["max_ratio"], 3),
            "last_trip": _state["last_trip"],
            "log": str(LOG_PATH),
        }


def _reset_for_tests() -> None:
    with _lock:
        _state.update({"checks": 0, "trips": 0, "last_trip": None, "max_ratio": 0.0})
