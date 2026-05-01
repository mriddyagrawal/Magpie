# Phase 2.5 Step 4 — The three LLM endpoints

> **What this doc is.** Step 4 of Phase 2.5, explained in plain words.
> What we built, what it does, and what the desktop will eventually
> send to it. No code unless an example makes the idea clearer.
>
> Read this when: you're trying to remember which endpoint does what,
> or you want to understand the cloud server's surface before touching
> the desktop side in step 5.
>
> Sibling: [IO - Phase 2.5.md](IO%20-%20Phase%202.5.md) covers all
> seven steps at a glance.

---

## What this step actually solves

Until step 4, the desktop app was the only place that knew how to talk
to an LLM. The desktop holds the prompts, builds the agent, calls
OpenRouter, parses the response. That means **the prompts ship in the
desktop binary** — anyone unpacking the .exe can read them.

Step 4 moves all of that work to a server *you* run. The desktop will
soon stop calling OpenRouter directly; instead it'll call **your**
server, send a question, and get an answer back. The prompts, the
provider choice, the API key — all stay on your side.

This step doesn't yet *flip the switch* on the desktop (that's step 5).
What we did in step 4: **built the cloud endpoints so the desktop has
something to call when it's ready.**

## The three things the cloud LLM does

The desktop needs three different LLM calls. Each one gets its own
endpoint on the cloud server:

### 1. `POST /llm/rewrite` — *"polish this question"*

The user types something like *"what's my flight stuff"*. That's
ambiguous and BM25-unfriendly. The rewrite step asks an LLM to expand
the question into a search-engine-friendly form: a long keyword-rich
query plus a list of likely terms.

| Input | Output |
|---|---|
| *"what's my flight stuff"* | `query: "list all flight receipts, airline confirmations, e-tickets, and travel itineraries..."` <br> `keywords: ["flight", "airline", "receipt", "itinerary", "boarding pass", ...]` |

This goes back to the desktop, which uses it to search Qdrant. **The
LLM never sees the user's documents** — only the question.

### 2. `POST /llm/answer` — *"read these snippets, answer the question"*

After the desktop searches Qdrant, it has a handful of relevant files.
It reads them, pulls out the most relevant text, and sends *just those
snippets* to the cloud:

| Input | Output |
|---|---|
| Question: *"how much did I spend on flights"* <br> Snippets: <br> • `Flight DL1492 Atlanta → Hartford, $247.50` <br> • `Avelo Yale-GSP, $170.18` <br> • `American Airlines CLT-BOS, $798.00` | *"You spent $1,215.68 on flights total, across three trips: Delta DL1492 ($247.50), Avelo Yale-GSP ($170.18), and American Airlines CLT-BOS ($798.00)."* <br> sources: `["DL1492.pdf", "Flight Yale - GSP Receipt.pdf", "trip_CLT-BOS.pdf"]` |

The user's full files **never go to the cloud** — only the small
relevant chunks the desktop already extracted. Privacy: ✓.

### 3. `POST /llm/summarize` — *"distill this file into searchable form"*

When the desktop is indexing a critical file (a receipt, contract, bank
statement), it asks the cloud to write a structured summary that gets
stored locally in Qdrant.

| Input | Output |
|---|---|
| filename: `dumplings_receipt.pdf` <br> text: *"MoMo Pasal Order #5 placed on 3/20/2026, total $184.52..."* | `title: "MoMo Pasal Order #5 — $184.52"` <br> `summary: "Restaurant receipt from MoMo Pasal..."` <br> `keywords: ["receipt", "restaurant", "momo", "pasal"]` <br> `identifiers: ["#5", "$184.52", "3/20/2026"]` |

The structured output then gets embedded and indexed locally on the
user's machine. The cloud sees the file's text *once* (during ingest)
and never again — the result is stored on the user's device.

## What we built (the actual files)

Five files in `server/magpie_server/`:

| File | What it is |
|---|---|
| `schemas.py` | The shape of every request/response — what the desktop sends, what the cloud returns. Pydantic models, fully typed. |
| `llm_client.py` | The thing that talks to OpenRouter. One function, `build_agent(prompt, output_type, model)`, returns a typed agent. |
| `llm_routes.py` | The three endpoints. Each one composes the user message, calls the agent, returns a typed response. |
| `main.py` (edited) | Now imports `llm_routes.router` and mounts it under `/llm/`. |
| `pyproject.toml` (edited) | Adds `pydantic-ai` so the agent code can run. |

That's about 280 lines of new code total. Most of it is type definitions; the actual orchestration is short because pydantic-ai handles the LLM provider details.

## How a `/llm/rewrite` call actually flows

For a single curl from your terminal hitting your local cloud server:

```
You run:
  curl -X POST localhost:8000/llm/rewrite \
       -H "Authorization: Bearer alice-test123" \
       -d '{"question":"flights to Boston"}'

  ┌─────────────────────────────────────┐
  │ FastAPI receives the request        │
  └────────────┬────────────────────────┘
               ▼
  ┌─────────────────────────────────────┐
  │ Auth dependency checks bearer token │
  │   → matches "alice-test123" ✓       │
  └────────────┬────────────────────────┘
               ▼
  ┌─────────────────────────────────────┐
  │ Endpoint composes the user message: │
  │   "Question: flights to Boston"      │
  └────────────┬────────────────────────┘
               ▼
  ┌─────────────────────────────────────┐
  │ build_agent loads:                   │
  │   • REWRITE_PROMPT (from prompts.py) │
  │   • SearchQuery output schema        │
  │   • OpenRouter API key (from .env)   │
  └────────────┬────────────────────────┘
               ▼
  ┌─────────────────────────────────────┐
  │ HTTPS to openrouter.ai/api/v1/...    │
  │   → Kimi processes the prompt        │
  │   → returns structured JSON          │
  └────────────┬────────────────────────┘
               ▼
  ┌─────────────────────────────────────┐
  │ pydantic-ai validates the JSON       │
  │   matches SearchQuery → safe to use  │
  └────────────┬────────────────────────┘
               ▼
  ┌─────────────────────────────────────┐
  │ Endpoint wraps with prompt_version   │
  │ and returns RewriteResponse          │
  └────────────┬────────────────────────┘
               ▼
  Curl receives:
    {
      "query": "flights to Boston, airline tickets, ...",
      "keywords": ["flight", "Boston", "airline", ...],
      "prompt_version": 1
    }
```

