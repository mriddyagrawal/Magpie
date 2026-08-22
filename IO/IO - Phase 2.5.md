# Phase 2.5 — Magpie Cloud (server scaffold)

> **What this doc is.** A frozen-in-time record of the cloud-server
> work started 2026-04-27 — the FastAPI service that holds the
> system prompts and proxies LLM calls so the desktop app never ships
> them. **In progress** — steps 1-2 done (scaffold + auth), steps 3-7
> still ahead. Update this doc as those land.
>
> Read this when: you're about to touch anything in `server/`, or
> before deciding where to put a new bit of LLM-orchestration logic.

---

## What we're building, and why

Two-layer architecture:

```
User's machine                              Your server (magpie.app)
────────────────                            ────────────────────────
Magpie.exe (Tauri shell)
  └── magpie-local sidecar
       ├── reads local files
       ├── runs MiniLM embedding              HTTPS
       ├── stores Qdrant index                ────────►   magpie-server (this!)
       ├── sends question + snippets ─────────/             ├── prompts (the IP)
       └── receives answer                                   ├── invite-code auth
                                                             ├── /llm/rewrite
                                                             ├── /llm/answer
                                                             ├── /llm/summarize
                                                             └── proxies to OpenRouter
                                                                  │
                                                                  ▼
                                                              Kimi / Claude / etc.
```

**Why the split**:

- **The user's data stays local** — files never leave the device.
- **The IP stays remote** — system prompts (the actual product secrets)
  live on your server, never ship in the .exe.
- **You own the bill** — desktop app uses your invite code to call your
  server; you pay OpenRouter, the user pays you (subscription), or
  beta is free for friends.
- **You can swap LLM providers** — change Kimi → Claude → GPT-4 in one
  env var on the server, no app update.

## Repo location

In the same monorepo as the desktop, in `server/` — see
[IO - Repo Structure.md](IO%20-%20Repo%20Structure.md) for why we
chose monorepo over a sibling repo. The server has its own
`pyproject.toml` so its Docker image doesn't need torch / qdrant /
colpali — only FastAPI + httpx + pydantic.

```
server/
├── magpie_server/
│   ├── __init__.py        ← package version                       [STEP 1 ✓]
│   ├── main.py            ← FastAPI app + /health + /whoami       [STEP 1 ✓]
│   ├── auth.py            ← invite-code bearer middleware         [STEP 2 ✓]
│   ├── settings.py        ← pydantic-settings env-var config      [STEP 1 ✓]
│   ├── prompts.py         ← system prompts (the IP)               [STEP 3 ✓]
│   ├── schemas.py         ← request/response Pydantic models      [STEP 4 ✓]
│   ├── llm_client.py      ← pydantic-ai wrapper around OpenRouter [STEP 4 ✓]
│   └── llm_routes.py      ← /llm/rewrite, /llm/answer, /llm/summarize  [STEP 4 ✓]
├── tests/
│   └── test_prompts_parity.py  ← guards desktop ↔ server prompt drift  [STEP 3 ✓]
├── pyproject.toml         ← server-only deps                       [STEP 1 ✓]
├── .env.example           ← copy to .env                            [STEP 1 ✓]
├── README.md              ← how to run                              [STEP 1 ✓]
└── Dockerfile             ← (step 7) for fly.io deploy
```

## Step 1 — FastAPI scaffold (DONE)

`magpie_server/main.py`:

```python
app = FastAPI(title="Magpie Cloud", version=__version__)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "auth_configured": bool(settings.valid_invite_codes()),
        "llm_configured": bool(settings.openrouter_api_key),
    }

@app.get("/whoami")
def whoami(invite: str = Depends(require_invite)):
    return {"invite_code": invite}
```

`/health` is **unauthenticated** — used by the desktop app to detect
"is the cloud reachable?" before it even tries to send a query, and by
deploy tools (fly.io) to health-check the container.

`/whoami` is **authenticated** — used during local debugging to confirm
the bearer-token path is wired correctly end-to-end.

## Step 2 — Invite-code auth (DONE)

Beta auth model: a comma-separated list of valid invite codes lives in
the `INVITE_CODES` env var. Each beta tester gets a unique one.

