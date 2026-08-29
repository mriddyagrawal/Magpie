# Eval report — 20260829T025810Z-receipts-baseline

> ⚠️ **SILVER (provisional) golden set** — 0/106 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `baseline` · dataset `receipts` · 106 questions · backend `dfa5074d5e2a`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.064 |
| Partial | 0.021 |
| Wrong | 0.34 |
| False abstain | 0.574 |
| Correct abstain (of 12 not_found) | 0.5 |
| False answer on not_found | 0.5 |
| hit@5 | 0.8829787234042553 |
| recall@12 | 0.9340425531914893 |
| MRR | 0.8304795677136104 |
| nDCG@5 | 0.8380057441715663 |
| Citation precision / recall | 0.032446808510638296 / 0.10638297872340426 |
| Solo-gate fire rate | 0.0 |
| Latency p50 / p95 (s) | 33.8 / 42.4 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=84, eligible n=73 (0.869) — basis: {'fact_spans': 0, 'file_level_image': 73}
- accuracy by basis: {'file_level_image': 0.068} | combined: 0.068

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 1
- non-abstain answers returned with ZERO cited sources: 26

## Failures (deterministic verdicts)

- **rcpt-total-01-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-06-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-06-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-11-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-11-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-16-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-16-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-01-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-06-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-06-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-11-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-11-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-04-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **rcpt-addr-09-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-09-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-total-02-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-07-typed** [wrong] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-total-07-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-12-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-12-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-17-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-17-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-02-typed** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-date-02-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-07-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-07-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-12-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-05-typed** [false_abstain] hit@5=0.0 gate=False facts=0/2 err=-
- **rcpt-addr-05-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-10-typed** [false_abstain] hit@5=0.0 gate=False facts=0/2 err=-
- **rcpt-addr-10-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-total-03-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-08-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-08-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-13-typed** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-total-13-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-18-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-18-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-03-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-08-typed** [wrong] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-date-08-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-01-typed** [false_abstain] hit@5=0.0 gate=False facts=0/2 err=-
- **rcpt-addr-01-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-06-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-06-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-total-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-04-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-09-typed** [wrong] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-total-09-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-14-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-14-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-19-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-19-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-04-typed** [wrong] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-date-04-full** [wrong] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-date-09-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-02-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-02-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-07-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-07-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **rcpt-total-05-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-05-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-10-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-10-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-15-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-15-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-20-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-20-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-05-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-05-full** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-date-10-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-10-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-03-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-08-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-08-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-absent-01-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-03-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-04-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-04-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-05-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-06-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-count-01-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-count-02-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-count-02-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-count-03-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-count-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-listdates-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-listdates-04-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-listdates-05-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-listdates-05-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
