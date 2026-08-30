# CONTINUE.md — session handoff (updated 2026-08-26)

For the next assistant/instance continuing Magpie's answer-quality work.
Read this top to bottom before doing anything. The prior session's full
measured trail is in `Evaluations/college_data/REPORT.md` (LOCAL-ONLY,
gitignored — see "machine-bound data" below).

## RESUME HERE (2026-08-27): four delivery-path bugs found and fixed

The local answer path was throwing away answers the model had already
produced. Four bugs, all between the model and the user, none of them in
the reasoning. Measured on a NEW instrument (`Evaluations/sem6/`, 25
questions over the indexed `/mnt/hardisk/sem6` archive, deterministic
regex scoring — see its REPORT.md):

**0/25 → median 19/25 (n=3: 19, 18, 20).**

| # | Bug | Fix |
| --- | --- | --- |
| 1 | `response_format: json_schema` is accepted and **silently ignored** by llama-server b9049 — structured output was never enforced. The model improvised key names and every answer was discarded. | `src/inference/gbnf.py` compiles the schema to GBNF; `LocalAgent` sends it as `grammar` (which does work) |
| 2 | `Answer` declared `not_found` first, so under a grammar the model committed to a refusal as its opening token and then wrote the correct answer underneath it — which the not-found contract deleted | field order is now `answer, sources_used, not_found, not_found_topic` |
| 3 | The grammar allowed raw control characters in strings and unbounded whitespace; one answer was 3,600 chars of fenced junk inside an open string, another was 2,048 tokens of tabs | `char` excludes `\x00-\x1F`, `ws` is one optional space, and `parse_json_with_repair` gained `_close_truncated_json` |
| 4 | The JSON drift rescue only fired when `sources_used` was present and correctly named — it never was | rescue widened; **this alone is 0 → 15**, and it is permanent value for cloud, which has no grammar |

Also shipped: Liquid's sampler set (temp 0.1 / min_p 0.15 / repeat_penalty
1.05 — the model card's numbers, never sent before), provider-aware so
cloud is untouched, plus a `settings.json` v1→v2 migration that unpins the
0.7 seeded from the old default. Worth ~2 strict points **and roughly half
the latency** (11.0s → 5.8s median with a grammar active).

And a deterministic groundedness guard (`src/grounding.py`, called from
`answer.py`): if every number in an answer appears in no file the model
read and none is a derivable sum, the answer becomes an honest not-found.
Across all three shipping-config runs: **zero unsupported numbers**, where
before it invented `$159.00` on the absence probe.

### Then extended to 40 questions (same day)

15 harder questions added (q26-q40). **n=4: 31, 31, 31, 30 → median 31/40
(77.5%), spread of one question.** The first three runs were identical
question for question; the fourth moved three verdicts (q10 and q38 out,
q27 in), all of them questions where the grounding guard is deciding
between an answer and a refusal. Against the `college_data` band of
{15, 11, 11} with eight questions flipping, the failures here are
systematic — which is the difference between "we cannot measure a lever"
and "we can attack them one at a time".

Two further hypotheses were pre-registered, run, and **refuted**:

- **MULTI-PART block** (tell the model to answer every part of a multi-part
  question): 30/40 against a 31 baseline, gate ≥33 FAILED. It changed
  exactly one verdict and converted neither of its two target questions.
  At 3B, instructing completeness does not produce completeness. Kept
  behind `MAGPIE_MULTIPART=1`.
- **Rerank fusion** (`MAGPIE_RERANK_FUSE=1`): built after finding that the
  cross-encoder is what buries q39's spreadsheet (rank 2 with rerank OFF,
  absent from the top 12 with rerank ON — the module's own documented bias
  against terse summaries, and the anchor guarantee protects only fusion
  #1). The retrieval probe did NOT recover the file, so it is off and
  **unclaimed**. The pool the reranker sees in production differs from the
  pool the probe used; that discrepancy is the next thing to chase.

One hypothesis was **confirmed and shipped**: fabricated figures were
entering at INDEX time. The Max Planck letter's digits are destroyed by a
font encoding, but its summary states a salary of 2,500.00 and a postcode of
44801 — invented by the summarizer — and every answer about that file quoted
them. Summaries no longer count as support for a figure
(`grounding.strip_generated_blocks`, now default, score-neutral at 31/40 and
two fabrications converted to honest refusals), and
`stage1.summarize.scrub_invented_numbers` stops new ones entering the index.
**Existing summaries still carry whatever the summarizer invented — only a
re-index cleans them.**

