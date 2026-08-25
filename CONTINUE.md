# CONTINUE.md — session handoff (written 2026-08-25)

For the next assistant/instance continuing Magpie's answer-quality work.
Read this top to bottom before doing anything. The prior session's full
measured trail is in `Evaluations/college_data/REPORT.md` (LOCAL-ONLY,
gitignored — see "machine-bound data" below).

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
- **Pre-registered gate (do not renegotiate after seeing results):**
  re-run the 12-question scanned block
  (`Evaluations/college_data/eval_college_data_scanned.json`) on local
  + cloud AFTER transcription covers `second chance/`, `supplements/`,
  `advance personal statement/`. KEEP if local ≥ 5/12 (baseline was
  1/12) with no text-question regression; else `--remove`.
- Registered predictions (score them): local 6-8/12, cloud 5-8/12.
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
