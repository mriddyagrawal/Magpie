"""`python -m src.daemon` — entry point for the daemon process.

Usage:
  python -m src.daemon              # run in foreground (debugging)
  python -m src.daemon --detach     # spawn detached + return
  python -m src.daemon --status     # print whether a daemon is running
  python -m src.daemon --stop       # ask running daemon to exit
"""

from __future__ import annotations

import argparse
import sys

from src.daemon import server
from src.daemon.client import (
    DaemonUnreachableError,
    ping_daemon,
    request_shutdown,
)
from src.daemon.spawn import existing_pid, spawn_daemon, wait_for_socket


def _cmd_status() -> int:
    pid = existing_pid()
    if pid is None:
        print("daemon: not running")
        return 1
    try:
        info = ping_daemon()
    except DaemonUnreachableError as e:
        print(f"daemon: pid {pid} alive but socket unreachable ({e})")
        return 1
    print(f"daemon: running")
    print(f"  pid:                  {info.pid}")
    print(f"  uptime:               {info.uptime_sec:.0f}s")
    print(f"  last activity ago:    {info.last_activity_ago_sec:.0f}s")
    if info.idle_timeout_sec > 0:
        remaining = info.idle_timeout_sec - info.last_activity_ago_sec
        print(f"  idle shutdown in:     {max(0, remaining):.0f}s "
              f"(MAGPIE_DAEMON_IDLE_MINUTES={info.idle_timeout_sec // 60})")
    else:
        print(f"  idle shutdown:        disabled (MAGPIE_DAEMON_IDLE_MINUTES=0)")
    return 0


def _cmd_stop() -> int:
    pid = existing_pid()
    if pid is None:
        print("daemon: not running — nothing to stop")
        return 0
    try:
        request_shutdown()
    except DaemonUnreachableError as e:
        print(f"daemon: socket unreachable ({e}); pidfile cleanup may be needed", file=sys.stderr)
        return 1
    print(f"daemon: shutdown requested (was pid {pid})")
    return 0


def _cmd_detach() -> int:
    if existing_pid() is not None:
        print("daemon: already running")
        return 0
    spawn_daemon()
    if not wait_for_socket(timeout_sec=15.0):
        print("daemon: spawn timeout — check log", file=sys.stderr)
        return 1
    print("daemon: started")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.daemon",
        description="Magpie daemon — keeps search models hot across CLI invocations.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--detach", action="store_true",
                      help="Spawn detached + return. Default for `nas daemon start`.")
    mode.add_argument("--status", action="store_true",
                      help="Print whether a daemon is running and its uptime.")
    mode.add_argument("--stop", action="store_true",
                      help="Ask the running daemon to shut down cleanly.")
    args = parser.parse_args()

    if args.status:
        return _cmd_status()
    if args.stop:
        return _cmd_stop()
    if args.detach:
        return _cmd_detach()

    # Foreground run — useful for debugging. Will print to stdout/stderr
    # rather than the log file, so you can see what's happening.
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