Retrieval is not the bottleneck on this instrument either:
`Evaluations/retrieval_recall.py` splits the blame per question and finds
8 of the 9 misses had the key file in front of the model.

### Two more corpora, two different bottlenecks (same day)

The owner asked for fresh datasets. Both were indexed into their own data
dir + their own Qdrant instance so the sem6 index stayed intact.

| corpus | what it is | strict | binding constraint |
| --- | --- | ---: | --- |
| `Evaluations/sem5` | a C# repository (CSC223 coursework) | 17 → **21/25** | retrieval |
| `Evaluations/sem4` | mixed: receipts, flights, RA handbook, 111 `.py` | 7 → 8/25 | **the summarizer** |

**sem5 — gate PASSED.** The summarizer describes code in prose and drops
every identifier: `GeneralUtils.cs` declares `ToCamelCase`,
`IsPasswordStrong`, `GetIndentation`, and its summary contains none of them
with `Identifiers:` empty. Search embeds the summary, so those questions had
no hook at all — 7 of 25 lost their key file. Two fixes shipped:
`stage1.summarize.extract_code_symbols` (regex, not the model) and a
**dedicated sparse prefetch for keywords** — previously they were merely
concatenated onto the query, which measurably is not enough: searching
`GetIndentation` ranks the file 1st/2nd/4th, while "What does GetIndentation
return for a level of 3?" does not return it at all.

**sem_4 — gate FAILED (needed ≥12).** The cause is upstream of everything:
`Receipt-2794-8324.pdf` is a $20 Cursor invoice whose generated summary
describes "a flight from Atlanta to Hartford, flight number DL1492,
passenger Jane Doe". Five questions inherited that fiction. Dropping the
summary from the answer context (the tested lever) does not recover them —
the model that wrote the fiction is the model doing the reading. **At 3B,
summary quality is a hard ceiling on answer quality.**

Also refuted with pre-registered gates and left OFF: MULTI-PART prompting,
summary-dropping (`MAGPIE_SUMMARY_WHEN_THIN`), and acronym widening — which
was shown inert on sem6 *before* running it (only 3 of 40 questions contain
an acronym and all three already pass).

### Two infrastructure bugs, both silent, both fixed

1. **The llama-server stderr pipe could deadlock the model.** Pipes were
   opened `text=True` with no `errors=` policy; llama-server emits non-UTF-8
   bytes, the drain thread raised, died, the pipe filled and the subprocess
   **blocked on write**, never reaching `/health`. One run sat at 0% CPU for
   twelve minutes. The same exception is in every log from this session.
2. **A zombie llama-server holding VRAM** makes the next spawn fail
   (`ggml_vulkan: Device memory allocation ... failed`). One eval scored
   1/25 that way and is recorded as INVALID, not as a result.

### WARNING: the sem6 index moved

