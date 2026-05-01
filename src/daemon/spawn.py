"""Platform-specific detached subprocess spawn for the daemon.

Linux / macOS use double-fork to fully detach from the parent's process
group — survives shell exit, terminal close, etc. Windows uses
`CREATE_NO_WINDOW | DETACHED_PROCESS` flags on `subprocess.Popen` for the
equivalent.

After `spawn_daemon()` returns, the caller should `wait_for_socket()` to
block until the daemon's listener is ready (poll the socket file or the
pidfile). The detach itself is non-blocking — by design we don't know
when the child is fully up.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from src.daemon.paths import daemon_log_path, pidfile, socket_address, state_dir


def spawn_daemon() -> int:
    """Spawn a detached daemon process. Returns the spawned PID (best-effort).

    Idempotent in the typical case — if a daemon is already running on
    our socket, the new spawn will log a "address in use" error to its
    log file and exit. Callers should `wait_for_socket()` and tolerate
    "already running" as success.
    """
    state_dir()  # ensure dir exists; the daemon will write pid/log there.

    log = daemon_log_path()
    log.touch(exist_ok=True)

    cmd = [sys.executable, "-m", "src.daemon"]

    if sys.platform == "win32":
        return _spawn_windows(cmd, log)
    return _spawn_unix(cmd, log)


def _spawn_unix(cmd: list[str], log: Path) -> int:
    """Double-fork spawn. The grandchild becomes the daemon; the parent
    sees its (intermediate) child exit immediately so we don't accumulate
    a zombie."""
    # First fork: parent returns to caller, child continues.
    pid = os.fork()
    if pid > 0:
        # Parent: reap the intermediate child so it doesn't zombie.
        os.waitpid(pid, 0)
        # Grandchild PID is unknown to us at this point — that's OK,
        # callers identify "is the daemon up?" via the pidfile + socket.
        return -1

    # Child (intermediate). Detach from controlling terminal.
    os.setsid()

    # Second fork. Grandchild is the actual daemon; intermediate exits.
    pid = os.fork()
    if pid > 0:
        os._exit(0)

    # Grandchild — the real daemon. Redirect stdio to log file so it
    # won't crash if the parent terminal closes.
    os.chdir(str(Path(__file__).resolve().parents[2]))  # repo root
    log_fd = os.open(str(log), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.dup2(log_fd, sys.stdout.fileno())
    os.dup2(log_fd, sys.stderr.fileno())
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, sys.stdin.fileno())
    os.close(devnull)
    os.close(log_fd)

    # Replace the Python interpreter image with the daemon entry point.
    # Using exec rather than subprocess so we don't leave a forked Python
    # holding open descriptors / threads inherited from the caller.
    os.execv(cmd[0], cmd)


def _spawn_windows(cmd: list[str], log: Path) -> int:
    """Detach via `subprocess.Popen` flags. No fork() on Windows."""
    # CREATE_NEW_PROCESS_GROUP isolates the child from Ctrl-C in the
    # parent terminal. DETACHED_PROCESS gives it no console at all.
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000

    f = log.open("ab")
    proc = subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).resolve().parents[2]),
        stdin=subprocess.DEVNULL,
        stdout=f,
        stderr=f,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        close_fds=True,
    )
    return proc.pid


# ---------------------------------------------------------------------------
# Readiness probing
# ---------------------------------------------------------------------------

def wait_for_socket(timeout_sec: float = 10.0) -> bool:
    """Poll until the daemon's listener address is reachable, or timeout.

    Returns True if the socket showed up, False if we timed out. The
    typical wait is 1-3 sec on a warm machine (Python startup +
    listener bind). Cold first-ever start adds the FastEmbed model
    download time if the cache is empty — could be 30+ sec, so callers
    that are willing to wait can pass a larger timeout.
    """
    addr = socket_address()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _socket_reachable(addr):
            return True
        time.sleep(0.1)
    return False


def _socket_reachable(addr) -> bool:
    """Best-effort 'can I open this socket?' check — no protocol exchange."""
    if isinstance(addr, str) and addr.startswith(r"\\."):
        # Windows named pipe: existence check is the closest we can do
        # without trying to connect (which would consume the listener).
        return Path(addr).exists()  # not strictly correct for pipes; revisit
    if isinstance(addr, str):
        # Unix socket — file appears once `Listener` binds.
        try:
            return Path(addr).exists()
        except OSError:
            return False
    return False


def existing_pid() -> int | None:
    """Return the PID from the pidfile if a process with that PID is alive.

    Used to distinguish 'daemon up' from 'daemon down with a stale
    pidfile left behind by a crash'. Returns None if no pidfile or the
    process is gone.
    """
    p = pidfile()
    if not p.exists():
        return None
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError):
        return None

    try:
        # Signal 0 = "are you alive?" without actually signaling.
        os.kill(pid, 0)
    except OSError:
        return None
    return pid
