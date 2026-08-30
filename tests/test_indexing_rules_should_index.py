"""Precedence tests for `IndexingRules.should_index()`.

Mirrors the precedence table in `Plans/Ingestion Rules/Implementation Plan.md` §4.
Each test pins one row of the table — when something fails, the diff is
small and the failing row is named in the test function.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.config import (
    GlobalRules,
    IncludePath,
    IndexingRules,
    MagpieDefaults,
    RuleSet,
    UserRules,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A clean per-test directory used as the include root."""

    # Use a child dir of tmp_path so we never accidentally treat the system
    # `/tmp/...` part of the path as content.
    r = tmp_path / "corpus"
    r.mkdir()
    return r


@pytest.fixture
def empty_defaults() -> MagpieDefaults:
    """No safety rails — for tests that want to exercise user rules in
    isolation. Real production always has the migrated DEFAULT_IGNORE_PATTERNS.
    """

    return MagpieDefaults()


def _build(root: Path, *,
           defaults: MagpieDefaults | None = None,
           include_rules: RuleSet | None = None,
           global_rules: GlobalRules | None = None,
           exclude_paths: list[str] | None = None,
           **user_kwargs) -> IndexingRules:
    """Convenience constructor that wires up a single root + given pieces."""

    user = UserRules(
        include_paths=[IncludePath(path=str(root), enabled=True, rules=include_rules)],
        exclude_paths=exclude_paths or [],
        global_rules=global_rules or GlobalRules(),
        **user_kwargs,
    )
    return IndexingRules(
        defaults=defaults or MagpieDefaults(),
        user=user,
        user_path=root / "fake.json",
    )


# ---------------------------------------------------------------------------
# Precedence row 0: explicit FILE include_paths overrides every other rule.
# ---------------------------------------------------------------------------
#
# When a user adds a single file (not a directory) to include_paths, that's
# their strongest possible signal of intent — it beats exclude_paths,
# gitignore, hidden-file rule, category-disabled, file-size cap. Directory
# entries in include_paths fall through to the normal precedence chain
# (exclude_paths still wins for files INSIDE them).


def _build_with_file_include(file_path: Path, **user_kwargs) -> IndexingRules:
    """Build rules where the include_paths entry IS the file itself."""

    user = UserRules(
        include_paths=[IncludePath(path=str(file_path), enabled=True)],
        global_rules=user_kwargs.pop("global_rules", None) or GlobalRules(),
        **user_kwargs,
    )
    return IndexingRules(
        defaults=user_kwargs.pop("defaults", None) or MagpieDefaults(),
        user=user,
        user_path=file_path.parent / "fake.json",
    )


def test_explicit_file_include_overrides_exclude_path(root: Path) -> None:
    """If a path is in BOTH include_paths (as a file) AND exclude_paths,
    the explicit file include wins."""

    f = root / "important.txt"
    f.write_text("x")
    user = UserRules(
        include_paths=[IncludePath(path=str(f), enabled=True)],
        exclude_paths=[str(f)],
    )
    rules = IndexingRules(
        defaults=MagpieDefaults(), user=user, user_path=root / "fake.json",
    )
    ok, reason = rules.should_index(f)
    assert ok is True
    assert "explicitly included file" in reason


def test_explicit_file_include_overrides_gitignore(root: Path) -> None:
    """A `.gitignore` entry that would normally hide the file is bypassed."""

    f = root / "build_artifact.bin"
    f.write_text("x")
    (root / ".gitignore").write_text("*.bin\n")
    rules = _build_with_file_include(f)
    ok, _ = rules.should_index(f)
    assert ok is True


def test_explicit_file_include_overrides_hidden(root: Path) -> None:
    """`.foo.txt` in include_paths is indexed even with ignore_hidden=True."""

    f = root / ".secret_notes.txt"
    f.write_text("x")
    rules = _build_with_file_include(f, ignore_hidden=True)
    ok, _ = rules.should_index(f)
    assert ok is True


