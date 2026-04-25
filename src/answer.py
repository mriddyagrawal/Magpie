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
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.content import SummarizeError, build_content_blocks
from src.ingest.ripgrep import format_hits_block, search_file as ripgrep_search
from src.llm import ChatAgent, build_agent
from src.manifest import Manifest


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
    "\n\n"
    "STRICT GROUNDING RULES — these are inviolable:\n"
    "1. EVERY substantive claim in your answer must be directly supported by "
    "text actually visible in the file content blocks. Do NOT add information "
    "from your training data that isn't explicitly present in the files — even "
    "if you know it to be true and even if it would round out the answer. "
    "Helpful expansion is harmful here; the user is checking what THEIR FILES "
    "say, not what the world knows.\n"
    "2. If the files cover a topic narrowly (e.g., Dirac delta in an "
    "electrodynamics text), do NOT expand the answer to cover adjacent areas "
    "(applications in other fields, historical context, modern variants, "
    "related concepts) unless those areas are also explicitly discussed in "
    "the files. Stay in the lane the files cover.\n"
    "3. EVERY page citation must point to a page whose content you actually "
    "used. Do not attach a citation to a claim you generated from general "
    "knowledge. Do not include 'decorative' citations (pages that happen to "
    "be in the file content but didn't contribute the cited fact).\n"
    "4. EVERY file used in your answer must appear in `sources_used`. If "
    "different bullets / sentences pull content from different files, list "
    "ALL contributing files. Do not attribute content from file A to file B. "
    "If you can't tell which file a piece of information came from, omit it.\n"
    "5. When in doubt between completeness and faithfulness, choose "
    "faithfulness. A short, accurate answer that cites the right files beats "
    "a comprehensive-looking answer that mixes sources or extrapolates.\n"
    "\n"
    "IMPORTANT — terminology and unit mapping. The absence of the user's exact "
    "phrase does NOT mean the file lacks the information. Before concluding that "
    "a file does not cover a topic, check whether the file discusses the same "
    "concept under a different name, a synonym, an abbreviation, or a different "
    "unit. When it does, answer from what the file states and briefly note the "
    "mapping. Concrete examples you should handle this way: "
    "(1) 'beats per second' → the file's 'BPM / beats per minute / tempo' — "
    "answer with the tempo/BPM definition and note that beats-per-second = BPM ÷ 60; "
    "(2) 'prereqs' → the file's 'prerequisites'; "
    "(3) 'bank fees' → the file's 'service charges'; "
    "(4) 'how long is the class' → the file's 'duration' or 'credit hours'. "
    "This is grounded answering, not invention — you are reporting what the file "
    "says and identifying it as the equivalent concept. Do NOT bridge genuinely "
    "distinct concepts (e.g. don't answer a question about pitch using a file "
    "that only discusses rhythm). "
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
    "In `sources_used`, include only the file paths your answer actually "
    "depends on. The path itself must be copied verbatim from the "
    "'--- File N: <path> ---' headers — but you MAY append page references "
    "after the path using this exact format: "
    "`<path>  [book pp. 254-258 / PDF pp. 269-273]`. Use this format only "
    "when the file has page anchors (you'll see '## PDF page N (book p. X)' "
    "headers in the file content). Do NOT invent page numbers; cite only the "
    "anchors that actually appear in what you read. "
    "\n\n"
    "Mathematical notation: PREFER Unicode math symbols — they render "
    "cleanly in plain-text terminals (which is what most users see). "
    "Use ∂ ∫ ∑ ∏ √ ⇒ ⇔ ≈ ≠ ≤ ≥ ∇ × · ± ∞ α β γ θ φ ψ ω π Δ where they "
    "express the equation. Use Unicode subscripts/superscripts where useful "
    "(x², q̇, m₁). Only fall back to LaTeX `$...$` (inline) or `$$...$$` "
    "(display) for structures Unicode can't express clearly: fractions like "
    "$\\frac{a}{b}$, multi-line sums, integrals with limits. "
    "Source PDFs often have OCR-garbled math (e.g. 'd/dt' shown as 'dldt', "
    "'∂' shown as 'a', subscripts split across spaces, em-dashes for minus "
    "signs). Use your knowledge of standard physics/math notation to "
    "reconstruct the correct expression — never copy garbled OCR verbatim. "
    "If you can't reliably reconstruct, describe the equation in plain "
    "language instead. "
    "\n\n"
    "Page numbers belong in `sources_used` ONLY. Do NOT pepper the answer "
    "prose with `[book p. N / PDF p. M]` annotations — they clutter the "
    "reading experience and the user already sees the consolidated page "
    "list at the bottom. The only exception: if the user explicitly asked "
    "'where' or 'on what page', you may give a single short citation in "
    "the prose using the form 'page N' (book page; the PDF page is in "
    "sources_used). Otherwise keep the prose clean. "
    "\n\n"
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
    search_keywords: list[str] | None = None,
) -> Answer:
    """Given a question and a list of file paths, return a grounded Answer.

    Missing or unreadable files are skipped with a stderr warning. If *every*
    path is unusable, raises SummarizeError.

    If `history` is provided (list of (question, answer) tuples from prior
    turns), it's prepended to the message so the model can resolve references
    like 'it' or 'the same course'. The model is still instructed to ground
    its answer in the current files, not recycle prior answers.

    If `search_keywords` is provided (the SearchQuery's keywords list from
    the rewriter), long PDFs are lazy-chunked: rather than send the LLM the
    first N chars (cover + preface for a 700-page book), we pick the pages
    matching those keywords. Without keywords, behavior is unchanged.
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

    # Manifest lets us see which retrieved files were routed to T0 (not
    # fully embedded). For those, ripgrep pulls the most likely relevant
    # lines so the LLM gets real content even though we skipped exhaustive
    # indexing at ingest.
    try:
        manifest = await asyncio.to_thread(Manifest)
    except Exception:  # pylint: disable=broad-except
        manifest = None

    def _is_t0(display: str) -> bool:
        if manifest is None:
            return False
        entry = manifest.get(display)
        return entry is not None and "T0" in (entry.routes or [])

    def _summary_supplement(display: str) -> str | None:
        """Return the T3 LLM summary text for `display`, if any.

        Used as supplementary context alongside the raw file. The summary is
        what keeps scanned PDFs / huge textbooks answerable: pypdf often
        extracts near-nothing from scans, and the scanned-fallback only
        renders the first 5 pages — but the T3 summary has the full
        chapter list. Labeled explicitly so the model knows it's a distilled
        overview, not raw file content.
        """
        if manifest is None:
            return None
        entry = manifest.get(display)
        if entry is None or not entry.summary_file:
            return None
        summary_path = REPO_ROOT / entry.summary_file
        try:
            body = summary_path.read_text(encoding="utf-8")
        except OSError:
            return None
        body = body.strip()
        if not body:
            return None
        return (
            "Content type: llm-summary (distilled overview of the file — use "
            "alongside the raw content below, especially when the raw "
            "extraction is thin or the file is large)\n\n---\n"
            f"{body}"
        )

    # Build blocks for every valid file off the event loop (pypdf, pymupdf, etc. are blocking)
    per_file_blocks: list[tuple[str, list]] = []
    for display, abs_path in valid:
        try:
            if _is_t0(display):
                # T0 files: skip the whole-file read and lean on ripgrep.
                hits = await asyncio.to_thread(ripgrep_search, abs_path, question)
                hits_text = format_hits_block(abs_path, hits)
                if hits_text:
                    blocks = [
                        f"Content type: t0-ripgrep (full file not embedded; "
                        f"below are the lines matching your question)\n\n---\n{hits_text}"
                    ]
                else:
                    blocks = [
                        f"Content type: t0-ripgrep\n\n---\n"
                        f"(no matching lines in {abs_path.name}; file not embedded at ingest)"
                    ]
            else:
                blocks = await asyncio.to_thread(
                    build_content_blocks,
                    abs_path,
                    max_chars=ANSWER_MAX_CHARS_PER_FILE,
                    max_pdf_pages=ANSWER_MAX_PDF_PAGES,
                    search_keywords=search_keywords,
                )
        except SummarizeError as e:
            print(f"  warn: skipping {display}: {e}", file=sys.stderr)
            continue

        # Prepend the T3 LLM summary (if we have one) as supplementary context.
        # Critical for scanned PDFs where raw extraction yields near-nothing,
        # and for very long files where the first-N-pages window misses the
        # user's target content (TOCs, later chapters, etc.).
        supplement = _summary_supplement(display)
        if supplement is not None:
            blocks = [supplement, *blocks]

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
        "Answer the current question using the files below. Follow the "
        "system-prompt guidance on terminology/unit mapping — if the file "
        "covers the concept under a different name, abbreviation, or unit "
        "(e.g. 'BPM' when the user asks about 'beats per second'), answer "
        "from what the file states and note the mapping rather than declaring "
        "the information absent. Cite the exact file paths (from the "
        "'--- File N: <path> ---' headers) in `sources_used`."
    )

    # If the user is asking an enumeration ("all my receipts" / "list every
    # X" / "what stuff did I do in Y") query, the strict-grounding rules
    # alone cause the LLM to cherry-pick a few "safe" representative items
    # and drop borderline matches. Enumeration questions need the opposite
    # stance: be exhaustive, include every file that plausibly fits, and
    # let borderline cases in with a short hedge rather than dropping them.
    # B1's classifier is the existing mechanism — re-run it here so the
    # answer stage sees the same class the search layer used. Pure regex,
    # no LLM call, cheap to run.
    from src.stage2.query_classify import QueryClass, classify as _classify_q
    if _classify_q(question) is QueryClass.LIST_ALL:
        intro_parts.append(
            ""
        )
        intro_parts.append(
            "ENUMERATION MODE: this is a 'list all' / 'give me every X' "
            "question. Be EXHAUSTIVE — include every file in the input "
            "that plausibly fits the user's category. Do NOT cherry-pick "
            "a few representative examples and drop the rest. If a file's "
            "membership in the category is uncertain, include it with a "
            "short hedge (e.g. '(possibly also a receipt)' / 'related: ...') "
            "rather than omitting. The strict grounding rules still apply "
            "— every line you write must be supported by visible file "
            "text — but for enumeration queries, err on the side of "
            "INCLUDING borderline matches rather than excluding them. "
            "List every contributing file in `sources_used`, not just the "
            "headline few."
        )

    message: list = ["\n".join(intro_parts)]
    for i, (display, blocks) in enumerate(per_file_blocks, 1):
        message.append(f"\n--- File {i}: {display} ---")
        message.extend(blocks)

    ans = await agent.run(message)

    # Defensive: drop any path the model invented that wasn't in our input.
    # Match is whitespace-tolerant — the model sometimes collapses double-spaces
    # or normalizes separators when echoing paths with spaces (e.g. "101 mus"),
    # which would cause a valid citation to be filtered out as a hallucination.
    # We ALSO accept an optional trailing `[book pp. N-M / PDF pp. X-Y]` page
    # suffix on each path: the bare path is verified against input_paths, but
    # the suffix is preserved in the output so the user sees both numbers.
    input_paths = {display for display, _ in per_file_blocks}
    normalized_input = {_normalize_path_for_match(p): p for p in input_paths}

    import re as _re
    _SUFFIX_RE = _re.compile(r"\s*(\[[^\]]*\])\s*$")

    filtered: list[str] = []
    dropped: list[str] = []
    for s in ans.sources_used:
        # Split off the page-citation suffix (if present) so we verify the
        # bare path against input_paths but keep the suffix for display.
        m = _SUFFIX_RE.search(s)
        if m:
            page_suffix = m.group(1)
            bare = s[: m.start()].rstrip()
        else:
            page_suffix = ""
            bare = s

        if bare in input_paths:
            canonical = bare
        else:
            canonical = normalized_input.get(_normalize_path_for_match(bare))

        if canonical is None:
            dropped.append(s)
            continue

        filtered.append(
            f"{canonical}  {page_suffix}" if page_suffix else canonical
        )

    if dropped:
        print(f"  warn: dropped hallucinated source paths: {dropped}", file=sys.stderr)
    ans.sources_used = filtered
    return ans


def _normalize_path_for_match(p: str) -> str:
    """Collapse whitespace and URL-decode so LLM-echoed paths match our originals.

    The model occasionally renders paths with collapsed spaces or %20-encoded
    spaces even when instructed to copy verbatim. Without normalization those
    echoes get filtered out as hallucinations and the user sees "Sources used:
    (none)" for an answer that did come from a real file.

    Also strips a trailing page-citation suffix like
    `  [book pp. 254-258 / PDF pp. 269-273]` or
    `  [PDF p. 7]` — added per system-prompt instruction so the user sees
    page info in the sources_used line. The canonical comparison is against
    the raw path; the suffix is recovered separately if we want to display it.
    """
    import urllib.parse as _up
    import re as _re
    decoded = _up.unquote(p)
    # Strip a trailing bracketed page-info suffix. The LLM is told to format
    # it as `<path>  [book pp. N-M / PDF pp. X-Y]` — we accept any [...]
    # block at the end of the string for forgiveness.
    decoded = _re.sub(r"\s*\[[^\]]*\]\s*$", "", decoded)
    return " ".join(decoded.split()).strip()


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
