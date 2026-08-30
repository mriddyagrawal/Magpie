# Repo Structure — monorepo today, splittable later

> **What this doc is.** A frozen-in-time record of *why* Magpie is one
> repo right now (instead of an engine repo + an app repo + a server
> repo), what we'd lose by splitting prematurely, and the explicit
> conditions under which we should split. Written 2026-04-27 when the
> team is two people; intended to be read by future-us (or a third
> hire) before they decide to "clean up the structure" and accidentally
> burn a week.
>
> Read this when: someone proposes splitting the repo. Read it BEFORE
> the proposal turns into a PR.

---

## Today's structure (one repo, three consumers)

```
Magpie/                     ← single git repo
├── src/                                  ← THE ENGINE (Python library)
│   ├── manifest.py                       ← portable APP_DATA_DIR via platformdirs
│   ├── ingest/                           ← walker + tier workers (T0-T4)
│   │   ├── walker.py
│   │   ├── tier0.py … tier4.py
│   │   └── common.py                     ← shared rendering / hashing
│   ├── stage1/, stage1_fast/             ← summarization, ColPali fast tier
│   ├── stage2/                           ← embedding + Qdrant search
│   ├── stage3/                           ← advanced indexing
│   ├── router.py                         ← peek + decide
│   ├── content.py                        ← format extractors
│   ├── answer.py                         ← LLM-grounded answering
│   ├── llm.py                            ← provider abstraction (Kimi / local / cloud)
│   └── server.py                         ← FastAPI sidecar (local backend for Tauri)
│
├── cli/                                  ← CLI consumer
│   └── magpie_cli/                     ← `ns` REPL, dot-commands, suggestions
│
├── frontend/                             ← Tauri + React desktop GUI consumer
│   ├── src/                              ← React UI (App.tsx, components/, api.ts)
│   └── src-tauri/                        ← Rust shell, sidecar config, NSIS installer
│
├── server/                               ← (FUTURE, Phase 2.5) cloud LLM backend
│   └── magpie_server/                    ← FastAPI app w/ /llm/rewrite, /llm/answer
│                                         ← prompts (the IP) live ONLY here
│
├── tests/                                ← shared test suite
├── scripts/                              ← migrate_data.py, build helpers
├── IO/                                   ← these design docs
├── Plans/                                ← engineering plans, backlog
└── pyproject.toml                        ← workspace root, deps for engine
```

Three consumers (`cli/`, `frontend/`, future cloud `server/`) all build on
the same `src/` engine. No code duplication. Each consumer can be touched
independently, but they share core logic via imports.

## What "modular" means here (and what it doesn't)

**Modular ≠ multi-repo.** A monorepo can be more modular than a poorly-
organized multi-repo. The dimensions that matter:

| Dimension | How we get it in one repo |
|---|---|
| **Code reuse** — engine logic shared by CLI / GUI / server | Import from `src/` |
| **Independent change** — touch the GUI without breaking CLI | Different folders, separate test suites |
| **Different dependencies** — server doesn't need torch | Per-folder `pyproject.toml` (workspace) |
| **Different deploy targets** — desktop installer vs cloud Docker | Separate build scripts in `scripts/` and `installer/` |
| **Different secrets** — desktop has none, server has API keys | `server/.env` gitignored; secrets injected by hosting provider |
| **Different release cadences** — server pushes daily, desktop ships monthly | Separate version tags (`server-v0.4.0`, `desktop-v0.4.0`) |

None of those require splitting the repo.

## Why one repo, today

We're a 2-person team shipping a beta. The cost/benefit math:

**What we'd pay to split (immediately):**

- 3-5 days to extract, set up CI for both repos, publish a private package, update imports across consumers
- Double the GitHub repos to monitor (issues, PRs, settings, secrets)
- Cross-repo PRs every time the API contract changes — *every* `/query` payload tweak becomes 2 PRs in 2 places with version skew in between
- Two READMEs, two changelogs, two release flows
- More cognitive load: "where does that change go?" friction on every commit

**What we'd buy:**

- Nothing tangible until the four "split triggers" below show up.

The math is easy: **stay monorepo until pain forces a split.** No pain
yet → no split yet.

## When to actually split (the four legitimate triggers)

Watch for any of these. When one happens, *that's* the moment to split —
not before.

### 1. People access boundary

> *"I'm hiring a backend contractor and I don't want them to see the
> desktop client code."*

Split when GitHub access permissions need to differ by repo. A
contractor working on `server/` should not see the desktop / installer /
proprietary UX work.

### 2. The server becomes a product itself

> *"We're going to sell the Magpie API to third-party developers."*

If the cloud server becomes a paid platform with external customers,
its repo gathers its own developer docs, OpenAPI spec, SDK clients,
support issues, customer-visible roadmap. That's a legitimate product
in its own right and deserves its own home.

### 3. License divergence

> *"Desktop is going closed-source; server stays open-source"* (or vice versa).

Splitting keeps each side's license, copyright headers, and contribution
flow clean. Mixing licenses in one repo is a mess we don't want.

### 4. Compliance / audit boundary