def test_explicit_file_include_overrides_disabled_category(root: Path) -> None:
    """Even with the file's category turned off globally, the explicit
    include wins. Common case: user disabled `data: false` for noise
    reduction but wants ONE specific CSV indexed."""

    f = root / "important_metrics.csv"
    f.write_text("x")
    rules = _build_with_file_include(
        f,
        global_rules=GlobalRules(
            categories_enabled={"text": True, "document": True, "image": True,
                                "data": False, "code": True, "archive": False},
        ),
    )
    ok, _ = rules.should_index(f)
    assert ok is True


def test_explicit_file_include_overrides_size_cap(root: Path, monkeypatch) -> None:
    """File-size cap is bypassed for explicit file includes."""

    f = root / "huge.bin"
    f.write_text("x" * 1024)
    rules = _build_with_file_include(
        f,
        global_rules=GlobalRules(max_file_size_mb=0.0001),  # ~100 bytes
    )
    ok, _ = rules.should_index(f)
    assert ok is True


def test_directory_include_does_not_trigger_file_short_circuit(root: Path) -> None:
    """include_paths entries pointing at DIRECTORIES still flow through
    the normal precedence chain — exclude_paths still wins for files
    inside them. Only file-typed entries trigger row 0."""

    f = root / "secret.txt"
    f.write_text("x")
    rules = _build(root, exclude_paths=[str(f)])
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "explicitly excluded" in reason


def test_disabled_explicit_file_include_does_not_short_circuit(root: Path) -> None:
    """An explicit file include with enabled=False falls back to the normal
    chain (which will reject the file as "not under any included folder")."""

    f = root / "important.txt"
    f.write_text("x")
    user = UserRules(
        include_paths=[IncludePath(path=str(f), enabled=False)],
    )
    rules = IndexingRules(
        defaults=MagpieDefaults(), user=user, user_path=root / "fake.json",
    )
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "not under any included folder" in reason


# ---------------------------------------------------------------------------
# Precedence row 1: explicit exclude_paths always wins
# ---------------------------------------------------------------------------


def test_explicit_exclude_path_wins_over_everything(root: Path) -> None:
    f = root / "secret.txt"
    f.write_text("x")
    rules = _build(root, exclude_paths=[str(f)])
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "explicitly excluded" in reason


def test_explicit_exclude_path_blocks_descendants(root: Path) -> None:
    """A directory in exclude_paths blocks every file beneath it."""

    sub = root / "private"
    sub.mkdir()
    f = sub / "diary.md"
    f.write_text("dear diary")
    rules = _build(root, exclude_paths=[str(sub)])
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "explicitly excluded" in reason


# ---------------------------------------------------------------------------
# Precedence row 2: must be under an enabled include
# ---------------------------------------------------------------------------


def test_file_outside_any_include_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    # Build with a different root that doesn't include `outside`.
    other_root = tmp_path / "other"
    other_root.mkdir()
    rules = _build(other_root)
    ok, reason = rules.should_index(outside)
    assert ok is False
    assert "not under any included folder" in reason


def test_disabled_include_does_not_count(root: Path) -> None:
    f = root / "x.txt"
    f.write_text("x")
    user = UserRules(include_paths=[IncludePath(path=str(root), enabled=False)])
    rules = IndexingRules(defaults=MagpieDefaults(), user=user, user_path=root / "fake.json")
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "not under any included folder" in reason


# ---------------------------------------------------------------------------
# Precedence row 3: most-specific include wins; per-root rules apply
# ---------------------------------------------------------------------------


def test_per_root_exclude_glob_rejects_matching_file(root: Path) -> None:
    f = root / "build_artifact.bin"
    f.write_text("x")
    rules = _build(root, include_rules=RuleSet(exclude_globs=["*.bin"]))
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "folder rule exclude" in reason


