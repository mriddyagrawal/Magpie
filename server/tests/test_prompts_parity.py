"""Guard against prompt drift between desktop copies and server source-of-truth.

While we're in the Phase 2.5 transition (server prompts created but desktop
hasn't yet switched to calling /llm/* over HTTP), the prompts physically
exist in both locations. This test asserts they're byte-identical so an
edit on one side without the other is caught at CI time, not at
"why did the cloud answer feel different from the local one" time.

After Phase 2.5 step 5 lands and the desktop copies are deleted, this
test gets deleted too — single source of truth, no parity to enforce.

Why text-parse instead of import: the desktop modules (src/answer.py etc.)
import torch / qdrant_client / pydantic_ai which the server venv
deliberately doesn't have. So we read the source files as text and
extract the prompt string with ast.parse — same correctness, no heavy
imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

from magpie_server import prompts

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _extract_str_constant(file_path: Path, var_name: str) -> str:
    """Parse `file_path` and return the value of the top-level string assignment
    `var_name = "..."`. Handles both single-token and concatenated/parenthesized
    string literals. Raises if the variable isn't found or isn't a string.
    """
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if var_name not in targets:
            continue
        try:
            return ast.literal_eval(node.value)
        except (ValueError, SyntaxError) as e:
            raise AssertionError(
                f"{var_name} in {file_path} is not a literal string: {e}"
            ) from e
    raise AssertionError(f"{var_name} not found at top level of {file_path}")


def test_answer_prompt_matches():
    desktop = _extract_str_constant(REPO_ROOT / "src" / "answer.py", "SYSTEM_PROMPT")
    assert prompts.ANSWER_PROMPT == desktop, (
        "Drift: server prompts.ANSWER_PROMPT differs from src/answer.py:SYSTEM_PROMPT. "
        "Edit the server copy first, then mirror to the desktop until Phase 2.5 step 5."
    )


def test_rewrite_prompt_matches():
    desktop = _extract_str_constant(
        REPO_ROOT / "src" / "stage2" / "search.py", "REWRITE_SYSTEM_PROMPT"
    )
    assert prompts.REWRITE_PROMPT == desktop, (
        "Drift: server prompts.REWRITE_PROMPT differs from "
        "src/stage2/search.py:REWRITE_SYSTEM_PROMPT."
    )


def test_summarize_prompt_matches():
    desktop = _extract_str_constant(
        REPO_ROOT / "src" / "stage1" / "summarize.py", "SYSTEM_PROMPT"
    )
    assert prompts.SUMMARIZE_PROMPT == desktop, (
        "Drift: server prompts.SUMMARIZE_PROMPT differs from "
        "src/stage1/summarize.py:SYSTEM_PROMPT."
    )


def test_summarize_prompt_local_matches():
    desktop = _extract_str_constant(
        REPO_ROOT / "src" / "stage1" / "summarize.py", "LOCAL_SYSTEM_PROMPT"
    )
    assert prompts.SUMMARIZE_PROMPT_LOCAL == desktop, (
        "Drift: server prompts.SUMMARIZE_PROMPT_LOCAL differs from "
        "src/stage1/summarize.py:LOCAL_SYSTEM_PROMPT."
    )
