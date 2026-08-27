"""HTTP server that wraps the existing RAG pipeline for the Magpie UI.

Endpoints:
    POST /query     - natural-language question → answer + sources
    POST /generate  - raw chat completion against the local LLM (text or SSE)
    GET  /preview   - return a file's content/rendering for the preview pane
    GET  /status    - model name + indexed file count (for the status pill)
    GET  /open      - open a file in the OS default app
    GET  /reveal    - reveal a file in Finder

Wraps `src.pipeline.ask()` and `src.content` helpers; does not touch RAG logic.

Run standalone:
    uv run uvicorn src.server:app --port 8765
Or as a Tauri sidecar (prints the chosen port to stdout):
    uv run python3 -m src.server
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import multiprocessing
import os
import socket
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path
from typing import Any

# PyInstaller + multiprocessing pitfall: when a frozen binary uses
# `multiprocessing.spawn`, Python's worker-bootstrap machinery
# re-invokes argv[0] with Python interpreter flags
# (`-B -S -I -c "from multiprocessing.resource_tracker import main; main(N)"`).
# The frozen `magpie-sidecar` binary's argparse doesn't understand these
# flags, so the worker fails silently with `unrecognized arguments`. The
# parent's worker-pool try/except swallows the failure, summarization
# returns no result, the manifest never gets `mark_summarized`, and
# stage 2 fails with "manifest is empty".
#
# `multiprocessing.freeze_support()` adds the special handling that
# detects "we're being re-invoked as a worker" and runs the worker
# bootstrap correctly. MUST be called before any code that might
# trigger multiprocessing.spawn (huggingface_hub downloads,
# transformers, etc.). At module-import time is the safest spot.
#
# In dev (non-frozen): no-op. In frozen builds: critical. See
# https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
multiprocessing.freeze_support()

# Force UTF-8 on stdout/stderr. On Windows these default to the legacy cp1252
# ("charmap") codec, so printing a path or summary containing a non-Latin1
# char (e.g. "≥") raises UnicodeEncodeError and kills the whole sync mid-walk.
# Tauri also sets PYTHONUTF8=1 on the sidecar, but this covers every other
# launch path (`just serve`, the CLI, direct `python -m src.server`). Guarded
# because a --noconsole PyInstaller build can hand us None or non-reconfigurable
# streams.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass

# Suppress library noise BEFORE importing torch / transformers / qdrant_client.
# These show up as scary-looking warnings and progress bars in dev terminals,
# but say nothing useful to the user. Set defaults so .env / env can override
# (e.g. TRANSFORMERS_VERBOSITY=info during model debugging).
#
# For the .env half of that promise to hold, .env must be in os.environ before
# the setdefault calls — setdefault-then-load_dotenv silently discards the
# .env value (python-dotenv never overrides existing vars). Hence dotenv loads
# here, first thing.
from dotenv import load_dotenv
load_dotenv()
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# logfire (pulled in by pydantic-ai) registers a Pydantic plugin that calls
# inspect.getsource() at import time — that crashes in PyInstaller bundles.
# LOGFIRE_PYDANTIC_PLUGIN_RECORD only controls logging; logfire still patches
# the SchemaValidator unconditionally. Swallow the OSError in frozen builds.
os.environ.setdefault("LOGFIRE_PYDANTIC_PLUGIN_RECORD", "off")
if getattr(sys, "frozen", False):
    import inspect as _inspect
    _real_getsource = _inspect.getsource
    def _safe_getsource(obj):  # noqa: E306
        try:
            return _real_getsource(obj)
        except OSError:
            return ""
    _inspect.getsource = _safe_getsource

    # PyInstaller + torch.distributed.rpc workaround.
    #
    # The bundled `torch._C` C extension registers `RpcBackendOptions`
    # at load time. Later, `torch._jit_internal.py:44` does
    # `import torch.distributed.rpc`, whose `__init__.py:28` calls
    # `torch._C._rpc_init()` — which tries to register the same type
    # AGAIN and fails with:
    #
    #   RuntimeError: generic_type: cannot initialize type
    #   "RpcBackendOptions": an object with that name is already defined
    #
    # The error is process-sticky: once thrown, every subsequent
    # `import torch` in the same sidecar process fails the same way,
    # which knocks out indexing, summarization, AND query rerank.
    #
    # Strategy: speculatively `import torch` once at sidecar startup
    # (frozen-only). On the expected RuntimeError, stub
    # `torch._C._rpc_init` to a no-op (we don't use distributed RPC),
    # clear partial torch.* state from sys.modules, and retry. After
    # this, every subsequent `import torch` is a cached no-op and the
    # whole pipeline works.
    #
    # 2026-05-09 NOTE: `--collect-all torch` was added to build_sidecar.py
    # in commit 99658a1 — that may have changed how PyInstaller bundles
    # torch's C extensions, possibly avoiding the duplicate-registration
    # scenario entirely. Kept this workaround as a defensive safety net:
    # if the speculative `import torch` succeeds (no RuntimeError), the
    # except branch never fires and we eat ~3-5s of warm-up that we'd
    # pay anyway on first query. If the bug still fires, the workaround
    # rescues us and logs `[server] applying torch.distributed.rpc
    # PyInstaller workaround` so we know. Remove this block once we
    # have positive evidence (a clean bootstrap.log without the warning
    # line) across multiple builds AND the CI /query smoke test
    # exercises the rerank path.
    #
    # Cost: ~3-5s of torch loading at sidecar startup that previously
    # was lazy. Acceptable in exchange for "queries actually work."
    # Skipped in dev because non-frozen `import torch` doesn't hit
    # this bug — it'd just slow down dev startup for no benefit.
    try:
        import torch  # noqa: F401  # eager-import warm-up
    except RuntimeError as e:
        if "RpcBackendOptions" not in str(e) or "already defined" not in str(e):
            raise
        print(
            "[server] applying torch.distributed.rpc PyInstaller workaround "
            "(stubbing torch._C._rpc_init)",
            file=sys.stderr,
        )
        _torch_c = sys.modules.get("torch._C")
        if _torch_c is not None:
            _torch_c._rpc_init = lambda: True  # type: ignore[attr-defined]
        # Clear partial torch.* state EXCEPT torch._C (which holds our
        # stub) so the retry doesn't see torch.distributed.rpc as
        # already-loaded-but-broken.
        for _k in list(sys.modules.keys()):
            if _k != "torch._C" and _k.startswith("torch"):
                sys.modules.pop(_k, None)
        import torch  # noqa: F401  # retry — should succeed via stub

warnings.filterwarnings("ignore", category=UserWarning, module="qdrant_client")
warnings.filterwarnings("ignore", category=UserWarning, module="torch.cuda")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel, Field

from src.manifest import APP_DATA_DIR


# `REPO_ROOT` here is the data root used to resolve manifest-relative paths.
# Portable across Linux / Windows / macOS via `platformdirs`.
REPO_ROOT = APP_DATA_DIR

# Eager-bootstrap the layered config files so they exist on disk for
# the user to inspect. Both are lazy-bootstrapped on first call by the
# code paths that need them (settings: settings UI; secrets: build
# cloud chat model), but in pure-local mode neither path fires
# during a session and the user wonders why <APP_DATA_DIR> looks
# empty. Running the bootstraps here makes the files appear on first
# server start regardless of which provider the user picks.
def _eager_bootstrap_config() -> None:
    try:
        from src.config.settings import load_user_settings
        load_user_settings()  # writes settings.json with defaults if missing
    except Exception as e:  # noqa: BLE001
        print(f"[server] settings bootstrap warning: {e}", file=sys.stderr)
    try:
        from src.config.secrets import load_secrets
        load_secrets()  # writes secrets.json (mode 0600) seeded from .env
    except Exception as e:  # noqa: BLE001
        print(f"[server] secrets bootstrap warning: {e}", file=sys.stderr)


_eager_bootstrap_config()

app = FastAPI(title="Magpie", version="0.1.0")


@app.on_event("startup")
def _startup_auto_resume() -> None:
    """Once the sidecar is up and routes are wired, fire an auto-sync if
    there's anything to do. Runs in a daemon thread (spawned inside
    `_spawn_sync_or_coalesce`), so this handler returns instantly and
    FastAPI keeps serving. Safe to fire on every launch — `_do_sync()`
    is idempotent.

    Why startup-event, not module-level: at module-import time the sidecar
    isn't yet bound to its port. If we fired sync there, the user's first
    `/ingest/status` poll could land before uvicorn finishes binding,
    leading to a confusing "fetch failed" → "indexing started" sequence.
    The startup event runs after binding."""
    try:
        _maybe_auto_resume_on_startup()
    except Exception as e:  # noqa: BLE001 — never crash the sidecar on auto-resume
        print(f"[server] auto-resume hook failed: {e}", file=sys.stderr)

# Permissive CORS so the Vite dev server (typically localhost:5173) can hit
# the sidecar on localhost:<port> without friction. In production, the
# frontend is loaded by Tauri under the `tauri://` origin which CORS treats
# as opaque anyway; wildcard is fine here since we only bind to loopback.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(path_str: str) -> Path:
    """Accept relative-to-repo or absolute paths; reject anything that escapes."""
    p = Path(path_str)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    else:
        p = p.resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"no such file: {path_str}")
    if not p.is_file():
        raise HTTPException(status_code=400, detail=f"not a file: {path_str}")
    return p


IMAGE_MIMES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif",
}
TEXT_EXTS = {".md", ".markdown", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx",
             ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb",
             ".swift", ".kt", ".sh", ".sql", ".json", ".yaml", ".yml", ".toml"}


# ---------------------------------------------------------------------------
# /query
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var. Accepts true/yes/on/1 (case-insensitive) as
    True, false/no/off/0/empty as False; anything else falls back to default."""
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("true", "yes", "on", "1"):
        return True
    if raw in ("false", "no", "off", "0", ""):
        return False
    return default


class QueryHistoryTurn(BaseModel):
    """One prior (question, answer) pair from the user's recent history.
    Sent to the LLM as conversational context so follow-up questions
    resolve references like 'it', 'the test', 'the same one'. The
    files / sources from the prior turn are NOT re-sent — only the
    question and answer text. See answer.py:SYSTEM_PROMPT for the
    history-handling instructions."""
    question: str
    answer: str


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    # `top_k` may be omitted by the client. When absent, the handler
    # falls back to `effective_settings().top_k` so the user's Settings
    # → Search & AI → Advanced → Top K slider is the single source of
    # truth for retrieval depth. An explicit per-request value still
    # wins. Same shape as the `rewrite` field below.
    top_k: int | None = Field(default=None, ge=1, le=20)
    # `rewrite` enables Kimi-style query expansion before retrieval (~20s
    # extra LLM round-trip; produces a keyword-rich SearchQuery). When the
    # client omits the field, the server falls back to the `REWRITE` env
    # var (default: false). Explicit per-request value still wins. So:
    #   .env REWRITE=true  + body omits rewrite → True
    #   .env REWRITE=true  + body rewrite=False → False (explicit override)
    #   .env unset         + body omits rewrite → False (current default)
    rewrite: bool | None = Field(default=None)
    # `fast` toggles ColPali visual-tier search. Default off — the cold-load
    # is ~25s for a model that's only useful for a small fraction of queries
    # (visual / scanned-PDF questions). Same default as the CLI's `.fast off`.
    fast: bool = Field(default=False)
    # Conversational context: the last N (question, answer) pairs from
    # the user's recents, oldest-first. Sent to the answer LLM so it can
    # resolve references in follow-ups ('what's on the test' after 'what
    # did Ram say about the test'). Files are NOT re-sent — only the
    # text. None / empty = no context (single-shot ask).
    history: list[QueryHistoryTurn] = Field(default_factory=list)


