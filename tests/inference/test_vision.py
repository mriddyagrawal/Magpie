"""Unit + integration tests for the local vision path.

Unit tests (always run, no subprocess, no network):
  - `_detect_image_media_type` magic-byte sniffing
  - `_attach_images_to_last_user` content-block shape
  - `LlamaServerLLM._select_profile` routing logic

Integration test (gated by `LLAMA_SERVER_VISION_INTEGRATION=1`):
  - Real `llama-server` spawn against the registered vision profile
  - Sends `tests/inference/image.png` (an LLM-evaluation diagram with
    visible text labels) and asserts the model recovers at least one of
    those labels — the load-bearing PR 2 claim.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.inference.local_llm import (
    LlamaServerLLM,
    _attach_images_to_last_user,
    _detect_image_media_type,
)
from src.inference.profiles import (
    LaunchArgs,
    ModelProfile,
    register,
)


# ---------------------------------------------------------------------------
# _detect_image_media_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "header, expected",
    [
        (b"\x89PNG\r\n\x1a\n" + b"rest", "image/png"),
        (b"\xff\xd8\xff" + b"jpeg-rest", "image/jpeg"),
        (b"GIF89a" + b"rest", "image/gif"),
        (b"GIF87a" + b"rest", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPmore", "image/webp"),
        (b"unrecognized blob", "image/png"),  # safe default
    ],
)
def test_detect_image_media_type(header, expected):
    assert _detect_image_media_type(header) == expected


# ---------------------------------------------------------------------------
# _attach_images_to_last_user
# ---------------------------------------------------------------------------

def test_attach_images_promotes_last_user_to_content_blocks():
    messages = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "what is in this image?"},
    ]
    out = _attach_images_to_last_user(messages, [b"\x89PNG\r\n\x1a\nbytes"])
    assert out[0] == messages[0]  # system left alone
    parts = out[1]["content"]
    # Two parts: text first, then one image_url block.
    assert parts[0] == {"type": "text", "text": "what is in this image?"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_attach_images_handles_multiple_images():
    """Receipt PDFs render to multiple PNG pages; all blobs need to ride
    on one user message."""
    messages = [{"role": "user", "content": "describe each page"}]
    out = _attach_images_to_last_user(
        messages,
        [b"\x89PNG\r\n\x1a\npage1", b"\xff\xd8\xffpage2"],
    )
    parts = out[0]["content"]
    assert len(parts) == 3  # text + 2 images
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_attach_images_no_user_message_returns_unchanged():
    """Defensive: if there's no user message at all (system-only request),
    don't crash — return the input as-is."""
    messages = [{"role": "system", "content": "system only"}]
    out = _attach_images_to_last_user(messages, [b"\x89PNG\r\n\x1a\n"])
    assert out == messages


def test_attach_images_does_not_mutate_input():
    messages = [{"role": "user", "content": "hi"}]
    _ = _attach_images_to_last_user(messages, [b"\x89PNG\r\n\x1a\n"])
    assert messages == [{"role": "user", "content": "hi"}]