Total wall-clock: ~3-8 seconds (depends on the LLM provider's latency,
not anything we control).

## Why each piece exists

### Why pydantic-ai instead of raw HTTP?

pydantic-ai gives us **schema-validated outputs**. We tell it
*"the LLM must return a SearchQuery with `query` (string) and
`keywords` (list of strings)"*; it enforces that. If the LLM returns
malformed JSON, pydantic-ai catches it and we return a clean error to
the desktop instead of crashing. The desktop already uses pydantic-ai;
keeping the same library on both sides means agent behavior is
identical.

### Why three endpoints instead of one big `/llm`?

Three reasons:
1. **Different output shapes.** Rewrite returns a SearchQuery. Answer
   returns an Answer. Summarize returns a FileSummary. One endpoint
   would need a `mode` field and a union response — uglier.
2. **Different rate-limiting later.** A single user might rewrite 100
   queries an hour but answer only 20. Per-endpoint quotas are easier.
3. **Different model choices later.** You might want Kimi for
   answering but a cheaper Gemini for rewriting. Per-endpoint model
   config is already in `settings.py`.

### Why `prompt_version` in every response?

When you tweak a prompt and ship the change, *every existing desktop
app starts using the new prompt the next time it calls the cloud* — no
app update needed. But you want to know *which version* answered each
query, so when a user complains *"this answer is worse than last
week"*, you can check whether they got prompt v3 or v4. The version is
just an integer in `prompts.py:PROMPT_VERSIONS` that you bump
manually.

### Why does the friendly-error mapper exist again here?

The cloud server has its own error mapper (separate from the desktop
sidecar's). When OpenRouter rate-limits us, the user sees *"Service is
busy right now"* — not *"ModelHTTPError: 429 from openrouter.ai"*. The
real error gets logged to the server's stderr where you can debug it.
Same principle as Phase 2: the user knows the product, never the stack.

## What this step does NOT yet do

| Thing | Status | Where it gets done |
|---|---|---|
| Desktop calls these endpoints | ❌ not yet | step 5 — adds `magpie-cloud` provider in `src/llm.py` |
| Vision / OCR for scanned PDFs | ❌ not yet | post-beta — current endpoints are text-only |
| Per-user rate limiting | ❌ not yet | production hardening, not beta |
| Prompt A/B testing | ❌ not yet | use `prompt_version` field once we have multiple versions |
| Real deployment | ❌ not yet | step 7 — Dockerfile + fly.io |

## Smoke-test results (today)

- ✓ `/health` returns ok
- ✓ `/llm/rewrite`, `/llm/answer`, `/llm/summarize` all reachable
- ✓ Auth blocks unauthorized when invite codes are configured
- ✓ Auth allows anonymous on localhost when no codes set (dev convenience)
- ✓ Missing `OPENROUTER_API_KEY` → friendly 500 *"Something went wrong"*, real error in stderr
- ✓ All four prompt-parity tests pass
- ✓ Server-only venv installs cleanly (~80 MB; no torch, no qdrant)

## End-to-end test you can run today

Once you set `OPENROUTER_API_KEY` in `server/.env`:

```bash
just cloud-serve

# In another terminal:
curl -s -X POST http://127.0.0.1:8000/llm/rewrite \
  -H "Content-Type: application/json" \
  -d '{"question":"what flight receipts do I have"}'
```

Expected: a `RewriteResponse` JSON with a beefier query and 5-12
keywords. Same kind of output the desktop currently gets when it calls
OpenRouter directly — just routed through your server now.

## What this unlocks

| Next step | What it needs from step 4 |
|---|---|
| **Step 5** — desktop calls cloud | The three endpoints to exist, with stable schemas. ✓ |
| **Step 6** — local end-to-end test | Local cloud server reachable on port 8000. ✓ |
| **Step 7** — fly.io deploy | A working FastAPI app to put in a Dockerfile. ✓ |

So step 4 is the **foundation** — the three URLs every later step relies on. They work; the schemas are typed; failure modes return user-safe errors. We're ready for step 5.

## Cross-references

- [server/magpie_server/llm_routes.py](../server/magpie_server/llm_routes.py) — the three endpoints
- [server/magpie_server/schemas.py](../server/magpie_server/schemas.py) — request/response shapes
- [server/magpie_server/llm_client.py](../server/magpie_server/llm_client.py) — pydantic-ai wrapper for OpenRouter
- [server/magpie_server/prompts.py](../server/magpie_server/prompts.py) — the IP that lives only on the cloud
- [IO - Phase 2.5.md](IO%20-%20Phase%202.5.md) — overview of all Phase 2.5 steps
- [IO - Phase 2.md](IO%20-%20Phase%202.md) — the desktop sidecar's no-tech-leak surface, same principle applied here
