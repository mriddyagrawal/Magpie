# Magpie Evaluation Harness — Master Plan

**Status:** draft for review · **Branch:** `evaluation_harness` · **Date:** 2026-08-28

The goal: a systematic, repeatable way to answer "what actually works and why" across
Magpie's parameter space — models, retrieval settings, prompt styles — on multiple
datasets, without overfitting to any one corpus and without ever touching the live
installed app.

This folder (`eval_harness/`) is self-contained. The legacy `Evaluations/` folder is a
separate one-off flow and is deliberately **not** used, extended, or modified by anything
here.

**Neutrality & pre-registered hypotheses:** the harness is hypothesis-neutral
infrastructure. Datasets, metrics, and the judge rubric are fixed before any runs and
are never tuned to make a particular model or config look good — a result that kills a
favored idea is the harness working. Hypotheses are written down *before* running only
so results can't be rationalized after the fact; being on this list buys a hypothesis
zero design influence. Current docket (add/remove freely):

- **H1 — model sufficiency:** where the gold file is retrieved and fits in budget,
  LFM2.5 answers ≥85% of extractive questions correctly; expected to break down on
  aggregation/enumeration and abstention. (§5's attribution split — retrieved-but-wrong
  vs. never-retrieved — is what tests this either way.)
- **H2 — rewrite:** query rewrite improves recall@5 on vague phrasings, adds little on
  keyword-style queries.
- **H3 — context width:** answer accuracy degrades as top-k grows past ~3–5 even while
  recall rises (attention dilution on a conv-heavy 3B).
- **H4 — grammar:** structured-output enforcement costs answer quality on small models.

---

## 1. Design principles

These are the converged decisions from our design discussion plus what the research
(OpenJarvis, ViDoRe/BEIR, Ragas/DeepEval, practitioner guidance) confirmed as standard
practice:

1. **Deterministic runner, no LLM in the execution path.** The harness is a plain Python
   CLI. Anything that needs judgment (golden-set generation, grading) is a separate
   offline pass over the runner's artifacts, so runs are reproducible and re-gradable.
2. **Three measurement surfaces, scored independently:** indexing quality, retrieval
   quality, answer quality. Retrieval metrics are deterministic IR math; answer metrics
   are deterministic asserts plus a binary-verdict LLM judge.
3. **Stage-factored cost control.** Index once per (dataset × col model × summary
   config), cache it, sweep answer-side parameters over cached indexes. Retrieve once at
   k_max and score all smaller top-k by truncation. Sweep retrieval-side parameters with
   a `--retrieval-only` mode (~5% the cost of a full run). Ablations from a baseline, not
   full factorial; targeted small grids only when an interaction is suspected.
4. **Full isolation.** Runs use a scratch data directory (env-var override), a fresh
   sidecar/pipeline instance per run, and never read or write
   `~/Library/Application Support/Magpie`. The one shared resource is the HF model
   weights cache, mounted read-only (re-downloading GBs of weights per run is waste, and
   weights are not state under test).
5. **Binary verdicts, never Likert.** Judges answer specific yes/no criteria
   (fact present? citation correct?), which makes judge precision/recall measurable and
   verdicts actionable.
6. **Judge hygiene:** reference-guided grading (judge sees the gold answer), pinned judge
   model version recorded in every output, judge from a different model family than the
   generator (self-preference bias is measured at 10–25% in the literature), one-time
   calibration against human labels.
7. **Everything lives in git:** golden sets, run configs, judge rubric (versioned), and
   run summaries. Corpora themselves stay out of the repo (size, privacy).
8. **Every run records its context:** git SHA of the backend, machine info, full
   parameter set, timestamps. Without this the run archive is uninterpretable in a month.

---

## 2. Parameter space

| Axis | Values (initial) | Binds to stage | Cost note |
|---|---|---|---|
| `dataset` | `receipts`, `personal_notes`, `furman_directory` (+ optional `mmlongbench` yardstick) | index | one cached index per (dataset × index-side config) |
| `col_model` | ColSmol vs ColQwen2.5 (confirm exact HF IDs in Phase 0) | index | doubles index builds; cached |
| `summary_model` / summary prompt | current default (+ variants later) | index | summaries are written by the gen model at index time → index-side, not answer-side |
| `gen_model` | LFM2.5-VL-3B vs Gemma (confirm exact IDs in Phase 0) | answer | full answer run per value |
| `provider` | `local` (primary) vs cloud (optional axis) | answer | cloud runs are fast but cost API money |
| `prompt_style` | `baseline` (current sandwich), `compact`, (room for more) | answer | full answer run per value |
| `grammar` | enforced vs off (response_format / structured output) | answer | full answer run per value |
| `rewrite` | on vs off | retrieval | scored via `--retrieval-only` (cheap) |
| `top_k` | 1, 3, 5, 12 | retrieval | **free** — retrieve once at k=12, truncate |
| `memory` | `null` (reserved; not built) | — | placeholder field only |