> *"SOC2 review says the LLM-handling code needs stricter controls
> than the client code."*

When a regulator requires a different access-control scope on different
parts of the codebase, splitting is the cleanest way to draw the line.

**If none of the four is true today, splitting is premature.** This is
the most common bad reason: *"It just feels cleaner to have separate
repos."* That feeling is real, but not strong enough to outweigh the
costs above.

## What would split first (when the time comes)

The most likely first split is **`server/` → its own repo**, because it
hits triggers #1 and #2 more easily than the engine or the desktop:

- The server holds the proprietary IP (system prompts, routing rules,
  rate-limiting logic, billing). When trigger #1 hits (a contractor
  works on it), separating it lets you hire someone for "Magpie Cloud"
  without exposing the desktop product roadmap.
- The server might evolve into a sellable API (trigger #2) — Magpie
  Cloud could become a paid LLM-orchestration product distinct from
  the desktop search tool.

The engine (`src/`) and desktop (`frontend/` + `cli/`) probably stay
together longer. Their atomic-commit benefit (changes to the engine
ripple immediately into both consumers) is too valuable to give up
without a strong reason.

## How to split when the time comes (concrete recipe)

When trigger #X fires and we decide to extract `server/`:

```bash
# 1. Create a new private repo: magpie-server
gh repo create magpie/magpie-server --private

# 2. Use git filter-repo to extract just the server/ folder with full history
git clone <main repo> /tmp/server-extract
cd /tmp/server-extract
git filter-repo --path server/ --path-rename server/:
git remote add origin git@github.com:magpie/magpie-server.git
git push origin main

# 3. In the original repo, remove server/ but keep history
cd <main repo>
git rm -r server/
git commit -m "Extract server/ into its own repo at magpie/magpie-server"

# 4. Replace cross-folder imports with cross-repo deps
#    src/llm.py used to call: server.magpie_server.client.query()
#    Now it calls:             import magpie_server_sdk; magpie_server_sdk.query()
#    Publish a thin SDK package that wraps HTTP calls — version-pin it.

# 5. Update CI in BOTH repos:
#    - main repo: drop server tests, build only desktop+engine
#    - server repo: add server tests, deploy on push to main

# 6. Update docs
#    - This doc gets a "split happened on YYYY-MM-DD" line
#    - The new repo's README points back here for engine context
```

Estimated effort: **3-5 days of focused work** to extract cleanly,
versus 1-2 hours per cross-repo PR forever after if we did it now and
didn't need it.

## The trap to avoid

> *"It would be cleaner to have separate repos."*

This sentence is the trap. "Cleaner" feels right — engineers are
trained to like separation. But cleanliness is a **design feeling**;
the actual costs are **operational** (PRs, CI, deploys, on-call) and
**cognitive** (where does this go? whose ownership?). The operational
costs are real and recurring; the cleanliness benefit is a one-time
aesthetic win.

The rule: **never split for aesthetic reasons. Only split when one of
the four triggers above actually fires.**

## Cross-folder dependencies today (the contract)

To make sure the monorepo doesn't drift into a tangled mess, the
allowed import directions are:

```
                 ┌──────────────────────────────────┐
                 │                                  │
                 ▼                                  │
              ┌─────┐                               │
              │ src/│ ◄────── cli/, frontend/, server/, scripts/
              └─────┘
                 ▲
                 │
                 └────────  tests/  (allowed to import any of the above)
```

Rules:
- `src/` imports nothing from `cli/`, `frontend/`, `server/`, or `scripts/`.
- Consumers (`cli/`, `frontend/`, `server/`) may import from `src/`.
- Consumers must NOT import from each other (no `cli/` → `server/`,
  no `server/` → `frontend/`).
- `tests/` can import from anywhere (they're tests).

**If we keep this contract, splitting later is mechanical.** Break the
contract (a back-import from a consumer into `src/`, or a cross-consumer
import) and splitting becomes a multi-day untangle. So we enforce it
in code review, not later.

## Checklist for "should we split?"

Run through this before opening a PR to extract a folder:

- [ ] Is one of the four triggers actually firing? (people / product / license / compliance)
- [ ] Have we hit a concrete bug or workflow problem because of monorepo? (Name it.)
- [ ] Is there a third party — not on the team — who would consume the extracted repo? (Name them.)
- [ ] Have we tried fixing the perceived issue WITHIN the monorepo first? (Better folder structure, per-folder pyproject.toml, separate CI jobs?)
- [ ] Are we willing to spend 3-5 days on the extraction and accept ongoing cross-repo PR cost?

If fewer than 4 of those check, **don't split**.

## Cross-references

- [pyproject.toml](../pyproject.toml) — workspace root + per-folder deps
- [frontend/package.json](../frontend/package.json) — Tauri + React workspace
- [cli/](../cli/) — CLI consumer of `src/`
- [scripts/migrate_data.py](../scripts/migrate_data.py) — example of build-time tooling that lives at repo root, not in any consumer
- [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md) — example of design docs that span all consumers
- [IO - Tiers.md](IO%20-%20Tiers.md) — the engine's tier system, used by every consumer
