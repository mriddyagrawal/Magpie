"""Tests for hidden-path filtering in find_candidates.

Covers:
  * Dot-folders pruned during traversal (.config/, .codex/, .antigravity/, ...)
  * Leaf-name dotfiles default-skipped
  * USEFUL_DOTFILE_NAMES allowlist (.bashrc, .vimrc, .gitconfig, ...) survive
  * Files inside dot-folders never reach the candidate set, regardless of name
  * Walk root being a dot-folder still works (we don't filter the root itself)
"""

from __future__ import annotations

from pathlib import Path

from src.ingest.walker import _USEFUL_DOTFILE_NAMES, find_candidates


def _touch(p: Path, contents: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents, encoding="utf-8")
    return p


def test_dot_folders_pruned_during_walk(tmp_path: Path):
    """`.config/`, `.codex/`, `.antigravity/` etc. are skipped wholesale."""
    _touch(tmp_path / "real.md", "real content")
    _touch(tmp_path / ".config" / "app" / "settings.json", "{}")
    _touch(tmp_path / ".codex" / "tmp" / "icon.png", "fake")
    _touch(tmp_path / ".antigravity" / "extensions" / "icon.png", "fake")
    _touch(tmp_path / ".cache" / "huge_blob.json", "{}")

    files, _ = find_candidates(tmp_path)
    names = {f.name for f in files}
    assert names == {"real.md"}


def test_leaf_dotfiles_default_skipped(tmp_path: Path):
    """A loose `.foo` at the walk root that's NOT in the allowlist is skipped."""
    _touch(tmp_path / "real.md", "real")
    _touch(tmp_path / ".unknown_dotfile", "noise")
    _touch(tmp_path / ".env", "SECRET=...")
    _touch(tmp_path / ".some_random_config", "noise")

    files, _ = find_candidates(tmp_path)
    names = {f.name for f in files}
    assert names == {"real.md"}


def test_useful_dotfiles_are_indexed(tmp_path: Path):
    """`.bashrc` / `.vimrc` / `.gitconfig` are indexed despite the dot."""
    _touch(tmp_path / ".bashrc", "alias gs='git status'")
    _touch(tmp_path / ".vimrc", "set number")
    _touch(tmp_path / ".gitconfig", "[user] name = Test")
    _touch(tmp_path / "ignored.unknown_ext", "junk")  # filtered by ext

    files, _ = find_candidates(tmp_path)
    names = {f.name for f in files}
    assert ".bashrc" in names
    assert ".vimrc" in names
    assert ".gitconfig" in names


def test_useful_dotfiles_inside_dotfolder_still_skipped(tmp_path: Path):
    """A `.bashrc` inside `.config/`, `.codex/`, etc. is still pruned —
    the parent-folder rule outranks the leaf allowlist."""
    _touch(tmp_path / ".config" / ".bashrc", "should not be indexed")
    _touch(tmp_path / "real.md", "real")

    files, _ = find_candidates(tmp_path)
    names = {f.name for f in files}
    assert names == {"real.md"}
    assert ".bashrc" not in names


def test_walk_root_can_itself_be_a_dotfolder(tmp_path: Path):
    """If the user explicitly walks `.codex/`, it still works.

    The dot-prune only applies to children seen during traversal, not to
    the walk root. A user who explicitly points us at a dot-folder must
    have meant it.
    """
    root = tmp_path / ".explicit"
    root.mkdir()
    _touch(root / "notes.md", "real")

    files, _ = find_candidates(root)
    names = {f.name for f in files}
    assert "notes.md" in names


def test_useful_dotfile_allowlist_is_sane():
    """Smoke test: the allowlist contains the obvious shell-rc files
    and excludes obvious secret filenames."""
    assert ".bashrc" in _USEFUL_DOTFILE_NAMES
    assert ".zshrc" in _USEFUL_DOTFILE_NAMES
    assert ".vimrc" in _USEFUL_DOTFILE_NAMES
    assert ".gitconfig" in _USEFUL_DOTFILE_NAMES
    # Secrets must NOT be on the allowlist
    assert ".env" not in _USEFUL_DOTFILE_NAMES
    assert ".netrc" not in _USEFUL_DOTFILE_NAMES
    assert ".pgpass" not in _USEFUL_DOTFILE_NAMES
    assert ".git-credentials" not in _USEFUL_DOTFILE_NAMES


def test_secrets_inside_corpus_skipped_by_ignore_rule(tmp_path: Path):
    """A loose `.env` or `id_rsa` inside the corpus root must be ignored
    by the built-in default patterns even though it's a leaf dotfile that
    happens to be at root."""
    _touch(tmp_path / "real.md", "real")
    _touch(tmp_path / ".env", "AWS_KEY=...")
    _touch(tmp_path / "id_rsa", "-----BEGIN PRIVATE KEY-----")
    _touch(tmp_path / "id_ed25519", "secret")
    _touch(tmp_path / "subfolder" / ".env", "more secrets")

    files, _ = find_candidates(tmp_path)
    names_with_paths = {str(f.relative_to(tmp_path)) for f in files}
    assert names_with_paths == {"real.md"}


def test_default_ignore_patterns_include_secrets():
    """Smoke check that the default-pattern list mentions secret files."""
    from src.ingest.ignore import DEFAULT_IGNORE_PATTERNS
    assert ".env" in DEFAULT_IGNORE_PATTERNS
    assert "id_rsa" in DEFAULT_IGNORE_PATTERNS
    assert "id_ed25519" in DEFAULT_IGNORE_PATTERNS
    assert ".netrc" in DEFAULT_IGNORE_PATTERNS
    assert ".git-credentials" in DEFAULT_IGNORE_PATTERNS


