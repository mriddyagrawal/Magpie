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


def test_windows_mount_cruft_ignored(tmp_path: Path):
    """When ingesting an external drive shared with Windows, $RECYCLE.BIN/
    and System Volume Information/ never contain user documents — they're
    OS metadata that should never be indexed."""
    # Real-world layout from a mounted NTFS drive
    _touch(tmp_path / "$RECYCLE.BIN" / "S-1-5-21-1001" / "$RZC2HSW.png")
    _touch(tmp_path / "$Recycle.Bin" / "user-folder" / "deleted.docx")
    _touch(tmp_path / "System Volume Information" / "VSS" / "blob.bin")
    _touch(tmp_path / "Config.Msi" / "rollback.dat")
    _touch(tmp_path / "Recovery" / "WindowsRE" / "winre.wim")
    _touch(tmp_path / "MSOCache" / "All Users" / "extras.txt")
    # Real user content alongside should still survive
    _touch(tmp_path / "real_doc.md", "actual content")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "$RECYCLE.BIN" / "S-1-5-21-1001" / "$RZC2HSW.png")
    assert rules.is_ignored(tmp_path / "$Recycle.Bin" / "user-folder" / "deleted.docx")
    assert rules.is_ignored(tmp_path / "System Volume Information" / "VSS" / "blob.bin")
    assert rules.is_ignored(tmp_path / "Config.Msi" / "rollback.dat")
    assert rules.is_ignored(tmp_path / "Recovery" / "WindowsRE" / "winre.wim")
    assert rules.is_ignored(tmp_path / "MSOCache" / "All Users" / "extras.txt")
    assert not rules.is_ignored(tmp_path / "real_doc.md")


def test_unix_recovery_and_snapshots_ignored(tmp_path: Path):
    """ext fsck recovery + filesystem snapshots have zero user content."""
    _touch(tmp_path / "lost+found" / "0001-orphan")
    _touch(tmp_path / ".snapshots" / "1" / "snapshot.xml")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "lost+found" / "0001-orphan")
    assert rules.is_ignored(tmp_path / ".snapshots" / "1" / "snapshot.xml")


def test_macos_resource_forks_on_non_hfs_ignored(tmp_path: Path):
    """`._foo.txt` (macOS resource fork sidecar) is OS metadata, not content."""
    _touch(tmp_path / "._real_doc.md", "macOS metadata blob")
    _touch(tmp_path / "real_doc.md", "actual content")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "._real_doc.md")
    assert not rules.is_ignored(tmp_path / "real_doc.md")


def test_default_patterns_include_windows_mount_cruft():
    """Smoke check that the new categorical-skip patterns are present."""
    assert "$RECYCLE.BIN/" in DEFAULT_IGNORE_PATTERNS
    assert "System Volume Information/" in DEFAULT_IGNORE_PATTERNS
    assert "lost+found/" in DEFAULT_IGNORE_PATTERNS


def test_windows_system_folders_ignored(tmp_path: Path):
    """Top-level Windows partition folders (when mounted at e.g. /mnt/win/)."""
    _touch(tmp_path / "WindowsApps" / "Microsoft.Office" / "manifest.xml")
    _touch(tmp_path / "Program Files" / "Adobe" / "Reader.exe.config")
    _touch(tmp_path / "Program Files (x86)" / "Steam" / "steam.cfg")
    _touch(tmp_path / "ProgramData" / "Microsoft" / "Crypto" / "x.txt")
    _touch(tmp_path / "$WINDOWS.~BT" / "Sources" / "uneeded.txt")
    _touch(tmp_path / "real_doc.md", "real")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "WindowsApps" / "Microsoft.Office" / "manifest.xml")
    assert rules.is_ignored(tmp_path / "Program Files" / "Adobe" / "Reader.exe.config")
    assert rules.is_ignored(tmp_path / "Program Files (x86)" / "Steam" / "steam.cfg")
    assert rules.is_ignored(tmp_path / "ProgramData" / "Microsoft" / "Crypto" / "x.txt")
    assert rules.is_ignored(tmp_path / "$WINDOWS.~BT" / "Sources" / "uneeded.txt")
    assert not rules.is_ignored(tmp_path / "real_doc.md")


