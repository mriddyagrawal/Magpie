"""Client-side helpers — connect to the daemon, send requests, receive
responses. Falls back gracefully when the daemon is unreachable so
callers don't have to handle "daemon down" themselves.

Public entry points:

  - `ask_via_daemon(question, ...)` — primary call site. Tries daemon,
    falls back to in-process pipeline. Returns the same shape `pipeline.ask`
    would have.

  - `ping_daemon()` — health check. Used by `python -m src.daemon --status`.
  - `request_shutdown()` — `--stop` command.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from multiprocessing.connection import Client

from src.daemon import protocol as proto
from src.daemon.paths import get_or_create_authkey, socket_address
from src.daemon.spawn import existing_pid, spawn_daemon, wait_for_socket


CONNECT_TIMEOUT_SEC = 2.0   # how long to wait for an existing daemon
SPAWN_TIMEOUT_SEC = 15.0    # how long to wait after spawning a fresh one


class DaemonUnreachableError(RuntimeError):
    """Raised when we can't reach the daemon and the caller asked us to."""


@dataclass
class _Connection:
    """Tiny wrapper so the close path is always run via context manager."""
    conn: object

    def __enter__(self):
        return self.conn

    def __exit__(self, *_):
        try:
            self.conn.close()  # type: ignore[attr-defined]
        except Exception:  # pylint: disable=broad-except
            pass


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def _try_connect() -> "_Connection | None":
    """Best-effort connect to an existing daemon. Returns None if the
    socket isn't there or the daemon refused us."""
    addr = socket_address()
    authkey = get_or_create_authkey()
    try:
        conn = Client(addr, authkey=authkey)
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        return None
    return _Connection(conn=conn)


def _connect_or_spawn(*, allow_spawn: bool = True) -> "_Connection | None":
    """Get a connected handle to the daemon, spawning if needed.

    Sequence:
      1. If a socket exists, try connecting. Done if it works.
      2. If allow_spawn, spawn a fresh daemon and wait for its socket.
         Then connect.
      3. Return None if we still can't reach it (callers fall back).
    """
    handle = _try_connect()
    if handle is not None:
        return handle

    if not allow_spawn:
        return None

    # Stale socket file from a crashed daemon, or no daemon yet — try
    # to spawn. spawn_daemon() returns immediately; we poll for the
    # listener to come up.
    if existing_pid() is None:
        spawn_daemon()
        if not wait_for_socket(timeout_sec=SPAWN_TIMEOUT_SEC):
            return None

    return _try_connect()


# ---------------------------------------------------------------------------
# RPC ops
# ---------------------------------------------------------------------------

def ping_daemon() -> proto.PingResponse:
    """Health check. Raises DaemonUnreachableError if no daemon responds."""
    handle = _connect_or_spawn(allow_spawn=False)
    if handle is None:
        raise DaemonUnreachableError("no daemon listening on the socket")

    with handle as conn:
        conn.send(proto.PingRequest())
        response = conn.recv()

    if isinstance(response, proto.PingResponse):
        return response
    raise DaemonUnreachableError(f"unexpected response: {type(response).__name__}")


def request_shutdown() -> None:
    handle = _connect_or_spawn(allow_spawn=False)
    if handle is None:
        raise DaemonUnreachableError("no daemon listening on the socket")
    with handle as conn:
        conn.send(proto.ShutdownRequest())
        conn.recv()


# ---------------------------------------------------------------------------
# The high-level `ask` call — what CLI / UI clients use.
# ---------------------------------------------------------------------------