A one-off cleanup pass over existing summaries was too aggressive — it
scrubbed figures from **scanned** files, where there is no text layer to
check against and the vision pass had read them correctly. 180 summaries
were affected; 174 have been re-summarized with the fixed scrubber, 6 failed
(oversized PDFs), and 14 still carry `[unreadable]` — almost all correctly
(the Max Planck letter's salary genuinely is unreadable glyphs).

**Consequence: sem6 summaries are not byte-identical to the ones behind the
31/40 numbers. Re-baseline before comparing any new sem6 run to v40a-v40f.**

### The summarizer was copying its own prompt (2026-08-28)

`Evaluations/summary_fidelity.py` is a new, deterministic index-time metric:
it checks each summary's own `Key entities:` / `Identifiers:` claims against
the source text. No model in the loop. It is the first instrument measuring
the INDEX path — the first three all measure the query path, and on sem_4
they all pointed at "the reader is weak" when the reader was fine and the
summary was fiction.

It immediately found two bugs, both the same shape:

| copied from | surfaced as |
| --- | --- |
| the summarizer prompt's one-shot Delta-receipt example | `Jane Doe`, `DL1492`, `ABC123` claimed in a resume, a cover letter, a Word doc and a Cursor invoice |
| the injected `Current date and time:` line | `2026-08-27` claimed as a *document identifier* in three unrelated files |

Both fixed. sem_4, full chain re-run twice (re-summarize → re-embed →
fidelity → 25 questions): **fabricated-claim rate 17.9% → 10.6% → 7.9%,
strict score 7/25 → 10/25 → 10/25.** The score flattening while fidelity
kept falling is the signal that the two instruments measure different
stages.

**The general lesson: a 3B does not mostly invent, it copies.** Every false
value traced today came from something WE put in its context. Check the
prompt before blaming the model.

Note for the local-vs-cloud question the owner raised: sem6's index was
built with the CLOUD provider and sem5/sem_4 with local, so the three-corpus
scores carry that confound. But the same prompt feeds both providers, and
removing the copyable text fixed 4/5 of the local fabrication without a
model change — so this was our bug, not a local-model limitation. A clean
cloud-vs-local fidelity comparison is still unrun, and would send document
text off-machine, which is an owner decision.

### sem_4: 7/25 -> 16/25 from three index-side bugs (2026-08-28)

None of them were the model reasoning badly. All three were things WE put in
its context, and each was found by measuring the INDEX rather than the query
path:

| bug | symptom | fix |
| --- | --- | --- |
| prompt's one-shot example | `Jane Doe`, `DL1492` claimed in a resume, a cover letter, a receipt | example replaced with `<SLOT>` placeholders |
| injected `Current date and time:` | `2026-08-27` claimed as a document identifier | summarizer no longer gets a timestamp; the answer step still does |
| **NUL bytes in PDF extraction** | content-free summary + leaked chat-template tokens, repeated verbatim as four answers | `content.scrub_control_chars` at a single choke point |

Reader losses fell 13 -> 5. The NUL fix alone was worth +6 questions, and it
was found by asking why ONE file's summary was empty — the only file across
three corpora with NUL bytes, and the only one leaking template tokens.

**Method note that generalises:** the query-side metrics all said "the reader
is weak" for this corpus, three times running. They were wrong three times.
The reader was faithfully repeating a broken summary built from corrupted
text. When answers look like descriptions of a document rather than answers
about it, suspect the summary, then suspect the extraction.

**`summary_fidelity` has a known flaw:** it counts summaries with >=1
unsupported claim, which penalises verbosity. After the NUL fix the model
made 21% more claims (it could finally read the files), so the dirty count
rose 12 -> 17 while the per-claim rate stayed flat at ~4%. Use the per-claim
rate as the headline; the count is secondary.

### Overnight: all three index-side fixes applied to every corpus (2026-08-28)

| corpus | fabricated-claim rate | strict score |
| --- | --- | --- |
| sem_4 mixed | 17.9% -> **7.9%** | 7/25 -> **19/25** |
| sem5 code | 9.3% -> **1.2%** | 17/25 -> **21/25** |
| sem6 documents | 28.4% -> **12.8%** | 27/40 -> 27/40 |

Fabrication fell on all three (2.3x, 7.8x, 2.2x). The score moved only where
the fabrication was load-bearing for the questions asked — sem_4's NUL bug
broke the exact receipt four questions targeted; sem5's gains came from the
retrieval fixes. **Cleaning summaries buys integrity; it buys points only
when the broken summary was in the answer path.** Keep both metrics.

The solo gate now hands over **two** files, not one (`LOCAL_SOLO_KEEP`). Its
founding premise — margin >=2.0 means the top hit is right 93% of the time —
does not hold on every corpus: on sem_4 it fired on 18 of 25 questions at
56% precision vs 86% on the ones it left alone, and the margin carried no
signal (16.97 put the wrong file first, 2.21 put the right one first). In
every failure the correct file sat at rank 2-4, already retrieved and then
discarded. sem_4: 16/25 -> 19/25. sem6: no regression.

**sem6 baseline is now 27/40, not 31/40.** Three things changed underneath
the older number (summary repair, gate width, keyword prefetch). The 27->27
before/after re-summarize was measured back to back on the same index and IS
clean; anything compared to 31/40 is not.

**Provider confound on sem6:** its index was built with CLOUD, this
re-summarize used LOCAL (owner asleep; the cloud route would have sent ~250
personal documents to OpenRouter). Prompt and provider changed together
there. But the `Jane Doe / DL1492` copying appears in CLOUD-written sem6
summaries too (`word_painting.pdf`, `SMOTE_ClassImbalance_Summary.md`), so
the copying was never a small-model-only failure.

### Operational lessons that cost real time tonight

1. **Env files must pin their Qdrant port.** Sourcing one after another let
   sem_4's endpoint persist into a sem6 run; both arms searched the wrong
   corpus (247 of 247 retrieved paths). Every env file now sets it and the
   driver asserts before touching a corpus.
2. **`sync_files_sync` discovers by walking the tree.** For /mnt/hardisk/sem6
   that is 7,345 files against the 392 the index holds — an 8-hour run that
   would redefine the corpus. Re-summarize scoped to the manifest instead
   (`/tmp/sem6_resum.py` pattern).
3. **Reap stray llama-servers before any GPU phase.** A zombie holding 2.9 GB
   made the next spawn fail and silently skipped 306 files of a re-summarize,
   and separately voided a whole eval arm at 1/25.
4. **Snapshot summaries before re-summarizing.** Doing so is what made the
   runaway sem6 run recoverable.

### What to do next

1. **Re-measure `college_data` on the Windows machine.** The sem6 numbers
   do not transfer; the *mechanisms* do, and bugs 1-4 are properties of the
   code and the llama-server build, not of the corpus. This is the single
   highest-value next action, and it may explain a large share of the
   {15, 11, 11} band.
2. Check whether the Windows CUDA b9049 build also ignores
   `response_format` (one curl; the answer decides how much of the gain
   transfers).
3. `Plans/Answer Quality Research Levers.md` — a literature review mapped
   to our failure classes, with the remaining levers (extract-then-write,
   MiniCheck as a verifier and as an independent eval judge, a
   grounding-trained small model in place of the 8B card) and pre-registered
   gates for each.
4. Nothing is committed. `git status` shows the full change set.

### Instrument notes

- `Evaluations/score_criteria.py` + `Evaluations/sem6/criteria.json` grade
  by pre-registered regex, so no assistant judgment enters the verdicts —
  the standing self-evaluation caveat does not apply to these numbers.
- `Evaluations/grounding_audit.py` scores any answers file for unsupported
  numbers and works retroactively on every run in `college_data/`.
- This machine: model weights at `/mnt/astavaknew/magpie-models`, Qdrant at
  `/mnt/astavaknew/magpie-qdrant` (start it from that directory, port 6433
  via `QDRANT__SERVICE__HTTP_PORT`), `MAGPIE_DATA_DIR=/mnt/hardisk/magpie-data`.
  The bundled llama-server there is CPU-only and missing its `.so.0`
  symlinks; a Vulkan build drives the RTX 3060 (31/31 layers) — point at it
  with `LLAMA_SERVER_PATH` + `LD_LIBRARY_PATH`.
- `LLAMA_SERVER_MODEL_PATH` / `LLAMA_SERVER_MMPROJ_PATH` now work
  (`_path_override`, previously tested-but-unimplemented) so weights already
  on disk are used instead of a second multi-GB download.
- The test suite could not be collected at all before today
  (`tests/inference/test_lfm_profiles.py` imported three names that never
  existed). It now runs: 796 passed, 15 failed — all 15 failing at HEAD too.

## RESUME HERE (2026-08-26): doc2query v3, mid-generation

Owner has a standing iterate-and-report mandate: pre-register a gate,
run, judge strictly, report, move to the next goal. Sequence state:

1. **DONE — routed map-reduce v1–v5 all 14/40 strict (= baseline).**
   Five configurations (LLM reduce top-5 / full-coverage / pure-code
   reduce / filter call / question-sandwich) — the 3B cannot assemble
   or filter multi-file findings; maps extract fine. Closed. Details +
   verdicts: REPORT.md "Routed answering" + `eval_answer_40__routed*`.
2. **DONE — transcripts: owner ruled KEEP** (cloud 0→7/12 on scanned).
3. **DONE — doc2query v3: gate FAILED on all three legs; removed.**
   686 questions generated and CACHED
   (`Evaluations/college_data/hype_questions_cache.json` — reuse it,
   generation never needs to re-run); global dedup 686→448; upserted;
   snapshot diff vs baseline: recall@5 33→29 (regression), rank-1 +0,
   sentinels still absent, and solo-gate margins eroded (q20 6.63→0).
   `--remove` executed (verified 0 hype points). Full table in
   REPORT.md. Conclusion: even deduped question points OUTVOTE summary
   points in RRF.
4. **DONE — doc2query v4 (weight 0.4) and v4.1 (rerank-only, weight
   1.0): both FAILED the gate; the doc2query line is CLOSED (3
   strikes).** Root cause: 3B question-generation quality — good
   questions are outnumbered by noise that embeds near everything.
   Search-side code stays (env-gated `MAGPIE_HYPE_WEIGHT`, default 0 =
   inert; main tier always excludes hype points), cache stays; revival
   path = stronger on-device generator (8B). Points removed.
5. **DONE — transcript index points (BM25-only, zero dense vector):
   FAILED the gate** (recall@5 33→32, Duke still absent for q40).
   Structural lesson, confirmed twice: the summaries pool is ZERO-SUM —
   additive points eat finite prefetch slots and displace real hits.
   Additive content needs its own collection/tier to be safe. Removed;
   `Evaluations/transcript_points.py` stays for a separate-tier design.
6. **IN FLIGHT — full-corpus transcription sweep** (58/248 at last
   check, resume-safe). After it completes: (a) grep transcripts for
   the MRV receipt (Everest/21,600 — q23/q24 diagnostic), (b) re-run
   the scanned-block (12q) local + cloud evals, and a full-40 LOCAL
   answer eval — measurement runs; transcripts are KEPT regardless.
   q20's FRB poster and the financial forms now have transcripts —
   expect reading-side gains where retrieval already lands (q20).
7. Retrieval iteration is EXHAUSTED for this index design; the
   measured big levers left: 8B model trial (owner-gated), separate
   transcript tier, margin-0.0 duplicate-file artifact card.
8. Lesson: NEVER run two llama-server jobs at once — 600s ReadTimeouts
   invalidated v5's first run and poisoned 15 cache entries (purged).
   Qdrant restart: run `<APP_DATA>\qdrant\qdrant.exe` from ITS OWN dir
   (default ./storage) — the repo binaries are 0-byte; the
   `qdrant_storage` env path is a DIFFERENT, empty store.

## Where the project stands

- **Shipped to `main` (through commit `afcdb1b`)**: anchor guarantee in
  rerank; provider-aware rewrite (local=raw, cloud=rewrite); solo gate
  (`search.gate_to_solo` — margin ≥ 2.0 sends the local model ONE file;
  comparative questions exempt); scoped SYNTHESIS MODE for comparative
  questions; provider-aware context budget + CPU prefill cap; RAM-tiered
  context window (`profiles._auto_n_ctx`); CUDA `-np 1`; installer
  dotenv fix; `MAGPIE_FORCE_PROVIDER` for eval harnesses.
- **Measured (strict binary, n=50: 40 tuning + 10 sealed held-out)**:
  local 15/50 (30%), cloud 18/50 (36%). Local was 0% three days prior
  (requests over the context window were rejected outright).
- **Key mechanism findings** (each verified by isolation tests):
  1. The local 3B reads a SINGLE correct file near-perfectly (text AND
     scanned images); distractor stacks are what destroy it.
  2. Search's top-hit margin over #2 predicts correctness: ≥2.0 margin
     = right file 93% (121-trace replay) → hence the solo gate.
  3. The 3B rewriter REPLACES questions rather than cleaning them;
     hybrid search absorbs typos natively → local runs raw.
  4. Cloud cannot see scanned documents at all (images never leave the
     machine, by privacy design) — 0/12 on the scanned block.

## IN FLIGHT, INTERRUPTED — resume this first

**Transcribe-at-index experiment** (vision transcripts for scanned PDFs):

- Hook is LIVE in `src/content.py` (`transcript_for`): scanned PDF with
  a transcript → answer stage reads the transcript text; without → the
  old pixel path. Ships in main.
- Transcriber: `Evaluations/transcribe_index.py` (resume-safe; skips
  existing transcripts; `--remove` deletes all). ~26 of an estimated
  60-100 scanned files were transcribed before cancellation, saved to
  `<APP_DATA_DIR>/transcripts/` on the ORIGINAL machine.
- **RESOLVED (2026-08-26): owner ruled KEEP.** The measured result:
  local 1/12 → 2/12 (pre-registered gate ≥5 FAILED), cloud 0/12 →
  **7/12** (transcripts are cloud's only sight into scanned docs; no
  image leaves the machine). Gate was mis-specified (never anticipated
  cloud being the win); escalated per house rules, owner chose keep.
  Remaining work: finish the full-corpus sweep (resume-safe, below),
  then consider indexing transcript text (retrieval margin raiser) and
  a digit-verification v2 pass (garbles cost cloud ~3 strict points).
- Resume command (repo root, all resume-safe):
  ```
  uv run python Evaluations/transcribe_index.py --corpus "<corpus>/second chance"
  uv run python Evaluations/transcribe_index.py --corpus "<corpus>/supplements"
  uv run python Evaluations/transcribe_index.py --corpus "<corpus>/advance personal statement"
  uv run python Evaluations/run_eval.py --provider local --no-rewrite \
      --questions Evaluations/college_data/eval_college_data_scanned.json \
      --answers Evaluations/college_data/eval_answer_scanned__local_transcripts.json
  uv run python Evaluations/run_eval.py --provider openrouter \
      --questions Evaluations/college_data/eval_college_data_scanned.json \
      --answers Evaluations/college_data/eval_answer_scanned__openrouter_transcripts.json
  ```
  Then judge strictly vs ground truths, update REPORT.md, execute the gate.

## Machine-bound data (DOES NOT travel with the repo — copy manually)

All gitignored because it contains the owner's personal information.
To continue on a new computer, copy from the old machine:

1. `Evaluations/college_data/` — the ENTIRE eval instrument: 40+10
   question sets with ground truths, every judged answer file, REPORT.md.
   Without this the eval history is gone.
2. `<APP_DATA_DIR>/transcripts/` — banked vision transcripts (optional;
   they regenerate in ~1-2h GPU).
3. `.env` — API keys + LLAMA_SERVER_GPU / LOCAL_SOLO_MARGIN etc.
4. The corpus itself (owner's documents) + the Qdrant index
   (`<APP_DATA_DIR>/qdrant/storage`) or re-index fresh.
5. `<APP_DATA_DIR>` generally (manifest, summaries) if avoiding a
   ~50-min re-index. APP_DATA_DIR: `%LOCALAPPDATA%\magpie\Magpie` on
   Windows.

New machine setup: `uv sync`; `python -m src.tools.install_llama_server`
(reads LLAMA_SERVER_GPU from .env — set `cuda-12.4` if NVIDIA); start
Qdrant (`scripts/qdrant_up.py` or the binary directly, port 6433).

## House rules the numbers were earned under (keep them)

1. **Strict binary correctness** — partial answers are wrong. The owner
   ruled this explicitly; "partial+" is retired from headlines.
2. **One variable per experiment; pre-register the gate before running.**
3. **n=3 medians** for any claim within ±2 questions (cloud free-tier
   flaps run-to-run on identical prompts — measured).
4. **Held-out set stays sealed** — `eval_college_data_heldout.json` is
   never consulted while tuning; final verdicts only.
5. Local and cloud are separate products — no router/blending (owner
   decision, privacy branding). Cloud never receives images.
6. Failed experiments get `--remove`d from the live index and documented
   in REPORT.md. doc2query spikes v1/v2 and knob trials (temp 0.2,
   top_k 3) are all measured-and-rejected — do not retry them as-is.

## Open cards, ranked (details in Plans/Local Answer Quality Plan.md)

1. Finish transcribe-at-index (above) — biggest measured-adjacent jump.
2. Fix the false "password-protected" PDF check in `src/content.py` —
   flags UNencrypted files (two confirmed); q23 in the eval probes it.
3. Enumeration/cross-doc answering — local lists 1 of 4 recommenders.
4. Grounding check for local fabrications (quote-or-refuse).
5. doc2query with CROSS-FILE dedup (evidence packaged in REPORT; needs
   global near-duplicate question detection — per-file filtering failed).
6. Mangled-entity typos break both retrieval modes → fuzzy keyword
   matching (design only).
7. 8B local model trial — owner has deferred; ask before running.
8. Vision-tier phase 2: photo questions with `--fast`.

## Gotchas that cost hours

- Qdrant does NOT autostart in dev. Port 6433. If retrieval returns 0
  hits with a qdrant_client version warning, it's down.
- Background jobs die silently with the assistant session — transcripts
  and eval answers are incrementally saved, so rerunning resumes; always
  check `done:` lines in task logs before trusting a sweep finished.
- `settings.json` (APP_DATA_DIR) is the source of truth over env for
  provider/temperature/rewrite; `MAGPIE_FORCE_PROVIDER` is the eval
  override. run_eval sets it from `--provider`.
- The eval judge is the assistant itself — owner wants Mridul to
  blind-check ~10 verdicts before any external claims.
- Owner communication: ADHD style — lead with the action/number, tables
  over prose, one next step at the end (see the i-have-adhd hook).

## Session: PhyLL corpus + four install-path bugs (2026-08-28)

Ran a fourth corpus — `/mnt/hardisk/PhyLL`, a scientific repo of LaTeX math
docs, Python and figures — chosen because none of the previous fixes were
tuned on it and its structure re-tests every open failure class (`math_docs/`
and `ascii_docs/` document the same nine scripts; three near-duplicate
`*stirred_window*` folders). Full write-up: `Evaluations/phyll/REPORT.md`.

**Result: 17/25 pre-registered (19/25 with two defective rules corrected).**

### The finding that should drive the next work

| metric | value |
| --- | --- |
| recall (key file in top-k) | 18/24 (75%) |
| **rank-1 (key file first)** | **6/24 (25%)** |

Retrieval finds the right document and then ranks a near-duplicate sibling
above it. With `LOCAL_SOLO_KEEP=2` the gate routinely forwards two wrong
siblings while the right file sits at rank 3+. Every retrieval loss had this
shape, and the reader answered confidently from the wrong sibling with real,
correctly-copied numbers (q23 quoted `10.17 / 14.72` from `scatter_pick.py`
for a question whose answer lives in `hardware/README.md`). **Sibling
disambiguation, not summary fabrication, is now the binding constraint.**

### Four bugs that ship to users, all found by running on a fresh machine path

1. **Both index tiers bypassed the rules gateway.** `find_supported_files`
   and `_iter_fast_files` were bare `root.rglob("*")`: the user's
   `indexing_rules.json` was ignored, dot-folders were walked, and **one
   unreadable directory aborted the whole sync** (`OSError: [Errno 5]`).
   This is also what caused the 7,345-file sem6 runaway. Both now delegate to
   `src.ingest.walker.find_candidates` — the walker the app already uses.
   Regression tests: `tests/stage1/test_find_supported_files.py`.
2. **`torchvision` was not routed to the pytorch-cpu index.** `torch` was;
   `torchvision` resolved from PyPI built against the CUDA torch ABI, so
   `torchvision::nms` never registered and `transformers` failed with
   "Could not import module 'PreTrainedModel'" — a silently dead cross-encoder
   reranker. Every `uv sync` re-broke it; this had already cost two prior
   sessions. Fixed in `pyproject.toml` (both pinned to one index, no version
   bump — the relock that tried to drag torch 2.10 -> 2.11 was reverted).
3. **llama-server's versioned `.so.0` names are lost on NTFS.** The release
   tarball ships `.so.0 -> .so` symlinks; extracting into a data dir on an
   ntfs-3g mount drops them, so the binary dies at spawn with
   `libllama-common.so.0: cannot open shared object file`. Any user whose
   data dir is on an external drive hits this. Worked around by materialising
   the versioned names; **a real fix belongs in the installer.**
4. **A fresh install pins `temperature: 0.7`.** `Defaults.temperature` is a
   hard `0.7` and the v1->v2 migration only nulls it for *existing* files, so
   new installs write it explicitly — and `_answer_temperature` treats an
   explicit value as "the user pinned it" and honours it even on local.
   Measured: sem_4 and sem5 both carry `0.7`; only sem6 has `None`.
   **sem_4's 19/25 and sem5's 21/25 were therefore measured at 0.7, not the
   0.1 we believed.** A 0.1-vs-0.7 A/B on PhyLL moved one question (17 vs 16),
   which at n=1 is noise — the config bug is real, a large quality effect is
   not demonstrated. Those two corpora should be re-measured.

### Operational note

`pkill -f llama-server` matches its own shell command line and kills the
shell. Use `pgrep -f '[l]lama-server'` and skip `$$`.
