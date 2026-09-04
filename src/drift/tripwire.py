"""Production self-check for the prompt budget.

After every local chat completion, the transport (src/inference/local_llm.py)
predicts what the prompt SHOULD have cost - text counted exactly by
llama-server's /tokenize, images by the mirrored llama.cpp tiling math -
and compares it with the `usage.prompt_tokens` the same server reported.
With text exact, any residual gap IS the image math (plus a few dozen
tokens of chat-template framing), so the day an upstream change moves the
tiling, the first few vision queries log it - not an eval three weeks
later, and not an HTTP 400 in front of a user.

A trip is `actual - expected > ABS_MARGIN + REL_MARGIN * expected`: the
absolute part absorbs template framing on tiny prompts, the relative part
keeps the bar meaningful on 10K-token prompts (a 20% under-count on one
1,000-token image is ~200 tokens, which clears the margin at any prompt
size the context window allows). The first cut used a flat 1.10x ratio
over a prediction that already over-counted text by 600-1,500 tokens - a
tripwire that could only catch catastrophes.

Trips go to stderr and to <APP_DATA_DIR>/drift/tripwires.jsonl; in-process
counters feed /status. Nothing here raises.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from typing import Optional

from src.drift.provenance import DRIFT_DIR

ABS_MARGIN = 64      # chat-template framing, BOS/EOS, the odd role token
REL_MARGIN = 0.01    # tokenizer/estimator rounding at scale
LOG_PATH = DRIFT_DIR / "tripwires.jsonl"

_lock = threading.Lock()
_state: dict = {"checks": 0, "trips": 0, "last_trip": None, "max_excess": 0}


def margin(expected: int) -> int:
    return int(ABS_MARGIN + REL_MARGIN * expected)


def record(
    expected: Optional[int],
    actual: Optional[int],
    *,
    context: str = "answer",
    exact_text: bool = True,
) -> bool:
    """Compare a predicted prompt-token count with the server-reported one.
    Returns True when the prediction was exceeded by more than the margin.
    `exact_text=False` (the /tokenize fallback path) widens the margin 5x -
    a chars-per-token guess cannot support a tight bar."""
    if not expected or not actual or expected <= 0:
        return False
    excess = actual - expected
    allowed = margin(expected) * (1 if exact_text else 5)
    tripped = excess > allowed
    with _lock:
        _state["checks"] += 1
        _state["max_excess"] = max(_state["max_excess"], excess)
        if tripped:
            _state["trips"] += 1
            rec = {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "context": context,
                "expected": int(expected),
                "actual": int(actual),
                "excess": int(excess),
                "allowed": int(allowed),
                "exact_text": exact_text,
            }
            _state["last_trip"] = rec
    if tripped:
        print(
            f"  drift: prompt budget under-predicted - expected ~{expected} tokens, "
            f"llama-server counted {actual} (+{excess}, allowed +{allowed}). The image "
            f"token math may have drifted from the installed llama.cpp; run "
            f"`just check-drift`.",
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
            "max_excess": _state["max_excess"],
            "last_trip": _state["last_trip"],
            "log": str(LOG_PATH),
        }


def _reset_for_tests() -> None:
    with _lock:
        _state.update({"checks": 0, "trips": 0, "last_trip": None, "max_excess": 0})
