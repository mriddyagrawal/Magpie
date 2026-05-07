"""Smoke test for the local llama-cpp-python backend.

Skipped unless `LLM_PROVIDER=local` is set in the environment. Cross-platform
since 2026-05 (was Apple-Silicon-only when this used mlx-vlm; see
Plans/Local LLM Plan.md). The filename is kept for git-history continuity
even though MLX is no longer the underlying engine.

Exercises the full path: load the model, summarize a text file and (if
available) an image, assert the outputs parse into valid Pydantic objects.
Real inference — no mocks. Expect ~30s first run (model load) + a few seconds
per file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.content import IMAGE_EXTS

pytestmark = pytest.mark.skipif(
    os.environ.get("LLM_PROVIDER", "").lower() != "local",
    reason="local-backend smoke test requires LLM_PROVIDER=local.",
)


REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_CONTENT = REPO_ROOT / "Test Content"


def _pick_text_file() -> Path | None:
    for candidate in TEST_CONTENT.rglob("*.csv"):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    for candidate in TEST_CONTENT.rglob("*.pdf"):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _pick_image_file() -> Path | None:
    for candidate in TEST_CONTENT.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTS:
            return candidate
    return None


@pytest.mark.asyncio
async def test_mlx_summarize_text():
    """Summarize a small text/CSV/PDF file; expect a valid FileSummary."""
    from src.stage1.summarize import (
        FileSummary,
        build_agent,
        build_user_message,
    )

    path = _pick_text_file()
    if path is None:
        pytest.skip("no text/csv/pdf under Test Content/ to summarize")

    agent = build_agent()
    message = build_user_message(path)
    result = await agent.run(message)

    assert isinstance(result, FileSummary)
    assert result.title, "FileSummary.title must be non-empty"
    assert result.content_type in {
        "image", "pdf", "docx", "xlsx", "text", "code", "markdown", "other",
    }


@pytest.mark.asyncio
async def test_mlx_summarize_image():
    """Summarize an image file (if any exist under Test Content/)."""
    from src.stage1.summarize import (
        FileSummary,
        build_agent,
        build_user_message,
    )

    path = _pick_image_file()
    if path is None:
        pytest.skip("no image files under Test Content/ to summarize")

    agent = build_agent()
    message = build_user_message(path)
    result = await agent.run(message)

    assert isinstance(result, FileSummary)
    assert result.title, "FileSummary.title must be non-empty for image"


@pytest.mark.asyncio
async def test_mlx_answer_from_file():
    """Ground-truth answering: hand the model a single file and ask about it."""
    from src.answer import Answer, answer_question, build_answer_agent

    path = _pick_text_file()
    if path is None:
        pytest.skip("no text/csv/pdf under Test Content/ to answer from")

    agent = build_answer_agent()
    ans = await answer_question(
        agent,
        "What kind of file is this?",
        [str(path.relative_to(REPO_ROOT))],
    )

    assert isinstance(ans, Answer)
    assert ans.answer, "Answer.answer must be non-empty"
