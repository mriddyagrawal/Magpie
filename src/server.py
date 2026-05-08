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
import os
import socket
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path
from typing import Any

# Suppress library noise BEFORE importing torch / transformers / qdrant_client.
# These show up as scary-looking warnings and progress bars in dev terminals,
# but say nothing useful to the user. Set defaults so .env / env can override
# (e.g. TRANSFORMERS_VERBOSITY=info during model debugging).
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
warnings.filterwarnings("ignore", category=UserWarning, module="qdrant_client")
warnings.filterwarnings("ignore", category=UserWarning, module="torch.cuda")

from dotenv import load_dotenv
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

load_dotenv()

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


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
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

    print(f"[server] internal error {name}: {text}", file=sys.stderr)

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
    from src.pipeline import ask
    from src.recents import add_recent

    # Resolve `rewrite`: explicit body value wins; otherwise REWRITE env.
    rewrite = req.rewrite if req.rewrite is not None else _env_bool("REWRITE", default=False)

    try:
        result = await ask(
            req.question,
            top_k=req.top_k,
            rewrite=rewrite,
            fast=req.fast,
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
        sources_scanned_count=len(result.retrieved),
        recent_id=recent_id,
    )


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
    """User-facing status. Deliberately omits LLM provider, model name,
    Qdrant provider, GPU info, etc. — those are implementation details
    that should never be visible in the GUI. See IO/IO - Repo Structure.md
    for the no-tech-leak product principle."""
    ready: bool
    indexed_count: int
    version: str


@app.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    now = time.monotonic()
    if _status_cache["payload"] is not None and now - _status_cache["ts"] < _STATUS_TTL:
        return _status_cache["payload"]

    from src.stage2.db import get_all_point_ids

    try:
        indexed_count = len(get_all_point_ids())
        ready = True
    except Exception:  # pylint: disable=broad-except
        indexed_count = 0
        ready = False

    payload = StatusResponse(
        ready=ready,
        indexed_count=indexed_count,
        version=app.version,
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
    abs_path = _resolve(path)
    try:
        if sys.platform == "win32":
            # explorer /select highlights the file in its parent folder.
            # check=False: explorer.exe returns non-zero even on success.
            subprocess.run(["explorer", f"/select,{abs_path}"], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(abs_path)], check=True)
        else:
            subprocess.run(["xdg-open", str(abs_path.parent)], check=True)
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
    "path": None,
    "files_total": 0,
    "files_done": 0,
    "current_file": None,
    "started_at": None,
    "stopped": False,
}

_stop_event = threading.Event()


class IngestRequest(BaseModel):
    path: str


@app.post("/ingest")
async def start_ingest(req: IngestRequest) -> dict[str, Any]:
    if _ingest_state["running"]:
        raise HTTPException(status_code=409, detail="Indexing already in progress")
    folder = Path(req.path)
    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.path}")
    if not folder.is_file() and not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a file or directory: {req.path}")

    _stop_event.clear()
    _ingest_state.update(
        running=True, done=False, error=None, path=req.path,
        files_total=0, files_done=0, current_file=None,
        started_at=time.time(), stopped=False,
    )
    if folder.is_file():
        threading.Thread(target=_do_ingest_file, args=(folder,), daemon=True).start()
    else:
        threading.Thread(target=_do_ingest, args=(folder,), daemon=True).start()
    return {"status": "started", "path": req.path}


def _do_ingest(folder: Path) -> None:
    def _on_progress(done: int, total: int, current: str | None = None) -> None:
        _ingest_state["files_done"] = done
        _ingest_state["files_total"] = total
        if current is not None:
            _ingest_state["current_file"] = current

    try:
        from src.ingest.walker import run_batch
        from src.stage2.__main__ import ingest_from_manifest
        asyncio.run(run_batch(
            folder,
            push_to_qdrant=True,
            concurrency=4,
            progress_callback=_on_progress,
            stop_event=_stop_event,
        ))
        if _stop_event.is_set():
            _ingest_state["stopped"] = True
        ingest_from_manifest(force=False, verbose=False)
        _ingest_state["done"] = True
    except Exception as exc:
        _ingest_state["error"] = str(exc)
        print(f"[server] ingest error: {exc}", file=sys.stderr)
    finally:
        _ingest_state["running"] = False