def test_gif_now_in_fast_image_exts():
    """Regression: T4 used to crash on GIFs ('unsupported file for fast tier')
    because FAST_IMAGE_EXTS didn't include `.gif`. PIL handles them fine."""
    from src.stage1_fast.router import FAST_IMAGE_EXTS
    assert ".gif" in FAST_IMAGE_EXTS


# ---------------------------------------------------------------------------
# .nasconfig.yaml `include_dotfiles: true` opt-in
# ---------------------------------------------------------------------------

def test_include_dotfiles_opt_in_unprunes_dotfolders(tmp_path: Path):
    """`include_dotfiles: true` in .nasconfig.yaml at the walk root lets the
    walker descend into dot-folders (and consider all dotfiles, not just the
    allowlist). Built-in default ignores still apply."""
    _touch(tmp_path / ".nasconfig.yaml", "include_dotfiles: true\n")
    _touch(tmp_path / ".myconfig" / "real_notes.md", "actual content")
    _touch(tmp_path / ".some-arbitrary-dotfile", "user notes")
    _touch(tmp_path / "regular.md", "also content")

    files, _ = find_candidates(tmp_path)
    rels = {str(f.relative_to(tmp_path)) for f in files}
    assert "regular.md" in rels
    # With the opt-in, both the previously-pruned dot-folder content and the
    # previously-skipped non-allowlisted dotfile are now indexed.
    assert ".myconfig/real_notes.md" in rels
    assert ".some-arbitrary-dotfile" in rels


def test_include_dotfiles_opt_in_does_not_disable_secret_skip(tmp_path: Path):
    """`include_dotfiles: true` is a permission to descend, not a security
    bypass. Built-in defaults (`.env`, `id_rsa`, etc.) still drop secret
    files even when the opt-in is set."""
    _touch(tmp_path / ".nasconfig.yaml", "include_dotfiles: true\n")
    _touch(tmp_path / ".env", "AWS_KEY=secret")
    _touch(tmp_path / "id_rsa", "-----BEGIN PRIVATE KEY-----")
    _touch(tmp_path / ".some-other-dotfile", "user content")

    files, _ = find_candidates(tmp_path)
    rels = {str(f.relative_to(tmp_path)) for f in files}
    # Secrets stay out
    assert ".env" not in rels
    assert "id_rsa" not in rels
    # Non-secret arbitrary dotfile makes it in
    assert ".some-other-dotfile" in rels


def test_include_dotfiles_scoped_to_subtree(tmp_path: Path):
    """A `.nasconfig.yaml` deeper in the tree opts in only that subtree.

    The default policy (skip dot-folders) still applies elsewhere.
    """
    _touch(tmp_path / "regular_root.md", "root content")
    # Sibling subtree: NO opt-in → dot-folder pruned
    _touch(tmp_path / "no_optin" / ".pruned" / "hidden.md", "should not appear")
    # Subtree WITH opt-in
    optin = tmp_path / "with_optin"
    _touch(optin / ".nasconfig.yaml", "include_dotfiles: true\n")
    _touch(optin / ".reachable" / "deep.md", "should appear")

    files, _ = find_candidates(tmp_path)
    rels = {str(f.relative_to(tmp_path)) for f in files}
    assert "regular_root.md" in rels
    assert "with_optin/.reachable/deep.md" in rels
    # The non-opt-in subtree's dot-folder content stays pruned
    assert "no_optin/.pruned/hidden.md" not in rels


def test_include_dotfiles_default_false_when_no_config(tmp_path: Path):
    """Sanity: with no .nasconfig.yaml at all, dot-folders are still pruned."""
    _touch(tmp_path / ".pruned" / "noise.md", "should not appear")
    _touch(tmp_path / "real.md", "real")
    files, _ = find_candidates(tmp_path)
    rels = {f.name for f in files}
    assert rels == {"real.md"}


def test_useful_dotfiles_route_to_t1_through_router(tmp_path: Path):
    """Regression: `.bashrc` was going through walker but failing at router
    with `peek failed: unsupported extension: (none)` because the router
    didn't know about the allowlist. Both peek and decide now treat
    extensionless useful dotfiles as text-tier.
    """
    from src.router import decide, peek

    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("alias gs='git status'\nexport PATH=$PATH:/usr/local/bin\n")

    p = peek(bashrc)
    assert p.peek_error is None or p.peek_error == ""
    assert p.extractable is True
    assert "alias" in p.peek_text

    d = decide(p)
    assert d.skipped is False
    assert d.routes == ["T1"]
    assert any(".bashrc" in n for n in d.notes)


def test_useful_dotfiles_huge_route_to_t0(tmp_path: Path):
    """Big enough dotfiles spill into T0 just like big .txt does."""
    from src.router import decide, peek

    big = tmp_path / ".bashrc"
    big.write_text("# alias\n" * 20_000)  # >100 KB threshold

    d = decide(peek(big))
    assert d.routes == ["T0"]


def test_router_allowlist_matches_walker_allowlist():
    """Both modules must reference the same set object."""
    from src.ingest.walker import _USEFUL_DOTFILE_NAMES as walker_set
    from src.router import USEFUL_DOTFILE_NAMES as router_set
    assert walker_set is router_set
