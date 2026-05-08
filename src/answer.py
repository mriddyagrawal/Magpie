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
from typing import TYPE_CHECKING, Sequence

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.content import SummarizeError, build_content_blocks
from src.ingest.ripgrep import format_hits_block, search_file as ripgrep_search
from src.llm import ChatAgent, build_agent
from src.manifest import APP_DATA_DIR, Manifest

if TYPE_CHECKING:
    from src.stage2.search import SearchQuery


# `REPO_ROOT` here is a legacy alias used to resolve manifest-relative paths
# (e.g. `summaries/<hash>_t1.md`). The app's data root is `APP_DATA_DIR`,
# which is portable across Linux / Windows / macOS via `platformdirs`.
REPO_ROOT = APP_DATA_DIR
ANSWER_MAX_CHARS_PER_FILE = 25_000
ANSWER_MAX_PDF_PAGES = 5
# `_summary_supplement` was designed for T3 LLM summaries (~200-500 words,
# typically <2 KB). Plan #17 Part A made T1 CSV summaries also LLM-generated
# (no more raw-content dumps), so the cap can be much higher than the
# emergency 4 KB band-aid we used to need. 10 KB comfortably fits any real
# FileSummary while still truncating accidental misuse.
ANSWER_SUPPLEMENT_MAX_CHARS = 10_000


class Answer(BaseModel):
    answer: str = Field(
        description=(
            "Natural-language answer grounded strictly in the provided files. "
            "Empty string when the question cannot be answered from the provided "
            "files (set `not_found=true` in that case)."
        )
    )
    sources_used: list[str] = Field(
        description=(
            "Subset of the input file paths the answer actually depends on. "
            "Copied verbatim from the '--- File N: <path> ---' headers. "
            "Do not include files you consulted but did not actually use. "
            "Empty list when `not_found=true`."
        )
    )
    not_found: bool = Field(
        default=False,
        description=(
            "Set to true when the provided files do not contain enough information "
            "to answer the question. When true, leave `answer` empty, leave "
            "`sources_used` empty, and set `not_found_topic` to a short noun "
            "phrase summarizing what the user was asking about."
        ),
    )
    not_found_topic: str = Field(
        default="",
        description=(
            "Short noun phrase summarizing what the user asked about, used in "
            "the UI's not-found copy ('I read 5 likely sources but didn't find "
            "anything about <topic>...'). Only set when `not_found=true`. "
            "Examples: 'a landlord's emergency phone number', 'the chemistry "
            "final exam time', 'who chairs the math department'."
        ),
    )