def ask_via_daemon(
    question: str,
    *,
    top_k: int = 5,
    rewrite: bool = False,
    rerank: bool = False,
    history: list[tuple[str, str]] | None = None,
    fallback_to_inprocess: bool = True,
) -> "PipelineResult":  # noqa: F821 — forward ref, imported lazily below
    """Run a question through the daemon, falling back to in-process if needed.

    Return type matches `pipeline.PipelineResult` so callers don't care
    whether the daemon answered or we fell back. The fallback path
    materializes SearchResult / SearchQuery objects from the in-process
    code; the daemon path reconstructs them from the wire-friendly dicts.

    Set `NS_DAEMON_DISABLED=1` to skip the daemon entirely (for development
    or troubleshooting).
    """
    if os.environ.get("NS_DAEMON_DISABLED") == "1":
        return _inprocess_fallback(question, top_k, rewrite, rerank, history)

    handle = _connect_or_spawn()
    if handle is None:
        if not fallback_to_inprocess:
            raise DaemonUnreachableError("daemon unreachable and fallback disabled")
        return _inprocess_fallback(question, top_k, rewrite, rerank, history)

    try:
        with handle as conn:
            conn.send(proto.AskRequest(
                question=question,
                top_k=top_k,
                rewrite=rewrite,
                rerank=rerank,
                history=history or [],
            ))
            response = conn.recv()
    except (EOFError, ConnectionResetError, OSError):
        # Daemon died mid-call. Fall back so the user still gets an answer.
        if not fallback_to_inprocess:
            raise
        return _inprocess_fallback(question, top_k, rewrite, rerank, history)

    if isinstance(response, proto.AskResponse):
        if not response.ok:
            # Server-side error — surface it. Don't silently fall back,
            # because the in-process path would hit the same error and
            # re-paying the model load is just wasted work.
            raise RuntimeError(
                f"{response.error_type}: {response.error}"
            )
        return _wire_to_pipeline_result(response)

    # ProtocolError or unknown — should be rare. Fall back to be safe.
    if fallback_to_inprocess:
        return _inprocess_fallback(question, top_k, rewrite, rerank, history)
    raise DaemonUnreachableError(f"unexpected response: {type(response).__name__}")


def _wire_to_pipeline_result(response: proto.AskResponse) -> "PipelineResult":  # noqa: F821
    """Hydrate the wire-format AskResponse into a PipelineResult that the
    rest of the codebase expects."""
    from src.pipeline import PipelineResult
    from src.stage2.search import SearchQuery, SearchResult

    retrieved = [
        SearchResult(
            summary=d.get("summary", ""),
            path=d.get("path", ""),
            score=float(d.get("score", 0.0)),
            tier=d.get("tier", "summary"),
        )
        for d in response.retrieved
    ]
    return PipelineResult(
        question=response.question,
        # The daemon doesn't currently echo the rewritten SearchQuery back —
        # callers that need it (eval, debugging) should set
        # NS_DAEMON_DISABLED=1. For interactive use, an empty stub is fine.
        search_query=SearchQuery(query=response.question, keywords=[]),
        retrieved=retrieved,
        answer=response.answer,
        sources_used=response.sources_used,
    )


def _inprocess_fallback(
    question: str,
    top_k: int,
    rewrite: bool,
    rerank: bool,
    history: list[tuple[str, str]] | None,
) -> "PipelineResult":  # noqa: F821
    """Run the pipeline directly in the calling process. Same path the
    REPL took before the daemon existed."""
    import asyncio
    from src.pipeline import PipelineResult
    from src.stage2.search import (
        SearchQuery, SearchResult,
        rewrite_query_async, raw_query, run_search,
    )
    from src.answer import answer_question, build_answer_agent

    async def _go() -> PipelineResult:
        if rewrite:
            sq = await rewrite_query_async(question, history=history or None)
        else:
            sq = raw_query(question)
        retrieved = await asyncio.to_thread(
            run_search, sq, top_k, question=question, rerank=rerank,
        )
        if not retrieved:
            return PipelineResult(
                question=question, search_query=sq, retrieved=[],
                answer="No matching documents found in the index.",
                sources_used=[],
            )
        agent = build_answer_agent()
        paths = list(dict.fromkeys(r.path for r in retrieved if r.path))
        ans = await answer_question(
            agent, question, paths,
            history=history or None, search_query=sq,
        )
        return PipelineResult(
            question=question, search_query=sq, retrieved=retrieved,
            answer=ans.answer, sources_used=ans.sources_used,
        )

    return asyncio.run(_go())
