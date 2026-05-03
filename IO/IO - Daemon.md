# Daemon — long-lived backend for hot search models

> **What this doc is.** Architecture overview + RPC contract for the
> NotAnotherSpotlight daemon. Read this if you're (a) integrating a UI
> against the daemon socket, (b) extending the RPC surface, or (c)
> debugging "why is my query slow."

---

## Why the daemon exists

Each fresh `ns` invocation pays ~3-5 sec of model deserialization (FastEmbed
dense + sparse + Qdrant TLS handshake + Kimi agent setup). Inside one process
those costs amortize — second query in a REPL session is fast. **Across
processes they don't.** Every UI window reopen, every shell-script call, every
new tab pays the cost again.

The daemon keeps the models loaded in a long-lived background process. CLI /
UI clients connect over a Unix socket (or named pipe on Windows), send a
question, get a `PipelineResult` back in ~200-500 ms. No model load.

```
┌────────────┐                       ┌──────────────────────────────┐
│  ns CLI    │                       │  ns-daemon (background)      │
│            │   ←───── socket ────→ │   • dense + sparse encoders  │
│  - argparse│   pickle envelope     │   • Qdrant client cached     │
│  - rendering                       │   • Kimi answer agent cached │
└────────────┘                       │   • idle-shutdown watchdog   │
┌────────────┐                       └──────────────────────────────┘
│  Friend UI │←──────── same socket  ↑
│            │   same wire format    │
│            │                       │
└────────────┘                       │
```

Same wire protocol regardless of client. CLI is one consumer; the friend's
UI is another.

---

## End-to-end speed comparison

| Scenario | No daemon | With daemon |
|---|---|---|
| First query of a fresh shell | ~5-10 s | ~0.3-0.6 s after first warm-up |
| Subsequent queries (same shell) | ~0.5-3 s | ~0.2-0.5 s |
| Close terminal, reopen, query | ~5-10 s again | ~0.2 s (daemon stayed up) |
| Friend's UI window reopen + query | ~5-10 s | ~0.2 s |

---

## Lifecycle

```
                          ┌──────────────────────────────────┐
                          │ no daemon running                │
                          │ no socket file                   │
                          └────────────┬─────────────────────┘
                                       │
                        first `ns query` arrives, or `just daemon-start`
                                       │
                                       ▼
                          ┌──────────────────────────────────┐
                          │ daemon spawned (detached)        │
                          │ binds socket, writes pidfile     │
                          │ background-prewarms models       │
                          │ enters accept loop               │
                          └────────────┬─────────────────────┘
                                       │
                          requests served, last_activity_t bumped
                                       │
                                       ▼
                          ┌──────────────────────────────────┐
                          │ idle for NS_DAEMON_IDLE_MINUTES  │
                          │ (default 15)                      │
                          └────────────┬─────────────────────┘
                                       │
                              watchdog triggers shutdown
                                       │
                                       ▼
                          ┌──────────────────────────────────┐
                          │ daemon exits cleanly             │
                          │ socket + pidfile removed         │
                          │ RAM freed                        │
                          └──────────────────────────────────┘
```

Set `NS_DAEMON_IDLE_MINUTES=0` to disable idle shutdown (always-on for power users).

Set `NS_DAEMON_DISABLED=1` on a client to force in-process execution
(skip the daemon entirely — useful for development or troubleshooting).

---

## CLI commands

```bash
just daemon-start    # spawn detached (idempotent)
just daemon-status   # is it running? uptime? idle countdown?
just daemon-stop     # graceful shutdown
just daemon-log      # tail the daemon's log file
```

Or directly:

```bash
python -m src.daemon              # foreground (debugging — Ctrl-C to stop)
python -m src.daemon --detach     # spawn detached
python -m src.daemon --status
python -m src.daemon --stop
```

---

## Client integration (Python)

The daemon is invisible to most callers — `ask_via_daemon` handles spawn /
fallback transparently:

```python
from src.daemon.client import ask_via_daemon

result = ask_via_daemon(
    question="how much did I spend at Trader Joe's last March?",
    top_k=5,
    rewrite=False,   # set True to use Kimi rewrite (~3-15s network call)
    rerank=False,    # set True to enable cross-encoder reranking
    history=[],      # list of (prev_q, prev_a) tuples
)

# result is a PipelineResult — same shape as `pipeline.ask` returns.
print(result.answer)
for src in result.sources_used:
    print(f"  - {src}")
```

Fallback behavior:

- If the daemon is running and reachable: query goes there, comes back fast.
- If no daemon: client auto-spawns one, waits for it to be ready (up to
  ~15 sec for first-ever cold start), then queries.
- If spawn fails or the daemon crashes mid-call: falls back to in-process
  pipeline. Caller still gets a result.
- If the caller passes `fallback_to_inprocess=False`, daemon failures
  raise `DaemonUnreachableError` instead.

---

## Wire protocol

The daemon and clients exchange Python dataclasses via
`multiprocessing.connection`. Pickle is the underlying format; the Listener
verifies a 32-byte authkey on every connection so other local users can't
talk to your daemon.

### Address

| Platform | Address | Discovery |
|---|---|---|
| Linux | `$XDG_RUNTIME_DIR/notspotlight/daemon.sock` (else `~/.cache/notspotlight/daemon.sock`) | Unix socket file |
| macOS | `~/.cache/notspotlight/daemon.sock` | Unix socket file |
| Windows | `\\.\pipe\notspotlight` | Named pipe |

