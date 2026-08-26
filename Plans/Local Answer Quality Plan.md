# Local Answer Quality — unplayed cards

Status: PLANNED, not started. Every item here ships only with a before/
after eval run against `Evaluations/college_data/` (same question files,
only the change under test varies). Baseline as of 2026-08-24: local
13% strict / 27% partial+, cloud 47% / 60% (see
`Evaluations/college_data/REPORT.md` for all measured runs).

## The cards, ranked

| # | Card | What it does | Expected lift | Effort | Risk |
|---|------|--------------|---------------|--------|------|
| 1 | Grounding check (local) | After answering, a second cheap call: "quote the sentence supporting this." No quote → downgrade to honest not-found | Kills the confident-fabrication cluster (7/15 at baseline) → +2-3 right-ish, and wrong answers become honest refusals | ~half day | Adds one LLM call to local answers (~5-15s on GPU) |
| 2 | 8B model trial | Swap LFM2.5-3B for an 8B at Q4 quant (~4.5 GB; fits the 6 GB RTX 3060) via LOCAL_MODEL env + `_REPO_PATTERNS` registration | Biggest untested lever; 3B→8B is typically the largest reading-accuracy jump available | 1 config change + overnight eval | ~2x answer latency; VRAM headroom untested with 32K KV |
| 3 | Synthesis prompt structure | Cross-doc/comparative questions get explicit "answer in labeled parts, one per file" scaffolding | All 4 cross-doc questions failed on BOTH providers; cloud's 4 wrongful refusals are the same cluster | ~2h, shared with cloud fix | Prompt changes can shift other verdicts — full eval rerun required |
| 4 | doc2query, productized | Question-space index points generated at index time | Partial+ 27→47% measured (spike v1) | Real pipeline work (Mridul) | ADOPTION CONDITIONS BELOW — two spike failures documented |
| 5 | Query router | Easy single-doc → local; synthesis/comparative → cloud (user-permitting) | Product-level: eval showed ZERO overlap in the two providers' failure modes; combined ceiling ~80% partial+ | Design needed | Privacy UX: must be explicit that routed questions go to cloud |
| 6 | Rewrite-as-retry | If local raw answer comes back not-found, one retry with rewrite | Marginal (+1?) — local's not-found rate is ~7% | ~1h | 3B rewriter demonstrably invents intent; last-resort only |
| 7 | Mechanical reduce for enumerations | Map-reduce spike (2026-08-26, routed v1+v2, both 14/40 — CLOSED) proved the maps extract good facts and the 3B REDUCE is the bottleneck (dilution, out-of-scope leaks, worse with more findings). Replace the LLM reduce with CODE: drop NOT_HERE, scope-filter by source file, dedup/merge bullets; LLM only phrases the final list | The 8 breadth questions are all baseline-wrong; near-misses (q40 2/4 dates, q14 forms found but dropped) suggest +2-4 within reach | ~half day | Scope-filter heuristics are corpus-sensitive; needs its own gated run |

## doc2query adoption conditions (from spikes v1 + v2)

- v1 (no filter): partial+ 27→47% BUT recall@k 87→73% — generic
  questions from crash-course files crowded out the Cornell essay (q01).
- v2 (per-file entity filter): FAILED — rejected almost nothing,
  recall fell to 67%. The collision is cross-file.
- Required design: GLOBAL near-duplicate detection — embed every
  generated question, drop/down-weight any question within ~0.9
  similarity of another FILE's question (keep-best-owner rule), and
  down-weight question points in RRF so summary points stay dominant.
- Gate for adoption: partial+ ≥ 40% AND recall@k ≥ 87% on the standard
  15-question set.

## Methodology debts (write probes BEFORE running)

1. **Mangled-entity typos** — the 2026-08-24 typo probes kept key
   entities intact ("cornell", "SAT"), the favorable case for raw
   search. Add 3-5 probes with the ENTITY misspelled ("cornal essya",
   "SATT scoer"). If raw loses these and rewrite wins them, the
   local-raw-only policy needs a retry exception. Author the probes and
   the pass/fail rule before running.
2. Visual tier phase 2 — photo questions + text-regression check with
   `--fast` on (queued since the baseline; unmeasured).
3. n is small everywhere (15/5/3). Treat <3-question deltas as noise;
   for ship/no-ship calls on close results, run n=3 repeats and compare
   medians.
4. Self-evaluation caveat: the same assistant authors ground truths and
   judges answers. For the beta go/no-go eval, have Mridul spot-check
   10 verdicts blind.
