# Eval report — smoke-02

> ⚠️ **SILVER (provisional) golden set** — 0/5 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `smoke` · dataset `receipts_smoke` · 5 questions · backend `b6f2a6301e83`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.0 |
| Partial | 0.0 |
| Wrong | 0.75 |
| False abstain | 0.25 |
| Correct abstain (of 1 not_found) | 1.0 |
| False answer on not_found | 0.0 |
| hit@5 | 1.0 |
| recall@12 | 1.0 |
| MRR | 1.0 |
| nDCG@5 | 1.0 |
| Citation precision / recall | 0.0 / 0.0 |
| Solo-gate fire rate | 0.0 |
| Latency p50 / p95 (s) | 23.6 / 36.2 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=4, eligible n=4 (1.0) — basis: {'fact_spans': 0, 'file_level_image': 4}
- accuracy on eligible: 0.0

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 2
- non-abstain answers returned with ZERO cited sources: 3

## Failures (deterministic verdicts)

- **rcpt-total-01** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-02** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-03** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-01** [wrong] hit@5=1.0 gate=False facts=0/1 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
