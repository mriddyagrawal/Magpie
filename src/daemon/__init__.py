"""Long-running daemon for hot search models.

The daemon keeps FastEmbed dense + sparse encoders, the Qdrant client, and
the Kimi answer agent loaded in memory across CLI invocations. Without it,
each `ns query` spawns a fresh Python process and pays ~3-5 seconds of
model deserialization per invocation. With it, every query after the first
is sub-second.

See `IO/IO - Daemon.md` for the architecture overview and RPC contract.

Public surface:

    from src.daemon.client import ask_via_daemon
    result = ask_via_daemon(question, top_k=5, rewrite=False, rerank=False)

The client transparently spawns the daemon on first call if not already
running, and falls back to in-process execution if the daemon is
unreachable. Callers don't need to think about it.
"""
