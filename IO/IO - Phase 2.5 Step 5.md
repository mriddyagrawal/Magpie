# Phase 2.5 Step 5 — Desktop calls Magpie Cloud

> **What this doc is.** Step 5 of Phase 2.5 — the desktop's
> `magpie-cloud` provider that routes every LLM call through your
> server instead of OpenRouter directly. Plain words + diagrams.
>
> Read this when: you're debugging cloud-mode behavior, deciding
> whether a feature should run client- or server-side, or explaining
> the architecture to a teammate.

---

## What this step did

Before step 5, every LLM call from the desktop went **direct to
OpenRouter** using whatever API key was in the user's `.env`. That
worked for your dev environment but couldn't ship to users —
distributing the .exe meant either bundling your API key (you'd pay
for everyone, no rate limit per user) or asking each user to get
their own (friction, no IP protection).

After step 5, the desktop has a **third provider option**:
`LLM_PROVIDER=magpie-cloud`. When set, all LLM calls go through your
server — which holds the prompts, the API key, and the model choice.
The user just has an invite code.

The shipped beta installer will set this provider as default. Users
never see "OpenRouter" or "Kimi" anywhere.

---

## The data flow — who sees what, and where

### What the user actually does (their mental model)

```
1. Download Magpie-Setup.exe
2. Install (one click, no admin)
3. Open Magpie
4. Paste invite code from email          ← only friction point
5. Pick documents folder
6. Type question, get answer
```

That's the entire user-facing flow. They never type an API key, never
see a model name, never know OpenRouter exists.

### What's actually happening under the hood (cloud mode)

```
End user (your friend Alice)
    │
    │ pastes invite code "alice-N7yLxQ4mPkR" in settings
    ▼
┌───────────────────────────────────────────────────────────┐
│ Magpie.exe on Alice's laptop                              │
│ ─────────────────────────────────────────────────────────  │
│ • Reads Alice's local files (PDF, DOCX, etc.)              │
│ • Embeds her question locally (MiniLM ~90 MB, bundled)     │
│ • Searches local Qdrant index (her own data)               │
│ • Reads top-k retrieved files for snippets                 │
│ • Sends question + ~8 KB snippets per file to:             │
└─────────────┬─────────────────────────────────────────────┘
              │ HTTPS POST /llm/answer
              │ Authorization: Bearer alice-N7yLxQ4mPkR
              │ body: {question, snippets[], history}
              ▼
┌───────────────────────────────────────────────────────────┐
│ YOUR magpie-cloud server (e.g. magpie.fly.dev)            │
│ ─────────────────────────────────────────────────────────  │
│ • Validates Alice's invite code ✓                          │
│ • Loads ANSWER_PROMPT (server-side, hidden from .exe)      │
│ • Composes prompt + question + snippets                    │
│ • Calls OpenRouter using YOUR API key:                     │
└─────────────┬─────────────────────────────────────────────┘
              │ HTTPS POST openrouter.ai/api/v1/chat/completions
              │ Authorization: Bearer sk-or-v1-YOUR-DEV-KEY
              │ body: {model: "moonshotai/kimi-k2:free",
              │        messages: [system_prompt, user_msg]}
              ▼
┌───────────────────────────────────────────────────────────┐
│ OpenRouter / Kimi / Claude (whichever model YOU chose)    │
│ • Charges YOUR OpenRouter account                          │
│ • Returns generated answer                                 │
└─────────────┬─────────────────────────────────────────────┘
              │ JSON response
              ▼
        magpie-cloud (server)
              │ {answer, sources_used, prompt_version}
              ▼
        Magpie.exe (Alice's laptop)
              │ renders the answer in the Tauri window
              ▼
            Alice sees: "You spent $1,215.68 on flights..."
```

### Who knows what — billing edition

| Party | What they know about Alice's request |
|---|---|
| **Alice** | She typed a question, got an answer |
| **Alice's OpenRouter account** | Doesn't exist — Alice has no account there |
| **YOUR magpie-cloud server** | Sees: invite code, question, snippets. Logs metadata only (no content) |
| **YOUR OpenRouter account** | Sees: a single API call, billed ~$0.005 |
| **OpenRouter / underlying LLM provider** | Sees: question + snippets (same as if Alice used ChatGPT) |

