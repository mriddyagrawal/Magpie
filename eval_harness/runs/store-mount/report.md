# Eval report — store-mount

> ⚠️ **SILVER (provisional) golden set** — 0/106 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `baseline` · dataset `receipts` · 106 questions · backend `e8ab5ccf6f7b`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | None |
| Partial | None |
| Wrong | None |
| False abstain | None |
| Correct abstain (of 0 not_found) | None |
| False answer on not_found | None |
| hit@5 | 0.8829787234042553 |
| recall@12 | 0.9340425531914893 |
| MRR | 0.8525037610143994 |
| nDCG@5 | 0.8545114982260408 |
| Citation precision / recall | None / None |
| Solo-gate fire rate | 0.0 |
| Latency p50 / p95 (s) | 0.0 / 0.0 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=84, eligible n=0 (0.0) — basis: {'fact_spans': 0, 'file_level_image': 0}
- accuracy by basis: {} | combined: None

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 0
- non-abstain answers returned with ZERO cited sources: 0

## Failures (deterministic verdicts)


_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