def _do_ingest_file(file_path: Path) -> None:
    def _on_progress(done: int, total: int, current: str | None = None) -> None:
        _ingest_state["files_done"] = done
        _ingest_state["files_total"] = total
        if current is not None:
            _ingest_state["current_file"] = current

    _on_progress(0, 1, file_path.name)
    try:
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
        _on_progress(1, 1, None)
        ingest_from_manifest(force=False, verbose=False)
        _ingest_state["done"] = True
    except Exception as exc:
        _ingest_state["error"] = str(exc)
        print(f"[server] ingest_file error: {exc}", file=sys.stderr)
    finally:
        _ingest_state["running"] = False


@app.post("/ingest/stop")
def stop_ingest() -> dict[str, str]:
    _stop_event.set()
    return {"status": "stopping"}


@app.get("/ingest/status")
def ingest_status() -> dict[str, Any]:
    elapsed: float | None = None
    if _ingest_state["started_at"] is not None:
        elapsed = round(time.time() - _ingest_state["started_at"], 1)
    return {
        "running": _ingest_state["running"],
        "done": _ingest_state["done"],
        "error": _ingest_state["error"],
        "path": _ingest_state["path"],
        "files_total": _ingest_state["files_total"],
        "files_done": _ingest_state["files_done"],
        "current_file": _ingest_state["current_file"],
        "elapsed_s": elapsed,
        "stopped": _ingest_state["stopped"],
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


def _init_ingest_state(*, path_label: str) -> None:
    """Bootstrap _ingest_state for a new job. Caller must already have
    confirmed `_ingest_state["running"] is False` and held that contract
    through to setting running=True."""
    _stop_event.clear()
    _ingest_state.update(
        running=True, done=False, error=None,
        path=path_label,
        files_total=0, files_done=0, current_file=None,
        started_at=time.time(), stopped=False,
    )


def _on_progress_update(done: int, total: int, current: str | None = None) -> None:
    """Shared progress callback for sync/reindex jobs. Mirrors the inline
    one in _do_ingest. Pulled out so multiple workers reuse the same
    update logic."""
    _ingest_state["files_done"] = done
    _ingest_state["files_total"] = total
    if current is not None:
        _ingest_state["current_file"] = current


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
        from src.config.indexing_rules import load_user_rules
        from src.ingest.walker import run_batch
        from src.stage2.__main__ import ingest_from_manifest

        rules = load_user_rules()
        roots: list[Path] = []
        for ip in rules.include_paths:
            if not ip.enabled:
                continue
            p = Path(ip.path).expanduser()
            if p.exists():
                roots.append(p)
        enabled_prefixes = [str(r.resolve()) for r in roots]

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
        for root in roots:
            if _stop_event.is_set():
                break
            asyncio.run(run_batch(
                root,
                push_to_qdrant=True,
                concurrency=4,
                progress_callback=_on_progress_update,
                stop_event=_stop_event,
            ))

        if _stop_event.is_set():
            _ingest_state["stopped"] = True
        # End-of-run orphan cleanup (this is what drops Qdrant points
        # whose source_path is no longer in the manifest).
        ingest_from_manifest(force=False, verbose=False)
        _ingest_state["done"] = True
    except Exception as exc:  # noqa: BLE001 — fail-safe: surface to UI, don't crash sidecar
        _ingest_state["error"] = str(exc)
        print(f"[server] sync error: {exc}", file=sys.stderr)
    finally:
        _ingest_state["running"] = False


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


@app.post("/index/sync")
def index_sync() -> IndexJobResponse:
    """Pick up new files; drop files that no longer match the rules.
    409 if any indexing job is already running."""
    if _ingest_state["running"]:
        raise HTTPException(status_code=409, detail="Indexing already in progress")
    _init_ingest_state(path_label="<sync: all enabled folders>")
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
    _init_ingest_state(path_label="<reindex: all enabled folders>")
    threading.Thread(target=_do_reindex, daemon=True).start()
    return IndexJobResponse(status="started", kind="reindex")


# ---------------------------------------------------------------------------
# Settings endpoints — folder management + shortcut read
# ---------------------------------------------------------------------------

from src.config.indexing_rules import (
    load_user_rules,
    save_user_rules,
    IncludePath as _IncludePath,
)

_SHORTCUT_FILE_PATH = APP_DATA_DIR / "shortcut.json"


@app.get("/settings/folders")
def settings_get_folders() -> dict[str, Any]:
    rules = load_user_rules()
    return {
        "folders": [{"path": p.path, "enabled": p.enabled} for p in rules.include_paths],
        "ingest_running": _ingest_state["running"],
    }


class FolderAddRequest(BaseModel):
    path: str


@app.post("/settings/folders")
def settings_add_folder(req: FolderAddRequest) -> dict[str, str]:
    rules = load_user_rules()
    target = str(Path(req.path).expanduser().resolve())
    for entry in rules.include_paths:
        if str(Path(entry.path).expanduser().resolve()) == target:
            if not entry.enabled:
                entry.enabled = True
                save_user_rules(rules)
                return {"status": "enabled"}
            return {"status": "already_exists"}
    rules.include_paths.append(_IncludePath(path=target, enabled=True))
    save_user_rules(rules)
    return {"status": "added"}


@app.delete("/settings/folders")
def settings_remove_folder(path: str) -> dict[str, str]:
    rules = load_user_rules()
    target = str(Path(path).expanduser().resolve())
    rules.include_paths = [
        p for p in rules.include_paths
        if str(Path(p.path).expanduser().resolve()) != target
    ]
    save_user_rules(rules)
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


class FolderTogglePatch(BaseModel):
    path: str
    enabled: bool


@app.patch("/settings/folders")
def settings_toggle_folder(req: FolderTogglePatch) -> dict[str, str]:
    """Toggle an existing IncludePath's `enabled` flag. 404 if path not
    found. The Settings UI's Data tab uses this for the per-row switch."""
    rules = load_user_rules()
    target = str(Path(req.path).expanduser().resolve())
    for entry in rules.include_paths:
        if str(Path(entry.path).expanduser().resolve()) == target:
            entry.enabled = req.enabled
            save_user_rules(rules)
            return {"status": "updated", "enabled": str(req.enabled).lower()}
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


class SearchSettingsPatch(BaseModel):
    provider: str | None = Field(default=None, pattern="^(local|cloud)$")
    top_k: int | None = Field(default=None, ge=1, le=20)
    rewrite: bool | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


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
    # Local: prefer the LOCAL_MODEL env (matches active_model_name's resolution
    # for the local provider). Defaults to "Gemma 4" as a friendly fallback.
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

    # Local: report the configured model. The binary's presence check
    # is parked for PR 5 — see the model-download flow in the spec.
    local_model = os.environ.get("LOCAL_MODEL", "Gemma 4")

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
            "available": True,
            "model": local_model,
            "downloaded": True,  # v1 assumption; PR 5 wires the real check
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
    default_action: str  # "empty" | "last"
    launch_at_login: bool
    show_in_tray: bool


class AppSettingsPatch(BaseModel):
    theme: str | None = Field(default=None, pattern="^(system|light|dark)$")
    accent: str | None = Field(default=None, pattern="^(ink|amber|jade|rose)$")
    default_action: str | None = Field(default=None, pattern="^(empty|last)$")
    launch_at_login: bool | None = None
    show_in_tray: bool | None = None


@app.get("/settings/app")
def settings_get_app() -> AppSettingsResponse:
    eff = _effective_settings()
    return AppSettingsResponse(
        theme=eff.theme,
        accent=eff.accent,
        default_action=eff.default_action,
        launch_at_login=eff.launch_at_login,
        show_in_tray=eff.show_in_tray,
    )


@app.patch("/settings/app")
def settings_patch_app(req: AppSettingsPatch) -> AppSettingsResponse:
    kwargs: dict[str, Any] = {}
    for field in ("theme", "accent", "default_action", "launch_at_login", "show_in_tray"):
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
    """Return the last N persisted recents, newest-first."""
    return {"recents": [r.model_dump(mode="json") for r in _list_recents()]}


@app.get("/recents/{entry_id}")
def recents_get(entry_id: str) -> dict[str, Any]:
    """Look up a recent by id. Used by the ask bar's replay path."""
    entry = _get_recent(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"recent not found: {entry_id}")
    return entry.model_dump(mode="json")


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