```python
# magpie_server/auth.py
def require_invite(authorization: str | None = Header(default=None)) -> str:
    valid = settings.valid_invite_codes()

    # No codes configured = open server. Only OK on localhost — refuses
    # if bound to anything else, so a forgotten env var in production
    # can't accidentally publish a free LLM proxy.
    if not valid:
        if settings.host not in ("127.0.0.1", "localhost", "::1"):
            raise HTTPException(503, "server not configured (no invite codes set)")
        return "anon-localhost"

    token = _extract_bearer(authorization)
    if token not in valid:
        raise HTTPException(401, "invalid invite code")
    return token
```

Smart-by-default behavior:

- **Local dev with empty `INVITE_CODES`**: auth is skipped, returns
  `"anon-localhost"` so you don't have to set a code while iterating.
- **Production with empty `INVITE_CODES`**: server refuses every
  request — protects against the "I forgot to set the env var" footgun
  that would otherwise leak a free LLM proxy onto the internet.
- **Any host with valid codes**: standard bearer-token check.

### Generate invite codes

```bash
$ python -c "import secrets; print('alice-' + secrets.token_urlsafe(16))"
alice-N7yLxQ4mPkRwHs8aVfBeJa

$ python -c "import secrets; print('bob-' + secrets.token_urlsafe(16))"
bob-Hw3vTjF8nKsM2pYrXq5cZx
```

Add to `server/.env`:
```
INVITE_CODES=alice-N7yLxQ4mPkRwHs8aVfBeJa,bob-Hw3vTjF8nKsM2pYrXq5cZx
```

To **revoke** a tester (someone leaks their code, or a friend stops
beta-testing): drop their entry from the env var, restart the server.
No DB, no migration, no "user records" — just secrets.

## End-to-end with curl

### `/health` — unauthenticated, always works

```bash
$ curl -s http://127.0.0.1:8000/health | jq
{
  "status": "ok",
  "version": "0.1.0",
  "auth_configured": false,
  "llm_configured": false
}
```

`auth_configured: false` and `llm_configured: false` are **fine for
dev** — they tell the desktop app "this is a dev server, expect
limited functionality." In production they should both be `true`.

### `/whoami` without auth — local dev mode

```bash
$ curl -s http://127.0.0.1:8000/whoami | jq
{ "invite_code": "anon-localhost" }
```

### `/whoami` with `INVITE_CODES` set — full auth path

```bash
$ INVITE_CODES="alice-test123" uv run uvicorn magpie_server.main:app --port 8000

# In another terminal:
$ curl -s http://127.0.0.1:8000/whoami | jq
{ "detail": "missing Authorization header" }      # 401

$ curl -s http://127.0.0.1:8000/whoami -H "Authorization: Bearer wrong-code" | jq
{ "detail": "invalid invite code" }               # 401

$ curl -s http://127.0.0.1:8000/whoami -H "Authorization: Bearer alice-test123" | jq
{ "invite_code": "alice-test123" }                # 200
```

All three return paths verified in the smoke test that landed alongside
this doc.

## Step 3 — Move prompts to `server/magpie_server/prompts.py` (DONE)

The four system prompts now live as constants in
[server/magpie_server/prompts.py](../server/magpie_server/prompts.py):

| Constant | Used by |
|---|---|
| `ANSWER_PROMPT` | `/llm/answer` — grounded answering |
| `REWRITE_PROMPT` | `/llm/rewrite` — query expansion for retrieval |
| `SUMMARIZE_PROMPT` | `/llm/summarize` — T3 cloud summarization |
| `SUMMARIZE_PROMPT_LOCAL` | (carried over) — local-mode fallback for v1.1 |

Plus `PROMPT_VERSIONS` dict so each `/llm/*` response can carry the
version of the prompt used — useful for A/B testing prompt changes
later without an app update.

Until step 5, the desktop still has copies in `src/answer.py`,
`src/stage1/summarize.py`, `src/stage2/search.py`. Each desktop copy
has a `# NOTE` comment pointing back to the server source-of-truth.
A parity test in
[server/tests/test_prompts_parity.py](../server/tests/test_prompts_parity.py)
catches drift via AST parsing — passes today, four-for-four.