def test_per_root_include_glob_force_includes(root: Path) -> None:
    """A per-root include glob short-circuits later reject checks
    (gitignore, hidden, category, size). Test by enabling include and a
    category-disable that would normally reject.
    """

    f = root / "important.bin"
    f.write_text("x")
    rules = _build(
        root,
        include_rules=RuleSet(include_globs=["important.bin"]),
        global_rules=GlobalRules(categories_enabled={
            "text": False, "document": False, "image": False,
            "data": False, "code": False, "archive": False,
        }),
    )
    ok, reason = rules.should_index(f)
    assert ok is True
    assert "folder rule include" in reason


def test_root_exclude_wins_over_root_include_in_same_root(root: Path) -> None:
    """Per the plan: if both include and exclude in the SAME root match,
    exclude wins. Reasoning: explicit exclude is the more cautious choice.
    """

    f = root / "x.bin"
    f.write_text("x")
    rules = _build(
        root,
        include_rules=RuleSet(
            exclude_globs=["*.bin"],
            include_globs=["x.bin"],
        ),
    )
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "folder rule exclude" in reason


def test_most_specific_include_wins_over_parent_root(tmp_path: Path) -> None:
    """If both `/parent` and `/parent/child` are included, files under
    `/parent/child` should use that root's rules, not `/parent`'s.
    """

    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    f = child / "data.txt"
    f.write_text("x")
    user = UserRules(include_paths=[
        IncludePath(path=str(parent), enabled=True,
                    rules=RuleSet(exclude_globs=["**/*.txt"])),
        IncludePath(path=str(child), enabled=True),  # no exclude
    ])
    rules = IndexingRules(defaults=MagpieDefaults(), user=user,
                          user_path=tmp_path / "fake.json")
    ok, reason = rules.should_index(f)
    assert ok is True, f"expected child's empty rules to win, got reason={reason!r}"


# ---------------------------------------------------------------------------
# Precedence row 4-5: global / defaults
# ---------------------------------------------------------------------------


def test_global_exclude_glob_rejects(root: Path) -> None:
    f = root / "x.tmp"
    f.write_text("x")
    rules = _build(root, global_rules=GlobalRules(exclude_globs=["**/*.tmp"]))
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "global exclude" in reason


def test_default_dir_name_match_rejects(root: Path) -> None:
    nm = root / "node_modules" / "x.js"
    nm.parent.mkdir()
    nm.write_text("x")
    rules = _build(
        root,
        defaults=MagpieDefaults(exclude_dirs=["node_modules"]),
    )
    ok, reason = rules.should_index(nm)
    assert ok is False
    assert "node_modules" in reason


def test_default_dir_name_does_not_match_absolute_prefix(tmp_path: Path) -> None:
    """Regression: `tmp` in defaults must not reject every file under
    /tmp/... — only `tmp` directories WITHIN the include subtree."""

    root = tmp_path / "corpus"  # `tmp` IS an absolute-path part here
    root.mkdir()
    f = root / "fine.txt"
    f.write_text("x")
    rules = _build(root, defaults=MagpieDefaults(exclude_dirs=["tmp"]))
    ok, _ = rules.should_index(f)
    assert ok is True


# ---------------------------------------------------------------------------
# Precedence row 6: inline rule files (.magpieinclude / .magpieexclude)
# ---------------------------------------------------------------------------


def test_magpieexclude_blocks(root: Path) -> None:
    (root / ".magpieexclude").write_text("*.tmp\n")
    f = root / "junk.tmp"
    f.write_text("x")
    rules = _build(root)
    ok, reason = rules.should_index(f)
    assert ok is False
    assert ".magpieexclude" in reason


def test_magpieinclude_force_includes_over_defaults(root: Path) -> None:
    """User explicitly says "yes index this," overriding magpie defaults."""

    (root / ".magpieinclude").write_text("important.env\n")
    f = root / "important.env"
    f.write_text("KEY=...")
    rules = _build(
        root,
        defaults=MagpieDefaults(exclude_globs=[".env", ".env.*"]),
    )
    ok, reason = rules.should_index(f)
    assert ok is True
    assert ".magpieinclude" in reason


