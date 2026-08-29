"""Priority queue for LLM calls.

Single-slot serialization across the entire process. Whichever caller
holds the slot is the only one talking to the LLM (local llama-server
or cloud provider) at that moment. Higher priority jumps ahead of
lower priority but cannot preempt a running call — preemption requires
provider-side support (Plan #27 covers that).

## Why this exists

Local llama-server runs ONE inference at a time (single slot). When
the user asks a question while ingest is summarizing files, both want
the slot. Without a queue:
  - llama-server serves them FIFO, so the user's question waits behind
    however many ingest summaries are currently queued.
  - The user feels the bar stall; their ask is not preferred.

With this queue:
  - All LLM calls go through `slot(priority)`.
  - User asks (priority=USER) jump ahead of ingest summaries
    (priority=INGEST).
  - The currently-running summary finishes (typically 1-30s on local
    Gemma 4), then the user's ask runs next.
  - Once the user's ask is done, ingest resumes from its next file.

## API

  >>> from src.inference.llm_queue import priority_context, slot, Priority
  >>>
  >>> # At an HTTP handler entry point, set the priority for everything
  >>> # in this task tree:
  >>> async with priority_context(Priority.USER):
  ...     result = await some_pipeline_that_calls_the_llm()
  >>>
  >>> # In the LLM client (LocalAgent.run, _CloudAgent.run), wrap the
  >>> # actual call:
  >>> async with slot():
  ...     return await self._call_llm(...)

The priority flows through `contextvars`, so async tasks created inside
`priority_context` inherit it. `asyncio.to_thread` also propagates
contextvars on Python 3.11+. No need to thread `priority=` through
every intermediate function signature.

## Cancellation

If the holder of a slot is cancelled (e.g., FastAPI client disconnect,
`asyncio.CancelledError`), the slot is released cleanly via the
`async with` `__aexit__`. The next-highest-priority waiter wakes.

If a waiter is cancelled before being granted the slot, it's removed
from the queue without blocking anyone else.
"""

from __future__ import annotations

import asyncio
import contextvars
from contextlib import asynccontextmanager
from enum import IntEnum
from itertools import count


class Priority(IntEnum):
    """Higher value = served sooner. FIFO within the same priority.

    The numeric gap between USER and INGEST is wide on purpose so that
    intermediate priorities (e.g., TEST_RUN=5 for benchmark eval runs)
    can be added later without colliding."""

    USER = 10
    INGEST = 1


# Per-task priority. Set via `priority_context()` at an entry point;
# inherited by all async tasks (and asyncio.to_thread workers on
# Python 3.11+) inside the context. Default is INGEST so background
# walker tasks fall through to low-priority without any explicit
# annotation.
_current_priority: contextvars.ContextVar[int] = contextvars.ContextVar(
    "llm_priority", default=Priority.INGEST
)


class PriorityLLMQueue:
    """Single-slot work queue. One running call at a time; the next
    slot goes to the highest-priority waiter (FIFO within priority).

    Implementation: an `asyncio.PriorityQueue` plus a single worker
    task that pulls one item, signals the caller (via `ready` event),
    waits for the caller's `done` event, then pulls the next.

    The slot lives for the entire `async with slot()` block — multiple
    sequential LLM calls inside one block are atomic from the queue's
    perspective. (E.g., a `/query` ask that does rewrite + answer
    holds the slot for both calls.)
    """

    def __init__(self) -> None:
        # Queue items: (-priority, monotonic_id, ready_event, done_event).
        # Negate priority because asyncio.PriorityQueue is a min-heap
        # but we want higher priority served first.
        self._queue: asyncio.PriorityQueue[
            tuple[int, int, asyncio.Event, asyncio.Event]
        ] = asyncio.PriorityQueue()
        self._counter = count()
        self._worker_task: asyncio.Task | None = None
        self._worker_lock = asyncio.Lock()

    async def _ensure_worker(self) -> None:
        """Lazily start the worker task on the first acquire. Lazy
        because some test paths import this module without an event
        loop running."""
        async with self._worker_lock:
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = asyncio.create_task(
                    self._worker(), name="llm-queue-worker"
                )

    async def _worker(self) -> None:
        """Forever loop: pull next item, signal it, wait for it to
        finish. Exceptions in callers are isolated — they set their
        `done` in their own `finally` regardless of how the body
        exited, so the worker always proceeds."""
        while True:
            _neg_pri, _id, ready, done = await self._queue.get()
            ready.set()
            await done.wait()
            self._queue.task_done()

    @asynccontextmanager
    async def slot(self, priority: int):
        """Acquire the LLM slot. Higher priority is served sooner.

        Held for the duration of the `async with` block. On exit
        (success, exception, or cancellation), the slot is released
        and the next waiter wakes."""
        await self._ensure_worker()
        ready = asyncio.Event()
        done = asyncio.Event()
        await self._queue.put((-int(priority), next(self._counter), ready, done))
        try:
            # Wait for our turn. If we get cancelled while waiting,
            # the `except` below sets `done` so the worker can move on
            # when it eventually pulls our (now-orphaned) item.
            await ready.wait()
            try:
                yield
            finally:
                done.set()
        except BaseException:
            # Either cancelled before we got the slot, or the body
            # raised. Setting done unblocks the worker so the queue
            # keeps moving. If `done.set()` already fired in the inner
            # finally, this is a no-op (Event.set is idempotent).
            done.set()
            raise


# Module-level singleton. All `slot()` calls share the same queue.
_queue = PriorityLLMQueue()


@asynccontextmanager
async def slot(priority: int | None = None):
    """Acquire an LLM slot. Default priority comes from the contextvar
    set by `priority_context()`; pass an explicit `priority` to
    override.

    Use this in the LLM client layer (LocalAgent.run, _CloudAgent.run)
    to wrap the actual provider call.
    """
    if priority is None:
        priority = _current_priority.get()
    async with _queue.slot(priority):
        yield


@asynccontextmanager
async def priority_context(priority: int):
    """Set the LLM call priority for everything in this `async with`.
    Propagates through async tasks and `asyncio.to_thread`.

    Use this at HTTP handler entry points (e.g., the /query handler)
    to mark a request's LLM calls as high priority. Background
    walker tasks don't need to call this — the contextvar default
    is `Priority.INGEST` already.
    """
    token = _current_priority.set(int(priority))
    try:
        yield
    finally:
        _current_priority.reset(token)
