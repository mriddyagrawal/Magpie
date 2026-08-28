# Eval report — 20260828T085454Z-receipts-topk1

> ⚠️ **SILVER (provisional) golden set** — 0/53 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `topk1` · dataset `receipts` · 53 questions · backend `24ff2c442e67`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.468 |
| Partial | 0.043 |
| Wrong | 0.255 |
| False abstain | 0.234 |
| Correct abstain (of 6 not_found) | 0.167 |
| False answer on not_found | 0.833 |
| hit@5 | 0.9361702127659575 |
| recall@12 | 0.9574468085106383 |
| MRR | 0.8969858156028369 |
| nDCG@5 | 0.9046336715065106 |
| Citation precision / recall | 0.5957446808510638 / 0.5539007092198581 |
| Solo-gate fire rate | 0.962 |
| Latency p50 / p95 (s) | 9.6 / 23.3 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=42, eligible n=36 (0.857) — basis: {'fact_spans': 0, 'file_level_image': 36}
- accuracy by basis: {'file_level_image': 0.611} | combined: 0.611

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 0
- non-abstain answers returned with ZERO cited sources: 2

## Failures (deterministic verdicts)

- **rcpt-total-02** [wrong] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-total-05** [false_abstain] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-total-08** [wrong] hit@5=0.0 gate=True facts=0/1 err=-
- **rcpt-total-12** [false_abstain] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-total-15** [wrong] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-total-17** [wrong] hit@5=0.0 gate=True facts=0/1 err=-
- **rcpt-date-03** [false_abstain] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-date-04** [wrong] hit@5=0.0 gate=True facts=0/1 err=-
- **rcpt-date-05** [wrong] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-date-06** [false_abstain] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-date-08** [wrong] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-date-12** [false_abstain] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-addr-01** [false_abstain] hit@5=1.0 gate=True facts=0/2 err=-
- **rcpt-addr-02** [false_abstain] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-addr-03** [false_abstain] hit@5=1.0 gate=True facts=0/2 err=-
- **rcpt-addr-05** [wrong] hit@5=1.0 gate=True facts=0/2 err=-
- **rcpt-addr-06** [partial] hit@5=1.0 gate=True facts=1/2 err=-
- **rcpt-addr-07** [wrong] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-addr-08** [false_abstain] hit@5=1.0 gate=True facts=0/2 err=-
- **rcpt-addr-09** [partial] hit@5=1.0 gate=True facts=1/2 err=-
- **rcpt-absent-02** [false_answer] hit@5=None gate=True facts=0/0 err=-
- **rcpt-absent-03** [false_answer] hit@5=None gate=True facts=0/0 err=-
- **rcpt-absent-04** [false_answer] hit@5=None gate=True facts=0/0 err=-
- **rcpt-absent-05** [false_answer] hit@5=None gate=True facts=0/0 err=-
- **rcpt-absent-06** [false_answer] hit@5=None gate=True facts=0/0 err=-
- **rcpt-count-01** [wrong] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-count-02** [wrong] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-count-03** [wrong] hit@5=1.0 gate=True facts=0/1 err=-
- **rcpt-listdates-04** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-listdates-05** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
