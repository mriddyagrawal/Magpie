"""Unit tests for the cross-platform llama-server installer.

No real network, no real archives downloaded from the internet — every
test either uses the in-memory asset table or builds a synthetic
tarball / zip in `tmp_path` and round-trips it through the extractor.

The integration ("does it actually install on macOS?") is validated
manually by `just install-llama-server`; can't gate that in CI without
a real network and ~30 MB of disk per run.
"""

from __future__ import annotations

import io
import sys
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools.install_llama_server import (
    DEFAULT_VERSION,
    AssetSpec,
    InstallError,
    _normalize_arch,
    _default_gpu,
    _find_binary,
    _copy_runtime_libs,
    extract_to,
    select_asset,
)


# ---------------------------------------------------------------------------
# arch normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "machine, expected",
    [
        ("arm64", "arm64"),
        ("aarch64", "arm64"),
        ("ARM64", "arm64"),
        ("x86_64", "x86_64"),
        ("AMD64", "x86_64"),
        ("amd64", "x86_64"),
        ("riscv64", "riscv64"),  # passthrough — fails downstream w/ message
    ],
)
def test_normalize_arch(machine, expected):
    assert _normalize_arch(machine) == expected


# ---------------------------------------------------------------------------
# default-gpu choice per OS
# ---------------------------------------------------------------------------

def test_default_gpu_macos_is_metal():
    """macOS releases bake Metal in — the gpu key picks the asset name."""
    assert _default_gpu("darwin") == "metal"


def test_default_gpu_linux_is_cpu():
    """Default to CPU on Linux for max compatibility — users with NVIDIA /
    AMD GPUs override via LLAMA_SERVER_GPU=cuda-12.4 / vulkan."""
    assert _default_gpu("linux") == "cpu"


def test_default_gpu_windows_is_cpu():
    assert _default_gpu("windows") == "cpu"


# ---------------------------------------------------------------------------
# select_asset: the load-bearing dispatch table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "os_name, arch, gpu, expected_substr, expected_kind, expected_bin",
    [
        # macOS
        ("darwin", "arm64", None, "macos-arm64.tar.gz", "tar.gz", "llama-server"),
        ("darwin", "x86_64", None, "macos-x64.tar.gz", "tar.gz", "llama-server"),
        # Linux x86_64
        ("linux", "x86_64", "cpu", "ubuntu-x64.tar.gz", "tar.gz", "llama-server"),
        ("linux", "x86_64", "vulkan", "ubuntu-vulkan-x64.tar.gz", "tar.gz", "llama-server"),
        # Linux arm64 — Rahul on a Pi or Graviton
        ("linux", "aarch64", "cpu", "ubuntu-arm64.tar.gz", "tar.gz", "llama-server"),
        ("linux", "arm64", "vulkan", "ubuntu-vulkan-arm64.tar.gz", "tar.gz", "llama-server"),
        # Windows x86_64
        ("windows", "x86_64", "cpu", "win-cpu-x64.zip", "zip", "llama-server.exe"),
        ("windows", "amd64", "vulkan", "win-vulkan-x64.zip", "zip", "llama-server.exe"),
        ("windows", "x86_64", "cuda-12.4", "win-cuda-12.4-x64.zip", "zip", "llama-server.exe"),
        ("windows", "x86_64", "cuda-13.1", "win-cuda-13.1-x64.zip", "zip", "llama-server.exe"),
        # Windows arm64
        ("windows", "arm64", "cpu", "win-cpu-arm64.zip", "zip", "llama-server.exe"),
    ],
)
def test_select_asset_table(
    os_name, arch, gpu, expected_substr, expected_kind, expected_bin
):
    spec, name = select_asset(os_name, arch, gpu, version=DEFAULT_VERSION)
    assert expected_substr in name
    assert DEFAULT_VERSION in name
    assert spec.archive_kind == expected_kind
    assert spec.bin_name == expected_bin


def test_select_asset_unsupported_combo_lists_alternatives():
    """Asking for an unsupported (os, arch, gpu) combo must surface every
    same-platform alternative so the user can fix LLAMA_SERVER_GPU."""
    with pytest.raises(InstallError) as exc:
        select_asset("linux", "x86_64", "rocm")  # not in our table
    msg = str(exc.value)
    assert "linux/x86_64" in msg
    assert "LLAMA_SERVER_GPU=cpu" in msg
    assert "LLAMA_SERVER_GPU=vulkan" in msg


def test_select_asset_unsupported_platform_lists_supported_set():
    """An OS/arch we don't support at all must dump the full supported
    matrix so the user knows what to switch to."""
    with pytest.raises(InstallError) as exc:
        select_asset("freebsd", "x86_64", None)
    msg = str(exc.value)
    assert "unsupported OS/arch" in msg
    assert "darwin/arm64" in msg
    assert "linux/x86_64" in msg
    assert "windows/x86_64" in msg
    assert "LLAMA_SERVER_PATH" in msg  # remediation hint


def test_cuda_specs_request_runtime_bundle():
    """Windows CUDA paths can't run without the cudart DLLs. select_asset
    must declare the cudart-* sibling archive in `extra` so the installer
    fetches both."""
    spec, _ = select_asset("windows", "x86_64", "cuda-12.4", version=DEFAULT_VERSION)
    assert spec.extra
    assert any("cudart" in e for e in spec.extra)


# ---------------------------------------------------------------------------
# extract_to: round-trip a synthetic archive
# ---------------------------------------------------------------------------

