"""Stage 1: summarize a single local file via Moonshot Kimi + PydanticAI.

Incremental by default. Tracks state in `Test Summaries/_manifest.json`:
- Unchanged files (same byte size) are skipped without hashing.
- Changed files (new byte size) are re-summarized; the old summary file is
  hard-deleted; the manifest row is updated and its `ingested_at` cleared
  so Stage 2 re-ingests.
- Files that vanished from disk are hard-deleted from the manifest and their
  summary files removed (batch mode only; single-file mode doesn't prune).

Pass `--force` to re-summarize everything regardless of size.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import re
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from src.content import (
    IMAGE_EXTS,
    SUPPORTED_EXTS,
    SummarizeError,
    build_content_blocks,
)
from src.llm import ChatAgent, active_provider, build_agent as _build_chat_agent
from src.manifest import APP_DATA_DIR, SUMMARIES_DIR, Manifest


MAX_TEXT_CHARS = 120_000
PDF_VISION_MAX_PAGES = 20
HASH_CHUNK = 1 << 20  # 1 MiB

# Legacy alias — historical code resolves manifest paths relative to this.
# Now points to the portable per-OS app data dir (see src/manifest.py).
REPO_ROOT = APP_DATA_DIR

ContentType = Literal["image", "pdf", "docx", "xlsx", "csv", "text", "code", "markdown", "other"]


class FileSummary(BaseModel):
    title: str = Field(description="Short human-readable title for the file (<=80 chars).")
    summary: str = Field(
        description=(
            "Comprehensive 3-7 sentence summary covering what the file is and the headline "
            "facts (merchant/author, dates, totals, key items). Write natural prose but include "
            "discriminator tokens verbatim — names, dates, totals — so retrieval can match them."
        )
    )
    content_type: ContentType = Field(description="What kind of content the file is.")
    keywords: list[str] = Field(description="3-10 topical keywords/tags for retrieval.")
    key_entities: list[str] = Field(
        description=(
            "Named entities mentioned in the file: people, organizations, places, products, "
            "branches/locations, file paths, function/class names. One entity per item, "
            "copied verbatim from the source."
        )
    )
    identifiers: list[str] = Field(
        description=(
            "Exact-match tokens that uniquely distinguish this file from similar ones. "
            "Copy capitalization, punctuation, and formatting EXACTLY as in the source. "
            "Include any of: order/transaction/receipt/invoice/slip/register/store/cashier numbers, "
            "barcodes, SKUs, dates in their original format (e.g. '25 May 2022', '05/04/23'), "
            "version strings, error codes, URLs, exact prices with currency. "
            "Empty list only if the file genuinely has none."
        )
    )

    # Cloud-provider drift tolerances. Local Gemma's grammar-constrained
    # generation enforces these field shapes at the token level so the
    # validators below are no-ops. Cloud (OpenRouter / Moonshot) only
    # has prompt-mode JSON instructions — Gemma in particular sometimes
    # emits a different-shaped value for these fields. Without these
    # coercions the whole FileSummary fails Pydantic validation, which
    # causes parse_json_with_repair to give up and the file to drop out
    # of the manifest entirely (silent data loss). Better to coerce.

    @field_validator("content_type", mode="before")
    @classmethod
    def _coerce_content_type(cls, v):
        # The schema's `ContentType` Literal is all-lowercase
        # ('image', 'pdf', 'docx', 'xlsx', 'text', 'code', 'markdown',
        # 'other'). Cloud output drifts on this field in two ways:
        # (1) capitalization ('CSV', 'PDF') — fixed by lowercasing.
        # (2) values outside the Literal entirely ('csv', 'html',
        # 'json', 'audio', 'video') — these aren't valid content_type
        # values today; map them all to 'other' so the validation
        # passes. The downstream consumer never branches on the niche
        # values anyway, so 'other' is harmless. Without this, every
        # cloud-summarized CSV crashes here.
        _VALID = {
            "image", "pdf", "docx", "xlsx", "csv", "text", "code", "markdown", "other",
        }
        if isinstance(v, str):
            lowered = v.lower().strip()
            return lowered if lowered in _VALID else "other"
        return v

    @field_validator("key_entities", "keywords", "identifiers", mode="before")
    @classmethod
    def _coerce_string_list(cls, v):
        # The schema asks for `list[str]`. Cloud output sometimes returns
        # `list[dict]` shaped like `[{"name": "Furman Clarinet Society",
        # "type": "organization"}]` for `key_entities`, or occasionally
        # mixes strings and dicts inside `identifiers`. Coerce each item:
        # dict → first non-empty value of the conventional name keys;
        # else str()-fall-through. Keeps the downstream consumer's
        # `list[str]` invariant intact.
        if not isinstance(v, list):
            return v
        out: list[str] = []
        for item in v:
            if isinstance(item, str):
                out.append(item)
                continue
            if isinstance(item, dict):
                # Try common name-ish keys in order. Models drift
                # toward {"name": ..., "type": ...} most often, but
                # occasionally use "value", "label", "text", or "id".
                for key in ("name", "value", "label", "text", "title", "id"):
                    val = item.get(key)
                    if isinstance(val, str) and val.strip():
                        out.append(val.strip())
                        break
                else:
                    # Last-ditch fallback: stringify the whole dict.
                    out.append(str(item))
                continue
            # Numbers / bools / None → str().
            out.append(str(item))
        return out


# NOTE: Until Phase 2.5 step 5 lands, this prompt is duplicated in
# `server/magpie_server/prompts.py:SUMMARIZE_PROMPT`. Edit there, not here.
# After step 5: deleted; desktop calls /llm/summarize on cloud.
SYSTEM_PROMPT = (
    "You are a file-summarization assistant. Given a single file's content, produce a "
    "FileSummary with: `title`, `summary`, `content_type`, `keywords`, `key_entities`, "
    "`identifiers`.\n\n"
    "CRITICAL — preserve discriminators verbatim. The downstream retrieval system uses "
    "BOTH dense embeddings (semantic) and BM25 (exact-token) over your output. For BM25 "
    "to find a file later, the discriminating tokens must appear verbatim somewhere in "
    "`summary`, `key_entities`, or `identifiers`. Be aggressive about capturing:\n"
    "- All numeric IDs (order #, transaction #, receipt #, invoice #, slip #, register #, "
    "store #, cashier ID, barcode, SKU)\n"
    "- All dates in their ORIGINAL format (e.g. '25 May 2022', '05/04/23', '08-May-21')\n"
    "- Merchant / store / organization name AND branch / location\n"
    "- Full product / line-item names exactly as printed\n"
    "- Totals, subtotals, exact prices and currency symbols\n"
    "- For non-receipt files: file paths, function/class names, version strings, "
    "error codes, URLs\n\n"
    "CATEGORY tagging in keywords. If the file represents a recognizable "
    "category, include the category name in `keywords` EVEN IF the file does "
    "not use that exact word. Examples: a flight itinerary, trip confirmation, "
    "or e-ticket → add `receipt` (it's a travel receipt); a hotel booking "
    "→ add `receipt`; a bank statement → add `statement` and `receipt`; a "
    "lease agreement → add `contract`; a course syllabus → add `syllabus`; "
    "an order confirmation → add `receipt` and `order`. The user searches "
    "by category words, not file-internal jargon — so the category MUST "
    "appear in keywords for retrieval to work.\n\n"
    "Be specific and factual. Do not invent content that is not present. If a field "
    "would be empty (e.g. `identifiers` for a code file), return an empty list — do "
    "not pad with guesses.\n\n"
    "Output RAW JSON only — do not wrap the response in markdown code fences like "
    "```json, and do not include any prose before or after the JSON object."
)


# NOTE: see SUMMARIZE_PROMPT_LOCAL in server/magpie_server/prompts.py.
# This local-mode prompt may stay client-side post-step-5 (since local
# mode doesn't go through the cloud), TBD when v1.1 local-LLM ships.
LOCAL_SYSTEM_PROMPT = """You are a file analyzer. Given a file's content, output a JSON object describing what the file is and the details someone might use to find it later via keyword search.