def test_magpie_inline_rules_disabled_via_flag(root: Path) -> None:
    (root / ".magpieexclude").write_text("*.tmp\n")
    f = root / "junk.tmp"
    f.write_text("x")
    user = UserRules(
        include_paths=[IncludePath(path=str(root), enabled=True)],
        respect_magpie_inline_rules=False,
    )
    rules = IndexingRules(defaults=MagpieDefaults(), user=user,
                          user_path=root / "fake.json")
    ok, _ = rules.should_index(f)
    assert ok is True  # inline rule ignored, no other reject


# ---------------------------------------------------------------------------
# Precedence row 7-8: gitignore / nasignore cascade
# ---------------------------------------------------------------------------


def test_gitignore_in_subdir_rejects(root: Path) -> None:
    sub = root / "vendored"
    sub.mkdir()
    (sub / ".gitignore").write_text("*.bundle\n")
    f = sub / "deps.bundle"
    f.write_text("x")
    rules = _build(root)
    ok, reason = rules.should_index(f)
    assert ok is False
    assert ".gitignore" in reason


def test_nasignore_still_respected(root: Path) -> None:
    """Legacy filename keeps working after the .magpieignore rename."""
    (root / ".nasignore").write_text("*.lock\n")
    f = root / "x.lock"
    f.write_text("x")
    rules = _build(root)
    ok, reason = rules.should_index(f)
    assert ok is False
    assert ".nasignore" in reason


def test_magpieignore_preferred_name(root: Path) -> None:
    (root / ".magpieignore").write_text("*.lock\n")
    f = root / "x.lock"
    f.write_text("x")
    rules = _build(root)
    ok, reason = rules.should_index(f)
    assert ok is False
    assert ".magpieignore" in reason


def test_magpieignore_and_legacy_compose(root: Path) -> None:
    """Both files in one dir: each contributes patterns, explain names the
    file that actually matched."""
    (root / ".magpieignore").write_text("*.lock\n")
    (root / ".nasignore").write_text("*.bak\n")
    rules = _build(root)
    for fname, expect_src in (("x.lock", ".magpieignore"), ("y.bak", ".nasignore")):
        f = root / fname
        f.write_text("x")
        ok, reason = rules.should_index(f)
        assert ok is False
        assert expect_src in reason


# ---------------------------------------------------------------------------
# Precedence row 9: hidden files
# ---------------------------------------------------------------------------


def test_hidden_file_rejected_when_flag_on(root: Path) -> None:
    f = root / ".secret"
    f.write_text("x")
    rules = _build(root)  # ignore_hidden defaults to True
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "hidden" in reason


def test_hidden_file_allowed_when_flag_off(root: Path) -> None:
    f = root / ".visible"
    f.write_text("x")
    user = UserRules(
        include_paths=[IncludePath(path=str(root), enabled=True)],
        ignore_hidden=False,
    )
    rules = IndexingRules(defaults=MagpieDefaults(), user=user,
                          user_path=root / "fake.json")
    ok, _ = rules.should_index(f)
    assert ok is True


def test_inline_rule_files_themselves_not_rejected_as_hidden(root: Path) -> None:
    """`.gitignore`, `.nasignore`, `.magpieinclude`, `.magpieexclude` start
    with `.` but should not themselves be rejected as hidden — they're
    rule files we want the user to be able to manage normally.
    """

    for name in (".gitignore", ".nasignore", ".magpieinclude", ".magpieexclude"):
        f = root / name
        f.write_text("# pattern\n")
        rules = _build(root)
        ok, reason = rules.should_index(f)
        # Will still get rejected for OTHER reasons (e.g. unknown extension)
        # but the reason must NOT be "hidden file".
        assert "hidden" not in reason, (
            f"{name} should not be rejected as hidden, got: {reason}"
        )


# ---------------------------------------------------------------------------
# Precedence row 10: category gating
# ---------------------------------------------------------------------------


