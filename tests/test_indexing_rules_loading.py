"""Config load/save tests for IndexingRules.

Covers:
  - Roundtrip (write → read → write again, equal)
  - Missing file → defaults written
  - Malformed JSON → clear failure
  - Comment fields (`_comment`) stripped on load
  - mtime cache invalidation (`maybe_reload`)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.config import (
    IncludePath,
    UserRules,
    load_indexing_rules,
    load_magpie_defaults,
    load_user_rules,
    save_user_rules,
)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "indexing_rules.json"
    rules = UserRules(
        include_paths=[IncludePath(path="/Users/x/Docs", enabled=True)],
        exclude_paths=["/Users/x/Docs/secret.txt"],
        respect_gitignore=False,
    )
    save_user_rules(rules, p)
    loaded = load_user_rules(p)
    assert loaded.include_paths[0].path == "/Users/x/Docs"
    assert loaded.exclude_paths == ["/Users/x/Docs/secret.txt"]
    assert loaded.respect_gitignore is False


def test_load_creates_default_file_when_missing(tmp_path: Path) -> None:
    p = tmp_path / "missing.json"
    assert not p.exists()
    rules = load_user_rules(p)
    assert p.exists()
    assert rules.include_paths == []
    # Default GlobalRules: archive off, others on; max_file_size_mb=200.
    assert rules.global_rules.max_file_size_mb == 200.0
    assert rules.global_rules.categories_enabled["archive"] is False
    assert rules.global_rules.categories_enabled["data"] is True


def test_malformed_json_raises_clearly(tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{ this is not json")
    with pytest.raises(json.JSONDecodeError):
        load_user_rules(p)


def test_magpie_defaults_strips_comment_fields(tmp_path: Path) -> None:
    p = tmp_path / "defaults.json"
    p.write_text(json.dumps({
        "_comment": "this should be stripped",
        "version": 1,
        "exclude_dirs": ["node_modules"],
        "exclude_globs": [],
        "exclude_extensions": [],
        "ignore_hidden": True,
    }))
    defaults = load_magpie_defaults(p)
    assert defaults.exclude_dirs == ["node_modules"]


def test_load_real_magpie_defaults_succeeds() -> None:
    """The shipped src/config/magpie_defaults.json must always parse —
    a regression here breaks first-run for every new user.
    """

    defaults = load_magpie_defaults()  # default path
    assert defaults.version == 1
    assert "node_modules" in defaults.exclude_dirs
    assert ".pyc" in defaults.exclude_extensions or ".DS_Store" in defaults.exclude_extensions
    # Some excludes_globs migrated from the old DEFAULT_IGNORE_PATTERNS
    assert any("env" in g for g in defaults.exclude_globs)


def test_maybe_reload_picks_up_external_edit(tmp_path: Path) -> None:
    user_path = tmp_path / "rules.json"
    rules = UserRules(include_paths=[IncludePath(path=str(tmp_path), enabled=True)])
    save_user_rules(rules, user_path)
    composed = load_indexing_rules(user_path=user_path)
    assert len(composed.user.include_paths) == 1

    # Edit the file externally (e.g. user via vim or future GUI) and
    # ensure mtime is strictly newer (some filesystems have 1s resolution).
    time.sleep(0.05)
    rules.exclude_paths = ["/some/excluded/path"]
    save_user_rules(rules, user_path)

    reloaded = composed.maybe_reload()
    assert reloaded is True
    assert composed.user.exclude_paths == ["/some/excluded/path"]

    # Calling again with no change → no reload.
    assert composed.maybe_reload() is False


def test_unknown_extra_fields_in_user_json_are_dropped_or_ignored(tmp_path: Path) -> None:
    """Forward-compat: a user on an older Magpie should be able to load a
    config written by a newer Magpie (extra fields gracefully ignored)."""

    p = tmp_path / "future.json"
    p.write_text(json.dumps({
        "version": 1,
        "include_paths": [],
        "exclude_paths": [],
        "global_rules": {
            "exclude_globs": [],
            "categories_enabled": {"text": True},
            "max_file_size_mb": 100,
        },
        "respect_gitignore": True,
        "respect_nasignore": True,
        "respect_magpie_inline_rules": True,
        "ignore_hidden": True,
        "future_field_we_dont_know_about": {"some": "data"},
    }))
    # Pydantic v2 ignores extra fields by default; load should succeed.
    rules = load_user_rules(p)
    assert rules.version == 1
