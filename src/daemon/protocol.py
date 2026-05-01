"""Wire protocol — typed request/response shapes the server and client
exchange over the multiprocessing.connection socket.

We send Python objects directly via `Connection.send()` (pickle under the
hood). All shapes here are simple dataclasses with primitive fields so the
pickle roundtrip is cheap and there's no risk of importing heavy modules
on the client side just to deserialize.

Adding a new RPC: define a new <Foo>Request / <Foo>Response pair, then
handle the type in `server._dispatch`. No registration step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Wire-format version. Bump on incompatible changes (rename a field, change
# a type, etc.) so an old client talking to a new daemon (or vice-versa)
# fails fast instead of silently misbehaving. Server and client compare
# this on every connection.
PROTOCOL_VERSION = 1


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@dataclass
class PingRequest:
    """Health probe — used by the client to verify the daemon is responsive
    before trusting the socket. No-op on the server side beyond bumping the
    last-activity timestamp."""
    protocol_version: int = PROTOCOL_VERSION


@dataclass
class PingResponse:
    ok: bool
    protocol_version: int
    pid: int
    uptime_sec: float
    idle_timeout_sec: int
    last_activity_ago_sec: float


@dataclass
class ShutdownRequest:
    """Ask the daemon to exit cleanly. Used by `nas daemon stop`."""


@dataclass
class ShutdownResponse:
    ok: bool


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@dataclass
class AskRequest:
    """Run the full retrieve → answer pipeline for one question.

    Mirrors `pipeline.ask` plus the extra knobs the REPL exposes
    (rerank, history). All fields are primitives so pickle is fast and
    the daemon doesn't need to import the search/rewrite/answer modules
    just to deserialize the request envelope."""
    question: str
    top_k: int = 5
    rewrite: bool = False
    rerank: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)
    protocol_version: int = PROTOCOL_VERSION


@dataclass
class AskResponse:
    """Successful: `ok=True` + the four fields the CLI actually renders.
    Failure: `ok=False` + `error` / `error_type` for the client to surface."""
    ok: bool
    # On success:
    question: str = ""
    answer: str = ""
    sources_used: list[str] = field(default_factory=list)
    # `retrieved` carries the raw search results so the CLI can show its
    # "Retrieved Documents" table. Each item is a plain dict (not the
    # SearchResult dataclass) to keep the wire format independent of
    # downstream module changes.
    retrieved: list[dict] = field(default_factory=list)
    # On failure:
    error: str = ""
    error_type: str = ""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

@dataclass
class ProtocolError:
    """Server returns this when it can't recognize the incoming request type
    — usually a version mismatch. Client raises so the user notices."""
    error: str
    server_protocol_version: int