def test_disabled_category_rejects(root: Path) -> None:
    f = root / "x.zip"
    f.write_text("x")
    rules = _build(
        root,
        global_rules=GlobalRules(categories_enabled={
            "text": True, "document": True, "image": True,
            "data": True, "code": True, "archive": False,
        }),
    )
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "archive" in reason


def test_unknown_extension_allowed(root: Path) -> None:
    """Plan §4: unknown extensions should be allowed (router handles them)."""

    f = root / "x.weirdext"
    f.write_text("x")
    rules = _build(root)
    ok, _ = rules.should_index(f)
    assert ok is True


def test_per_root_category_override_wins_over_global(root: Path) -> None:
    f = root / "data.csv"
    f.write_text("a,b\n1,2")
    rules = _build(
        root,
        # Global says data: false; per-root override says data: true.
        include_rules=RuleSet(categories_enabled={"data": True}),
        global_rules=GlobalRules(categories_enabled={"data": False, "text": True,
                                                      "document": True, "image": True,
                                                      "code": True, "archive": False}),
    )
    ok, _ = rules.should_index(f)
    assert ok is True


# ---------------------------------------------------------------------------
# Precedence row 11: file-size cap
# ---------------------------------------------------------------------------


def test_oversize_file_rejected(root: Path) -> None:
    f = root / "big.txt"
    f.write_bytes(b"x" * (3 * 1024 * 1024))  # 3 MB
    rules = _build(
        root,
        global_rules=GlobalRules(max_file_size_mb=1.0),
    )
    ok, reason = rules.should_index(f)
    assert ok is False
    assert "exceeds max file size" in reason


def test_per_root_size_override(root: Path) -> None:
    f = root / "big.txt"
    f.write_bytes(b"x" * (3 * 1024 * 1024))
    rules = _build(
        root,
        include_rules=RuleSet(max_file_size_mb=10.0),  # override
        global_rules=GlobalRules(max_file_size_mb=1.0),
    )
    ok, _ = rules.should_index(f)
    assert ok is True


# ---------------------------------------------------------------------------
# is_pruneable_dir hot-path
# ---------------------------------------------------------------------------


def test_is_pruneable_dir_for_default_name(root: Path) -> None:
    nm = root / "node_modules"
    nm.mkdir()
    rules = _build(root, defaults=MagpieDefaults(exclude_dirs=["node_modules"]))
    assert rules.is_pruneable_dir(nm) is True


def test_is_pruneable_dir_for_user_excluded(root: Path) -> None:
    sub = root / "private"
    sub.mkdir()
    rules = _build(root, exclude_paths=[str(sub)])
    assert rules.is_pruneable_dir(sub) is True


def test_is_pruneable_dir_normal_dir(root: Path) -> None:
    sub = root / "docs"
    sub.mkdir()
    rules = _build(root)
    assert rules.is_pruneable_dir(sub) is False


# ---------------------------------------------------------------------------
# mtime dev-toggle (manifest field, not should_index — but adjacent enough)
# ---------------------------------------------------------------------------


def test_manifest_needs_summarization_size_only_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MAGPIE_DEV_USE_MTIME", raising=False)
    from src.manifest import Entry, Manifest

    m = Manifest.__new__(Manifest)
    m.entries = {"foo": Entry(size=100, mtime=1000.0)}
    # Same size, newer mtime — should NOT need re-summarization (size-only mode).
    assert m.needs_summarization("foo", 100, current_mtime=2000.0) is False


def test_manifest_needs_summarization_mtime_aware_when_dev_flag_set(monkeypatch) -> None:
    monkeypatch.setenv("MAGPIE_DEV_USE_MTIME", "1")
    from src.manifest import Entry, Manifest

    m = Manifest.__new__(Manifest)
    m.entries = {"foo": Entry(size=100, mtime=1000.0)}
    # Same size, newer mtime — under dev flag, SHOULD trigger re-summarization.
    assert m.needs_summarization("foo", 100, current_mtime=2000.0) is True
    # Same size, same mtime — still skipped.
    assert m.needs_summarization("foo", 100, current_mtime=1000.0) is False
