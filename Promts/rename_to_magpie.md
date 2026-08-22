Hey, I have changed the name of this repo on GitHub from `NotAnotherSpotlight`
to `Magpie`. The product itself is already called Magpie internally — the
desktop UI, the cloud server (`server/magpie_server/`), and the macOS data
directory (`~/Library/Application Support/Magpie/`) all use the new name.
The leftover references to "NotAnotherSpotlight" / "notspotlight" /
"notanotherspotlight" are all cosmetic. Please implement this — rename them
consistently so nothing on the machine still says the old name.

Before you make any changes, run these to ground yourself:
  - `pwd` — confirm you're inside the renamed repo (path should end in `/Magpie`)
  - `git remote -v` — confirm what the origin URL currently is
  - `ls ~/.cache/notspotlight/ 2>/dev/null && echo 'old daemon state exists'`
  - `just daemon-status` — note whether the daemon is running

Plan, in this order. Pause and check with me before any step that changes
state I can't easily roll back (renaming live directories, uninstalling the
CLI tool).

1. Local folder: if the parent folder is still `NotAnotherSpotlight/`, leave
   that to me — I'll do the `mv` outside the editor since the working
   directory is locked while Claude Code runs. If the folder is already
   `Magpie/`, skip this step.

2. Git remote: update origin to the new URL with
   `git remote set-url origin https://github.com/mriddyagrawal/Magpie.git`,
   then `git remote -v` to verify. The old URL still works via GitHub's
   permanent 301 redirect, but updating is cleaner.

3. Daemon state migration. If `~/.cache/notspotlight/` exists, stop the
   daemon first (`just daemon-stop`), then rename the directory to
   `~/.cache/magpie/` so socket/pidfile/authkey/log all move with it.
   Update `src/daemon/paths.py` to reference `magpie` instead of
   `notspotlight` (look for the literal string "notspotlight" in the
   `_state_dir()` and `socket_address()` functions).

4. Python package rename in `pyproject.toml`: change
   `name = "notanotherspotlight"` to `name = "magpie"`. After this lands,
   delete the stale `notanotherspotlight.egg-info/` directory — `uv sync`
   regenerates it under the new name.

5. CLI package rename: `cli/notspotlight/` → `cli/magpie/`. Update
   `cli/pyproject.toml` to reflect the new package name. KEEP the existing
   short aliases (`ns`, `nas`) as console-script entry points — those are
   muscle-memory shortcuts. Add `magpie` as the canonical entry point;
   make `notspotlight` a deprecated alias that prints a one-line warning
   and forwards to `magpie` for one release cycle, then can be removed.

6. Update every import site. Grep for `from notspotlight` and `import
   notspotlight` across the repo and rewrite to `from magpie` /
   `import magpie`. Don't miss test files, `cli/notspotlight/repl.py`'s
   own internal imports, or the workspace declaration in the root
   `pyproject.toml` (`[tool.uv.sources]` and `[tool.uv]` workspace).

7. The `HISTORY_FILE` constant in the REPL is `~/.notspotlight_history`.
   Migrate it: rename to `~/.magpie_history` if the old file exists,
   otherwise just update the constant. Losing prompt history is fine if
   the file's missing.

8. Justfile updates: any user-facing message that says "notspotlight" or
   "NotAnotherSpotlight" gets updated. Specifically the `chat` target's
   `uv run notspotlight` command → `uv run magpie`, and the `install`
   target's success message at the bottom. Don't rename the targets
   themselves (`just chat`, `just install`) — those names are fine.

9. README.md: rewrite the "# NotAnotherSpotlight" heading and the
   prose first paragraph to use "Magpie" as the product name. Leave any
   sentence whose meaning depends on the old name (none should — the rest
   of the README already says Magpie throughout).

10. Other docs: scan `Plans/`, `IO/`, `Promts/`, `man_build/` for
    "NotAnotherSpotlight" / "notspotlight" mentions. Update prose
    references but don't rewrite historical decision logs — a doc dated
    2026-04 that says "the NotAnotherSpotlight repo" can stay as a
    historical record. Use judgment.

11. Reinstall the CLI tool so the new aliases register:
    `just uninstall && just install`. Verify all four aliases work:
    `magpie --help`, `ns --help`, `nas --help`, and `notspotlight --help`
    (the last one should print the deprecation warning).

12. Run the full test suite: `just test`. Everything that passed before
    must still pass. Pre-existing failures (collected before this rename)
    are fine if they're unrelated — verify by `git stash && just test`
    on the parent commit.

13. When everything is green, commit with a message like
    "Rename: NotAnotherSpotlight → Magpie (cosmetic)".
    Don't push without showing me the diff first.

Things NOT to touch:
- The runtime data directory at `~/Library/Application Support/Magpie/`
  (manifest, summaries, qdrant_data) — already correctly named.
- The cloud server at `server/magpie_server/` — already correct.
- The Tauri product name in `frontend/src-tauri/tauri.conf.json` — already
  "Magpie".
- The `MAGPIE_*` environment variables in `.env.example` — already correct.
- Any string inside `.git/` or `.venv/`.

Audit before declaring done:
`grep -rn "notanotherspotlight\|NotAnotherSpotlight\|notspotlight" \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules \
  --exclude-dir=target --exclude-dir=__pycache__ --exclude-dir=.turbo .`
The only acceptable hits are: historical Plans/IO docs you intentionally
left alone, and the deprecated `notspotlight` alias's warning message.
Everything else should be Magpie.

---

ONE LAST THING: when you're fully done — tests green, audit clean, commit
landed — DELETE THIS FILE (`Promts/rename_to_magpie.md`) and amend the
rename commit to include its removal. It's a one-time prompt; no need to
keep it around in the repo's history of permanent prompts. After the
amend, show me `git log -1 --stat` so I can confirm the file is gone from
the tree before I push.
