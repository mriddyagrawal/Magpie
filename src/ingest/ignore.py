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
    # Custom-named venvs (e.g. `dpp/lib/python3.12/site-packages/`, `myproj/Lib/site-packages/`)
    # — `site-packages/` is universally a Python install directory, never user content.
    "site-packages/",
    "*.egg-info/",
    "*.dist-info/",                  # pip-installed package metadata (sibling of site-packages)
    "pip-cache/",                    # pip wheel cache
    "pip_cache/",                    # pip wheel cache (alt name)
    "pip-packages/",                 # buildout-style local pip install
    # PhotoRec / TestDisk recovery output. `found.NNN/` is the recovery root
    # and `dirNNNN.chk/` are the chunk subdirectories. Recovered files are
    # heavily duplicated, often partial, and bypass the user's own folder
    # organization — low-value for retrieval. Users who genuinely want them
    # indexed can `!found.001/` in a per-corpus `.nasignore` to opt back in.
    "found.[0-9]*/",
    "*.chk/",
    # Node / JavaScript / TypeScript
    "node_modules/",
    ".next/",
    ".nuxt/",
    ".parcel-cache/",
    ".turbo/",
    ".vercel/",
    ".netlify/",
    ".svelte-kit/",
    ".angular/",
    ".firebase/",
    "bower_components/",
    # Rust / Go / Java / .NET (compiled outputs are not in SUPPORTED_EXTS so
    # we don't double-filter them; what these patterns catch is folders that
    # CONTAIN supported-ext text noise — CMake configs, IDE project files,
    # generated metadata).
    "target/",                       # Rust / Maven
    "bin/",                          # IDE / .NET
    "obj/",                          # .NET
    "*.rs.bk",                       # rustfmt backup
    # Build / dist (generic)
    "build/",
    "dist/",
    "out/",
    ".output/",
    "coverage/",                     # test-coverage reports (unit-test runners)
    # C / C++ / autotools / CMake
    "CMakeFiles/",
    "CMakeCache.txt",
    "cmake_install.cmake",
    ".deps/",                        # autotools dep tracking
    ".libs/",                        # libtool
    "autom4te.cache/",
    "config.log",
    "config.status",
    "config.cache",
    "*.dSYM/",                       # macOS debug-symbol bundles (also Swift)
    # C# / Visual Studio (`.vs/` is in IDE section above; these are stragglers)
    "*.suo", "*.user", "*.userosscache", "*.sln.docstates",
    "*.opendb", "*.opensdf", "*.VC.db", "*.VC.opendb",
    "*.tlog",
    # Java / Kotlin / Gradle / IntelliJ project state
    ".gradle/",
    "*.iml",
    "*.ipr",
    "*.iws",
    # Swift / Xcode / iOS
    "DerivedData/",
    "xcuserdata/",
    "Pods/",                         # CocoaPods
    ".swiftpm/",
    # Haskell
    ".stack-work/",
    "dist-newstyle/",
    ".cabal-sandbox/",
    "cabal.sandbox.config",
    # Erlang / Elixir
    "_build/",
    ".elixir_ls/",
    # Scala
    ".bloop/",
    ".metals/",
    ".bsp/",
    # Ruby
    ".bundle/",
    "vendor/bundle/",                # NB: bare `vendor/` deliberately NOT
                                     # ignored — too generic, collides with
                                     # legit user content (e.g. "vendor/" as
                                     # a literal user folder, Go-vendored
                                     # source the user wants searchable, etc.)
    # NOTE on intentionally-NOT-ignored patterns:
    #   `packages/`  — collides with Apple Packages, generic "packages" dirs
    #   `vendor/`    — see above
    #   `deps/`      — too generic, used in Erlang AND non-build contexts
    #   `*.log`      — `.log` is in TEXT_EXTS (server / app logs are
    #                  legitimate user content). LaTeX logs leak as a
    #                  known limitation; user can `.nasignore` them.
    #   `core.*`     — `core.py` etc. would false-positive. Plain `core`
    #                  is below in the Unix section.
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
    # System temp + cache directories — these contain transient state from
    # other tools (compiler intermediates, browser caches, pytest fixtures,
    # OS metadata) that should never be indexed as documents. Real instance
    # observed 2026-04-25: a pytest-fixture path leaked into the user's
    # production manifest because the test root happened to be `/tmp/...`
    # and the manifest persisted across runs. The patterns are gitignore
    # syntax, so they catch these directories at any depth under the walk
    # root — `tmp/` matches both `/tmp/...` (when walking `/`) and
    # `<corpus>/tmp/...` (when walking a corpus that contains a tmp folder).
    "tmp/",
    "var/tmp/",
    ".cache/",                       # XDG / Linux user cache
    "**/Library/Caches/**",          # macOS user caches (multi-segment → needs **/)
    "**/AppData/Local/Temp/**",      # Windows user temp
    "**/AppData/Local/Cache/**",     # Windows user cache
    # Pytest fixture roots — `pytest-of-<user>/` is created by pytest's
    # tmp_path fixture and lives under /tmp on Linux; explicit pattern
    # catches it when /tmp/ itself isn't filtered (e.g. during dev runs).
    "pytest-of-*/",
    # macOS metadata sidecars + zip-extraction noise
    "__MACOSX/",
    ".fseventsd/",
    ".Spotlight-V100/",
    ".TemporaryItems/",
    ".Trashes/",
    ".AppleDouble/",
    "._*",                           # macOS resource fork sidecars on non-HFS
    ".AppleDB/",
    ".AppleDesktop/",
    ".AppleSystemFiles/",
    ".DocumentRevisions-V100/",      # Versions / autosave history
    ".PKInstallSandboxManager/",     # macOS installer state
    ".com.apple.timemachine.donotpresent",
    ".com.apple.timemachine.supported",
    ".metadata_never_index",         # Spotlight opt-out marker — also a hint we should ignore
    ".VolumeIcon.icns",
    "Network Trash Folder/",         # AFP volume trash
    "Temporary Items/",              # legacy macOS temp
    "*.sparsebundle/",               # Time Machine encrypted bundle
    "Backups.backupdb/",             # Time Machine over AFP
    "Library/Containers/",           # macOS App Store sandbox
    "Library/Logs/",
    "Library/CrashReporter/",
    # Trash bins (Linux + macOS)
    ".Trash/",
    ".Trash-*/",
    # Windows-mount cruft — surfaces when ingesting an external NTFS/exFAT
    # drive shared with a Windows install. None of these contain user
    # documents; they're per-user trash bins, recovery state, installer
    # caches, and OS metadata.
    "$RECYCLE.BIN/",
    "$Recycle.Bin/",                 # case-variant — gitignore is case-sensitive on Linux
    "RECYCLER/",                     # pre-Vista Windows recycle bin
    "System Volume Information/",
    "Config.Msi/",
    "Recovery/",                     # Windows recovery partition contents
    "MSOCache/",                     # Office install cache
    "PerfLogs/",                     # Windows perf monitor logs
    "Documents and Settings/",       # XP-era junction; on modern systems redirects to /Users
    # Windows system + program folders — when ingesting a mounted Windows
    # partition (`/mnt/win/`, etc.), these are gigabytes of system binaries
    # and app installs, never user documents.
    "WindowsApps/",
    "Program Files/",
    "Program Files (x86)/",
    "ProgramData/",
    "$WINDOWS.~BT/",                 # Windows 10/11 in-place upgrade staging
    "$WINDOWS.~WS/",                 # same — different stage
    "$Windows.~BT/",                 # case-variant
    "$GetCurrent/",                  # Windows Update download
    "$SysReset/",                    # Windows Reset state
    "OneDriveTemp/",                 # OneDrive sync staging
    # Windows file artifacts at C:\ root or system locations
    "pagefile.sys",
    "hiberfil.sys",
    "swapfile.sys",
    "DumpStack.log",
    "DumpStack.log.tmp",
    "bootmgr",
    "BOOTNXT",
    "BOOTSECT.BAK",
    "NTUSER.DAT*",                   # per-user Windows registry hive
    "ntuser.dat*",                   # case-variant
    "~$*",                           # Office lock file (e.g. ~$Document.docx — open by Word)
    "IconCache.db",
    # Unix recovery + filesystem snapshots
    "lost+found/",                   # ext{2,3,4} fsck recovery; root-only, never user content
    ".snapshots/",                   # btrfs / nilfs / Snapper snapshot directories
    ".zfs/snapshot/",                # ZFS auto-snapshot tree
    "core",                          # literal core dump file (`core.py` etc. NOT matched)
    "*~",                            # emacs / nano single-tilde backup
    "\\#*#",                         # emacs autosave — `#` is the gitignore comment
                                     # char so we escape the leading one. The
                                     # pattern still matches plain `#foo#` files.
    ".#*",                           # emacs lock files (already covered by leaf-dotfile skip,
                                     # but explicit here for clarity)
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
    # Office-archive decomposition: when someone unzips a .pptx / .docx / .xlsx
    # into a folder, the `*_extracted/<type>/media/` path holds the raw image
    # assets (slide clipart, icons, chart pics). These are NOT documents — they
    # get indexed as single-page images by T4/ColPali, each eating ~1 MB of
    # vector storage for content the user never actually searches for. These
    # patterns are safe as universal defaults because the `ppt/media/`,
    # `word/media/`, `xl/media/` structure is mandated by Microsoft's OOXML
    # spec — not a user naming choice — so the path IS the boundary.
    "**/*_extracted/ppt/media/**",
    "**/*_extracted/word/media/**",
    "**/*_extracted/xl/media/**",
    # NOTE on scattered decorative files (logos, favicons, stock photos):
    # we deliberately do NOT pattern-match filenames like `*logo.png` or
    # `favicon.*` at the default level. Filename patterns are too brittle
    # (users name things `crest.png`, `school_symbol.png`, etc.). Instead,
    # the walker applies a sibling-density rule: folders where images
    # dominate and no documents live are treated as asset libraries and
    # their images are skipped — see src/ingest/walker.py.
    #
    # Common-secret filenames — never index, even with `--force`. Most secret
    # locations (`.ssh/`, `.gnupg/`, `.aws/`) are dot-folders, already pruned
    # by the walker. These patterns cover loose secret files that could land
    # outside dot-folders (e.g. a project's `.env` inside its source tree).
    # Keep narrow — false positives silently drop legitimate user content.
    ".env",
    ".env.*",
    ".npmrc",
    ".netrc",
    ".pgpass",
    ".git-credentials",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "id_ecdsa",
    "id_ecdsa.*",
    "id_dsa",
    "id_dsa.*",
    "*.pfx",
    "*.p12",

    # Photo libraries (macOS bundles — internal app state, not user content)
    "*.photoslibrary/",
    "Photos Library.photoslibrary/",

    # iWork / Pages bundles — not internal state, but treating as opaque is right
    # (the bundle's internal XML isn't useful to embed; user wants the doc as a doc)
    "*.pages/",
    "*.numbers/",
    "*.key/",

    # Cloud sync internal state
    ".dropbox.cache/",
    ".dropbox/",                        # Dropbox metadata folder (rare but exists)
    "OneDrive/.~tmp/",                  # OneDrive sync staging (path-relative)

    # OneDrive conflict files (byte-identical caught by dedup; this catches the renamed-but-modified ones)
    "*-conflict-*.{docx,xlsx,pptx,pdf,txt,md}",
    "*-{Mac,PC,iPhone,iPad,Android}-*-conflict.*",

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
        """Scan `root` once; collect every `.gitignore` / `.nasignore` beneath it.

        Prunes the walk on:
          * Dot-folders (`.git/`, `.config/`, `.venv/`, ...)
          * Any directory matching a built-in default-ignore pattern
            (`node_modules/`, `Program Files/`, `target/`, `WindowsApps/`,
            `System Volume Information/`, ...)

        Without these prunes, on a 1 TB drive we'd `os.walk` straight into
        `node_modules/` (50k+ files per package), `Library/Containers/`,
        `Program Files/`, etc. just to discover they don't contain
        `.gitignore` files we'd care about anyway.
        """
        rules = cls(root=root.resolve())
        for dirpath, dirnames, filenames in os.walk(rules.root):
            # Prune hidden directories AND default-ignored directories in-place.
            dirpath_p = Path(dirpath)
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".")
                and not rules.is_default_ignored_dir(dirpath_p / d)
            ]
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

    def is_default_ignored_dir(self, abs_dir: Path) -> bool:
        """True if a directory matches a built-in default-ignore pattern.

        Used by `from_root` and the walker's `find_candidates` to **prune the
        walk** at the directory level, not just filter files. Without this,
        we descend into `node_modules/` to filter 50k files individually
        instead of skipping the whole subtree.

        Folder patterns in `DEFAULT_IGNORE_PATTERNS` are kept with trailing
        `/` so we test `<rel>/` against the spec.
        """
        try:
            rel = abs_dir.resolve().relative_to(self.root)
        except (ValueError, OSError):
            return False
        rel_str = str(rel)
        if not rel_str or rel_str == ".":
            return False  # don't prune the walk root itself
        return self._defaults.match_file(rel_str + "/")

    def is_ignored(self, path: Path) -> bool:
        """Return True if `path` matches any ancestor's ignore rules.

        Built-in defaults always apply. User rules from `.gitignore` /
        `.nasignore` apply relative to the directory they were declared in.

        Gitignore semantics: dir-only patterns (e.g. `$RECYCLE.BIN/`,
        `movies/`) only match when the path is presented with a trailing
        slash. We detect via `path.is_dir()` and append a `/` so dir-only
        patterns fire correctly. Without this, the rule existed but
        directories silently slipped through.
        """
        try:
            resolved = path.resolve()
        except OSError:
            return False
        try:
            suffix = "/" if resolved.is_dir() else ""
        except OSError:
            suffix = ""

        # 1. Built-in defaults — match against path relative to the walk root
        try:
            rel_to_root = resolved.relative_to(self.root)
        except ValueError:
            return False    # outside the walk — don't ignore
        if self._defaults.match_file(str(rel_to_root) + suffix):
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
            if spec.match_file(str(rel) + suffix):
                return True
        return False

    def __repr__(self) -> str:
        return (
            f"IgnoreRules(root={self.root}, "
            f"user_dirs_with_rules={len(self._per_dir)}, "
            f"defaults={len(DEFAULT_IGNORE_PATTERNS)})"
        )
