# Pipeline Eval Results (stages 3 + 4, end-to-end)

- Run: 2026-04-13 01:00:53 UTC
- Model: kimi-k2.5 via Moonshot
- Top-k (Qdrant): 5
- Questions: 1

## Summary

| ID | Difficulty | Retrieval recall | Citation recall | Elapsed (s) |
|---|---|---|---|---|
| medium-11 | medium | — | — | 39.9 (ERROR) |

## Per-question

### medium-11 — medium

**Question:** According to the Artwork Analysis essay, what do students who fail at understanding harmonies in their abstract form go on to become, and what about those who fail astronomy?

**Expected answer:** Those who fail harmonies become 'Harmon-ists' who make, tune, and study instruments. Those who fail astronomy (the pure-logic/math understanding of stellar motions) become Astronomers who build telescopes and study stars.

**Expected source files:**
- `Test Content/Artwork Analysis.docx`

**ERROR:** ModelHTTPError: status_code: 429, model_name: kimi-k2.5, body: {'message': 'The engine is currently overloaded, please try again later', 'type': 'engine_overloaded_error'}

*Elapsed: 39.9s*

---

