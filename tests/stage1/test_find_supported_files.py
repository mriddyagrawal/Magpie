"""`find_supported_files` must go through the rules-aware walker.

It used to be a bare `root.rglob("*")`, which had three consequences the
summary tier's callers never asked for: the user's `indexing_rules.json` was
ignored (so `just sync` indexed files the app itself refuses), dot-folders
like `.git/` and `.venv/` were walked, and a single unreadable directory
raised `OSError` out of the whole sync.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from src.stage1.summarize import find_supported_files


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A small tree plus an isolated MAGPIE_DATA_DIR holding its rules."""
    data_dir = tmp_path / "magpie-data"
    data_dir.mkdir()
    # `src.manifest.APP_DATA_DIR` is a module-level constant resolved at import
    # time, so setting MAGPIE_DATA_DIR now would be too late — patch the
    # attribute itself, which `_user_rules_path()` re-reads on every call.
    monkeypatch.setenv("MAGPIE_DATA_DIR", str(data_dir))
    monkeypatch.setattr("src.manifest.APP_DATA_DIR", data_dir)

    root = tmp_path / "corpus"
    (root / "keep").mkdir(parents=True)
    (root / "vendor").mkdir()
    (root / ".venv").mkdir()

    (root / "keep" / "notes.md").write_text("keep me")
    (root / "vendor" / "third_party.md").write_text("excluded by rule")
    (root / ".venv" / "lib.md").write_text("inside a dot-folder")

    rules = {
        "version": 1,
        "include_paths": [{
            "path": str(root),
            "enabled": True,
            "display_name": "corpus",
            "rules": {"exclude_globs": ["vendor/**", "**/vendor/**"]},
        }],
        "exclude_paths": [],
    }
    (data_dir / "indexing_rules.json").write_text(json.dumps(rules))
    return root


def test_user_exclude_globs_are_honored(corpus: Path) -> None:
    names = {p.name for p in find_supported_files(corpus)}
    assert "notes.md" in names
    assert "third_party.md" not in names


def test_dot_folders_are_pruned(corpus: Path) -> None:
    names = {p.name for p in find_supported_files(corpus)}
    assert "lib.md" not in names


def test_unreadable_directory_does_not_abort_the_walk(corpus: Path) -> None:
    """One bad folder must not take the whole sync down.

    A failing external drive produced `OSError: [Errno 5]` mid-walk and no
    files were indexed at all. The walk should skip what it cannot read and
    still return everything else.
    """
    blocked = corpus / "blocked"
    blocked.mkdir()
    (blocked / "hidden.md").write_text("unreachable")
    os.chmod(blocked, 0o000)
    try:
        if os.access(blocked, os.R_OK):  # running as root — the chmod is a no-op
            pytest.skip("cannot make a directory unreadable as this user")
        names = {p.name for p in find_supported_files(corpus)}
        assert "notes.md" in names
    finally:
        os.chmod(blocked, stat.S_IRWXU)
