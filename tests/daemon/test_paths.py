"""Filesystem path / authkey tests — no daemon spawn, just helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.daemon import paths


def test_state_dir_is_creatable(monkeypatch, tmp_path: Path):
    """state_dir() must create its directory if missing."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    d = paths.state_dir()
    assert d.exists()
    assert d.is_dir()


def test_authkey_persists(monkeypatch, tmp_path: Path):
    """Calling get_or_create_authkey twice returns the same bytes."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    k1 = paths.get_or_create_authkey()
    k2 = paths.get_or_create_authkey()
    assert k1 == k2
    assert len(k1) == 32


def test_authkey_regenerates_on_corrupt_file(monkeypatch, tmp_path: Path):
    """If the on-disk authkey is the wrong length, we generate a fresh one."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    paths.get_or_create_authkey()
    paths.authkey_path().write_bytes(b"too short")
    fresh = paths.get_or_create_authkey()
    assert len(fresh) == 32


@pytest.mark.skipif(sys.platform == "win32", reason="unix-only test")
def test_authkey_perms_unix(monkeypatch, tmp_path: Path):
    """Authkey file must be 0600 — no other user can read it."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    paths.get_or_create_authkey()
    mode = os.stat(paths.authkey_path()).st_mode & 0o777
    assert mode == 0o600


def test_socket_address_per_platform(monkeypatch, tmp_path: Path):
    """Linux/macOS get a Unix-socket path; Windows gets a named pipe."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    addr = paths.socket_address()
    assert isinstance(addr, str)
    if sys.platform == "win32":
        assert addr.startswith(r"\\.\pipe\notspotlight")
    else:
        assert addr.endswith("daemon.sock")
