"""Per-run service lifecycle: an isolated Qdrant instance + worker subprocesses.

Qdrant is a localhost SERVER in this app (src/stage2/db.py, default
127.0.0.1:6433), so MAGPIE_DATA_DIR alone does NOT isolate the vector store —
an eval run pointed at the default port would write collections into whatever
Qdrant is already running (possibly the user's live app). Every run therefore
gets its own qdrant process: bundled binary, storage inside the run folder,
ports from envctl.Ports, endpoint injected via QDRANT_CLUSTER_ENDPOINT.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_QDRANT_BINARIES = {
    ("darwin", "arm64"): "qdrant-aarch64-apple-darwin",
    ("darwin", "x86_64"): "qdrant-x86_64-apple-darwin",
    ("win32", "AMD64"): "qdrant-x86_64-pc-windows-msvc.exe",
    ("linux", "x86_64"): "qdrant-x86_64-unknown-linux-gnu",
}


def qdrant_binary() -> Path:
    import platform
    key = (sys.platform, platform.machine())
    name = _QDRANT_BINARIES.get(key)
    if name is None:
        raise RuntimeError(f"no bundled qdrant binary known for {key}")
    path = REPO_ROOT / "frontend" / "src-tauri" / "binaries" / name
    if not path.exists():
        raise RuntimeError(
            f"qdrant binary missing at {path} — run `just download-qdrant` once"
        )
    return path


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


class QdrantInstance:
    """A run-private qdrant server. Storage lives under the run folder and is
    part of the run's raw artifacts (gitignored)."""

    def __init__(self, storage_dir: Path, http_port: int, grpc_port: int, log_path: Path):
        self.storage_dir = storage_dir
        self.http_port = http_port
        self.grpc_port = grpc_port
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"

    def start(self, timeout_s: float = 30.0) -> None:
        for port, what in ((self.http_port, "http"), (self.grpc_port, "grpc")):
            if not _port_free(port):
                raise RuntimeError(
                    f"qdrant {what} port {port} already in use — a previous run "
                    f"may not have been torn down (check `pgrep -fl qdrant`)"
                )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "QDRANT__STORAGE__STORAGE_PATH": str(self.storage_dir),
            "QDRANT__SERVICE__HOST": "127.0.0.1",
            "QDRANT__SERVICE__HTTP_PORT": str(self.http_port),
            "QDRANT__SERVICE__GRPC_PORT": str(self.grpc_port),
            "QDRANT__TELEMETRY_DISABLED": "true",
        }
        log_f = self.log_path.open("ab")
        self.proc = subprocess.Popen(
            [str(qdrant_binary())], env=env, stdout=log_f, stderr=log_f,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"qdrant exited immediately (code {self.proc.returncode}); "
                    f"see {self.log_path}"
                )
            try:
                with urllib.request.urlopen(self.endpoint + "/readyz", timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.25)
        self.stop()
        raise RuntimeError(f"qdrant not ready within {timeout_s}s; see {self.log_path}")

    def stop(self, timeout_s: float = 10.0) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc = None

    def __enter__(self) -> "QdrantInstance":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


def run_worker(
    phase: str,
    run_dir: Path,
    env: dict[str, str],
    payload: dict,
    *,
    timeout_s: float | None = None,
    log_name: str | None = None,
) -> dict:
    """Launch one worker subprocess (fresh interpreter, controlled env) and
    return its result JSON.

    Protocol: payload JSON on argv, result JSON written to a file (stdout is
    unusable — the backend prints query traces there and to stderr; those
    traces are captured to a per-phase log and mined later for timings).
    """
    result_path = run_dir / "raw" / f"worker_{phase}_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if result_path.exists():
        result_path.unlink()
    payload_path = run_dir / "raw" / f"worker_{phase}_payload.json"
    payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    log_path = run_dir / "raw" / (log_name or f"worker_{phase}.log")
    worker_script = Path(__file__).with_name("worker.py")
    cmd = [
        sys.executable, str(worker_script),
        "--phase", phase,
        "--payload", str(payload_path),
        "--result", str(result_path),
    ]
    with log_path.open("ab") as log_f:
        proc = subprocess.run(
            cmd, env=env, cwd=str(REPO_ROOT),
            stdout=log_f, stderr=subprocess.STDOUT, timeout=timeout_s,
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"worker phase={phase} exited {proc.returncode}; see {log_path}"
        )
    if not result_path.exists():
        raise RuntimeError(f"worker phase={phase} wrote no result; see {log_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))
