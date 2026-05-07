"""Thinking-mode helper for chat templates.

Gemma 4 supports a thinking mode toggled by the `<|think|>` token in the
system prompt: presence enables, absence disables. For the E4B variant
specifically, disabling produces no empty thought blocks at all (cleaner
than the larger sizes).

We don't try to handle every model's thinking-token convention here —
that would mean wiring in per-model knowledge and stays brittle. Instead:

  - For the default Gemma 4 path, inject `<|think|>` into the system
    message when `thinking=True`.
  - For other models (or when we can't tell), `thinking=True` is a
    silent no-op — the kwarg passes through, the model just doesn't see
    a thinking token, and emits its normal output. This matches the
    "code stays consistent across models" goal in the plan.

When other thinking-capable model families need first-class support,
add their token convention here and switch on model-id prefix.
"""

from __future__ import annotations

# Gemma 4 thinking token — per Google's prompt-formatting docs:
# https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4
_GEMMA4_THINK_TOKEN = "<|think|>"


def is_gemma4(model_repo_or_path: str) -> bool:
    """Heuristic: does `model_repo_or_path` look like a Gemma 4 model?

    Matches `gemma-4-*` and `gemma4-*` casing variants in HF repo IDs and
    GGUF filenames. Used only to decide whether thinking-token injection
    will actually do anything; a False here means `thinking=True` becomes
    a no-op rather than an error.
    """

    s = model_repo_or_path.lower()
    return "gemma-4" in s or "gemma4" in s


def apply_thinking_to_messages(
    messages: list[dict],
    *,
    thinking: bool,
    model_repo_or_path: str,
) -> list[dict]:
    """Return a copy of `messages` with thinking-mode applied if applicable.

    For Gemma 4 + thinking=True, prepends `<|think|>` to the (first)
    system message — creating an empty system message if none exists.
    For other models, returns `messages` unchanged. Either way, the
    caller can pass the result straight to `Llama.create_chat_completion`.

    Idempotent — re-applying with `thinking=True` does not stack tokens.
    """

    if not thinking:
        return messages
    if not is_gemma4(model_repo_or_path):
        # Silent no-op for non-Gemma-4 models. The caller already passed
        # through `thinking` to us; logging here every call would be
        # noise. The cloud-side warning in `src/llm.py` covers the
        # "user clearly expected thinking and it didn't happen" case.
        return messages

    out = [dict(m) for m in messages]
    sys_idx = next((i for i, m in enumerate(out) if m.get("role") == "system"), -1)
    if sys_idx < 0:
        out.insert(0, {"role": "system", "content": _GEMMA4_THINK_TOKEN})
        return out

    content = out[sys_idx].get("content", "") or ""
    if _GEMMA4_THINK_TOKEN in content:
        return out  # already applied
    out[sys_idx]["content"] = (
        f"{_GEMMA4_THINK_TOKEN}\n{content}" if content else _GEMMA4_THINK_TOKEN
    )
    return out


def strip_thinking_from_response(text: str) -> str:
    """Remove a Gemma-4-style thought block from the model's response.

    Per the Gemma 4 spec, when thinking is on the model emits:
        <|channel|>thought\\n<reasoning here><channel|>\\n<final answer>

    This strips that prefix so callers see only the final answer. If no
    thought block is present, returns `text` unchanged. Used by callers
    that want the answer without the reasoning trace; the `/generate`
    endpoint's stream surface preserves the raw output instead.
    """

    # Look for the closing `<channel|>` (note the orientation flip vs
    # the opening `<|channel|>`). Everything before and including it is
    # the thinking block.
    closing = "<channel|>"
    idx = text.find(closing)
    if idx < 0:
        return text
    return text[idx + len(closing):].lstrip("\n")
