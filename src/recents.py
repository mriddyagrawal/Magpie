"""Recents store — the user's last N questions, with cached answers.

Lives at `<APP_DATA_DIR>/recents.json`. Backs the ask bar's "RECENT" panel
(see `Specs/UI/ask_bar.md`). Re-firing a recent renders the cached payload
instantly without a fresh LLM call — the renderer treats a cached entry
exactly like a freshly-returned `Answer`.

Storage shape (newest-first JSON array):

    [
      {
        "id": "rec_abc123",
        "asked_at": "2026-05-07T22:42:00-04:00",
        "question": "who is the chair of the math department?",
        "rewritten_query": "math department chair faculty",
        "result": {
          "answer": "...",
          "sources_used": [...],
          "not_found": false,
          "not_found_topic": ""
        }
      },
      ...
    ]

Why we persist the `result` payload (not just the question):
  - Replays cost zero LLM tokens.
  - The user's typing-state UI needs the question text + timestamp;
    re-firing needs the answer text + sources to re-render the answer
    card.
  - Storing the rewritten_query is a free debugging signal — it's
    already computed during the original ask, and persisting it lets us
    correlate "this rewrite got a hit, this one didn't" later without
    re-running the pipeline.

v1 design notes:
  - Cap at MAX_STORED entries (oldest evicted on append).
  - No filtering by typed input — the ask bar always shows the last N.
  - Staleness: re-firing a recent renders the cached answer even if
    underlying files have changed since. Acceptable because the user
    can always re-type the question to force a fresh pipeline run.
  - Single-process write; no locking. Concurrent writers (e.g., two
    Magpie instances pointing at the same APP_DATA_DIR) would race,
    but the single-instance Tauri plugin prevents this in production.
"""

from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.answer import Answer
from src.manifest import APP_DATA_DIR

RECENTS_FILENAME = "recents.json"
MAX_STORED = 10
"""How many entries to persist on disk. Older entries evict on append.
The UI shows fewer (currently last 4 — see ask_bar.md). Storing more
than we show gives us headroom to expose more later without a data
migration."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class RecentEntry(BaseModel):
    """One persisted ask. Mirrors the answer pipeline's structured output
    so re-firing the recent rehydrates the answer card byte-for-byte."""

    id: str
    """Stable identifier. Format: `rec_<12 hex chars>`."""

    asked_at: str
    """ISO-8601 timestamp with timezone (e.g. `2026-05-07T22:42:00-04:00`)."""

    question: str
    """Raw user input as typed in the ask bar."""

    rewritten_query: str | None = None
    """The rewriter's output for retrieval, if rewriting was used. Stored
    for debugging / analytics — not displayed to the user. None when
    rewriting was disabled or skipped."""

    result: Answer
    """The answer payload at the time the question was asked. Includes
    `not_found` etc. — replays render whichever state was cached."""


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def recents_path() -> Path:
    return APP_DATA_DIR / RECENTS_FILENAME


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_recents() -> list[RecentEntry]:
    """Return all persisted recents, newest-first. Returns [] if the file
    doesn't exist or is unreadable / malformed (defensive — ask bar must
    keep working even if recents.json is corrupt)."""
    path = recents_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  warn: recents.json unreadable, returning empty list: {e}",
              file=sys.stderr)
        return []
    if not isinstance(raw, list):
        print(f"  warn: recents.json is not a list (got {type(raw).__name__}); "
              f"returning empty list", file=sys.stderr)
        return []
    out: list[RecentEntry] = []
    for item in raw:
        try:
            out.append(RecentEntry.model_validate(item))
        except ValidationError as e:
            # Skip individual bad entries rather than failing the whole load —
            # one malformed entry shouldn't hide the user's other history.
            print(f"  warn: dropping malformed recents entry: {e}",
                  file=sys.stderr)
            continue
    return out


def add_recent(
    question: str,
    result: Answer,
    rewritten_query: str | None = None,
) -> RecentEntry:
    """Append a new recent. Truncates to MAX_STORED, persists atomically.

    The new entry goes to the front (index 0). Returns the persisted
    entry so callers can echo its id back to the client.
    """
    entry = RecentEntry(
        id=f"rec_{secrets.token_hex(6)}",
        asked_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        question=question,
        rewritten_query=rewritten_query,
        result=result,
    )
    existing = list_recents()
    new_list = [entry, *existing][:MAX_STORED]
    _save(new_list)
    return entry


def get_recent(entry_id: str) -> RecentEntry | None:
    """Look up a recent by id. None if not found."""
    for r in list_recents():
        if r.id == entry_id:
            return r
    return None


def clear_recents() -> None:
    """Remove the recents file entirely. Used by Settings → Data → "Clear
    history" once we wire that affordance."""
    path = recents_path()
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _save(entries: list[RecentEntry]) -> None:
    """Write `entries` to recents.json atomically (write-temp + rename).

    Atomic writes matter because the ask bar polls this file on focus —
    a partial write would surface as a parse error and (defensively)
    show an empty recents list. Atomic rename guarantees the reader
    sees either the old or the new file, never a half-written one.
    """
    path = recents_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: list[dict[str, Any]] = [e.model_dump(mode="json") for e in entries]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
