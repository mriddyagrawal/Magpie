"""Single-slot backup and restore for the entire Magpie indexed state.

Captures everything that gets re-built by `just sync`:

  - manifest.json        (the file → tier/summary/ingestion bookkeeping)
  - summaries/*.md       (every parsed summary markdown on disk)
  - Qdrant collections   (snapshot the binary segments via Qdrant's native
                          snapshot API, so vectors / HNSW / quantization /
                          payload indexes restore exactly without re-embedding)

Single backup slot at `<APP_DATA_DIR>/backup/`. Each `create_backup()` call
overwrites the previous one atomically (stage to `.new/`, swap, drop `.old/`).
The `just sync` recipe auto-fires this at the end of every successful walk so
the user always has a recent known-good state to restore from — turning
`reset-index` from a 15-minute re-summarize disaster into a 30-second restore.

Python entry points (`create_backup()` / `restore_backup()`) are deliberately
shaped like `pipeline.reset()`: pure functions returning a stats dict, no CLI
side effects, safe to call from any caller (just recipes, future Tauri
sidecar HTTP endpoint, tests).

NOTE: only Magpie's local Qdrant (loopback, on the port db.py is configured
for) is supported, since the snapshot/recover round-trip uses HTTP downloads
+ `file://` URLs back into the same server. That matches the only deployment
shape db.py supports anyway.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.manifest import APP_DATA_DIR, DEFAULT_MANIFEST_PATH, SUMMARIES_DIR
from src.stage2.db import get_qdrant_client

BACKUP_DIR = APP_DATA_DIR / "backup"
_STAGING_DIR = APP_DATA_DIR / "backup.new"
_OLD_DIR = APP_DATA_DIR / "backup.old"

_BACKUP_FORMAT_VERSION = 1


def _qdrant_base_url() -> str:
    """Resolve the localhost Qdrant URL the same way db.py does.

    Snapshot download / recover round-trips go through HTTP rather than
    poking at Qdrant's on-disk storage tree, so we don't need to know
    where the server stores its data — just where it listens.
    """
    return os.environ.get(
        "QDRANT_CLUSTER_ENDPOINT", "http://localhost:6433"
    ).rstrip("/")


def create_backup() -> dict[str, Any]:
    """Snapshot all Qdrant collections + copy manifest + summary markdowns
    into `<APP_DATA_DIR>/backup/`. Overwrites any prior backup atomically.

    Returns a stats dict (also written to `meta.json` inside the backup):

        {
          "magpie_backup_version": 1,
          "created_at": "<ISO8601 UTC>",
          "manifest_present": bool,
          "summary_count": int,
          "qdrant_collections": [
            {"name": str, "points": int, "size_bytes": int}, ...
          ],
          "qdrant_total_bytes": int,
          "qdrant_url": str,
          "backup_dir": str,
        }

    Raises on any hard failure (Qdrant down, disk full, etc.). The atomic
    rename means a partial failure leaves the previous backup intact —
    you'll find a `.new` directory to clean up but the canonical `backup/`
    is unchanged.
    """
    client = get_qdrant_client()

    # Stage to a sibling temp dir; atomic rename only happens on full success.
    if _STAGING_DIR.exists():
        shutil.rmtree(_STAGING_DIR)
    _STAGING_DIR.mkdir(parents=True)

    stats: dict[str, Any] = {
        "magpie_backup_version": _BACKUP_FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_present": False,
        "summary_count": 0,
        "qdrant_collections": [],
        "qdrant_total_bytes": 0,
        "qdrant_url": _qdrant_base_url(),
        "backup_dir": str(BACKUP_DIR),
    }

    # ---- 1. Manifest -----------------------------------------------------
    if DEFAULT_MANIFEST_PATH.exists():
        shutil.copy2(DEFAULT_MANIFEST_PATH, _STAGING_DIR / "manifest.json")
        stats["manifest_present"] = True

    # ---- 2. Summary markdowns -------------------------------------------
    summaries_out = _STAGING_DIR / "summaries"
    summaries_out.mkdir()
    if SUMMARIES_DIR.is_dir():
        for md in SUMMARIES_DIR.glob("*.md"):
            shutil.copy2(md, summaries_out / md.name)
            stats["summary_count"] += 1

    # ---- 3. Qdrant collections ------------------------------------------
    qdrant_out = _STAGING_DIR / "qdrant"
    qdrant_out.mkdir()

    collections = [c.name for c in client.get_collections().collections]
    base_url = _qdrant_base_url()
    for col in collections:
        info = client.get_collection(col)
        snap_desc = client.create_snapshot(collection_name=col)
        snap_name = snap_desc.name  # e.g. "summaries-1234567890-abc.snapshot"
        try:
            dest = qdrant_out / f"{col}.snapshot"
            url = f"{base_url}/collections/{col}/snapshots/{snap_name}"
            urllib.request.urlretrieve(url, dest)
            size = dest.stat().st_size
            stats["qdrant_collections"].append({
                "name": col,
                "points": info.points_count or 0,
                "size_bytes": size,
            })
            stats["qdrant_total_bytes"] += size
        finally:
            # Always clean up the server-side snapshot so it doesn't leak
            # into Qdrant's storage dir between backup runs.
            try:
                client.delete_snapshot(
                    collection_name=col, snapshot_name=snap_name,
                )
            except Exception:  # pylint: disable=broad-except
                pass

    # ---- 4. Meta + atomic swap ------------------------------------------
    (_STAGING_DIR / "meta.json").write_text(
        json.dumps(stats, indent=2) + "\n", encoding="utf-8",
    )

    if BACKUP_DIR.exists():
        if _OLD_DIR.exists():
            shutil.rmtree(_OLD_DIR)
        BACKUP_DIR.rename(_OLD_DIR)
    _STAGING_DIR.rename(BACKUP_DIR)
    if _OLD_DIR.exists():
        shutil.rmtree(_OLD_DIR)

    return stats


def restore_backup() -> dict[str, Any]:
    """Restore from `<APP_DATA_DIR>/backup/`. Destructive.

    Drops every collection that the backup contains (so a half-written
    in-progress collection doesn't survive), recovers each from its
    snapshot file, then replaces the on-disk manifest + every summary
    markdown.

    Raises `FileNotFoundError` if no backup exists. Caller is responsible
    for confirming with the user before calling — `reset()`-style
    semantics (no built-in prompt; a CLI / GUI wrapper asks).
    """
    if not BACKUP_DIR.is_dir():
        raise FileNotFoundError(
            f"no backup found at {BACKUP_DIR}. Run `just backup` first "
            f"(or `just sync`, which auto-backs-up at the end)."
        )

    meta_path = BACKUP_DIR / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(
            f"backup at {BACKUP_DIR} is missing meta.json — looks corrupt; "
            f"manually inspect or delete and re-run `just backup`."
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    fmt_version = meta.get("magpie_backup_version", 0)
    if fmt_version != _BACKUP_FORMAT_VERSION:
        raise RuntimeError(
            f"backup format version {fmt_version} unsupported "
            f"(this build expects {_BACKUP_FORMAT_VERSION}). Re-create the "
            f"backup with the current Magpie build."
        )

    client = get_qdrant_client()

    # ---- 1. Qdrant: drop existing then upload-and-recover each snapshot --
    # We use the multipart-upload endpoint rather than `client.recover_snapshot`
    # with a `file://` URL because Qdrant 1.17 enforces that any file:// path
    # must live inside the server's own snapshots dir (a security check
    # against arbitrary local-disk reads). The upload endpoint takes the
    # bytes over HTTP, side-stepping the path restriction without needing
    # us to know or write into Qdrant's snapshots dir.
    import requests

    qdrant_dir = BACKUP_DIR / "qdrant"
    base_url = _qdrant_base_url()
    restored: list[str] = []
    for col_info in meta.get("qdrant_collections", []):
        name = col_info["name"]
        snap_path = qdrant_dir / f"{name}.snapshot"
        if not snap_path.is_file():
            raise FileNotFoundError(
                f"backup is missing snapshot file for collection {name!r} "
                f"at {snap_path}; refusing partial restore."
            )

        if client.collection_exists(name):
            client.delete_collection(name)

        upload_url = f"{base_url}/collections/{name}/snapshots/upload?priority=snapshot"
        with snap_path.open("rb") as fh:
            resp = requests.post(
                upload_url,
                files={"snapshot": (snap_path.name, fh, "application/octet-stream")},
                # Long timeout: large snapshots (multi-GB ColPali tiers) take
                # real wall-clock to upload + recover even on loopback.
                timeout=600,
            )
        if not resp.ok:
            raise RuntimeError(
                f"snapshot upload failed for collection {name!r}: "
                f"{resp.status_code} {resp.text}"
            )
        restored.append(name)

    # ---- 2. Manifest ----------------------------------------------------
    manifest_src = BACKUP_DIR / "manifest.json"
    manifest_restored = False
    if manifest_src.exists():
        DEFAULT_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_src, DEFAULT_MANIFEST_PATH)
        manifest_restored = True

    # ---- 3. Summary markdowns ------------------------------------------
    summaries_src = BACKUP_DIR / "summaries"
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    # Wipe whatever's there now so a leftover post-reset markdown can't
    # masquerade as a backup-restored one.
    summary_count = 0
    for md in SUMMARIES_DIR.glob("*.md"):
        md.unlink()
    if summaries_src.is_dir():
        for md in summaries_src.glob("*.md"):
            shutil.copy2(md, SUMMARIES_DIR / md.name)
            summary_count += 1

    return {
        "restored_collections": restored,
        "manifest_restored": manifest_restored,
        "summary_count": summary_count,
        "from_backup_created_at": meta.get("created_at", "unknown"),
    }


def backup_info() -> dict[str, Any] | None:
    """Return the current backup's `meta.json` contents, or None if no
    backup exists. Cheap (one file read) — safe to call from a UI to
    drive a "last backup: …" status pill.
    """
    if not BACKUP_DIR.is_dir():
        return None
    meta_path = BACKUP_DIR / "meta.json"
    if not meta_path.is_file():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))
