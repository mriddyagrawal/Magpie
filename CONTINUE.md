# CONTINUE.md — session handoff (updated 2026-08-26)

For the next assistant/instance continuing Magpie's answer-quality work.
Read this top to bottom before doing anything. The prior session's full
measured trail is in `Evaluations/college_data/REPORT.md` (LOCAL-ONLY,
gitignored — see "machine-bound data" below).

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
