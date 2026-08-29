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
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.content import SummarizeError, build_content_blocks
from src.grounding import looks_fabricated, strip_generated_blocks
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

# ---------------------------------------------------------------------------
# Context budget — local models only.
#
# The per-file caps alone allow 5 files × (25K content + 10K supplement)
# ≈ 175K chars ≈ 45K tokens. Cloud windows (128K+) swallow that; the local
# llama-server hard-REJECTS any request over its context window (16K
# default) — the model never sees the question and the user reads "answer
# not found" (2026-08-23: every multi-source local answer failed this way,
# requests of 24-52K tokens against the 16,384-token window).
# ---------------------------------------------------------------------------

# Rough chars-per-token for English prose + markdown. Deliberately LOW —
# overestimating tokens keeps us safely under the window; the failure mode
# of guessing high is a slightly shorter prompt, not a rejected request.
_CHARS_PER_TOKEN = 3.2
# Tokens held back for everything that isn't file blocks: system prompt,
# JSON-schema grammar, question, history, and the generated answer itself.
_ANSWER_RESERVE_TOKENS = 3_000


def _context_budget_chars() -> int | None:
    """Char budget for the file blocks, or None when no budget applies
    (cloud providers — their windows dwarf the per-file caps)."""
    try:
        from src.llm import active_provider

        if active_provider().name != "local":
            return None
        from src.inference.profiles import default_text_profile, get_profile

        ctx = get_profile(default_text_profile()).args.ctx_size
    except Exception:  # noqa: BLE001 — the budget is protective, never fatal
        ctx = 16_384
    usable_tokens = max(2_000, ctx - _ANSWER_RESERVE_TOKENS)
    # Prefill-speed cap — the window is not the only ceiling. On CPU,
    # llama-server reads ~50-100 tokens/s before the first output token, so
    # a 32K window packed full is 5-9 MINUTES of silence (observed
    # 2026-08-24: a 10-minute no-answer hang colliding with the 600s request
    # timeout). Cap the document budget so time-to-first-token stays humane;
    # GPU backends (metal/vulkan/cuda) prefill 10-100x faster and get the
    # full window. Fewer-but-sharper sources also suits a 3B model — see the
    # Lost-in-the-Middle note at the prompt assembly below.
    gpu_default = "metal" if sys.platform == "darwin" else "cpu"
    on_cpu = os.environ.get("LLAMA_SERVER_GPU", gpu_default).lower() == "cpu"
    cap_env = os.environ.get("LOCAL_PREFILL_BUDGET_TOKENS", "").strip()
    if on_cpu:
        prefill_cap = int(cap_env or "8000")
        usable_tokens = min(usable_tokens, max(2_000, prefill_cap))
    elif cap_env:
        # GPU backends prefill far faster than CPU, so they were left
        # uncapped — which on a 32K-window profile means a document budget of
        # ~29,700 tokens. Measured 2026-08-28 on the phyll corpus: the answer
        # step is ~48% of query wall-clock and scales with files read (2 files
        # 4.5s, 5 files up to 15.7s). Setting this caps GPU prefill the same
        # way, which is also what the Lost-in-the-Middle result argues for on
        # a 3B model: fewer, sharper sources beat a packed window. Unset =
        # previous behaviour (no GPU cap).
        usable_tokens = min(usable_tokens, max(2_000, int(cap_env)))
    return int(usable_tokens * _CHARS_PER_TOKEN)


def _block_cost_chars(block: object) -> int:
    """Budget cost of one message block. Non-text blocks (images on the
    vision path) get a flat cost — an image is ~1-2K tokens once encoded."""
    if isinstance(block, str):
        return len(block)
    return 6_000


