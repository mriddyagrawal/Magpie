"""Cross-platform `llama-server` installer.

Replaces the older bash justfile recipe with a single Python module that
runs everywhere Magpie runs — macOS, Linux (x86_64 + arm64), and Windows
(PowerShell, cmd, Git Bash). All work goes through stdlib (`urllib`,
`tarfile`, `zipfile`, `pathlib`, `shutil`), so no curl / unzip / find
dependency. See `Specs/llama_server_migration.md` PR 4 for the why.

Public surface:
  - `download_and_install(version=None, gpu=None, *, skip_mmproj=False)` — full path
  - `select_asset(os_name, arch, gpu)` — returns the release-asset filename
  - `extract_to(archive_path, dest_dir)` — handles .tar.gz + .zip uniformly
  - `__main__` — `python -m src.tools.install_llama_server`

Env vars (read by main):
  LLAMA_SERVER_VERSION       release tag (default: DEFAULT_VERSION)
  LLAMA_SERVER_GPU           gpu hint (cpu / vulkan / cuda-12.4 / cuda-13.3)
                             default: per-platform safe pick (Metal on
                             macOS, CPU elsewhere)
  SKIP_MMPROJ_DOWNLOAD       set to 1 to skip the weights + projector download
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# The pinned llama.cpp release.
#
# Must be >= b10000-era (2026-06-10). The `lfm2` architecture itself has
# been supported since 2025-07 (PR #14620) with vision via PR #15347, so
# the previous pin b9049 (2026-05-06) LOADS LFM2.5-VL fine — which is the
# trap. Three later fixes are what force the bump:
#
#   #24178  2026-06-05  unify and fix LFM2/LFM2.5 tool parser
#   #24234  2026-06-06  fix LFM2/LFM2.5 reasoning round-trip and <think> leak
#   #24377  2026-06-10  chat: fix LFM2/LFM2.5 ignoring json_schema   <-- critical
#
# On a pre-#24377 build, llama-server silently IGNORES the `json_schema`
# response_format for this model family. Structured output would appear to
# work while the GBNF grammar was never applied, leaving parse_json_with_repair
# to carry every summarize call — degraded extraction, no error anywhere.
# That is precisely the "model swap that doesn't honor the parameter" case
# `src.llm.LocalAgent` warns about.
DEFAULT_VERSION = "b10502"

# NOTE: there is deliberately no DEFAULT_MMPROJ_REPO / default-quant constant
# here any more. Those duplicated what src/inference/profiles.py already
# declares, and the copies drifted: this module defaulted the projector to
# BF16 while the profile asked for Q8_0, so `just install-llama-server`
# fetched an 822 MB file the runtime ignored and then re-fetched the right
# one at first spawn. `_ensure_mmproj` now reads the active profile.


class InstallError(RuntimeError):
    """Anything user-visible — printed to stderr and exits 1 from main."""


# ---------------------------------------------------------------------------
# Asset selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetSpec:
    """One row of the asset-selection table.

    `name_template` is formatted with `version=...` to get the actual
    file name. `archive_kind` controls extraction (`tar.gz` vs `zip`)
    and what `--bin-name` to expect inside (`llama-server` vs
    `llama-server.exe`).
    """

    name_template: str
    archive_kind: str  # "tar.gz" or "zip"
    bin_name: str  # "llama-server" or "llama-server.exe"
    extra: tuple[str, ...] = ()  # sibling assets to also download (e.g. cudart)


# Platform tables. Keys are (os_name, arch_alias, gpu). `arch_alias`
# normalizes platform.machine() outputs into the few buckets release
# names actually use (`arm64` covers Apple Silicon + Linux ARM64; `x86_64`
# covers everything Intel/AMD 64-bit).
_TABLE: dict[tuple[str, str, str], AssetSpec] = {
    # --- macOS ---
    ("darwin", "arm64", "metal"): AssetSpec(
        "llama-{version}-bin-macos-arm64.tar.gz", "tar.gz", "llama-server"
    ),
    ("darwin", "x86_64", "metal"): AssetSpec(
        "llama-{version}-bin-macos-x64.tar.gz", "tar.gz", "llama-server"
    ),
    # --- Linux x86_64 ---
    ("linux", "x86_64", "cpu"): AssetSpec(
        "llama-{version}-bin-ubuntu-x64.tar.gz", "tar.gz", "llama-server"
    ),
    ("linux", "x86_64", "vulkan"): AssetSpec(
        "llama-{version}-bin-ubuntu-vulkan-x64.tar.gz", "tar.gz", "llama-server"
    ),
    # --- Linux arm64 ---
    ("linux", "arm64", "cpu"): AssetSpec(
        "llama-{version}-bin-ubuntu-arm64.tar.gz", "tar.gz", "llama-server"
    ),
    ("linux", "arm64", "vulkan"): AssetSpec(
        "llama-{version}-bin-ubuntu-vulkan-arm64.tar.gz", "tar.gz", "llama-server"
    ),
    # --- Windows x86_64 ---
    ("windows", "x86_64", "cpu"): AssetSpec(
        "llama-{version}-bin-win-cpu-x64.zip", "zip", "llama-server.exe"
    ),
    ("windows", "x86_64", "vulkan"): AssetSpec(
        "llama-{version}-bin-win-vulkan-x64.zip", "zip", "llama-server.exe"
    ),
    ("windows", "x86_64", "cuda-12.4"): AssetSpec(
        "llama-{version}-bin-win-cuda-12.4-x64.zip",
        "zip",
        "llama-server.exe",
        extra=("cudart-llama-bin-win-cuda-12.4-x64.zip",),
    ),
    # CUDA 13.1 was renamed 13.3 upstream somewhere between b9049 and
    # b10502 — the 13.1 asset no longer exists on current releases, so the
    # old entry 404s on any recent pin. Verified against b10502's asset list.
    ("windows", "x86_64", "cuda-13.3"): AssetSpec(
        "llama-{version}-bin-win-cuda-13.3-x64.zip",
        "zip",
        "llama-server.exe",
        extra=("cudart-llama-bin-win-cuda-13.3-x64.zip",),
    ),
    # --- Windows arm64 ---
    ("windows", "arm64", "cpu"): AssetSpec(
        "llama-{version}-bin-win-cpu-arm64.zip", "zip", "llama-server.exe"
    ),
    ("windows", "arm64", "cuda-13.4"): AssetSpec(
        "llama-{version}-bin-win-cuda-13.4-arm64.zip",
        "zip",
        "llama-server.exe",
        extra=("cudart-llama-bin-win-cuda-13.4-arm64.zip",),
    ),
}


def _normalize_arch(machine: str) -> str:
    """Collapse platform.machine() variants into release-name buckets."""
    m = machine.lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x86_64"
    return m  # passthrough; will fail downstream with a useful message


def _default_gpu(os_name: str) -> str:
    """Per-platform safe default. macOS = Metal (baked into all builds);
    Linux + Windows = CPU (works without any GPU runtime). Users with
    NVIDIA / AMD / Intel GPUs override via LLAMA_SERVER_GPU=..."""
    if os_name == "darwin":
        return "metal"
    return "cpu"


def select_asset(
    os_name: str,
    arch: str,
    gpu: Optional[str] = None,
    *,
    version: str = DEFAULT_VERSION,
) -> tuple[AssetSpec, str]:
    """Look up the right release asset for the given (os, arch, gpu).

    Returns `(spec, formatted_filename)`. Raises `InstallError` with a
    full enumeration of the missing combo + supported alternatives so
    the user can fix their environment without grepping the source.
    """
    os_norm = os_name.lower()
    arch_norm = _normalize_arch(arch)
    gpu_norm = (gpu or _default_gpu(os_norm)).lower()
    key = (os_norm, arch_norm, gpu_norm)
    if key in _TABLE:
        spec = _TABLE[key]
        return spec, spec.name_template.format(version=version)

    # Build a useful error: list every combo we DO support for the
    # detected OS+arch so the user can pick a different gpu= flag.
    same_platform = sorted(
        f"  - LLAMA_SERVER_GPU={g}"
        for (o, a, g) in _TABLE
        if o == os_norm and a == arch_norm
    )
    if same_platform:
        details = (
            f"detected platform {os_norm}/{arch_norm} is supported, but "
            f"GPU hint {gpu_norm!r} isn't. Try one of:\n"
            + "\n".join(same_platform)
        )
    else:
        details = (
            f"unsupported OS/arch combination: {os_norm}/{arch_norm}. "
            "Supported combinations are:\n"
            + "\n".join(
                f"  - {o}/{a} (gpu={g})" for (o, a, g) in sorted(_TABLE)
            )
            + "\n\nDownload the binary manually from "
            "https://github.com/ggml-org/llama.cpp/releases and set "
            "LLAMA_SERVER_PATH=/abs/path/to/llama-server in .env."
        )
    raise InstallError(details)


# ---------------------------------------------------------------------------
# Download + extract
# ---------------------------------------------------------------------------

_RELEASE_URL = (
    "https://github.com/ggml-org/llama.cpp/releases/download/{version}/{asset}"
)


def _download(url: str, dest: Path, *, label: str) -> None:
    """Stream `url` to `dest` with a coarse-grained progress indicator
    (one dot per ~MB). stdlib `urllib` instead of curl because we want
    zero shell dependencies on Windows."""
    print(f"==> Downloading {label} from {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(url) as resp:  # noqa: S310 (controlled URL)
            total = resp.getheader("Content-Length")
            total_mb = int(total) / 1e6 if total else None
            written = 0
            tick = 0
            with open(dest, "wb") as out:
                while True:
                    buf = resp.read(1 << 20)  # 1 MiB chunks
                    if not buf:
                        break
                    out.write(buf)
                    written += len(buf)
                    tick += 1
                    if tick % 4 == 0:
                        if total_mb:
                            pct = 100 * written / int(total)
                            print(
                                f"    {written/1e6:6.1f} MB / "
                                f"{total_mb:6.1f} MB  ({pct:5.1f}%)",
                                file=sys.stderr,
                                flush=True,
                            )
                        else:
                            print(
                                f"    {written/1e6:6.1f} MB",
                                file=sys.stderr,
                                flush=True,
                            )
    except urllib.error.HTTPError as e:
        raise InstallError(
            f"download failed ({e.code} {e.reason}) for {url}. "
            "Confirm the version tag exists and the asset name is right; "
            "https://github.com/ggml-org/llama.cpp/releases lists every "
            "asset per release."
        ) from e
    except urllib.error.URLError as e:
        raise InstallError(
            f"network error downloading {url}: {e.reason}. "
            "Check connectivity / proxy settings."
        ) from e


def extract_to(archive: Path, dest: Path, *, kind: str) -> None:
    """Extract a .tar.gz or .zip archive to `dest`. Pure stdlib."""
    dest.mkdir(parents=True, exist_ok=True)
    if kind == "tar.gz":
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest)  # noqa: S202 (controlled archive)
    elif kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)  # noqa: S202 (controlled archive)
    else:
        raise InstallError(f"unknown archive kind: {kind!r}")


def _find_binary(extracted_root: Path, bin_name: str) -> Path:
    """Locate the `llama-server` binary inside the extracted release tree.

    Modern releases nest under `build/bin/`; older ones flatten. We
    rglob to be tolerant of either layout (and any future variations).
    """
    for cand in extracted_root.rglob(bin_name):
        if cand.is_file():
            return cand
    raise InstallError(
        f"no {bin_name} found in extracted archive at {extracted_root}. "
        "The release layout may have changed; report this with the version tag."
    )


def _copy_runtime_libs(bin_src_dir: Path, dest: Path) -> int:
    """Copy sibling shared libraries the binary needs (libllama.dylib /
    libggml-metal.dylib on macOS, .so on Linux, .dll on Windows). Without
    these the binary fails to launch with a dyld / loader error."""
    n = 0
    for ext in (".dylib", ".so", ".dll"):
        for lib in bin_src_dir.glob(f"*{ext}"):
            shutil.copy2(lib, dest / lib.name)
            n += 1
    return n


def _strip_macos_quarantine(*paths: Path) -> None:
    """Strip com.apple.quarantine xattr so Gatekeeper doesn't block the
    downloaded binary on first execution. macOS only; no-op elsewhere.
    Shells out because there's no portable Python equivalent."""
    if sys.platform != "darwin":
        return
    for p in paths:
        if not p.exists():
            continue
        # `-r` recurses; `2>/dev/null || true` equivalent via check=False.
        # Errors here are typically "no quarantine attr" which is fine.
        subprocess.run(  # noqa: S603,S607 (controlled args)
            ["xattr", "-d", "com.apple.quarantine", str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def _verify_version(binary: Path) -> None:
    """Print the binary's version. Diagnostic only — `LlamaServerBinary`
    enforces the min-version check at runtime."""
    print("==> Verifying version (Metal probe takes ~12s on first run)",
          file=sys.stderr)
    try:
        # 60s is overkill but cheap insurance against cold metallib caches.
        result = subprocess.run(  # noqa: S603 (controlled args)
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise InstallError(
            f"could not invoke `{binary} --version`: {e}. "
            "Binary may be corrupt or for the wrong platform; re-download."
        ) from e
    out = (result.stdout + result.stderr).strip().splitlines()
    for line in out:
        if line.startswith(("version:", "build", "built")):
            print(f"    {line}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def _resolve_dest_dir() -> Path:
    """Where to install the binary. Always `<APP_DATA_DIR>/bin/` so the
    discovery code in `llama_server_binary.py` finds it without env
    overrides."""
    # Imported here (not at module top) to avoid a hard dep when this
    # module is imported from a context that doesn't need APP_DATA_DIR
    # (e.g., a unit test stubbing out the install path).
    from src.manifest import APP_DATA_DIR

    return APP_DATA_DIR / "bin"


def download_and_install(
    version: Optional[str] = None,
    gpu: Optional[str] = None,
    *,
    skip_mmproj: bool = False,
) -> Path:
    """End-to-end install. Returns the path to the installed binary."""
    version = version or os.environ.get("LLAMA_SERVER_VERSION", DEFAULT_VERSION)
    gpu = gpu or os.environ.get("LLAMA_SERVER_GPU") or None

    os_name = sys.platform
    if os_name.startswith("linux"):
        os_name = "linux"
    elif os_name == "darwin":
        os_name = "darwin"
    elif os_name in ("win32", "cygwin"):
        os_name = "windows"
    arch = platform.machine() or "unknown"

    spec, asset_name = select_asset(os_name, arch, gpu, version=version)
    dest = _resolve_dest_dir()
    dest.mkdir(parents=True, exist_ok=True)

    print(
        f"==> Installing llama-server {version} for {os_name}/{arch} "
        f"(gpu={gpu or _default_gpu(os_name)})",
        file=sys.stderr,
    )

    with tempfile.TemporaryDirectory(prefix="llama-install-") as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / asset_name
        url = _RELEASE_URL.format(version=version, asset=asset_name)
        _download(url, archive_path, label=asset_name)

        extracted = tmp_path / "extracted"
        print(f"==> Extracting to {dest}", file=sys.stderr)
        extract_to(archive_path, extracted, kind=spec.archive_kind)

        bin_src = _find_binary(extracted, spec.bin_name)
        bin_dest = dest / spec.bin_name
        shutil.copy2(bin_src, bin_dest)
        n_libs = _copy_runtime_libs(bin_src.parent, dest)
        bin_dest.chmod(0o755)

        # Extra archives (Windows CUDA needs cudart-*.zip alongside).
        for extra in spec.extra:
            extra_url = _RELEASE_URL.format(version=version, asset=extra)
            extra_archive = tmp_path / extra
            try:
                _download(extra_url, extra_archive, label=extra)
            except InstallError as e:
                print(
                    f"  warn: extra asset {extra!r} could not be fetched: {e}. "
                    "If runtime fails with missing DLLs, install the matching "
                    "CUDA toolkit on the host.",
                    file=sys.stderr,
                )
                continue
            extra_extracted = tmp_path / "extra-extracted"
            extract_to(extra_archive, extra_extracted, kind="zip")
            n_libs += _copy_runtime_libs(extra_extracted, dest)

        _strip_macos_quarantine(
            bin_dest, *[dest / lib.name for lib in dest.glob("*.dylib")]
        )

        print(
            f"==> Installed binary + {n_libs} runtime libs to {dest}",
            file=sys.stderr,
        )

    _verify_version(bin_dest)
    print(f"==> Installed to: {bin_dest}", file=sys.stderr)

    if not skip_mmproj and os.environ.get("SKIP_MMPROJ_DOWNLOAD") != "1":
        _ensure_mmproj()
    else:
        print(
            "==> Skipping mmproj download (SKIP_MMPROJ_DOWNLOAD=1). "
            "Vision will lazy-download on first use.",
            file=sys.stderr,
        )

    print("==> done.", file=sys.stderr)
    return bin_dest


def _ensure_mmproj() -> None:
    """Pre-download the model weights AND the vision projector so the first
    local inference doesn't stall on a multi-GB fetch.

    Everything is read off the ACTIVE PROFILE rather than re-declared here.
    That matters: this function used to hardcode `BF16` as the projector
    fallback while the profile asked for `Q8_0`, so `just install-llama-server`
    would happily fetch an 822 MB projector the runtime then ignored, and
    re-fetch the right one at first spawn. Two sources of truth, ~300 MB
    wasted, no error.

    It also only ever fetched the projector, despite the projector being the
    SMALLER of the two files — the weights are what actually make a first
    query hang, and they were left to download lazily mid-inference.

    Imported lazily so the module stays testable without huggingface_hub.
    """
    try:
        from src.inference.model_downloader import ensure_mmproj, ensure_model
        from src.inference.profiles import default_text_profile, get_profile
    except ImportError as e:
        raise InstallError(
            f"cannot import the inference layer: {e}. "
            "Run `just sync-environment` first."
        ) from e

    args = get_profile(default_text_profile()).args

    # Weights. Env still wins so an explicit LOCAL_MODEL/LOCAL_QUANT override
    # is honored — but the DEFAULT now comes from the profile, not a copy.
    repo = os.environ.get("LOCAL_MODEL", args.repo_id)
    quant = os.environ.get("LOCAL_QUANT", args.quant)
    print(f"==> Pre-downloading model weights: {repo} :: {quant}", file=sys.stderr)
    print("    First-time only; cached under $APP_DATA_DIR/cache/hub/.", file=sys.stderr)
    p = ensure_model(repo, quant)
    print(f"    cached at {p}", file=sys.stderr)

    if not args.mmproj_repo_id:
        print("==> Profile is text-only; no projector to fetch.", file=sys.stderr)
        return

    mm_repo = os.environ.get("LOCAL_MMPROJ_REPO", args.mmproj_repo_id)
    mm_variant = os.environ.get("LOCAL_MMPROJ_VARIANT", args.mmproj_variant)
    print(
        f"==> Pre-downloading vision projector: {mm_repo} :: {mm_variant}",
        file=sys.stderr,
    )
    p = ensure_mmproj(mm_repo, mm_variant)
    print(f"    cached at {p}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main(argv: Optional[Iterable[str]] = None) -> int:
    """`python -m src.tools.install_llama_server`. Reads env vars; no flags
    today (keeping CLI surface minimal — env is the same plumbing the
    runtime already uses)."""
    try:
        download_and_install()
    except InstallError as e:
        print(f"\nERROR: {e}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
