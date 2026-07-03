git commit -m "$(cat <<'EOF'
PR1: IndexingRules — single config-driven gateway for "should this file be indexed?"

Replaces the ~459-line src/ingest/ignore.py + scattered .gitignore /
.nasignore handling + hardcoded DEFAULT_IGNORE_PATTERNS with one
layered system:

  1. src/config/magpie_defaults.json — shipped safety rails (migrated
     from DEFAULT_IGNORE_PATTERNS). User never edits this.
  2. <APP_DATA_DIR>/indexing_rules.json — user-controlled include_paths
     + exclude_paths + global_rules + category toggles. Auto-created on
     first run with sensible defaults; auto-extended by `just walk <path>`.
  3. Cascade-discovered .gitignore / .nasignore / .magpieinclude /
     .magpieexclude (new) at every directory depth.

Single public gateway: IndexingRules.should_index(path) -> (bool, reason).
Reason strings power `just walk-explain`, `just check`, `just check-dir`,
and the future GUI "why isn't this indexed?" panel. Linear precedence
chain documented in Plans/Ingestion Rules/Implementation Plan.md §4.

Key changes:
- src/config/ (new module): indexing_rules.py + magpie_defaults.json
- src/router.py: CATEGORY_MAP added (single source of truth for
  user-facing category↔extension mapping; existing TEXT_EXTS/CODE_EXTS/
  etc. untouched, become subsets)
- src/manifest.py: Entry.mtime added (optional; size-only is still the
  default; MAGPIE_DEV_USE_MTIME=1 enables size-AND-mtime check)
- src/ingest/walker.py: 4 IgnoreRules call sites swapped for
  IndexingRules.should_index() / .is_pruneable_dir(); walker auto-adds
  the requested path to include_paths if not already covered
- src/ingest/ignore.py: gutted to a deprecation shim — IgnoreRules
  removal raises a clear AttributeError pointing at the new system
- justfile: rename existing `sync` -> `sync-environment`; new `sync`
  walks all enabled include_paths in one shot. New `check <path>` and
  `check-dir <path>` recipes for dry-run rule explainers
- scripts/check_indexing.py: powers the two new check recipes
- pyproject.toml: psutil added (PR2 backpressure dep, harmless to add now)

Tauri sidecar (src/server.py + src/answer.py + src/stage2/) is
NOT touched — no IgnoreRules references in any production search/answer
code path. `pnpm tauri dev` and `pnpm tauri build` work unchanged.

Tests: 43 new tests (precedence chain, config load/save roundtrip,
CATEGORY_MAP consistency, .magpieinclude/.magpieexclude, mtime toggle).
Legacy tests/ingest/test_ignore.py (23 tests) ported via a thin compat
shim — same behavioral assertions, new API. tests/ingest/test_walk_pruning.py
(5 tests) ported to the new is_pruneable_dir API. Full suite: 459 pass,
16 fail (all 16 pre-exist on main; verified via git stash).

Plans/Ingestion Rules/Implementation Plan.md is the locked design doc.
Plans/Future Plans.md gains entries #12–#15 + addendum to #10:
- #12: routing data files (CSV/JSON/etc.) properly through tiers
- #13: daemon as true OS service (launchctl/systemd)
- #14: promote MAGPIE_DEV_USE_MTIME to user-facing setting
- #15: auto-promotion of nested rules into sub-roots (deferred from this PR)
- #10 addendum: packaging magpie_defaults.json for built binaries

Two follow-ups noted (not blocking PR1):
- Tests pollute the dev indexing_rules.json by auto-adding pytest tmp
  paths — should monkeypatch MAGPIE_DATA_DIR; quick win for PR2.
- Pre-existing mark_summarized Entry-replacement bug causes
  test_mark_summarized_preserves_fast_tier_state to fail on main too.
  Fix alongside Future Plan #11 work.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)" 2>&1 | tail -10