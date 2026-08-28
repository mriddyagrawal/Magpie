# Judge rubric — v1.0 (2026-08-28)

Binary, reference-guided grading of one Magpie answer against golden truth
(PLAN §5). The judge NEVER sees document content — only the question, the
gold answer + key facts, the model's answer, and cited file names (§9.4
privacy scope). Verdicts are yes/no per criterion; no scores, no scales.

## Criteria (each answered true/false, independently)

1. **fact_present[i]** — for each key fact: does the answer STATE this fact,
   allowing formatting variants (46.20 ≈ RM46.20 ≈ "46.20 ringgit";
   13/01/2018 ≈ "13 Jan 2018")? Restating the question or hedging does not
   count. A fact merely implied but not stated does not count.
2. **no_contradiction** — the answer contains NO claim that contradicts the
   gold answer (a wrong total alongside the right one fails this).
3. **abstention_correct** — only for `not_found` items: the answer declines
   (in structure or prose) rather than supplying any concrete value.
4. **enumeration_complete** — only for `enumeration` items: every element of
   the gold list appears; no invented extras.

## Verdict derivation (mechanical, from the criteria)

- extractive: correct = all fact_present AND no_contradiction
- enumeration: correct = enumeration_complete AND no_contradiction
- not_found: correct = abstention_correct
- partial = some but not all fact_present, AND no_contradiction
- anything else = wrong

## Bias guards

- Reference-guided: the gold answer is shown; grade against IT, not taste.
- Phrasing-blind: a correct answer phrased unlike the gold is still correct —
  the calibration fixture contains such items deliberately (§7 Phase 3).
- When genuinely undecidable from the given material, return
  `"undecidable": true` rather than guessing.

## Output (strict JSON, nothing else)

```json
{
  "fact_present": {"0": true, "1": false},
  "no_contradiction": true,
  "abstention_correct": null,
  "enumeration_complete": null,
  "undecidable": false,
  "reason": "one sentence"
}
```