def test_attach_images_empty_text_skips_text_block():
    """If the user message is empty (rare — but T3 ingest can pass
    just an image with no framing), we shouldn't emit an empty text part."""
    messages = [{"role": "user", "content": ""}]
    out = _attach_images_to_last_user(messages, [b"\x89PNG\r\n\x1a\n"])
    parts = out[0]["content"]
    assert len(parts) == 1
    assert parts[0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# LlamaServerLLM._select_profile (vision routing)
# ---------------------------------------------------------------------------

def test_select_profile_no_images_uses_instance_default():
    """No images → call sticks with the text profile bound at construction."""
    llm = LlamaServerLLM()
    assert llm._select_profile(None) == llm.profile_name
    assert llm._select_profile([]) == llm.profile_name


def test_select_profile_default_is_vision_so_no_swap_needed():
    """Post-2026-05 default: the singleton LLM is bound to the vision
    profile (one subprocess serves both text and image requests, mmproj
    sits idle for text-only). So _select_profile returns the same name
    whether images are present or not — no swap.

    To exercise the legacy text→vision swap path explicitly, see
    `test_select_profile_text_instance_switches_to_vision_when_images_present`
    below."""
    llm = LlamaServerLLM()
    assert llm.profile_name == "lfm25-vl-vision"
    assert llm._select_profile(None) == llm.profile_name
    assert llm._select_profile([b"\x89PNG\r\n\x1a\n"]) == llm.profile_name


def test_select_profile_text_instance_switches_to_vision_when_images_present():
    """The legacy / opt-in path: users who explicitly set
    `LLAMA_SERVER_TEXT_MODEL=lfm25-vl-text` to save the projector's
    ~946 MB. With a text-bound instance, image-bearing calls still
    route to the vision profile — incurring an LRU swap with
    MAX_LOADED_MODELS=1, hence why this isn't the default anymore."""
    llm = LlamaServerLLM(profile_name="lfm25-vl-text")
    chosen = llm._select_profile([b"\x89PNG\r\n\x1a\n"])
    assert chosen == "lfm25-vl-vision"
    assert chosen != llm.profile_name  # explicit text → vision switch


def test_select_profile_vision_instance_does_not_double_switch():
    """If the instance is already bound to a vision profile (PR 3 may
    construct a vision-bound LLM), images don't trigger a redundant
    switch — the same profile is reused."""
    register(ModelProfile(
        name="test-vision-profile",
        args=LaunchArgs(repo_id="x/y", quant="Q4_K_M"),
        has_vision=True,
    ))
    llm = LlamaServerLLM(profile_name="test-vision-profile")
    assert llm._select_profile([b"\x89PNG\r\n\x1a\n"]) == "test-vision-profile"


def test_select_profile_no_vision_registered_raises():
    """If a text-bound instance hits an image-bearing call AND no vision
    profile is registered, callers need a loud error so they can either
    install the mmproj or fall back. Constructed via the opt-in
    text profile because the default instance is now vision-bound and
    wouldn't take this code path."""
    from src.inference import llama_server_pool

    llm = LlamaServerLLM(profile_name="lfm25-vl-text")
    with patch(
        "src.inference.local_llm.default_vision_profile",
        return_value=None,
    ):
        with pytest.raises(llama_server_pool.LlamaServerSpawnError):
            llm._select_profile([b"\x89PNG\r\n\x1a\n"])


# ---------------------------------------------------------------------------
# Integration: real spawn + real image (gated)
# ---------------------------------------------------------------------------

_INTEGRATION_GATE = "LLAMA_SERVER_VISION_INTEGRATION"


@pytest.mark.skipif(
    os.environ.get(_INTEGRATION_GATE) != "1",
    reason=(
        f"set {_INTEGRATION_GATE}=1 to run the real vision-integration "
        "test (spawns llama-server + downloads the mmproj projector on "
        "first run, ~946 MB). Slow and disk-heavy; opt-in only."
    ),
)
def test_vision_recovers_visible_text_from_fixture_image():
    """End-to-end: send the LLM-evaluation diagram (`image.png`) to the
    local vision profile, expect at least one of the visible labels to
    come back. PR 2's load-bearing claim — if this fails on a clean
    machine, vision isn't actually working."""
    fixture = Path(__file__).parent / "image.png"
    assert fixture.exists(), f"missing test fixture: {fixture}"
    blob = fixture.read_bytes()

    llm = LlamaServerLLM()
    response = llm.complete_sync(
        messages=[
            {"role": "system", "content": "Describe images concisely."},
            {"role": "user", "content": "What text labels do you see?"},
        ],
        images=[blob],
        max_tokens=512,
    )
    response_lc = response.lower()
    # Any one of the diagram's section labels is a pass — small models
    # may compress / paraphrase, so we don't require all of them.
    expected_any = [
        "llm", "evaluation", "knowledge", "cognition", "hallucination",
        "creativity", "coding", "bias", "context",
    ]
    matched = [w for w in expected_any if w in response_lc]
    assert matched, (
        f"vision profile returned no recognizable text labels. "
        f"Response was:\n{response[:500]}"
    )
