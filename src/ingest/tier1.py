"""Tier 1 — direct embed: file IS the content.

Used for: small `.txt .md .json .yaml .toml`, code files, small CSVs.

The non-CSV path is a no-LLM dump: we write a summary markdown whose body
is the raw file content (capped at DEFAULT_BODY_MAX_CHARS). Filename is
included in the title so BM25 hits filename-like queries. Stage 2's parser
then embeds that body verbatim — exact-token matches survive.

The **CSV path** (`run_csv_async`) is different: it generates a real
`FileSummary` via the LLM agent, sampling header + first ~20 rows / ~1000
chars. The row-level Qdrant points are still produced separately by
`src.stage2.csv_ingest.ingest_csv_rows` from the original file. So a CSV
ends up represented twice in different Qdrant collections / shapes:
  - one summary point (semantic-context-grade summary, for "what is this CSV?")
  - N row points (one per row, for "find the row that matches X")
The answer step combines them: row hits trigger row-window content, with
the file's summary attached as supplement. See Plans/Future Plans.md #17.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from src.ingest.common import (
    DEFAULT_BODY_MAX_CHARS,
    SUMMARIES_DIR,
    TierOutcome,
    hash_file,
    render_summary_markdown,
    summary_output_path,
    summary_rel_path,
    title_from_path,
    write_summary,
)

if TYPE_CHECKING:
    from src.llm import ChatAgent
    from src.stage1.summarize import FileSummary


# ---------------------------------------------------------------------------
# Non-CSV T1 (no LLM)
# ---------------------------------------------------------------------------

def run(path: Path, source_rel: str) -> TierOutcome:
    """Read the file, write a summary-markdown whose body is the raw content.

    Non-CSV path. CSVs go through `run_csv_async` (LLM-summarized).
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8", errors="ignore")

    ext = path.suffix.lower()

    cap = DEFAULT_BODY_MAX_CHARS
    body = raw[:cap].strip()
    if not body:
        body = "(empty file)"

    content_type = (
        "markdown" if ext in {".md", ".markdown"}
        else "code" if ext in {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
            ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".swift", ".kt",
            ".sh", ".sql",
        }
        else "config" if ext in {".json", ".yaml", ".yml", ".toml"}
        else "text"
    )

    md = render_summary_markdown(
        source_rel=source_rel,
        title=f"{title_from_path(path)} ({path.name})",
        body=body,
        content_type=content_type,
        keywords=[path.name, content_type],
        entities=[],
        identifiers=[path.name],
    )

    out = summary_output_path(path, "t1")
    write_summary(out, md)
    return TierOutcome(
        summary_file_rel=summary_rel_path(out),
        body_chars=len(body),
    )


# ---------------------------------------------------------------------------
# CSV T1 (LLM-summarized)
# ---------------------------------------------------------------------------

CSV_SAMPLE_MAX_ROWS = 20
"""How many rows after the header to feed the summarizer LLM. 20 is enough
for the LLM to recognize the row shape (column names + sample values) on
catalog/directory CSVs without ballooning the prompt. The full CSV is
still indexed row-by-row separately — this sample only feeds the
file-level summary, not the searchable content."""

CSV_SAMPLE_MAX_CHARS = 1000
"""Cap on total sample text fed to the LLM. Prevents wide CSVs (many
columns) from sending huge rows. The header is always kept; rows after
header are truncated to fit."""


def _csv_sample(
    path: Path,
    max_rows: int = CSV_SAMPLE_MAX_ROWS,
    max_chars: int = CSV_SAMPLE_MAX_CHARS,
) -> tuple[str, int]:
    """Read header + up to `max_rows` rows, capped at `max_chars` total.

    Returns `(text, n_rows_after_header)`. Rows are joined with `\\n`. The
    header always appears first so the LLM can name the columns regardless
    of how aggressively the row body is truncated.
    """
    lines: list[str] = []
    char_count = 0
    n_rows = 0
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for i, raw_line in enumerate(f):
                line = raw_line.rstrip("\n")
                if i == 0:
                    lines.append(line)
                    char_count += len(line) + 1
                    continue
                if n_rows >= max_rows or char_count + len(line) > max_chars:
                    break
                lines.append(line)
                char_count += len(line) + 1
                n_rows += 1
    except OSError:
        return ("", 0)
    return ("\n".join(lines), n_rows)


