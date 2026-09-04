---
name: did-magpie-drift
description: Investigate whether the open-source pieces under Magpie (llama.cpp, Qdrant, the GGUF weights, the col encoders, the Python lockfile) have moved and whether any of Magpie's mirrored assumptions broke - runs the drift guard, reads its evidence, attributes what changed, and recommends the fix. Trigger with /did-magpie-drift.
---

# Did Magpie drift? - analysis procedure

You are answering ONE question for the owner: **did anything underneath
Magpie move, and did it break an assumption Magpie's code makes about
it?** The deterministic layer is code (`src/drift/`, `just check-drift`);
your job is the part code cannot do: reading the evidence together,
attributing a change to a component, judging whether it matters, and
saying what to do next. Ask the owner whenever uncertain (AskUserQuestion
is fine - they prefer questions over guesses). Read-only over `src/`
unless the owner explicitly asks for a fix.

## What the guard actually checks (know this before reading output)

| Layer | Mechanism | What it catches |
|---|---|---|
| **pins** (`src/drift/pins.py`) | installed llama-server build / Qdrant version vs the validated constants | a binary that is not the one we tested on |
| **provenance** (`provenance.py`) | fingerprint over llama-server build+commit, GGUF + mmproj sha256, col model, `uv.lock` hash, platform | *anything* in that set changed since the last check (keys the oracle cache; stamped into every eval `run.json`) |
| **oracle `image_tokens`** | 4 synthetic sizes against the live server vs `estimate_image_tokens` | llama.cpp's LFM2 tiling math moved (under-estimate = HTTP 400s in production) |
| **oracle `grammar`** | product-exact GBNF probe | the sampler no longer enforces the grammar (structured output silently broken) |
| **oracle `vector_dims`** | stored Qdrant collection widths vs encoder constants | an encoder swap that left stale vectors behind |
| **tripwire** (`tripwire.py`) | every local completion: text via `/tokenize` + image estimate vs `usage.prompt_tokens` | the token math drifting on REAL traffic, same day |
| **compare.py `runtime` axis** | provenance fingerprint differs between two eval runs | a metric that moved because a binary/model bumped |

Nothing here covers: prompt-template rendering changes inside llama.cpp
(image placement, role tokens), Qdrant query semantics, colpali-engine
output changes, or Python-package behaviour changes that don't alter a
hash. If the symptom points there, say so - the guard is silent on it by
design and the eval harness is the only detector.

## Phase 1 - Collect the evidence (deterministic)

Run, in order, and READ the output rather than summarising it:

1. `uv run python -m src.drift status --json` - provenance, pin mismatches,
   cached oracle verdicts for the current fingerprint, tripwire counters.
2. `uv run python -m src.drift check --force` - re-runs the three oracles
   against the real llama-server (spawns the 3B vision model if needed,
   ~30 s) and Qdrant if reachable. Say up front that it loads the model.
3. `<APP_DATA_DIR>/drift/` (macOS: `~/Library/Application Support/Magpie/drift/`):
   list `oracles-*.json` (one per fingerprint ever seen - MORE THAN ONE
   means the runtime changed at some point; diff the fingerprints' inputs),
   and read `tripwires.jsonl` (each line is a real request whose cost
   exceeded the prediction).
4. `git log --oneline -20 -- src/drift/pins.py src/tools/install_llama_server.py uv.lock justfile`
   - deliberate bumps, with dates.
5. The last few eval runs' `run.json` `provenance` blocks
   (`eval_harness/runs/*/run.json`) - what fingerprint each run was
   stamped with, and whether `compare.py` flagged `<runtime>` in any
   `eval_harness/comparisons/*/comparison.json`.

If the owner named a symptom (an HTTP 400, prose where JSON was expected,
empty search results, a metric that moved), collect the artefact for it
too: the worker log, the llm log line, the enriched row.

## Phase 2 - Attribute

For every difference found, answer three things:

- **Which component moved?** Map it through the table: llama-server build
  -> tiling math + grammar + template; model file hash -> tokenizer,
  tiling config (`processor_config`), grammar behaviour; col model ->
  vector dims + retrieval quality (index-side, needs a rebuild); `uv.lock`
  -> qdrant-client / colpali-engine / huggingface_hub behaviour; platform
  -> GPU backend (Metal vs CPU changes prefill speed AND fp16 NaN behaviour).
- **Did it break a mirrored assumption?** The oracle verdicts answer this
  for the three assumptions they cover. For `image_tokens` failures, run
  the full 23-size calibration to see the SHAPE of the drift:
  boot a throwaway server on a free port with the model + mmproj (see the
  script's docstring), then
  `uv run python eval_harness/scripts/calibrate_image_tokens.py --port <p>`.
  Which sizes under-count tells you what changed (threshold, grid choice,
  thumbnail rule, per-tile tokens).
- **Was it deliberate?** A pin bump commit with `check-drift` in its
  message is a validated upgrade; an installed build that differs from the
  pin with no commit is an accident (someone ran `brew upgrade`, or
  `LLAMA_SERVER_VERSION` is set in `.env` - check env var NAMES only,
  never print `.env` values).

When the llama-server build differs from the pin, fetch the llama.cpp
release notes between the two builds (WebFetch on the GitHub releases
page) and look specifically for `mtmd`, `clip`, `grammar`, `json_schema`,
`chat template`, `lfm2` - quote the relevant entries.

## Phase 3 - Judge and recommend

Write a short report (chat is fine unless the owner asks for a file):

1. **Verdict in one sentence**: no drift / drift, harmless / drift, broke X.
2. **Evidence table**: component, expected, found, source of evidence.
3. **Blast radius**: which user-facing paths are affected (answering,
   summarising at index time, retrieval, evals) and whether existing
   eval comparisons are still valid (any run pair spanning the change is
   `runtime`-confounded).
4. **Recommended action**, exactly one of:
   - *nothing* - verdict recorded, no change;
   - *re-pin* - the new build/model is intended: update
     `src/drift/pins.py` (and the justfile literal for Qdrant), run
     `just check-drift`, run an eval acceptance arm if inference or
     indexing is touched, then merge - offer to do the pin edit but do
     not touch `src/` without the owner's go;
   - *revert* - reinstall the pinned build (`just install-llama-server`
     honours the pin), rebuild the index if the col model changed;
   - *fix the mirror* - the upstream change is real and wanted, so
     `estimate_image_tokens` (or whichever mirror) must be updated to
     match, re-calibrated on all 23 sizes, and its tests re-pinned.
5. **Open questions for the owner**, if any.

## Hard rules

- Never edit `src/`, pins, or the justfile inside this skill unless the
  owner explicitly asks in this session; the deliverable is the analysis.
- Never print `.env` values; variable names only.
- Say when the guard is blind: an unchanged fingerprint with a real
  symptom means the cause is outside the guard's coverage (see the
  "nothing here covers" list) and the eval harness is the next tool.
- Quote numbers from the artefacts; do not paraphrase a verdict the code
  already printed.
