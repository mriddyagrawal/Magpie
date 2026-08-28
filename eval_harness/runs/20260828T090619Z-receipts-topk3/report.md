# Eval report — 20260828T090619Z-receipts-topk3

> ⚠️ **SILVER (provisional) golden set** — 0/53 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `topk3` · dataset `receipts` · 53 questions · backend `c046326b7170`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.149 |
| Partial | 0.0 |
| Wrong | 0.638 |
| False abstain | 0.213 |
| Correct abstain (of 6 not_found) | 0.0 |
| False answer on not_found | 1.0 |
| hit@5 | 0.9148936170212766 |
| recall@12 | 0.9574468085106383 |
| MRR | 0.8855116514690983 |
| nDCG@5 | 0.8885502022796365 |
| Citation precision / recall | 0.20212765957446802 / 0.374468085106383 |
| Solo-gate fire rate | 0.0 |
| Latency p50 / p95 (s) | 23.5 / 33.6 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=42, eligible n=38 (0.905) — basis: {'fact_spans': 0, 'file_level_image': 38}
- accuracy by basis: {'file_level_image': 0.158} | combined: 0.158

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 6
- non-abstain answers returned with ZERO cited sources: 8

## Failures (deterministic verdicts)

- **rcpt-total-01** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-02** [wrong] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-total-04** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-05** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-07** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-08** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-total-09** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-10** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-11** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-12** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-13** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-15** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-16** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-17** [wrong] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-total-18** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-19** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-01** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-02** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-03** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-04** [wrong] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-date-06** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-07** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-08** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-10** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-11** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-12** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-01** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-02** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-03** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-04** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-05** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-06** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-07** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-08** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-09** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-10** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-absent-01** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-02** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-03** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-04** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-05** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-absent-06** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-count-01** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-count-03** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-listdates-04** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-listdates-05** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