When step 5 lands, the desktop copies get deleted and the parity test
gets deleted with them.

## Step 4 — `/llm/rewrite`, `/llm/answer`, `/llm/summarize` (DONE)

See [IO - Phase 2.5 Step 4.md](IO%20-%20Phase%202.5%20Step%204.md) for
the dedicated walkthrough. Headlines:

- Three endpoints live, schema-validated, all auth-gated
- pydantic-ai wraps OpenRouter so we get typed responses
- User-facing error mapper returns *"Something went wrong"* style
  messages; real errors logged to stderr
- Smoke-tested: missing API key returns clean 500, not a stack trace
- Server venv installs cleanly without torch / qdrant / colpali
  (~80 MB Docker image target)

### Step 5 — Add `magpie-cloud` provider to `src/llm.py`

The desktop app gains a new entry in `PROVIDERS`:

```python
PROVIDERS["magpie-cloud"] = MagpieCloudProvider(
    base_url=settings.magpie_cloud_url,    # e.g. https://api.magpie.app
    invite_code=user_settings.invite_code,
)
```

Selecting `LLM_PROVIDER=magpie-cloud` makes every LLM call route through
your server instead of OpenRouter directly. The user's app no longer
sees prompts, no longer needs an OpenRouter API key.

### Step 6 — End-to-end test

Local-only loop:
1. `cd server && just cloud-serve` — local cloud server on :8000
2. `LLM_PROVIDER=magpie-cloud MAGPIE_CLOUD_URL=http://localhost:8000 just serve` — local sidecar that talks to local cloud
3. `curl localhost:8765/query` — full pipeline runs through both layers

If that works locally, the only remaining variable for production is
"is the network reachable" — which is solved by deploying.

### Step 7 — Dockerfile + first deploy

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev
COPY server/magpie_server ./magpie_server
ENV HOST=0.0.0.0
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "magpie_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
fly launch                        # one-time, creates fly.toml
fly secrets set INVITE_CODES=...
fly secrets set OPENROUTER_API_KEY=...
fly deploy                        # ships to magpie.fly.dev
```

For beta-scale traffic (~10-20 testers), runs on fly.io's free tier
(256 MB VM). $0/month.

## Production hardening (not in scope for beta, but on the list)

- **Rate limiting per invite code** — `slowapi` middleware, e.g. 60 req/min/code
- **Request logging with PII redaction** — log who-asked-what without
  storing question text long-term (privacy)
- **Per-user accounting** — track how much OpenRouter spend each invite
  code is generating, set monthly caps
- **Audit trail** — every prompt change versioned, so we know what
  prompt was used for any past query
- **JWT migration** — when public launch needs >100 users, swap
  `auth.py` for JWT validation; endpoint signatures unchanged

## Files created

| File | Purpose |
|---|---|
| [server/magpie_server/__init__.py](../server/magpie_server/__init__.py) | Package marker, version |
| [server/magpie_server/main.py](../server/magpie_server/main.py) | FastAPI app, `/health`, `/whoami` |
| [server/magpie_server/auth.py](../server/magpie_server/auth.py) | `require_invite` dependency |
| [server/magpie_server/settings.py](../server/magpie_server/settings.py) | Env-var config via pydantic-settings |
| [server/pyproject.toml](../server/pyproject.toml) | Server-only deps |
| [server/.env.example](../server/.env.example) | Template for `.env` |
| [server/README.md](../server/README.md) | How to run |
| [justfile](../justfile) | New `cloud-serve` recipe |

Verified: smoke test runs all four auth paths (no header / bad code / good code / dev mode) and `/health` returns expected fields.

## Cross-references

- [server/](../server/) — the actual code
- [server/README.md](../server/README.md) — operator-facing docs (how
  to run, deploy, generate codes)
- [IO - Repo Structure.md](IO%20-%20Repo%20Structure.md) — why the
  cloud server lives in this monorepo
- [IO - Phase 1.md](IO%20-%20Phase%201.md) — portable paths
  (foundation for desktop packaging that this server will pair with)
- [IO - Phase 2.md](IO%20-%20Phase%202.md) — backend leak-scrub at
  the local sidecar boundary; same patterns apply at the cloud
  boundary