def _trim_blocks_to_budget(
    per_file_blocks: list[tuple[str, list]], budget_chars: int
) -> list[tuple[str, list]]:
    """Fit the per-file blocks into `budget_chars`, best-ranked first.

    `per_file_blocks` arrives in retrieval rank order (best first). Files
    are kept whole until the budget runs out; the first block that crosses
    the line is truncated (text blocks only), everything after is dropped,
    and a note naming the dropped files is appended so the model can say
    they exist instead of hallucinating or denying them.
    """
    kept: list[tuple[str, list]] = []
    dropped: list[str] = []
    spent = 0
    for display, blocks in per_file_blocks:
        if spent >= budget_chars:
            dropped.append(display)
            continue
        out_blocks: list = []
        for block in blocks:
            cost = _block_cost_chars(block)
            if spent + cost <= budget_chars:
                out_blocks.append(block)
                spent += cost
                continue
            remaining = budget_chars - spent
            if isinstance(block, str) and remaining > 500:
                out_blocks.append(
                    block[:remaining]
                    + "\n…(truncated to fit the local model's context window)"
                )
            spent = budget_chars
            break
        if out_blocks:
            kept.append((display, out_blocks))
        else:
            dropped.append(display)
    if dropped and kept:
        last_display, last_blocks = kept[-1]
        kept[-1] = (
            last_display,
            [
                *last_blocks,
                "(Context note: "
                f"{len(dropped)} lower-ranked source file(s) were omitted to "
                "fit the local model's context window: "
                + ", ".join(dropped)
                + ". If the answer isn't in the files above, say these files "
                "exist but were not read — do not claim they don't exist.)",
            ],
        )
    return kept
# `_summary_supplement` was designed for T3 LLM summaries (~200-500 words,
# typically <2 KB). Plan #17 Part A made T1 CSV summaries also LLM-generated
# (no more raw-content dumps), so the cap can be much higher than the
# emergency 4 KB band-aid we used to need. 10 KB comfortably fits any real
# FileSummary while still truncating accidental misuse.
ANSWER_SUPPLEMENT_MAX_CHARS = 10_000

# Above this much raw extracted text, a file speaks for itself and the
# index-time summary is dropped from the answer context. Below it (scans,
# thin extractions) the summary is often the only readable content there is.
SUMMARY_UNNEEDED_ABOVE_CHARS = 1_500


class Answer(BaseModel):
    # Field order matters: it is the order the GBNF grammar forces the model
    # to emit (src/inference/gbnf.py). It used to run not_found first, on the
    # reasoning that letting the model commit to the verdict up front was
    # natural for the not-found path and harmless otherwise.
    #
    # That reasoning was written while `response_format` was believed to be
    # constraining generation. It wasn't — llama-server accepted the schema
    # and ignored it — so the order was never actually enforced and never
    # actually tested. The first run with a real grammar showed what it costs:
    # the model emits `not_found: true` as its opening token, with nothing
    # generated to base that on, and then writes the correct answer anyway.
    # Measured on the sem6 set (2026-08-27), verbatim:
    #
    #   {"not_found": true, ..., "answer": "The W-2 lists Furman University
    #    as the employer with the address 3300 Poinsett Highway, ..."}
    #   {"not_found": true, ..., "answer": "Receipt shows Avelo Airlines for
    #    170.18 USD[1]", "sources_used": [".../Flight Yale - GSP Receipt.pdf"]}
    #
    # Both correct, both deleted by the not-found contract below. Answer
    # first, verdict second: the model states what it found, then judges
    # whether that constitutes an answer — the decision now follows the
    # evidence instead of preceding it.
    answer: str = Field(
        ...,  # required: in not-found cases the model emits an empty string,
              # not a missing field — the strict JSON schema requires presence.
        description=(
            "Natural-language answer grounded strictly in the provided files. "
            "Empty string when the question cannot be answered from the provided "
            "files (set `not_found=true` in that case)."
        ),
    )
    sources_used: list[str] = Field(
        ...,  # required: emit an empty list in not-found cases, not a missing field.
        description=(
            "Subset of the input file paths the answer actually depends on. "
            "Copied verbatim from the '--- File N: <path> ---' headers. "
            "Do not include files you consulted but did not actually use. "
            "Empty list when `not_found=true`."
        ),
    )
    not_found: bool = Field(
        ...,  # required — the schema's `required` list controls what the
              # GBNF grammar enforces; with a Python default, pydantic
              # would mark this optional and the model could legally omit it.
        description=(
            "Set to true ONLY when `answer` above is empty because the provided "
            "files do not contain enough information. If you wrote an answer "
            "above, this is false."
        ),
    )
    not_found_topic: str = Field(
        ...,  # required: emit "" in found cases, the topic phrase in not-found cases.
        description=(
            "Short noun phrase summarizing what the user asked about, used in "
            "the UI's not-found copy ('I read 5 likely sources but didn't find "
            "anything about <topic>...'). Only set when `not_found=true`. "
            "Examples: 'a landlord's emergency phone number', 'the chemistry "
            "final exam time', 'who chairs the math department'."
        ),
    )


