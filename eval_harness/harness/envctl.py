"""Controlled-environment construction for eval runs (PLAN.md §3).

The backend worker's environment is built FROM SCRATCH here — never inherited
from the parent shell — so ambient `.env` / shell state cannot change a run
without appearing in the run record. `src/manifest.py:63` loads the repo `.env`
with `load_dotenv()` (override=False), which means every variable this module
sets explicitly wins, and every variable it deliberately leaves unset falls to
the backend's own coded default — never to a machine-local dotfile.

Cache contract (PLAN.md §3, review finding #1/#2): `src/manifest.py:97-114`
derives HF_HOME / HF_HUB_CACHE / TRANSFORMERS_CACHE / FASTEMBED_CACHE_PATH from
APP_DATA_DIR via `os.environ.setdefault`, so exporting them BEFORE the worker
process imports any `src.*` module makes the scratch data dir and the shared
10 GB weights cache coexist. `HF_HUB_OFFLINE=1` guarantees zero downloads and
zero cache mutation (a literal read-only mount breaks hub lockfiles).

Shared read-only tools (same rationale as weights — installed artifacts, not
state under test): the real app's llama-server binary via LLAMA_SERVER_PATH.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# The real installed app's data dir. Read for: model weights cache (shared,
# offline-locked), llama-server binary (shared tool). NEVER written; the
# isolation test asserts this by content-hashing before/after.
if sys.platform == "darwin":
    REAL_APP_DATA = Path.home() / "Library" / "Application Support" / "Magpie"
elif sys.platform.startswith("win"):
    REAL_APP_DATA = Path(os.environ.get("APPDATA", "")) / "Magpie"
else:
    REAL_APP_DATA = Path.home() / ".local" / "share" / "Magpie"

SHARED_MODEL_CACHE = REAL_APP_DATA / "cache"
SHARED_LLAMA_SERVER = REAL_APP_DATA / "bin" / "llama-server"

# Port block far from both the live app's defaults (llama 9100, qdrant 6433)
# and common dev servers. One run at a time, but keep per-run offsets anyway
# so a wedged old process can't be mistaken for the current run's.
QDRANT_HTTP_BASE = 6533
QDRANT_GRPC_BASE = 6534
LLAMA_BASE = 9400

# Vars whose values are secrets: excluded from the built env unless a run
# explicitly needs one (cloud arms), and always redacted in snapshots.
_SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")

# Minimal system base carried over from the parent so subprocesses (python,
# llama-server, qdrant) can run at all. Everything else starts absent.
_BASE_PASSTHROUGH = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")


@dataclass(frozen=True)
class Ports:
    qdrant_http: int
    qdrant_grpc: int
    llama_base: int

    @classmethod
    def for_slot(cls, slot: int = 0) -> "Ports":
        return cls(
            qdrant_http=QDRANT_HTTP_BASE + slot * 10,
            qdrant_grpc=QDRANT_GRPC_BASE + slot * 10,
            llama_base=LLAMA_BASE + slot * 10,
        )


def _is_secret(name: str) -> bool:
    return any(marker in name.upper() for marker in _SECRET_MARKERS)


def build_env(
    appdata_dir: Path,
    params: dict,
    ports: Ports,
    *,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The worker process environment, from scratch.

    `params` is the run config's `params` block (PLAN.md §4.2). Only keys the
    backend actually reads become env vars; pipeline-level knobs (top_k,
    rewrite, fast) travel as ask() arguments instead, set by the worker.
    """
    env: dict[str, str] = {}
    for key in _BASE_PASSTHROUGH:
        val = os.environ.get(key)
        if val:
            env[key] = val

    # --- isolation root ---
    env["MAGPIE_DATA_DIR"] = str(appdata_dir)

    # --- cache contract: MUST precede any src.* import in the worker ---
    env["HF_HOME"] = str(SHARED_MODEL_CACHE)
    env["HF_HUB_CACHE"] = str(SHARED_MODEL_CACHE / "hub")
    env["TRANSFORMERS_CACHE"] = str(SHARED_MODEL_CACHE)
    env["FASTEMBED_CACHE_PATH"] = str(SHARED_MODEL_CACHE / "fastembed")
    env["HF_HUB_OFFLINE"] = "1"

    # --- per-run services ---
    env["QDRANT_CLUSTER_ENDPOINT"] = f"http://127.0.0.1:{ports.qdrant_http}"
    env["LLAMA_SERVER_BASE_PORT"] = str(ports.llama_base)
    if SHARED_LLAMA_SERVER.exists():
        env["LLAMA_SERVER_PATH"] = str(SHARED_LLAMA_SERVER)

    # --- swept / pinned parameters (PLAN.md §2) ---
    # MAGPIE_FORCE_PROVIDER is the eval-only escape hatch with absolute
    # precedence (src/llm.py:150-166). LLM_PROVIDER alone is a
    # settings-unavailable fallback and settings.json always exists with
    # provider="cloud" - the exact trap that made a 2026-08-24 eval run
    # answer locally under a cloud label. Set both.
    env["MAGPIE_FORCE_PROVIDER"] = params.get("provider", "local")
    env["LLM_PROVIDER"] = params.get("provider", "local")
    env["LOCAL_TEMPERATURE"] = str(params.get("temperature", 0.0))
    env["LOCAL_SOLO_MARGIN"] = str(params.get("solo_margin", 2.0))
    local_n_ctx = params.get("local_n_ctx")
    if local_n_ctx is not None:
        # None = shipped-app behavior (profile auto-sizing). The resolved
        # value is recorded by the worker, so "auto" is still reproducible
        # evidence, just not a forced setting.
        env["LOCAL_N_CTX"] = str(local_n_ctx)

    startup_timeout = params.get("llama_startup_timeout_s", 300)
    env["LLAMA_SERVER_STARTUP_TIMEOUT_S"] = str(startup_timeout)

    if extra:
        env.update(extra)
    return env


