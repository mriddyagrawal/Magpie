"""Cascading ignore rules for ingest — `.gitignore` + `.nasignore` + built-in defaults.

Semantics match git's: rules from `.gitignore` files are applied at each
directory level, and rules in a deeper folder's `.gitignore` override those
from ancestors. `.nasignore` is a NotAnotherSpotlight-specific equivalent for
cases where a user wants the walker to skip something their git rules track.

On top of user rules we unconditionally apply a small set of **built-in
defaults** — `node_modules/`, `__pycache__/`, `.venv/`, `.git/`, `build/`,
`dist/`, `target/`, IDE cache folders, etc. These are common across projects
and keep a fresh install from embedding the universe by accident.

Reference: https://git-scm.com/docs/gitignore

The module is a thin wrapper around `pathspec.PathSpec`:
  - `IgnoreRules.from_root(root)` builds a cascading ruleset for a walk rooted at `root`
  - `rules.is_ignored(path)` returns True/False

We choose to **check each file's nearest-ancestor spec** rather than rebuilding
specs per directory. That's slightly less faithful to git semantics (git
evaluates rules from outermost to innermost with later rules winning) but it's
dramatically simpler and matches how ripgrep's `ignore` crate behaves in
practice. Trade-off documented here so we can revisit if it bites.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pathspec


# Built-in patterns — applied regardless of user config, in gitignore syntax.
DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    # VCS
    ".git/",
    ".hg/",
    ".svn/",
    # Python
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".tox/",
    ".venv/",
    "venv/",
    "env/",
    "*.egg-info/",
    # Node
    "node_modules/",
    ".next/",
    ".nuxt/",
    # Rust / Go / Java
    "target/",
    "bin/",
    "obj/",
    # Build / dist
    "build/",
    "dist/",
    "out/",
    ".output/",
    # IDE
    ".idea/",
    ".vscode/",
    ".vs/",
    "*.swp",
    "*.swo",
    # OS cruft
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    # NotAnotherSpotlight's own state (never ingest our own summaries!)
    "Test Summaries/",
    # Jupyter checkpoints
    ".ipynb_checkpoints/",
    # Lock files (not source content)
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "go.sum",
)


IGNORE_FILENAMES = (".gitignore", ".nasignore")


@dataclass
class IgnoreRules:
    """Cascading ignore ruleset for a walk rooted at `root`.

    Internally: a map from absolute directory path → compiled PathSpec for
    patterns declared in that directory's `.gitignore` / `.nasignore`. Plus a
    single PathSpec for the built-in defaults.
    """

    root: Path
    _per_dir: dict[Path, pathspec.PathSpec] = field(default_factory=dict)
    _defaults: pathspec.PathSpec = field(
        default_factory=lambda: pathspec.PathSpec.from_lines(
            "gitignore", DEFAULT_IGNORE_PATTERNS
        )
    )

    @classmethod
    def from_root(cls, root: Path) -> IgnoreRules:
        """Scan `root` once; collect every `.gitignore` / `.nasignore` beneath it."""
        rules = cls(root=root.resolve())
        for dirpath, dirnames, filenames in os.walk(rules.root):
            # Prune hidden directories in-place so os.walk skips them.
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            patterns: list[str] = []
            for name in IGNORE_FILENAMES:
                if name in filenames:
                    try:
                        text = (Path(dirpath) / name).read_text(encoding="utf-8")
                    except OSError:
                        continue
                    patterns.extend(text.splitlines())
            if patterns:
                rules._per_dir[Path(dirpath)] = pathspec.PathSpec.from_lines(
                    "gitignore", patterns
                )
        return rules

    def is_ignored(self, path: Path) -> bool:
        """Return True if `path` matches any ancestor's ignore rules.

        Built-in defaults always apply. User rules from `.gitignore` /
        `.nasignore` apply relative to the directory they were declared in.
        """
        try:
            resolved = path.resolve()
        except OSError:
            return False

        # 1. Built-in defaults — match against path relative to the walk root
        try:
            rel_to_root = resolved.relative_to(self.root)
        except ValueError:
            return False    # outside the walk — don't ignore
        if self._defaults.match_file(str(rel_to_root)):
            return True

        # 2. User rules cascading up: check each ancestor dir that has a spec.
        for ancestor in [resolved, *resolved.parents]:
            if ancestor == self.root.parent:
                break
            spec = self._per_dir.get(ancestor)
            if spec is None and ancestor.is_dir():
                # Deeper-than-file check; a file's own dir is its first parent.
                continue
            spec = self._per_dir.get(ancestor.parent) if spec is None else spec
            if spec is None:
                continue
            try:
                rel = resolved.relative_to(ancestor.parent if ancestor.is_file() else ancestor)
            except ValueError:
                continue
            if spec.match_file(str(rel)):
                return True
        return False

    def __repr__(self) -> str:
        return (
            f"IgnoreRules(root={self.root}, "
            f"user_dirs_with_rules={len(self._per_dir)}, "
            f"defaults={len(DEFAULT_IGNORE_PATTERNS)})"
        )