**Alice's bank account is untouched.** YOUR OpenRouter card gets a
~$0.25/week charge for Alice's 50 queries. Post-beta you charge Alice
a subscription that covers it.

---

## Three modes the codebase supports

The desktop's `src/llm.py` has multiple providers registered. Only one
ever ships to users; the others are for development.

### Mode 1 — `magpie-cloud` (the SHIPPED user mode)

```
LLM_PROVIDER=magpie-cloud
MAGPIE_CLOUD_URL=https://magpie.fly.dev
MAGPIE_INVITE_CODE=alice-N7yLxQ4mPkR
```

What happens: every LLM call goes through your server. Prompts hidden,
API key hidden, model choice hidden, billing centralized.

**This is what beta testers and v1.0 users will use.**

### Mode 2 — `openrouter` direct (DEV ONLY)

```
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-your-dev-key
```

What happens: desktop calls OpenRouter directly using a key in your
`.env`. Used by you to debug the engine without needing magpie-cloud
running.

**This mode is NEVER exposed in the shipped app's settings UI.** It
lives in the codebase for your CLI use only. The bundled binary's
default config sets `LLM_PROVIDER=magpie-cloud` and the settings UI
won't show provider switching.

### Mode 3 — `local` / future (v1.1)

```
LLM_PROVIDER=local
LOCAL_MODEL=mlx-community/gemma-3n-E2B-it-4bit
```

What happens: nothing leaves the device. Bundled small LLM runs
locally. Slower, less accurate, fully private.

**Available as a toggle in settings starting v1.1.** Pre-launch users
won't see this.

### Power-user "BYOK" — does it exist?

**No, not in the shipped app.** Reason: if BYOK shipped, the desktop
would need to call OpenRouter directly, which would mean shipping the
prompts in the binary. That undoes the IP protection Phase 2.5
exists to provide.

Power users who want BYOK clone the repo and use the CLI — the CLI's
`LLM_PROVIDER=openrouter` mode has always worked. The desktop app is
deliberately the consumer product, the CLI is the dev/power-user
tool.

Enterprise customers later who need their own provider account is a
**paid custom-deployment conversation** — doesn't affect the public
beta or v1.0 architecture.

---

## What this enables for your business model

Two things you couldn't do with BYOK:

### 1. Charge a subscription

If users had their own keys, they'd already be paying OpenRouter —
you couldn't charge them on top. With magpie-cloud:

- You eat the LLM cost (~$0.005/query × 50 queries/day × 30 days = ~$7/user/month at heavy use)
- You charge $X/month subscription
- The gap is your revenue
- Power users pay flat regardless of usage; light users subsidize heavy users

This is the SaaS model. Cursor charges $20/mo. Notion AI is $10/mo.
ChatGPT Plus is $20/mo. Magpie can pick a tier.

### 2. Provider-swap without app update

Today: Kimi via OpenRouter (free tier, decent quality).

Next month: Claude Sonnet 5 ships and is cheaper per quality token. You:

```bash
fly secrets set ANSWER_MODEL=anthropic/claude-sonnet-5
fly deploy
```

**Every existing user instantly gets better answers.** They don't
reinstall, don't update, don't notice. Their app feels smarter
overnight.

If each user had their own OpenRouter key, you couldn't do this — they'd
each have to update their settings. Magpie-cloud centralizes the
control.

---

## What changed in code (step 5 specifics)

| File | Change | Lines |
|---|---|---|
| [src/cloud_provider.py](../src/cloud_provider.py) | NEW — `CloudClient` (httpx wrapper) + `CloudRewriteAgent`, `CloudAnswerAgent`, `CloudSummarizeAgent`, `build_cloud_agent()` dispatcher | ~190 |
| [src/llm.py](../src/llm.py) | Added `magpie-cloud` to `PROVIDERS` dict; `build_agent()` dispatches to cloud agents when active provider is `magpie-cloud` | ~12 |
| [src/manifest.py](../src/manifest.py) | Hardening: redirect HuggingFace model cache from `~/.cache/huggingface/` to `APP_DATA_DIR/cache/` so model identity doesn't pollute the user's shared cache | ~6 |

