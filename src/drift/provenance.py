"""What exactly is running: a fingerprint of the installed binaries, the
resolved model files, the retrieval encoder, and the dependency lockfile.

Used three ways:
  - `/status` and the startup log show it, so "which llama-server is
    this?" never needs a terminal;
  - every eval run stamps it into run.json, so a moved number can be
    attributed to a binary or model bump rather than guessed at;
  - its `fingerprint` hash keys the oracle cache - the mirrored-assumption
    checks re-run exactly when one of these inputs changes.

Everything here is best-effort and offline: no downloads, no model loads
(the col-model family is read from the device cache file, not by
importing torch), and any probe that fails reports None instead of
raising. Hashing the GGUF files (2+ GB) happens once and is cached by
(path, size, mtime) under <APP_DATA_DIR>/drift/hashes.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.manifest import APP_DATA_DIR

DRIFT_DIR = APP_DATA_DIR / "drift"
_HASH_CACHE = DRIFT_DIR / "hashes.json"
# In a PyInstaller bundle this resolves inside the extraction temp dir: there
# is no .git and no uv.lock there, so `magpie.git_sha` and `deps` come back
# None and the fingerprint rests on the binary + model hashes alone. Fine -
# a packaged build's dependency set is frozen by construction.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_lock = threading.Lock()
_cached: Optional[dict] = None

_COMMIT_RE = re.compile(r"commit\s+([0-9a-f]{6,40})", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> Optional[str]:
    """Full sha256 of a file, cached by (size, mtime) so multi-GB model
    files are read once per install, not once per launch.

    The cache is read-modify-replaced whole, unlocked: two processes hashing
    at the same moment (sidecar startup + an eval worker) can lose one
    entry, which is simply recomputed next time. Benign by design."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    cache: dict = {}
    try:
        cache = json.loads(_HASH_CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - missing/corrupt cache = recompute
        cache = {}
    hit = cache.get(key)
    if hit and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime:
        return hit.get("sha256")
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return None
    digest = h.hexdigest()
    cache[key] = {"size": st.st_size, "mtime": st.st_mtime, "sha256": digest}
    try:
        DRIFT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _HASH_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        tmp.replace(_HASH_CACHE)
    except OSError:
        pass
    return digest


def _git_sha() -> Optional[str]:
    try:
        from src.subproc import no_window_kwargs

        r = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False,
            # runs in the sidecar's startup event: without this, Windows pops
            # a console window at every launch when git is installed
            **no_window_kwargs(),
        )
        sha = r.stdout.strip()
        return sha if r.returncode == 0 and sha else None
    except Exception:  # noqa: BLE001 - packaged builds have no git
        return None


def _llama_server() -> dict:
    try:
        from src.inference.llama_server_binary import find_llama_server, get_binary_version

        binary = find_llama_server()
        raw, build = get_binary_version(binary)
        m = _COMMIT_RE.search(raw)
        return {
            "path": str(binary),
            "build": build,
            "commit": m.group(1) if m else None,
            "raw": raw[:200],
        }
    except Exception as e:  # noqa: BLE001
        return {"path": None, "build": None, "commit": None, "error": str(e)[:200]}


def _qdrant() -> dict:
    import urllib.request

    try:
        from src.stage2.db import resolve_endpoint

        endpoint = resolve_endpoint()
    except Exception:  # noqa: BLE001
        endpoint = os.environ.get("QDRANT_CLUSTER_ENDPOINT", "") or "http://127.0.0.1:6433"
    try:
        with urllib.request.urlopen(endpoint + "/", timeout=1.5) as r:
            info = json.load(r)
        return {"endpoint": endpoint, "version": info.get("version"), "reachable": True}
    except Exception:  # noqa: BLE001 - not running is a normal state
        return {"endpoint": endpoint, "version": None, "reachable": False}


def _cached_model_file(repo_id: str, filename: str, revision: Optional[str] = None) -> Optional[Path]:
    """Path of an already-downloaded HF file at `revision` (the pinned one
    when None), or None. Never downloads."""
    try:
        from huggingface_hub import try_to_load_from_cache

        from src.inference.model_downloader import _pinned

        hit = try_to_load_from_cache(repo_id=repo_id, filename=filename,
                                     revision=_pinned(repo_id, revision))
        return Path(hit) if isinstance(hit, str) else None
    except Exception:  # noqa: BLE001
        return None


def _snapshot_of(path: Optional[Path]) -> Optional[str]:
    """The HF snapshot (commit sha) a cached file belongs to, from its path."""
    if path is None:
        return None
    parts = path.parts
    return parts[parts.index("snapshots") + 1] if "snapshots" in parts else None


def _file_record(path: Optional[Path], hash_models: bool) -> dict:
    if path is None:
        return {"path": None, "size": None, "sha256": None}
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    return {
        "path": str(path),
        "size": size,
        "sha256": _sha256_file(path) if hash_models else None,
    }


