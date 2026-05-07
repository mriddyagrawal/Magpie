"""Smoke test for the local llama-server backend.

Skipped unless `LLM_PROVIDER=local` is set in the environment. Cross-platform
since 2026-05 (was Apple-Silicon-only when this used mlx-vlm; see
Plans/Local LLM Plan.md). The filename is kept for git-history continuity
even though neither MLX nor llama-cpp-python is the underlying engine —
the actual backend is `llama-server` (HTTP) plus the Gemma 4 E4B GGUF
and BF16 mmproj projector for vision.

Exercises the full path: load the model, summarize a text file and (if
available) an image, ask a question that requires reading an image —
assert the outputs parse into valid Pydantic objects AND (for image
tests) contain non-trivial image-derived content. Real inference,
no mocks. Expect ~30s first run (model + mmproj load) + a few seconds
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
    """Prefer the committed fixture (deterministic content for assertions);
    fall back to any image under Test Content/ for users who run the smoke
    test without that fixture available."""
    fixture = REPO_ROOT / "tests" / "inference" / "image.png"
    if fixture.is_file():
        return fixture
    for candidate in TEST_CONTENT.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTS:
            return candidate
    return None


# Visible text labels in `tests/inference/image.png` (an LLM-evaluation
# diagram). The image-bearing tests assert the model recovers at least
# one — the non-trivial image-derived content gate. "fake" is an inner
# quadrant label the BF16 mmproj reliably identifies (verified against
# b9049 + Gemma 4 E4B, 2026-05-07).
_FIXTURE_IMAGE_LABELS = (
    "llm", "evaluation", "knowledge", "cognition", "hallucination",
    "creativity", "coding", "bias", "context", "lightbulb", "fake",
)


def _matches_fixture_labels(text: str) -> list[str]:
    lower = text.lower()
    return [w for w in _FIXTURE_IMAGE_LABELS if w in lower]


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
    """Summarize an image file end-to-end through the vision profile.

    When the committed fixture is present, this is the load-bearing test
    that PR 3's wiring actually delivers vision to T3 ingest: the
    FileSummary's title or summary must mention something the image
    visibly contains. A non-trivial assertion (vs. just "title is
    non-empty") catches regressions where the image gets dropped to
    text-only path silently.
    """
    from src.stage1.summarize import (
        FileSummary,
        build_agent,
        build_user_message,
    )

    path = _pick_image_file()
    if path is None:
        pytest.skip("no image files (no fixture, no Test Content/ images)")

    agent = build_agent()
    message = build_user_message(path)
    result = await agent.run(message)

    assert isinstance(result, FileSummary)
    assert result.title, "FileSummary.title must be non-empty for image"

    # If the user pointed us at the committed fixture, demand image-derived
    # content. Other images skip the strong assertion (we don't know what
    # they contain) but still validate the structural path above.
    is_fixture = path == REPO_ROOT / "tests" / "inference" / "image.png"
    if is_fixture:
        haystack = " ".join([result.title, result.summary or ""])
        matched = _matches_fixture_labels(haystack)
        assert matched, (
            "vision profile produced no image-derived content for the "
            f"committed fixture. FileSummary was:\ntitle={result.title!r}\n"
            f"summary={result.summary!r}"
        )


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


@pytest.mark.asyncio
async def test_mlx_answer_from_image():
    """The PR 3 gate: an image-bearing answer-step call must route bytes
    to the vision profile and return image-derived content.

    Skipped if the committed fixture isn't present — without a known
    image we can't make a non-trivial assertion about the answer."""
    from src.answer import Answer, answer_question, build_answer_agent

    fixture = REPO_ROOT / "tests" / "inference" / "image.png"
    if not fixture.is_file():
        pytest.skip("committed image fixture missing; can't verify content")

    agent = build_answer_agent()
    # Phrase the prompt so the model returns prose, not a list. Gemma 4
    # otherwise emits a JSON list when asked "list every X" and the
    # Answer schema (answer: str) trips structured-output parsing —
    # that's a schema concern, not a vision one.
    ans = await answer_question(
        agent,
        "Describe what you see in this image, including any visible text.",
        [str(fixture)],
    )

    assert isinstance(ans, Answer)
    assert ans.answer, "Answer.answer must be non-empty"
    matched = _matches_fixture_labels(ans.answer)
    assert matched, (
        "answer-step vision is not delivering image content to the model. "
        f"Answer was:\n{ans.answer[:500]}"
    )
