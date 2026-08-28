# Magpie Evaluation Harness

Deterministic, isolated eval runs for the Magpie backend. Design and rationale
live in [PLAN.md](PLAN.md); this file is the runbook.

## One-time setup (fresh clone)

```bash
just sync-environment            # uv deps
just download-qdrant             # bundled qdrant binary (the harness spawns
                                 #   its own instance per run — NEVER the
                                 #   live app's, and never port 6433)
just install-llama-server        # llama.cpp server binary
uv run python eval_harness/scripts/warm_model_cache.py   # REQUIRED, one-time,
                                 #   online: fills processor/tokenizer gaps in
                                 #   the shared cache. Runs go online but any
                                 #   model-blob download DURING a run fails the
                                 #   run's isolation check - warm first.
# per dataset, per machine (corpora live OUTSIDE the repo):
uv run --with datasets --with pillow python eval_harness/scripts/prepare_receipts.py
```

Prove isolation before trusting anything (Phase 0 exit test — boots the real
backend against a scratch dir, indexes, answers, and asserts the live app dir
is untouched and zero model blobs downloaded):

```bash
uv run python eval_harness/scripts/phase0_isolation_check.py
```

## Running an eval

```bash
uv run python eval_harness/harness/run.py --config eval_harness/configs/baseline.json
# variants:
#   --retrieval-only            retrieval sweep only (~2 min; no generation)
#   --index-only                build + report the index, stop
#   --reuse-index <run_id>      mount a prior run's index (same dataset +
#                               index-side params enforced via hash)
#   --questions-limit N         smoke-sized subset
```

Everything a run produces lands in `eval_harness/runs/<run_id>/`:

| Artifact | Committed? | What it is |
|---|---|---|
| `run.json` | ✅ | provenance: params, git SHA, machine, redacted env, isolation verdicts |
| `metrics.json` | ✅ | aggregate metrics incl. H1 slice, abstention, product findings |
| `report.md` | ✅ | human-readable report (silver-golden banner until review) |
| `answers_enriched.json` | ✅ | per-question rows: verdicts, retrieval, in_prompt, spans |
| `raw/` | ❌ gitignored | scratch appdata, qdrant storage, worker logs, JSONL |

A run FAILS (nonzero exit, artifacts still written) if the shared model cache
or the real app data dir changed during it — isolation is enforced, not
advisory.

## Judging (offline, separate from the runner by design)

```bash
uv run python eval_harness/judge/judge.py --run-dir eval_harness/runs/<id> [--dry-run]
```

Judges only rows the deterministic pass couldn't settle. Verdicts carry the
judge model + rubric sha; see [judge/rubric.md](judge/rubric.md). Do not act
on judged numbers until the golden set is human-verified (silver→gold review,
PLAN §6) and the judge is calibrated (PLAN §7 Phase 3).

## Review protocol

On the machine where this branch is being developed, commits are reviewed in
`comments.md` — a per-machine working-session artifact, local-only and never
committed; a fresh clone will not have it and doesn't need it. Reply inline
under the review block; severity tags are BLOCKER/MAJOR/MINOR/NIT.

## Where things live

```
eval_harness/
├── PLAN.md            design, phases, hypotheses docket, decisions
├── README.md          this runbook
├── harness/           envctl · backend · worker · run · enrich · metrics
├── judge/             rubric.md · judge.py
├── configs/           baseline.json (+ ablations/ later)
├── datasets/<name>/   golden.json · qrels.tsv · manifest.json (+ untracked
│                      corpus_root.local.json pointing at the local corpus)
├── scripts/           phase0 check · dataset prep · cache warm
├── tests/             unit + pytrec_eval cross-check (importorskip)
└── runs/<id>/         committed summaries + gitignored raw/
```