Baseline config = current production settings. Sweeps are ablations from baseline
(one axis at a time): per dataset that is ~7 answer runs instead of ~144.

---

## 3. Architecture

```
eval_harness/
├── PLAN.md                  ← this file
├── harness/                 ← Python package (the deterministic runner)
│   ├── run.py               ← CLI entrypoint
│   ├── sidecar.py           ← spawn/teardown of an isolated backend instance
│   ├── indexing.py          ← index stage + index report
│   ├── answering.py         ← answer stage (+ --retrieval-only)
│   ├── metrics.py           ← pytrec_eval wrapper + deterministic asserts
│   └── schemas.py           ← dataclasses / JSON-schema validation for all artifacts
├── judge/
│   ├── rubric.md            ← versioned grading rubric (binary criteria)
│   └── judge.py             ← offline judge pass (Claude API, pinned model)
├── configs/
│   ├── baseline.json        ← production-equivalent settings
│   └── ablations/           ← one file per single-axis variation
├── datasets/
│   └── <dataset>/
│       ├── manifest.json    ← file list (paths relative to corpus root), hashes
│       ├── golden.json      ← golden QA set (schema §4.1)
│       └── qrels.tsv        ← derived from golden.json for pytrec_eval
├── runs/                    ← one folder per run (raw outputs gitignored,
│   └── <run_id>/               summary + metrics committed)
└── README.md                ← how to run (written in Phase 1)
```

**Runner CLI (shape):**

```bash
uv run python -m eval_harness.harness.run \
    --dataset receipts --config configs/baseline.json \
    [--index-only | --retrieval-only | --skip-index]   # --skip-index = use cached index
```

**Isolation mechanics:** the backend must accept a data-directory override
(`MAGPIE_DATA_DIR` env var or equivalent — Phase 0 confirms whether this exists or adds
it). Each run gets `runs/<run_id>/appdata/` as its data dir; the sidecar/pipeline is
spawned fresh, port-isolated, and torn down at the end. Backend logs and the LLM JSONL
log are captured into the run folder (including raw bodies of any 4xx/5xx — the
llama-server 400s must be visible this time).

**Cache-sharing contract (verified against src/manifest.py, 2026-08-28):**
`src/manifest.py:97-100` derives the HF model cache from `APP_DATA_DIR`, so a naive
data-dir override would point the cache at an empty folder and re-download ~10 GB of
weights per run. The env vars are set with `os.environ.setdefault`, which is the escape
hatch: the harness MUST export `HF_HOME`, `HF_HUB_CACHE`, `TRANSFORMERS_CACHE`, **and**
`FASTEMBED_CACHE_PATH` (fastembed ignores `HF_HOME` entirely — see
`src/manifest.py:102-114`) pointing at the real shared cache **before any `src.*`
import / backend spawn**. Weights are protected from mutation with `HF_HUB_OFFLINE=1`
(a literal read-only mount breaks the hub's lockfile writes on cache hits), which also
guarantees runs never silently download anything.

**Controlled environment (no ambient `.env`):** `src/manifest.py:53` loads `.env` before
paths resolve, and `LLM_PROVIDER`, `OPENROUTER_MODEL`, `LOCAL_TEMPERATURE`, `LOCAL_N_CTX`
etc. are ambient env reads — precisely the axes being swept. The runner therefore
constructs the backend's environment explicitly from the run config (every
parameter-relevant var set; the repo `.env` never inherited) and writes the fully
resolved environment + the scratch `settings.json` it generated into the run record, so
two "baseline" runs on two machines are comparable by construction.

**Offline stages (Claude-side, via subagent fan-out, never inside the runner):**
golden-set generation, judge pass, run comparison reports. Wrapped later as a repo skill
(`.claude/skills/magpie-eval/`) so any session runs them identically (Phase 6).

---

## 4. Data formats

### 4.1 Golden QA item (`datasets/<ds>/golden.json`)

