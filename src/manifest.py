"""Persistent state for stages 1 (summarize) and 2 (ingest).

Every source file that has been summarized gets a row here. Stage 1 uses the
manifest to skip unchanged files without hashing. Stage 2 uses it to know
which summaries are already in Qdrant.

Schema (JSON dict keyed by repo-relative source path):

    {
      "Test Content/Flight GSP - Hartford Receipt.pdf": {
        "size": 17616,
        "summary_file": "Test Summaries/8c2bbf673a91ef8d.md",
        "summarized_at": "2026-04-13T01:42:00Z",
        "ingested_at":   "2026-04-13T01:45:00Z"
      },
      ...
    }

Change detection uses `size` only. If the byte count is identical, we assume
the content hasn't changed. Content changes that preserve size exactly (rare
in practice for anything other than binary blob edits) will be missed.

Hard-delete policy: any path in the manifest whose file no longer exists on
disk is removed from the manifest on the next summarize run, along with its
summary file. Stage 2's next ingest run will notice the missing source path
and delete the corresponding Qdrant point.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir


# ---------------------------------------------------------------------------
# Paths — portable across Linux / Windows / macOS via `platformdirs`.
#
#   Linux   : ~/.local/share/Magpie/
#   Windows : %LOCALAPPDATA%\magpie\Magpie\
#   macOS   : ~/Library/Application Support/Magpie/
#
# Override for dev/CI by setting `MAGPIE_DATA_DIR` — useful for tests that
# want isolated, throwaway data dirs without touching the user's real one.
# ---------------------------------------------------------------------------

_APP_NAME = "Magpie"
_APP_AUTHOR = "magpie"


def _resolve_app_data_dir() -> Path:
    """Where Magpie keeps its runtime state (manifest, summaries, qdrant).

    Honors `MAGPIE_DATA_DIR` env override (absolute or ~-expandable), else
    falls back to the OS-appropriate user data dir from `platformdirs`.
    """
    override = os.environ.get("MAGPIE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_dir(_APP_NAME, _APP_AUTHOR, roaming=False))


APP_DATA_DIR = _resolve_app_data_dir()
"""User data root: manifest, summaries, qdrant collections all live under
this. Use this for any path the app writes to at runtime."""

SUMMARIES_DIR = APP_DATA_DIR / "summaries"
"""Tier-output markdown files live here, one per indexed source file."""

DEFAULT_MANIFEST_PATH = APP_DATA_DIR / "manifest.json"
"""Per-file metadata index — the source of truth for what's been ingested."""

