# Eval report — gbnf-baseline

> ⚠️ **SILVER (provisional; label-derived) golden set** — 0/106 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `baseline` · dataset `receipts` · 106 questions · backend `0a3968fb26b7`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.0 |
| Partial | 0.0 |
| Wrong | 0.0 |
| False abstain | 1.0 |
| Correct abstain (of 12 not_found) | 1.0 |
| False answer on not_found | 0.0 |
| hit@5 | None |
| recall@12 | None |
| MRR | None |
| nDCG@5 | None |
| Citation precision / recall | 0.0 / 0.0 |
| Solo-gate fire rate | 0.0 |
| Latency p50 / p95 (s) | 1.1 / 1.9 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=84, eligible n=0 (0.0) — basis: {'fact_spans': 0, 'file_level_image': 0}
- accuracy by basis: {} | combined: None

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 0
- non-abstain answers returned with ZERO cited sources: 0

## Failures (deterministic verdicts)

- **rcpt-total-01-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-01-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-06-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-06-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-11-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-11-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-16-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-16-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-01-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-01-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-06-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-06-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-11-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-11-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-addr-04-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-04-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-09-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-09-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-total-02-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-02-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-07-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-07-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-12-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-12-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-17-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-17-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-02-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-02-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-07-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-07-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-12-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-12-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-addr-05-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-05-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-10-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-10-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-total-03-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-03-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-08-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-08-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-13-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-13-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-18-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-18-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-03-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-03-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-08-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-08-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-addr-01-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-01-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-06-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-06-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-total-04-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-04-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-09-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-09-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-14-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-14-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-19-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-19-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-04-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-04-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-09-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-09-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-addr-02-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-02-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-07-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-07-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-total-05-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-05-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-10-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-10-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-15-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-15-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-20-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-total-20-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-05-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-05-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-10-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-date-10-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-addr-03-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-03-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-08-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-addr-08-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-count-01-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-count-01-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-count-02-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-count-02-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-count-03-typed** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-count-03-full** [false_abstain] hit@5=None gate=False facts=0/1 err=-
- **rcpt-listdates-04-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-listdates-04-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-listdates-05-typed** [false_abstain] hit@5=None gate=False facts=0/2 err=-
- **rcpt-listdates-05-full** [false_abstain] hit@5=None gate=False facts=0/2 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