def _models(hash_models: bool) -> dict:
    try:
        from src.inference.model_downloader import _filename_for, _mmproj_filename_for
        from src.inference.profiles import default_text_profile, get_profile

        name = default_text_profile()
        prof = get_profile(name)
        args = prof.args
        from src.inference.gguf_meta import identity
        from src.inference.model_downloader import _pinned
        from src.inference.profiles import clamp_ctx_to_model

        gguf = _cached_model_file(args.repo_id, _filename_for(args.repo_id, args.quant), args.revision)
        out: dict[str, Any] = {
            "profile": name,
            "repo": args.repo_id,
            "quant": args.quant,
            # the revision we ASK for and the snapshot the cached file IS
            # (they differ when a pin was added after an unpinned download)
            "revision": _pinned(args.repo_id, args.revision),
            "snapshot": _snapshot_of(gguf),
            "gguf": {**_file_record(gguf, hash_models),
                     "identity": identity(gguf) if gguf else None},
            # launch args that reach llama-server argv: the runtime the
            # mirrored assumptions execute in (a LOCAL_N_CTX change must
            # re-run the oracles once)
            "launch": {
                "ctx_size_requested": args.ctx_size,
                "ctx_size": clamp_ctx_to_model(args.ctx_size, gguf),
                "ngl": args.ngl,
                "extra_args": list(getattr(args, "extra_args", []) or []),
            },
        }
        if args.mmproj_repo_id:
            mm = _cached_model_file(
                args.mmproj_repo_id, _mmproj_filename_for(args.mmproj_repo_id, args.mmproj_variant),
                args.revision,
            )
            out["mmproj"] = {"variant": args.mmproj_variant, "snapshot": _snapshot_of(mm),
                             **_file_record(mm, hash_models)}
        else:
            out["mmproj"] = None
        return out
    except Exception as e:  # noqa: BLE001
        return {"profile": None, "error": str(e)[:200]}


def _col_model() -> dict:
    """Retrieval encoder identity from the device cache - no torch import."""
    try:
        from src.stage1_fast.device import (
            COLQWEN_MODEL_ID, COLSMOL_MODEL_ID, _CACHE_PATH,
        )

        cache = json.loads(Path(_CACHE_PATH).read_text(encoding="utf-8"))
        family = cache.get("model_family")
        model_id = {"colqwen2_5": COLQWEN_MODEL_ID, "colidefics3": COLSMOL_MODEL_ID}.get(family)
        return {
            "family": family,
            "model_id": model_id,
            "device": cache.get("device"),
            "dtype": cache.get("dtype"),
            "override": os.environ.get("MAGPIE_COL_MODEL", "auto"),
        }
    except Exception:  # noqa: BLE001 - never detected yet is a normal state
        return {"family": None, "model_id": None, "override": os.environ.get("MAGPIE_COL_MODEL", "auto")}


def _deps() -> dict:
    lock = _REPO_ROOT / "uv.lock"
    try:
        digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    except OSError:
        digest = None
    return {"uv_lock_sha256": digest}


def runtime_fingerprint(*, hash_models: bool = True, refresh: bool = False) -> dict:
    """Assemble the provenance record. Cached in-process after the first
    call (the llama-server --version probe alone can take seconds on a cold
    Metal shader cache); `refresh=True` recomputes."""
    global _cached
    with _lock:
        if _cached is not None and not refresh:
            return _cached
        gpu_default = "metal" if sys.platform == "darwin" else "cpu"
        prov: dict[str, Any] = {
            "computed_utc": _now(),
            "magpie": {"git_sha": _git_sha()},
            "python": platform.python_version(),
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "gpu_backend": os.environ.get("LLAMA_SERVER_GPU", gpu_default).lower(),
            },
            "llama_server": _llama_server(),
            "qdrant": _qdrant(),
            "models": _models(hash_models),
            "col_model": _col_model(),
            "deps": _deps(),
        }
        prov["fingerprint"] = fingerprint_of(prov)
        _cached = prov
        return prov


def fingerprint_of(prov: dict) -> str:
    """Stable 16-hex digest over the inputs the oracles depend on.

    Deliberately excluded: the Magpie git sha (changes every commit; the
    checks are about the world underneath the code) and the Qdrant version
    (its probe depends on whether Qdrant happened to be up - the sidecar's
    startup probe races Tauri's Qdrant spawn - and it cannot move the token
    math or grammar behaviour; vector_dims reads the live collections
    anyway). Both stay in the provenance record for display and pins."""
    models = prov.get("models") or {}
    stable = {
        "llama_build": (prov.get("llama_server") or {}).get("build"),
        "llama_commit": (prov.get("llama_server") or {}).get("commit"),
        "gguf": ((models.get("gguf") or {}).get("sha256")) or ((models.get("gguf") or {}).get("path")),
        "gguf_identity": (models.get("gguf") or {}).get("identity"),
        "launch": models.get("launch"),
        "mmproj": ((models.get("mmproj") or {}).get("sha256")) or ((models.get("mmproj") or {}).get("path")),
        "col": (prov.get("col_model") or {}).get("model_id"),
        "deps": (prov.get("deps") or {}).get("uv_lock_sha256"),
        "platform": prov.get("platform"),
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:16]


def summary(prov: dict) -> dict:
    """The short form for /status: one line per component."""
    ls = prov.get("llama_server") or {}
    models = prov.get("models") or {}
    gguf = models.get("gguf") or {}
    mm = models.get("mmproj") or {}
    return {
        "fingerprint": prov.get("fingerprint"),
        "llama_server": f"b{ls['build']}" if isinstance(ls.get("build"), int) else None,
        "qdrant": (prov.get("qdrant") or {}).get("version"),
        "model": f"{models.get('repo')}:{models.get('quant')}" if models.get("repo") else None,
        "snapshot": (models.get("snapshot") or "")[:12] or None,
        "ctx_size": (models.get("launch") or {}).get("ctx_size"),
        "gguf_sha256": (gguf.get("sha256") or "")[:12] or None,
        "mmproj_sha256": (mm.get("sha256") or "")[:12] or None,
        "col_model": (prov.get("col_model") or {}).get("model_id"),
        "magpie_git_sha": ((prov.get("magpie") or {}).get("git_sha") or "")[:12] or None,
    }