# NOTE: Until Phase 2.5 step 5 (cloud-provider wiring) lands, this prompt and
# the block constants below are duplicated in `server/magpie_server/prompts.py`
# (SYSTEM_PROMPT ↔ ANSWER_PROMPT, _INLINE_CITATION_BLOCK ↔
# ANSWER_CITATION_BLOCK, etc.). Edit there, not here — copy back to keep
# parity; server/tests/test_prompts_parity.py enforces it. After step 5 lands,
# these constants are deleted and the desktop calls /llm/answer instead.
#
# Prompt diet (2026-08-27): the always-on system prompt was 1,802 tokens of
# accreted eval patches, all paid on every question. A 3B model has a fragile
# instruction budget — rules that don't apply to THIS question actively
# compete with the ones that do — so everything situational now injects into
# the user message only when triggered (math, page anchors, llm-summary
# note, cloud output format), following the SYNTHESIS/ENUMERATION MODE
# pattern below. The always-on core is what's left here.
SYSTEM_PROMPT = (
    "You are a file-grounded question-answering assistant. Answer the "
    "user's question using ONLY the files provided in the message. Never "
    "invent facts.\n"
    "\n"
    "Terminology: the absence of the user's exact words does NOT mean the "
    "information is absent. If a file covers the concept under a different "
    "name, synonym, abbreviation, or unit (e.g. 'prereqs' → the file's "
    "'prerequisites'), answer from what the file states and briefly note "
    "the mapping. Do not bridge genuinely different concepts (don't answer "
    "a question about pitch from a file that only discusses rhythm).\n"
    "\n"
    "Be concise: give the shortest answer that directly addresses the "
    "question — one sentence or a short list. Do not restate the question "
    "or add background the user didn't ask for. Exception: when the "
    "question asks for a list or a comparison, completeness beats brevity "
    "— include every file that qualifies, even when its own label differs "
    "from the user's word for the category.\n"
    "\n"
    "If prior conversation turns are shown, use them only to resolve "
    "references in the current question ('it', 'that', 'the same course'); "
    "answer from the current files, never by recycling a prior answer.\n"
    "\n"
    "{citation_block}"
    "In `sources_used`, list only the files your answer actually depends "
    "on, each path copied verbatim from its '--- File N: <path> ---' "
    "header. If the answer is naturally a list, write the items as bullet "
    "lines inside the single `answer` string.\n"
    "\n"
    "If none of the files contain the answer (after the terminology rule "
    "above), do not fabricate: set not_found=true, answer=\"\", "
    "sources_used=[], and put a short noun phrase naming what was asked "
    "about in not_found_topic (e.g. 'a landlord's emergency phone number')."
)


_ANSWER_FALLBACK = Answer(
    answer="(model output could not be parsed into Answer)",
    sources_used=[],
    not_found=False,
    not_found_topic="",
)


# The inline-citation-marker instructions are factored out so the
# Settings → Search & AI → Advanced → "Cite sources inline" toggle can
# remove them at agent-build time when the user prefers plain prose.
# Cost: ~80 prompt tokens that the small model doesn't have to process
# when off. The frontend's renderAnswer() handles markerless prose
# gracefully (no orphan-pill warnings), so toggling at runtime is safe.
_INLINE_CITATION_BLOCK = (
    "Cite as you write: put a bracketed number immediately after the claim "
    "it supports — [1] is the first entry of `sources_used`, [2] the "
    "second; reuse a file's number on repeat citations. Example: 'CSC-105 "
    "has 4 credit hours[1] and is offered every fall[2].' Only this form "
    "counts (never '[Source 1]', '[file: x.pdf]', or '(1)'), and never use "
    "a number beyond the length of `sources_used`.\n"
    "\n"
)


