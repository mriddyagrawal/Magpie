# Phase 2 — Backend leak-scrub

> **What this doc is.** A frozen-in-time record of the work done
> 2026-04-27 to remove every implementation detail that was leaking
> from the FastAPI server into the GUI surface — model names, LLM
> provider strings, infrastructure labels, raw exception text. The
> CLI keeps all its tracing (it's the dev's debugger). The GUI gets
> a sanitized, product-shaped surface.
>
> Read this when: you're touching `src/server.py` or any frontend
> code that consumes its responses, or before adding a new field to
> any HTTP response. The principle is *user knows the product, nothing
> else.*

---

## What was leaking

Three separate channels, each fixed independently.

### 1. `/status` exposed the entire stack

```json
// BEFORE — what /status used to return
{
  "llm_provider": "openrouter",
  "llm_model": "google/gemma-4-26b-a4b-it:free",
  "qdrant_provider": "cloud",
  "indexed_count": 19355
}
```

The frontend's `StatusPill` rendered all of it:

> `gemma-4-26b-a4b-it:free · 19,355 indexed · openrouter ▸ qdrant cloud`

Anyone glancing at the corner of the window learned: which embedding
model we use, which LLM provider we route through, which model variant,
where the vector store lives. Free reverse-engineering aid.

```json
// AFTER — only product-shaped facts
{
  "ready": true,
  "indexed_count": 19355,
  "version": "0.1.0"
}
```

```jsx
// AFTER — StatusPill shows one fact a non-tech user cares about
"19,355 documents indexed"
```

### 2. `/query` exposed raw exceptions to the client

```json
// BEFORE — internal error details leak straight through
{
  "detail": "pipeline error: ModelHTTPError: 429 from openrouter.ai - rate limit exceeded"
}
```

`ModelHTTPError` reveals we use a typed HTTP-error class (PydanticAI
giveaway). `openrouter.ai` reveals the upstream provider. `429 rate
limit` is implementation detail. None of it tells the user anything
they can act on.

```python
# AFTER — error mapper catches everything, returns user-safe strings;
# real exception text goes to stderr where only the dev sees it.
def _user_facing_error(exc: Exception) -> tuple[int, str]:
    name = type(exc).__name__
    text = str(exc)
    print(f"[server] internal error {name}: {text}", file=sys.stderr)

    if "429" in text or "rate" in text.lower() or "quota" in text.lower():
        return 503, "Service is busy right now. Try again in a few seconds."
    if "401" in text or "403" in text or "unauthor" in text.lower():
        return 401, "Account isn't set up yet. Check your settings."
    if name in ("ConnectionError", "TimeoutError"):
        return 503, "Can't reach the network. Check your connection."
    if name == "FileNotFoundError":
        return 404, "Couldn't find that file anymore."
    if "qdrant" in text.lower() or "collection" in text.lower():
        return 503, "Search is starting up. Try again in a moment."
    return 500, "Something went wrong. Please try again."
```

Result for the same incident:

```json
// AFTER — the user sees this
{ "detail": "Service is busy right now. Try again in a few seconds." }

// while server log shows
[server] internal error ModelHTTPError: 429 from openrouter.ai - rate limit exceeded
```

User has actionable advice (*"try again"*); we keep full debug detail
for ourselves.

### 3. Library noise blasted the dev terminal AND any forwarded UI logs

```text
# BEFORE — what every server startup printed to stderr
/.../qdrant_remote.py:280: UserWarning: Qdrant client version 1.17.1 is incompatible
with server version 1.12.4. Major versions should match...
/.../torch/cuda/__init__.py:1007: UserWarning: Can't initialize NVML
Loading weights: 100%|██████████| 490/490 [00:24<00:00, 20.23it/s]
Loading weights: 100%|██████████| 448/448 [00:01<00:00, 422.44it/s]
```

These don't appear in production (Tauri swallows sidecar stderr), but
they're scary in dev and could be exposed to users via Tauri's debug
mode. Suppressed at the module-import boundary so they never fire:

```python
# src/server.py — at the very top, BEFORE importing torch / qdrant_client
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
warnings.filterwarnings("ignore", category=UserWarning, module="qdrant_client")
warnings.filterwarnings("ignore", category=UserWarning, module="torch.cuda")
```

## Bonus fix landed in the same phase: ColPali default off in `/query`

The CLI's `.fast off` default skips the ColPali visual tier entirely —
saves the ~25-second cold-load on first query. The FastAPI server
didn't have parity: every `/query` against a fresh server triggered the
full ColPali load whether the question needed visual search or not.

