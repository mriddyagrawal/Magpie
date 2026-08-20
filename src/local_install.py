"""Local-model install manager — backend for the `/local/*` endpoints.

Owns downloading everything "Local" needs, with progress a UI can poll:

  LLM half (what the Local provider toggle requires):
    - the `llama-server` binary (~40 MB, llama.cpp GitHub release)
    - LFM2.5-VL weights          (2.22 GB at Q6_K, HuggingFace)
    - the mmproj vision projector (0.56 GB at Q8_0, same repo)

  Visual half (used by T4 indexing REGARDLESS of provider):
    - the ColPali-family retriever `detect_device()` picked for this
      machine — ColQwen2.5 (7.25 GB) or ColSmol-500M (0.93 GB), each a
      LoRA adapter repo plus its base-model repo.

Design notes, all deliberate:

  - One state dict + lock, mirroring `_ingest_state` in src/server.py —
    the UI polls GET /local/status exactly like /ingest/status.
  - Each artifact downloads in a **subprocess**, not a thread.
    `hf_hub_download` has no cancel hook; a killable child is the only
    honest cancel. Termination leaves HuggingFace's `*.incomplete` blobs
    behind, which is a feature: hf resumes partial downloads, so a
    cancelled 2 GB fetch loses nothing.
  - Progress is computed READ-side: the status call stats the cache's
    blob files (complete + .incomplete). The worker stays a dumb
    sequential orchestrator; nothing pushes bytes anywhere.
  - The binary installs first. It is the smallest artifact and the one
    that fails for structural reasons (unsupported platform, missing GPU
    asset) — failing there costs seconds, not twenty minutes into a
    multi-GB fetch.
  - Byte totals for the LLM files come from HF metadata, fetched lazily
    once and cached; the visual tier uses the measured repo totals
    recorded in device.py. If metadata is unreachable the UI gets None
    and renders "~".
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from src.manifest import APP_DATA_DIR

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "cancel_requested": False,
    "cancelled": False,
    "phase": None,        # artifact currently downloading, e.g. "llm_weights"
    "error": None,        # user-safe message; phase it died in stays in "phase"
    "started_at": None,
}

# The child currently downloading, so cancel can terminate it. Guarded by
# _lock for assignment; the worker is the only writer.
_current_proc: Optional[multiprocessing.Process] = None

_BINARY_SIZE_BYTES = 40 * 1024 * 1024  # ~binary + runtime libs; display-only

# Lazily-populated {filename: bytes} for the LLM artifacts. HF metadata is
# one HEAD-ish call per file; cached for the process lifetime.
_size_cache: dict[str, Optional[int]] = {}


# ---------------------------------------------------------------------------
# What does this machine need?
# ---------------------------------------------------------------------------


def _llm_spec() -> dict[str, Any]:
    """The three LLM artifacts for the active profile, resolved once per call
    so env overrides keep working."""
    from src.inference.model_downloader import _filename_for, _mmproj_filename_for
    from src.inference.profiles import default_text_profile, get_profile

    args = get_profile(default_text_profile()).args
    return {
        "repo": args.repo_id,
        "quant": args.quant,
        "weights_file": _filename_for(args.repo_id, args.quant),
        "mmproj_repo": args.mmproj_repo_id,
        "mmproj_file": (
            _mmproj_filename_for(args.mmproj_repo_id, args.mmproj_variant)
            if args.mmproj_repo_id
            else None
        ),
    }


def _visual_spec() -> dict[str, Any]:
    """The retriever detect_device() picked, plus its transitively-loaded
    base repo — the part `model_id` alone hides (see device.py)."""
    from src.stage1_fast.device import (
        COLQWEN_BASE_ID,
        COLQWEN_MODEL_ID,
        COLQWEN_TOTAL_GB,
        COLSMOL_BASE_ID,
        COLSMOL_TOTAL_GB,
        detect_device,
    )

    cfg = detect_device()
    if cfg.model_id == COLQWEN_MODEL_ID:
        base, total_gb = COLQWEN_BASE_ID, COLQWEN_TOTAL_GB
    else:
        base, total_gb = COLSMOL_BASE_ID, COLSMOL_TOTAL_GB
    return {"adapter": cfg.model_id, "base": base, "total_gb": total_gb}


# ---------------------------------------------------------------------------
# Present / ready checks — all offline, no network
# ---------------------------------------------------------------------------


def _binary_status() -> dict[str, Any]:
    try:
        from src.inference.llama_server_binary import (
            find_llama_server,
            get_binary_version,
        )

        path = find_llama_server()
        _raw, build = get_binary_version(path)
        return {"present": True, "version": build}
    except Exception:  # noqa: BLE001 — missing/broken binary == not present
        return {"present": False, "version": None}


def _hf_file_present(repo: str, filename: str) -> bool:
    try:
        from huggingface_hub import hf_hub_download

        hf_hub_download(repo_id=repo, filename=filename, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _hf_repo_present(repo: str) -> bool:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=repo, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def is_llm_ready() -> bool:
    """Binary + weights + projector all present. This is what the Settings
    'Local' card's `downloaded` flag means — the visual tier is deliberately
    excluded, since T4 indexing uses it regardless of provider."""
    spec = _llm_spec()
    if not _binary_status()["present"]:
        return False
    if not _hf_file_present(spec["repo"], spec["weights_file"]):
        return False
    if spec["mmproj_file"] and not _hf_file_present(
        spec["mmproj_repo"], spec["mmproj_file"]
    ):
        return False
    return True


# ---------------------------------------------------------------------------
# Progress accounting (read-side)
# ---------------------------------------------------------------------------


def _repo_cache_dir(repo: str) -> Path:
    return (
        APP_DATA_DIR / "cache" / "hub" / f"models--{repo.replace('/', '--')}"
    )


def _bytes_on_disk(repo: str, filename: Optional[str] = None) -> int:
    """Bytes downloaded so far for a repo (or one file), counting partials.

    HF stores content-addressed blobs plus `.incomplete` partials in
    `blobs/`; snapshot filenames are symlinks into it. For a single file we
    can't map filename→blob without the etag, so single-file accounting
    counts the whole repo's blobs — correct for our repos, where the only
    things we ever fetch are the artifacts we account for.
    """
    d = _repo_cache_dir(repo) / "blobs"
    if not d.is_dir():
        return 0
    total = 0
    for p in d.iterdir():
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


def _remote_size(repo: str, filename: str) -> Optional[int]:
    """Total bytes for one HF file, cached. None when offline."""
    key = f"{repo}/{filename}"
    if key in _size_cache:
        return _size_cache[key]
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_url

        meta = get_hf_file_metadata(hf_hub_url(repo, filename), timeout=5.0)
        _size_cache[key] = meta.size
    except Exception:  # noqa: BLE001 — offline → unknown, UI shows "~"
        _size_cache[key] = None
    return _size_cache[key]


# ---------------------------------------------------------------------------
# Download targets — run in a CHILD PROCESS, must stay module-level picklable
# ---------------------------------------------------------------------------


def _dl_binary() -> None:
    from src.tools.install_llama_server import download_and_install

    download_and_install(skip_mmproj=True)


def _dl_hf_file(repo: str, filename: str) -> None:
    from huggingface_hub import hf_hub_download

    hf_hub_download(repo_id=repo, filename=filename)


def _dl_hf_repo(repo: str) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=repo)


def _execute(target: Callable, *args: Any) -> Optional[str]:
    """Run `target(*args)` in a subprocess; poll for cancel; return an error
    string or None. Swappable in tests."""
    global _current_proc
    proc = multiprocessing.Process(target=target, args=args, daemon=True)
    proc.start()
    with _lock:
        _current_proc = proc
    try:
        while proc.is_alive():
            if _state["cancel_requested"]:
                proc.terminate()
                proc.join(10)
                return "cancelled"
            proc.join(0.25)
        if proc.exitcode != 0:
            return f"download subprocess exited with code {proc.exitcode}"
        return None
    finally:
        with _lock:
            _current_proc = None


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------


def _preflight_disk(needed_bytes: int) -> Optional[str]:
    try:
        free = shutil.disk_usage(str(APP_DATA_DIR)).free
    except OSError:
        return None  # can't measure → don't block on it
    # 10% headroom: hf writes the .incomplete next to the final blob.
    if free < needed_bytes * 1.1:
        need_gb = needed_bytes / 1024**3
        free_gb = free / 1024**3
        return (
            f"Not enough disk space: this download needs about "
            f"{need_gb:.1f} GB plus headroom, but only {free_gb:.1f} GB is free."
        )
    return None


def _plan() -> list[tuple[str, Callable, tuple]]:
    """Ordered (phase, target, args) for every MISSING artifact. Binary
    first — smallest, and the one that fails for structural reasons."""
    steps: list[tuple[str, Callable, tuple]] = []
    llm = _llm_spec()
    if not _binary_status()["present"]:
        steps.append(("binary", _dl_binary, ()))
    if not _hf_file_present(llm["repo"], llm["weights_file"]):
        steps.append(("llm_weights", _dl_hf_file, (llm["repo"], llm["weights_file"])))
    if llm["mmproj_file"] and not _hf_file_present(llm["mmproj_repo"], llm["mmproj_file"]):
        steps.append(("mmproj", _dl_hf_file, (llm["mmproj_repo"], llm["mmproj_file"])))
    vis = _visual_spec()
    if not _hf_repo_present(vis["adapter"]):
        steps.append(("visual_adapter", _dl_hf_repo, (vis["adapter"],)))
    if not _hf_repo_present(vis["base"]):
        steps.append(("visual_base", _dl_hf_repo, (vis["base"],)))
    return steps


def _estimate_remaining_bytes(steps: list[tuple[str, Callable, tuple]]) -> int:
    llm = _llm_spec()
    vis = _visual_spec()
    total = 0
    for phase, _t, _a in steps:
        if phase == "binary":
            total += _BINARY_SIZE_BYTES
        elif phase == "llm_weights":
            total += _remote_size(llm["repo"], llm["weights_file"]) or 0
        elif phase == "mmproj":
            total += _remote_size(llm["mmproj_repo"], llm["mmproj_file"]) or 0
        elif phase in ("visual_adapter", "visual_base"):
            # split the measured repo-pair total across the two steps
            total += int(vis["total_gb"] * 1024**3 / 2)
    return total


def _worker() -> None:
    try:
        steps = _plan()
        err = _preflight_disk(_estimate_remaining_bytes(steps))
        if err:
            with _lock:
                _state.update(running=False, error=err, phase=None)
            return
        for phase, target, args in steps:
            with _lock:
                if _state["cancel_requested"]:
                    _state.update(running=False, cancelled=True, phase=None)
                    return
                _state["phase"] = phase
            result = _execute(target, *args)
            if result == "cancelled":
                with _lock:
                    _state.update(running=False, cancelled=True, phase=None)
                return
            if result is not None:
                with _lock:
                    _state.update(running=False, error=result)
                return
        with _lock:
            _state.update(running=False, phase=None)
    except Exception as e:  # noqa: BLE001 — worker must never die silently
        with _lock:
            _state.update(running=False, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Public API — what server.py's endpoints call
# ---------------------------------------------------------------------------


def start_install() -> tuple[bool, str]:
    """Kick off the worker. Returns (started, message)."""
    with _lock:
        if _state["running"]:
            return False, "already downloading"
        _state.update(
            running=True,
            cancel_requested=False,
            cancelled=False,
            error=None,
            phase="starting",
            started_at=time.time(),
        )
    threading.Thread(target=_worker, daemon=True, name="local-install").start()
    return True, "started"


def cancel_install() -> tuple[bool, str]:
    with _lock:
        if not _state["running"]:
            return False, "nothing downloading"
        _state["cancel_requested"] = True
        proc = _current_proc
    if proc is not None and proc.is_alive():
        proc.terminate()
    return True, "cancelling"


def delete_models(component: str = "all") -> dict[str, Any]:
    """Remove downloaded model data. Refuses while a download runs.

    component: "llm" | "visual" | "all". The llama-server binary is NOT
    removed — it is 40 MB and removing it would just re-trip the platform
    detection on reinstall.
    """
    with _lock:
        if _state["running"]:
            return {"deleted": [], "error": "a download is running; cancel it first"}
    deleted: list[str] = []
    targets: list[str] = []
    if component in ("llm", "all"):
        targets.append(_llm_spec()["repo"])
    if component in ("visual", "all"):
        vis = _visual_spec()
        targets.extend([vis["adapter"], vis["base"]])
    for repo in targets:
        d = _repo_cache_dir(repo)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            deleted.append(repo)
    return {"deleted": deleted, "error": None}


def status() -> dict[str, Any]:
    """Everything the Settings card needs, in one poll."""
    llm = _llm_spec()
    vis = _visual_spec()
    binary = _binary_status()

    weights_present = _hf_file_present(llm["repo"], llm["weights_file"])
    mmproj_present = (
        _hf_file_present(llm["mmproj_repo"], llm["mmproj_file"])
        if llm["mmproj_file"]
        else True
    )
    adapter_present = _hf_repo_present(vis["adapter"])
    base_present = _hf_repo_present(vis["base"])

    llm_ready = binary["present"] and weights_present and mmproj_present
    visual_ready = adapter_present and base_present

    with _lock:
        running = _state["running"]
        phase = _state["phase"]
        error = _state["error"]
        cancelled = _state["cancelled"]

    if running:
        overall = "downloading"
    elif error:
        overall = "error"
    elif llm_ready and visual_ready:
        overall = "ready"
    else:
        overall = "not_installed"

    weights_total = _remote_size(llm["repo"], llm["weights_file"])
    mmproj_total = (
        _remote_size(llm["mmproj_repo"], llm["mmproj_file"])
        if llm["mmproj_file"]
        else 0
    )
    # Per-repo byte accounting; LLM weights+mmproj share one repo dir.
    llm_bytes_done = _bytes_on_disk(llm["repo"])
    visual_bytes_done = _bytes_on_disk(vis["adapter"]) + _bytes_on_disk(vis["base"])

    return {
        "state": overall,
        "running": running,
        "phase": phase,
        "error": error,
        "cancelled": cancelled,
        "llm": {
            "ready": llm_ready,
            "binary": binary,
            "repo": llm["repo"],
            "quant": llm["quant"],
            "weights": {"file": llm["weights_file"], "present": weights_present,
                        "bytes_total": weights_total},
            "mmproj": {"file": llm["mmproj_file"], "present": mmproj_present,
                       "bytes_total": mmproj_total},
            "bytes_done": llm_bytes_done,
            "bytes_total": (weights_total or 0) + (mmproj_total or 0) or None,
        },
        "visual": {
            "ready": visual_ready,
            "adapter": vis["adapter"],
            "base": vis["base"],
            "bytes_done": visual_bytes_done,
            "bytes_total": int(vis["total_gb"] * 1024**3),
        },
    }
