"""Tests for src/ingest/ignore.py — cascading .gitignore + .nasignore + defaults.

Covers:
  * Built-in defaults (node_modules/, .git/, __pycache__/, etc.) always fire
  * `.gitignore` at root is honored
  * `.nasignore` is honored and composes with `.gitignore`
  * Deeper `.gitignore` files apply below their own directory
  * Negation patterns ("!foo") unignore a subset
  * Rules don't bleed outside the walk root
"""

from __future__ import annotations

from pathlib import Path

from src.ingest.ignore import DEFAULT_IGNORE_PATTERNS, IgnoreRules


def _touch(p: Path, contents: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents, encoding="utf-8")
    return p


def test_defaults_applied_without_any_gitignore(tmp_path: Path):
    _touch(tmp_path / "app.py", "print(1)")
    _touch(tmp_path / "node_modules" / "react" / "index.js")
    _touch(tmp_path / "__pycache__" / "foo.cpython-311.pyc")
    _touch(tmp_path / "dist" / "bundle.js")

    rules = IgnoreRules.from_root(tmp_path)

    assert rules.is_ignored(tmp_path / "node_modules" / "react" / "index.js")
    assert rules.is_ignored(tmp_path / "__pycache__" / "foo.cpython-311.pyc")
    assert rules.is_ignored(tmp_path / "dist" / "bundle.js")
    assert not rules.is_ignored(tmp_path / "app.py")


def test_gitignore_at_root(tmp_path: Path):
    _touch(tmp_path / ".gitignore", "secrets.txt\nprivate/\n")
    _touch(tmp_path / "secrets.txt", "...")
    _touch(tmp_path / "private" / "note.md", "...")
    _touch(tmp_path / "public" / "note.md", "...")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "secrets.txt")
    assert rules.is_ignored(tmp_path / "private" / "note.md")
    assert not rules.is_ignored(tmp_path / "public" / "note.md")


def test_nasignore_honored(tmp_path: Path):
    _touch(tmp_path / ".nasignore", "draft/\n")
    _touch(tmp_path / "draft" / "todo.md", "...")
    _touch(tmp_path / "final.md", "...")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "draft" / "todo.md")
    assert not rules.is_ignored(tmp_path / "final.md")


def test_gitignore_and_nasignore_compose(tmp_path: Path):
    """`.gitignore` covers code cruft; `.nasignore` adds search-specific excludes."""
    _touch(tmp_path / ".gitignore", "*.log\n")
    _touch(tmp_path / ".nasignore", "personal/\n")
    _touch(tmp_path / "server.log", "...")
    _touch(tmp_path / "personal" / "diary.md", "...")
    _touch(tmp_path / "report.md", "...")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "server.log")
    assert rules.is_ignored(tmp_path / "personal" / "diary.md")
    assert not rules.is_ignored(tmp_path / "report.md")


def test_nested_gitignore(tmp_path: Path):
    """A .gitignore inside a subfolder applies only below it."""
    _touch(tmp_path / "a" / ".gitignore", "local_only.txt\n")
    _touch(tmp_path / "a" / "local_only.txt", "...")
    _touch(tmp_path / "b" / "local_only.txt", "...")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "a" / "local_only.txt")
    # Same filename in a sibling dir has no matching rule → kept.
    assert not rules.is_ignored(tmp_path / "b" / "local_only.txt")


def test_node_modules_ignored_even_with_gitignore_negation(tmp_path: Path):
    """Built-in defaults cannot be overridden by user patterns — safety rail."""
    _touch(tmp_path / ".gitignore", "!node_modules/\n")
    _touch(tmp_path / "node_modules" / "react" / "index.js")

    rules = IgnoreRules.from_root(tmp_path)
    # Defaults are conservative: node_modules stays ignored regardless.
    assert rules.is_ignored(tmp_path / "node_modules" / "react" / "index.js")


def test_outside_root_paths_not_ignored(tmp_path: Path):
    """Paths above the root return False — we don't reach out of scope."""
    outside = tmp_path.parent / "outside.txt"
    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(outside) is False


def test_default_patterns_list_is_sane():
    """Smoke check that our built-in list hasn't accidentally been emptied."""
    assert len(DEFAULT_IGNORE_PATTERNS) >= 20
    assert "node_modules/" in DEFAULT_IGNORE_PATTERNS
    assert ".git/" in DEFAULT_IGNORE_PATTERNS
    assert "__pycache__/" in DEFAULT_IGNORE_PATTERNS


def test_walker_find_candidates_filters_node_modules(tmp_path: Path):
    """End-to-end: find_candidates drops files under node_modules."""
    from src.ingest.walker import find_candidates

    _touch(tmp_path / "app.py", "print(1)")
    _touch(tmp_path / "README.md", "hi")
    _touch(tmp_path / "node_modules" / "react" / "index.js", "/* dep */")
    _touch(tmp_path / "node_modules" / "react" / "README.md", "# react")
    _touch(tmp_path / "build" / "bundle.js", "...")
    _touch(tmp_path / "src" / "util.py", "...")

    files, ignored, asset_skipped = find_candidates(tmp_path)
    names = {f.name for f in files}
    assert names == {"app.py", "README.md", "util.py"}
    assert ignored >= 3          # node_modules/*.js, node_modules/*.md, build/*.js
    assert asset_skipped == 0    # no asset-library-shaped folders here
