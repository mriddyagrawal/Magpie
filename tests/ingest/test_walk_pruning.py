"""Tests for directory-level walk pruning — the speed fix for big corpora.

Without these prunes, on a 1 TB drive we'd descend into `node_modules/`
(50k+ files per package) and `Program Files/` etc. just to filter every
file individually. The prune skips the entire subtree at the directory
level so `os.walk` never even lists those children.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.ingest.ignore import IgnoreRules
from src.ingest.walker import find_candidates


def _touch(p: Path, contents: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents, encoding="utf-8")
    return p


def test_is_default_ignored_dir_recognizes_node_modules(tmp_path: Path):
    rules = IgnoreRules.from_root(tmp_path)
    nm = tmp_path / "node_modules"
    nm.mkdir()
    assert rules.is_default_ignored_dir(nm)


def test_is_default_ignored_dir_recognizes_target_and_windows_dirs(tmp_path: Path):
    rules = IgnoreRules.from_root(tmp_path)
    for d in ("target", "Program Files", "WindowsApps", "$RECYCLE.BIN",
              "System Volume Information", "lost+found"):
        (tmp_path / d).mkdir()
    for d in ("target", "Program Files", "WindowsApps", "$RECYCLE.BIN",
              "System Volume Information", "lost+found"):
        assert rules.is_default_ignored_dir(tmp_path / d), f"missed: {d}"


def test_is_default_ignored_dir_does_not_match_normal_folders(tmp_path: Path):
    rules = IgnoreRules.from_root(tmp_path)
    for d in ("src", "docs", "Documents", "Downloads", "my_project"):
        (tmp_path / d).mkdir()
        assert not rules.is_default_ignored_dir(tmp_path / d), f"false-positive: {d}"


def test_is_default_ignored_dir_walk_root_itself_not_pruned(tmp_path: Path):
    """The walk root must NEVER be pruned — even if it happens to be named
    `node_modules` (some user is debugging an npm package directly)."""
    nm_root = tmp_path / "node_modules"
    nm_root.mkdir()
    rules = IgnoreRules.from_root(nm_root)
    assert not rules.is_default_ignored_dir(nm_root)


def test_find_candidates_does_not_descend_into_node_modules(tmp_path: Path):
    """Real test: 100 files inside node_modules should NEVER be stat'd."""
    nm = tmp_path / "node_modules" / "react"
    nm.mkdir(parents=True)
    for i in range(100):
        _touch(nm / f"file{i}.js", "x")
    _touch(tmp_path / "real.py", "real")

    # Spy on Path.is_file to count calls — if prune is working, only ~1
    # file (the real.py) should be stat'd, not 101.
    real_is_file = Path.is_file
    call_paths: list[Path] = []

    def spy_is_file(self):
        call_paths.append(self)
        return real_is_file(self)

    with patch.object(Path, "is_file", spy_is_file):
        files, _, _ = find_candidates(tmp_path)

    names = {f.name for f in files}
    assert names == {"real.py"}
    # We should NOT have stat'd anything inside node_modules/
    nm_calls = [p for p in call_paths if "node_modules" in str(p)]
    assert nm_calls == [], (
        f"prune failed — find_candidates stat'd "
        f"{len(nm_calls)} files inside node_modules/"
    )


def test_find_candidates_prunes_program_files_and_recyclebin(tmp_path: Path):
    """Same prune for Windows-mount cruft — never descend."""
    pf = tmp_path / "Program Files" / "Adobe"
    pf.mkdir(parents=True)
    rb = tmp_path / "$RECYCLE.BIN" / "S-1-5-21-1001"
    rb.mkdir(parents=True)
    for i in range(50):
        _touch(pf / f"setup{i}.cfg", "x")
        _touch(rb / f"$RZC{i}.png", "x")
    _touch(tmp_path / "real_doc.md", "real")

    files, _, _ = find_candidates(tmp_path)
    names = {f.name for f in files}
    assert names == {"real_doc.md"}


def test_from_root_does_not_descend_into_default_ignored_dirs(tmp_path: Path):
    """Smoke test for from_root walk-prune: a `.gitignore` deep inside
    a default-ignored folder should NOT be discovered (we never descend)."""
    # Plant a .gitignore inside node_modules — should be invisible.
    deep = tmp_path / "node_modules" / "react" / "deep" / ".gitignore"
    _touch(deep, "real_doc.md\n")
    # And one at root that we DO want
    _touch(tmp_path / ".gitignore", "private/\n")

    rules = IgnoreRules.from_root(tmp_path)
    # Root .gitignore was found
    assert tmp_path.resolve() in rules._per_dir
    # The deep one inside node_modules was NOT found (walk pruned)
    deep_dir = (tmp_path / "node_modules" / "react" / "deep").resolve()
    assert deep_dir not in rules._per_dir