def _make_synthetic_release_tarball(dest: Path, bin_name: str = "llama-server"):
    """Build a tar.gz that mimics a real release layout: binary nested
    under build/bin/, a sibling .so, plus a junk file."""
    with tarfile.open(dest, "w:gz") as tf:
        # the binary
        bin_data = b"#!/bin/sh\necho fake llama-server\n"
        info = tarfile.TarInfo(name=f"build/bin/{bin_name}")
        info.size = len(bin_data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(bin_data))
        # a runtime library next to it
        lib_data = b"\x7fELFfake-shared-lib"
        info = tarfile.TarInfo(name="build/bin/libllama.so")
        info.size = len(lib_data)
        info.mode = 0o644
        tf.addfile(info, io.BytesIO(lib_data))
        # something irrelevant
        info = tarfile.TarInfo(name="LICENSE")
        info.size = 4
        tf.addfile(info, io.BytesIO(b"MIT\n"))


def _make_synthetic_release_zip(dest: Path, bin_name: str = "llama-server.exe"):
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(f"build/bin/{bin_name}", b"MZfakeexe")
        zf.writestr("build/bin/llama.dll", b"MZfakedll")
        zf.writestr("LICENSE", "MIT\n")


def test_extract_to_handles_tar_gz(tmp_path):
    archive = tmp_path / "rel.tar.gz"
    _make_synthetic_release_tarball(archive)
    out = tmp_path / "extracted"
    extract_to(archive, out, kind="tar.gz")
    assert (out / "build" / "bin" / "llama-server").is_file()
    assert (out / "build" / "bin" / "libllama.so").is_file()


def test_extract_to_handles_zip(tmp_path):
    archive = tmp_path / "rel.zip"
    _make_synthetic_release_zip(archive)
    out = tmp_path / "extracted"
    extract_to(archive, out, kind="zip")
    assert (out / "build" / "bin" / "llama-server.exe").is_file()
    assert (out / "build" / "bin" / "llama.dll").is_file()


def test_extract_to_unknown_kind_raises(tmp_path):
    with pytest.raises(InstallError):
        extract_to(tmp_path / "x", tmp_path / "y", kind="rar")


# ---------------------------------------------------------------------------
# _find_binary: tolerant of release-layout variations
# ---------------------------------------------------------------------------

def test_find_binary_in_nested_tree(tmp_path):
    target = tmp_path / "build" / "bin" / "llama-server"
    target.parent.mkdir(parents=True)
    target.write_text("fake")
    found = _find_binary(tmp_path, "llama-server")
    assert found == target


def test_find_binary_in_flat_tree(tmp_path):
    """Older releases put the binary at the root of the archive."""
    target = tmp_path / "llama-server"
    target.write_text("fake")
    assert _find_binary(tmp_path, "llama-server") == target


def test_find_binary_missing_raises(tmp_path):
    """Empty extracted tree → useful error pointing at the version tag."""
    with pytest.raises(InstallError) as exc:
        _find_binary(tmp_path, "llama-server")
    assert "no llama-server" in str(exc.value)
    assert "release layout" in str(exc.value)


def test_find_binary_finds_exe_on_windows_layout(tmp_path):
    """The bin_name parameter is what's looked for — `.exe` on Windows
    is set by AssetSpec, not detected here."""
    target = tmp_path / "build" / "bin" / "llama-server.exe"
    target.parent.mkdir(parents=True)
    target.write_text("fake")
    assert _find_binary(tmp_path, "llama-server.exe") == target


# ---------------------------------------------------------------------------
# _copy_runtime_libs: every shared-library extension gets picked up
# ---------------------------------------------------------------------------

def test_copy_runtime_libs_copies_all_extensions(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "libllama.dylib").write_bytes(b"mac")
    (src / "libllama.so").write_bytes(b"linux")
    (src / "llama.dll").write_bytes(b"windows")
    # Should not be copied (binary itself, not a library)
    (src / "llama-server").write_bytes(b"binary")
    n = _copy_runtime_libs(src, dest)
    assert n == 3
    assert (dest / "libllama.dylib").exists()
    assert (dest / "libllama.so").exists()
    assert (dest / "llama.dll").exists()
    assert not (dest / "llama-server").exists()


def test_copy_runtime_libs_zero_when_empty(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    (src / "binary-only").write_text("fake")
    assert _copy_runtime_libs(src, dest) == 0


# ---------------------------------------------------------------------------
# macOS quarantine helper: no-op on non-macOS
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only branch")
def test_strip_quarantine_runs_xattr_on_darwin(tmp_path):
    """On macOS, the helper shells out to `xattr`. We can't easily mock
    a real fs xattr in a unit test, so check the helper completes without
    raising on a fresh file (no attr to strip = exit 1, but check=False
    means we ignore that)."""
    from src.tools.install_llama_server import _strip_macos_quarantine

    p = tmp_path / "fake-binary"
    p.write_text("hi")
    # Should be a no-op (file has no quarantine attr) and not raise.
    _strip_macos_quarantine(p)


def test_strip_quarantine_is_noop_on_non_macos(tmp_path, monkeypatch):
    """On Linux / Windows the helper returns immediately without trying
    to invoke xattr (which doesn't exist)."""
    from src.tools.install_llama_server import _strip_macos_quarantine

    monkeypatch.setattr(sys, "platform", "linux")
    # No exception even though /tmp/fake doesn't exist; doesn't shell out.
    _strip_macos_quarantine(Path("/tmp/does-not-exist"))
