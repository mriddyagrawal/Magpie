"""Daemon server: accept loop + idle-shutdown watchdog.

Lifecycle:
  1. `run()` loads heavy modules in background, binds the listener, writes
     pidfile, and enters the accept loop.
  2. Each connection runs one request, returns one response, closes.
     Connections are handled serially — one query at a time. Adding a
     thread pool is ~10 lines if we ever need it, but most users only
     run one query at a time.
  3. A watchdog thread checks `_last_activity_t` every 30 sec; when it
     exceeds `idle_timeout_sec`, the daemon exits cleanly (close listener,
     remove pidfile, sys.exit).
  4. SIGTERM / SIGINT / Windows CTRL_BREAK_EVENT also trigger a clean shutdown.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from multiprocessing.connection import Listener
from typing import Any

from src.daemon import protocol as proto
from src.daemon.paths import (
    daemon_log_path,
    get_or_create_authkey,
    pidfile,
    socket_address,
)


# 15 minutes default — matches the value we agreed on earlier.
DEFAULT_IDLE_TIMEOUT_SEC = 15 * 60


def _idle_timeout_sec() -> int:
    """Read MAGPIE_DAEMON_IDLE_MINUTES (legacy NS_DAEMON_IDLE_MINUTES honored). 0 disables auto-shutdown."""
    raw = os.environ.get("MAGPIE_DAEMON_IDLE_MINUTES") or os.environ.get("NS_DAEMON_IDLE_MINUTES")
    if raw is None:
        return DEFAULT_IDLE_TIMEOUT_SEC
    try:
        minutes = int(raw)
        return max(0, minutes) * 60
    except ValueError:
        return DEFAULT_IDLE_TIMEOUT_SEC


# ---------------------------------------------------------------------------
# Module-level state — there's exactly one daemon process per user, so
# globals are fine. Touched by the accept loop and the watchdog.
# ---------------------------------------------------------------------------

_started_at = time.monotonic()
_last_activity_t = time.monotonic()
_activity_lock = threading.Lock()
_shutdown_requested = threading.Event()
_listener: Listener | None = None


def _bump_activity() -> None:
    global _last_activity_t
    with _activity_lock:
        _last_activity_t = time.monotonic()


def _seconds_since_activity() -> float:
    with _activity_lock:
        return time.monotonic() - _last_activity_t


# ---------------------------------------------------------------------------
# Request dispatch
# ---------------------------------------------------------------------------

def _dispatch(request: Any) -> Any:
    """Route a request to its handler. Catches all exceptions and converts
    them into structured responses so the client gets something parseable
    even when a handler crashes mid-call."""
    _bump_activity()

    if isinstance(request, proto.PingRequest):
        return _handle_ping(request)
    if isinstance(request, proto.ShutdownRequest):
        return _handle_shutdown(request)
    if isinstance(request, proto.AskRequest):
        return _handle_ask(request)

    return proto.ProtocolError(
        error=f"unknown request type: {type(request).__name__}",
        server_protocol_version=proto.PROTOCOL_VERSION,
    )


def _handle_ping(_: proto.PingRequest) -> proto.PingResponse:
    return proto.PingResponse(
        ok=True,
        protocol_version=proto.PROTOCOL_VERSION,
        pid=os.getpid(),
        uptime_sec=time.monotonic() - _started_at,
        idle_timeout_sec=_idle_timeout_sec(),
        last_activity_ago_sec=_seconds_since_activity(),
    )


def _handle_shutdown(_: proto.ShutdownRequest) -> proto.ShutdownResponse:
    _shutdown_requested.set()
    return proto.ShutdownResponse(ok=True)


def _handle_ask(req: proto.AskRequest) -> proto.AskResponse:
    """Run pipeline.ask in-process. Models stay loaded across calls — that's
    the whole point of the daemon."""
    # Lazy imports so daemon startup stays cheap and Python interpreter
    # startup doesn't pay for them when we just return ping responses.
    import asyncio
    from src.pipeline import ask as pipeline_ask
    from src.stage2.search import (
        SearchQuery,
        rewrite_query_async,
        raw_query,
        run_search,
    )
    from src.answer import answer_question, build_answer_agent

    try:
        # Recreate the pipeline path here so we can pass `rerank` and
        # `history` (pipeline.ask doesn't expose them yet — adding kwargs
        # there would cascade through ask_sync, callers, etc.).
        async def _run() -> proto.AskResponse:
            if req.rewrite:
                sq = await rewrite_query_async(req.question, history=req.history or None)
            else:
                sq = raw_query(req.question)

            retrieved = await asyncio.to_thread(
                run_search, sq, req.top_k, question=req.question, rerank=req.rerank,
            )
            if not retrieved:
                return proto.AskResponse(
                    ok=True,
                    question=req.question,
                    answer="No matching documents found in the index.",
                    sources_used=[],
                    retrieved=[],
                )

            agent = build_answer_agent()
            paths = list(dict.fromkeys(r.path for r in retrieved if r.path))
            ans = await answer_question(
                agent, req.question, paths,
                history=req.history or None, search_query=sq,
            )

            return proto.AskResponse(
                ok=True,
                question=req.question,
                answer=ans.answer,
                sources_used=ans.sources_used,
                retrieved=[
                    {"path": r.path, "score": float(r.score), "tier": r.tier, "summary": r.summary}
                    for r in retrieved
                ],
            )

        return asyncio.run(_run())

    except Exception as e:  # pylint: disable=broad-except
        return proto.AskResponse(
            ok=False,
            error=str(e),
            error_type=type(e).__name__,
        )


# ---------------------------------------------------------------------------
# Accept loop + watchdog
# ---------------------------------------------------------------------------

def _watchdog_loop() -> None:
    """Background thread — exits the daemon if idle exceeds threshold."""
    timeout = _idle_timeout_sec()
    if timeout <= 0:
        return  # idle-shutdown disabled (MAGPIE_DAEMON_IDLE_MINUTES=0).
    while not _shutdown_requested.is_set():
        if _seconds_since_activity() > timeout:
            print(
                f"[daemon] idle for {timeout/60:.1f} min, shutting down",
                file=sys.stderr,
            )
            _shutdown_requested.set()
            _shutdown_listener()
            return
        # Check ~every 30 seconds — fast enough for a 15 min timeout,
        # cheap enough to run forever.
        if _shutdown_requested.wait(timeout=30):
            return


def _shutdown_listener() -> None:
    """Force-close the Listener so the accept loop's blocking `accept()`
    returns immediately. Safe to call from any thread."""
    global _listener
    try:
        if _listener is not None:
            _listener.close()
    except Exception:  # pylint: disable=broad-except
        pass


def _install_signal_handlers() -> None:
    """Install graceful-shutdown handlers. No-ops when not in the main
    thread (e.g. test harnesses that spawn the daemon in a thread).
    `signal.signal` raises `ValueError` outside the main thread."""
    if threading.current_thread() is not threading.main_thread():
        return

    def _on_signal(_signum, _frame):
        print(f"[daemon] received signal, shutting down", file=sys.stderr)
        _shutdown_requested.set()
        _shutdown_listener()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _on_signal)


def _write_pidfile() -> None:
    pidfile().write_text(str(os.getpid()), encoding="utf-8")


def _remove_pidfile() -> None:
    try:
        pidfile().unlink()
    except OSError:
        pass


def _remove_socket_if_unix(addr) -> None:
    """If a previous daemon crashed without unlinking its Unix socket file,
    `Listener` would error 'Address already in use'. Best-effort cleanup."""
    if isinstance(addr, str) and addr.startswith("/"):
        try:
            os.unlink(addr)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    """Daemon main loop. Called by `python -m src.daemon`."""
    global _listener, _started_at, _last_activity_t

    print(
        f"[daemon] starting pid={os.getpid()} log={daemon_log_path()}",
        file=sys.stderr,
    )

    addr = socket_address()
    authkey = get_or_create_authkey()
    _remove_socket_if_unix(addr)

    _listener = Listener(addr, authkey=authkey)
    if isinstance(addr, str) and addr.startswith("/"):
        # Tighten Unix-socket permissions: only the owning user can connect.
        try:
            os.chmod(addr, 0o600)
        except OSError:
            pass

    _started_at = time.monotonic()
    _last_activity_t = time.monotonic()

    _write_pidfile()
    _install_signal_handlers()

    # Background-prewarm the search-side models so the first `ask` is fast.
    # Same prewarm logic the REPL uses, but here it runs once for the
    # daemon's lifetime. Failures are silent — first real call will retry.
    def _prewarm() -> None:
        try:
            from src.stage2.embeddings import get_dense_model, get_sparse_model
            get_dense_model()
            get_sparse_model()
        except BaseException:  # pylint: disable=broad-except
            pass
        try:
            from src.stage2.db import get_qdrant_client
            client = get_qdrant_client()
            try:
                client.get_collections()
            except BaseException:  # pylint: disable=broad-except
                pass
        except BaseException:  # pylint: disable=broad-except
            pass
        try:
            from src.answer import build_answer_agent
            build_answer_agent()
        except BaseException:  # pylint: disable=broad-except
            pass

    threading.Thread(target=_prewarm, daemon=True).start()
    threading.Thread(target=_watchdog_loop, daemon=True).start()

    print(f"[daemon] listening on {addr}", file=sys.stderr)

    try:
        while not _shutdown_requested.is_set():
            try:
                conn = _listener.accept()
            except OSError:
                # Listener was closed by the watchdog or signal handler.
                break

            try:
                request = conn.recv()
                response = _dispatch(request)
                conn.send(response)
            except EOFError:
                pass
            except Exception as e:  # pylint: disable=broad-except
                # Last-resort: a crash in dispatch shouldn't take down
                # the daemon. Log and keep accepting.
                print(
                    f"[daemon] dispatch error: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
            finally:
                try:
                    conn.close()
                except Exception:  # pylint: disable=broad-except
                    pass
    finally:
        _shutdown_listener()
        _remove_pidfile()
        _remove_socket_if_unix(addr)
        print(f"[daemon] stopped", file=sys.stderr)


if __name__ == "__main__":
    run()
