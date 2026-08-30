"""Localhost progress page for eval runs: `just eval-watch`, then watch.

Serves eval_harness/watch/index.html plus a tiny read-only JSON API over
the runs directory. The page polls; the harness processes write
progress.json (see harness/progress.py). Nothing here mutates anything,
and no LLM is anywhere in this loop.

Routes:
  GET /                                  the watch page
  GET /api/latest                        runs/latest.json (404 until a run starts)
  GET /api/runs                          run ids, newest first
  GET /api/run/<id>/progress             runs/<id>/raw/progress.json
  GET /api/run/<id>/run                  runs/<id>/run.json
  GET /api/run/<id>/tail?file=X.log&bytes=N   last N bytes of a raw/*.log

A plain `python -m http.server` can't do this job: browsers block fetch()
from file://, SimpleHTTPRequestHandler ignores Range so tailing a
multi-hundred-MB worker log would refetch the whole file every poll, and
progress.json needs no-store headers or the browser serves you the past.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
RUNS = EVAL / "runs"
PAGE = EVAL / "watch" / "index.html"

_RUN_ID = re.compile(r"^[A-Za-z0-9._,-]+$")     # no separators — traversal-proof
_LOG_NAME = re.compile(r"^[A-Za-z0-9._-]+\.log$")
TAIL_DEFAULT = 4000
TAIL_MAX = 65536


def tail_bytes(path: Path, n: int) -> bytes:
    """Last `n` bytes of `path` without reading the rest of the file."""
    n = max(0, min(int(n), TAIL_MAX))
    size = path.stat().st_size
    with path.open("rb") as f:
        f.seek(max(0, size - n))
        return f.read()


def safe_run_dir(run_id: str) -> Path | None:
    if not _RUN_ID.match(run_id):
        return None
    d = RUNS / run_id
    return d if d.is_dir() else None


# Skill-phase artifacts (magpie-eval SKILL.md): the golden set, judge, the
# three report agents and the supervisor synthesis all announce completion
# by writing a file with a fixed name. Statting those files gives the watch
# page step states for the agent-driven phases WITHOUT instrumenting the
# skill — an agent step is done exactly when its artifact exists.
STEP_ARTIFACTS = {
    "judge_verdicts": "judge_verdicts.json",
    "judge_report": "JUDGE-REPORT.md",
    "report_answers": "REPORT-answers.md",
    "report_retrieval": "REPORT-retrieval.md",
    "report_indexing": "REPORT-indexing.md",
    "supervisor_report": "SUPERVISOR-REPORT.md",
}


def _stat_entry(path: Path) -> dict:
    if not path.is_file():
        return {"exists": False}
    st = path.stat()
    return {"exists": True, "mtime": st.st_mtime, "size": st.st_size}


def artifact_stats(run_dir: Path) -> dict:
    """Existence/mtime/size for every skill-phase artifact of one run, plus
    the dataset's golden.json (mtime vs run start tells fresh vs reused)."""
    out = {k: _stat_entry(run_dir / name) for k, name in STEP_ARTIFACTS.items()}
    golden: dict = {"exists": False}
    try:
        record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        ds = record.get("dataset", "")
        if ds and _RUN_ID.match(ds):
            golden = _stat_entry(EVAL / "datasets" / ds / "golden.json")
            golden["dataset"] = ds
    except Exception:  # noqa: BLE001 — run.json mid-write or absent
        pass
    out["golden"] = golden
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "magpie-eval-watch/1"

    # ---- plumbing -------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _json_file(self, path: Path) -> None:
        if not path.is_file():
            self._json(404, {"error": f"{path.name} not found"})
            return
        try:
            body = path.read_bytes()
            json.loads(body)  # never serve a half-written file as JSON
        except Exception:  # noqa: BLE001 — mid-write; the next poll gets it
            self._json(503, {"error": f"{path.name} unreadable right now"})
            return
        self._send(200, body, "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 — silence per-request spam
        pass

    # ---- routes ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]

        if not parts:
            if not PAGE.is_file():
                self._json(500, {"error": f"watch page missing at {PAGE}"})
                return
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return

        if parts == ["api", "latest"]:
            self._json_file(RUNS / "latest.json")
            return

        if parts == ["api", "runs"]:
            runs = sorted(
                (d.name for d in RUNS.iterdir() if d.is_dir()),
                reverse=True,
            ) if RUNS.is_dir() else []
            self._json(200, {"runs": runs[:50]})
            return

        if len(parts) == 4 and parts[:2] == ["api", "run"]:
            run_dir = safe_run_dir(parts[2])
            if run_dir is None:
                self._json(404, {"error": "unknown run id"})
                return
            leaf = parts[3]
            if leaf == "progress":
                self._json_file(run_dir / "raw" / "progress.json")
                return
            if leaf == "run":
                self._json_file(run_dir / "run.json")
                return
            if leaf == "artifacts":
                self._json(200, artifact_stats(run_dir))
                return
            if leaf == "tail":
                q = parse_qs(url.query)
                name = (q.get("file") or [""])[0]
                if not _LOG_NAME.match(name):
                    self._json(400, {"error": "file must be a bare *.log name"})
                    return
                log = run_dir / "raw" / name
                if not log.is_file():
                    self._json(404, {"error": f"{name} not found"})
                    return
                n = (q.get("bytes") or [str(TAIL_DEFAULT)])[0]
                try:
                    body = tail_bytes(log, int(n))
                except (OSError, ValueError) as e:
                    self._json(500, {"error": str(e)})
                    return
                self._send(200, body, "text/plain; charset=utf-8")
                return

        self._json(404, {"error": "no such route"})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true",
                    help="open the page in the default browser")
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"[eval-watch] serving {url}  (runs dir: {RUNS})")
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[eval-watch] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
