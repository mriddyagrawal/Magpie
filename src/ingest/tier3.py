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

from src.ingest.common import (
    SUMMARIES_DIR,
    TierOutcome,
    hash_file,
    summary_rel_path,
    write_summary,
)
from src.llm import ChatAgent
from src.stage1.summarize import (
    FileSummary,
    _run_with_retry,
    build_user_message,
    render_markdown,
)


async def run_async(
    path: Path,
    source_rel: str,
    agent: ChatAgent[FileSummary],
    *,
    inflight: dict[str, asyncio.Event] | None = None,
    inflight_lock: asyncio.Lock | None = None,
) -> TierOutcome:
    """Run the LLM summary and write <hash>_t3.md. Retries on 429 like Stage 1.

    Phase A dedup: if `inflight` + `inflight_lock` are provided (the walker
    threads them in for batch dedup), three short-circuits apply in order:

    1. **Existing summary on disk.** If `<digest>_t3.md` already exists from
       a prior walk, skip the LLM call entirely and return a deduped
       outcome pointing at that file.
    2. **In-flight by another worker.** If a peer worker in this walk is
       currently computing this digest, await its event and reuse the
       summary it produces.
    3. **Claim it.** Otherwise, register the digest in `inflight`, run the
       LLM, write the summary, and signal the event so any peer awaiters
       can finish.

    `inflight=None` (the default) preserves the pre-dedup behavior — useful
    for tests and standalone calls that don't go through the walker.
    """
    digest = await asyncio.to_thread(hash_file, path)
    out_path = SUMMARIES_DIR / f"{digest}_t3.md"
    summary_rel = summary_rel_path(out_path)

    if inflight is not None and inflight_lock is not None:
        # Short-circuit 1: existing summary on disk from a prior walk.
        if out_path.exists():
            return TierOutcome(
                summary_file_rel=summary_rel,
                body_chars=out_path.stat().st_size,
                deduped=True,
                content_hash=digest,
            )

        # Short-circuit 2 / 3: claim the digest or wait for a peer.
        await inflight_lock.acquire()
        existing_event = inflight.get(digest)
        if existing_event is not None:
            inflight_lock.release()
            await existing_event.wait()
            # Peer wrote the summary; reuse it.
            if out_path.exists():
                return TierOutcome(
                    summary_file_rel=summary_rel,
                    body_chars=out_path.stat().st_size,
                    deduped=True,
                    content_hash=digest,
                )
            # Peer failed and never wrote the file — fall through and run
            # ourselves. (Don't re-claim; the failed event is already set
            # so any further peers will also fall through here.)
        else:
            event = asyncio.Event()
            inflight[digest] = event
            inflight_lock.release()
            try:
                outcome = await _do_summarize(path, source_rel, agent, out_path, summary_rel, digest)
                return outcome
            finally:
                event.set()

    # No inflight infrastructure (legacy / standalone): just run.
    return await _do_summarize(path, source_rel, agent, out_path, summary_rel, digest)


async def _do_summarize(
    path: Path,
    source_rel: str,
    agent: ChatAgent[FileSummary],
    out_path: Path,
    summary_rel: str,
    digest: str,
) -> TierOutcome:
    """The actual LLM-summary work, factored out so dedup short-circuits
    can return without duplicating the call site."""
    message = await asyncio.to_thread(build_user_message, path)
    # _run_with_retry returns the parsed FileSummary directly (ChatAgent.run()
    # already unwraps the PydanticAI RunResult). Do NOT do .output here.
    summary = await _run_with_retry(agent, message, path.name)
    body_markdown = render_markdown(summary, source_rel)
    await asyncio.to_thread(write_summary, out_path, body_markdown)
    return TierOutcome(
        summary_file_rel=summary_rel,
        body_chars=len(body_markdown),
        deduped=False,
        content_hash=digest,
    )


def run(path: Path, source_rel: str, agent: ChatAgent[FileSummary]) -> TierOutcome:
    """Sync convenience wrapper — runs the async path via asyncio.run."""
    return asyncio.run(run_async(path, source_rel, agent))