```python
# src/server.py — before
async def query(req: QueryRequest):
    result = await ask(req.question, top_k=req.top_k, rewrite=req.rewrite)
    # → run_search default = visual tier ON → ColPali load, ~25s cold

# after — visual search becomes opt-in via fast=true in the request body
class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    rewrite: bool = False
    fast: bool = False              # NEW — matches CLI's `.fast off` default

async def query(req: QueryRequest):
    result = await ask(req.question, top_k=req.top_k, rewrite=req.rewrite,
                       fast=req.fast)
```

Wall-clock impact: first `/query` after `just serve` drops from ~35
sec → ~10 sec. The remaining ~10 sec is the LLM round-trip itself,
not local work — same latency as ChatGPT.

## End-to-end with curl

### Before Phase 2 (what the user used to see)

```bash
$ curl -s http://127.0.0.1:8765/status | jq
{
  "llm_provider": "openrouter",
  "llm_model": "google/gemma-4-26b-a4b-it:free",
  "qdrant_provider": "cloud",
  "indexed_count": 19355
}
```

```bash
# When OpenRouter rate-limits us
$ curl -s -X POST http://127.0.0.1:8765/query -d '{"question":"..."}' | jq
{ "detail": "pipeline error: ModelHTTPError: 429 from openrouter.ai" }
```

### After Phase 2

```bash
$ curl -s http://127.0.0.1:8765/status | jq
{
  "ready": true,
  "indexed_count": 1012,
  "version": "0.1.0"
}
```

```bash
# Same rate-limit incident, user-safe message
$ curl -s -X POST http://127.0.0.1:8765/query -d '{"question":"..."}' | jq
{ "detail": "Service is busy right now. Try again in a few seconds." }

# while in `just serve` terminal:
# [server] internal error ModelHTTPError: 429 from openrouter.ai - rate limit exceeded
```

## Files touched

| File | Change |
|---|---|
| [src/server.py](../src/server.py) | Strip `/status` to `{ready, indexed_count, version}`; add `_user_facing_error` mapper; suppress library noise at import time; add `fast=False` field to `QueryRequest` |
| [src/pipeline.py](../src/pipeline.py) | Add `fast: bool = False` parameter to `ask()` and `ask_sync()`; thread through to `run_search` as `skip_fast=not fast` |
| [src/stage2/search.py](../src/stage2/search.py) | Already had `skip_fast` param from earlier; no change |
| [frontend/src/types.ts](../frontend/src/types.ts) | `StatusResponse` schema → `{ready, indexed_count, version}` |
| [frontend/src/components/StatusPill.tsx](../frontend/src/components/StatusPill.tsx) | Render only `"N documents indexed"`; drop model + provider strings |
| [justfile](../justfile) | Add `serve` and `serve-dev` recipes |

Tests: 409 passing (no regressions).

## What stays unchanged

- The CLI (`ns`) keeps every bit of its trace output: `query_class=list_all`,
  `top_k 5→30`, `Loading weights`, retrieved-document table with tier
  column, etc. The CLI is a developer tool — full visibility is the
  feature.
- All file-preview / file-open / file-reveal endpoints — they expose
  paths but that's the user's own filesystem; they know it.
- The retrieval logic (Qdrant, embedding, ColPali, LLM call) — pure
  internals, untouched.

## Acceptance test (the principle holding)

> A friend installs Magpie, uses it for an hour, and at the end you
> ask: *"What language is the backend written in? Which AI model
> does it use? Is there a vector database under the hood?"* If they
> can't answer any of those questions from anything they saw in the
> UI, you're done.

Backend changes verified via curl: ✓
Frontend StatusPill rebuilt: ✓ (rendering verified — pending
graphical session for full Tauri test)
Error path: ✓ (mapper unit-tested in smoke runs)

The Tauri visual verification was deferred — see Phase 2 status notes
in chat. Everything visible to the GUI is now sanitized at the API
boundary.

## What this unlocks

- **Tauri E2E from any session** — the data flowing into the React
  components is already user-shaped, no further frontend filtering
  needed.
- **Phase 2.5 cloud server** — the same response-shape contract carries
  over: any error mapping, any tech detail scrubbing already done at
  the local-sidecar boundary stays applied at the cloud-server boundary.
- **Phase 3 Windows installer** — when packaging, no risk that a
  diagnostic field accidentally surfaces; the surface is already minimal.

## Cross-references

- [src/server.py](../src/server.py) — main server, `_user_facing_error`,
  `/status`, `/query`
- [frontend/src/components/StatusPill.tsx](../frontend/src/components/StatusPill.tsx) —
  the most-visible leak, now sanitized
- [IO - Phase 1.md](IO%20-%20Phase%201.md) — the path-portability work
  that landed in the same session
- [IO - Phase 2.5.md](IO%20-%20Phase%202.5.md) — what Phase 2's
  sanitization patterns inform on the cloud server
- [IO - Repo Structure.md](IO%20-%20Repo%20Structure.md) — the
  no-tech-leak product principle
