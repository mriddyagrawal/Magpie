# Eval report — 20260830T121044Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-rewrite

> ⚠️ **SILVER (provisional; includes MODEL-AUTHORED gold - review those first) golden set** — 0/120 items human-verified. Every number below is provisional until both founders complete the silver→gold review (PLAN §6). Do not act on H1 or publish these figures.

Config `custom-rahul-topk2-rerank-off-rewrite` · dataset `custom_dataset_rahul_Aug30` · 120 questions · backend `cca67570b04a`

## Headline

| Metric | Value |
|---|---:|
| Correct (answerable, deterministic) | 0.029 |
| Partial | 0.192 |
| Wrong | 0.346 |
| False abstain | 0.433 |
| Correct abstain (of 16 not_found) | 0.625 |
| False answer on not_found | 0.375 |
| hit@1 (pooled) | 0.8557692307692307 |
| hit@1 typed / full | 0.7884615384615384 / 0.9230769230769231 |
| hit@5 | 0.875 |
| recall@12 | 0.8605769230769231 |
| MRR | 0.8621794871794871 |
| nDCG@5 | 0.8451940711058769 |
| Citation precision / recall | 0.16346153846153846 / 0.17841880341880342 |
| Solo-gate fire rate | 0.042 |
| Latency p50 / p95 (s) | 14.4 / 41.0 |

## H1 slice (per-arm; never compare raw across arms)

- extractive n=70, eligible n=44 (0.629) — basis: {'fact_spans': 0, 'file_level_image': 44}
- accuracy by basis: {'file_level_image': 0.045} | combined: 0.045

## Product findings (deterministic observations, not verdicts)

- answers that abstained in prose while the structured not_found flag stayed False: 1
- non-abstain answers returned with ZERO cited sources: 25

## Failures (deterministic verdicts)

- **viz-01-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-02-typed** [wrong] hit@5=0.0 gate=False facts=0/2 err=-
- **viz-02-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **viz-03-typed** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **viz-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **viz-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **viz-04-full** [partial] hit@5=1.0 gate=False facts=3/4 err=-
- **viz-05-typed** [wrong] hit@5=1.0 gate=False facts=0/3 err=-
- **viz-05-full** [partial] hit@5=1.0 gate=False facts=1/3 err=-
- **viz-06-typed** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **viz-06-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **viz-07-typed** [false_abstain] hit@5=0.0 gate=False facts=0/4 err=-
- **viz-07-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **viz-08-typed** [wrong] hit@5=0.0 gate=False facts=0/2 err=-
- **viz-08-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **viz-09-typed** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **viz-09-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **viz-10-typed** [wrong] hit@5=0.0 gate=False facts=0/4 err=-
- **viz-10-full** [partial] hit@5=1.0 gate=False facts=3/4 err=-
- **viz-11-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **viz-11-full** [partial] hit@5=1.0 gate=False facts=1/3 err=-
- **arch-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-01-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-02-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-02-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-03-typed** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/1 err=-
- **arch-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-04-full** [partial] hit@5=1.0 gate=True facts=1/2 err=-
- **arch-05-typed** [wrong] hit@5=0.0 gate=False facts=0/2 err=-
- **arch-05-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-06-typed** [wrong] hit@5=1.0 gate=True facts=0/2 err=-
- **arch-06-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-07-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **arch-07-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **arch-08-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **arch-08-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **arch-09-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-09-full** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **arch-10-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **arch-10-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **study-01-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **study-01-full** [partial] hit@5=1.0 gate=False facts=2/4 err=-
- **study-02-typed** [wrong] hit@5=1.0 gate=False facts=0/8 err=-
- **study-02-full** [wrong] hit@5=1.0 gate=False facts=0/8 err=-
- **study-03-typed** [false_abstain] hit@5=1.0 gate=True facts=0/5 err=-
- **study-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/5 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **study-04-typed** [false_abstain] hit@5=0.0 gate=False facts=0/5 err=-
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
- **rcpt-02-full** [partial] hit@5=1.0 gate=False facts=1/5 err=-
- **rcpt-03-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-03-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-04-full** [partial] hit@5=1.0 gate=False facts=1/4 err=-
- **rcpt-05-typed** [wrong] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-05-full** [partial] hit@5=1.0 gate=False facts=1/4 err=-
- **rcpt-06-typed** [wrong] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-06-full** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-07-typed** [wrong] hit@5=0.0 gate=False facts=0/5 err=-
- **rcpt-07-full** [false_abstain] hit@5=0.0 gate=False facts=0/5 err=-
- **rcpt-08-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **rcpt-08-full** [partial] hit@5=1.0 gate=False facts=1/4 err=-
- **rcpt-09-typed** [wrong] hit@5=1.0 gate=False facts=0/5 err=-
- **rcpt-09-full** [false_abstain] hit@5=1.0 gate=False facts=0/5 err=-
- **phone-01-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-02-typed** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **phone-02-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **phone-03-typed** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-03-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-04-typed** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **phone-04-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=-
- **phone-05-typed** [false_abstain] hit@5=1.0 gate=False facts=0/7 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **phone-05-full** [wrong] hit@5=1.0 gate=False facts=0/7 err=-
- **phone-06-typed** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **phone-06-full** [partial] hit@5=1.0 gate=False facts=1/2 err=-
- **phone-07-typed** [false_abstain] hit@5=1.0 gate=False facts=0/4 err=-
- **phone-08-typed** [false_abstain] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-08-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-09-typed** [false_abstain] hit@5=0.0 gate=False facts=0/1 err=-
- **phone-09-full** [wrong] hit@5=1.0 gate=False facts=0/1 err=-
- **phone-10-typed** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-10-full** [wrong] hit@5=1.0 gate=False facts=0/2 err=-
- **phone-11-typed** [partial] hit@5=1.0 gate=False facts=1/3 err=-
- **phone-11-full** [false_abstain] hit@5=1.0 gate=False facts=0/3 err=HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:9400/v1/chat/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- **nf-01-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-03-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-04-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-04-full** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-05-typed** [false_answer] hit@5=None gate=False facts=0/0 err=-
- **nf-08-full** [false_answer] hit@5=None gate=False facts=0/0 err=-

_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._