```jsonc
{
  "id": "receipts-007",
  "question": "What was the total on the March Costco receipt?",
  "question_variants": ["costco march total"],          // vague/realistic phrasings
  "answer_type": "extractive | synthesis | enumeration | not_found",
  "gold_answer": "…",
  "key_facts": ["total was $214.60", "dated March 14"], // atomic, binary-checkable
  "gold_sources": ["receipts/costco-2026-03.pdf"],      // must be retrieved AND cited
  "acceptable_sources": [],                             // also contain the answer
  "requires": { "visual_tier": true, "multi_file": false },
  "difficulty": "easy | medium | hard",
  "human_verified": false,                              // silver until a human reviews
  "generator": "claude-<model>/2026-08-28 | dataset-conversion | hand-written"
}
```

Composition targets per dataset (~40–60 items): mix of single-doc / multi-doc synthesis /
enumeration, **10–15% `not_found`** (abstention slice), several visual-only items
(charts, scans — ColQwen's differentiator), at least a few `.docx` (known router bug),
and a vague `question_variants` phrasing for most items. Generation is **blind**
(questions written from extracted fact lists, not from page text) so questions cannot
lexically copy the document and make retrieval trivially easy (ViDoRe v2's fix).
Distractor files — topically similar files that do NOT contain answers — are planted in
every corpus.

`qrels.tsv` (`question-id  file-id  relevance`) is generated mechanically from
`gold_sources`/`acceptable_sources` so pytrec_eval can compute all retrieval metrics.

### 4.2 Run config (`configs/*.json`, snapshotted into the run folder)

```jsonc
{
  "config_name": "baseline",
  "dataset": "receipts",
  "params": {
    "col_model": "…", "summary_model": "…",
    "gen_model": "…", "provider": "local",
    "prompt_style": "baseline", "grammar": true,
    "rewrite": true, "top_k_max": 12,
    "temperature": 0.0,                 // evals run at 0 — variance kills comparisons
    "memory": null
  }
}
```

The runner stamps in: `run_id`, backend git SHA, harness git SHA, machine info,
start/end timestamps, the resolved index-cache key it used, and the **fully resolved
environment** it constructed for the backend (see §3 controlled environment) — ambient
`.env` values must never be able to change a run without appearing in the record.

### 4.3 Index report (`runs/<id>/index_report.json`, one entry per file)

```jsonc
{
  "path": "receipts/costco-2026-03.pdf", "content_hash": "…",
  "tier": "visual | fast", "duration_s": 84.2,
  "status": "ok | error", "error": null,
  "summary_path": "…", "tokens_used": 1450
}
```

Judge pass later appends per file: binary checklist results (each key fact from
questions sourced to this file: derivable from the summary alone? yes/no →
"answerable-from-summary %"), faithfulness flags, free-text bug notes.

### 4.4 Answer report (`runs/<id>/answers.json`, one entry per question × variant)

```jsonc
{
  "qa_id": "receipts-007", "variant": 0,
  "rewritten_query": "…",
  "retrieved": [{"path": "…", "score": 0.031, "rank": 1}, …],   // full list at k_max
  "answer": "…", "cited": ["…"],
  "latency_s": {"rewrite": 1.8, "retrieval": 0.2, "generation": 24.1, "total": 26.1},
  "tokens": {"prompt": 9800, "completion": 210},
  "error": null                                   // raw body on HTTP errors
}
```

Judge pass appends: per-key-fact yes/no, verdict
(`correct | partial | wrong | correct_abstain | false_abstain`), citation
precision/recall, hallucinated-citation flag, one-sentence reason, judge model + rubric
version, and the composite score.

---

## 5. Metrics

**Retrieval** (deterministic, via pytrec_eval over qrels): **nDCG@5** (ViDoRe
convention for these exact models), **Recall@k** for k ∈ {1,3,5,12}, **MRR**. Computed
per question and aggregated; also split by `answer_type` and `requires.visual_tier`.

**Answer:** exact/fuzzy match where `key_facts` are short and deterministic; otherwise
reference-guided binary LLM judge per key fact. Headline per-answer **composite score**
(OpenJarvis DocQA weights, adopted as-is until we have reason to change):
`0.5 × key_facts_matched + 0.3 × citations_correct + 0.2 × judge_checklist`.

**Citation** (ALCE-style at file granularity, deterministic): citation precision
(every cited file ∈ gold/acceptable sources) and citation recall (every gold source that
was needed is cited).

**Abstention:** false-answer rate on `not_found` questions + false-refusal rate on
answerable ones. (Literature baseline: top LLMs correctly refuse <50% — expect this
slice to be ugly and informative.)

**Ops:** latency p50/p95 per stage, index throughput (files/min, per tier), hard-failure
rate (HTTP errors, crashes). Timing on a laptop is indicative only — never pick a winner
on a <10–15% latency delta, and never A/B timing across different thermal sessions.

**Diagnostic reading order when a config scores badly:** was the gold file in top-k?
(no → retrieval problem) → was it cited? (no → prompt/generation problem) → were the
facts right? (no → generation/grounding problem). Every answer row carries all three.

---

## 6. Datasets

| Dataset | Source | Golden QA | Prep |
|---|---|---|---|
| `receipts` | **SROIE** (ICDAR 2019, CC-BY-4.0 mirror) — ~150–300 of 987 scanned receipts | Converted mechanically from labeled fields (total, date, vendor, address) → exact-match QA; plus a handful of hand-written cross-receipt aggregation questions | ~1 hr scripting |
| `personal_notes` | User's syllabi / class notes / books (stays **out of the repo**, path in a local untracked config; judge pass on it requires explicit OK since content goes to the cloud judge) | Claude-generated via subagent fan-out: agent A extracts fact list per file → agent B writes questions from facts only (blind) → both founders review every item (silver→gold; expect to cut/fix 20–30%) | half a day incl. review |
| `furman_directory` | Furman CSV corpus (already on disk) | Fresh golden set generated under §4.1 schema (structured-data QA: filters, aggregation, multi-hop) | ~2 hrs |
| `mmlongbench` (optional yardstick) | MMLongBench-Doc: 135 real PDFs, 1,091 QA with evidence pages + 22.5% unanswerable, CC-BY-NC-4.0 | Ships with ground truth — adapter converts to §4.1 | ~2 hrs adapter |

Three corpus types (scanned images / structured CSV / mixed personal docs) is the
overfitting hedge: a parameter change must win on at least two to be believed.

---

## 7. Phases

### Phase 0 — Prerequisites & decisions *(small, unblocks everything)*
- Audit how the backend resolves its data dir; add/confirm an env-var override so a run
  can point all state (index, DB, logs, settings) at a scratch folder. **This is the
  only production-code change the harness needs.**
- Implement the cache-sharing contract from §3: export `HF_HOME` / `HF_HUB_CACHE` /
  `TRANSFORMERS_CACHE` / `FASTEMBED_CACHE_PATH` to the shared cache before backend
  import, plus `HF_HUB_OFFLINE=1`; verify with a run that downloads zero bytes.
- Implement controlled-env construction + resolved-env snapshotting (§3/§4.2); confirm
  the isolation test passes with a deliberately conflicting repo `.env` present.
- Confirm the `furman_directory` and personal-notes corpus paths still exist on this
  machine (corpora live outside the repo by design; `manifest.json` records the
  expected root via a local untracked path config).
- Confirm exact model IDs for both axes (gen: LFM2.5-VL-3B / Gemma; col: ColSmol /
  ColQwen2.5) and that both are installable into the shared cache.
- Pin the judge model (a Claude model ID) and create `judge/rubric.md` v1.
- Decide git policy for `runs/` (proposal: commit config + metrics + reports, gitignore
  raw appdata/logs).
- **Exit:** a script boots the backend against a scratch data dir, answers one hardcoded
  question, and tears down — with `~/Library/Application Support/Magpie` untouched
  (verified by mtime/hash check).

### Phase 1 — v0 end-to-end, one dataset, baseline config
- Build `harness/` runner: config in → spawn isolated backend → index stage (with
  index report) → answer stage → metrics → `runs/<run_id>/` out. Resume-safe
  (per-question flush), temperature 0.
- Dataset: `receipts` first (small files, fast indexing, deterministic answers).
- Deterministic metrics only in this phase (exact-match facts, citation asserts,
  retrieval hit@k) — no judge yet.
- **Exit:** two consecutive baseline runs produce identical retrieval metrics and
  ≥95%-identical answer verdicts; a written list of every bug the first runs surfaced
  (this phase is a bug-finding machine — expect it to pay for itself immediately).

### Phase 2 — Retrieval eval done properly
- qrels generation from golden sets; pytrec_eval integration (nDCG@5, Recall@k, MRR).
- `--retrieval-only` mode (rewrite + retrieval, no generation): full retrieval sweep on
  a dataset in ~1 minute.
- Top-k-by-truncation scoring; rewrite on/off comparison as the first real experiment.
- **Exit:** a one-command retrieval comparison table (col_model × rewrite × k) for the
  receipts dataset.

### Phase 3 — Judge pass & golden v2
- `judge/judge.py`: offline, reads a finished run folder, binary per-fact verdicts,
  reference-guided, composite score, appends to reports; judge + rubric version stamped.
- Abstention metrics wired (needs `not_found` items in golden sets).
- **Calibration:** both founders independently pass/fail the same 30–50 judged answers;
  measure judge agreement (target ≥90%); iterate rubric until hit. Keep the labeled set
  as the permanent judge-regression fixture.
- **Exit:** full metric suite (retrieval + answer + citation + abstention + composite)
  produced for one baseline run, with a calibrated judge.

### Phase 4 — Caching & sweeps
- Index cache keyed by (dataset, col_model, summary-config hash, backend SHA of
  index-relevant code); `--skip-index` mounts a cached index into a run.
- `configs/ablations/` populated (one axis at a time from baseline); a sweep driver that
  queues runs sequentially (laptop = one run at a time).
- Cross-run comparison report: one table, rows = configs, columns = headline metrics,
  generated from `runs/` summaries.
- **Exit:** the full ablation set for the receipts dataset completed and compared in one
  afternoon of wall-clock.

### Phase 5 — Dataset expansion
- `personal_notes`: subagent fan-out golden generation (blind two-stage), founder
  review, freeze v1.
- `furman_directory`: fresh golden set under the v2 schema.
- Optional: `mmlongbench` adapter as the external yardstick.
- Rerun baseline + winning ablations on all datasets; first "does it generalize"
  read-out.
- **Exit:** every parameter conclusion checked against ≥2 corpus types.

### Phase 6 — Skill, CI hook & error analysis
- `.claude/skills/magpie-eval/`: procedures for generate-golden / launch-run / judge /
  compare, so any future session (or Rahul's) runs identically.
- Smoke eval: ~10-question deterministic-only subset that runs in minutes, suitable for
  pre-release checks; wire into `justfile`.
- Error-analysis loop: after each judged run, cluster failures into a taxonomy
  (retrieval-miss / wrong-citation / hallucination / false-abstain / …), file the top
  recurring cluster as a GitHub issue. The taxonomy, not the metrics, drives what we fix
  next.
- **Exit:** a new contributor can run the whole flow from README + skill without asking
  us anything.

---

## 8. Rough cost model (laptop, local models)

| Operation | Rough cost |
|---|---|
| Index build (50-file dataset, visual tier) | 1–2 h, cached forever after |
| Full answer run (40–60 q, local 3B, temp 0) | 30–60 min |
| `--retrieval-only` run | ~1–2 min |
| Judge pass (cloud, per run) | minutes + small API cost |
| Full ablation set, one dataset (post-caching) | ~1 afternoon |
| Everything, all datasets | a weekend of background compute |

Versus the naive full factorial (~430 monolithic runs × hours each): ~2% of the compute
for the same decisions.

---

## 9. Open questions for review

1. **Judge model:** pin which Claude model? (Different family than LFM/Gemma either way,
   so bias hygiene is satisfied.)
2. **Cloud provider axis:** include moonshot/openrouter in the sweep from Phase 1, or
   local-only until Phase 4?
3. **`runs/` git policy:** commit summaries+metrics only (proposed) — agree?
4. **Personal-notes privacy:** OK sending that corpus's answers/snippets to the cloud
   judge, or should that dataset get deterministic-only grading?
5. **SROIE subset size:** 150 receipts (fast iteration) vs 300+ (tighter numbers)?
6. **MMLongBench-Doc:** worth the adapter in Phase 5, or park it?

---

## 10. References

- OpenJarvis (Stanford, 2026) — runner + DocQA scorer pattern: github.com/open-jarvis/OpenJarvis
  (existence re-verified via GitHub API 2026-08-28: 9,093 stars, Apache-2.0, pushed
  2026-08-27 — the project postdates most models' training data, so offline reviewers
  cannot see it)
- ViDoRe v1/v2/v3 + vidore-benchmark (ColQwen's own eval): github.com/illuin-tech/vidore-benchmark
- BEIR corpus/queries/qrels format: github.com/beir-cellar/beir · pytrec_eval
- MMLongBench-Doc: github.com/mayubo2333/MMLongBench-Doc
- SROIE receipts: huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE
- ALCE citation precision/recall: github.com/princeton-nlp/ALCE
- LLM-as-judge biases: "Judging LLM-as-a-Judge with MT-Bench" (arXiv:2306.05685)
- Practitioner doctrine (binary verdicts, judge calibration, error analysis):
  hamel.dev/blog/posts/evals/ · hamel.dev/blog/posts/evals-faq/ · Anthropic eval docs
