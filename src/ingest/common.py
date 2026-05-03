"""Shared helpers for tier workers: hashing, markdown rendering, paths."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from src.manifest import APP_DATA_DIR, SUMMARIES_DIR

# Re-export the canonical SUMMARIES_DIR from manifest so existing imports
# (`from src.ingest.common import SUMMARIES_DIR`) still work.
__all__ = ["SUMMARIES_DIR", "APP_DATA_DIR"]

# Path used to render manifest entries relative to the data root.
REPO_ROOT = APP_DATA_DIR

HASH_CHUNK = 1 << 20                      # 1 MiB
DEFAULT_BODY_MAX_CHARS = 8_000            # cap embedded text per file


@dataclass(frozen=True)
class TierOutcome:
    """What a tier worker returns after running. Consumed by the walker."""
    summary_file_rel: str | None          # repo-relative path to the generated md (or None)
    body_chars: int                        # length of embedded body (audit / debug)
    deduped: bool = False                  # True if work was skipped because
                                           # another path with identical content
                                           # already produced this tier's summary
    content_hash: str | None = None        # 16-char sha256 prefix (when computed)


def hash_file(path: Path) -> str:
    """SHA-256 digest of a file, returned as a 16-char hex prefix (same as Stage 1)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def source_rel_path(path: Path) -> str:
    """Repo-relative path if under the repo, otherwise absolute resolved path."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def _fmt_list(items: list[str]) -> str:
    return ", ".join(items) if items else "—"


def render_summary_markdown(
    *,
    source_rel: str,
    title: str,
    body: str,
    content_type: str,
    keywords: list[str] | None = None,
    entities: list[str] | None = None,
    identifiers: list[str] | None = None,
) -> str:
    """Produce the exact shape Stage 2's `parse_summary_file` expects."""
    return (
        f"Source: {source_rel}\n\n"
        f"# {title}\n\n"
        f"{body}\n\n"
        f"**Content type:** {content_type}\n\n"
        f"**Keywords:** {_fmt_list(keywords or [])}\n\n"
        f"**Key entities:** {_fmt_list(entities or [])}\n\n"
        f"**Identifiers:** {_fmt_list(identifiers or [])}\n"
    )


def summary_output_path(path: Path, tier: str) -> Path:
    """Deterministic output path: <APP_DATA_DIR>/summaries/<16-char hash>_<tier>.md."""
    digest = hash_file(path)
    return SUMMARIES_DIR / f"{digest}_{tier.lower()}.md"


def summary_rel_path(out_path: Path) -> str:
    """Repo-relative path for manifest storage, with absolute fallback."""
    try:
        return str(out_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(out_path.resolve())


def write_summary(out_path: Path, content: str) -> None:
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")


def title_from_path(path: Path) -> str:
    """Default title: filename (without extension), prettified."""
    return path.stem.replace("_", " ").replace("-", " ")[:80]
