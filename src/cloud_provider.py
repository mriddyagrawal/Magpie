"""Magpie Cloud provider — desktop-side client that calls the cloud server.

When `LLM_PROVIDER=magpie-cloud` is set, every LLM call (rewrite / answer
/ summarize) goes through *your* server instead of OpenRouter directly.
The user's app sees only an invite code; prompts, API keys, model
selection all live server-side.

This module exposes three agent classes that match the `ChatAgent`
protocol from `src.llm`. They take the same `message` lists the
existing call sites build and translate them into the typed JSON shapes
that `server/magpie_server/llm_routes.py` expects.

Vision content (binary PDF page images) is NOT supported in cloud mode
for beta — text-only path. Files routed to vision tiers fall back to
local mode if configured.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel

# Schema imports are deferred to where they're used to avoid a circular
# import (`src.llm` imports this module to register the provider, and
# the schemas live in `src.answer`, `src.stage1.summarize`,
# `src.stage2.search`).


T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class CloudClient:
    """Thin httpx wrapper. Reads URL + invite code from env vars.

    `MAGPIE_CLOUD_URL` defaults to localhost:8000 for local dev; production
    builds set it to your fly.io URL via the env file shipped with the app.
    `MAGPIE_INVITE_CODE` is what the user pasted into the settings UI.
    """

    DEFAULT_URL = "http://127.0.0.1:8000"
    REQUEST_TIMEOUT_S = 60.0   # generous — LLM round-trips can be slow

    def __init__(
        self,
        base_url: str | None = None,
        invite_code: str | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("MAGPIE_CLOUD_URL", "").strip()
            or self.DEFAULT_URL
        ).rstrip("/")
        self.invite_code = (
            invite_code or os.environ.get("MAGPIE_INVITE_CODE", "").strip()
        )

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        # Localhost dev mode lets the server run with no codes set; in that
        # case the desktop omitting the header is also fine (server returns
        # `anon-localhost` from /whoami). For production, the code is
        # required — the server will 401 without it.
        if self.invite_code:
            h["Authorization"] = f"Bearer {self.invite_code}"
        return h

    async def post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT_S) as client:
            try:
                resp = await client.post(url, json=json, headers=self._headers())
            except httpx.RequestError as e:
                raise RuntimeError(f"could not reach Magpie Cloud at {url}: {e}") from e
        if resp.status_code >= 400:
            # Surface the server's `detail` field if present, else fall back.
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:  # pylint: disable=broad-except
                detail = resp.text
            raise RuntimeError(f"Magpie Cloud {resp.status_code}: {detail}")
        return resp.json()


# ---------------------------------------------------------------------------
# Message-format adapters: convert the existing client-side `message` lists
# into the typed JSON shapes the server expects.
# ---------------------------------------------------------------------------

def _strings_only(message: list) -> list[str]:
    """Filter a desktop-side message list down to its text parts.

    The desktop's `build_content_blocks` may emit text strings interleaved
    with binary `BinaryContent` (for vision PDFs). Cloud mode is text-only
    for beta — drop the binaries, keep the text.
    """
    out: list[str] = []
    for m in message:
        if isinstance(m, str):
            out.append(m)
        # Anything not a string (BinaryContent etc.) gets silently skipped.
    return out


def _join_text(message: list) -> str:
    """Concatenate the text-only parts into a single string."""
    return "\n".join(_strings_only(message)).strip()


_FILE_HEADER = re.compile(r"^---\s*File\s+\d+:\s*(.+?)\s*---\s*$")


def _parse_answer_message(message: list) -> tuple[str, list[dict]]:
    """Split the answer-call message into (question, snippets[]).

    The desktop builds messages like:
        ["Current date and time: ...",
         "Question: <user question>",
         "--- File 1: /path/to/foo.pdf ---",
         "<file content>",
         "--- File 2: /path/to/bar.docx ---",
         "<file content>",
         ...]

    We slice it on the `--- File N: <path> ---` markers to recover the
    structured form the cloud expects.
    """
    parts = _strings_only(message)
    question = ""
    snippets: list[dict] = []

    current_path: str | None = None
    current_buf: list[str] = []

    def flush():
        if current_path is not None:
            snippets.append({"path": current_path, "text": "\n".join(current_buf).strip()})

    for part in parts:
        for line in part.splitlines():
            m = _FILE_HEADER.match(line.strip())
            if m:
                flush()
                current_path = m.group(1)
                current_buf = []
                continue
            if current_path is not None:
                current_buf.append(line)
            elif line.startswith("Question:"):
                question = line[len("Question:"):].strip()

    flush()
    # If we never saw a "Question:" prefix, fall back to using the first
    # non-header text block as the question (defensive).
    if not question and parts:
        for p in parts:
            stripped = p.strip()
            if stripped and not _FILE_HEADER.match(stripped):
                question = stripped.splitlines()[0]
                break

    return question, snippets


def _parse_summarize_message(message: list) -> tuple[str, str]:
    """Split the summarize-call message into (filename, file_text).

    Desktop builds: ["Filename: <name>\nSummarize this file.",  "<file text>"]
    """
    parts = _strings_only(message)
    if not parts:
        return "", ""

    filename = ""
    text_parts: list[str] = []
    for i, p in enumerate(parts):
        if i == 0:
            for line in p.splitlines():
                if line.lower().startswith("filename:"):
                    filename = line.split(":", 1)[1].strip()
                    break
        else:
            text_parts.append(p)

    return filename, "\n".join(text_parts).strip()


# ---------------------------------------------------------------------------
# ChatAgent-shaped wrappers — drop-in replacement for the OpenAI-compatible
# agents that `src.llm.build_agent` would otherwise return.
# ---------------------------------------------------------------------------

class _CloudAgentBase(Generic[T]):
    """Common machinery: the cloud client and the output Pydantic class.

    `thinking=True` is accepted for protocol compatibility with the local
    backend but is currently a no-op (warns once via `src.llm`). When the
    Magpie Cloud server adds a reasoning surface to its `/llm/*` endpoints,
    we forward the flag in the POST body instead of dropping it. See
    Plans/Future Plans.md #16.
    """

    def __init__(self, output_type: type[T]) -> None:
        self._output_type = output_type
        self._client = CloudClient()

    def run_sync(self, message: list, *, thinking: bool = False) -> T:
        return asyncio.get_event_loop().run_until_complete(
            self.run(message, thinking=thinking)
        )

    async def run(self, message: list, *, thinking: bool = False) -> T:
        raise NotImplementedError


def _maybe_warn_thinking(thinking: bool) -> None:
    """Cloud paths don't yet honor `thinking`; warn once via the shared
    helper in src.llm so the magpie-cloud / openrouter / moonshot warnings
    all share a single throttle."""
    if not thinking:
        return
    from src.llm import _warn_cloud_thinking_unsupported
    _warn_cloud_thinking_unsupported("magpie-cloud")


class CloudRewriteAgent(_CloudAgentBase[T]):
    async def run(self, message: list, *, thinking: bool = False) -> T:
        _maybe_warn_thinking(thinking)
        # The rewrite call is text-only and the message is just the question
        # (plus possibly history lines). For simplicity we forward the joined
        # text as `question`; history threading on cloud-side TBD.
        question = _join_text(message)
        body = await self._client.post("/llm/rewrite", {"question": question})
        # Build the desktop's SearchQuery-shaped object from the response.
        return self._output_type(query=body["query"], keywords=body["keywords"])  # type: ignore[call-arg]


class CloudAnswerAgent(_CloudAgentBase[T]):
    async def run(self, message: list, *, thinking: bool = False) -> T:
        _maybe_warn_thinking(thinking)
        question, snippets = _parse_answer_message(message)
        body = await self._client.post(
            "/llm/answer",
            {"question": question, "snippets": snippets},
        )
        return self._output_type(  # type: ignore[call-arg]
            answer=body["answer"],
            sources_used=body["sources_used"],
        )


class CloudSummarizeAgent(_CloudAgentBase[T]):
    async def run(self, message: list, *, thinking: bool = False) -> T:
        _maybe_warn_thinking(thinking)
        filename, text = _parse_summarize_message(message)
        body = await self._client.post(
            "/llm/summarize",
            {"filename": filename, "text": text},
        )
        # The /llm/summarize endpoint nests the FileSummary under "summary".
        return self._output_type(**body["summary"])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Dispatch — picks the right cloud agent based on the desktop's output_type.
# ---------------------------------------------------------------------------

def build_cloud_agent(output_type: type[T]) -> _CloudAgentBase[T]:
    """Pick the right cloud agent for the requested output schema.

    Mapping:
        SearchQuery      -> /llm/rewrite
        Answer           -> /llm/answer
        FileSummary      -> /llm/summarize

    Identification by class NAME (not isinstance) so server-side and
    desktop-side classes don't have to be the literal same import path —
    they just have to share the structural shape.
    """
    name = output_type.__name__
    if name == "SearchQuery":
        return CloudRewriteAgent(output_type)
    if name == "Answer":
        return CloudAnswerAgent(output_type)
    if name == "FileSummary":
        return CloudSummarizeAgent(output_type)
    raise RuntimeError(
        f"magpie-cloud provider has no endpoint for output_type={name!r}; "
        f"valid: SearchQuery, Answer, FileSummary"
    )