async def run_csv_async(
    path: Path,
    source_rel: str,
    agent: "ChatAgent[FileSummary]",
    *,
    inflight: dict[str, asyncio.Event] | None = None,
    inflight_lock: asyncio.Lock | None = None,
) -> TierOutcome:
    """T1 CSV path: sample, ask LLM for a `FileSummary`, write markdown.

    Phase A content-hash dedup mirrors T3: byte-identical CSVs across paths
    share one summary. The dedup short-circuits in the same order:

      1. Existing `<digest>_t1.md` on disk → reuse, mark deduped.
      2. Another worker computing this digest → await its event, then reuse.
      3. Otherwise, claim the digest, run the LLM, write the summary.
    """
    digest = await asyncio.to_thread(hash_file, path)
    out_path = SUMMARIES_DIR / f"{digest}_t1.md"
    summary_rel = summary_rel_path(out_path)

    if inflight is not None and inflight_lock is not None:
        if out_path.exists():
            return TierOutcome(
                summary_file_rel=summary_rel,
                body_chars=out_path.stat().st_size,
                deduped=True,
                content_hash=digest,
            )
        await inflight_lock.acquire()
        existing_event = inflight.get(digest)
        if existing_event is not None:
            inflight_lock.release()
            await existing_event.wait()
            if out_path.exists():
                return TierOutcome(
                    summary_file_rel=summary_rel,
                    body_chars=out_path.stat().st_size,
                    deduped=True,
                    content_hash=digest,
                )
            # Peer failed and never wrote — fall through and run ourselves.
        else:
            event = asyncio.Event()
            inflight[digest] = event
            inflight_lock.release()
            try:
                return await _do_csv_summarize(
                    path, source_rel, agent, out_path, summary_rel, digest
                )
            finally:
                event.set()

    # No inflight infrastructure (legacy / standalone): just run.
    return await _do_csv_summarize(
        path, source_rel, agent, out_path, summary_rel, digest
    )


async def _do_csv_summarize(
    path: Path,
    source_rel: str,
    agent: "ChatAgent[FileSummary]",
    out_path: Path,
    summary_rel: str,
    digest: str,
) -> TierOutcome:
    """The actual LLM-summary work for a CSV. Factored out so the dedup
    short-circuits don't duplicate the call site."""
    # Deferred imports keep this module import-cheap for non-CSV walks.
    from src.stage1.summarize import _run_with_retry, render_markdown

    sample_text, n_rows = await asyncio.to_thread(_csv_sample, path)
    if not sample_text:
        # File unreadable — fall back to a minimal summary so we don't break
        # the manifest. Stage 2 row-ingest will skip it cleanly too.
        from src.stage1.summarize import FileSummary
        summary = FileSummary(
            title=f"{path.name} (unreadable CSV)",
            summary=f"CSV file at {source_rel} could not be read for summarization.",
            content_type="other",
            keywords=[path.name, "csv", "error"],
            key_entities=[],
            identifiers=[path.name],
        )
    else:
        message = [
            f"Filename: {path.name}\n"
            f"This is a CSV file. Below is the header followed by the first "
            f"{n_rows} row(s) — a representative sample. Produce a structured "
            f"FileSummary describing what the CSV contains: what each row "
            f"represents, what kind of data the columns hold, and any "
            f"identifiers (column names, dataset name, etc.) that would "
            f"help someone search for this file by purpose, not just by "
            f"row contents.",
            sample_text,
        ]
        summary = await _run_with_retry(agent, message, path.name)

    body_markdown = render_markdown(summary, source_rel)
    # Append a deterministic stats block (row count, column names, per-column
    # distribution / numeric range). The LLM prose above is good for semantic
    # retrieval ("course catalog", "people directory"); the stats block
    # answers aggregation questions ("how many SUS courses?", "how many 0-credit
    # courses across all majors?") that small models otherwise undercount because
    # they're working from a top-k retrieval window, not the full file. See
    # benchmarks/course_information/REPORT.md for the failure mode that
    # motivated this. Compute is deterministic + fast (no LLM call) so we
    # do it unconditionally for every CSV at ingest time.
    from src.ingest.csv_stats import compute_csv_stats_markdown
    body_markdown += await asyncio.to_thread(compute_csv_stats_markdown, path)
    await asyncio.to_thread(write_summary, out_path, body_markdown)
    return TierOutcome(
        summary_file_rel=summary_rel,
        body_chars=len(body_markdown),
        deduped=False,
        content_hash=digest,
    )
