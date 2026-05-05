"""Build the magpie-sidecar binary using PyInstaller.

Must be run on the target platform — PyInstaller cannot cross-compile.
Run from the project root:

    uv run python scripts/build_sidecar.py

Output (placed in frontend/src-tauri/binaries/):
    Windows : magpie-sidecar-x86_64-pc-windows-msvc.exe
    macOS ARM: magpie-sidecar-aarch64-apple-darwin
    macOS x86: magpie-sidecar-x86_64-apple-darwin
    Linux    : magpie-sidecar-x86_64-unknown-linux-gnu

Tauri's externalBin strips the target triple at bundle time, so the
binary name in tauri.conf.json stays just "binaries/magpie-sidecar".
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
BINARIES_DIR = ROOT / "frontend" / "src-tauri" / "binaries"


def target_triple() -> str:
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        return "x86_64-pc-windows-msvc"
    if system == "Darwin":
        return "aarch64-apple-darwin" if machine == "arm64" else "x86_64-apple-darwin"
    if system == "Linux":
        return "x86_64-unknown-linux-gnu"

    raise RuntimeError(f"unsupported platform: {system} {machine}")


def main() -> None:
    triple = target_triple()
    is_windows = platform.system() == "Windows"
    output_name = f"magpie-sidecar-{triple}" + (".exe" if is_windows else "")

    print(f"Building magpie-sidecar for {triple}...")
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    # PyInstaller --add-data separator is ; on Windows, : elsewhere
    sep = ";" if is_windows else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "src/server.py",
        "--name", "magpie-sidecar",
        "--onefile",
        "--noconsole",
        "--noconfirm",
        # Heavy packages that use dynamic imports or include non-Python assets
        "--collect-all", "sentence_transformers",
        "--collect-all", "fastembed",
        "--collect-all", "qdrant_client",
        "--collect-all", "pymupdf",
        # Uvicorn loads its protocol/loop implementations dynamically
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        # src.* modules are lazy-imported inside endpoint functions
        "--hidden-import", "src.pipeline",
        "--hidden-import", "src.content",
        "--hidden-import", "src.stage2.db",
        "--hidden-import", "src.stage2",
        "--hidden-import", "src.stage2.__main__",
        "--hidden-import", "src.stage1",
        "--hidden-import", "src.manifest",
        "--hidden-import", "src.ingest",
        "--hidden-import", "src.ingest.walker",
        "--hidden-import", "src.ingest.common",
        "--hidden-import", "src.ingest.ignore",
        "--hidden-import", "src.router",
        # Bundle the src package so relative imports resolve at runtime
        "--add-data", f"src{sep}src",
        # Packages that call importlib.metadata.version() on themselves at import
        # time — PyInstaller strips .dist-info by default, so the lookup crashes.
        "--copy-metadata", "genai_prices",
        "--copy-metadata", "pydantic_ai",
    ]

    subprocess.run(cmd, cwd=ROOT, check=True)

    src_exe = ROOT / "dist" / ("magpie-sidecar.exe" if is_windows else "magpie-sidecar")
    dst_exe = BINARIES_DIR / output_name

    if dst_exe.exists():
        dst_exe.unlink()
    shutil.move(str(src_exe), dst_exe)

    size_mb = dst_exe.stat().st_size / 1024 / 1024
    print(f"\nDone: {dst_exe}")
    print(f"Size: {size_mb:.0f} MB")
    print(f"\nNext: pnpm tauri build")


if __name__ == "__main__":
    main()