def test_windows_root_artifacts_ignored(tmp_path: Path):
    """Per-user registry hive + Office lock files at corpus root."""
    _touch(tmp_path / "NTUSER.DAT", "binary blob")
    _touch(tmp_path / "ntuser.dat.LOG1", "tx log")
    _touch(tmp_path / "~$Document.docx", "office lock")
    _touch(tmp_path / "~$Spreadsheet.xlsx", "office lock")
    _touch(tmp_path / "Document.docx", "real")  # NOT a lock file

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "NTUSER.DAT")
    assert rules.is_ignored(tmp_path / "ntuser.dat.LOG1")
    assert rules.is_ignored(tmp_path / "~$Document.docx")
    assert rules.is_ignored(tmp_path / "~$Spreadsheet.xlsx")
    assert not rules.is_ignored(tmp_path / "Document.docx")


def test_macos_extra_metadata_ignored(tmp_path: Path):
    """Extended macOS metadata: AppleDB, AppleSystemFiles, DocumentRevisions, etc."""
    _touch(tmp_path / ".AppleDB" / "info.plist")
    _touch(tmp_path / ".DocumentRevisions-V100" / "rev.bin")
    _touch(tmp_path / ".PKInstallSandboxManager" / "sandbox.bin")
    _touch(tmp_path / ".metadata_never_index", "spotlight opt-out")
    _touch(tmp_path / "Network Trash Folder" / "deleted.txt")
    _touch(tmp_path / "Library" / "Containers" / "com.app" / "Data" / "x.txt")
    _touch(tmp_path / "Library" / "Logs" / "DiagnosticReports" / "crash.log")
    _touch(tmp_path / "Library" / "CrashReporter" / "crash.crash")
    _touch(tmp_path / "real_doc.md", "real")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / ".AppleDB" / "info.plist")
    assert rules.is_ignored(tmp_path / ".DocumentRevisions-V100" / "rev.bin")
    assert rules.is_ignored(tmp_path / ".PKInstallSandboxManager" / "sandbox.bin")
    assert rules.is_ignored(tmp_path / ".metadata_never_index")
    assert rules.is_ignored(tmp_path / "Network Trash Folder" / "deleted.txt")
    assert rules.is_ignored(tmp_path / "Library" / "Containers" / "com.app" / "Data" / "x.txt")
    assert rules.is_ignored(tmp_path / "Library" / "Logs" / "DiagnosticReports" / "crash.log")
    assert rules.is_ignored(tmp_path / "Library" / "CrashReporter" / "crash.crash")
    assert not rules.is_ignored(tmp_path / "real_doc.md")


def test_unix_emacs_artifacts_ignored(tmp_path: Path):
    """Emacs / nano backup + autosave / lock files."""
    _touch(tmp_path / "src.py~", "emacs backup")          # *~
    _touch(tmp_path / "#Untitled.org#", "emacs autosave")  # #*#
    _touch(tmp_path / ".#locked.txt", "emacs lock")         # .#*  (also dot-leaf)
    _touch(tmp_path / "core", "core dump file")             # exact name
    _touch(tmp_path / "real.py", "real")
    _touch(tmp_path / "core.py", "should NOT match `core`")  # core.py is fine

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "src.py~")
    assert rules.is_ignored(tmp_path / "#Untitled.org#")
    assert rules.is_ignored(tmp_path / ".#locked.txt")
    assert rules.is_ignored(tmp_path / "core")
    assert not rules.is_ignored(tmp_path / "real.py")
    # Critical: `core` pattern must not match `core.py`
    assert not rules.is_ignored(tmp_path / "core.py")


