# How to run a Magpie evaluation

From a fresh clone to a judged, reported eval run. Two paths: **with Claude
Code** (recommended — the skills drive everything and interview you) and
**manual CLI** (no Claude needed except for the judge step).
[README.md](README.md) is the mechanics reference; [PLAN.md](PLAN.md) is the
design rationale. This file is the "I just cloned the repo" path.

## Platform status (2026-08-30, honest)

| OS | Status |
|---|---|
| macOS (Apple silicon) | Proven — every run so far happened here |
| Linux | Expected to work (all paths/binaries resolve per-platform); untested — first run should be watched |
| Windows | **Blocked** on known fixes: qdrant teardown uses `os.killpg`, worker env allowlist lacks `SYSTEMROOT`/`USERPROFILE`/`TEMP`, llama-server path lacks `.exe` |

## Prerequisites (once per machine)

```bash
uv sync                     # python env (uv: https://docs.astral.sh/uv/)
just download-qdrant        # per-platform qdrant binary -> frontend/src-tauri/binaries/
just install-llama-server   # per-platform llama-server -> <app-data>/bin/
                            #   Linux GPU: LLAMA_SERVER_GPU=cuda-* just install-llama-server
```

- **Models download themselves** on the first run (ColQwen2.5 or ColSmol by
  machine spec, the answer LLM, rerank/embedding models) into
  `<app-data>/cache/`. First index run is therefore slow; everything after is
  cached. `<app-data>` = `~/Library/Application Support/Magpie` (mac),
  `~/.local/share/Magpie` (Linux), `%LOCALAPPDATA%\magpie\Magpie` (Windows).
- **Machine gate**: ColQwen2.5 needs ≥8 GB dedicated VRAM (CUDA) or ≥24 GB
  unified memory (Apple silicon); below that the visual tier runs ColSmol-500M
  — a *different retriever*, so don't compare such runs against ColQwen runs.
- **The Magpie app is NOT required.** The harness only reuses the app's
  directory convention and installer scripts, and it never touches a live
  app's Qdrant or data (own ports, own scratch dirs, isolation verified per
  run).
- **`claude` CLI, logged in, with Opus access** — required for the judge and
  for the skills. The deterministic layers (index/retrieve/answer/metrics)
  run without it.

## Dataset (once per dataset per machine)

Corpora never live in the repo. For the built-in `receipts` dataset (public
SROIE scans, downloads from HuggingFace):

```bash
uv run python eval_harness/scripts/prepare_receipts.py
```

This writes the corpus to disk, `manifest.json` (sha256 pins), and
`datasets/receipts/corpus_root.local.json` — the per-machine pointer the
runner requires. `--verify` re-checks an existing corpus. For a new corpus of
your own, the `/magpie-eval` skill sets the dataset up during its interview.

## The Claude way (recommended)

Open Claude Code in the repo and type:

```
/magpie-eval
```

The skill interviews you (dataset, golden set reuse/generate, ONE config —
it will always ask about rerank and the solo gate explicitly), generates
persona-real questions by actually reading your files if asked, launches the
run in the background with progress updates, judges every answer with a
full-context judge, then writes three agent reports plus a supervisor
synthesis into `eval_harness/runs/<run_id>/`.

To compare two finished runs:

```
/magpie-eval-compare
```

Deterministic paired diff (discordant counts + exact McNemar p — sub-5
discordant deltas are flagged as noise), agent cause-attribution for every
flipped question, and a verdict that answers the question you give it.

## The manual way

```bash
# one run under one config (configs/baseline.json is the template)
uv run python eval_harness/harness/run.py --config eval_harness/configs/baseline.json

# useful flags:
#   --questions-limit 4      smoke test
#   --index-only             build/cache the index and stop
#   --retrieval-only         cheap retrieval metrics, no generation
#   --rebuild-index          ignore the index store
#   --slot 1                 second concurrent run (separate ports)
```

The run is self-contained: private qdrant, pinned env (snapshot in
`run.json`), resumable per-phase, enrichment + deterministic metrics run
automatically at the end (`metrics.json`, `report.md`). Indexes cache in
`eval_harness/indexes/` keyed by dataset + index-side params — the second run
with the same index config mounts in seconds.

Judge (needs `claude` CLI):

```bash
uv run python eval_harness/judge/judge.py --run-dir eval_harness/runs/<run_id>
```

Compare (no Claude needed for the deterministic part):

```bash
uv run python eval_harness/harness/compare.py <baseline_run> <other_run>
```

## What a finished run contains

```
eval_harness/runs/<run_id>/
  run.json            provenance: params, env snapshot, scoped git SHAs,
                      golden_sha, isolation verdicts, solo_gate stamp
  metrics.json        deterministic metrics; retrieval on BOTH bases
                      (pre-gate ranking AND end-to-end) + divergence counts
  answers_enriched.json  per-question rows (magpie_answer / golden_answer)
  judge_verdicts.json + JUDGE-REPORT.md      (after the judge)
  REPORT-*.md + SUPERVISOR-REPORT.md         (after the skill's agents)
  raw/                gitignored: logs, scratch app-data, private qdrant
```

Commit the summaries; `raw/` and `indexes/` never leave the machine
(gitignored — see .gitignore's eval_harness block for why).

## Interpreting results — two rules

1. **Judge verdicts are the authority on answer quality**; `metrics.json`'s
   deterministic verdicts are a matcher, always labeled as such, and the
   judge's report lists every disagreement with them.
2. Runs are comparable question-for-question only when the triple
   (params, backend git SHA, golden_sha) differs on exactly the axis you
   mean to test. The compare tool checks this for you and names the axis.
