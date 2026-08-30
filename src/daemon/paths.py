"""Filesystem paths and addresses for the daemon.

Centralized so server and client agree on where things live without
threading config through every call site.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


_HOME = Path.home()


def _state_dir() -> Path:
    """Per-user directory where the daemon keeps its socket / pid / authkey.

    Linux / macOS: `$XDG_RUNTIME_DIR/magpie` if set, else
    `~/.cache/magpie`. The `runtime` dir is preferred because it's
    typically tmpfs (RAM-backed) and auto-cleaned on logout — exactly
    right for transient daemon state.

    Windows: `%LOCALAPPDATA%\\magpie` if set, else `~/.magpie`.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "magpie"
        return _HOME / ".magpie"

    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "magpie"
    return _HOME / ".cache" / "magpie"


def state_dir() -> Path:
    """Resolve and create the daemon's state directory if needed."""
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def socket_address() -> str | tuple[str, int]:
    """Address the daemon listens on / the client connects to.

    Linux / macOS: Unix socket path (string). multiprocessing.connection
    handles it transparently. The path embeds `os.getuid()` to avoid
    cross-user collision in shared `/tmp`.

    Windows: named pipe (string). multiprocessing.connection's Listener
    detects the format automatically.
    """
    if sys.platform == "win32":
        return r"\\.\pipe\magpie-" + str(os.getpid_ns()) if hasattr(os, "getpid_ns") else r"\\.\pipe\magpie"
    # Unix — short-ish path because some kernels cap socket paths at 108 chars.
    return str(state_dir() / "daemon.sock")


def pidfile() -> Path:
    """Where the running daemon writes its PID."""
    return state_dir() / "daemon.pid"


def authkey_path() -> Path:
    """Where the shared authentication key is stored.

    32 random bytes, generated on first daemon spawn, mode 0600. Both
    server and client read it; without a matching key, a connection is
    rejected. Prevents another local process from binding our socket and
    impersonating the daemon.
    """
    return state_dir() / "authkey"


def get_or_create_authkey() -> bytes:
    """Read the on-disk authkey, generating + writing one on first call."""
    p = authkey_path()
    if p.exists():
        try:
            data = p.read_bytes()
            if len(data) == 32:
                return data
        except OSError:
            pass

    # Either missing or corrupt — regenerate.
    key = secrets.token_bytes(32)
    p.write_bytes(key)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass  # Windows / permission-denied — best-effort.
    return key


def daemon_log_path() -> Path:
    """Where the daemon writes stdout/stderr after detaching."""
    return state_dir() / "daemon.log"
