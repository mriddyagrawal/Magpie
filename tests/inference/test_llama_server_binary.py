"""Unit tests for binary discovery + version parsing. No subprocess."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.inference.llama_server_binary import (
    DEFAULT_MIN_VERSION,
    LlamaServerBinaryError,
    assert_min_version,
    find_llama_server,
    parse_build_number,
)


# ---------------------------------------------------------------------------
# parse_build_number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("version: b5400", 5400),
        ("llama-server build b5400-12-gabc123", 5400),
        ("b5400", 5400),
        ("version: b9999 (release)", 9999),
        # Regression: the actual macOS-arm64 build of b5400 reports
        # `version: 5400 (sha)` with no `b` prefix — observed against
        # llama-b5400-bin-macos-arm64.zip, 2026-05. If the regex stops
        # accepting this shape, the min-version check silently no-ops
        # because get_binary_version returns build_number=None.
        ("version: 5400 (c6a2c9e7)", 5400),
        (
            "version: 5400 (c6a2c9e7)\nbuilt with Apple clang version 15.0.0",
            5400,
        ),
        # Regression: b10502 (2026-08) moved to a semver line with the build
        # number behind the word `build`:
        #   `version: 0.1.2-dev (build 10502, commit 0adcc3bb5)`
        # The old regex matched neither (`version:` is followed by the semver,
        # not digits), so parse_build_number returned None and the MIN_VERSION
        # guard warned-and-proceeded — reducing to advisory exactly the check
        # that keeps pre-#24377 binaries (which silently ignore json_schema
        # for LFM2/2.5) from being used. Caught live during the first LFM2.5
        # inference test.
        (
            "version: 0.1.2-dev (build 10502, commit 0adcc3bb5)\n"
            "built with AppleClang 21.0.0.21000101 for Darwin arm64",
            10502,
        ),
        # The commit sha next to `build NNNNN` must not be latched onto.
        ("(build 10502, commit 0adcc3bb5)", 10502),
        ("commit abc123 (no tag)", None),
        ("", None),
        ("just some text", None),
    ],
)
def test_parse_build_number(raw, expected):
    assert parse_build_number(raw) == expected


# ---------------------------------------------------------------------------
# find_llama_server (discovery order)
# ---------------------------------------------------------------------------

def test_env_var_takes_priority(monkeypatch, tmp_path):
    """LLAMA_SERVER_PATH wins over every other discovery path."""
    fake_bin = tmp_path / "fake-llama-server"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("LLAMA_SERVER_PATH", str(fake_bin))
    found = find_llama_server()
    assert found == fake_bin


def test_missing_binary_lists_paths_tried(monkeypatch, tmp_path):
    """Error message must enumerate every checked path so users can fix.
    Redirects APP_DATA_DIR to a clean tmp tree so a real install on the
    dev machine doesn't satisfy discovery and skip the failure path."""
    monkeypatch.setenv("LLAMA_SERVER_PATH", str(tmp_path / "does-not-exist"))
    with patch(
        "src.inference.llama_server_binary.APP_DATA_DIR", tmp_path
    ), patch("shutil.which", return_value=None):
        with pytest.raises(LlamaServerBinaryError) as exc:
            find_llama_server()
    msg = str(exc.value)
    assert "does-not-exist" in msg
    assert "just install-llama-server" in msg
    assert "LLAMA_SERVER_PATH" in msg


def test_app_data_dir_path_is_checked(monkeypatch, tmp_path):
    """When the env override is unset, APP_DATA_DIR/bin/llama-server is
    one of the paths we look at — that's where install-llama-server
    stages the binary, AND where the .app bundle would put it.
    Redirects APP_DATA_DIR to a clean tmp tree (see test above)."""
    monkeypatch.delenv("LLAMA_SERVER_PATH", raising=False)
    with patch(
        "src.inference.llama_server_binary.APP_DATA_DIR", tmp_path
    ), patch("shutil.which", return_value=None):
        with pytest.raises(LlamaServerBinaryError) as exc:
            find_llama_server()
    msg = str(exc.value)
    # The APP_DATA_DIR path appears even when the file isn't there —
    # the user needs to know we checked.
    assert "/bin/llama-server" in msg or "\\bin\\llama-server" in msg


# ---------------------------------------------------------------------------
# assert_min_version
# ---------------------------------------------------------------------------

def test_version_check_passes_when_newer(tmp_path, monkeypatch):
    """A binary newer than the pin should be accepted silently."""
    fake_bin = tmp_path / "fake-llama-server"
    fake_bin.write_text("ok")
    fake_bin.chmod(0o755)
    with patch(
        "src.inference.llama_server_binary.get_binary_version",
        return_value=("version: b5500", 5500),
    ):
        # Should not raise.
        assert_min_version(fake_bin, "b5400")


def test_version_check_hard_fails_when_older(tmp_path):
    """Older binary → LlamaServerBinaryError with the version + remediation."""
    fake_bin = tmp_path / "fake-llama-server"
    with patch(
        "src.inference.llama_server_binary.get_binary_version",
        return_value=("version: b5300", 5300),
    ):
        with pytest.raises(LlamaServerBinaryError) as exc:
            assert_min_version(fake_bin, "b5400")
    msg = str(exc.value)
    assert "b5300" in msg
    assert "b5400" in msg
    assert "install-llama-server" in msg


def test_version_check_warns_when_pin_format_unknown(tmp_path, capsys):
    """A non-bNNNN pin (e.g. user is testing a custom build) skips the
    check with a stderr warning. We don't want to refuse to run."""
    fake_bin = tmp_path / "fake-llama-server"
    with patch(
        "src.inference.llama_server_binary.get_binary_version",
        return_value=("custom build", None),
    ):
        # Should not raise even though the pin is non-standard.
        assert_min_version(fake_bin, "custom-tag-xyz")
    captured = capsys.readouterr()
    assert "warn" in captured.err
    assert "custom-tag-xyz" in captured.err


def test_default_min_version_supports_gemma4():
    """Document the default pin in code so a regression catches it.
    Must be a build that knows the `gemma4` model architecture (added
    upstream after Gemma 4's 2026-04 release). b5400 (mid-2024) DOES
    NOT — model load bails with `unknown model architecture: gemma4`.
    Verified empirically against the macOS-arm64 build of b9049, which
    loads the unsloth/gemma-4-E4B-it-GGUF model successfully."""
    parsed = parse_build_number(DEFAULT_MIN_VERSION)
    assert parsed is not None and parsed >= 9049, (
        f"DEFAULT_MIN_VERSION pin {DEFAULT_MIN_VERSION!r} is too old to "
        f"load Gemma 4 GGUFs. Bump to a release that supports the gemma4 "
        f"architecture."
    )