# ---------------------------------------------------------------------------
# Situational blocks — injected into the USER message only when the
# assembled file content actually triggers them. Rationale for the split:
# each was an always-on system-prompt rule costing every question its full
# token weight (math 220, page-refs 229) even on corpora that never need
# them, and small-model instruction-following degrades as irrelevant rules
# stack up. Same injection mechanism as SYNTHESIS/ENUMERATION MODE.
# ---------------------------------------------------------------------------

_MATH_BLOCK = (
    "MATH NOTATION: prefer Unicode math symbols (∂ ∑ ∫ √ ≤ ≥ π x² m₁); "
    "use LaTeX $...$ only for structures Unicode can't express (fractions, "
    "integrals with limits). Source PDFs often garble math ('dldt' for "
    "'d/dt') — reconstruct the standard notation instead of copying it; if "
    "you can't reconstruct reliably, describe the equation in words."
)

# Fires on symbols/keywords that only show up in genuinely mathematical
# text. False positive = 80 wasted tokens; false negative = the model
# falls back to its default LaTeX habits. Both are cheap.
_MATH_SIGNALS = re.compile(
    r"[∂∫∑∏√∇]|\\frac|\$\$|\b(equation|theorem|integral|derivative)s?\b",
    re.IGNORECASE,
)

_PAGE_REF_BLOCK = (
    "PAGE REFERENCES: some files carry '## PDF page N (book p. X)' "
    "anchors. You may append page ranges to a `sources_used` entry as "
    "`<path>  [book pp. A-B / PDF pp. C-D]` — only pages that actually "
    "appear in what you read, never invented. Keep page numbers out of the "
    "answer prose unless the user explicitly asked where; then a single "
    "'page N' is allowed."
)

# The one-time explainer for 'Content type: llm-summary' markers — hoisted
# out of _summary_supplement so N files cost one explanation, not N.
_SUMMARY_NOTE = (
    "Some files include an 'llm-summary' — a distilled overview generated "
    "at indexing time; read it alongside that file's raw content (raw "
    "extraction can be thin for scans and large files)."
)

# Cloud only. The local path compiles the response schema to a GBNF grammar
# (llama-server json_schema → sampler-level enforcement), so the model
# literally cannot emit wrong keys, wrong order, fences, or stray prose —
# format instructions there are dead weight. Cloud providers run with NO
# response_format at all (Google AI Studio rejects both variants; see
# src/llm.py) and depend on the prompt plus parse_json_with_repair, so they
# keep an explicit spec. Placed at the bottom of the message: after
# thousands of tokens of file content, the recency zone is where a format
# contract survives.
_FORMAT_BLOCK_CLOUD = (
    "OUTPUT FORMAT: respond with a single raw JSON object — no markdown "
    "fences, no prose before or after — with exactly these four keys in "
    "this order:\n"
    "{\"answer\": <string>, \"sources_used\": [<file path>, ...], "
    "\"not_found\": <boolean>, \"not_found_topic\": <string>}\n"
    "Example: {\"answer\": \"The chair is Dr. Elena Marquez[1].\", "
    "\"sources_used\": [\"path/to/math-dept-2024.pdf\"], "
    "\"not_found\": false, \"not_found_topic\": \"\"}"
)