Resolved by `src.daemon.paths.socket_address()`.

### Authkey

32 random bytes at `<state_dir>/authkey`, mode `0600`. Generated on first
daemon spawn; clients read the same file. Mismatched keys → connection
refused.

Resolved by `src.daemon.paths.get_or_create_authkey()`.

### Request types

All requests carry `protocol_version: int` for forward compatibility. The
server returns `ProtocolError` if a future client sends an unknown shape.

#### `PingRequest` — health check

```python
@dataclass
class PingRequest:
    protocol_version: int = 1

@dataclass
class PingResponse:
    ok: bool
    protocol_version: int
    pid: int
    uptime_sec: float
    idle_timeout_sec: int               # 0 if disabled
    last_activity_ago_sec: float
```

#### `AskRequest` — run a full query

```python
@dataclass
class AskRequest:
    question: str
    top_k: int = 5
    rewrite: bool = False               # Kimi rewrite (~3-15s network)
    rerank: bool = False                # Cross-encoder reranking
    history: list[tuple[str, str]] = []
    protocol_version: int = 1

@dataclass
class AskResponse:
    ok: bool
    # On success:
    question: str
    answer: str
    sources_used: list[str]
    retrieved: list[dict]               # [{path, score, tier, summary}, ...]
    # On failure:
    error: str
    error_type: str                     # exception class name
```

#### `ShutdownRequest` — ask the daemon to exit

```python
@dataclass
class ShutdownRequest: ...

@dataclass
class ShutdownResponse:
    ok: bool
```

### Pickle gotchas for non-Python clients

If your friend's UI is in another language (TS/Rust/Swift), pickle is
inconvenient. Options:

1. **Spawn a thin Python adapter** that reads JSON from stdin, calls
   `ask_via_daemon`, writes JSON to stdout. ~30 lines.
2. **Add a JSON protocol mode** to the daemon — `--json` flag that switches
   the Listener to read/write JSON instead of pickle. ~50 lines if you go
   this route. Not built today; ask before relying on it.
3. **Use a proper IPC layer** (gRPC, msgpack-rpc) — bigger lift but
   eliminates the pickle dependency entirely.

For an Electron / Tauri UI: option 1 is fastest.

---

## RAM footprint

| Daemon state | RSS |
|---|---|
| Idle (just started, no models loaded yet) | ~80 MB |
| Active (dense + sparse + Qdrant + answer agent loaded) | **~250 MB** |
| With cross-encoder rerank loaded | ~700 MB (sentence-transformers pulls torch) |
| With ColPali fast-tier loaded | ~2.5 GB (unavoidable) |

After idle-shutdown the entire process exits and frees everything.

---

## Search-as-you-type pattern (for the UI)

The daemon serves any number of requests per second from hot models —
which makes typing-debounced incremental search practical:

```typescript
// Pseudo-code for the friend's UI
let pending = null
input.on('keystroke', () => {
  pending?.cancel()
  pending = setTimeout(() => {
    daemon.ask({ question: input.value, top_k: 10 })
      .then(result => render(result))
  }, 50)  // 50ms debounce
})
```

Each keystroke debounces 50 ms, sends a fresh query, the UI updates with
the latest results. The daemon's per-request cost is ~200-500 ms — fast
enough that the user sees results refining as they type.

Without the daemon, this pattern is impossible: each query would spawn a
new process and take ~5 sec, way longer than the inter-keystroke interval.

---

## Limitations / what's not built (yet)

- **No fine-grained RPC ops** — only `ask` does the whole pipeline. If the
  UI needs intermediate progress events (rewriting / embedding / searching /
  answering), we'd need to add streaming callbacks or split the op.
  Current shape returns one result per request.
- **One request at a time per daemon.** No thread pool. If you fire ten
  queries concurrently, they queue. Adding a worker pool is ~15 lines but
  not done today.
- **Per-model eviction not implemented.** Models loaded once stay loaded
  for the daemon's lifetime. Idle shutdown is whole-daemon, not
  per-model. Means a daemon that ever loaded ColPali keeps 2 GB until
  the whole daemon shuts down.
- **No JSON protocol.** Pickle is the wire format. Non-Python clients
  need a Python adapter (see "Pickle gotchas" above).
- **No graceful protocol-version mismatch UX.** Server returns
  `ProtocolError`; clients raise. We don't auto-upgrade.

---

## Cross-references

- [src/daemon/server.py](../src/daemon/server.py) — accept loop, dispatcher, watchdog
- [src/daemon/client.py](../src/daemon/client.py) — `ask_via_daemon`, fallback logic
- [src/daemon/protocol.py](../src/daemon/protocol.py) — request/response dataclasses
- [src/daemon/paths.py](../src/daemon/paths.py) — socket address, authkey, pidfile
- [src/daemon/spawn.py](../src/daemon/spawn.py) — cross-platform detached subprocess
- [src/daemon/__main__.py](../src/daemon/__main__.py) — `--detach` / `--status` / `--stop`
- [tests/daemon/](../tests/daemon/) — 21 tests covering protocol, paths, lifecycle, fallback
- [IO - Tiers.md](IO%20-%20Tiers.md) — how the search pipeline the daemon hosts works
