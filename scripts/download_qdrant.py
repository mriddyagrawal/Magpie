"""Download the Qdrant binary for the current platform.

Run from the project root:
    uv run python scripts/download_qdrant.py

Output (placed in frontend/src-tauri/binaries/):
    Windows : qdrant-x86_64-pc-windows-msvc.exe
    macOS ARM: qdrant-aarch64-apple-darwin
    macOS x86: qdrant-x86_64-apple-darwin
    Linux    : qdrant-x86_64-unknown-linux-gnu

Pass --force to re-download even if the binary already exists.
"""

import argparse
import platform
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
BINARIES_DIR = ROOT / "frontend" / "src-tauri" / "binaries"
QDRANT_VERSION = "v1.17.1"


def target_triple() -> tuple[str, str, bool]:
    """Returns (output_triple, download_triple, is_windows)."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        return "x86_64-pc-windows-msvc", "x86_64-pc-windows-msvc", True
    if system == "Darwin":
        if machine == "arm64":
            return "aarch64-apple-darwin", "aarch64-apple-darwin", False
        return "x86_64-apple-darwin", "x86_64-apple-darwin", False
    # Linux — use musl for maximum portability across distros
    return "x86_64-unknown-linux-gnu", "x86_64-unknown-linux-musl", False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download even if already present")
    args = parser.parse_args()

    triple, download_triple, is_windows = target_triple()
    ext = ".exe" if is_windows else ""
    output_name = f"qdrant-{triple}{ext}"
    dst = BINARIES_DIR / output_name

    if dst.exists() and not args.force:
        print(f"Qdrant already present: {dst}  (pass --force to re-download)")
        return

    BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    archive_ext = ".zip" if is_windows else ".tar.gz"
    archive_name = f"qdrant-{download_triple}{archive_ext}"
    url = (
        f"https://github.com/qdrant/qdrant/releases/download/"
        f"{QDRANT_VERSION}/{archive_name}"
    )
    tmp = BINARIES_DIR / archive_name

    print(f"Downloading Qdrant {QDRANT_VERSION} for {triple}...")
    urllib.request.urlretrieve(url, tmp, reporthook=_progress)
    print()

    print("Extracting...")
    if is_windows:
        with zipfile.ZipFile(tmp) as z:
            z.extract("qdrant.exe", BINARIES_DIR)
        (BINARIES_DIR / "qdrant.exe").replace(dst)
    else:
        with tarfile.open(tmp) as t:
            t.extract("qdrant", BINARIES_DIR)
        extracted = BINARIES_DIR / "qdrant"
        extracted.chmod(0o755)
        extracted.replace(dst)

    tmp.unlink()
    size_mb = dst.stat().st_size / 1024 / 1024
    print(f"Done: {dst}  ({size_mb:.0f} MB)")


def _progress(count: int, block: int, total: int) -> None:
    if total <= 0:
        return
    pct = min(count * block * 100 // total, 100)
    bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
    sys.stdout.write(f"\r  [{bar}] {pct}%")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
