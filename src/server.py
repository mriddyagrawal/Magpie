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
    from src.pipeline import ask

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
    return QueryResponse(
        question=result.question,
        answer=result.answer,
        sources=sources,
        search_query={"query": result.search_query.query, "keywords": result.search_query.keywords},
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