# ---------------------------------------------------------------------------
# Build-artifact patterns across languages
# ---------------------------------------------------------------------------

def test_c_cpp_build_artifacts_ignored(tmp_path: Path):
    """CMake / autotools generated files inside otherwise-supported folders."""
    _touch(tmp_path / "CMakeFiles" / "Foo.dir" / "DependInfo.cmake")
    _touch(tmp_path / "CMakeCache.txt")
    _touch(tmp_path / "cmake_install.cmake")
    _touch(tmp_path / ".deps" / "main.Plo")
    _touch(tmp_path / ".libs" / "libfoo.la")
    _touch(tmp_path / "autom4te.cache" / "output.0")
    _touch(tmp_path / "config.log", "")
    _touch(tmp_path / "config.status", "")
    _touch(tmp_path / "real.c", "int main(){return 0;}")  # real source

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "CMakeFiles" / "Foo.dir" / "DependInfo.cmake")
    assert rules.is_ignored(tmp_path / "CMakeCache.txt")
    assert rules.is_ignored(tmp_path / "cmake_install.cmake")
    assert rules.is_ignored(tmp_path / ".deps" / "main.Plo")
    assert rules.is_ignored(tmp_path / ".libs" / "libfoo.la")
    assert rules.is_ignored(tmp_path / "autom4te.cache" / "output.0")
    assert rules.is_ignored(tmp_path / "config.log")
    assert rules.is_ignored(tmp_path / "config.status")
    assert not rules.is_ignored(tmp_path / "real.c")


def test_xcode_swift_artifacts_ignored(tmp_path: Path):
    """DerivedData, xcuserdata, Pods/, .swiftpm/ never contain user content."""
    _touch(tmp_path / "DerivedData" / "MyApp" / "ModuleCache.noindex" / "x.pcm")
    _touch(tmp_path / "MyApp.xcodeproj" / "xcuserdata" / "user.xcuserstate")
    _touch(tmp_path / "Pods" / "Manifest.lock")
    _touch(tmp_path / ".swiftpm" / "Package.resolved")
    _touch(tmp_path / "AppDelegate.swift", "// real")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / "DerivedData" / "MyApp" / "ModuleCache.noindex" / "x.pcm")
    # `xcuserdata/` matches at any depth (gitignore semantics)
    assert rules.is_ignored(
        tmp_path / "MyApp.xcodeproj" / "xcuserdata" / "user.xcuserstate"
    )
    assert rules.is_ignored(tmp_path / "Pods" / "Manifest.lock")
    assert rules.is_ignored(tmp_path / ".swiftpm" / "Package.resolved")
    assert not rules.is_ignored(tmp_path / "AppDelegate.swift")


def test_jvm_artifacts_ignored(tmp_path: Path):
    """Gradle cache, IntelliJ project files."""
    _touch(tmp_path / ".gradle" / "8.0" / "checksums" / "checksums.lock")
    _touch(tmp_path / "MyProject.iml", "<module>...")
    _touch(tmp_path / "MyProject.ipr", "<project>...")
    _touch(tmp_path / "MyProject.iws", "<workspace>...")
    _touch(tmp_path / "Main.java", "// real")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / ".gradle" / "8.0" / "checksums" / "checksums.lock")
    assert rules.is_ignored(tmp_path / "MyProject.iml")
    assert rules.is_ignored(tmp_path / "MyProject.ipr")
    assert rules.is_ignored(tmp_path / "MyProject.iws")
    assert not rules.is_ignored(tmp_path / "Main.java")