The JSON MUST have exactly these keys (and only these keys):
- title (string, <=80 chars)
- summary (string, 3-7 sentences of natural prose)
- content_type (one of: "image", "pdf", "docx", "xlsx", "csv", "text", "code", "markdown", "other")
- keywords (list of 3-10 topical words)
- key_entities (list of named entities: people, organisations, places, products, branches — copied verbatim from the file)
- identifiers (list of exact tokens that uniquely distinguish this file: numeric IDs, dates in their ORIGINAL format, SKUs, version strings, exact prices with currency, URLs — copied verbatim)

FORMAT EXAMPLE — placeholders only. Every value below is a <SLOT>, not
content. NEVER copy a value from this example into your output; if the file
does not contain something, leave that field out rather than borrowing.
Input:
Filename: <FILENAME>
Content type: <TYPE>
<the file's own text>

Output:
{"title": "<short name drawn from the file>", "summary": "<2-4 sentences, only facts present in the file above>", "content_type": "<one of the allowed types>", "keywords": ["<term from the file>", "<term from the file>"], "key_entities": ["<person, org or place NAMED IN THE FILE>"], "identifiers": ["<id, code, date or amount COPIED FROM THE FILE>"]}

Now analyze the file below. Return ONLY the JSON object - no markdown fences, no code blocks, no commentary. Start with { and end with }."""


def build_agent() -> ChatAgent[FileSummary]:
    # No fallback — hard-fail on parse errors so the file is skipped cleanly
    # (matches cloud behavior). The walker's next pass will retry it.
    #
    # Why two prompts. The original reason recorded here was that "cloud
    # providers use PydanticAI's NativeOutput which enforces the schema
    # natively; local needs a few-shot example to stay in JSON mode." That
    # is now backwards on both halves: cloud's response_format was disabled
    # in 2026-05 because OpenRouter's Google AI Studio route rejects it, and
    # local gained real GBNF grammar enforcement, which no cloud provider
    # here has.
    #
    # The split survives for a different and better reason: the few-shot
    # example teaches the model WHAT to extract — identifiers verbatim,
    # dates in their original format, category words the user would actually
    # search for. Grammar constrains shape, never content, so a 3B model
    # still benefits from being shown a worked example. Keep both prompts;
    # just don't believe the old rationale.
    prompt = LOCAL_SYSTEM_PROMPT if active_provider().name == "local" else SYSTEM_PROMPT
    return _build_chat_agent(prompt, FileSummary, None)


# Fallback agent: built lazily on first cloud failure, cached for the rest of
# the process. Keyed on FALLBACK_LLM_PROVIDER (e.g. "ollama" / "moonshot").
# When unset OR set to the same value as LLM_PROVIDER, no fallback exists and
# `_run_with_retry` raises after primary failure — matching pre-fallback
# behavior.
_fallback_agent_cache: ChatAgent[FileSummary] | None = None
_fallback_checked: bool = False


def get_fallback_agent() -> ChatAgent[FileSummary] | None:
    """Return the cached fallback summarization agent, or None if not configured.

    Reads `FALLBACK_LLM_PROVIDER` once per process. Returns None if:
      - the env var is unset / empty
      - the env var equals `LLM_PROVIDER` (no point falling back to itself)
      - the env var names an unknown provider (warned once)

    The agent is built lazily so users not opting into a fallback don't
    pay the construction cost (model load, network warmup).
    """
    global _fallback_agent_cache, _fallback_checked
    if _fallback_checked:
        return _fallback_agent_cache
    _fallback_checked = True

    name = os.environ.get("FALLBACK_LLM_PROVIDER", "").strip().lower()
    if not name:
        return None

    from src.llm import PROVIDERS  # deferred import to avoid load-time cycle
    if name not in PROVIDERS:
        sys.stderr.write(
            f"  warn: FALLBACK_LLM_PROVIDER={name!r} unknown; "
            f"valid: {sorted(PROVIDERS)}\n"
        )
        return None
    if name == active_provider().name:
        # Falling back to the same provider doesn't help — skip silently.
        return None

    prompt = LOCAL_SYSTEM_PROMPT if name == "local" else SYSTEM_PROMPT
    _fallback_agent_cache = _build_chat_agent(
        prompt, FileSummary, None, provider_override=name
    )
    sys.stderr.write(
        f"  fallback summarization agent armed: provider={name!r}\n"
    )
    return _fallback_agent_cache


def build_user_message(path: Path) -> list:
    instruction = "Summarize this image." if path.suffix.lower() in IMAGE_EXTS else "Summarize this file."
    header = f"Filename: {path.name}\n{instruction}"
    blocks = build_content_blocks(
        path,
        max_chars=MAX_TEXT_CHARS,
        max_pdf_pages=PDF_VISION_MAX_PAGES,
    )
    return [header, *blocks]


def render_markdown(summary: FileSummary, source_rel: str) -> str:
    keywords = ", ".join(summary.keywords) if summary.keywords else "—"
    entities = ", ".join(summary.key_entities) if summary.key_entities else "—"
    identifiers = ", ".join(summary.identifiers) if summary.identifiers else "—"
    return (
        f"Source: {source_rel}\n\n"
        f"# {summary.title}\n\n"
        f"{summary.summary}\n\n"
        f"**Content type:** {summary.content_type}\n\n"
        f"**Keywords:** {keywords}\n\n"
        f"**Key entities:** {entities}\n\n"
        f"**Identifiers:** {identifiers}\n"
    )


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def source_rel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def write_summary_at(out_path: Path, summary: FileSummary, source_rel: str) -> None:
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(summary, source_rel), encoding="utf-8")


def _open_csv_text(path: Path) -> io.StringIO:
    """Read a CSV as text, trying UTF-8 first then falling back to Latin-1.

    Latin-1 never raises UnicodeDecodeError (every byte maps to a character),
    so it's a safe fallback for legacy CSVs (e.g. Excel exports with
    accented characters saved in a non-UTF-8 encoding). We decode the full
    file up front so the caller gets a stream where iteration can't fail
    on a late bad byte, then hand back a StringIO for csv.reader.
    """
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return io.StringIO(text)


def _count_csv_rows(path: Path) -> int:
    """Return the number of data rows (excluding header) in a CSV file."""
    try:
        reader = csv.reader(_open_csv_text(path))
        next(reader, None)  # skip header
        return sum(1 for _ in reader)
    except csv.Error as e:
        raise SummarizeError(f"cannot read CSV {path}: {e}") from e


def _delete_summary_file(rel_summary: str | None) -> None:
    if rel_summary is None:
        return
    p = REPO_ROOT / rel_summary
    if p.exists():
        p.unlink()


def bootstrap_manifest_from_existing(manifest) -> int:
    """Back-fill an empty manifest from the `Source:` line of existing summary files.

    Only runs when the manifest is empty but `Test Summaries/*.md` files exist
    (e.g. on first use after the manifest feature lands). Idempotent no-op if
    the manifest already has entries.
    """
    if manifest.entries:
        return 0
    if not SUMMARIES_DIR.is_dir():
        return 0

    count = 0
    for md in sorted(SUMMARIES_DIR.glob("*.md")):
        try:
            with md.open(encoding="utf-8") as f:
                first_line = f.readline()
        except OSError:
            continue
        if not first_line.startswith("Source:"):
            continue
        source_rel = first_line.removeprefix("Source:").strip()
        source_path = REPO_ROOT / source_rel
        if not source_path.is_file():
            continue
        try:
            size = source_path.stat().st_size
        except OSError:
            continue
        manifest.mark_summarized(source_rel, size, str(md.relative_to(REPO_ROOT)))
        count += 1

    if count:
        manifest.save()
    return count


MAX_429_RETRIES = 6


async def _run_with_retry(agent: ChatAgent[FileSummary], message: list, label: str) -> FileSummary:
    """Call agent.run() with retry on 429 + optional provider fallback.

    Two-stage failure handling:

      1. **429 backoff loop** on the primary agent — up to MAX_429_RETRIES
         attempts with exponential-or-server-suggested wait. Only `ModelHTTPError`
         with `status_code == 429` triggers retries; other HTTP / parse errors
         break out immediately.

      2. **Provider fallback** (if `FALLBACK_LLM_PROVIDER` is set): on ANY
         primary failure that isn't a 429 worth retrying — including
         `UnexpectedModelBehavior` (the SDK couldn't parse the response,
         which is what OpenRouter free-tier returns on quota exhaustion),
         non-429 HTTP errors, network errors — make ONE attempt against the
         fallback agent. If it succeeds, the file is rescued. If it also
         fails, raise the fallback's exception (chained from the primary's).

    Without `FALLBACK_LLM_PROVIDER`, behavior is identical to before this
    change — the primary failure propagates as a SummarizeError to the
    walker, and the file lands in the `errors` bucket of the run summary.
    """
    try:
        from pydantic_ai.exceptions import ModelHTTPError
    except ImportError:  # pragma: no cover — pydantic_ai is always installed
        ModelHTTPError = None  # type: ignore[assignment]

    last_error: Exception | None = None

    for attempt in range(1, MAX_429_RETRIES + 1):
        try:
            return await agent.run(message)
        except Exception as e:
            last_error = e

            is_retryable_429 = (
                ModelHTTPError is not None
                and isinstance(e, ModelHTTPError)
                and getattr(e, "status_code", None) == 429
                and attempt < MAX_429_RETRIES
            )
            if not is_retryable_429:
                # Either non-429, or the final 429 attempt — break out and try
                # the fallback (if configured), then re-raise.
                break

            # Parse retryDelay from the response body; fall back to exponential.
            wait = 2 ** attempt
            if isinstance(getattr(e, "body", None), dict):
                meta = e.body.get("metadata", {})  # type: ignore[union-attr]
                raw = meta.get("raw", "")
                if isinstance(raw, str):
                    import re
                    m = re.search(r'"retryDelay":\s*"(\d+)s?"', raw)
                    if m:
                        wait = int(m.group(1)) + 1
            from tqdm import tqdm
            tqdm.write(f"  429 on {label}, retry {attempt}/{MAX_429_RETRIES} in {wait}s")
            await asyncio.sleep(wait)

    # Primary failed. Last-ditch attempt on the fallback agent if configured.
    #
    # Building that agent can itself hard-exit: `_CloudAgent.__init__` calls
    # sys.exit when the fallback provider has no API key, which is the normal
    # state of a Local-only install. Observed 2026-08-27 indexing a code
    # folder — one file's summary failed, the fallback tried to construct an
    # unconfigured `ollama` agent, and SystemExit propagated out of the
    # worker and killed a sync that had already summarized 28 of 98 files.
    # A missing fallback is not an error condition; it just means there is
    # no fallback, and the caller's own retry/stub path should handle it.
    try:
        fallback = get_fallback_agent()
    except (SystemExit, Exception) as e:  # noqa: BLE001 — never kill a sync here
        from tqdm import tqdm
        tqdm.write(
            f"  note: no usable fallback provider for {label} "
            f"({type(e).__name__}); continuing with the primary failure"
        )
        fallback = None
    if fallback is not None and last_error is not None:
        from tqdm import tqdm
        primary_kind = type(last_error).__name__
        tqdm.write(f"  fallback firing on {label} (primary raised {primary_kind})")
        try:
            return await fallback.run(message)
        except Exception as fallback_err:
            tqdm.write(
                f"  fallback also failed on {label}: "
                f"{type(fallback_err).__name__}: {fallback_err}"
            )
            raise fallback_err from last_error

    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable")


# Declaration shapes for the languages this corpus actually contains. Each
# pattern captures ONE name. Kept deliberately dumb: a regex that misses an
# exotic declaration costs us one symbol, while a parser per language costs a
# dependency per language.
_SYMBOL_PATTERNS = (
    # C#, Java, TypeScript: modifiers then class/interface/struct/enum/record
    r"\b(?:class|interface|struct|enum|record)\s+([A-Za-z_]\w*)",
    # C#/Java method: modifiers, return type, name, open paren
    # ...the trailing `(?:<...>)?` is load-bearing: a generic method reads
    # `public static List<T> GetUniqueItems<T>(...)`, and without it the
    # name-then-paren match fails on exactly the methods most worth finding.
    r"\b(?:public|private|protected|internal|static|async|override|virtual)\s+"
    r"[\w<>\[\],?\s]+?\s+([A-Za-z_]\w*)\s*(?:<[^>()]{0,40}>)?\s*\(",
    # Python / Ruby
    r"^\s*def\s+([A-Za-z_]\w*)",
    # JS/TS functions and Go/Rust
    r"\bfunction\s+([A-Za-z_]\w*)",
    r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)",
    r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)",
    # namespace / package / module
    r"\b(?:namespace|package|module)\s+([A-Za-z_][\w.]*)",
)

_CODE_SUFFIXES = {
    ".cs", ".java", ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".rb", ".kt", ".swift", ".cpp", ".c", ".h", ".hpp",
}

# Below this much extracted text, the file is effectively unreadable and its
# summary cannot be checked against anything. Scanned pages land here.
MIN_SOURCE_CHARS = 200

# Cap so one generated file cannot flood the embedding text with symbols.
MAX_SYMBOLS = 60

# Names that appear in every project and identify nothing.
_SYMBOL_STOPWORDS = {
    "Main", "ToString", "Equals", "GetHashCode", "Dispose", "get", "set",
    "if", "for", "while", "switch", "return", "using", "new",
}


def extract_code_symbols(path: Path) -> list[str]:
    """Class / method / namespace names declared in a source file.

    Why this exists: the summarizer describes code in prose and drops every
    identifier. Measured on the sem5 C# corpus — the summary of
    `GeneralUtils.cs` contains none of `GetIndentation`, `ToCamelCase`,
    `IsPasswordStrong` or `IsValidOperator`, and its `Identifiers:` line is
    empty. Search embeds the summary, not the file, so a question naming any
    of those methods had no dense OR lexical hook and the file was never
    retrieved: 7 of 25 questions lost their key file that way.

    Symbols are exactly the kind of thing a regex gets right and a 3B gets
    vague about, so they are extracted here rather than asked for.
    """
    if path.suffix.lower() not in _CODE_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for pattern in _SYMBOL_PATTERNS:
        for m in re.finditer(pattern, text, re.MULTILINE):
            name = m.group(1)
            if name in seen or name in _SYMBOL_STOPWORDS or len(name) < 3:
                continue
            seen.add(name)
            found.append(name)
            if len(found) >= MAX_SYMBOLS:
                return found
    return found


def scrub_invented_numbers(summary: FileSummary, path: Path) -> FileSummary:
    """Remove figures from a summary that do not appear in the source file.

    A summary is written once and read forever: every question about that
    file is answered with it in context, so a number the summarizer invented
    becomes a permanent, apparently-grounded fact. This is not theoretical.
    The Max Planck invitation letter in the sem6 corpus has all of its digits
    destroyed by a font-encoding bug — the salary reads 'Ҏ.ҔҐҎ.ҕɦ €' — and
    its summary confidently states '2,500.00' and postcode '44801'. Asked
    what the letter offers, Magpie answered '€2,500.00'. The lie was
    manufactured at index time, months before the question.

    So each figure in the summary text is checked against the extracted
    source and replaced with '[unreadable]' when it is absent. Deliberately
    only figures: prose can paraphrase, numbers cannot.
    """
    from src.grounding import numerals

    try:
        blocks = build_content_blocks(path, max_chars=60_000, max_pdf_pages=20)
    except Exception:  # noqa: BLE001 — no source text means nothing to check against
        return summary
    source = "".join(b for b in blocks if isinstance(b, str))

    # A scanned page has no text layer, so its extraction is a one-line
    # marker and NOTHING the summarizer wrote can be matched against it —
    # including the figures a vision pass read correctly off the image.
    # Scrubbing there deletes good data: a hotel folio in the sem6 corpus
    # lost its confirmation number, both stay dates and its total to this
    # exact mistake. No text to check against means no checking.
    if "scanned / image-only" in source or len(source.strip()) < MIN_SOURCE_CHARS:
        return summary

    # The filename is evidence too — a year or an invoice number that
    # appears only in the path is still grounded, not invented.
    source = f"{path.name}\n{source}"
    if not source.strip():
        return summary
    # Compare against a de-spaced copy too: letter-spaced PDFs render '2026'
    # as '2 0 2 6', and that is support, not a fabrication.
    haystack = re.sub(r"(?<=\d),(?=\d)", "", source)
    despaced = re.sub(r"\s+", "", haystack)

    scrubbed = 0

    def _replace(match: "re.Match[str]") -> str:
        nonlocal scrubbed
        tok = match.group(0)
        bare = tok.replace(",", "")
        if bare in haystack or bare in despaced or tok in haystack:
            return tok
        scrubbed += 1
        return "[unreadable]"

    text = summary.summary
    # Same numeral shape and same "ignore the small stuff" floor the runtime
    # groundedness check uses, so index time and answer time agree.
    interesting = {n for n in numerals(text)}
    if not interesting:
        return summary
    new_text = re.sub(
        r"\d[\d,]*(?:\.\d+)?",
        lambda m: _replace(m) if m.group(0).replace(",", "").rstrip(".") in interesting
        else m.group(0),
        text,
    )
    if not scrubbed:
        return summary
    from tqdm import tqdm
    tqdm.write(
        f"  note: {path.name}: {scrubbed} figure(s) in the summary appear "
        f"nowhere in the file; replaced with [unreadable]"
    )
    return summary.model_copy(update={"summary": new_text})


async def summarize_one(
    agent: ChatAgent[FileSummary],
    path: Path,
    source_rel: str,
    old_summary_rel: str | None,
) -> tuple[FileSummary, str]:
    """Hash, summarize, write; returns (summary, new_summary_rel_path).

    Caller decides whether to delete `old_summary_rel` after updating the manifest.
    We don't delete inside this function because a failure (API 429, etc.)
    must not leave the filesystem in a state that disagrees with the manifest.
    """
    from src.llm import JSONParseError

    digest = await asyncio.to_thread(hash_file, path)
    out_path = SUMMARIES_DIR / f"{digest}.md"
    message = await asyncio.to_thread(build_user_message, path)
    try:
        summary = await _run_with_retry(agent, message, path.name)
    except JSONParseError as e:
        # Cloud LLMs (OpenRouter Gemma especially) sometimes emit JSON
        # that even FileSummary's relaxed coercion validators can't
        # rescue. Pre-2026-05 we re-raised as SummarizeError, which
        # caused the walker to skip the file silently — meaning every
        # cloud-side parse failure dropped a real document from the
        # index. Now: write a deterministic stub summary so the file
        # still lands in the manifest and stays searchable on filename
        # / content alone (BM25 over the body, the file path, etc.).
        # The stub is intentionally honest about being a stub so a
        # future re-sync (or a switch to local Gemma) can detect and
        # replace it.
        from tqdm import tqdm
        tqdm.write(
            f"  warn: structured summary parse failed for {path.name} "
            f"({type(e).__name__}); falling back to a deterministic stub "
            f"so the file still indexes"
        )
        suffix = path.suffix.lower().lstrip(".") or "other"
        # Map known extensions to the FileSummary `ContentType` Literal
        # values; fall through to "other" for anything not in the set.
        content_type: ContentType
        if suffix in ("png", "jpg", "jpeg", "webp", "gif"):
            content_type = "image"
        elif suffix == "pdf":
            content_type = "pdf"
        elif suffix in ("docx", "doc"):
            content_type = "docx"
        elif suffix in ("xlsx", "xlsm", "xls"):
            content_type = "xlsx"
        elif suffix == "csv":
            content_type = "csv"
        elif suffix in ("md", "markdown"):
            content_type = "markdown"
        elif suffix in ("txt", "log"):
            content_type = "text"
        elif suffix in (
            "py", "js", "ts", "tsx", "jsx", "go", "rs", "java", "c", "cpp",
            "h", "hpp", "cs", "rb", "swift", "kt", "sh", "sql",
        ):
            content_type = "code"
        else:
            content_type = "other"
        summary = FileSummary(
            title=f"{path.name} (auto-stub)",
            summary=(
                f"File at {source_rel}. The structured-summary LLM call failed "
                f"to return parseable JSON; this is a deterministic stub so "
                f"the file is still indexed. Re-running sync (or switching "
                f"the indexing-time provider to local Gemma, which uses "
                f"grammar-constrained generation) should produce a real "
                f"summary."
            ),
            content_type=content_type,
            keywords=[path.name, suffix, "auto-stub"],
            key_entities=[],
            identifiers=[path.name],
        )
    summary = await asyncio.to_thread(scrub_invented_numbers, summary, path)
    # Code files get their declared symbols added to `identifiers`, which
    # `stage2.db._build_embedding_text` already folds into the embedded text
    # for both dense and BM25. Without this a code corpus is searchable only
    # by the prose the summarizer chose to write about it.
    symbols = await asyncio.to_thread(extract_code_symbols, path)
    if symbols:
        merged = list(dict.fromkeys([*summary.identifiers, *symbols]))[:MAX_SYMBOLS]
        summary = summary.model_copy(update={"identifiers": merged})
    await asyncio.to_thread(write_summary_at, out_path, summary, source_rel)

    new_summary_rel = str(out_path.relative_to(REPO_ROOT))
    if old_summary_rel and old_summary_rel != new_summary_rel:
        await asyncio.to_thread(_delete_summary_file, old_summary_rel)
    return summary, new_summary_rel


def find_supported_files(root: Path) -> list[Path]:
    """Every file under `root` this tier can summarize.

    Delegates the walk to `src.ingest.walker.find_candidates` — the same
    rules-aware walker the app and `nas explain` use — then keeps only the
    extensions this tier handles. Going through the walker rather than a bare
    `rglob` is what gets us, for free:

    * the user's `indexing_rules.json` (`exclude_globs`, `exclude_paths`) is
      actually honored here; a bare rglob ignored it, so `just sync` indexed
      files the app itself would refuse,
    * dot-folders (`.git/`, `.venv/`, `.cache/`) are pruned during traversal
      instead of being walked and then filtered file-by-file, and
    * `os.walk` skips directories it cannot read, so one unreadable folder
      no longer aborts the entire sync with `OSError: [Errno 5]`.
    """
    from src.ingest.walker import find_candidates

    files, _ignored = find_candidates(root)
    return sorted(p for p in files if p.suffix.lower() in SUPPORTED_EXTS)


async def run_batch(
    agent: ChatAgent[FileSummary],
    root: Path,
    force: bool,
    concurrency: int,
    skip_fast_tier: bool = False,
) -> None:
    from tqdm import tqdm

    # Pre-load the local model before the tqdm bar starts so the 10-20s
    # GGUF load doesn't look like "stuck on first file." Triggers the
    # weight download + load via the LocalLLM singleton; subsequent calls
    # in this process are free.
    if active_provider().name == "local":
        from src.inference import get_local_llm
        get_local_llm()._ensure_loaded()

    manifest = Manifest()
    bootstrapped = bootstrap_manifest_from_existing(manifest)
    if bootstrapped:
        print(f"bootstrapped manifest from {bootstrapped} existing summary files")
    files = find_supported_files(root)
    if skip_fast_tier:
        # Don't double-process files the fast tier already covers (PDFs ≤50p,
        # images). Routes are decided by `src.stage1_fast.router.route_file`.
        from src.stage1_fast.router import route_file
        files = [p for p in files if route_file(p) != "fast"]
    if not files:
        sys.exit(f"no supported files found under {root}")

    # Prune manifest rows whose source files no longer exist (hard delete).
    # Scoped to files under the walked `root` to avoid nuking rows for files
    # outside this run's scope.
    try:
        root_rel = str(root.resolve().relative_to(REPO_ROOT)) + os.sep
    except ValueError:
        root_rel = None
    existing_rels = {source_rel_path(p) for p in files}
    pruned = 0
    if root_rel is not None:
        for rel in list(manifest.paths()):
            if rel.startswith(root_rel) and rel not in existing_rels:
                entry = manifest.drop(rel)
                if entry:
                    _delete_summary_file(entry.summary_file)
                    pruned += 1

    skipped = 0
    errors: list[tuple[Path, str]] = []
    sem = asyncio.Semaphore(concurrency)
    manifest_lock = asyncio.Lock()
    bar = tqdm(total=len(files), desc="summarizing", unit="file")

    async def worker(path: Path) -> None:
        nonlocal skipped
        rel = source_rel_path(path)
        try:
            size = path.stat().st_size
            async with manifest_lock:
                existing = manifest.get(rel)
            if not force and existing is not None and existing.size == size:
                skipped += 1
                return

            old_summary_rel = existing.summary_file if existing else None

            # CSVs: register in manifest without LLM summarization.
            if path.suffix.lower() == ".csv":
                row_count = await asyncio.to_thread(_count_csv_rows, path)
                # Delete old summary .md if migrating from LLM-summarized CSV.
                if old_summary_rel:
                    await asyncio.to_thread(_delete_summary_file, old_summary_rel)
                async with manifest_lock:
                    manifest.mark_summarized(rel, size, summary_file=None)
                    entry = manifest.get(rel)
                    assert entry is not None
                    entry.row_count = row_count
                tqdm.write(f"  csv: {path.name} ({row_count} rows)")
                return

            async with sem:
                bar.set_postfix_str(path.name[:40])
                _, new_summary_rel = await summarize_one(agent, path, rel, old_summary_rel)

            async with manifest_lock:
                manifest.mark_summarized(rel, size, new_summary_rel)
        except SummarizeError as e:
            errors.append((path, str(e)))
            tqdm.write(f"  skip: {e}")
        except Exception as e:
            errors.append((path, f"{type(e).__name__}: {e}"))
            tqdm.write(f"  error on {path.name}: {type(e).__name__}: {e}")
        finally:
            bar.update(1)

    try:
        await asyncio.gather(*(worker(p) for p in files))
    finally:
        bar.close()
        manifest.save()

    done = len(files) - skipped - len(errors)
    print(
        f"\ndone: {done} summarized, {skipped} unchanged, "
        f"{pruned} pruned (deleted), {len(errors)} errors"
    )
    if errors:
        print("errors:")
        for p, msg in errors:
            print(f"  - {source_rel_path(p)}: {msg}")


async def run_single(agent: Agent[None, FileSummary], path: Path, force: bool) -> None:
    manifest = Manifest()
    bootstrapped = bootstrap_manifest_from_existing(manifest)
    if bootstrapped:
        print(f"bootstrapped manifest from {bootstrapped} existing summary files")
    rel = source_rel_path(path)
    size = path.stat().st_size

    existing = manifest.get(rel)
    if not force and existing is not None and existing.size == size:
        print(f"unchanged (already summarized): {existing.summary_file}")
        return

    old_summary_rel = existing.summary_file if existing else None

    # CSVs: register without LLM summarization.
    if path.suffix.lower() == ".csv":
        try:
            row_count = _count_csv_rows(path)
        except SummarizeError as e:
            sys.exit(f"error: {e}")
        if old_summary_rel:
            _delete_summary_file(old_summary_rel)
        manifest.mark_summarized(rel, size, summary_file=None)
        entry = manifest.get(rel)
        assert entry is not None
        entry.row_count = row_count
        manifest.save()
        print(f"csv registered: {rel} ({row_count} rows)")
        return

    try:
        summary, new_summary_rel = await summarize_one(agent, path, rel, old_summary_rel)
    except SummarizeError as e:
        sys.exit(f"error: {e}")
    manifest.mark_summarized(rel, size, new_summary_rel)
    manifest.save()
    print(json.dumps(summary.model_dump(), indent=2, ensure_ascii=False))
    print(f"\nwrote: {new_summary_rel}")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Summarize a local file (or directory) via Kimi.")
    parser.add_argument("path", help="File or directory to summarize.")
    parser.add_argument("--force", action="store_true",
                        help="Re-summarize every file, ignoring the manifest.")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Max files summarized in parallel during batch mode (default: 1).")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        sys.exit(f"error: no such path: {path}")

    agent = build_agent()

    if path.is_dir():
        asyncio.run(run_batch(agent, path, force=args.force, concurrency=args.concurrency))
    else:
        asyncio.run(run_single(agent, path, force=args.force))


if __name__ == "__main__":
    main()
