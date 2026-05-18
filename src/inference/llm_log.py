"""Per-session LLM request/response log.

Writes one JSONL file per Magpie launch under
`APP_DATA_DIR/logs/llm-<utc-timestamp>.log`. Every chat-completion call
through `LocalAgent` or `_CloudAgent` appends one line capturing what
went over the wire and what came back. Diagnostic-only — never
consulted by the runtime; meant to be tailed (`tail -f`) or read after
the fact when something looks off.

Format: each line is a self-contained JSON object. Fields:
  - ts: ISO-8601 UTC timestamp
  - provider: "local" / "openrouter" / "moonshot" / etc.
  - model: model identifier sent to the API
  - phase: "request" or "response"
  - latency_s: seconds (response only)
  - request: { system, messages, response_format, temperature, ... }
  - response: { content, raw_status, error, usage } — depending on success
  - error: stringified exception when the call raised

Privacy: we log everything that was sent to the model — including
file content and any user-typed question. The log lives ONLY on the
user's machine (not transmitted anywhere). It's exactly the
"what did Magpie ask the model" trace, which is the entire point.
API keys are NOT logged (they're in HTTP headers, never in our
log calls).

Cost: each call writes a few KB to disk; SSD-bound, async-flushed by
the OS. Negligible vs the multi-second LLM call itself.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.manifest import APP_DATA_DIR


_LOGS_DIR = APP_DATA_DIR / "logs"
_lock = threading.Lock()
_session_path: Path | None = None
_session_started_at: float | None = None


def _ensure_session() -> Path:
    """Resolve the per-session log path, creating the parent dir +
    writing a header line on first call. Subsequent calls return the
    cached path. Thread-safe."""
    global _session_path, _session_started_at
    if _session_path is not None:
        return _session_path
    with _lock:
        if _session_path is not None:
            return _session_path
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        # Filesystem-safe ISO timestamp: replace ':' (Windows-illegal)
        # with '-'. UTC so log file ordering is timezone-stable.
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        path = _LOGS_DIR / f"llm-{ts}.log"
        # Header line so anyone tailing the file knows what it is.
        header = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": "session_start",
            "session_id": ts,
            "note": (
                "Magpie LLM request/response log. One JSON object per line. "
                "Use `jq -c` to filter, `jq -s` to load as a list."
            ),
        }
        try:
            with path.open("w", encoding="utf-8") as f:
                f.write(json.dumps(header, ensure_ascii=False) + "\n")
        except OSError as e:
            # Logging must never block the actual request path — fall
            # through with a stderr warning and the cached `None` path
            # makes future calls cheap.
            print(f"[llm-log] couldn't open {path}: {e}", file=sys.stderr)
            _session_path = path  # remember failed path so we don't retry
            return path
        _session_path = path
        _session_started_at = time.monotonic()
        # Print the path so the user can `tail -f` it from another
        # terminal. Once per session.
        print(f"[llm-log] session log: {path}", file=sys.stderr)
        return path


def _truncate(value: Any, max_chars: int = 50_000) -> Any:
    """Cap pathologically large strings so the log file doesn't
    explode. 50 KB is large enough for any realistic prompt + response;
    file-content blocks above that get tail-truncated with a marker."""
    if isinstance(value, str) and len(value) > max_chars:
        return (
            value[: max_chars // 2]
            + f"\n\n[...truncated {len(value) - max_chars} chars...]\n\n"
            + value[-max_chars // 2 :]
        )
    if isinstance(value, list):
        return [_truncate(v, max_chars) for v in value]
    if isinstance(value, dict):
        return {k: _truncate(v, max_chars) for k, v in value.items()}
    return value


def _append(record: dict[str, Any]) -> None:
    """Append one JSONL record. Best-effort — never raises."""
    path = _ensure_session()
    try:
        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError as e:
        print(f"[llm-log] write failed: {e}", file=sys.stderr)


def log_request(
    *,
    provider: str,
    model: str,
    messages: list[dict] | list,
    system_prompt: str | None = None,
    response_format: dict | None = None,
    temperature: float | None = None,
    extra: dict | None = None,
) -> str:
    """Log an outgoing request. Returns a request_id for matching
    with the corresponding `log_response` call so you can grep/jq
    by id."""
    request_id = f"req-{int(time.time() * 1000)}-{id(messages) & 0xffff:04x}"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": "request",
        "request_id": request_id,
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "response_format": response_format,
        "system_prompt": _truncate(system_prompt) if system_prompt else None,
        "messages": _truncate(messages),
        "extra": extra or {},
    }
    _append(record)
    return request_id


def log_response(
    *,
    request_id: str,
    provider: str,
    model: str,
    latency_s: float,
    content: str | None = None,
    raw_status: int | None = None,
    usage: dict | None = None,
    error: str | None = None,
) -> None:
    """Log the response (or error) for a previously-logged request."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": "response",
        "request_id": request_id,
        "provider": provider,
        "model": model,
        "latency_s": round(latency_s, 3),
        "raw_status": raw_status,
        "usage": usage,
        "content": _truncate(content) if content else None,
        "error": error,
    }
    _append(record)


def session_log_path() -> Path | None:
    """Where is the current session's log file? `None` until first
    request fires (the file is lazy-created)."""
    return _session_path
