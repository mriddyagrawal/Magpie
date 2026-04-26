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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = REPO_ROOT / "Test Summaries" / "_manifest.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Entry:
    size: int
    summary_file: str | None = None
    summarized_at: str = ""
    ingested_at: str | None = None
    fast_indexed_at: str | None = None  # set when the file lands in fast_tier
    fast_pages: int | None = None        # page count indexed into fast_tier
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

    def mark_summarized(self, rel_path: str, size: int, summary_file: str | None) -> None:
        """Record a successful summarization. Clears ingested_at so stage 2 re-ingests.

        Mutates the existing entry rather than replacing it. Other fields owned
        by **other indexing paths** — fast-tier state (`fast_indexed_at`,
        `fast_pages`) and the router audit trail (`routes`, scores,
        `criticality`, etc.) — must NOT be wiped when this tier completes its
        own work. A real bug existed before 2026-04-25 where this method
        replaced the entry wholesale, silently zeroing out `fast_indexed_at`
        on any file that was first ColPali-indexed and then re-summarized;
        the fast-tier vectors still lived in Qdrant but the manifest forgot
        about them, so subsequent ingests would re-encode unnecessarily.
        Symmetric to `mark_fast_indexed` (which correctly mutates) and
        `mark_routed` (also mutates).
        """
        entry = self.entries.get(rel_path)
        if entry is None:
            entry = Entry(size=size)
            self.entries[rel_path] = entry
        entry.size = size
        entry.summary_file = summary_file
        entry.summarized_at = _now_iso()
        entry.ingested_at = None  # re-ingest needed since the summary changed

    def mark_ingested(self, rel_path: str) -> None:
        entry = self.entries.get(rel_path)
        if entry is None:
            raise KeyError(f"cannot mark ingested: {rel_path!r} not in manifest")
        entry.ingested_at = _now_iso()

    def drop(self, rel_path: str) -> Entry | None:
        """Remove a row and return the dropped Entry (or None if it wasn't there)."""
        return self.entries.pop(rel_path, None)

    def clean_missing_summaries(self) -> dict[str, int]:
        """Inverse of `clean_stale`: clear stale `summary_file` pointers when
        the on-disk markdown is gone but the source file is still present.

        This handles the case where summary markdowns disappear independently
        of the source — typical causes:
          * User manually deleted `Test Summaries/` to free disk
          * `--rebuild` interrupted partway, leaving manifest references to
            now-missing files
          * Backup / sync software cleared `Test Summaries/` as "cache"
          * Disk corruption or filesystem rollback

        Symptom in the field: Stage 2 ingest spams `warn: summary missing,
        skipping: Test Summaries/<hash>_t1.md` because the manifest says the
        file is summarized but the markdown is gone.

        Behavior: for each row whose `summary_file` doesn't exist on disk:
          * Source still exists → clear `summary_file`/`summarized_at`/
            `ingested_at` so the next walker run re-summarizes it.
          * Source ALSO gone → drop the row entirely (covered by
            `clean_stale` too; we re-do that work here so the user only
            needs one cleanup call).

        Returns `{"resummarize": N, "dropped": M}`. Caller must `save()` after.
        """
        resummarize = 0
        dropped = 0
        for rel in list(self.paths()):
            entry = self.get(rel)
            if entry is None or not entry.summary_file:
                continue
            summary_abs = REPO_ROOT / entry.summary_file
            if summary_abs.is_file():
                continue  # summary intact, nothing to do
            # Summary missing. Decide based on source presence.
            source_abs = REPO_ROOT / rel if not rel.startswith("/") else Path(rel)
            if source_abs.is_file():
                # Re-summarize on next ingest run.
                entry.summary_file = None
                entry.summarized_at = ""
                entry.ingested_at = None
                resummarize += 1
            else:
                # Source AND summary both gone — drop the whole row.
                self.drop(rel)
                dropped += 1
        return {"resummarize": resummarize, "dropped": dropped}

    def clean_stale(self) -> dict[str, int]:
        """Drop manifest rows whose source file no longer exists on disk, and
        delete the orphaned summary markdown for each.

        Used to clean up manifest pollution from earlier ingest runs whose
        sources have since been deleted (the typical case: pytest fixture
        directories under `/tmp/...` that vanished after the test ran).

        The walker's per-run prune at `walker.py:run_batch` only touches
        entries under the walked root — `/tmp/...` entries linger if the
        user ingests `/home/me/sem6` instead. This method does an
        unconditional sweep across the whole manifest.

        Qdrant orphan cleanup happens automatically on the next stage 2
        ingest run (it diffs `manifest.paths()` against `get_all_point_ids()`
        and deletes the difference). Caller is responsible for triggering
        that — either by re-ingesting or by running `python -m src.stage2 ingest`.

        Returns `{"dropped": N, "summaries_removed": M}`. Caller must call
        `save()` afterward to persist.
        """
        dropped = 0
        summaries_removed = 0
        for rel in list(self.paths()):
            # Manifest keys may be repo-relative or absolute. Resolve to abs.
            abs_path = REPO_ROOT / rel if not rel.startswith("/") else Path(rel)
            if abs_path.is_file():
                continue
            entry = self.drop(rel)
            dropped += 1
            if entry and entry.summary_file:
                summary_abs = REPO_ROOT / entry.summary_file
                if summary_abs.is_file():
                    try:
                        summary_abs.unlink()
                        summaries_removed += 1
                    except OSError:
                        pass  # best-effort; manifest still cleaned
        return {"dropped": dropped, "summaries_removed": summaries_removed}

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

    def reconcile_from_fast_tier(self) -> dict[str, int]:
        """Rebuild lost `fast_indexed_at` / `fast_pages` from Qdrant fast_tier.

        Recovery method for the pre-2026-04-25 `mark_summarized` bug that
        wiped fast-tier fields when a previously-T4-indexed file got
        re-summarized. The Qdrant fast_tier collection still holds the
        vectors — this scrolls it, counts pages per source path, and
        re-stamps the manifest with the recovered state. Caller must
        `save()` afterward.

        Returns `{"recovered": N, "missing_in_manifest": M}` where the
        second count tracks paths that have fast_tier vectors but no
        manifest row at all (rare; would require manual investigation).
        """
        # Local import — avoids a load-time cycle and keeps this method
        # callable in tests without spinning up Qdrant unless invoked.
        from collections import Counter
        from src.stage2.db import get_qdrant_client
        from src.stage2.fast_db import FAST_COLLECTION_NAME

        client = get_qdrant_client()
        if not client.collection_exists(FAST_COLLECTION_NAME):
            return {"recovered": 0, "missing_in_manifest": 0}

        # Scroll the entire fast_tier collection, counting pages per source.
        page_counts: Counter[str] = Counter()
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=FAST_COLLECTION_NAME,
                limit=512,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                src = (p.payload or {}).get("source_path")
                if src:
                    page_counts[src] += 1
            if offset is None:
                break

        recovered = 0
        missing = 0
        for src_path, n_pages in page_counts.items():
            entry = self.entries.get(src_path)
            if entry is None:
                missing += 1
                continue
            # Only restore if the field is currently empty — don't blow away
            # a freshly-set timestamp.
            if entry.fast_indexed_at is None:
                entry.fast_indexed_at = _now_iso()
                entry.fast_pages = n_pages
                recovered += 1
        return {"recovered": recovered, "missing_in_manifest": missing}