# MULTI-PART questions — the quietest failure class in the sem6 eval. Asked
# "what was my academic standing and class standing", the model answers one
# and stops; asked for fall AND spring inspection dates, it gives fall. Every
# such answer is strict-binary wrong while looking helpful, which is the
# worst combination for trust. Detector and injection follow the
# SYNTHESIS/ENUMERATION MODE pattern: pure regex, scoped to the questions
# that need it, so single-fact questions never see the extra instruction.
_MULTIPART_BLOCK = (
    "MULTI-PART QUESTION: this asks for more than one thing. Answer EVERY "
    "part explicitly, in the order asked, even when a part is a single word "
    "or a single number. Do not stop after the first part, and do not merge "
    "two parts into one vague sentence. If one part genuinely is not in the "
    "files, answer the parts that are and say which part is missing."
)

# Fires on: two interrogatives joined by 'and' ('when ... and where ...'),
# an explicit pairing ('both X and Y', 'X and Y respectively'), or a
# coordinated noun pair in the question's object ('the fall and spring
# inspections', 'my total and section scores'). Deliberately does NOT fire on
# a bare 'and' inside a proper noun.
_MULTIPART_RE = re.compile(
    r"\b(what|when|where|who|which|how (?:much|many|long|far))\b[^?]{0,80}?"
    r"\band\b[^?]{0,80}?\b(what|when|where|who|which|how|did|was|were|is|are|do|does)\b"
    r"|\bboth\b.{0,60}\band\b"
    r"|\b(fall|spring|first|second|total)\b\s+and\s+\b(spring|fall|second|third|section)\b"
    # A repeated head noun across the conjunction: "academic standing and
    # class standing", "trip fare and total fare". The repetition is what
    # marks it as two things rather than one compound name.
    r"|\b(?P<head>\w{4,})\b[^?]{0,24}\band\b[^?]{0,24}\b(?P=head)\b"
    # An Oxford-comma list is three or more things by construction.
    r"|,\s+and\b",
    re.IGNORECASE,
)


def _needs_prompted_format() -> bool:
    """True when the active provider enforces JSON by prompt rather than
    grammar. On any doubt, include the block: the cost is ~120 tokens; the
    failure mode of omitting it on a cloud path is a parse failure."""
    try:
        from src.llm import active_provider

        return active_provider().name != "local"
    except Exception:  # noqa: BLE001
        return True


def _resolve_system_prompt(cite_inline: bool) -> str:
    """Final system prompt with the citation block included or stripped
    based on the user's `cite_sources_inline` setting."""
    return SYSTEM_PROMPT.replace(
        "{citation_block}",
        _INLINE_CITATION_BLOCK if cite_inline else "",
    )