# NOTE: Until Phase 2.5 step 5 (cloud-provider wiring) lands, this prompt is
# duplicated in `server/magpie_server/prompts.py:ANSWER_PROMPT`. Edit there,
# not here — copy back to keep parity. After step 5 lands, this constant is
# deleted and the desktop calls /llm/answer on the cloud server instead.
SYSTEM_PROMPT = (
    "You are a file-grounded question-answering assistant. "
    "Answer the user's question using ONLY the files provided in the message. "
    "If the files do not contain the information needed to answer, say so explicitly — "
    "do not invent facts. "
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
    "for a list ('which courses...', 'what are all...', 'what receipts do I have'), "
    "return the full list AND include every retrieved file that qualifies — even "
    "if the file uses a different word for the category. A 'flight itinerary' or "
    "'trip confirmation' IS a travel receipt; a 'lease agreement' IS a contract; "
    "a 'bank statement' IS a financial record / receipt of transactions. Map the "
    "user's category to its equivalents in the files. Do NOT silently drop files "
    "from the answer because their internal label differs from the user's word. "
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
    "\n\n"
    "INLINE CITATION MARKERS. As you write the answer, cite the supporting "
    "file with a numbered marker in square brackets: `[1]` for the first "
    "file you cite, `[2]` for the second, and so on. The number is the "
    "1-based index into your `sources_used` list (the first entry of "
    "`sources_used` is `[1]`, the second is `[2]`, etc.). Place each "
    "marker immediately after the claim it supports, with no space "
    "before the bracket. Re-use the same number whenever you cite the "
    "same file again. Examples:\n"
    "  - 'The chair of the Mathematics department is Dr. Elena Marquez[1].'\n"
    "  - 'CSC-105 has 4 credit hours[1] and is offered every fall[2].'\n"
    "Do NOT use markers like `[Source 1]`, `[file: foo.pdf]`, or `(1)` — "
    "the bracketed number alone is the only accepted form. Do NOT invent "
    "citation numbers that exceed the length of `sources_used`. If you "
    "have nothing to cite for a claim, omit the marker entirely.\n"
    "\n\n"
    "WHEN YOU CANNOT ANSWER FROM THE PROVIDED FILES. If, after reading the "
    "files carefully (including the synonym/unit mapping above), none of "
    "them contain the information needed to answer the question, do NOT "
    "fabricate. Instead, set the result fields as follows:\n"
    "  - `not_found`: true\n"
    "  - `answer`: \"\" (empty string)\n"
    "  - `sources_used`: [] (empty list)\n"
    "  - `not_found_topic`: a short noun phrase summarizing what the user "
    "    asked about. Examples: 'a landlord's emergency phone number', "
    "    'the chemistry final exam time', 'who chairs the math department'. "
    "    Keep it short (a few words). Do not restate the full question.\n"
    "Use this branch ONLY when the files genuinely don't contain the answer. "
    "If the files contain the answer under a synonym, abbreviation, or "
    "different unit (per the mapping rules above), DO answer normally — "
    "that's not a not-found case.\n"
    "\n\n"
    "OUTPUT FORMAT — required schema. Respond with a single JSON object that "
    "has EXACTLY these four keys, named EXACTLY as shown:\n"
    "  {\"answer\": <string>, \"sources_used\": [<file path>, ...], "
    "\"not_found\": <boolean>, \"not_found_topic\": <string>}\n"
    "All four keys are required. Do NOT rename `answer` to something "
    "descriptive like `result` / `summary` / `courses_mentioned` / "
    "`findings` — small models tend to do this and it breaks downstream "
    "parsing. The key is literally the four letters `answer` regardless "
    "of what the question is about. "
    "If the answer is naturally a list (e.g. 'list every X'), join the "
    "items into a single string inside the `answer` value (use bullets "
    "`- ` or newlines), do NOT make `answer` a JSON array.\n"
    "Example for a successful answer with citations:\n"
    "  {\"answer\": \"The chair of the Mathematics department is "
    "Dr. Elena Marquez[1].\", \"sources_used\": "
    "[\"path/to/math-dept-2024.pdf\"], \"not_found\": false, "
    "\"not_found_topic\": \"\"}\n"
    "Example for a list-shaped question:\n"
    "  {\"answer\": \"- Item one[1]\\n- Item two[2]\\n- Item three[1]\", "
    "\"sources_used\": [\"path/to/file-a.md\", \"path/to/file-b.md\"], "
    "\"not_found\": false, \"not_found_topic\": \"\"}\n"
    "Example for a not-found case:\n"
    "  {\"answer\": \"\", \"sources_used\": [], \"not_found\": true, "
    "\"not_found_topic\": \"a landlord's emergency phone number\"}\n"
    "\n"
    "Output RAW JSON only — do not wrap the response in markdown code fences "
    "like ```json, and do not include any prose before or after the JSON object."
)


