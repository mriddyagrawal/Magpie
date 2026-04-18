"""Stage 4: answer a question from a set of files via Moonshot Kimi + PydanticAI.

Input contract (from stage 3):
    - question: the natural-language user question
    - file_paths: list of file paths retrieved from Qdrant (typically top-k = 5)

Output contract:
    Answer(answer=<str>, sources_used=<list[str] subset of input paths>)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.content import SummarizeError, build_content_blocks
from src.llm import ChatAgent, build_agent


REPO_ROOT = Path(__file__).resolve().parent.parent
ANSWER_MAX_CHARS_PER_FILE = 25_000
ANSWER_MAX_PDF_PAGES = 5


class Answer(BaseModel):
    answer: str = Field(
        description=(
            "Natural-language answer grounded strictly in the provided files. "
            "If the files do not contain the information, say so explicitly."
        )
    )
    sources_used: list[str] = Field(
        description=(
            "Subset of the input file paths the answer actually depends on. "
            "Copied verbatim from the '--- File N: <path> ---' headers. "
            "Do not include files you consulted but did not actually use."
        )
    )


SYSTEM_PROMPT = (
    "You are a file-grounded question-answering assistant. "
    "Answer the user's question using ONLY the files provided in the message. "
    "If the files do not contain the information needed to answer, say so explicitly — "
    "do not invent facts. "
    "Be concise. Default to the shortest answer that directly addresses the "
    "question — one sentence or a brief list is usually enough. Do not restate "
    "the question, add background context, or enumerate details the user didn't "
    "ask for. If the user wants more detail, they will ask a follow-up. "
    "Exception: if the question is explicitly comparative, aggregative, or asks "
    "for a list ('which courses...', 'what are all...'), return the full list. "
    "If prior conversation turns are included, use them to interpret the user's "
    "current question (resolve references like 'that', 'it', 'the same course'), "
    "but still ground your answer in the files — do not recycle a prior answer "
    "without checking the current files. "
    "In `sources_used`, include only the exact file paths (copied verbatim from the "
    "'--- File N: <path> ---' headers) that your answer actually depends on. "
    "Do not list files you consulted but did not actually use. "
    "Output RAW JSON only — do not wrap the response in markdown code fences "
    "like ```json, and do not include any prose before or after the JSON object."
)


_ANSWER_FALLBACK = Answer(
    answer="(model output could not be parsed into Answer)",
    sources_used=[],
)


def build_answer_agent() -> ChatAgent[Answer]:
    return build_agent(SYSTEM_PROMPT, Answer, _ANSWER_FALLBACK)


def _strip_fragment(p: str) -> str:
    """Remove any '#...' fragment (e.g. '#scene:00:20') from a source path.

    Stage 3 uses fragments on `.alt` source paths to give per-scene Qdrant
    points unique IDs. The answer step only needs the underlying file.
    """
    return p.split("#", 1)[0]


def _resolve(p: str | Path) -> Path:
    path = Path(_strip_fragment(str(p)))
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _display_path(abs_path: Path) -> str:
    try:
        return str(abs_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(abs_path.resolve())


async def answer_question(
    agent: ChatAgent[Answer],
    question: str,
    file_paths: Sequence[str | Path],
    history: list[tuple[str, str]] | None = None,
) -> Answer:
    """Given a question and a list of file paths, return a grounded Answer.

    Missing or unreadable files are skipped with a stderr warning. If *every*
    path is unusable, raises SummarizeError.

    If `history` is provided (list of (question, answer) tuples from prior
    turns), it's prepended to the message so the model can resolve references
    like 'it' or 'the same course'. The model is still instructed to ground
    its answer in the current files, not recycle prior answers.
    """
    if not question.strip():
        raise ValueError("question is empty")
    if not file_paths:
        raise SummarizeError("no file paths provided")

    # Resolve + filter. Dedup on the post-fragment-strip path so multiple
    # retrieval hits at different `#scene:...` fragments of the same .alt
    # collapse to a single file read.
    valid: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for p in file_paths:
        abs_path = _resolve(p)
        key = str(abs_path)
        if key in seen:
            continue
        seen.add(key)
        if not abs_path.is_file():
            print(f"  warn: skipping missing file: {p}", file=sys.stderr)
            continue
        valid.append((_display_path(abs_path), abs_path))

    if not valid:
        raise SummarizeError("all provided file paths were missing or invalid")

    # Build blocks for every valid file off the event loop (pypdf, pymupdf, etc. are blocking)
    per_file_blocks: list[tuple[str, list]] = []
    for display, abs_path in valid:
        try:
            blocks = await asyncio.to_thread(
                build_content_blocks,
                abs_path,
                max_chars=ANSWER_MAX_CHARS_PER_FILE,
                max_pdf_pages=ANSWER_MAX_PDF_PAGES,
            )
        except SummarizeError as e:
            print(f"  warn: skipping {display}: {e}", file=sys.stderr)
            continue
        per_file_blocks.append((display, blocks))

    if not per_file_blocks:
        raise SummarizeError("no files could be read (all were unsupported or empty)")

    # Assemble the chat message
    intro_parts: list[str] = []
    if history:
        intro_parts.append("Previous conversation turns:")
        for i, (q, a) in enumerate(history, 1):
            intro_parts.append(f"[Turn {i}] Q: {q}")
            intro_parts.append(f"[Turn {i}] A: {a}")
        intro_parts.append("")
    intro_parts.append(f"Current question: {question}")
    intro_parts.append("")
    intro_parts.append(
        "Answer the current question strictly from the files below. "
        "Cite the exact file paths (from the '--- File N: <path> ---' headers) "
        "in `sources_used`."
    )
    message: list = ["\n".join(intro_parts)]
    for i, (display, blocks) in enumerate(per_file_blocks, 1):
        message.append(f"\n--- File {i}: {display} ---")
        message.extend(blocks)

    ans = await agent.run(message)

    # Defensive: drop any path the model invented that wasn't in our input
    input_paths = {display for display, _ in per_file_blocks}
    filtered = [s for s in ans.sources_used if s in input_paths]
    if len(filtered) != len(ans.sources_used):
        dropped = [s for s in ans.sources_used if s not in input_paths]
        print(f"  warn: dropped hallucinated source paths: {dropped}", file=sys.stderr)
    ans.sources_used = filtered
    return ans


def answer_question_sync(
    agent: ChatAgent[Answer],
    question: str,
    file_paths: Sequence[str | Path],
) -> Answer:
    return asyncio.run(answer_question(agent, question, file_paths))


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Answer a question given a list of file paths (stage 4)."
    )
    parser.add_argument("question", help="The natural-language question.")
    parser.add_argument("paths", nargs="+", help="File paths (typically stage-3 top-k output).")
    args = parser.parse_args()

    agent = build_answer_agent()
    try:
        ans = answer_question_sync(agent, args.question, args.paths)
    except SummarizeError as e:
        sys.exit(f"error: {e}")
    print(json.dumps(ans.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
