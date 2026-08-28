# Eval report — h2-vague-rw0

> ⚠️ **SILVER (provisional) golden set** — 0/32 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `h2-vague-rw0` · dataset `receipts` · 32 questions · backend `6f4cf3d185f0`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | None |
| Partial | None |
| Wrong | None |
| False abstain | None |
| Correct abstain (of 0 not_found) | None |
| False answer on not_found | None |
| hit@5 | 0.90625 |
| recall@12 | 0.9375 |
| MRR | 0.91015625 |
| nDCG@5 | 0.90625 |
| Citation precision / recall | None / None |
| Solo-gate fire rate | 0.0 |
| Latency p50 / p95 (s) | 0.0 / 0.0 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=32, eligible n=0 (0.0) — basis: {'fact_spans': 0, 'file_level_image': 0}
- accuracy by basis: {} | combined: None

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 0
- non-abstain answers returned with ZERO cited sources: 0

## Failures (deterministic verdicts)


_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
