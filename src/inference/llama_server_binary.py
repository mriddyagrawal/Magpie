"""llama-server binary discovery + version verification.

Discovery order (first hit wins):
  1. `LLAMA_SERVER_PATH` env var (developer convenience, CI override)
  2. `<APP_DATA_DIR>/bin/llama-server` (where `just install-llama-server`
     puts it; same path the eventual `.app` bundle uses — see Plan #10
     and `Specs/llama_server_migration.md` "Bundling story")
  3. `<sys.argv[0] dir>/bin/llama-server` (Tauri-bundled future)
  4. `llama-server` on `PATH` (developer + brew install fallback)

If nothing's found OR the binary is older than `LLAMA_SERVER_MIN_VERSION`,
hard-fail at sidecar startup with a clear remediation message. Failing
here is much friendlier than the cryptic "model load returned -1" the
user would see at first inference attempt against an old binary.

Version format: llama.cpp tags releases like `b5400` (build number,
monotonically increasing). Comparing two `bNNNN` strings as integers
gives the right ordering. We're conservative — if the version string
doesn't match the expected pattern, treat it as "unknown" and warn,
but don't refuse to run.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from src.manifest import APP_DATA_DIR


_BIN_NAME = "llama-server" + (".exe" if sys.platform == "win32" else "")

# llama.cpp release tags look like `b5400` or `b5400-12-gabc123` (build
# number + commits-since + sha when built from a non-tag commit). We
# only care about the numeric part for comparisons.
# llama-server's `--version` ships in two shapes depending on the release
# vintage. Older builds emit the bare release-tag form `b5400`. Newer
# builds (b5400+ on macOS, observed 2026-05) emit `version: 5400 (sha)`
# with no `b` prefix — bare digits. We accept both, plus the embedded-tag
# form `b5400-12-gabc123` from local builds. Anchored to either a `b`
# preceded by a word boundary OR `version:` to avoid latching onto random
# 3-6 digit numbers in the surrounding text (commit hashes contain digits).
_VERSION_RE = re.compile(
    r"(?:\bb|version:\s*)(\d{3,6})\b",
    re.IGNORECASE,
)


class LlamaServerBinaryError(RuntimeError):
    """Binary missing OR too old. Carries a remediation message safe to
    surface to the user (no internal paths beyond what they need to fix)."""


def _candidate_paths() -> list[Path]:
    """All paths to check, in priority order. Filtered for existence by
    the caller."""
    out: list[Path] = []
    env_override = os.environ.get("LLAMA_SERVER_PATH", "").strip()
    if env_override:
        out.append(Path(env_override).expanduser())
    out.append(APP_DATA_DIR / "bin" / _BIN_NAME)

    # `.app` packaging future (Plan #10): the binary lives next to the
    # bundled python interpreter. Today this resolves to the venv's
    # bin dir, which is harmless — just won't have the binary there.
    try:
        argv0 = Path(sys.argv[0]).resolve().parent
        out.append(argv0 / "bin" / _BIN_NAME)
    except (OSError, ValueError):
        pass

    # PATH fallback (resolved by shutil.which, not a literal path).
    on_path = shutil.which(_BIN_NAME)
    if on_path:
        out.append(Path(on_path))
    return out


def find_llama_server() -> Path:
    """Resolve the llama-server binary or raise `LlamaServerBinaryError`
    with a remediation hint. Idempotent — caller can stash the result.

    The error message names every path we tried, in the order we tried
    them, so the user can drop the binary into the right place without
    grepping the source.
    """
    tried: list[str] = []
    for cand in _candidate_paths():
        tried.append(str(cand))
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
    raise LlamaServerBinaryError(
        "llama-server binary not found. Tried (in order):\n"
        + "\n".join(f"  - {p}" for p in tried)
        + "\n\nFix: run `just install-llama-server` to download the right "
        "binary for this platform into the first path. Or set "
        "LLAMA_SERVER_PATH=/absolute/path/to/llama-server."
    )


def parse_build_number(version_string: str) -> int | None:
    """Extract the `bNNNN` build number from `llama-server --version`
    output. Returns None when the format isn't what we expect — caller
    should warn-but-continue rather than refuse to run."""
    match = _VERSION_RE.search(version_string)
    if match:
        return int(match.group(1))
    return None


def get_binary_version(binary: Path) -> tuple[str, int | None]:
    """Run `llama-server --version`, return (raw_output, build_number).

    `build_number is None` when the output didn't match `bNNNN` — usually
    means a custom-built binary, not a release tag.
    """
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            # Modern macOS builds (b9000+) load the Metal library on
            # `--version`, which can take 12-15s on first invocation
            # because it compiles and caches shaders. 30s leaves
            # comfortable headroom; a binary that hangs longer than
            # that is genuinely broken.
            timeout=30,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise LlamaServerBinaryError(
            f"could not invoke `{binary} --version`: {e}. "
            "Re-download with `just install-llama-server`."
        ) from e

    raw = (result.stdout + result.stderr).strip()
    return raw, parse_build_number(raw)


def assert_min_version(binary: Path, min_version_tag: str) -> None:
    """Hard-fail if the binary is older than `min_version_tag`.

    `min_version_tag` is expected to look like `b5400`. Anything else
    is treated as "the user knows what they're doing" — we warn but
    don't block. Failing closed when the user explicitly overrides the
    pin would be more annoying than helpful.
    """
    expected = parse_build_number(min_version_tag)
    if expected is None:
        # User set a non-standard pin (custom build, etc.). Skip the check.
        print(
            f"  warn: LLAMA_SERVER_MIN_VERSION={min_version_tag!r} doesn't "
            f"look like a release tag (bNNNN); skipping version check.",
            file=sys.stderr,
        )
        return

    raw, found = get_binary_version(binary)
    if found is None:
        print(
            f"  warn: could not parse `{binary} --version` output "
            f"({raw[:120]!r}); proceeding anyway.",
            file=sys.stderr,
        )
        return

    if found < expected:
        raise LlamaServerBinaryError(
            f"llama-server is too old: {binary} reports build b{found}, "
            f"need >= {min_version_tag}. Re-download with "
            f"`just install-llama-server`."
        )


# Default min version pin — see `Specs/llama_server_migration.md` for
# the rationale. Override via `LLAMA_SERVER_MIN_VERSION` if you need to
# experiment with a newer or older tag.
DEFAULT_MIN_VERSION = "b9049"


def resolve_and_check() -> Path:
    """Find the binary AND verify it's recent enough. Single entrypoint
    the pool manager calls at startup. Caches nothing — caller does."""
    binary = find_llama_server()
    min_version = os.environ.get("LLAMA_SERVER_MIN_VERSION", DEFAULT_MIN_VERSION)
    assert_min_version(binary, min_version)
    return binary