def test_haskell_erlang_scala_artifacts_ignored(tmp_path: Path):
    _touch(tmp_path / ".stack-work" / "install" / "x86_64-linux" / "x.txt")
    _touch(tmp_path / "dist-newstyle" / "build" / "x.cabal")
    _touch(tmp_path / "_build" / "default" / "lib" / "myapp" / "x.txt")
    _touch(tmp_path / ".elixir_ls" / "build" / "x.json")
    _touch(tmp_path / ".bloop" / "myproj.json")
    _touch(tmp_path / ".metals" / "metals.lock")
    _touch(tmp_path / "real.hs", "main = putStrLn \"hi\"")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / ".stack-work" / "install" / "x86_64-linux" / "x.txt")
    assert rules.is_ignored(tmp_path / "dist-newstyle" / "build" / "x.cabal")
    assert rules.is_ignored(tmp_path / "_build" / "default" / "lib" / "myapp" / "x.txt")
    assert rules.is_ignored(tmp_path / ".elixir_ls" / "build" / "x.json")
    assert rules.is_ignored(tmp_path / ".bloop" / "myproj.json")
    assert rules.is_ignored(tmp_path / ".metals" / "metals.lock")
    assert not rules.is_ignored(tmp_path / "real.hs")


def test_modern_js_framework_caches_ignored(tmp_path: Path):
    _touch(tmp_path / ".parcel-cache" / "data.mdb")
    _touch(tmp_path / ".turbo" / "daemon.json")
    _touch(tmp_path / ".vercel" / "project.json")
    _touch(tmp_path / ".svelte-kit" / "build" / "x.js")
    _touch(tmp_path / "bower_components" / "jquery" / "package.json")
    _touch(tmp_path / "coverage" / "lcov.info")
    _touch(tmp_path / "src.ts", "// real")

    rules = IgnoreRules.from_root(tmp_path)
    assert rules.is_ignored(tmp_path / ".parcel-cache" / "data.mdb")
    assert rules.is_ignored(tmp_path / ".turbo" / "daemon.json")
    assert rules.is_ignored(tmp_path / ".vercel" / "project.json")
    assert rules.is_ignored(tmp_path / ".svelte-kit" / "build" / "x.js")
    assert rules.is_ignored(tmp_path / "bower_components" / "jquery" / "package.json")
    assert rules.is_ignored(tmp_path / "coverage" / "lcov.info")
    assert not rules.is_ignored(tmp_path / "src.ts")


def test_vendor_NOT_ignored_by_default(tmp_path: Path):
    """`vendor/` (Go, PHP, Ruby) is too generic to default-ignore — collides
    with legit folders. Only `vendor/bundle/` (Ruby Bundler) is specific
    enough to skip."""
    _touch(tmp_path / "vendor" / "MyAuthor" / "MyLibrary" / "src.go", "// real")
    _touch(tmp_path / "vendor" / "bundle" / "ruby" / "gems" / "x.gemspec")
    _touch(tmp_path / "real.go", "// real")

    rules = IgnoreRules.from_root(tmp_path)
    # Bare vendor/ NOT ignored
    assert not rules.is_ignored(tmp_path / "vendor" / "MyAuthor" / "MyLibrary" / "src.go")
    # vendor/bundle/ IS ignored (Ruby specific)
    assert rules.is_ignored(tmp_path / "vendor" / "bundle" / "ruby" / "gems" / "x.gemspec")
    assert not rules.is_ignored(tmp_path / "real.go")


def test_walker_find_candidates_filters_node_modules(tmp_path: Path):
    """End-to-end: find_candidates drops files under node_modules.

    Note: as of the walk-pruning fix, default-ignored directories are
    skipped at the directory level (`os.walk` never lists their children),
    so files inside them DON'T count toward `ignored` — that counter only
    captures per-file ignore-rule hits. The win is that we never stat'd
    those files in the first place. See `test_walk_pruning.py` for the
    direct measurement test.
    """
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
    # `ignored` is 0 because the prune skipped node_modules/ and build/
    # before per-file ignore-rule checks ran. That's the speed win.
    assert ignored == 0
    assert asset_skipped == 0    # no asset-library-shaped folders here
