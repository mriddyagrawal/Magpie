# Furman Directory eval

**Date:** 2026-05-07
**Corpus:** `~/Desktop/Magpie testing/Furman Directory/furman_directory.csv` (single file, 1,481 rows; columns: name, title, email, phone, office, profile_url)
**Eval file:** `~/Desktop/Magpie testing/eval_furman_directory.json` (25 questions)
**Backend:** `LLM_PROVIDER=local`, Gemma 4 E4B + mmproj-BF16, llama-server `b9049`, vision profile as singleton default
**Pipeline:** `ask_sync(question, top_k=5, rewrite=True)`

The questions test direct-name lookup, role-based search ("who is the X"),
disambiguation among same-titled rows, reverse lookup (phone → person,
office → person), informal-name resolution ("Bill" → "William"), and
faculty enumeration.

## Result

| Verdict | Count | % |
|---|---:|---:|
| correct | 18 | 72% |
| partially_correct | 2 | 8% |
| incorrect | 5 | 20% |
| **partial-or-better** | **20** | **80%** |

Average per-question latency: **18.1s** (min 13.8s, max 30.1s) — fastest of the three evals.
Total wall-clock: ~7.5 min for the 25 questions.

**This is Magpie's best-performing eval.** Single-file CSV with one row per
person and rich text fields — exactly what the embedding + structured-extraction
pipeline does well.

## What Magpie got right (18 strict-correct)

The clean wins (questions answered with right person + key contact details):

- **q03** Farm Manager → Bruce Adams ✓
- **q04** Chief of Police → John Milby + phone + email ✓
- **q06** Provost → Beth Pontari ✓
- **q08** Dean of Students → Jason Cassidy ✓
- **q09** General Counsel → Meredith E. Green (correctly disambiguated from alumni listing) ✓
- **q10** Chaplain → Vaughn CroweTipton ✓
- **q11** Director of Libraries → Caroline Mills (disambiguated from Patricia Sasser of Maxwell Music Library) ✓
- **q12** Phone reverse lookup → Caro Douglas ✓
- **q15-q17** Math/Physics/MLL chairs → Lewis / Gulley / Friis ✓
- **q18** Earle Health Center medical director → Ann Gilchrist ✓
- **q19** Bill Aarnes email → bill.aarnes@furman.edu (correctly resolved Bill → William) ✓
- **q20** Engaged Learning Coordinator → Sara Abraham-Oxford ✓
- **q21** Emeritus CS Professor → Ken Abernethy ✓
- **q22** Psych chair → Erin Hahn (correctly disambiguated from Onarae Rice who chairs Neuroscience) ✓
- **q23** Anthropology chair → Lisa Knight ✓
- **q25** Frat/Sorority Life → Caro Douglas with full contact ✓

## Partial credit (2)

- **q05** (Title IX Coordinator): got Melissa Nichols correctly, missed mentioning Jeremy Cass as the deputy
- **q13** (Riley Hall 200-E): returned Kevin Treu only; GT says BOTH Tartaro and Treu share that office

## Failure modes (5)

### 1. Disambiguation under high false-positive load
- **q01** (President of Furman): said "Kevin T. Byrne, President and CEO of The University Financing Foundation" instead of Elizabeth Davis. The CSV has 69 entries containing "president" in their title (FAN club presidents, alumni-affiliated org presidents); only 1 has the bare title `President`. Magpie picked an alumni listing. **The eval was specifically designed to test this disambiguation challenge — it caught Magpie.**

### 2. Faculty enumeration limited by retrieval
- **q14** (List CS professors): returned only Chris Alvin + Bryan Catron. GT lists 6 current faculty (Tartaro, Treu, Alvin, Catron, Drucker, Sultan) plus Abernethy emeritus. With top_k=5, retrieval only surfaces a handful of rows; full-department enumeration needs all 6+ rows in the prompt.
- **q07** (Dean of Faculty): returned support staff (director of fiscal ops, executive assistant, faculty development director) but missed Jeremy Cass himself.
- **q02** (CS chair): said "do not contain information"; Andrea Tartaro is in the CSV but didn't make top-5 retrieval.

### 3. String confusion
- **q24** (Daniel Chapel office): returned "Mark Britt's office is in Daniel Music Building, Room 7" — wrong building (Daniel Music vs Daniel Chapel). Embedding match on "Daniel" without disambiguating which building.

## Diagnostic notes

For role-based and direct-name lookups against a clean CSV, Magpie is genuinely useful — 80% partial-or-better is a strong number for a small local model. The four failure cases are all related to retrieval scope:

- **Disambiguation** (q01) needs either a re-rank step that prefers exact-title matches, or a "filter for exact match first" pre-step in the pipeline.
- **Enumeration** (q07, q14) needs top_k > 5 when the question asks for "all" or "list every" — the existing query-class detector should bump top_k higher (it already does this for some classes; look at `query_class=list_all` in the pipeline log).
- **Embedding ambiguity** (q24) is a recall-precision tradeoff that's hard to fix without dataset-specific tuning.

When retrieval lands on the right row, the small local model extracts name + email + phone + office cleanly almost every time. **The CSV-row indexing + retrieval system is doing most of the work; the LLM just formats.**
