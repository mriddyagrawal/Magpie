"""Error-mapping tests for `src.server._user_facing_error`.

Focus: local-inference failures must tell the user the actionable thing
(switch to Cloud in Settings) instead of falling through to the generic
500. Before this mapping existed, all three llama-server exceptions hit
the default branch and every query returned "Something went wrong. Please
try again." — permanently, with no hint that the fix was a toggle.

Also pins the ordering guarantee: type matching runs BEFORE the substring
heuristics, so a filesystem path containing "rate" or "collection" can't
reroute a local-model error into the wrong message.
"""

from __future__ import annotations

import pytest

from src.server import _user_facing_error


class LlamaServerBinaryError(RuntimeError):
    """Stand-in with the same class name the real module exports.

    `_user_facing_error` dispatches on `type(exc).__name__` to avoid an
    import cycle, so a same-named local class exercises the real path
    without dragging src.inference (and torch) into the test.
    """


class LlamaServerSpawnError(RuntimeError):
    pass


class LlamaServerCrashError(RuntimeError):
    pass


def test_binary_missing_tells_user_to_switch_to_cloud():
    status, msg = _user_facing_error(
        LlamaServerBinaryError("llama-server binary not found. Tried (in order): ...")
    )
    assert status == 503
    assert "local model" in msg.lower()
    assert "cloud" in msg.lower()
    assert "settings" in msg.lower()


@pytest.mark.parametrize("exc_cls", [LlamaServerSpawnError, LlamaServerCrashError])
def test_spawn_and_crash_also_point_at_cloud(exc_cls):
    status, msg = _user_facing_error(exc_cls("subprocess died during load"))
    assert status == 503
    assert "cloud" in msg.lower()


def test_no_developer_remediation_leaks_to_the_user():
    """`just install-llama-server` is a dev instruction — stderr only."""
    status, msg = _user_facing_error(
        LlamaServerBinaryError(
            "llama-server binary not found. Tried (in order):\n"
            "  - /Users/x/Library/Application Support/Magpie/bin/llama-server\n\n"
            "Fix: run `just install-llama-server` to download the right binary."
        )
    )
    assert "just install" not in msg
    assert "llama" not in msg.lower()
    assert "binary" not in msg.lower()


def test_type_match_wins_over_substring_heuristics():
    """A path containing a heuristic trigger must not reroute the message.

    'rate' would otherwise hit the 429 branch ("Service is busy") and
    'collection' the Qdrant branch ("Search is starting up") — both wrong
    and both un-actionable for a missing local model.
    """
    for trap in ("/Users/rate-limiter/bin", "/Users/x/collection/bin", "/quota/bin"):
        status, msg = _user_facing_error(
            LlamaServerBinaryError(f"llama-server binary not found. Tried: {trap}")
        )
        assert status == 503, trap
        assert "cloud" in msg.lower(), trap
        assert "busy" not in msg.lower(), trap
        assert "starting up" not in msg.lower(), trap


def test_unrelated_errors_still_hit_their_own_branches():
    """The new branch must not shadow the existing mappings."""
    assert _user_facing_error(Exception("429 too many requests"))[0] == 503
    assert _user_facing_error(Exception("401 unauthorized"))[0] == 401
    assert _user_facing_error(FileNotFoundError("gone"))[0] == 404
    assert _user_facing_error(Exception("qdrant unreachable"))[0] == 503
    # Genuine unknowns still get the generic 500.
    assert _user_facing_error(Exception("something exotic"))[0] == 500
