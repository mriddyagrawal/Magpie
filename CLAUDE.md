# Repo instructions for Claude

- **Commits: never add Claude as an author or co-author.** No
  `Co-Authored-By: Claude ...` trailer, no Claude-identifying commit metadata,
  on any branch. Commit author is always the human's git identity.
  (Owner directive, 2026-08-29.)

- **Every new or changed env knob must be threaded through the eval harness
  in the same change.** Whenever code adds, renames, or changes the default
  of an environment variable that alters behaviour (`os.environ.get(...)` in
  `src/`), do all of the following before committing:
  1. Pin it in `eval_harness/harness/envctl.py:build_env` from a `params`
     key, ALWAYS set (never "unset = default": `load_dotenv` fills unset vars
     from this machine's `.env`, so an unpinned knob silently inherits a
     dotfile value).
  2. Add the params key with the production default and a `_notes` entry to
     `eval_harness/configs/baseline.json`.
  3. Add the default to `PARAM_DEFAULTS` in `eval_harness/harness/compare.py`
     so runs recorded before the knob existed compare as "unchanged", not as
     a confounding config diff.
  4. Extend the managed-key list in `eval_harness/tests/test_envctl.py` and
     document the variable in `.env.example`.
  Why: the harness's #115 rule (one knob per comparison) only holds if every
  knob is pinned and defaulted. The 2026-09-03 grounding-guard toggle
  (e4ce01d) showed the failure: two new params made every comparison against
  earlier runs report as confounded until defaults were mapped.
