# Eval report — 20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite

> ⚠️ **SILVER (provisional; includes MODEL-AUTHORED gold - review those first) golden set** — 0/120 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `custom-rahul-topk2-rerank-off-norewrite` · dataset `custom_dataset_rahul_Aug30` · 120 questions · backend `cca67570b04a`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.029 |
| Partial | 0.154 |
| Wrong | 0.394 |
| False abstain | 0.423 |
| Correct abstain (of 16 not_found) | 0.5 |
| False answer on not_found | 0.5 |
| hit@1 (pooled) | 0.9326923076923077 |
| hit@1 typed / full | 0.9230769230769231 / 0.9423076923076923 |
| hit@5 | 0.9423076923076923 |
| recall@12 | 0.9358974358974359 |
| MRR | 0.9346153846153846 |
| nDCG@5 | 0.9218625957145861 |
| Citation precision / recall | 0.17307692307692307 / 0.19604700854700854 |
| Solo-gate fire rate | 0.05 |
| Latency p50 / p95 (s) | 15.5 / 52.2 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=70, eligible n=49 (0.7) — basis: {'fact_spans': 0, 'file_level_image': 49}
- accuracy by basis: {'file_level_image': 0.041} | combined: 0.041

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 0
- non-abstain answers returned with ZERO cited sources: 29

## Failures (deterministic verdicts)

- **viz-01-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-02-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-02-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-03-typed** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **viz-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **viz-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **viz-04-full** [partial] hit@5=1.0 gate=False facts=3/4 err=-
- **viz-05-typed** [partial] hit@5=1.0 gate=False facts=1/3 err=-
- **viz-05-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **viz-06-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-06-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **viz-07-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **viz-07-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **viz-08-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-08-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-09-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-09-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **viz-10-typed** [partial] hit@5=1.0 gate=False facts=1/4 err=-
- **viz-10-full** [partial] hit@5=1.0 gate=False facts=3/4 err=-
- **viz-11-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **viz-11-full** [partial] hit@5=1.0 gate=False facts=1/3 err=-
- **arch-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-01-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-02-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-02-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-03-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-04-typed** [partial] hit@5=1.0 gate=True facts=1/2 err=-
- **arch-04-full** [partial] hit@5=1.0 gate=True facts=1/2 err=-
- **arch-05-typed** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **arch-05-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-06-typed** [wrong] hit@5=1.0 gate=True facts=0/2 err=-
- **arch-06-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-07-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **arch-07-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **arch-08-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **arch-08-full** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **arch-09-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-09-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-10-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **arch-10-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **study-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **study-01-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **study-02-typed** [wrong] hit@5=1.0 gate=False facts=0/8 err=-
- **study-02-full** [wrong] hit@5=1.0 gate=False facts=0/8 err=-
- **study-03-typed** [false_abstain] hit@5=1.0 gate=True facts=0/5 err=-
- **study-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/5 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **study-04-typed** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **study-04-full** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **study-05-typed** [wrong] hit@5=0.0 gate=False facts=0/5 err=-
- **study-05-full** [wrong] hit@5=0.0 gate=False facts=0/5 err=-
- **study-06-typed** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **study-06-full** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **study-07-typed** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **study-07-full** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **study-08-typed** [false_abstain] hit@5=1.0 gate=True facts=0/6 err=-
- **study-08-full** [wrong] hit@5=1.0 gate=True facts=0/6 err=-
- **study-09-typed** [wrong] hit@5=1.0 gate=False facts=0/6 err=-
- **study-09-full** [wrong] hit@5=1.0 gate=False facts=0/6 err=-
- **study-10-typed** [wrong] hit@5=0.0 gate=False facts=0/6 err=-
- **study-10-full** [wrong] hit@5=0.0 gate=False facts=0/6 err=-
- **study-11-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **study-11-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-01-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-02-typed** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **rcpt-02-full** [false_abstain] hit@5=1.0 gate=False facts=0/5 err=-
- **rcpt-03-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-04-typed** [partial] hit@5=1.0 gate=False facts=1/4 err=-
- **rcpt-04-full** [partial] hit@5=1.0 gate=False facts=1/4 err=-
- **rcpt-05-typed** [wrong] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-05-full** [wrong] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-06-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-06-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-07-typed** [false_abstain] hit@5=0.0 gate=False facts=0/5 err=-
- **rcpt-07-full** [false_abstain] hit@5=0.0 gate=False facts=0/5 err=-
- **rcpt-08-typed** [wrong] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-08-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-09-typed** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **rcpt-09-full** [false_abstain] hit@5=1.0 gate=False facts=0/5 err=-
- **phone-01-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-02-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-02-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-03-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-03-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **phone-04-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **phone-05-typed** [false_abstain] hit@5=1.0 gate=False facts=0/7 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **phone-05-full** [wrong] hit@5=1.0 gate=False facts=0/7 err=-
- **phone-06-typed** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **phone-06-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **phone-07-typed** [wrong] hit@5=1.0 gate=False facts=0/4 err=-
- **phone-08-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-08-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **phone-09-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-09-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-10-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-10-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-11-typed** [partial] hit@5=1.0 gate=False facts=2/3 err=-
- **phone-11-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **nf-02-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-04-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-04-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-06-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-07-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-07-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-08-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-08-full** [false_answer] hit@5=None gate=False facts=0/0 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