def snapshot_env(env: dict[str, str]) -> dict[str, str]:
    """Run-record form of the environment: secrets replaced by a stable
    sha256 prefix so two runs can be compared for same/different key without
    the value ever entering the record."""
    out: dict[str, str] = {}
    for key, value in sorted(env.items()):
        if _is_secret(key):
            digest = hashlib.sha256(value.encode()).hexdigest()[:12]
            out[key] = f"<redacted sha256:{digest}>"
        else:
            out[key] = value
    return out


def machine_info() -> dict[str, str]:
    info = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
    }
    if sys.platform == "darwin":
        try:
            info["chip"] = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            info["mem_bytes"] = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            pass
    return info


def git_sha(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


def cache_fingerprint() -> dict:
    """Cheap before/after probe of the shared cache: file count + total bytes.
    HF_HUB_OFFLINE should make these identical across a run; the isolation
    test asserts it (zero-bytes-downloaded exit criterion, PLAN.md Phase 0)."""
    n_files = 0
    total = 0
    if SHARED_MODEL_CACHE.exists():
        for p in SHARED_MODEL_CACHE.rglob("*"):
            if p.is_file():
                n_files += 1
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    return {"files": n_files, "bytes": total}


def appdata_fingerprint() -> str:
    """Content fingerprint of the real app dir's MUTABLE state (everything
    except the shared cache/ and bin/, which runs legitimately read). Used to
    prove a run wrote nothing to the live app."""
    h = hashlib.sha256()
    if not REAL_APP_DATA.exists():
        return "absent"
    for p in sorted(REAL_APP_DATA.rglob("*")):
        rel = p.relative_to(REAL_APP_DATA)
        parts = rel.parts
        if parts and parts[0] in ("cache", "bin", "logs"):
            # cache/bin are shared-read; logs excluded because the LIVE app
            # (if the user has it open) appends to its own logs on its own
            # schedule - that is not evidence about the eval run. The eval
            # writes logs only inside its scratch dir.
            continue
        if p.is_file():
            try:
                st = p.stat()
                h.update(str(rel).encode())
                h.update(str(st.st_size).encode())
                h.update(str(int(st.st_mtime)).encode())
            except OSError:
                pass
    return h.hexdigest()


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
