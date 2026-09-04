# Magpie Evaluation Harness

Deterministic, isolated eval runs for the Magpie backend. Design and rationale
live in [PLAN.md](PLAN.md); this file is the runbook. New here? Start with
[HOW_TO_RUN_EVALS.md](HOW_TO_RUN_EVALS.md) - fresh clone to judged run, with
and without Claude.

## One-time setup (fresh clone)

```bash
uv sync
just prepare-eval-harness        # binaries + models this machine will use
                                 #   (--check reports; --col / --llm pin;
                                 #   wraps download-qdrant, install-llama-server,
                                 #   and the model prefetch in one command)
just eval-smoke                  # ~5 min end-to-end sanity check (committed
                                 #   fictional corpus; loose-floor tripwire)

# per dataset, per machine. Corpora live either in-tree at
# datasets/<name>/corpus/ (gitignored) or anywhere via --corpus-dir:
uv run python eval_harness/scripts/register_corpus.py --name <name> [--corpus-dir DIR]
# the receipts dataset has its own fetcher (pinned SROIE download):
uv run --with datasets --with pillow python eval_harness/scripts/prepare_receipts.py
# NOTE: the judge reads corpus files IN FULL, so their contents go to the
# Claude API - if you point the harness at a personal corpus, that is what
# you are agreeing to (standing owner approval recorded in PLAN 9.4).
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
# live progress: `just eval-watch` serves http://127.0.0.1:8765/ - the
# harness writes raw/progress.json as it works; the page polls it
# variants:
#   --retrieval-only            retrieval sweep only (~2 min; no generation)
#   --index-only                build + report the index, stop
#   (indexes are cached automatically in eval_harness/indexes/ keyed by
#    dataset + index-side params; a matching entry mounts in seconds)
#   --rebuild-index             force a fresh index build + republish
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

## Drift guard (what happens when upstream moves)

Every run stamps `run.json` with a `provenance` block (llama-server build,
Qdrant version, GGUF/mmproj hashes, col model, lockfile hash) and
`compare.py` treats a changed fingerprint as a fourth comparability axis,
`runtime`, so a metric that moved because a binary was bumped is
attributed, not guessed. The checks themselves live in `src/drift/`:

```bash
just drift-status     # installed vs pinned, cached oracle verdicts, tripwire counts
just check-drift      # oracles against the real llama-server + Qdrant, then eval-smoke
```

Run `check-drift` after ANY llama-server / Qdrant / model / lockfile bump,
before merging it. Pins are in `src/drift/pins.py`.

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