The `build_cloud_agent()` dispatcher picks which endpoint to hit based
on the `output_type` requested:

- `SearchQuery` → `/llm/rewrite`
- `Answer` → `/llm/answer`
- `FileSummary` → `/llm/summarize`

So the call sites in `src/answer.py`, `src/stage1/summarize.py`, and
`src/stage2/search.py` don't change at all — `build_agent(prompt,
OutputType, fallback)` returns either a regular pydantic-ai agent
(OpenRouter direct) or a cloud agent (Magpie Cloud), based on the
active provider.

## What didn't change

- ALL retrieval logic (`run_search`, embedding, Qdrant) — still local
- ALL file reading — still local
- The prompts in the desktop's `src/answer.py`, `src/stage1/summarize.py`,
  `src/stage2/search.py` — still there as duplicates of server's prompts
  (parity-tested). They'll be **deleted** when v1.0 ships cloud-only;
  for now they're kept so dev mode 2 (OpenRouter direct) keeps working.
- The Tauri UI — pixel-identical
- The CLI REPL — pixel-identical

---

## Verified

- ✓ Provider registered (`magpie-cloud` in `PROVIDERS`)
- ✓ `active_provider().name == "magpie-cloud"` when env var set
- ✓ `build_agent(prompt, SearchQuery, fallback)` returns `CloudRewriteAgent`
- ✓ `build_agent(prompt, Answer, fallback)` returns `CloudAnswerAgent`
- ✓ `build_agent(prompt, FileSummary, fallback)` returns `CloudSummarizeAgent`
- ✓ Unknown output_type raises clear error
- ✓ HF cache redirected to `APP_DATA_DIR/cache/` (no leak to `~/.cache/huggingface/`)
- ✓ Desktop test suite: 409 passing, no regressions

---

## End-to-end test recipe (step 6 preview)

When you have an OpenRouter API key, the full loop is testable on
your laptop:

```bash
# 0. One-time setup
echo "OPENROUTER_API_KEY=sk-or-v1-..." >> server/.env
echo "INVITE_CODES=alice-test123" >> server/.env

# 1. Start your local cloud server
just cloud-serve
# → http://127.0.0.1:8000

# 2. In another terminal, point the desktop at it
LLM_PROVIDER=magpie-cloud \
MAGPIE_CLOUD_URL=http://127.0.0.1:8000 \
MAGPIE_INVITE_CODE=alice-test123 \
just chat

# 3. Ask anything — every LLM call goes through your local cloud
> what receipts do I have
```

Expected: clean answer, no model names visible, server stderr shows
the activity.

---

## Phase 2.5 progress

| Step | Status |
|---|---|
| 1. Scaffold | ✓ |
| 2. Auth | ✓ |
| 3. Prompts moved server-side | ✓ |
| 4. LLM endpoints (rewrite/answer/summarize) | ✓ |
| **5. Desktop's magpie-cloud provider** | ✓ |
| 6. End-to-end local test | next |
| 7. Dockerfile + first deploy | after 6 |

---

## Cross-references

- [src/cloud_provider.py](../src/cloud_provider.py) — the new client code
- [src/llm.py](../src/llm.py) — provider registry, build_agent factory
- [server/magpie_server/llm_routes.py](../server/magpie_server/llm_routes.py) — the three endpoints we now call
- [IO - Phase 2.5.md](IO%20-%20Phase%202.5.md) — overview of all Phase 2.5 steps
- [IO - Phase 2.5 Step 4.md](IO%20-%20Phase%202.5%20Step%204.md) — the cloud endpoints (server side of step 5's calls)
- [IO - Privacy.md](IO%20-%20Privacy.md) — the privacy implications of this routing
- [IO - Repo Structure.md](IO%20-%20Repo%20Structure.md) — why both desktop and server live in this monorepo
