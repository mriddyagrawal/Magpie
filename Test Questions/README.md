# Test Questions — RAG eval set

Ground-truth question set for evaluating retrieval + answering over the files in `Test Content/`. Used later by the Stage 3 query pipeline to measure:

1. **Retrieval quality** — is the correct source file in the top-k returned by Qdrant?
2. **Answer quality** — does the final LLM's answer match `expected_answer`?

## Format

`questions.jsonl` — one JSON object per line. Schema:

| Field | Type | Meaning |
|---|---|---|
| `id` | `str` | Unique id, `<difficulty>-<NN>` |
| `difficulty` | `"easy"\|"medium"\|"hard"` | See below. |
| `question` | `str` | The natural-language query to send into the pipeline. |
| `expected_answer` | `str` | Ground truth — human-written answer with enough specificity to grade against. |
| `source_files` | `list[str]` | Files that actually contain the answer. Used to score retrieval precision / recall. Paths are relative to the repo root. |
| `notes` | `str` (optional) | Why the question is interesting or what skill it tests (aggregation, conflict detection, etc.). |

## Difficulty levels

- **Easy** — the answer is a single fact lexically present in exactly one file. A well-indexed lexical search alone would usually find it. Purpose: baseline sanity check on retrieval.
- **Medium** — the answer needs paraphrase understanding, a small inference, or a light aggregation inside one file. Sometimes spans a pair of obviously-related files (e.g., both flight receipts). Purpose: tests that the embedding model handles question-vs-summary asymmetric search and basic synthesis.
- **Hard** — multi-file synthesis, temporal reasoning, conflict detection between files, or cross-domain disambiguation (same keyword meaning different things in different files). Purpose: stress-tests the agentic retrieval loop (top-k = 5 may not be enough; model may need to call `fetch_next_documents` — see `Plans/Future Plans.md`).

## Current counts

- Easy: 12
- Medium: 12
- Hard: 11
- **Total: 35**

## How it'll be used downstream

Per the Stage 3 plan:

1. Feed each `question` to an LLM that generates one or more DB queries.
2. Run those queries against Qdrant, return top-5 summaries.
3. Give a second LLM the question + top-5 summaries + a system prompt; it names which file it used as the source of truth and gives the answer.
4. Compare: (a) is each entry in `source_files` present in the retrieved top-k? (b) does the final answer semantically match `expected_answer`? (c) did the model correctly cite its source file?

Metric sketch:
- **Recall@5** — fraction of questions where *every* file in `source_files` appears in the retrieved top-5.
- **Source accuracy** — fraction where the model's cited source is in `source_files`.
- **Answer accuracy** — graded by an LLM judge against `expected_answer` (or eyeballed for now).

## Extending

- Append new lines; keep IDs unique.
- Prefer answers that can be graded unambiguously. If the answer is genuinely open-ended, spell out the minimum facts that must appear.
- If a question's answer changes because a file in `Test Content/` changed, update the entry — don't leave stale ground truth.
