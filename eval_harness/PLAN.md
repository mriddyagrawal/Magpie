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
zero design influence. Every hypothesis carries a pre-stated minimum effect size — a
result below it is "no effect" regardless of direction (§5's latency discipline,
extended to accuracy). Current docket (add/remove freely):

- **H1 — model sufficiency:** where the question's key facts are *observed present in
  the assembled prompt* (§4.4 `key_fact_spans` all true — fact-level, because head
  truncation can keep a file while cutting the asked-about span; never inferred from
  rank: budget trimming keeps best-ranked-first, so "survived the budget" is a
  rank-biased subset), LFM2.5 answers ≥85% of extractive questions correctly; expected
  to break down on aggregation/enumeration and abstention. **Basis caveat (2026-08-28,
  finding #50):** on image corpora fact-spans are unobservable and eligibility degrades
  to file-level ("the right image was in the prompt") — a DIFFERENT claim, since fact
  legibility is part of what's being measured. H1 numbers are reported per basis and
  never pooled across bases; `receipts` is 100% file-level basis. Reported **per arm** as
  accuracy × its own eligible fraction (`n_eligible / n_extractive`) — raw percentages
  are never compared across arms, because the denominators differ structurally (cloud
  has no budget and no gate, so its eligible set is everyone's). The
  retrieved-but-excluded rate (trimmed / gated / fact-cut) is reported alongside as its
  own scaffolding-fault class.
- **H2 — rewrite:** rewrite improves recall@5 on vague `question_variants` by ≥10
  points while moving keyword-style recall@5 by <5 points.
- **H3 — context width:** extractive key-fact accuracy at `top_k_context=12` is ≥10
  points below `top_k_context=3` even while retrieval recall rises. Answer-side: tested
  as a {3, 12} bracket costing two full runs, not by truncation (§2). Both bracket runs
  set `LOCAL_SOLO_MARGIN=0` — with the gate on, ~24% of questions ignore k entirely.
  Prior evidence this is real (`src/stage2/search.py:840`, 2026-08-24, 121-trace
  replay + reading-isolation ladder): the 3B is near-perfect from a single correct
  file and drops to ~13% with 4 distractors — the bracket measures magnitude, not
  existence. Expected band, so the number can actually surprise: <10 points = no
  effect, H3 refuted; 10–30 = real but materially weaker than the ladder predicted
  (find out why); >40 = consistent with prior.
- **H5 — solo-gate recovery (the question the shipped gate is betting on):** with
  distractors present, gate ON (margin 2.0) recovers ≥20 points of extractive accuracy
  vs. gate OFF at the same k — at a cost of ≤10 points of enumeration coverage (the
  gate's own docstring predicts the cost: "loses enumeration coverage if starved").
  Local arms only, by construction. **BLOCKED on `receipts` (2026-08-28, finding
  #1/#59):** rerank scores every visual-tier hit against the constant placeholder
  "(visual match — page N)" (`src/stage2/rerank.py:92`, `search.py:523`), so the
  gate's margin is structurally 0 on image corpora and it can never fire there at ANY
  `LOCAL_SOLO_MARGIN`. Test H5 on a text corpus, or after the rerank placeholder bug
  is fixed. (Baseline evidence: fire rate 0/53, all margins exactly 0.0.)
- **H4 — grammar:** enforcement costs ≥5 points of key-fact accuracy vs. enforcement
  off; anything smaller = no effect, keep enforcement for parse reliability.

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
   k_max and score all smaller top-k by truncation — **retrieval metrics only**;
   answer-side context-width effects change the prompt itself, need their own generation
   runs, and are bracketed instead (§2). Sweep retrieval-side parameters with
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
| `model_config` | 3 named configs (decided 2026-08-28): `lfm-local` (LFM2.5-VL-3B, grammar ON) · `gemma26b-local` (Gemma 4 26B-A4B, grammar ON) · `gemma26b-openrouter` (same model via API, grammar OFF — a codebase choice, not an API limit; see confound table below) | answer | full run per value. ⚠ `gemma26b-openrouter` is a **capability probe** ("can a 26B do it at all?"), not a comparison arm — see the six-factor confound table below the parameter table |
| `prompt_style` | `baseline` (current sandwich), `compact`, (room for more) | answer | full answer run per value |
| `grammar` | enforced vs off — H4 ablation, run on a LOCAL model config only (the `model_config` values above otherwise pin their own grammar setting) | answer | full answer run per value |
| `solo_gate` (`LOCAL_SOLO_MARGIN`) | 2.0 (prod default) vs 0 (off). Local-only: when the top rerank score dominates #2 by the margin, the generator gets that file ALONE — fires on ~24% of questions (measured, see `src/stage2/search.py:840`) | answer | full run per value. Contaminates any axis assuming k controls context width — H3 runs with it OFF; `solo_gated` is recorded per question in every run regardless |
| `rewrite` | on vs off | retrieval | scored via `--retrieval-only` (cheap) |
| `top_k_retrieval` | scored at 1, 3, 5, 12 | retrieval | **free for retrieval metrics** — retrieve once at k=12, truncate the ranked list |
| `top_k_context` | blocks fed to the generator: bracket {3, 12}, widen only if the bracket shows an effect | answer | **not free** — one full answer run per value (this is H3's axis) |
| `memory` | `null` (reserved; not built) | — | placeholder field only |

**The local-vs-openrouter confound, in full.** `gemma26b-openrouter` differs from
`gemma26b-local` in **six** ways, so no delta between them is attributable to any single
factor. Conclusions about parameters come from the two local arms; the openrouter arm
answers only "can a bigger model do this at all?":

1. provider (the intended axis)
2. grammar — local compiles GBNF; cloud runs with **no** `response_format` **by
   codebase choice** (`src/answer.py:330-332`: Google AI Studio rejects both variants —
   OpenRouter itself supports `response_format` on this model, so this is revisitable)
3. `gate_to_solo` never fires on cloud (`src/stage2/search.py:863-866`)
4. no context-budget trimming on cloud (`_context_budget_chars() → None`,
   `src/answer.py:62-68`)
5. context window differs ~4× (local `LOCAL_N_CTX` vs OpenRouter's 262,144)
6. cloud gets `_FORMAT_BLOCK_CLOUD` appended to the prompt (`src/answer.py:336-345`,
   applied at :746-748) — i.e. choosing this arm silently changes `prompt_style`

Baseline config = current production settings. Sweeps are ablations from baseline
(one axis at a time): per dataset that is ~9 answer runs — the `top_k_context` bracket
{3, 12} adds two, and baseline's production k=5 supplies a free third point, making the
bracket a 3-point curve — instead of ~144. Known blind spot, accepted for the compute
budget: ablations explore the *neighborhood* of the shipped config; a config that only
wins via two simultaneous changes is invisible until a targeted grid is run. That is a
scoping choice, not neutrality.

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
│   ├── metrics.py           ← pure-Python IR metrics (fixture-tested) + deterministic asserts
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

**Two drive modes, because the harness never modifies production code** (we are
measuring current-main; changing it would measure something else): **pipeline mode**
calls `pipeline.ask()` verbatim — used for baseline and all runs it can express;
**composed mode** calls the same `run_search` → `gate_to_solo` → `answer_question`
sequence `ask()` itself uses (mirroring `src/pipeline.py`), needed only where `ask()`
has no knob (`top_k_context`), with a fidelity test asserting composed(k=5, gate on)
reproduces pipeline-mode behavior. **Prompt-composition observability** (`in_prompt`,
`key_fact_spans`) is read back from the backend's own LLM JSONL request log — the
assembled messages are string-matched after the fact: observed, never inferred, zero
production changes.

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

**Controlled environment (no ambient `.env`):** `src/manifest.py:63` calls
`load_dotenv()` before paths resolve, and `LLM_PROVIDER`, `OPENROUTER_MODEL`, `LOCAL_TEMPERATURE`,
`LOCAL_N_CTX`, `LOCAL_SOLO_MARGIN`, `LOCAL_PREFILL_BUDGET_TOKENS`, `LLAMA_SERVER_GPU`
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
every corpus. **v1 answer runs execute the primary phrasing only** (`variant: 0`);
`question_variants` power a separate ~10-question robustness mini-experiment rather than
multiplying every run by the variant count (which would cut directly against §3's cost
discipline).

`qrels.tsv` (`question-id  file-id  relevance`) is generated mechanically from
`gold_sources`/`acceptable_sources` so pytrec_eval can compute all retrieval metrics.

### 4.2 Run config (`configs/*.json`, snapshotted into the run folder)

```jsonc
{
  "config_name": "baseline",
  "dataset": "receipts",
  "params": {
    "col_model": "…", "summary_model": "…",
    "model_config": "lfm-local",        // lfm-local | gemma26b-local | gemma26b-openrouter
    "prompt_style": "baseline",
    "grammar": true,                    // resolved from model_config unless an H4 ablation overrides it
    "solo_margin": 2.0,                 // LOCAL_SOLO_MARGIN; local-only; 0 disables
    "rewrite": true,
    "top_k_retrieval_max": 12,
    "top_k_context": 5,                 // blocks fed to generator; confirm prod default in Phase 0
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
  "solo_gated": false,                              // did gate_to_solo fire on this question
  "retrieved": [{"path": "…", "score": 0.031, "rank": 1}, …],
  "in_prompt": {"<basename>":
      "full | truncated | dropped | solo_excluded | absent | unknown_log_truncated"},
  // observed from the backend's own prompt markers (the '--- File N: … ---'
  // headers, the '…(truncated to fit…)' marker inside a file's block, and the
  // omitted-files context note) — never inferred from rank/budget arithmetic.
  // unknown_log_truncated = the LLM log's 50KB per-string cap cut the middle
  // of the request, so presence is undecidable (three-valued honesty).
  "key_fact_spans": {"0": true, "1": false},
  // each key fact string-matched (normalized) against the assembled prompt read from
  // the LLM request log. File-level presence is NOT enough: head truncation
  // (src/answer.py:124-128) keeps a file's beginning and cuts its tail — on a receipt
  // the total is at the BOTTOM, so "in_prompt: truncated" can mean the asked-about
  // fact is gone. H1 conditions on the FACT being present, not the file.
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

**Retrieval** (deterministic, over qrels): **nDCG@5** (ViDoRe convention for these
exact models), **Recall@k** for k ∈ {1,3,5,12}, **MRR**. Implemented as pure-Python
functions in `harness/metrics.py`, unit-tested against hand-computed fixtures — no
`pytrec_eval` dependency (C extension; would bite Windows setup and add an app-adjacent
dep for ~40 lines of math). The qrels TSV stays pytrec_eval-compatible so anyone can
cross-check externally. Computed per question and aggregated; also split by
`answer_type` and `requires.visual_tier`.

**Answer:** exact/fuzzy match where `key_facts` are short and deterministic; otherwise
reference-guided binary LLM judge per key fact. Headline per-answer **composite score**
(OpenJarvis DocQA weights, adopted as-is until we have reason to change):
`0.5 × key_facts_matched + 0.3 × citations_correct + 0.2 × judge_checklist`. The three
components are always reported separately; the composite is a **sort key for triage**,
never a headline claim — a blended float is exactly the Likert-shaped thing §1.5 bans,
so it exists to order failures for reading, not to compare configs.

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
(no → retrieval problem) → did its content actually reach the prompt, or was it trimmed
by the context budget / excluded by the solo gate? (no → **scaffolding: budget/gating
fault, not the model's**) → was it cited? (no → prompt/generation problem) → were the
facts right? (no → generation/grounding problem). Every answer row carries all four —
`in_prompt` and `solo_gated` are observed and recorded, never inferred.

---

## 6. Datasets

| Dataset | Source | Golden QA | Prep |
|---|---|---|---|
| `receipts` | **SROIE** (ICDAR 2019, CC-BY-4.0 mirror) — 150 of 987 scanned receipts (decided 2026-08-28) | Converted mechanically from labeled fields (total, date, vendor, address) → exact-match QA; plus a handful of hand-written cross-receipt aggregation questions | ~1 hr scripting |
| `personal_notes` | User's syllabi / class notes / books (stays **out of the repo**, path in a local untracked config; judge pass on it requires explicit OK since content goes to the cloud judge) | Claude-generated via subagent fan-out: agent A extracts fact list per file → agent B writes questions from facts only (blind) → both founders review every item (silver→gold; expect to cut/fix 20–30%) | half a day incl. review |
| `furman_directory` | Furman CSV corpus (already on disk) | Fresh golden set generated under §4.1 schema (structured-data QA: filters, aggregation, multi-hop) | ~2 hrs |
| `mmlongbench` (optional yardstick) | MMLongBench-Doc: 135 real PDFs, 1,091 QA with evidence pages + 22.5% unanswerable, CC-BY-NC-4.0 | Ships with ground truth — adapter converts to §4.1 | ~2 hrs adapter |

Three corpus types (scanned images / structured CSV / mixed personal docs) is the
overfitting hedge: a parameter change must win on at least two to be believed.

---

## 7. Phases

### Phase 0 — Prerequisites & decisions *(small, unblocks everything)*
- **Verified: `MAGPIE_DATA_DIR` already exists** (`src/manifest.py:74`) — isolation
  requires **zero production-code changes**; all Phase 0 work is harness-side contract
  (env construction, cache exports, boot/teardown). `top_k_context` likewise needs no
  production change: the runner's composed mode (§3) supplies it.
- Implement the cache-sharing contract from §3: export `HF_HOME` / `HF_HUB_CACHE` /
  `TRANSFORMERS_CACHE` / `FASTEMBED_CACHE_PATH` to the shared cache before backend
  import, plus `HF_HUB_OFFLINE=1`; verify with a run that downloads zero bytes.
- Implement controlled-env construction + resolved-env snapshotting (§3/§4.2); confirm
  the isolation test passes with a deliberately conflicting repo `.env` present.
- Confirm the `furman_directory` and personal-notes corpus paths still exist on this
  machine (corpora live outside the repo by design; `manifest.json` records the
  expected root via a local untracked path config).
- Confirm exact model IDs for the three `model_config` values (LFM2.5-VL-3B GGUF; the
  Gemma 4 26B-A4B GGUF **and whether this machine can actually serve it locally** —
  MoE with ~4B active params should fit, verify; OpenRouter slug
  `google/gemma-4-26b-a4b-it:free` per `.env.example`) and both col models, all
  installable into the shared cache.
- Set the judge (a high-tier Claude: Opus 5 or Fable 5) and create `judge/rubric.md` v1.
  Pinning discipline: judge model ID + rubric version stamped on every verdict; never
  mix judge versions within one comparison; judge upgrades are allowed only after
  re-running the human-labeled calibration fixture + one anchor run with the new judge
  and confirming agreement.
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
- **Exit:** two consecutive baseline runs agree **within stated tolerance** — bit-identical
  is not the bar, because Qdrant fuses dense+BM25 via RRF and tie-breaks aren't
  guaranteed stable across runs: per-question hit@k identical on ≥95% of questions,
  MRR within ±0.02, deterministic answer verdicts stable on ≥95% at temp 0. Plus a
  written list of every bug the first runs surfaced (this phase is a bug-finding
  machine — expect it to pay for itself immediately).

### Phase 2 — Retrieval eval done properly
- qrels generation from golden sets; pure-Python nDCG@5 / Recall@k / MRR with
  hand-computed fixture tests (qrels kept pytrec_eval-compatible for external
  cross-checks).
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
  as the permanent judge-regression fixture. The fixture deliberately includes several
  **correct answers phrased unlike the Claude-authored gold** — the judge and the
  golden-set author are both Claude, and this is the cheap test that the judge isn't
  rewarding its own phrasing (self-preference channel).
- **Exit:** full metric suite (retrieval + answer + citation + abstention + composite)
  produced for one baseline run, with a calibrated judge.

### Phase 4 — Caching & sweeps
- Index cache keyed by (dataset, col_model, summary-config hash, backend SHA of
  index-relevant code); `--skip-index` mounts a cached index into a run.
- `configs/ablations/` populated (one axis at a time from baseline); a sweep driver that
  queues runs sequentially (laptop = one run at a time).
- Cross-run comparison report: one table, rows = configs, columns = headline metrics,
  generated from `runs/` summaries.
- **Exit:** the full ablation set for the receipts dataset (≈8 runs incl. the
  top_k_context bracket) completed and compared within a day of wall-clock.

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
| Full ablation set, one dataset (post-caching) | ≈9 answer runs, 5–9 h wall-clock |
| Everything, all datasets | a weekend of background compute |
| **Golden-set review — both founders, per dataset** | **2–4 h of human time** |
| **Judge-calibration labeling — both founders, once** | **2–3 h of human time** |

The two human rows are the critical path, not GPU time — machine hours run overnight;
founder hours don't.

Versus the naive full factorial (~430 monolithic runs × hours each): ~2% of the compute
for the same decisions.

---

## 9. Decisions (resolved with the owner, 2026-08-28)

1. **Judge model:** a high-tier Claude (Opus 5 / Fable 5). Pinning is about
   comparability, not capability: judge ID + rubric version on every verdict, never mix
   judge versions within a comparison, upgrades only after recalibrating on the
   human-labeled fixture + one anchor run. If the pinned snapshot is retired
   mid-project, treat retirement as a forced upgrade: same recalibration gate before
   any new verdicts count. (Different family than LFM/Gemma, so bias hygiene is
   satisfied; the Claude-judges-Claude-goldens channel is tested by the calibration
   fixture's unlike-gold items, §7 Phase 3.)
2. **Model axis:** exactly three `model_config` values — `lfm-local` (grammar on),
   `gemma26b-local` (grammar on), `gemma26b-openrouter` (grammar off; free API forbids
   enforcement). The openrouter config's provider+grammar confound is accepted and
   documented in §2; H4 tests grammar cleanly on a local config.
3. **`runs/` git policy:** commit config + metrics + reports; gitignore raw
   appdata/logs.
4. **Personal-notes privacy:** approved — that corpus's content may go to the cloud
   judge. Scope of what leaves the machine, in writing: the question, gold answer +
   key facts, the generated answer, cited/retrieved file *names*, and — only when a
   verdict requires it — the specific retrieved snippet under dispute. Never whole
   documents.
5. **SROIE subset:** 150 receipts.
6. **MMLongBench-Doc adapter:** deferred — re-ask the owner at Phase 5 kickoff.

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
- **Internal prior work** (closest thing to prior art, and it's ours): the 2026-08-24
  reading-isolation ladder + 121-trace retrieval replay recorded in the `gate_to_solo`
  docstring (`src/stage2/search.py:840`) — single-clean-file ≈ near-perfect, 4
  distractors ≈ 13%, margin≥2 → top-1 correct 93%, fires ~24%.
