# Eval report — 20260828T092814Z-receipts-topk12

> ⚠️ **SILVER (provisional) golden set** — 0/53 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `topk12` · dataset `receipts` · 53 questions · backend `29c56610d39a`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.0 |
| Partial | 0.0 |
| Wrong | 0.085 |
| False abstain | 0.915 |
| Correct abstain (of 6 not_found) | 1.0 |
| False answer on not_found | 0.0 |
| hit@5 | 0.9148936170212766 |
| recall@12 | 0.9574468085106383 |
| MRR | 0.8848362039851401 |
| nDCG@5 | 0.8885502022796365 |
| Citation precision / recall | 0.0 / 0.0 |
| Solo-gate fire rate | 0.0 |
| Latency p50 / p95 (s) | 34.8 / 47.3 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=42, eligible n=21 (0.5) — basis: {'fact_spans': 0, 'file_level_image': 21}
- accuracy by basis: {'file_level_image': 0.0} | combined: 0.0

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 0
- non-abstain answers returned with ZERO cited sources: 4

## Failures (deterministic verdicts)

- **rcpt-total-01** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-02** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-03** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-04** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-05** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-06** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-07** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-08** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-total-09** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-10** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-11** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-12** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-13** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-14** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-15** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-16** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-17** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-18** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-total-19** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-total-20** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-01** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-date-02** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-03** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-04** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-date-05** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-06** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-07** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-08** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-09** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-date-10** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-date-11** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-date-12** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-addr-01** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-addr-02** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-addr-03** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-04** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-addr-05** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-06** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-addr-07** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-addr-08** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-09** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-addr-10** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-count-01** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-count-02** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-count-03** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-listdates-04** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-listdates-05** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
