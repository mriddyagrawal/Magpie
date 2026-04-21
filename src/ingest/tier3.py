"""Tier 3 — LLM-produced structured summary.

Used for: receipts, bank statements, contracts, scanned short PDFs, and any
file where the content router auto-upgraded criticality. This is today's
Stage 1 behavior — `FileSummary(title, summary, keywords, key_entities,
identifiers)` via the configured LLM. Most files skip T3 under the new
router; the ones that land here genuinely earn the LLM call.

Depends on the existing Stage-1 machinery in `src/stage1/summarize.py`
(agent build, build_user_message, retry loop, render_markdown) so the output
shape stays byte-compatible with Stage 2's parser.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic_ai import Agent

from src.ingest.common import (
    SUMMARIES_DIR,
    TierOutcome,
    hash_file,
    summary_rel_path,
    write_summary,
)
from src.stage1.summarize import (
    FileSummary,
    _run_with_retry,
    build_user_message,
    render_markdown,
)


async def run_async(
    path: Path,
    source_rel: str,
    agent: Agent[None, FileSummary],
) -> TierOutcome:
    """Run the LLM summary and write <hash>_t3.md. Retries on 429 like Stage 1."""
    digest = await asyncio.to_thread(hash_file, path)
    out_path = SUMMARIES_DIR / f"{digest}_t3.md"
    message = await asyncio.to_thread(build_user_message, path)
    result = await _run_with_retry(agent, message, path.name)
    body_markdown = render_markdown(result.output, source_rel)
    await asyncio.to_thread(write_summary, out_path, body_markdown)
    return TierOutcome(
        summary_file_rel=summary_rel_path(out_path),
        body_chars=len(body_markdown),
    )


def run(path: Path, source_rel: str, agent: Agent[None, FileSummary]) -> TierOutcome:
    """Sync convenience wrapper — runs the async path via asyncio.run."""
    return asyncio.run(run_async(path, source_rel, agent))
