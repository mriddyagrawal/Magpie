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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = REPO_ROOT / "Test Summaries" / "_manifest.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Entry:
    size: int
    summary_file: str
    summarized_at: str
    ingested_at: str | None = None


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
        self.entries = {k: Entry(**v) for k, v in raw.items()}

    def save(self) -> None:
        """Atomic write: stage to <path>.tmp, then rename."""
        self.path.parent.mkdir(exist_ok=True)
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

    def needs_summarization(self, rel_path: str, current_size: int) -> bool:
        """True if rel_path is new to us, or its byte size has changed."""
        entry = self.entries.get(rel_path)
        if entry is None:
            return True
        return entry.size != current_size

    def needs_ingestion(self, rel_path: str) -> bool:
        """True if the row has been summarized but not yet ingested (or re-summarized)."""
        entry = self.entries.get(rel_path)
        if entry is None:
            return False
        return entry.ingested_at is None

    # ---- mutations ------------------------------------------------------

    def mark_summarized(self, rel_path: str, size: int, summary_file: str) -> None:
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
