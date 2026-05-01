"""HTTP server that wraps the existing RAG pipeline for the Magpie UI.

Endpoints:
    POST /query     - natural-language question → answer + sources
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
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
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

class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    rewrite: bool = Field(default=False)


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


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    from src.pipeline import ask

    try:
        result = await ask(req.question, top_k=req.top_k, rewrite=req.rewrite)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"pipeline error: {type(e).__name__}: {e}") from e

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
        return JSONResponse({"columns": header, "rows": rows, "truncated": i + 1 >= max_rows if rows else False})

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
    llm_provider: str
    llm_model: str
    qdrant_provider: str
    indexed_count: int


@app.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    now = time.monotonic()
    if _status_cache["payload"] is not None and now - _status_cache["ts"] < _STATUS_TTL:
        return _status_cache["payload"]

    from src.llm import active_provider, active_model_name
    from src.stage2.db import get_all_point_ids

    llm_prov = active_provider().name
    llm_model = active_model_name()
    qdrant_prov = os.environ.get("QDRANT_PROVIDER", "cloud").strip().lower()
    try:
        indexed_count = len(get_all_point_ids())
    except Exception:
        indexed_count = 0

    payload = StatusResponse(
        llm_provider=llm_prov,
        llm_model=llm_model,
        qdrant_provider=qdrant_prov,
        indexed_count=indexed_count,
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
        subprocess.run(["open", str(abs_path)], check=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"open failed: {e}") from e
    return JSONResponse({"ok": True})


@app.get("/reveal")
def reveal_file(path: str = Query(...)) -> JSONResponse:
    abs_path = _resolve(path)
    try:
        subprocess.run(["open", "-R", str(abs_path)], check=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"reveal failed: {e}") from e
    return JSONResponse({"ok": True})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


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
