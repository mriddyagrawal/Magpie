# Eval report — 20260829T081855Z-receipts-topk3-rerank-off-norewrite

> ⚠️ **SILVER (provisional; includes MODEL-AUTHORED gold - review those first) golden set** — 0/120 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `topk3-rerank-off-norewrite` · dataset `receipts` · 120 questions · backend `c823a44f1227`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.009 |
| Partial | 0.047 |
| Wrong | 0.623 |
| False abstain | 0.321 |
| Correct abstain (of 14 not_found) | 0.5 |
| False answer on not_found | 0.5 |
| hit@1 (pooled) | 0.7924528301886793 |
| hit@1 typed / full | 0.6792452830188679 / 0.9056603773584906 |
| hit@5 | 0.9433962264150944 |
| recall@12 | 0.9516509433962265 |
| MRR | 0.8508647798742138 |
| nDCG@5 | 0.8604884447010349 |
| Citation precision / recall | 0.06037735849056604 / 0.11202830188679246 |
| Solo-gate fire rate | 0.0 |
| Latency p50 / p95 (s) | 20.3 / 58.1 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=80, eligible n=73 (0.912) — basis: {'fact_spans': 0, 'file_level_image': 73}
- accuracy by basis: {'file_level_image': 0.014} | combined: 0.014

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 0
- non-abstain answers returned with ZERO cited sources: 45

## Failures (deterministic verdicts)

- **rcpt-a-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-a-01-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-a-02-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-a-02-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-a-03-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-03-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-04-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-04-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-05-typed** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-a-05-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-a-06-typed** [wrong] hit@5=0.0 gate=False facts=0/2 err=-
- **rcpt-a-06-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-07-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-a-07-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-a-08-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-08-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-09-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-09-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-a-10-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **rcpt-a-10-full** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **rcpt-b-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-b-01-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-b-02-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-b-02-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-b-03-typed** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **rcpt-b-03-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-b-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-b-04-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-b-05-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-b-06-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-b-06-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-b-07-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-b-07-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **rcpt-b-08-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-b-08-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-b-09-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-b-09-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-b-10-typed** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **rcpt-b-10-full** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **rcpt-c-01-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-01-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-02-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-02-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-03-typed** [wrong] hit@5=0.0 gate=False facts=0/2 err=-
- **rcpt-c-03-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-c-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-c-04-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-c-05-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-05-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-06-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-06-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-07-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-c-07-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-c-08-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-08-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-c-09-typed** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **rcpt-c-09-full** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **rcpt-c-10-typed** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **rcpt-c-10-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-d-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-d-01-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-d-02-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-d-02-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **rcpt-d-03-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-d-03-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-d-04-typed** [false_abstain] hit@5=0.0 gate=False facts=0/2 err=-
- **rcpt-d-04-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-d-05-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-d-05-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-d-06-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-d-06-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-d-07-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-d-07-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-d-08-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-d-08-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-d-09-typed** [partial] hit@5=1.0 gate=False facts=1/3 err=-
- **rcpt-d-09-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **rcpt-d-10-typed** [partial] hit@5=1.0 gate=False facts=1/3 err=-
- **rcpt-d-10-full** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **rcpt-e-01-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-01-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-02-typed** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-e-02-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-03-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-03-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-04-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-e-04-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-e-05-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-05-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-06-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-06-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-e-07-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-e-07-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-e-08-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-e-08-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-e-09-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-e-09-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-e-10-typed** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **rcpt-e-10-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-en-01-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-en-01-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-en-02-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-en-02-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **rcpt-en-03-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-en-03-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **rcpt-nf-02-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-nf-03-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-nf-04-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-nf-05-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-nf-06-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-nf-06-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **rcpt-nf-07-full** [false_answer] hit@5=None gate=False facts=0/0 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
