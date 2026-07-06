"""Start Qdrant locally for dev mode — cross-platform (Windows/macOS/Linux).

In dev (`pnpm tauri dev` / `just run-magpie`), Tauri does NOT auto-spawn
Qdrant — that's release-only. The sidecar then defaults to
http://localhost:6433, so if nothing is listening there, every flush fails
with a connection-refused error and indexed files never become searchable.

This launches the bundled Qdrant binary on that port, using the SAME storage
dir the packaged app uses (resolved via the app's own APP_DATA_DIR helper, so
we never hardcode %LOCALAPPDATA% / ~/Library / ~/.local/share). Data flushed
in dev therefore persists and is visible to the release build too.

    uv run python scripts/qdrant_up.py      # leave running; Ctrl-C to stop

Then run `pnpm tauri dev` in another terminal.

Only one Qdrant may use the storage dir at a time — quit the packaged Magpie
app (which spawns its own Qdrant) before running this, or you'll get a lock
error.
"""

from __future__ import annotations

import os
import platform
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
BINARIES = ROOT / "frontend" / "src-tauri" / "binaries"
HTTP_PORT = "6433"  # matches src/stage2/db.py:_DEFAULT_ENDPOINT
GRPC_PORT = "6434"


def qdrant_binary() -> Path:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows":
        name = "qdrant-x86_64-pc-windows-msvc.exe"
    elif system == "Darwin":
        name = "qdrant-aarch64-apple-darwin" if machine == "arm64" else "qdrant-x86_64-apple-darwin"
    elif system == "Linux":
        arch = "aarch64" if machine in ("aarch64", "arm64") else "x86_64"
        name = f"qdrant-{arch}-unknown-linux-gnu"
    else:
        raise SystemExit(f"unsupported platform: {system} {machine}")
    path = BINARIES / name
    if not path.exists():
        raise SystemExit(
            f"Qdrant binary not found: {path}\n"
            f"Run `uv run python scripts/download_qdrant.py` first."
        )
    return path


def storage_dir() -> Path:
    # Same dir the packaged app uses, via the app's own helper — no hardcoded
    # platform paths.
    from src.manifest import APP_DATA_DIR
    return Path(APP_DATA_DIR) / "qdrant_storage"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    binary = qdrant_binary()
    storage = storage_dir()
    storage.mkdir(parents=True, exist_ok=True)

    # Pre-flight: the #1 failure is "something already owns this storage / port"
    # — the packaged Magpie app (it runs its own Qdrant), or a leftover qdrant
    # process. Two Qdrants can't share one storage dir; the second dies with an
    # opaque WAL-lock panic. Catch the common case early with a clear message.
    if _port_in_use(int(HTTP_PORT)):
        raise SystemExit(
            f"Port {HTTP_PORT} is already in use — a Qdrant is very likely "
            f"already running.\n"
            f"  - If it's the packaged Magpie app, you don't need this script; "
            f"the app runs its own Qdrant.\n"
            f"  - Otherwise stop the stray one, then retry:\n"
            f"      Get-Process qdrant* | Stop-Process -Force"
        )

    env = dict(os.environ)
    env["QDRANT__STORAGE__STORAGE_PATH"] = str(storage)
    env["QDRANT__SERVICE__HOST"] = "127.0.0.1"
    env["QDRANT__SERVICE__HTTP_PORT"] = HTTP_PORT
    env["QDRANT__SERVICE__GRPC_PORT"] = GRPC_PORT

    print(f"Starting Qdrant on http://localhost:{HTTP_PORT} (gRPC {GRPC_PORT})")
    print(f"  binary:  {binary}")
    print(f"  storage: {storage}")
    print("  Leave this running while you use `pnpm tauri dev`. Ctrl-C to stop.")
    try:
        subprocess.run([str(binary)], env=env, cwd=str(storage), check=True)
    except KeyboardInterrupt:
        print("\nQdrant stopped.")
    except subprocess.CalledProcessError as e:
        # Exit 101 = Rust panic, almost always the storage WAL lock: another
        # Qdrant (or the packaged app) has this storage dir open.
        raise SystemExit(
            f"\nQdrant exited with status {e.returncode}. If the log above shows "
            f"a WAL lock / 'another process has locked' error, another Qdrant is "
            f"using this storage.\nQuit the packaged Magpie app and kill any stray "
            f"Qdrant, then retry:\n    Get-Process qdrant* | Stop-Process -Force"
        ) from None


if __name__ == "__main__":
    main()
