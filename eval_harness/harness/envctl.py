"""Controlled-environment construction for eval runs (PLAN.md §3).

The backend worker's environment is built FROM SCRATCH here — never inherited
from the parent shell. One refill path survives that: `src/manifest.py:63`
calls `load_dotenv()` (override=False) at import time, which fills any UNSET
variable from the repo `.env`. So the contract is a managed set, not an empty
set: every variable the harness cares about is set explicitly (explicit always
wins over load_dotenv), every remaining `.env` name must be consciously listed
in ACCEPTED_ENV_LEAKS (inert or infra-only; recorded in each result's
resolved_env snapshot), and build_env fails loudly on any `.env` name that is
neither — so a leak can be added to this codebase only by writing it down.

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
# isolation test asserts this with a size+mtime fingerprint before/after.
# Resolved exactly the way src/manifest.py resolves it (platformdirs, same
# app/author args) so this can never drift to a path the app doesn't use —
# review #28: a hand-rolled %APPDATA%\Magpie guess made the Windows isolation
# proof pass vacuously against a directory that doesn't exist.
try:
    from platformdirs import user_data_dir

    # identical args to src/manifest.py:77 (_APP_NAME, _APP_AUTHOR, roaming)
    REAL_APP_DATA = Path(user_data_dir("Magpie", "magpie", roaming=False))
except ImportError:  # matches the manifest.py documented layouts
    if sys.platform == "darwin":
        REAL_APP_DATA = Path.home() / "Library" / "Application Support" / "Magpie"
    elif sys.platform.startswith("win"):
        REAL_APP_DATA = (
            Path(os.environ.get("LOCALAPPDATA", "")) / "magpie" / "Magpie"
        )
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


# --- model_config resolution (PLAN.md §2/§9.2) -----------------------------
# One explicit mapping, raising on unknowns — review #27: a .get(..., "local")
# fallback made a gemma26b-openrouter run execute entirely locally with every
# layer agreeing it was told to.
MODEL_CONFIGS: dict[str, dict] = {
    "lfm-local": {"provider": "local", "grammar": True, "env": {}},
    "gemma26b-local": {"provider": "local", "grammar": True, "env": None},
    "gemma26b-openrouter": {
        "provider": "openrouter",
        "grammar": False,  # codebase choice, not API limit — PLAN §2 factor 2
        "env": {"OPENROUTER_MODEL": "google/gemma-4-26b-a4b-it:free"},
    },
}


def resolve_model_config(params: dict) -> dict:
    """params['model_config'] -> resolved {provider, grammar, env_extra}.

    Raises on unknown names and on configs whose prerequisites aren't met —
    a mislabeled run is the worst artifact an eval can produce."""
    name = params.get("model_config")
    cfg = MODEL_CONFIGS.get(name or "")
    if cfg is None:
        raise ValueError(
            f"unknown model_config {name!r}; valid: {sorted(MODEL_CONFIGS)}"
        )
    env_extra = cfg["env"]
    if name == "gemma26b-local":
        local_model = params.get("local_model")
        if not local_model:
            raise NotImplementedError(
                "gemma26b-local needs params.local_model (GGUF repo id) — "
                "PLAN Phase 0 open item: pin it before running this arm"
            )
        env_extra = {"LOCAL_MODEL": str(local_model)}
    if name == "gemma26b-openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError(
            "gemma26b-openrouter needs OPENROUTER_API_KEY in the parent env "
            "(passed through without logging; snapshots redact it)"
        )
    return {"provider": cfg["provider"], "grammar": cfg["grammar"], "env_extra": dict(env_extra)}


# .env names allowed to reach the worker via manifest's load_dotenv WITHOUT
# the harness pinning them. Each is either inert for eval runs or a pure
# infra knob; all of them appear (redacted where secret) in every result's
# resolved_env snapshot, so a leak is recorded evidence, never invisible.
# Promoting one to pinned = add it to build_env and delete it here. Any
# .env name that is neither managed nor listed here fails build_env loudly.
ACCEPTED_ENV_LEAKS = {
    "OPENROUTER_API_KEY",   # secret; needed by the cloud arm; redacted in snapshots
    "HF_TOKEN",             # inert under HF_HUB_OFFLINE=1; redacted
    "OPENROUTER_MODEL",     # cloud arms override explicitly; inert for local
    "REWRITE",              # not consulted by src (server.py precedence flip)
    "MOONSHOT_API_KEY",     # unused provider in this harness; redacted
    "MOONSHOT_MODEL",
    "MOONSHOT_BASE_URL",
    "OPENROUTER_BASE_URL",
    "LLAMA_SERVER_IDLE_TIMEOUT_S",    # infra tuning; recorded, not swept
    "LLAMA_SERVER_MAX_LOADED_MODELS", # infra tuning; recorded, not swept
    "LLAMA_SERVER_MIN_VERSION",       # binary version floor; recorded
}


def dotenv_names(repo_root: Path) -> set[str]:
    """Variable NAMES defined in the repo .env (values never read into the
    harness beyond dotenv's parse; nothing is printed or stored)."""
    path = repo_root / ".env"
    if not path.exists():
        return set()
    try:
        from dotenv import dotenv_values

        return set(dotenv_values(path).keys())
    except Exception:  # noqa: BLE001 — fall back to a line parse of names only
        names: set[str] = set()
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                names.add(line.split("=", 1)[0].strip())
        return names


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
    # Provider comes ONLY from resolve_model_config — no default. A missing
    # provider here means the caller skipped resolution; failing beats
    # mislabeling (review #27).
    provider = params.get("provider")
    if not provider:
        raise ValueError(
            "params carries no resolved provider — pass the run config "
            "through resolve_model_config() and merge its result first"
        )
    # MAGPIE_FORCE_PROVIDER is the eval-only escape hatch with absolute
    # precedence (src/llm.py:150-166). LLM_PROVIDER alone is a
    # settings-unavailable fallback and settings.json always exists with
    # provider="cloud" - the exact trap that made a 2026-08-24 eval run
    # answer locally under a cloud label. Set both.
    env["MAGPIE_FORCE_PROVIDER"] = provider
    env["LLM_PROVIDER"] = provider
    env["LOCAL_TEMPERATURE"] = str(params.get("temperature", 0.0))
    env["LOCAL_SOLO_MARGIN"] = str(params.get("solo_margin", 2.0))
    # ALWAYS set: "leave unset for the backend default" is a lie whenever the
    # repo .env defines the var - load_dotenv (manifest.py:63) fills unset
    # vars, so an omitted knob would silently inherit this machine's dotfile
    # (observed live in the first phase0 run: .env's LOCAL_N_CTX=65536 leaked
    # into an env that meant to leave ctx at the coded default). 16384 is the
    # .env.example fresh-clone value and what the shipped beta runs at.
    env["LOCAL_N_CTX"] = str(params.get("local_n_ctx", 16384))

    startup_timeout = params.get("llama_startup_timeout_s", 300)
    env["LLAMA_SERVER_STARTUP_TIMEOUT_S"] = str(startup_timeout)

    if extra:
        env.update(extra)

    # --- managed-set completeness check (review #26) ---
    # manifest.py:63's load_dotenv fills any UNSET var from the repo .env at
    # worker import time, so "we didn't set it" never means "coded default".
    # Every .env name must therefore be explicitly set above or consciously
    # listed in ACCEPTED_ENV_LEAKS; a new .env line fails here loudly until
    # someone classifies it.
    repo_root = Path(__file__).resolve().parents[2]
    unmanaged = dotenv_names(repo_root) - set(env) - ACCEPTED_ENV_LEAKS
    if unmanaged:
        raise RuntimeError(
            f"unmanaged .env var(s) would leak into the worker via "
            f"load_dotenv: {sorted(unmanaged)} — set them in build_env or "
            f"classify them in ACCEPTED_ENV_LEAKS"
        )
    return env


def non_secret(env: dict[str, str]) -> dict[str, str]:
    """The env minus secret-valued vars — safe to write into worker payloads
    (used as the expected_env for the worker's runtime assertion)."""
    return {k: v for k, v in env.items() if not _is_secret(k)}


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
    test asserts it (zero-bytes-downloaded exit criterion, PLAN.md Phase 0).
    `.locks` entries are excluded — the hub writes those even on pure cache
    hits (the exact reason HF_HUB_OFFLINE was chosen over a read-only mount),
    so counting them would fail a correct run (review #30)."""
    n_files = 0
    total = 0
    if SHARED_MODEL_CACHE.exists():
        for p in SHARED_MODEL_CACHE.rglob("*"):
            if ".locks" in p.parts:
                continue
            if p.is_file():
                n_files += 1
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    return {"files": n_files, "bytes": total}


def appdata_fingerprint() -> str:
    """Size+mtime fingerprint (NOT content hash — a same-size same-second
    overwrite is invisible; acceptable for this guard, stated so nobody
    over-trusts it) of the real app dir's mutable state, excluding the shared
    cache/ and bin/ that runs legitimately read. Used to show a run wrote
    nothing to the live app."""
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