# Redirect HuggingFace's model cache into APP_DATA_DIR/cache/ so embedding
# and visual-tier model files don't leak into the user's shared cache
# (~/.cache/huggingface/hub/) where directory names like
# `models--vidore--colSmol-500M` directly identify our stack to anyone
# browsing. This must be set BEFORE any transformers / sentence-transformers
# / colpali-engine import — putting it here guarantees that, since
# APP_DATA_DIR is required by every code path that loads a model.
_MODEL_CACHE_DIR = APP_DATA_DIR / "cache"
os.environ.setdefault("HF_HOME", str(_MODEL_CACHE_DIR))
os.environ.setdefault("HF_HUB_CACHE", str(_MODEL_CACHE_DIR / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(_MODEL_CACHE_DIR))

# Backward-compat alias. Existing imports of `REPO_ROOT` for data-path
# resolution (manifest entries store summary paths relative to this) keep
# working unchanged. New code should reference `APP_DATA_DIR` directly.
REPO_ROOT = APP_DATA_DIR


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Entry:
    size: int
    summary_file: str | None = None
    summarized_at: str = ""
    ingested_at: str | None = None
    row_count: int | None = None
    fast_indexed_at: str | None = None  # set when the file lands in fast_tier
    fast_pages: int | None = None        # page count indexed into fast_tier
    # Optional file mtime (seconds since epoch). Captured at ingest time when
    # MAGPIE_DEV_USE_MTIME=1 is set; used by `needs_summarization` as a
    # secondary check (size-only is the production default — see
    # `Plans/Ingestion Rules/Implementation Plan.md` §6 / Future Plan #14).
    # Always optional + nullable so old manifests load cleanly.
    mtime: float | None = None
    # Router audit trail (src/router.py + Plans/Indexing Tiers.md). Defaults
    # are backward-compatible: pre-router manifest rows load cleanly.
    routes: list[str] = field(default_factory=list)
    visual_score: int = 0
    sensitivity_score: int = 0
    t4_cost_mb: float = 0.0
    t4_cost_s: float = 0.0
    criticality: str = "normal"            # "critical" | "normal" | "casual"
    criticality_source: str = "default"    # "user" | "auto" | "default"
    skip_reason: str | None = None


class Manifest:
    """Mutable, file-backed mapping from source path -> Entry.

    Thread-unsafe; caller must serialize mutations (an asyncio.Lock around
    mark_summarized / mark_ingested / drop is sufficient in the stage 1 batch).
    """

    def __init__(self, path: Path = DEFAULT_MANIFEST_PATH) -> None:
        self.path = path
        self.entries: dict[str, Entry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.entries = {}
            return
        with self.path.open(encoding="utf-8") as f:
            raw = json.load(f)
        # Accept-what-we-know: old manifest rows may be missing new fields
        # (defaults apply) and future rows may have fields we don't know about
        # (silently drop rather than crash on downgrade).
        known = {f.name for f in Entry.__dataclass_fields__.values()}
        self.entries = {
            k: Entry(**{kk: vv for kk, vv in v.items() if kk in known})
            for k, v in raw.items()
        }

    def save(self) -> None:
        """Atomic write: stage to <path>.tmp, then rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(
                {k: asdict(v) for k, v in sorted(self.entries.items())},
                f,
                indent=2,
                ensure_ascii=False,
            )
            f.write("\n")
        tmp.replace(self.path)

    # ---- queries --------------------------------------------------------

    def get(self, rel_path: str) -> Entry | None:
        return self.entries.get(rel_path)

    def paths(self) -> list[str]:
        return list(self.entries.keys())

    def needs_summarization(
        self,
        rel_path: str,
        current_size: int,
        current_mtime: float | None = None,
    ) -> bool:
        """True if rel_path is new to us, or its byte size has changed.

        With MAGPIE_DEV_USE_MTIME=1 set in the environment AND a non-None
        `current_mtime` provided, ALSO returns True when the on-disk mtime
        is newer than the recorded `entry.mtime`. This catches "user
        re-saved with no byte changes" — useful for dev/debug workflows
        where you want to force re-summarization on touch. Production
        default (env unset) ignores mtime entirely. See Future Plan #14
        for graduating this to a user-facing setting.
        """
        entry = self.entries.get(rel_path)
        if entry is None:
            return True
        if entry.size != current_size:
            return True
        if (
            current_mtime is not None
            and entry.mtime is not None
            and os.environ.get("MAGPIE_DEV_USE_MTIME") == "1"
            and current_mtime > entry.mtime
        ):
            return True
        return False

    def needs_ingestion(self, rel_path: str) -> bool:
        """True if the row has been summarized but not yet ingested (or re-summarized)."""
        entry = self.entries.get(rel_path)
        if entry is None:
            return False
        return entry.ingested_at is None

    # ---- mutations ------------------------------------------------------

    def mark_summarized(self, rel_path: str, size: int, summary_file: str | None) -> None:
        """Record a successful summarization. Clears ingested_at so stage 2 re-ingests."""
        self.entries[rel_path] = Entry(
            size=size,
            summary_file=summary_file,
            summarized_at=_now_iso(),
            ingested_at=None,
        )

    def mark_ingested(self, rel_path: str) -> None:
        entry = self.entries.get(rel_path)
        if entry is None:
            raise KeyError(f"cannot mark ingested: {rel_path!r} not in manifest")
        entry.ingested_at = _now_iso()

    def drop(self, rel_path: str) -> Entry | None:
        """Remove a row and return the dropped Entry (or None if it wasn't there)."""
        return self.entries.pop(rel_path, None)

    def mark_routed(
        self,
        rel_path: str,
        size: int,
        *,
        routes: list[str],
        visual_score: int,
        sensitivity_score: int,
        t4_cost_mb: float,
        t4_cost_s: float,
        criticality: str,
        criticality_source: str,
        skip_reason: str | None = None,
    ) -> None:
        """Record the router's verdict. Creates the row if absent; preserves
        summary/ingest timestamps if present (so the walker can call this
        before the tier worker runs)."""
        entry = self.entries.get(rel_path)
        if entry is None:
            entry = Entry(size=size)
            self.entries[rel_path] = entry
        entry.size = size
        entry.routes = routes
        entry.visual_score = visual_score
        entry.sensitivity_score = sensitivity_score
        entry.t4_cost_mb = t4_cost_mb
        entry.t4_cost_s = t4_cost_s
        entry.criticality = criticality
        entry.criticality_source = criticality_source
        entry.skip_reason = skip_reason

    # ---- fast-tier helpers ---------------------------------------------

    def needs_fast_indexing(self, rel_path: str, current_size: int) -> bool:
        """True if this file isn't yet in the fast tier, or its size changed."""
        entry = self.entries.get(rel_path)
        if entry is None or entry.fast_indexed_at is None:
            return True
        return entry.size != current_size

    def mark_fast_indexed(self, rel_path: str, size: int, pages: int) -> None:
        """Record a successful fast-tier indexing. Preserves any summary state."""
        entry = self.entries.get(rel_path)
        if entry is None:
            self.entries[rel_path] = Entry(
                size=size,
                fast_indexed_at=_now_iso(),
                fast_pages=pages,
            )
        else:
            entry.size = size
            entry.fast_indexed_at = _now_iso()
            entry.fast_pages = pages