def build_answer_agent(*, cite_inline: bool | None = None) -> ChatAgent[Answer]:
    """Build the answer agent. `cite_inline` overrides the setting; if
    None, reads the user's preference from settings.json. Lazy import
    of the settings layer keeps this module importable in environments
    where the config layer isn't built yet (e.g., test fixtures)."""
    if cite_inline is None:
        try:
            from src.config.settings import effective_settings
            cite_inline = effective_settings().cite_sources_inline
        except Exception:  # noqa: BLE001
            cite_inline = True  # safe default — match the original behavior
    return build_agent(_resolve_system_prompt(cite_inline), Answer, _ANSWER_FALLBACK)


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
    enumerate_lists: bool = True,
    temperature: float | None = None,
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
        # Bare marker — the one-time _SUMMARY_NOTE in the message intro
        # explains it, so N files don't repeat the same 34-token sentence.
        return (
            "Content type: llm-summary\n\n---\n"
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
        # A summary earns its place when raw extraction is thin — a scan, or a
        # long file whose first pages miss the target. When the file already
        # yields plenty of real text, the summary is a paraphrase competing
        # with the source, and a bad one wins: the sem_4 corpus contains a
        # $20 Cursor invoice whose generated summary describes "a flight from
        # Atlanta to Hartford, flight number DL1492, passenger Jane Doe". The
        # model saw the real receipt AND that fiction, and refused. Five
        # questions died on that one summary.
        #
        # MAGPIE_SUMMARY_WHEN_THIN=0 restores the old always-attach behaviour.
        # Pre-registered gate was >=12/25 on sem_4; it landed 8/25 against a
        # 7/25 baseline, so it does NOT ship. Off by default, kept behind
        # MAGPIE_SUMMARY_WHEN_THIN=1 because the diagnosis behind it is still
        # sound (one invented summary poisoned five questions) — the fix just
        # is not "hide the summary", it is "do not write a fictional one".
        if supplement is not None and os.environ.get(
            "MAGPIE_SUMMARY_WHEN_THIN", "0"
        ).strip() == "1":
            raw_chars = sum(len(b) for b in blocks if isinstance(b, str))
            if raw_chars >= SUMMARY_UNNEEDED_ABOVE_CHARS:
                supplement = None
        if supplement is not None:
            blocks = [supplement, *blocks]

        per_file_blocks.append((display, blocks))

    if not per_file_blocks:
        raise SummarizeError("no files could be read (all were unsupported or empty)")

    # Fit the blocks to the active model's context window (local only —
    # see _context_budget_chars). Must run BEFORE the recency reversal
    # below so it keeps the best-ranked files, not the worst.
    _budget = _context_budget_chars()
    if _budget is not None:
        per_file_blocks = _trim_blocks_to_budget(per_file_blocks, _budget)

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
    # One line, not a paragraph: the terminology and citation rules already
    # live in the system prompt — re-explaining them here cost ~100 tokens
    # per question and taught the model nothing new.
    intro_parts.append(
        "Answer the current question from the files below. If a file uses "
        "a different word for the same concept, that still counts — see "
        "the terminology rule."
    )

    # Situational guidance — injected only when the content that triggers
    # it is actually in the message (see the block constants above).
    _flags_text = "\n".join(
        b for _d, _blocks in per_file_blocks for b in _blocks
        if isinstance(b, str)
    )
    if "Content type: llm-summary" in _flags_text:
        intro_parts.append("")
        intro_parts.append(_SUMMARY_NOTE)
    if _MATH_SIGNALS.search(_flags_text):
        intro_parts.append("")
        intro_parts.append(_MATH_BLOCK)
    if "## PDF page" in _flags_text:
        intro_parts.append("")
        intro_parts.append(_PAGE_REF_BLOCK)

    # If the user is asking an enumeration ("all my receipts" / "list every
    # X" / "what stuff did I do in Y") query, the strict-grounding rules
    # alone cause the LLM to cherry-pick a few "safe" representative items
    # and drop borderline matches. Enumeration questions need the opposite
    # stance: be exhaustive, include every file that plausibly fits, and
    # let borderline cases in with a short hedge rather than dropping them.
    # B1's classifier is the existing mechanism — re-run it here so the
    # answer stage sees the same class the search layer used. Pure regex,
    # no LLM call, cheap to run.
    # SYNTHESIS MODE — targeted, not global (2026-08-24). A first attempt
    # put a "multi-file answers are normal" permission into the SYSTEM
    # prompt; cross-doc refusals improved (two first-ever wins) but
    # single-doc questions started overthinking themselves into refusals —
    # the previously-perfect q01 sentinel regressed on BOTH providers
    # (Evaluations/college_data/REPORT.md). Injecting per-question, exactly
    # like ENUMERATION MODE below, scopes the permission to the questions
    # shaped like comparisons and leaves single-doc questions untouched.
    import re as _re
    _COMPARATIVE_RE = _re.compile(
        r"\b(compare|versus|vs\.?|difference between|connects?|links?|"
        r"in common|both .{0,40}\b(essays?|files?|documents?|letters?)|"
        r"same (file|document|content)|are (these|those|they) .{0,20}same)\b",
        _re.IGNORECASE,
    )
    if _COMPARATIVE_RE.search(question):
        intro_parts.append("")
        intro_parts.append(
            "SYNTHESIS MODE: this question compares or connects things that "
            "may live in DIFFERENT files. Assembling the answer from several "
            "of the provided files is expected and correct: take fact A from "
            "one file, fact B from another, state the comparison plainly, "
            "and cite every file used in `sources_used`. Structure the "
            "answer as one short labeled part per side (e.g. 'Rochester: … "
            "Swarthmore: …'). The absence of a single file containing the "
            "whole comparison is NOT a not-found case — declare not_found "
            "only if a needed side is missing from EVERY provided file, and "
            "name that missing side in `not_found_topic`."
        )

    # Off by default until measured; the arm that tests it sets
    # MAGPIE_MULTIPART=1. Same escape-hatch shape as LOCAL_GRAMMAR.
    if os.environ.get("MAGPIE_MULTIPART", "0").strip() == "1" and (
        _MULTIPART_RE.search(question)
    ):
        intro_parts.append("")
        intro_parts.append(_MULTIPART_BLOCK)

    from src.stage2.query_classify import QueryClass, classify as _classify_q
    if enumerate_lists and _classify_q(question) is QueryClass.LIST_ALL:
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

    # Reverse so the highest-ranked retrieval result lands closest to
    # generation. Liu et al. (2023, "Lost in the Middle") found that
    # smaller decoder-only models are heavily recency-biased
    # (Llama-2 7B is "solely recency-biased"); Gemma 4 E4B sits in the
    # same size class. Position effect is large — up to 20 points of
    # accuracy and worse-than-closed-book in the worst case. The
    # "File N" header is just an identifier — citation numbers
    # (`[1]`, `[2]`) are 1-based into `sources_used`, which the model
    # assembles itself, so reversing the prompt order doesn't affect
    # the citation contract.
    ordered_blocks = list(reversed(per_file_blocks))
    message: list = ["\n".join(intro_parts)]
    for i, (display, blocks) in enumerate(ordered_blocks, 1):
        message.append(f"\n--- File {i}: {display} ---")
        message.extend(blocks)

    # Prompt-enforced JSON contract, cloud only — the local grammar makes
    # it unnecessary (see _FORMAT_BLOCK_CLOUD for the full rationale).
    if _needs_prompted_format():
        message.append(f"\n{_FORMAT_BLOCK_CLOUD}")

    # Echo the question once more at the bottom (query-aware
    # contextualization). Liu et al. found this had minimal impact on
    # multi-document QA for 30B+ models, but small recency-biased models
    # benefit from having the question text in the recency zone right
    # before generation — otherwise the question can effectively be
    # "forgotten" after the model reads thousands of tokens of file
    # content. Cheap (~15-30 tokens) for a real win on a 3B backend.
    message.append(f"\nNow answer this question: {question}")

    ans = await agent.run(message, temperature=temperature)

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

    # Groundedness guard. Every number in the answer is checked against the
    # text the model was actually shown; if NONE of them appear there (and
    # none is the sum of numbers that do), the answer is a fabrication and
    # the honest output is the not-found contract. Measured on the sem6
    # absence probe: asked what he paid for his dorm room — a figure no file
    # in the corpus contains — the model answered "$159.00". Deterministic,
    # no extra model call, and deliberately conservative: an answer with one
    # bad figure among good ones is a misreading the citations let the user
    # check, and it passes through untouched. See src/grounding.py.
    if ans.answer:
        # Index-time LLM summaries do NOT count as support for a figure. A
        # summary is the model's own earlier output; letting it ground a
        # later answer is how a fabrication launders itself into a fact.
        # Measured on the 40-question sem6 set: score-neutral (31/40 either
        # way) and it converted two invented figures — a €2,500.00 salary and
        # a postcode — into honest refusals. MAGPIE_STRICT_GROUNDING=0 turns
        # it off for anyone who would rather have the guess.
        _blocks = [
            b for _d, blocks in per_file_blocks for b in blocks if isinstance(b, str)
        ]
        if os.environ.get("MAGPIE_STRICT_GROUNDING", "1").strip() != "0":
            _blocks = strip_generated_blocks(_blocks)
        context_text = "\n".join(_blocks)
        if looks_fabricated(ans.answer, context_text):
            print(
                "  note: every figure in the answer is absent from the files "
                "read; returning not-found instead",
                file=sys.stderr,
            )
            ans.not_found = True
            ans.not_found_topic = ans.not_found_topic or question.strip().rstrip("?")
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