_ANSWER_FALLBACK = Answer(
    answer="(model output could not be parsed into Answer)",
    sources_used=[],
    not_found=False,
    not_found_topic="",
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
    search_query: "SearchQuery | None" = None,
    csv_row_hits: dict[str, list[int]] | None = None,
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
        # Defensive cap — see ANSWER_SUPPLEMENT_MAX_CHARS for why.
        truncated = len(body) > ANSWER_SUPPLEMENT_MAX_CHARS
        body = body[:ANSWER_SUPPLEMENT_MAX_CHARS]
        suffix = "\n…(supplement truncated)" if truncated else ""
        return (
            "Content type: llm-summary (distilled overview of the file — use "
            "alongside the raw content below, especially when the raw "
            "extraction is thin or the file is large)\n\n---\n"
            f"{body}{suffix}"
        )

    # If the caller did a Kimi rewrite, its `keywords` list is already the
    # discriminator-grade tokenization we want for ripgrep — names, dates
    # (in multiple formats, per the rewriter prompt), amounts, IDs. The raw
    # question's tokenizer would emit noise like "much" / "spend". Fall back
    # to the question when no rewrite was done (rewrite is off by default).
    if search_query is not None and search_query.keywords:
        rg_query = search_query.query + " " + " ".join(search_query.keywords)
    else:
        rg_query = question

    def _csv_row_indexes_for(display: str, abs_path: Path) -> list[int] | None:
        """Look up the row indexes for this path in `csv_row_hits`.

        Search by display path (the value `pipeline.ask` passes) first, then
        absolute path as a fallback. Returns None if no row hits — the path
        will fall through to the standard file-content path."""
        if csv_row_hits is None:
            return None
        if display in csv_row_hits:
            return csv_row_hits[display]
        abs_str = str(abs_path)
        if abs_str in csv_row_hits:
            return csv_row_hits[abs_str]
        return None

    # Build blocks for every valid file off the event loop (pypdf, pymupdf, etc. are blocking)
    per_file_blocks: list[tuple[str, list]] = []
    for display, abs_path in valid:
        try:
            csv_hits = _csv_row_indexes_for(display, abs_path)
            is_csv = abs_path.suffix.lower() == ".csv"

            if is_csv and csv_hits:
                # Plan #17 Part B (case B/C): one or more rows of this CSV
                # were retrieved → row-window block (matched rows + ±2
                # neighbors, merged across hits). The LLM summary still
                # gets prepended as supplement.
                from src.stage2.search import build_csv_row_window_block
                block = await asyncio.to_thread(
                    build_csv_row_window_block, display, csv_hits
                )
                if block is None:
                    blocks = [
                        f"Content type: csv-row-windows\n\n---\n"
                        f"(could not read {abs_path.name} from disk)"
                    ]
                else:
                    blocks = [
                        f"Content type: csv-row-windows (the rows that match "
                        f"the question, with ±2 neighbors for context; "
                        f"matched rows are tagged inline. Full CSV is "
                        f"intentionally NOT included — rely on the per-file "
                        f"summary above for cross-row context or to know "
                        f"what the CSV is about as a whole)\n\n---\n{block}"
                    ]
            elif is_csv:
                # Plan #17 Part B (case A): the CSV's file-level summary
                # point hit in retrieval but no specific rows did. The
                # user asked something the summary matched semantically
                # ("do we have a faculty directory?"), not something a
                # row matches verbatim. Surface the first 5 rows as a
                # representative sample so the model has a concrete
                # picture of row shape alongside the summary supplement.
                from src.stage2.search import build_csv_sample_block
                block = await asyncio.to_thread(build_csv_sample_block, display)
                if block is None:
                    blocks = [
                        f"Content type: csv-sample\n\n---\n"
                        f"(could not read {abs_path.name} from disk)"
                    ]
                else:
                    blocks = [
                        f"Content type: csv-sample (first 5 rows of this CSV "
                        f"— no specific row matched your question; the "
                        f"per-file summary above explains what the CSV is "
                        f"overall, the rows below are illustrative of its "
                        f"shape)\n\n---\n{block}"
                    ]
            elif _is_t0(display):
                # T0 files: skip the whole-file read and lean on ripgrep.
                hits = await asyncio.to_thread(ripgrep_search, abs_path, rg_query)
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
                # Pass the rewriter's keywords through so build_content_blocks
                # can lazy-chunk long PDFs into the most relevant pages instead
                # of always returning the first N chars (preface for a 700-page
                # textbook). Without this, page-anchor headers (`## PDF page N
                # (book p. X)`) never get emitted, the LLM has nothing to cite,
                # and `sources_used` shows up without `[book pp. X / PDF pp. Y]`.
                keywords = list(search_query.keywords) if search_query else None
                blocks = await asyncio.to_thread(
                    build_content_blocks,
                    abs_path,
                    max_chars=ANSWER_MAX_CHARS_PER_FILE,
                    max_pdf_pages=ANSWER_MAX_PDF_PAGES,
                    search_keywords=keywords,
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

    # If the model declared not_found, normalize the rest of the payload so the
    # downstream consumer doesn't have to think about partial fills. Some small
    # models set not_found=true but still write a hedging "answer" and pick a
    # source — that's an inconsistent state, and the UI's not-found card has
    # no slot for either, so we drop them.
    if ans.not_found:
        if ans.answer or ans.sources_used:
            print(
                "  note: not_found=true but answer/sources_used were non-empty; "
                "clearing them to match the not-found contract",
                file=sys.stderr,
            )
        ans.answer = ""
        ans.sources_used = []
        return ans

    # Defensive: drop any path the model invented that wasn't in our input.
    # Match is whitespace-tolerant — the model sometimes collapses double-spaces
    # or normalizes separators when echoing paths with spaces (e.g. "101 mus"),
    # which would cause a valid citation to be filtered out as a hallucination.
    input_paths = {display for display, _ in per_file_blocks}
    normalized_input = {_normalize_path_for_match(p): p for p in input_paths}

    filtered: list[str] = []
    dropped: list[str] = []
    for s in ans.sources_used:
        if s in input_paths:
            filtered.append(s)
            continue
        canonical = normalized_input.get(_normalize_path_for_match(s))
        if canonical is not None:
            filtered.append(canonical)
        else:
            dropped.append(s)
    if dropped:
        print(f"  warn: dropped hallucinated source paths: {dropped}", file=sys.stderr)
    ans.sources_used = filtered
    return ans


def _normalize_path_for_match(p: str) -> str:
    """Collapse whitespace, URL-decode, and strip page-citation suffix so
    LLM-echoed paths match our originals.

    The model occasionally renders paths with collapsed spaces or %20-encoded
    spaces even when instructed to copy verbatim. Without normalization those
    echoes get filtered out as hallucinations and the user sees "Sources used:
    (none)" for an answer that did come from a real file.

    Also strips any trailing `[...]` page-citation suffix the LLM may have
    appended per the dual-page citation rule (`<path>  [book pp. 254-258 /
    PDF pp. 269-273]`). The suffix is for display, not for path matching —
    it must be removed before comparing against the canonical file path.
    """
    import re
    import urllib.parse as _up
    decoded = _up.unquote(p)
    # Strip trailing `[...]` (page-citation suffix or any other bracketed
    # annotation the LLM appended after the path).
    decoded = re.sub(r"\s*\[[^\]]*\]\s*$", "", decoded)
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
