"""Tests for directory-level walk pruning — the speed fix for big corpora.

Without these prunes, on a 1 TB drive we'd descend into `node_modules/`
(50k+ files per package) and `Program Files/` etc. just to filter every
file individually. The prune skips the entire subtree at the directory
level so `os.walk` never even lists those children.

Ported in 2026-05 from the old `IgnoreRules.is_default_ignored_dir` API
to the new `IndexingRules.is_pruneable_dir` API. Behavior identical;
the API surface name changed.
"""

from __future__ import annotations

from pathlib import Path

from src.config import IncludePath, IndexingRules, UserRules, load_magpie_defaults
from src.ingest.walker import find_candidates


def _touch(p: Path, contents: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents, encoding="utf-8")
    return p


def _rules_for(root: Path) -> IndexingRules:
    """Build an IndexingRules with `root` as a single enabled include and
    the real shipped magpie_defaults — same composition the production
    walker gets via `load_indexing_rules()`.
    """

    return IndexingRules(
        defaults=load_magpie_defaults(),
        user=UserRules(include_paths=[IncludePath(path=str(root), enabled=True)]),
        user_path=root / "_test_fake.json",
    )


def test_is_pruneable_dir_recognizes_node_modules(tmp_path: Path):
    rules = _rules_for(tmp_path)
    nm = tmp_path / "node_modules"
    nm.mkdir()
    assert rules.is_pruneable_dir(nm)


def test_is_pruneable_dir_recognizes_target_and_windows_dirs(tmp_path: Path):
    rules = _rules_for(tmp_path)
    for d in ("target", "Program Files", "WindowsApps", "$RECYCLE.BIN",
              "System Volume Information", "lost+found"):
        (tmp_path / d).mkdir()
    for d in ("target", "Program Files", "WindowsApps", "$RECYCLE.BIN",
              "System Volume Information", "lost+found"):
        assert rules.is_pruneable_dir(tmp_path / d), f"missed: {d}"


def test_is_pruneable_dir_does_not_match_normal_folders(tmp_path: Path):
    rules = _rules_for(tmp_path)
    for d in ("src", "docs", "Documents", "Downloads", "my_project"):
        (tmp_path / d).mkdir()
        assert not rules.is_pruneable_dir(tmp_path / d), f"false-positive: {d}"


def test_find_candidates_does_not_descend_into_node_modules(tmp_path: Path):
    """Real test: 100 files inside node_modules should NEVER be stat'd."""
    nm = tmp_path / "node_modules" / "react"
    nm.mkdir(parents=True)
    for i in range(100):
        _touch(nm / f"file{i}.js", f"// dep {i}")
    _touch(tmp_path / "real_doc.md", "real content")

    rules = _rules_for(tmp_path)
    files, _, _ = find_candidates(tmp_path, indexing_rules=rules)
    names = {f.name for f in files}
    assert names == {"real_doc.md"}


def test_find_candidates_does_not_descend_into_recycle_bin(tmp_path: Path):
    """Real test: $RECYCLE.BIN/ should be pruned even with weird filenames."""
    rb = tmp_path / "$RECYCLE.BIN" / "S-1-5-21-foo-bar-baz"
    rb.mkdir(parents=True)
    for i in range(50):
        _touch(rb / f"$RZC{i}.png", "x")
    _touch(tmp_path / "real_doc.md", "real")

    rules = _rules_for(tmp_path)
    files, _, _ = find_candidates(tmp_path, indexing_rules=rules)
    names = {f.name for f in files}
    assert names == {"real_doc.md"}


def test_cascade_cache_does_not_load_gitignore_inside_pruned_dirs(tmp_path: Path):
    """A `.gitignore` deep inside a default-ignored folder should never
    have its rules loaded into the cache — because the walker never
    descends into the folder, `note_directory()` is never called for any
    descendant.

    Behavioral check (the new API doesn't expose pre-walk discovery —
    cascade is lazy). After a walk, the cascade cache should NOT contain
    entries for directories under node_modules.
    """

    deep = tmp_path / "node_modules" / "react" / "deep" / ".gitignore"
    _touch(deep, "real_doc.md\n")
    _touch(tmp_path / ".gitignore", "private/\n")
    _touch(tmp_path / "real_doc.md", "real content")

    rules = _rules_for(tmp_path)
    find_candidates(tmp_path, indexing_rules=rules)

    # The root cascade should be cached (.gitignore at root was visible).
    assert tmp_path.resolve() in rules._cascade_cache
    # The deep one inside node_modules was NEVER walked → not cached.
    deep_dir = (tmp_path / "node_modules" / "react" / "deep").resolve()
    assert deep_dir not in rules._cascade_cache
