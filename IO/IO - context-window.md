# IO — Local model context window (auto-sizing)

**Date:** 2026-08-24
**Files:** `src/inference/profiles.py` (`_auto_n_ctx`), `src/answer.py` (context
budget), `src/inference/llama_server_pool.py` (`-np 1`), `.env`

## The incident that led here

Local-provider answers returned "answer not found" for every multi-source
question while the cloud provider answered fine. The local model was never
broken — llama-server **hard-rejects any request larger than its context
window**, and the answer step was assembling 24–52K-token prompts
(5 files × 25K chars content + 10K chars summary) against a 16,384-token
window. The rejection was surfaced to the user as "answer not found".

Log signature (`bootstrap-*.log`):

```
E srv send_error: ... error: request (45808 tokens) exceeds the available
context size (16384 tokens), try increasing it
```

A related config bug multiplied the pain: llama-server was spawned without
`-np`, so its default parallel slots SPLIT the 16K window (~4K per slot) —
too small to decode a single image, producing the "failed to find free space
in the KV cache" → "failed to decode image" crashes on 8 files during
indexing.

## What changed

1. **`-np 1`** in `llama_server_pool._build_argv` — one slot, full window.
   Concurrent requests queue server-side; CPU throughput unchanged.
2. **Answer-step context budget** (`src/answer.py:_context_budget_chars` /
   `_trim_blocks_to_budget`) — local answers now measure the prompt before
   sending: best-ranked sources kept whole, the block that crosses the line
   is truncated, dropped files are named in the prompt so the model says
   "these exist but weren't read" instead of denying them. Cloud providers
   are unaffected (budget returns `None`).
3. **RAM-tiered auto window** (`profiles._auto_n_ctx`, keyed off TOTAL RAM
   via psutil so the size is stable across runs):

   | Total RAM | Window |
   |---|---|
   | < 8 GB | 8,192 |
   | 8–15 GB | 16,384 |
   | 16–31 GB | 32,768 |
   | ≥ 32 GB | 49,152 |

   Boundaries sit under nominal sizes (15/30) because the OS reports total
   minus hardware reservations (a "16 GB" machine reports ~15.4).
   49K is the deliberate ceiling: Liquid does not recommend LFM2.5-3B for
   long-context reasoning, KV RAM is reserved up front at spawn, and a full
   window on CPU means minutes of prompt-reading before the first token.

## Rollback

- **Pin the window on one machine:** set `LOCAL_N_CTX=16384` in `.env`
  (an explicit value always beats the auto-sizing).
- **Kill auto-sizing entirely:** in `profiles.py`, change the `ctx_size=`
  line back to `int(os.environ.get("LOCAL_N_CTX", DEFAULT_N_CTX))`.
- **Revert the answer budget:** delete the `_budget` block above "Assemble
  the chat message" in `src/answer.py` (the helpers then go dead but are
  harmless). Do NOT revert `-np 1` unless also reverting to small windows —
  large windows split across default slots re-create the image crashes.

## Watch for

- Local answers noticeably slower after a RAM upgrade → the tier jumped;
  pin `LOCAL_N_CTX` lower.
- `MemoryError` / model spawn failures on low-RAM machines → tiers may need
  lowering; check what `_auto_n_ctx` picked (llama-server logs the `-c`
  value in its spawn line in `bootstrap-*.log`).
