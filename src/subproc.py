"""Cross-platform subprocess helpers.

The one thing this module exists for: stop console executables (llama-server,
ripgrep, the binary `--version` probes) from flashing a black terminal window
every time we spawn them.

In a windowed GUI build (Tauri on Windows), the host process has no console.
When it `Popen`/`run`s a *console* subsystem `.exe`, Windows helpfully creates
a brand-new console window for the child and tears it down when the child
exits. A short-lived or repeatedly-respawned child therefore looks like the
screen is flickering — a terminal pops up and vanishes over and over.

`CREATE_NO_WINDOW` tells Windows "run this console program with no console
window at all". This is exactly what `src/daemon/spawn.py` already does for the
detached daemon; this helper makes the same fix reusable for every other spot
that launches a bundled console binary.

No-op on macOS and Linux, where launching a subprocess never spawns a window.
"""

from __future__ import annotations

import subprocess
import sys


def no_window_kwargs() -> dict:
    """Return `subprocess` kwargs that suppress the console window on Windows.

    Spread into any `subprocess.run(...)` / `subprocess.Popen(...)` that
    launches a console executable::

        subprocess.run([binary, "--version"], **no_window_kwargs())

    Returns an empty dict on non-Windows platforms, so the call site stays
    identical everywhere.
    """
    if sys.platform == "win32":
        # subprocess.CREATE_NO_WINDOW only exists on the Windows build of
        # CPython, so it's referenced solely inside this branch.
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