class SourceOut(BaseModel):
    path: str
    summary: str
    score: float
    cited: bool  # whether the answer model listed this in sources_used


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceOut]
    search_query: dict[str, Any]
    # Not-found state — set by the answer pipeline when none of the retrieved
    # files contain enough information to answer the question. The frontend
    # renders the ask bar's State 5 (single "Add folder where this knowledge
    # might live" CTA) when not_found=True. See Specs/UI/ask_bar.md.
    not_found: bool = False
    not_found_topic: str = ""
    sources_scanned_count: int = 0
    # Recent id — the entry just persisted to recents.json. Lets the frontend
    # append the new ask to its in-memory recents list without an extra GET.
    recent_id: str | None = None


def _user_facing_error(exc: Exception) -> tuple[int, str]:
    """Map an internal exception to (HTTP status, user-safe message).

    Real exception details are logged server-side (stderr) so we can debug,
    but the client only ever sees a generic friendly message — no model
    names, no provider names, no implementation jargon. See
    IO/IO - Repo Structure.md for the no-tech-leak principle.
    """
    name = type(exc).__name__
    text = str(exc)

    # Full stack trace to stderr so packaged-build runtime errors
    # (e.g. PyInstaller exclude regressions like `ModuleNotFoundError:
    # torch.distributed`) leave a real diagnostic, not just a one-line
    # "internal error". Tauri pipes stderr to bootstrap.log, so this
    # ends up in the user's APP_DATA_DIR/logs/ for postmortem.
    import traceback
    print(f"[server] internal error {name}: {text}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)

    # Local-inference failures. Matched on exception TYPE, deliberately
    # ahead of the substring heuristics below: the binary-not-found message
    # embeds filesystem paths, and a user whose home directory happens to
    # contain "rate" or "collection" would otherwise be told the service is
    # busy or that search is starting up. Type matching can't misfire that
    # way. Matched by name rather than by importing the classes so this
    # stays cheap and free of an import cycle through src.inference.
    #
    # Without this, all three fell through to the 500 default and the user
    # got "Something went wrong. Please try again." on every query, forever,
    # with no hint that the fix is a Settings toggle. The remediation detail
    # ("run `just install-llama-server`") stays in the stderr log above —
    # it's a developer instruction, not something to show an end user.
    #
    # Wording tracks the Settings UI's own vocabulary ("Local" / "Cloud")
    # rather than naming llama-server, per the no-tech-leak principle in
    # IO/IO - Repo Structure.md.
    if name == "LlamaServerBinaryError":
        return 503, "The local model isn't set up on this machine. Switch to Cloud in Settings."
    if name in ("LlamaServerSpawnError", "LlamaServerCrashError"):
        return 503, "The local model couldn't start. Switch to Cloud in Settings."

    # 429 rate-limit / quota-exhausted from any LLM provider
    if "429" in text or "rate" in text.lower() or "quota" in text.lower():
        return 503, "Service is busy right now. Try again in a few seconds."
    # Auth / API-key issues (cloud provider rejected our request)
    if "401" in text or "403" in text or "unauthor" in text.lower() or "api key" in text.lower():
        return 401, "Account isn't set up yet. Check your settings."
    # Network / DNS / connection errors
    if name in ("ConnectionError", "TimeoutError") or "connection" in text.lower():
        return 503, "Can't reach the network. Check your connection."
    # Local file disappeared between retrieval and read
    if name == "FileNotFoundError" or "no such file" in text.lower():
        return 404, "Couldn't find that file anymore."
    # Qdrant unavailable
    if "qdrant" in text.lower() or "collection" in text.lower():
        return 503, "Search is starting up. Try again in a moment."
    # Default fallback
    return 500, "Something went wrong. Please try again."


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    from src.answer import Answer
    from src.manifest import Manifest
    from src.pipeline import ask
    from src.recents import add_recent

    # Resolve `rewrite` and `top_k`: explicit body values win; otherwise
    # use the user's Settings → Search & AI choices (persisted in
    # settings.json, surfaced via `effective_settings()`). The legacy
    # `REWRITE` env var is no longer consulted — same precedence flip
    # we did for `LLM_PROVIDER` on 2026-05-08, since env was silently
    # shadowing the UI toggle. To force a per-query override, pass
    # `rewrite` in the request body.
    eff = _effective_settings()  # noqa — see _rewrite_for_provider below
    rewrite = req.rewrite if req.rewrite is not None else _rewrite_for_provider(eff)
    top_k = req.top_k if req.top_k is not None else eff.top_k

    # Convert the history Pydantic models to the (q, a) tuples answer.py
    # expects. Empty list when no history was sent.
    history_pairs: list[tuple[str, str]] = [
        (turn.question, turn.answer) for turn in req.history
    ]

    try:
        result = await ask(
            req.question,
            top_k=top_k,
            rewrite=rewrite,
            fast=req.fast,
            history=history_pairs,
        )
    except Exception as e:  # pylint: disable=broad-except
        status_code, detail = _user_facing_error(e)
        raise HTTPException(status_code=status_code, detail=detail) from e

    cited = set(result.sources_used)
    sources = [
        SourceOut(path=r.path, summary=r.summary, score=r.score, cited=r.path in cited)
        for r in result.retrieved
    ]

    # Persist this ask as a recent so the user can replay it without paying
    # LLM cost again. We mirror the Answer payload exactly — the cached state
    # is what gets re-rendered on replay. See Specs/UI/ask_bar.md.
    answer_for_recent = Answer(
        answer=result.answer,
        sources_used=result.sources_used,
        not_found=result.not_found,
        not_found_topic=result.not_found_topic,
    )
    rewritten = result.search_query.query if rewrite else None
    try:
        recent_entry = add_recent(
            question=result.question,
            result=answer_for_recent,
            rewritten_query=rewritten,
        )
        recent_id: str | None = recent_entry.id
    except Exception as e:  # pylint: disable=broad-except
        # Recents persistence failure must not break the user's ask. Log and
        # continue with no recent_id; the ask bar falls back to GET /recents.
        print(f"[server] recents persist failed (non-fatal): {e}", file=sys.stderr)
        recent_id = None

    return QueryResponse(
        question=result.question,
        answer=result.answer,
        sources=sources,
        search_query={"query": result.search_query.query, "keywords": result.search_query.keywords},
        not_found=result.not_found,
        not_found_topic=result.not_found_topic,
        # File-level count from the manifest, not chunk count from
        # `result.retrieved` — the latter inflates with CSV row hits
        # (one file → many chunk rows), which made the not-found
        # card say "I read 20 likely sources" when top_k was 5.
        sources_scanned_count=len(Manifest().entries),
        recent_id=recent_id,
    )


# ---------------------------------------------------------------------------
# /query/stream — same RAG pipeline, surfaces retrieval before the answer
# ---------------------------------------------------------------------------
#
# Mirrors `/query` 1:1 in inputs, but emits results as an SSE stream so
# the ask bar can paint the sources card the moment retrieval finishes
# (~500ms-3s), before the answer LLM call returns. The answer itself is
# delivered as a sequence of `answer_chunk` events that the frontend
# appends to the AnswerCard as they arrive — token-by-token UX once
# Phase 2 lands (see below).
#
# Wire format (SSE, `text/event-stream`):
#
#   event: sources
#   data: {"retrieved": [...], "search_query": {...},
#          "rewritten_query": "..." | null, "sources_scanned_count": N}
#   ── fires once after retrieval, before the answer LLM call.
#
#   event: not_found_topic
#   data: {"topic": "..."}
#   ── fires only when the answer pipeline declares not-found. Terminal
#      branch: no `answer_chunk` / `sources_used` will follow.
#
#   event: answer_chunk
#   data: {"text": "..."}
#   ── fires N times during the answer phase, each with a slice of the
#      answer text. Caller appends `text` to its in-progress answer
#      buffer. Newlines / Unicode preserved verbatim (JSON-encoded).
#
#   event: sources_used
#   data: {"paths": [...]}
#   ── fires once after the final `answer_chunk`, with the subset of
#      retrieved paths the model actually cited. Frontend reconciles
#      the `cited` flag on its sources state at this point.
#
#   event: done
#   data: {"recent_id": "..." | null}
#   ── terminal sentinel. Always fires last (success, not-found, or
#      error). Frontend stops the SSE reader on this event.
#
#   event: error
#   data: {"detail": "user-safe message", "phase": "retrieval"|"answer"}
#   ── fires when retrieval or the answer step throws. Followed by
#      `done`. No `answer_chunk` / `sources_used` will follow.
#
# **Phase status (2026-05).** Phase 1 (this implementation) emits the
# answer as **a single `answer_chunk`** containing the full answer text,
# emitted after the agent's structured-output call returns. The wire
# shape is correct for token-by-token streaming; Phase 2 (Plan #35)
# replaces the single-chunk emission with real per-token chunks by:
# (a) extracting `_build_answer_messages` from `answer_question`, and
# (b) calling `local_llm.stream(messages, response_format=…json_schema…)`
# instead of `agent.run`, then routing the streamed JSON bytes through
# a substring-match parser that watches for the `"answer": "` field
# start and emits everything between the opening and closing quotes
# as `answer_chunk` events.

@app.post("/query/stream")
async def query_stream(req: QueryRequest):
    """Streaming variant of `/query`. See block comment above for wire format."""
    # Inline imports mirror /query — keeps cold-start cheap when the
    # endpoint isn't called.
    from src.answer import Answer, answer_question, build_answer_agent
    from src.manifest import Manifest
    from src.recents import add_recent
    from src.stage2.search import raw_query, rewrite_query, run_search

    eff = _effective_settings()
    rewrite = req.rewrite if req.rewrite is not None else _rewrite_for_provider(eff)
    top_k = req.top_k if req.top_k is not None else eff.top_k
    history_pairs: list[tuple[str, str]] = [
        (turn.question, turn.answer) for turn in req.history
    ]

    async def sse_iter():
        # Helper: format an SSE frame. JSON-encode the payload so newlines
        # inside fields (e.g. multi-line answers) get escaped — raw
        # newlines would break the `data: ...\n\n` frame boundary.
        def _frame(event: str, payload: dict[str, Any] | None = None) -> str:
            data = json.dumps(payload or {}, ensure_ascii=False)
            return f"event: {event}\ndata: {data}\n\n"

        # Mirror pipeline.ask's enumerate_lists read with the same
        # defensive fallback.
        try:
            enumerate_lists = _effective_settings().enumerate_lists
        except Exception:  # noqa: BLE001 — defensive, never block on settings
            enumerate_lists = True

        # ── Phase 1: retrieval ────────────────────────────────────────
        try:
            if rewrite:
                sq = await asyncio.to_thread(rewrite_query, req.question)
            else:
                sq = raw_query(req.question)

            retrieved = await asyncio.to_thread(
                run_search, sq, top_k,
                question=req.question, skip_fast=not req.fast, rerank=True,
                enumerate_lists=enumerate_lists,
            )
            # Confident-retrieval solo gate (local only) — see
            # search.gate_to_solo. Keeps the streaming path and
            # pipeline.ask() behaviorally identical.
            from src.stage2.search import gate_to_solo
            retrieved = gate_to_solo(retrieved, question=req.question)
        except Exception as e:  # pylint: disable=broad-except
            _, detail = _user_facing_error(e)
            yield _frame("error", {"detail": detail, "phase": "retrieval"})
            yield _frame("done")
            return

        sources_scanned_count = len(Manifest().entries)

        # Empty-retrieval is a not-found shape — no sources, no answer
        # call. Emit one sources frame with an empty list, then the
        # synthetic not_found_topic, then done.
        if not retrieved:
            not_found_topic = req.question.strip().rstrip("?").strip()
            yield _frame("sources", {
                "retrieved": [],
                "search_query": {"query": sq.query, "keywords": sq.keywords},
                "rewritten_query": sq.query if rewrite else None,
                "sources_scanned_count": sources_scanned_count,
            })
            try:
                recent_entry = add_recent(
                    question=req.question,
                    result=Answer(
                        answer="", sources_used=[],
                        not_found=True, not_found_topic=not_found_topic,
                    ),
                    rewritten_query=(sq.query if rewrite else None),
                )
                recent_id: str | None = recent_entry.id
            except Exception as e:  # pylint: disable=broad-except
                print(f"[server] recents persist failed (non-fatal): {e}", file=sys.stderr)
                recent_id = None
            yield _frame("not_found_topic", {"topic": not_found_topic})
            yield _frame("done", {"recent_id": recent_id})
            return

        # Sources frame — the whole point of streaming. Frontend renders
        # the sources card immediately and parks the answer card on a
        # spinner until the answer_chunk events start arriving.
        sources_payload_list = [
            {
                "path": r.path,
                "summary": r.summary,
                "score": r.score,
                # `cited` is False here because the answer model hasn't
                # run yet. The `sources_used` frame (after the answer
                # finishes) supersedes this — the frontend reconciles
                # the cited set on event=sources_used.
                "cited": False,
            }
            for r in retrieved
        ]
        yield _frame("sources", {
            "retrieved": sources_payload_list,
            "search_query": {"query": sq.query, "keywords": sq.keywords},
            "rewritten_query": sq.query if rewrite else None,
            "sources_scanned_count": sources_scanned_count,
        })

        # ── Phase 2: answer ───────────────────────────────────────────
        paths = list(dict.fromkeys(r.path for r in retrieved if r.path))
        csv_row_hits: dict[str, list[int]] = {}
        for r in retrieved:
            if r.path and r.chunk_index is not None:
                csv_row_hits.setdefault(r.path, []).append(int(r.chunk_index))

        try:
            agent = build_answer_agent()
            ans: Answer = await answer_question(
                agent, req.question, paths,
                history=history_pairs,
                search_query=sq,
                csv_row_hits=csv_row_hits or None,
                enumerate_lists=enumerate_lists,
            )
        except Exception as e:  # pylint: disable=broad-except
            _, detail = _user_facing_error(e)
            yield _frame("error", {"detail": detail, "phase": "answer"})
            yield _frame("done", {"recent_id": None})
            return

        # Persist recent — non-fatal on failure, same as /query.
        try:
            recent_entry = add_recent(
                question=req.question,
                result=Answer(
                    answer=ans.answer,
                    sources_used=ans.sources_used,
                    not_found=ans.not_found,
                    not_found_topic=ans.not_found_topic,
                ),
                rewritten_query=(sq.query if rewrite else None),
            )
            recent_id = recent_entry.id
        except Exception as e:  # pylint: disable=broad-except
            print(f"[server] recents persist failed (non-fatal): {e}", file=sys.stderr)
            recent_id = None

        # Not-found branch — single not_found_topic event, no answer
        # chunks, no sources_used. Frontend transitions to the not-found
        # card on this event without waiting for further frames.
        if ans.not_found:
            yield _frame("not_found_topic", {"topic": ans.not_found_topic})
            yield _frame("done", {"recent_id": recent_id})
            return

        # Found branch.
        # Phase 1: emit the entire answer as a single chunk. Phase 2 will
        # replace this `for chunk in [ans.answer]:` with a true per-token
        # iterator backed by `local_llm.stream()` + a substring-match
        # JSON parser that watches the streamed bytes for the `"answer":
        # "..."` field and pipes through everything between the quotes.
        # The wire format is already correct — Phase 2 is a backend
        # implementation swap; api.ts and MagpieWindow integration land
        # on day one.
        if ans.answer:
            yield _frame("answer_chunk", {"text": ans.answer})
        yield _frame("sources_used", {"paths": ans.sources_used})
        yield _frame("done", {"recent_id": recent_id})

    return StreamingResponse(sse_iter(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# /generate — raw chat completion against the local LLM
# ---------------------------------------------------------------------------
#
# `/query` is the high-level RAG endpoint (retrieve → answer with citations).
# `/generate` is one level lower: it talks to the local LLM directly with the
# caller's chat-completion message list. Used for ad-hoc generation, future
# agentic loops, and any UI surface that wants conversational completion
# without going through retrieval. Local-only by design — cloud paths use
# `/query` (or, eventually, the magpie-cloud sidecar's own routes).

class GenerateMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class GenerateRequest(BaseModel):
    messages: list[GenerateMessage]
    stream: bool = Field(default=False)
    thinking: bool = Field(default=False)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)


class GenerateResponse(BaseModel):
    text: str


@app.post("/generate")
async def generate(req: GenerateRequest):
    """Run a chat completion against the local LLM.

    Returns JSON `{text}` for `stream=false`. Returns an
    `text/event-stream` of `data: <chunk>\\n\\n` lines for `stream=true`,
    terminated by `data: [DONE]\\n\\n` — the standard SSE shape that
    OpenAI-style streaming clients expect.
    """
    from src.inference import get_local_llm

    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    llm = get_local_llm()

    if not req.stream:
        try:
            text = await llm.complete(
                msgs,
                thinking=req.thinking,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
        except Exception as e:  # pylint: disable=broad-except
            status_code, detail = _user_facing_error(e)
            raise HTTPException(status_code=status_code, detail=detail) from e
        return GenerateResponse(text=text)

    async def sse_iter():
        try:
            stream = await llm.stream(
                msgs,
                thinking=req.thinking,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
            async for chunk in stream:
                # SSE wire format: each event is `data: <payload>\n\n`.
                # Newlines inside the chunk would break the framing, so
                # encode them — clients reverse this on the other side.
                safe = chunk.replace("\n", "\\n")
                yield f"data: {safe}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:  # pylint: disable=broad-except
            # Errors mid-stream: emit a final SSE event with the user-safe
            # message and end the stream. Client-side error UI then has
            # something to show without a TCP reset.
            _, detail = _user_facing_error(e)
            yield f"event: error\ndata: {detail}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(sse_iter(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# /preview
# ---------------------------------------------------------------------------

# In-memory cache for rendered PDF pages, keyed by (abs_path, mtime, page).
# Keeps re-preview on click cheap; no need for bounded eviction at our scale.
_pdf_cache: dict[tuple[str, float, int], bytes] = {}


@app.get("/preview")
def preview(
    path: str = Query(...),
    page: int = Query(default=0, ge=0),
    max_rows: int = Query(default=500, ge=1, le=5000),
):
    abs_path = _resolve(path)
    ext = abs_path.suffix.lower()

    if ext in IMAGE_MIMES:
        return FileResponse(abs_path, media_type=IMAGE_MIMES[ext])

    if ext == ".pdf":
        from src.content import render_pdf_pages_as_png, SummarizeError

        mtime = abs_path.stat().st_mtime
        key = (str(abs_path), mtime, page)
        if key in _pdf_cache:
            return Response(content=_pdf_cache[key], media_type="image/png")
        try:
            pages = render_pdf_pages_as_png(abs_path, max_pages=page + 1)
        except SummarizeError as e:
            raise HTTPException(status_code=415, detail=str(e)) from e
        if page >= len(pages):
            raise HTTPException(status_code=404, detail=f"page {page} not in pdf (max {len(pages) - 1})")
        png = pages[page]
        _pdf_cache[key] = png
        return Response(content=png, media_type="image/png")

    if ext == ".csv":
        try:
            with abs_path.open(encoding="utf-8") as f:
                reader = csv.reader(f)
                rows_iter = iter(reader)
                header = next(rows_iter, [])
                rows = []
                for i, row in enumerate(rows_iter):
                    if i >= max_rows:
                        break
                    rows.append(row)
        except (UnicodeDecodeError, csv.Error) as e:
            raise HTTPException(status_code=415, detail=f"csv parse error: {e}") from e
        return JSONResponse({"columns": header, "rows": rows, "truncated": len(rows) >= max_rows})

    if ext in TEXT_EXTS:
        try:
            text = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=415, detail=f"not valid utf-8: {e}") from e
        return PlainTextResponse(text)

    if ext == ".docx":
        from src.content import extract_docx_text, SummarizeError
        try:
            text = extract_docx_text(abs_path)
        except SummarizeError as e:
            raise HTTPException(status_code=415, detail=str(e)) from e
        return PlainTextResponse(text)

    if ext in {".xlsx", ".xlsm"}:
        from src.content import extract_xlsx_text, SummarizeError
        try:
            text = extract_xlsx_text(abs_path)
        except SummarizeError as e:
            raise HTTPException(status_code=415, detail=str(e)) from e
        return PlainTextResponse(text)

    raise HTTPException(
        status_code=415,
        detail=f"unsupported preview type '{ext}' — client should fall back to /open",
    )


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------

_status_cache: dict[str, Any] = {"ts": 0.0, "payload": None}
_STATUS_TTL = 5.0


class StatusResponse(BaseModel):
    """User-facing status. Originally omitted provider/model/disk size
    on the no-tech-leak principle, but the Settings sidebar's status
    footer (`understood: N · size: N MB · provider: Local · Gemma 4`)
    needs them. They're surfaced here, not in any user-facing tooltip
    on the ask bar — Settings is the chrome that shows operational
    state. The ask bar's StatusFooter consumes the same data."""
    ready: bool
    indexed_count: int
    version: str
    # Settings UI extras (PR 5):
    provider: str = "local"  # "local" | "cloud"
    model: str = ""          # human-readable model name
    size_mb: int | None = None  # on-disk Qdrant collection size; null if unknown


@app.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    now = time.monotonic()
    if _status_cache["payload"] is not None and now - _status_cache["ts"] < _STATUS_TTL:
        return _status_cache["payload"]

    from src.stage2.db import COLLECTION_NAME, get_qdrant_client

    # `indexed_count` is the file count from the manifest, not the
    # Qdrant point count. Manifest = files Magpie has read end-to-end;
    # Qdrant points include per-chunk rows (CSV row hits, PDF pages),
    # which inflates beyond a user's mental model of "indexed files".
    # The Settings sidebar's "understood: N" and the not-found card's
    # "I checked all N sources" both want the file count.
    try:
        from src.manifest import Manifest
        indexed_count = len(Manifest().entries)
        # Liveness is still a Qdrant probe — manifest could be populated
        # while Qdrant is down, in which case search would fail.
        get_qdrant_client().get_collections()
        ready = True
    except Exception:  # pylint: disable=broad-except
        indexed_count = 0
        ready = False

    # Provider / model — read from layered config. Lazy import to keep
    # the cold path of /status fast and to allow the config layer to
    # not be importable in degenerate test envs.
    provider = "local"
    model = ""
    try:
        from src.config.settings import effective_settings
        eff = effective_settings()
        provider = eff.provider
        # Reuse the helper added in PR 3 for the search-pill resolution.
        model = _resolved_model_name(provider)
    except Exception:  # pylint: disable=broad-except
        pass

    # On-disk Qdrant size — best-effort. Qdrant 1.7+ exposes
    # disk_data_size on get_collection's response; older builds may
    # return None or omit the field. We catch broadly: a None disk
    # value just means the Settings sidebar shows "size: …" rather
    # than crashing.
    size_mb: int | None = None
    try:
        client = get_qdrant_client()
        info = client.get_collection(COLLECTION_NAME)
        # Different qdrant-client versions expose this differently —
        # try the common attribute names in order.
        raw_bytes: int | None = None
        for attr in ("disk_data_size", "disk_data_size_bytes"):
            v = getattr(info, attr, None)
            if isinstance(v, (int, float)) and v > 0:
                raw_bytes = int(v)
                break
        if raw_bytes is None and hasattr(info, "config"):
            v = getattr(info.config, "disk_data_size", None)
            if isinstance(v, (int, float)) and v > 0:
                raw_bytes = int(v)
        if raw_bytes is not None:
            size_mb = raw_bytes // (1024 * 1024)
    except Exception:  # pylint: disable=broad-except
        size_mb = None

    payload = StatusResponse(
        ready=ready,
        indexed_count=indexed_count,
        version=app.version,
        provider=provider,
        model=model,
        size_mb=size_mb,
    )
    _status_cache["payload"] = payload
    _status_cache["ts"] = now
    return payload


# ---------------------------------------------------------------------------
# /open, /reveal
# ---------------------------------------------------------------------------

@app.get("/open")
def open_file(path: str = Query(...)) -> JSONResponse:
    abs_path = _resolve(path)
    try:
        if sys.platform == "win32":
            os.startfile(str(abs_path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(abs_path)], check=True)
        else:
            subprocess.run(["xdg-open", str(abs_path)], check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise HTTPException(status_code=500, detail=f"open failed: {e}") from e
    return JSONResponse({"ok": True})


@app.get("/reveal")
def reveal_file(path: str = Query(...)) -> JSONResponse:
    """Reveal a file or folder in the OS file browser.

    Earlier versions used `_resolve()` which rejects directories — this
    broke the Settings → Data tab's per-folder Reveal button when the
    target was a folder. Now we accept either: files reveal-in-parent
    (macOS `open -R`, Windows `explorer /select`), folders open the
    folder itself (`open <path>`).
    """
    p = Path(path)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    else:
        p = p.resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"no such path: {path}")

    is_dir = p.is_dir()
    try:
        if sys.platform == "win32":
            if is_dir:
                # `explorer <path>` opens the folder. `/select` is for files.
                subprocess.run(["explorer", str(p)], check=False)
            else:
                # check=False: explorer.exe returns non-zero even on success.
                subprocess.run(["explorer", f"/select,{p}"], check=False)
        elif sys.platform == "darwin":
            if is_dir:
                # `open <dir>` opens the folder. `open -R` would reveal it
                # in its parent — usually not what the user wants for a
                # folder click.
                subprocess.run(["open", str(p)], check=True)
            else:
                subprocess.run(["open", "-R", str(p)], check=True)
        else:
            # Linux / xdg: same `xdg-open` call works for files and dirs.
            target = str(p) if is_dir else str(p.parent)
            subprocess.run(["xdg-open", target], check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise HTTPException(status_code=500, detail=f"reveal failed: {e}") from e
    return JSONResponse({"ok": True})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /ingest  — trigger folder indexing from the GUI
# ---------------------------------------------------------------------------

_ingest_state: dict[str, Any] = {
    "running": False,
    "done": False,
    "error": None,
    # NOTE: `path` moves DURING a sync — `_do_sync` repoints it at each raw
    # root as it walks so that root's Settings row shows its own bar. Between
    # job start and the first root (and during end-of-run cleanup) it holds a
    # human label like "<sync: all enabled folders>" instead, which matches no
    # folder row. Use `roots` when you need the job's scope; `path` is the
    # "what is it working on right now" pointer.
    "path": None,
    # Every raw configured root this job covers, in the same string form
    # /settings/folders returns as `folder.path`. Lets the UI mark all covered
    # rows as part of the run even before the walker reaches them, and lets the
    # global progress panel exist independently of which root is current.
    "roots": [],
    # What kicked this off: "folder" (Add folder/file) | "sync" | "reindex" |
    # "auto" (startup resume / rule change). Drives the panel's title.
    "kind": "idle",
    "files_total": 0,
    "files_done": 0,
    "current_file": None,
    "started_at": None,
    "stopped": False,
    # How the stop was requested: "pause" (user intends to resume — the UI
    # shows a Resume affordance and the run's partial progress) | "cancel"
    # (just end it) | None (no stop requested this job). Pause and cancel
    # share the same drain mechanics; resume is simply the next sync, which
    # picks up from the manifest.
    "stop_kind": None,
    # "idle" before any job; "scanning" while find_candidates is enumerating
    # files (no per-file progress yet); "indexing" once the worker pool has
    # started chewing through the candidate list. The Settings UI's status
    # pill reads this so the user sees scan-vs-ingest distinctly — on a
    # 50K-file root the scan alone can take ~30s.
    "phase": "idle",
}


def _enabled_root_paths() -> list[str]:
    """Raw configured paths of every enabled include_path, in the exact string
    form `/settings/folders` hands the UI. Kept raw (not resolved) so the
    frontend can match them against `folder.path` without normalising."""
    try:
        from src.config.indexing_rules import load_user_rules

        return [ip.path for ip in load_user_rules().include_paths if ip.enabled]
    except Exception:  # noqa: BLE001 — scope reporting must never sink a job
        return []

_stop_event = threading.Event()

# Coalesce flag — flipped True by `_spawn_sync_or_coalesce()` if a rule
# change arrives while a sync is already in flight. The in-flight `_do_sync`
# checks this in its `finally` block and respawns once. Single-job model
# preserved (no queue), but rule edits made mid-sync don't get lost.
_rerun_pending: bool = False
_rerun_lock = threading.Lock()


class IngestRequest(BaseModel):
    path: str


def _rewrite_for_provider(eff) -> bool:
    """Provider-aware default for the query-rewrite step.

    The rewriter is the ACTIVE provider's model, so its value tracks who is
    doing the rewriting (measured, Evaluations/college_data/REPORT.md
    "Rewrite A/B", 2026-08-24):

      - cloud (26B): rewrite helps — recall@k 80% vs 60% without it.
        Honors the user's settings toggle as before.
      - local (3B): rewrite is net harmful — it REPLACES questions
        (typo'd bank query became a "landlord's emergency phone number"
        question) and raw beats it on every register: clean (MRR .628 vs
        .572), typos (recall 100% vs 80%), vague (100% vs 67%). Forced
        off; hybrid dense+BM25 search absorbs typos natively.

    An explicit per-request `rewrite` in the body still overrides both.
    """
    try:
        from src.llm import active_provider

        if active_provider().name == "local":
            return False
    except Exception:  # noqa: BLE001 — never let routing sink a query
        pass
    return eff.rewrite_default


def _require_qdrant() -> None:
    """Fail fast (503) when the search database is down, instead of letting
    an indexing job run for an hour and silently lose every Qdrant write —
    the 2026-08-23 incident cost two full sync runs exactly this way. Guards
    the three button-driven endpoints; the workers re-check for auto-fired
    jobs (startup resume, rule changes), which bypass the endpoints."""
    from src.stage2.db import qdrant_reachable

    ok, url = qdrant_reachable()
    if not ok:
        raise HTTPException(
            status_code=503,
            detail=(
                f"The search database (Qdrant) is not running at {url}, so "
                "indexing can't save results. Start it and try again — "
                "already-indexed files are reused, not re-read. "
                "(Dev: `uv run python scripts/qdrant_up.py`.)"
            ),
        )


def _raise_if_qdrant_down() -> None:
    """Worker-side twin of _require_qdrant: raises RuntimeError so the job's
    except-block records it in _ingest_state['error'] for the Settings UI."""
    from src.stage2.db import qdrant_reachable

    ok, url = qdrant_reachable()
    if not ok:
        raise RuntimeError(
            f"The search database (Qdrant) is not running at {url} — nothing "
            "was indexed. Start it and press Sync; finished work is reused."
        )


@app.post("/ingest")
async def start_ingest(req: IngestRequest) -> dict[str, Any]:
    if _ingest_state["running"]:
        raise HTTPException(status_code=409, detail="Indexing already in progress")
    _require_qdrant()
    folder = Path(req.path)
    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.path}")
    if not folder.is_file() and not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a file or directory: {req.path}")

    _stop_event.clear()
    _ingest_state.update(
        running=True, done=False, error=None, path=req.path,
        roots=[req.path], kind="folder",
        files_total=0, files_done=0, current_file=None,
        started_at=time.time(), stopped=False, stop_kind=None,
        phase="scanning",
    )
    if folder.is_file():
        threading.Thread(target=_do_ingest_file, args=(folder,), daemon=True).start()
    else:
        threading.Thread(target=_do_ingest, args=(folder,), daemon=True).start()
    return {"status": "started", "path": req.path}


def _do_ingest(folder: Path) -> None:
    # Uses the shared callback (defined further down; resolved at call time,
    # and this only ever runs on a worker thread). The inline copy this
    # replaced never flipped `phase` off "scanning", so a single-folder ingest
    # showed the indeterminate scanning bar for its whole run.
    try:
        _raise_if_qdrant_down()
        from src.ingest.walker import run_batch
        from src.stage2.__main__ import ingest_from_manifest
        asyncio.run(run_batch(
            folder,
            push_to_qdrant=True,
            concurrency=4,
            progress_callback=_on_progress_update,
            stop_event=_stop_event,
        ))
        if _stop_event.is_set():
            # Cancelled — same contract as _do_sync: keep what finished,
            # skip the multi-minute end-of-run pass, let the next sync
            # catch up.
            _ingest_state["stopped"] = True
            print("[server] ingest cancelled — skipping end-of-run cleanup", file=sys.stderr)
        else:
            ingest_from_manifest(force=False, verbose=False)
        _ingest_state["done"] = True
    except Exception as exc:
        _ingest_state["error"] = str(exc)
        print(f"[server] ingest error: {exc}", file=sys.stderr)
    finally:
        _ingest_state["running"] = False
        # Invalidate cached folder stats so the next /settings/folders
        # call re-aggregates the post-ingest manifest. Without this,
        # rows show '0 files' for up to FOLDER_STATS_TTL seconds after
        # indexing finishes, even though the manifest was just updated.
        _invalidate_folder_stats_cache()
        # Status cache holds indexed_count / size_mb; same staleness.
        _status_cache["payload"] = None
        _status_cache["ts"] = 0.0


def _do_ingest_file(file_path: Path) -> None:
    # Same shared callback as _do_ingest. total=1 here, so the first call
    # immediately flips phase to "indexing" — a single file has no scan phase
    # worth showing.
    _on_progress_update(0, 1, file_path.name)
    try:
        _raise_if_qdrant_down()
        from src.ingest.walker import ingest_one, _gpu_available
        from src.manifest import Manifest
        from src.stage2.__main__ import ingest_from_manifest

        manifest = Manifest()
        agent = None

        def get_agent():
            nonlocal agent
            if agent is None:
                from src.stage1.summarize import build_agent as _build
                agent = _build()
            return agent

        async def _run():
            return await ingest_one(
                file_path, manifest, get_agent,
                gpu_available=_gpu_available(),
                t4_budget_used_mb=0.0,
            )

        asyncio.run(_run())
        manifest.save()
        _on_progress_update(1, 1, None)
        ingest_from_manifest(force=False, verbose=False)
        _ingest_state["done"] = True
    except Exception as exc:
        _ingest_state["error"] = str(exc)
        print(f"[server] ingest_file error: {exc}", file=sys.stderr)
    finally:
        _ingest_state["running"] = False
        # Invalidate cached folder stats so the next /settings/folders
        # call re-aggregates the post-ingest manifest. Without this,
        # rows show '0 files' for up to FOLDER_STATS_TTL seconds after
        # indexing finishes, even though the manifest was just updated.
        _invalidate_folder_stats_cache()
        # Status cache holds indexed_count / size_mb; same staleness.
        _status_cache["payload"] = None
        _status_cache["ts"] = 0.0


@app.post("/ingest/stop")
def stop_ingest(mode: str = "cancel") -> dict[str, str]:
    """Stop the in-flight job. `mode` is a query param:

    - "pause"  — the user wants the machine back to ask questions; the UI
                 keeps the run's progress visible with a Resume button.
                 Resume = POST /index/sync (manifest-driven, loses nothing).
    - "cancel" — just end it (default; also what pre-mode clients get).

    Both ABORT in-flight file attempts (walker cancels the worker tasks
    within ~0.25s); an aborted file is neither done nor failed, so the next
    sync re-runs exactly those files. Near-instant from the user's side.
    """
    if mode not in ("pause", "cancel"):
        mode = "cancel"
    _stop_event.set()
    # The brief abort window still deserves acknowledgment in the UI —
    # flip the phase so the buttons show "Pausing…/Stopping…" immediately.
    if _ingest_state["running"]:
        _ingest_state["phase"] = "stopping"
        _ingest_state["stop_kind"] = mode
    return {"status": "stopping", "mode": mode}


@app.get("/ingest/status")
def ingest_status() -> dict[str, Any]:
    elapsed: float | None = None
    if _ingest_state["started_at"] is not None:
        elapsed = round(time.time() - _ingest_state["started_at"], 1)
    return {
        "running": _ingest_state["running"],
        "done": _ingest_state["done"],
        "error": _ingest_state["error"],
        # `path` is "what is being walked right now" and moves during a sync.
        # `roots` is the job's full scope and is stable for its lifetime — use
        # that to decide which folder rows belong to this run.
        "path": _ingest_state["path"],
        "roots": _ingest_state.get("roots", []),
        "kind": _ingest_state.get("kind", "idle"),
        "files_total": _ingest_state["files_total"],
        "files_done": _ingest_state["files_done"],
        "current_file": _ingest_state["current_file"],
        "elapsed_s": elapsed,
        "stopped": _ingest_state["stopped"],
        # "pause" | "cancel" | None — how the stop (if any) was requested.
        # Drives whether the UI offers Resume after the run drains.
        "stop_kind": _ingest_state.get("stop_kind"),
        # "scanning" before find_candidates returns; "indexing" once the
        # worker pool starts processing files; "idle" between jobs.
        # Frontend uses this to label the status pill differently during
        # the scan phase (which shows no per-file progress).
        "phase": _ingest_state.get("phase", "idle"),
    }


# ---------------------------------------------------------------------------
# /index/sync and /index/reindex — global Sync/Reindex buttons
# ---------------------------------------------------------------------------
# Backs the Settings → Data tab's two-button design. Both reuse the
# existing _ingest_state + _stop_event machinery (single in-flight job
# across /ingest, /index/sync, /index/reindex). Polling goes through
# the existing GET /ingest/status. See Specs/UI/settings_window.md
# "Two utility buttons" + Plans/UI/Implementation Plan.md "Indexing
# triggers".


class IndexJobResponse(BaseModel):
    status: str  # "started"
    kind: str    # "sync" | "reindex"


def _init_ingest_state(*, path_label: str, kind: str) -> None:
    """Bootstrap _ingest_state for a new job. Caller must already have
    confirmed `_ingest_state["running"] is False` and held that contract
    through to setting running=True.

    `roots` is snapshotted here rather than passed in: every caller of this
    helper is a whole-index job, so the scope is always "the enabled roots".
    """
    _stop_event.clear()
    _ingest_state.update(
        running=True, done=False, error=None,
        path=path_label,
        roots=_enabled_root_paths(), kind=kind,
        files_total=0, files_done=0, current_file=None,
        started_at=time.time(), stopped=False, stop_kind=None,
        # Jobs always start in scanning phase — find_candidates runs before
        # any file work. _on_progress_update flips to "indexing" once the
        # walker reports a non-zero total.
        phase="scanning",
    )


def _on_progress_update(done: int, total: int, current: str | None = None) -> None:
    """Shared progress callback for sync/reindex jobs. Mirrors the inline
    one in _do_ingest. Pulled out so multiple workers reuse the same
    update logic."""
    _ingest_state["files_done"] = done
    _ingest_state["files_total"] = total
    if current is not None:
        _ingest_state["current_file"] = current
    # First progress callback with a known total marks the transition from
    # scan to ingest. Stay in "scanning" until run_batch tells us how many
    # files it found; from then on this is the worker pool churning.
    # "stopping" is sticky — a progress tick from an in-flight worker must
    # not flip the pill back to "indexing" after the user pressed Cancel.
    if total > 0 and _ingest_state.get("phase") not in ("indexing", "stopping"):
        _ingest_state["phase"] = "indexing"


def _drop_manifest_rows_outside_enabled_roots(enabled_prefixes: list[str]) -> int:
    """The `Sync` button must drop manifest rows whose root is no longer
    enabled (e.g., user removed a folder, or toggled it off). `run_batch`
    only walks the enabled roots; it doesn't see the disabled ones, so
    those rows would otherwise stay forever.

    Returns the number of rows dropped. Mirrors `walker.py:632-637`'s
    in-walk drift logic but for cross-walk root removal."""
    from src.manifest import Manifest, REPO_ROOT
    from src.ingest.walker import _delete_if_exists

    manifest = Manifest()
    dropped = 0
    for rel in list(manifest.paths()):
        # Resolve the path the same way the walker does. Manifest paths
        # are stored as the source's str() — typically absolute, but
        # historical entries may be REPO_ROOT-relative.
        absolute = rel if Path(rel).is_absolute() else str(REPO_ROOT / rel)
        if not any(absolute.startswith(p) for p in enabled_prefixes):
            entry = manifest.drop(rel)
            if entry and entry.summary_file:
                _delete_if_exists(entry.summary_file)
            dropped += 1
    if dropped:
        manifest.save()
    return dropped


def _do_sync() -> None:
    """Background worker for POST /index/sync.

    1. Pre-compute enabled roots from `indexing_rules.json`.
    2. Drop manifest rows under any root that's no longer enabled.
    3. Walk each enabled root via `run_batch` (which already handles
       new-files / mtime-changes / deleted-files within its scope).
    4. End-of-run `ingest_from_manifest` for orphan Qdrant cleanup.
    """
    try:
        _raise_if_qdrant_down()
        from src.config.indexing_rules import load_user_rules
        from src.ingest.walker import run_batch
        from src.stage2.__main__ import ingest_from_manifest

        rules = load_user_rules()
        # Keep the raw configured path next to the resolved one. The raw path
        # is what /settings/folders returns as `folder.path`, so pointing
        # `_ingest_state["path"]` at it lets the matching folder row in the
        # Settings UI light up its OWN progress bar as each root is walked.
        roots: list[tuple[str, Path]] = []
        for ip in rules.include_paths:
            if not ip.enabled:
                continue
            p = Path(ip.path).expanduser()
            if p.exists():
                roots.append((ip.path, p))
        enabled_prefixes = [str(p.resolve()) for _, p in roots]

        # Honor `global_rules.categories_enabled.data` for the walker's
        # `_DATA_EXTS_DEFAULT_OFF` filter (.json / .csv / .dat). Without
        # this, even with `data: true` set in indexing_rules.json, the
        # UI Sync button silently skipped data-extension files because
        # `run_batch`'s `include_data` arg defaulted to False — gate #1
        # (extension whitelist) blocked the file before gate #2
        # (`rules.should_index` consulting `categories_enabled`) ever
        # got a chance to weigh in. CLI `--include-data` worked because
        # it set the flag explicitly; the UI had no equivalent. Fix:
        # derive `include_data` from the saved global rule so the UI
        # toggle (when one is wired) and the rules file agree.
        include_data = bool(
            rules.global_rules.categories_enabled.get("data", False)
        )

        # Drift cleanup BEFORE walking — drops manifest rows under
        # disabled/removed roots so end-of-run orphan cleanup picks up
        # the corresponding Qdrant points.
        dropped = _drop_manifest_rows_outside_enabled_roots(enabled_prefixes)
        if dropped:
            print(f"[server] sync drift cleanup: dropped {dropped} rows", file=sys.stderr)

        # Walk every enabled root. run_batch handles its own progress
        # callback per-walk; we reset files_done/files_total per root
        # so progress is observable, even if the global "files_total"
        # only reflects the current root mid-run.
        for raw_path, root in roots:
            if _stop_event.is_set():
                break
            # Point the shared ingest state at THIS folder so its row (and only
            # its row) shows the live progress bar in Settings. Reset counters
            # so the bar restarts per folder instead of carrying the previous
            # root's totals.
            _ingest_state["path"] = raw_path
            _ingest_state["files_done"] = 0
            _ingest_state["files_total"] = 0
            _ingest_state["current_file"] = None
            _ingest_state["phase"] = "scanning"
            asyncio.run(run_batch(
                root,
                push_to_qdrant=True,
                concurrency=4,
                progress_callback=_on_progress_update,
                stop_event=_stop_event,
                include_data=include_data,
            ))

        if _stop_event.is_set():
            # Cancelled: skip the end-of-run Qdrant pass — it can run for
            # minutes, which reads as "Cancel didn't work". Chunk flushes
            # already persisted completed files; the next sync catches up.
            _ingest_state["stopped"] = True
            print("[server] sync cancelled — skipping end-of-run cleanup", file=sys.stderr)
        else:
            # End-of-run orphan cleanup (this is what drops Qdrant points
            # whose source_path is no longer in the manifest).
            ingest_from_manifest(force=False, verbose=False)
        _ingest_state["done"] = True
    except Exception as exc:  # noqa: BLE001 — fail-safe: surface to UI, don't crash sidecar
        _ingest_state["error"] = str(exc)
        print(f"[server] sync error: {exc}", file=sys.stderr)
    finally:
        _ingest_state["running"] = False
        _ingest_state["phase"] = "idle"
        # Invalidate cached folder stats so the next /settings/folders
        # call re-aggregates the post-ingest manifest. Without this,
        # rows show '0 files' for up to FOLDER_STATS_TTL seconds after
        # indexing finishes, even though the manifest was just updated.
        _invalidate_folder_stats_cache()
        # Status cache holds indexed_count / size_mb; same staleness.
        _status_cache["payload"] = None
        _status_cache["ts"] = 0.0
        # /index/plan reflects manifest state; invalidate so the next
        # poll re-walks the roots against the now-updated manifest.
        _invalidate_plan_cache()
        # Coalesce: if any rule edit landed while we were running, respawn
        # exactly one fresh sync so the new rules.json gets picked up.
        # Single-job model preserved (the new sync starts after this one's
        # `running=False`). The flag is one-shot — if N edits arrive during
        # one sync, they all collapse into a single rerun.
        global _rerun_pending
        with _rerun_lock:
            should_rerun = _rerun_pending
            _rerun_pending = False
        if should_rerun:
            print(
                "[server] sync coalesce: rule changed mid-run, respawning",
                file=sys.stderr,
            )
            _init_ingest_state(path_label="<sync: coalesced rerun>", kind="sync")
            threading.Thread(target=_do_sync, daemon=True).start()


def _do_reindex() -> None:
    """Background worker for POST /index/reindex.

    Calls `pipeline.reset()` (drops summaries + manifest + both Qdrant
    collections), then runs `_do_sync()` from a clean slate. The reset
    step reuses the same proven helper that `just reset-index` calls.
    """
    try:
        from src.pipeline import reset as _reset

        stats = _reset()
        print(f"[server] reindex reset stats: {stats}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        _ingest_state["error"] = str(exc)
        _ingest_state["running"] = False
        print(f"[server] reindex reset error: {exc}", file=sys.stderr)
        return

    # Sync from clean slate. _do_sync sets running=False in its finally.
    _do_sync()


def _spawn_sync_or_coalesce(*, reason: str) -> str:
    """Auto-fire helper for non-button code paths (rule changes, app launch
    auto-resume). Returns one of: "started" / "coalesced" / "noop".

    Contract:
      - If no sync is running → start one immediately.
      - If a sync IS running → set rerun_pending=True. The in-flight sync's
        finally block will respawn once. Multiple calls during one run
        collapse into a single rerun (no queue).
      - Caller should treat all three return values as success — whatever
        state it ends in, the user's request is going to land.

    `reason` is purely a stderr breadcrumb for debugging — it shows up in
    logs as "[server] auto-sync: <reason>" so you can tell why a sync
    fired without a button press.
    """
    global _rerun_pending
    if _ingest_state["running"]:
        with _rerun_lock:
            _rerun_pending = True
        print(f"[server] auto-sync deferred (running): {reason}", file=sys.stderr)
        return "coalesced"
    _init_ingest_state(path_label=f"<auto-sync: {reason}>", kind="auto")
    threading.Thread(target=_do_sync, daemon=True).start()
    print(f"[server] auto-sync started: {reason}", file=sys.stderr)
    return "started"


def _maybe_auto_resume_on_startup() -> None:
    """Called once during sidecar startup. Fires `_do_sync()` if there's
    any drift between the manifest and the current rules — i.e., if the
    user has enabled folders whose files aren't all in the manifest, or
    manifest rows whose root is no longer enabled.

    For a packaged user this is the "I closed Magpie mid-index, double-
    clicked it again, expected it to pick up where it left off" path.
    `_do_sync()` is idempotent: if there's nothing to do, the diff-walk
    is a no-op (~30s scan, zero file work). So even erring on the side
    of always firing is cheap.
    """
    try:
        # Local import — `_maybe_auto_resume_on_startup` is defined above the
        # Settings-endpoints block where `load_user_rules` is imported at
        # module scope. Local import keeps this function self-contained and
        # robust to definition-order shuffling.
        from src.config.indexing_rules import load_user_rules as _load_rules
        rules = _load_rules()
    except Exception as e:  # noqa: BLE001
        print(f"[server] auto-resume: rules load failed, skipping: {e}", file=sys.stderr)
        return
    enabled_paths = [ip for ip in rules.include_paths if ip.enabled]
    if not enabled_paths:
        # Empty corpus / first launch — nothing to resume.
        return
    _spawn_sync_or_coalesce(reason="startup-resume")


@app.post("/index/sync")
def index_sync() -> IndexJobResponse:
    """Pick up new files; drop files that no longer match the rules.
    409 if any indexing job is already running."""
    if _ingest_state["running"]:
        raise HTTPException(status_code=409, detail="Indexing already in progress")
    _require_qdrant()
    _init_ingest_state(path_label="<sync: all enabled folders>", kind="sync")
    threading.Thread(target=_do_sync, daemon=True).start()
    return IndexJobResponse(status="started", kind="sync")


@app.post("/index/reindex")
def index_reindex() -> IndexJobResponse:
    """Wipe the entire index, then sync from scratch. Destructive but
    reversible by syncing again. 409 if any indexing job is already
    running. Frontend is responsible for the typed-confirmation modal
    before calling this."""
    if _ingest_state["running"]:
        raise HTTPException(status_code=409, detail="Indexing already in progress")
    _require_qdrant()
    _init_ingest_state(path_label="<reindex: all enabled folders>", kind="reindex")
    threading.Thread(target=_do_reindex, daemon=True).start()
    return IndexJobResponse(status="started", kind="reindex")


# ---------------------------------------------------------------------------
# Local-model install — the Settings card's download flow.
#
# All logic lives in src.local_install; these are thin HTTP shims following
# the /ingest + /ingest/status polling pattern. Lazy imports keep the module
# (and its transitive profiles/device imports) off the sidecar's cold-start
# path — the first status poll pays it instead.
# ---------------------------------------------------------------------------


@app.get("/local/status")
def local_status() -> dict[str, Any]:
    """Install state for both halves of Local: the LLM (binary + weights +
    projector — what the provider toggle needs) and the visual tier (what T4
    indexing uses regardless of provider). Poll while `running`."""
    from src import local_install

    return local_install.status()


@app.post("/local/install", status_code=202)
def local_install_start() -> dict[str, str]:
    """Download every missing local artifact, in a background worker.
    202 on start; 409 when a download is already running. Progress via
    GET /local/status. Partial downloads resume — cancelling loses nothing."""
    from src import local_install

    started, msg = local_install.start_install()
    if not started:
        raise HTTPException(status_code=409, detail=msg)
    return {"status": msg}


@app.post("/local/install/cancel")
def local_install_cancel() -> dict[str, str]:
    from src import local_install

    ok, msg = local_install.cancel_install()
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    return {"status": msg}


@app.delete("/local/model")
def local_model_delete(component: str = Query(default="all")) -> dict[str, Any]:
    """Reclaim downloaded model disk. component: llm | visual | all.
    Refuses (409) while a download runs. The llama-server binary stays —
    it is 40 MB and platform-specific; deleting it buys nothing."""
    from src import local_install

    if component not in ("llm", "visual", "all"):
        raise HTTPException(status_code=422, detail="component must be llm, visual or all")
    result = local_install.delete_models(component)
    if result["error"]:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


# Plan endpoint cache. /index/plan does a real filesystem walk per enabled
# root via find_candidates — cheap-ish (~30s on a 50K-file root) but the
# Settings UI polls /ingest/status on a tick and would otherwise hammer
# this endpoint on every refresh. Cache for a few seconds; invalidate
# when sync starts/finishes via the same hooks as folder stats.
_plan_cache: dict[str, Any] = {"payload": None, "ts": 0.0}
_PLAN_TTL_S = 10.0


def _invalidate_plan_cache() -> None:
    _plan_cache["payload"] = None
    _plan_cache["ts"] = 0.0


def _compute_index_plan() -> dict[str, Any]:
    """Run `find_candidates` over each enabled root and report per-folder
    file counts vs how many are already in the manifest.

    Approximation: a file is counted as "remaining" if its rel_path is
    NOT in the manifest at all. Files whose size has changed (would
    re-summarize on next sync) are NOT counted as remaining — that
    would require statting every candidate (~50ms × N files), and
    the UX value here is "rough total left to do," not exact.

    Returns:
      {
        "folders": [
          {
            "path": str,        # raw user-facing path (rules.json value)
            "enabled": bool,
            "total": int,       # candidates under this root
            "remaining": int,   # candidates not in manifest yet
          },
          ...
        ],
        "grand_total": int,
        "grand_remaining": int,
      }
    """
    from src.config.indexing_rules import (
        load_indexing_rules,
        load_user_rules as _load_rules,
    )
    from src.ingest.common import source_rel_path
    from src.ingest.walker import find_candidates
    from src.manifest import Manifest

    user_rules = _load_rules()
    indexing_rules = load_indexing_rules()
    manifest = Manifest()
    manifest_keys = set(manifest.entries.keys())

    folders_out: list[dict[str, Any]] = []
    grand_total = 0
    grand_remaining = 0

    for ip in user_rules.include_paths:
        try:
            p = Path(ip.path).expanduser()
        except OSError:
            p = Path(ip.path)
        # Disabled folders are reported with zero counts — UI can still
        # show them in the list but they shouldn't contribute to "files
        # left to index." Keeps the grand-total honest.
        if not ip.enabled or not p.exists():
            folders_out.append({
                "path": ip.path,
                "enabled": ip.enabled,
                "total": 0,
                "remaining": 0,
            })
            continue
        try:
            files, _ignored, _asset = find_candidates(
                p, indexing_rules=indexing_rules, include_data=False,
            )
        except Exception as e:  # noqa: BLE001 — never crash plan on one bad root
            print(f"[server] /index/plan scan failed for {ip.path}: {e}", file=sys.stderr)
            folders_out.append({
                "path": ip.path,
                "enabled": ip.enabled,
                "total": 0,
                "remaining": 0,
            })
            continue
        total = len(files)
        remaining = sum(
            1 for f in files if source_rel_path(f) not in manifest_keys
        )
        folders_out.append({
            "path": ip.path,
            "enabled": ip.enabled,
            "total": total,
            "remaining": remaining,
        })
        grand_total += total
        grand_remaining += remaining

    return {
        "folders": folders_out,
        "grand_total": grand_total,
        "grand_remaining": grand_remaining,
    }


@app.get("/index/plan")
def index_plan() -> dict[str, Any]:
    """Read-only preview of what `/index/sync` would do.

    Walks each enabled root (Phase A only — no ingestion) and returns
    per-folder counts. The Settings UI uses the grand totals to show
    "8,200 files across 4 folders, 1,234 still to index" without firing
    any work.

    Cached for 10s — Settings polls every couple of seconds and the
    walk is non-trivial (filesystem stats × N files). Refreshed
    automatically after sync completes (same invalidation as folder
    stats / status caches)."""
    now = time.monotonic()
    if (
        _plan_cache["payload"] is not None
        and now - _plan_cache["ts"] < _PLAN_TTL_S
    ):
        return _plan_cache["payload"]
    payload = _compute_index_plan()
    _plan_cache["payload"] = payload
    _plan_cache["ts"] = now
    return payload


# ---------------------------------------------------------------------------
# Settings endpoints — folder management + shortcut read
# ---------------------------------------------------------------------------

from src.config.indexing_rules import (
    load_user_rules,
    save_user_rules,
    IncludePath as _IncludePath,
)

_SHORTCUT_FILE_PATH = APP_DATA_DIR / "shortcut.json"


_folder_stats_cache: dict[str, Any] = {"payload": None, "ts": 0.0}
_FOLDER_STATS_TTL = 3.0


def _compute_folder_stats() -> dict[str, dict[str, Any]]:
    """Return {folder_path: {files, size_bytes, last_read_at}} aggregated
    from the manifest. Cheap-ish (~O(manifest entries)) but cached for
    a few seconds so the Settings UI's poll-on-tick doesn't re-scan
    on every refresh.

    `last_read_at` is the max `ingested_at` across files under that
    root (= when this folder's contents most recently landed in
    Qdrant). Folders with no entries return zeros.
    """
    from src.manifest import Manifest, REPO_ROOT
    manifest = Manifest()
    rules = load_user_rules()

    # Pre-resolve each include_path's absolute prefix once.
    roots: list[tuple[str, str]] = []  # (raw_path, resolved_prefix)
    for ip in rules.include_paths:
        try:
            resolved = str(Path(ip.path).expanduser().resolve())
        except OSError:
            resolved = ip.path
        roots.append((ip.path, resolved))

    out: dict[str, dict[str, Any]] = {
        raw: {"files": 0, "size_bytes": 0, "last_read_at": None, "failed": 0}
        for raw, _ in roots
    }

    for rel, entry in manifest.entries.items():
        absolute = rel if Path(rel).is_absolute() else str(REPO_ROOT / rel)
        for raw, prefix in roots:
            # Use os.sep, NOT a hardcoded "/". On Windows both `absolute`
            # (manifest path) and `prefix` (resolved include_path) come back
            # with backslashes, so `prefix + "/"` never matched a file living
            # in a subfolder — every real folder showed "Not read yet" even
            # after it was fully summarized, while a single-file include_path
            # still matched via the `==` branch. os.sep is "\\" on Windows and
            # "/" on macOS/Linux, so this is correct on all three.
            if absolute == prefix or absolute.startswith(prefix + os.sep):
                stats = out[raw]
                stats["files"] += 1
                stats["size_bytes"] += int(entry.size or 0)
                # Files whose last attempt failed (walker's mark_error) —
                # surfaced per-row so failures stop being invisible.
                if (entry.skip_reason or "").startswith("error: "):
                    stats["failed"] += 1
                if entry.ingested_at:
                    prev = stats["last_read_at"]
                    if prev is None or entry.ingested_at > prev:
                        stats["last_read_at"] = entry.ingested_at
                # NO break: credit the file to EVERY root whose subtree holds
                # it. With nested roots (a folder row plus a row for one of
                # its subfolders), the old first-match-wins break let the
                # parent claim every file, so the subfolder row aggregated
                # zero and showed "Not read yet" forever — however many times
                # its files were actually indexed. Each row now reports its
                # own subtree honestly; a file under nested roots appears in
                # both rows' counts, which is the truthful per-row answer.

    return out


def _invalidate_folder_stats_cache() -> None:
    """Drop the cached folder stats so the next /settings/folders call
    re-aggregates from a fresh manifest. Called after ingest completes
    — without this, a folder that just finished indexing would keep
    showing '0 files · — · not yet read' for the cache TTL window
    because the cache was populated mid-ingest."""
    _folder_stats_cache["payload"] = None
    _folder_stats_cache["ts"] = 0.0


def _get_folder_stats() -> dict[str, dict[str, Any]]:
    now = time.monotonic()
    if (
        _folder_stats_cache["payload"] is not None
        and now - _folder_stats_cache["ts"] < _FOLDER_STATS_TTL
    ):
        return _folder_stats_cache["payload"]
    payload = _compute_folder_stats()
    _folder_stats_cache["payload"] = payload
    _folder_stats_cache["ts"] = now
    return payload


@app.get("/settings/folders")
def settings_get_folders() -> dict[str, Any]:
    rules = load_user_rules()
    stats = _get_folder_stats()
    folders = []
    for p in rules.include_paths:
        s = stats.get(p.path, {"files": 0, "size_bytes": 0, "last_read_at": None})
        folders.append({
            "path": p.path,
            "enabled": p.enabled,
            "display_name": p.display_name,  # may be None
            "files": s["files"],
            "size_bytes": s["size_bytes"],
            "last_read_at": s["last_read_at"],  # ISO string or None
            # Files under this root whose last read attempt failed —
            # drives the amber "N couldn't be read" note in the row.
            "failed": s.get("failed", 0),
        })
    return {
        "folders": folders,
        "ingest_running": _ingest_state["running"],
    }


@app.get("/index/failures")
def index_failures() -> dict[str, Any]:
    """Every file whose last read attempt failed, with the recorded reason.

    Backs the Data tab's "files that couldn't be read" panel — before this,
    failures lived only in logs and the folder just looked mysteriously
    smaller (2026-08-24). Reasons come from Manifest.mark_error; the
    "error: " prefix is stripped for display. Reindex (or editing the
    file) retries them.
    """
    from src.manifest import Manifest

    failures = []
    for rel, entry in Manifest().entries.items():
        reason = entry.skip_reason or ""
        if reason.startswith("error: "):
            failures.append({"path": rel, "reason": reason[len("error: "):]})
        if len(failures) >= 500:  # sanity cap; nobody scrolls further
            break
    return {"failures": failures}


class FolderAddRequest(BaseModel):
    path: str


@app.post("/settings/folders")
def settings_add_folder(req: FolderAddRequest) -> dict[str, str]:
    """Add (or re-enable) a folder. Auto-fires `_do_sync()` so the new
    folder's files get ingested without a separate "Sync" click. If a
    sync is already running, the rule edit is coalesced — the in-flight
    sync's finally block respawns once with the fresh rules."""
    rules = load_user_rules()
    target = str(Path(req.path).expanduser().resolve())
    for entry in rules.include_paths:
        if str(Path(entry.path).expanduser().resolve()) == target:
            if not entry.enabled:
                entry.enabled = True
                save_user_rules(rules)
                _spawn_sync_or_coalesce(reason=f"folder-enabled: {target}")
                return {"status": "enabled"}
            return {"status": "already_exists"}
    rules.include_paths.append(_IncludePath(path=target, enabled=True))
    save_user_rules(rules)
    _spawn_sync_or_coalesce(reason=f"folder-added: {target}")
    return {"status": "added"}


@app.delete("/settings/folders")
def settings_remove_folder(path: str) -> dict[str, str]:
    """Remove a folder. Auto-fires `_do_sync()` so the orphan-cleanup pass
    drops the folder's manifest rows + Qdrant points. Without auto-fire,
    queries would keep returning hits from the just-removed folder until
    the user manually clicked Sync."""
    rules = load_user_rules()
    target = str(Path(path).expanduser().resolve())
    before = len(rules.include_paths)
    rules.include_paths = [
        p for p in rules.include_paths
        if str(Path(p.path).expanduser().resolve()) != target
    ]
    save_user_rules(rules)
    if len(rules.include_paths) < before:
        _spawn_sync_or_coalesce(reason=f"folder-removed: {target}")
    return {"status": "removed"}


@app.get("/settings/shortcut")
def settings_get_shortcut() -> dict[str, str]:
    if _SHORTCUT_FILE_PATH.exists():
        try:
            import json as _json
            data = _json.loads(_SHORTCUT_FILE_PATH.read_text(encoding="utf-8"))
            return {"shortcut": data.get("shortcut", "Alt+Space")}
        except Exception:
            pass
    return {"shortcut": "Alt+Space"}


class ShortcutPutRequest(BaseModel):
    shortcut: str = Field(min_length=1, max_length=64)


@app.put("/settings/shortcut")
def settings_put_shortcut(req: ShortcutPutRequest) -> dict[str, str]:
    """Atomic write to shortcut.json. Tauri-side picks up the change on
    next app launch; we don't try to re-register the global shortcut
    in-flight (that's a Tauri API concern, not the sidecar's)."""
    import json as _json
    _SHORTCUT_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SHORTCUT_FILE_PATH.with_suffix(_SHORTCUT_FILE_PATH.suffix + ".tmp")
    tmp.write_text(
        _json.dumps({"shortcut": req.shortcut}, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(_SHORTCUT_FILE_PATH)
    return {"status": "saved", "shortcut": req.shortcut}


class FolderPatch(BaseModel):
    """PATCH /settings/folders body. Identifies the folder by `path`;
    any of `enabled` / `display_name` may be set. Unset fields are
    left unchanged. Setting `display_name` to `null` clears the
    override (UI falls back to the path's basename)."""
    path: str
    enabled: bool | None = None
    display_name: str | None = None


@app.patch("/settings/folders")
def settings_patch_folder(req: FolderPatch) -> dict[str, Any]:
    """Patch an existing IncludePath. 404 if path not found. The
    Settings UI's Data tab uses this for the per-row toggle and for
    the overflow-menu rename action.

    Auto-fires `_do_sync()` only when `enabled` actually changed —
    `display_name` is purely cosmetic (no ingest impact) so it
    shouldn't trigger a possibly-expensive walk."""
    rules = load_user_rules()
    target = str(Path(req.path).expanduser().resolve())
    for entry in rules.include_paths:
        if str(Path(entry.path).expanduser().resolve()) == target:
            enabled_changed = (
                req.enabled is not None and req.enabled != entry.enabled
            )
            if req.enabled is not None:
                entry.enabled = req.enabled
            # display_name is patched even when None — None means
            # "clear the override" (per the model docstring). Use
            # FastAPI's "unset" idiom would conflict with that; we
            # rely on the request body explicitly including the field.
            # Pydantic exclude_unset gates this for us via model_fields_set.
            if "display_name" in req.model_fields_set:
                entry.display_name = req.display_name
            save_user_rules(rules)
            if enabled_changed:
                action = "enabled" if entry.enabled else "disabled"
                _spawn_sync_or_coalesce(reason=f"folder-{action}: {entry.path}")
            return {
                "status": "updated",
                "path": entry.path,
                "enabled": entry.enabled,
                "display_name": entry.display_name,
            }
    raise HTTPException(status_code=404, detail=f"folder not found: {req.path}")


# ---------------------------------------------------------------------------
# Settings endpoints — Search & AI / App appearance / providers
# ---------------------------------------------------------------------------
# Settings UI's Search & AI tab + Shortcut & App tab. All four routes
# below read/patch the layered config (settings.json over magpie_defaults.json
# over hardcoded). Spec: Specs/UI/settings_window.md.

from src.config.settings import (
    effective_settings as _effective_settings,
    patch_user_settings as _patch_user_settings,
)


class SearchSettingsResponse(BaseModel):
    provider: str  # "local" | "cloud"
    model: str  # resolved per-provider (cloud_model for cloud, model_env for local)
    top_k: int
    rewrite: bool
    temperature: float
    cite_sources_inline: bool
    # When True, "list all my X" / "what are every Y" style questions
    # widen top_k, suppress cross-encoder rerank, and add an
    # ENUMERATION MODE prompt addition. Off = every query takes the
    # standard semantic-retrieval path.
    enumerate_lists: bool


class SearchSettingsPatch(BaseModel):
    provider: str | None = Field(default=None, pattern="^(local|cloud)$")
    top_k: int | None = Field(default=None, ge=1, le=20)
    rewrite: bool | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    cite_sources_inline: bool | None = None
    enumerate_lists: bool | None = None


def _resolved_model_name(provider: str) -> str:
    """The model the user-visible search-pill / status-footer should show."""
    if provider == "cloud":
        # Cloud routing now lives in secrets.json. Read whichever cloud
        # provider is currently active and surface its per-provider model.
        from src.config.secrets import load_secrets
        try:
            s = load_secrets()
            if s.cloud_provider == "moonshot":
                return s.moonshot_model or "Moonshot"
            return s.openrouter_model or "OpenRouter"
        except Exception:  # noqa: BLE001
            return "Cloud"
    # Local: name the launch profile the pool will actually spawn, so the
    # pill tracks `LLAMA_SERVER_TEXT_MODEL` instead of always reading
    # "Gemma 4" during an LFM2.5 run. Falls back to the env var if the
    # profile registry can't answer (unknown profile name in env).
    try:
        from src.inference.profiles import active_profile, short_model_name

        profile = active_profile()
        return f"{short_model_name(profile)} ({profile.args.quant})"
    except Exception:  # noqa: BLE001
        return os.environ.get("LOCAL_MODEL", "Gemma 4")


@app.get("/settings/search")
def settings_get_search() -> SearchSettingsResponse:
    eff = _effective_settings()
    return SearchSettingsResponse(
        provider=eff.provider,
        model=_resolved_model_name(eff.provider),
        top_k=eff.top_k,
        rewrite=eff.rewrite_default,
        temperature=eff.temperature,
        cite_sources_inline=eff.cite_sources_inline,
        enumerate_lists=eff.enumerate_lists,
    )


@app.patch("/settings/search")
def settings_patch_search(req: SearchSettingsPatch) -> SearchSettingsResponse:
    """PATCH any subset of search fields. None = leave unchanged.
    Frontend can chain a PATCH then GET, or just trust the response
    here as the new effective view."""
    kwargs: dict[str, Any] = {}
    if req.provider is not None:
        kwargs["provider"] = req.provider
    if req.top_k is not None:
        kwargs["top_k"] = req.top_k
    if req.rewrite is not None:
        kwargs["rewrite_default"] = req.rewrite
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.cite_sources_inline is not None:
        kwargs["cite_sources_inline"] = req.cite_sources_inline
    if req.enumerate_lists is not None:
        kwargs["enumerate_lists"] = req.enumerate_lists
    if kwargs:
        _patch_user_settings(**kwargs)
    return settings_get_search()


class ProvidersInfo(BaseModel):
    local: dict[str, Any]  # {available, model, downloaded}
    cloud: dict[str, Any]  # {available, model, configured}


@app.get("/settings/search/providers")
def settings_get_providers() -> ProvidersInfo:
    """Per-provider availability for the Search & AI tab's two cards.
    v1 stub — local "downloaded" is best-effort (the llama-server
    binary's presence; the model itself is downloaded on first use).
    Cloud reports configured iff the active cloud provider's API key
    in secrets.json is non-empty."""
    from src.config.secrets import load_secrets

    # Local: real readiness, not the old hardcoded stub. `downloaded` means
    # binary + weights + projector are all on disk (src.local_install PR 5);
    # the visual tier is deliberately excluded — T4 indexing uses it
    # regardless of provider, and /local/status reports it separately.
    from src import local_install

    try:
        _llm = local_install._llm_spec()
        local_model = f"{_llm['repo'].rsplit('/', 1)[-1]} ({_llm['quant']})"
        local_downloaded = local_install.is_llm_ready()
    except Exception:  # noqa: BLE001 — never let the settings tab 500 on this
        local_model = "local model"
        local_downloaded = False

    # Cloud: introspect the active provider's per-provider key. If the
    # user has cloud_provider="openrouter" but only has a moonshot key,
    # we still report unconfigured — matches the runtime behavior of
    # build_chat_model() which wouldn't be able to authenticate.
    cloud_provider = "openrouter"
    cloud_model_name = ""
    cloud_configured = False
    try:
        s = load_secrets()
        cloud_provider = s.cloud_provider
        if s.cloud_provider == "moonshot":
            cloud_model_name = s.moonshot_model
            cloud_configured = bool(s.moonshot_api_key.strip())
        else:
            cloud_model_name = s.openrouter_model
            cloud_configured = bool(s.openrouter_api_key.strip())
    except Exception:  # noqa: BLE001
        pass

    return ProvidersInfo(
        local={
            "available": local_downloaded,
            "model": local_model,
            "downloaded": local_downloaded,
        },
        cloud={
            "available": cloud_configured,
            "model": cloud_model_name,
            "configured": cloud_configured,
            "provider": cloud_provider,  # internal info; UI may surface for debug
        },
    )


class AppSettingsResponse(BaseModel):
    theme: str  # "system" | "light" | "dark"
    accent: str  # "ink" | "amber" | "jade" | "rose"
    launch_at_login: bool


class AppSettingsPatch(BaseModel):
    theme: str | None = Field(default=None, pattern="^(system|light|dark)$")
    accent: str | None = Field(default=None, pattern="^(ink|amber|jade|rose)$")
    launch_at_login: bool | None = None


@app.get("/settings/app")
def settings_get_app() -> AppSettingsResponse:
    eff = _effective_settings()
    return AppSettingsResponse(
        theme=eff.theme,
        accent=eff.accent,
        launch_at_login=eff.launch_at_login,
    )


@app.patch("/settings/app")
def settings_patch_app(req: AppSettingsPatch) -> AppSettingsResponse:
    kwargs: dict[str, Any] = {}
    for field in ("theme", "accent", "launch_at_login"):
        value = getattr(req, field)
        if value is not None:
            kwargs[field] = value
    if kwargs:
        _patch_user_settings(**kwargs)
    return settings_get_app()


# ---------------------------------------------------------------------------
# Settings endpoints — exclusions (paths + globs)
# ---------------------------------------------------------------------------
# Backs the Data tab's Exclusions sub-panel. UserRules carries the
# user-level lists; magpie_defaults.json carries the immutable safety
# rails (which the UI doesn't surface).


class ExclusionsResponse(BaseModel):
    paths: list[str]
    globs: list[str]


class ExclusionAddRequest(BaseModel):
    path: str | None = None
    glob: str | None = None


@app.get("/settings/exclusions")
def settings_get_exclusions() -> ExclusionsResponse:
    rules = load_user_rules()
    return ExclusionsResponse(
        paths=list(rules.exclude_paths),
        globs=list(rules.global_rules.exclude_globs),
    )


@app.post("/settings/exclusions")
def settings_add_exclusion(req: ExclusionAddRequest) -> dict[str, str]:
    if (req.path is None) == (req.glob is None):
        # Exactly one of {path, glob} must be set.
        raise HTTPException(
            status_code=400,
            detail="exactly one of `path` or `glob` must be provided",
        )
    rules = load_user_rules()
    if req.path is not None:
        target = str(Path(req.path).expanduser().resolve())
        if target in rules.exclude_paths:
            return {"status": "already_exists"}
        rules.exclude_paths.append(target)
    else:
        if req.glob in rules.global_rules.exclude_globs:
            return {"status": "already_exists"}
        rules.global_rules.exclude_globs.append(req.glob or "")
    save_user_rules(rules)
    return {"status": "added"}


@app.delete("/settings/exclusions")
def settings_remove_exclusion(
    type: str = Query(..., pattern="^(path|glob)$"),
    value: str = Query(..., min_length=1),
) -> dict[str, str]:
    """Delete a single exclude entry. Query: ?type=path|glob&value=..."""
    rules = load_user_rules()
    if type == "path":
        target = str(Path(value).expanduser().resolve())
        before = len(rules.exclude_paths)
        rules.exclude_paths = [p for p in rules.exclude_paths if p != target]
        if len(rules.exclude_paths) == before:
            raise HTTPException(status_code=404, detail=f"path not found: {value}")
    else:
        before = len(rules.global_rules.exclude_globs)
        rules.global_rules.exclude_globs = [
            g for g in rules.global_rules.exclude_globs if g != value
        ]
        if len(rules.global_rules.exclude_globs) == before:
            raise HTTPException(status_code=404, detail=f"glob not found: {value}")
    save_user_rules(rules)
    return {"status": "removed"}


# ---------------------------------------------------------------------------
# /diagnostics/why-not — explain why a path was/wasn't indexed
# ---------------------------------------------------------------------------
# Surfaces the (bool, reason) pair from IndexingRules.should_index() that
# the CLI's `walk-explain` already uses. Powers the "Why isn't this
# indexed?" affordance in the Settings → Data tab and the future
# Spotlight-style file diagnostic. The reason strings are already part
# of the public API (Plans/Ingestion Rules/Implementation Plan.md §4).


@app.get("/diagnostics/why-not")
def diagnostics_why_not(path: str = Query(...)) -> dict[str, Any]:
    """Run should_index(path) and return the verdict + reason.

    `indexed` is the ground-truth bool (True = file would be indexed if
    a sync ran now). `reason` is the short explanation suitable for the
    GUI's tooltip/popover. `resolved_path` echoes back the absolute
    path we actually evaluated, so the caller can confirm symlink/
    relative-path resolution matched their expectation.
    """
    from src.config.indexing_rules import load_indexing_rules

    rules = load_indexing_rules()
    try:
        resolved = str(Path(path).expanduser().resolve())
    except OSError as e:
        return {"path": path, "resolved_path": None, "indexed": False,
                "reason": f"cannot resolve path: {e}"}
    indexed, reason = rules.should_index(path)
    return {
        "path": path,
        "resolved_path": resolved,
        "indexed": indexed,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# /recents — the user's last N questions, with cached results
# ---------------------------------------------------------------------------
# Backs the ask bar's "RECENT" panel. The /query endpoint appends new
# entries automatically (see _record_recent below). The frontend can
# read /recents to populate the typing state and replay a recent by id
# without re-running the pipeline.
# Spec: Specs/UI/ask_bar.md, "Recents storage shape".

from src.recents import list_recents as _list_recents, get_recent as _get_recent


@app.get("/recents")
def recents_list() -> dict[str, Any]:
    """Return the last N persisted recents, newest-first.

    Each entry includes `is_stale: bool` — True when the search index
    has been updated since the entry was persisted. The frontend uses
    this to decide between rendering the cached payload (fresh) vs
    firing a fresh /query (stale). model_dump(by_alias=False,
    exclude_unset=False) keeps is_stale in the response even though
    Field(exclude=True) excludes it from the persisted JSON."""
    return {
        "recents": [
            {**r.model_dump(mode="json"), "is_stale": r.is_stale}
            for r in _list_recents()
        ]
    }


@app.get("/recents/{entry_id}")
def recents_get(entry_id: str) -> dict[str, Any]:
    """Look up a recent by id. Used by the ask bar's replay path.

    Includes `is_stale: bool` so the frontend can re-check freshness
    immediately before rendering — list_recents stamped the field at
    fetch-time, but a sync may have completed between the recents
    list-fetch and the user's click."""
    entry = _get_recent(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"recent not found: {entry_id}")
    return {**entry.model_dump(mode="json"), "is_stale": entry.is_stale}


# ---------------------------------------------------------------------------
# Feedback — the post-answer "Feedback" box (src/feedback.py).
# ---------------------------------------------------------------------------

class FeedbackContext(BaseModel):
    question: str = ""
    answer: str = ""


class FeedbackRequest(BaseModel):
    message: str
    # Present ONLY when the user ticked "include my question and answer" —
    # the privacy contract lives in src/feedback.py's module docstring.
    context: FeedbackContext | None = None


@app.post("/feedback")
async def post_feedback(req: FeedbackRequest):
    from src import feedback

    if not feedback.webhook_configured():
        raise HTTPException(
            status_code=503,
            detail="This build has no feedback destination configured — "
            "you can open a GitHub issue instead.",
        )
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Feedback message is empty.")
    context = req.context.model_dump() if req.context else None
    # to_thread: delivery is a blocking HTTP POST with a 10s timeout.
    return await asyncio.to_thread(feedback.submit, message, context)


@app.on_event("startup")
def _flush_feedback_outbox() -> None:
    """Feedback typed offline gets retried on the next launch — in a
    daemon thread so a slow webhook can't delay the port announcement."""
    from src import feedback

    if feedback.webhook_configured():
        threading.Thread(target=feedback.flush_outbox, daemon=True).start()


# ---------------------------------------------------------------------------
# Sidecar entrypoint: pick a free port, print it, serve.
# ---------------------------------------------------------------------------

def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_sidecar() -> None:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0, help="0 = pick free port")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    port = args.port or _pick_free_port()
    # First line of stdout is the port contract Tauri reads.
    print(f"MAGPIE_PORT={port}", flush=True)
    uvicorn.run(app, host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    _run_sidecar()
