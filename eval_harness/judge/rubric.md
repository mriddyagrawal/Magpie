# Judge rubric — v2.0 (2026-08-28)

One judge instance (a pinned high-tier Claude, default Opus 5) grades an ENTIRE
run with full context: every question, its golden answer, Magpie's answer, AND the
actual source files (it Reads the gold-source images/documents itself). It
writes two artifacts in exactly the formats below. Owner decision 2026-08-28,
replacing the per-row partial-context judge.

Privacy: full-context judging sends document content to the API. Fine for
public corpora (receipts/SROIE). For personal corpora this mode requires the
owner's explicit per-dataset OK (PLAN §9.4).

## Grading rules (binary, reference-guided)

Verdicts (exactly one per question):
- `correct` — every key fact stated (formatting variants fine: 46.20 ≈ RM46.20;
  13/01/2018 ≈ "13 Jan 2018"), nothing contradicting the golden answer.
- `partial` — some but not all key facts, no contradiction.
- `wrong` — contradicts gold, states a different value, or answers a different
  receipt/file.
- `false_abstain` — answerable question, but Magpie declined (structured
  not_found flag OR abstaining prose OR empty answer).
- `correct_abstain` / `false_answer` — for `not_found` questions only: declined
  correctly / supplied a concrete value.

Discipline:
- Grade against the golden answer, not taste; phrasing-blind (a correct answer
  worded unlike the gold is still correct).
- Consult the source image when gold and answer disagree — if the GOLD is wrong
  (label error, ambiguous receipt), keep the verdict relative to the file's
  truth and flag the item in `golden_issues`.
- `undecidable: true` instead of guessing when the file itself can't settle it.
- Citation check: `citation_ok` = cited file names include the gold source
  (null when Magpie abstained or cited nothing on an abstain).

## Artifact 1 — `judge_verdicts.json` (strict schema)

```json
{
  "rubric_version": "2.0",
  "judge_model": "<resolved model id>",
  "run_id": "<run id>",
  "mode": "full_context",
  "verdicts": {
    "<qa_id>": {
      "verdict": "correct|partial|wrong|false_abstain|correct_abstain|false_answer",
      "facts": {"0": true, "1": false},
      "citation_ok": true,
      "source_consulted": true,
      "undecidable": false,
      "reason": "one sentence"
    }
  },
  "golden_issues": [
    {"qa_id": "…", "problem": "what is wrong with the golden item, per the file"}
  ],
  "summary": {
    "n": 0, "correct": 0, "partial": 0, "wrong": 0,
    "false_abstain": 0, "correct_abstain": 0, "false_answer": 0,
    "by_phrasing": {"typed": {"correct": 0, "n": 0}, "full": {"correct": 0, "n": 0}},
    "disagreements_with_deterministic": 0
  }
}
```

Every qa_id in the run's answers MUST appear in `verdicts`. `facts` keys are
key_facts indices from golden.json.

## Artifact 2 — `JUDGE-REPORT.md` (fixed sections, in order)

1. `# Judge report — <run_id>` + one-paragraph headline (numbers + the single
   most important pattern).
2. `## Scoreboard` — table: verdict counts overall and typed vs full phrasing.
3. `## Failure patterns` — failures grouped by cause (wrong-source reads,
   abstention, enumeration…), each with 2–3 qa_id examples and what the source
   image actually shows.
4. `## Golden-set issues` — items where the gold itself is wrong/ambiguous
   (this feeds the founders' silver→gold review).
5. `## Deterministic disagreements` — where the judge overturned the
   deterministic verdict and why (matcher-precision evidence).
6. `## Verdict-independent observations` — anything else the files revealed
   (product behavior, not scoring).
