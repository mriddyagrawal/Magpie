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
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.content import (
    IMAGE_EXTS,
    SUPPORTED_EXTS,
    SummarizeError,
    build_content_blocks,
)
from src.llm import ChatAgent, active_provider, build_agent as _build_chat_agent
from src.manifest import Manifest


MAX_TEXT_CHARS = 120_000
PDF_VISION_MAX_PAGES = 20
HASH_CHUNK = 1 << 20  # 1 MiB

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUMMARIES_DIR = REPO_ROOT / "Test Summaries"

ContentType = Literal["image", "pdf", "docx", "xlsx", "text", "code", "markdown", "other"]


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
    "Be specific and factual. Do not invent content that is not present. If a field "
    "would be empty (e.g. `identifiers` for a code file), return an empty list — do "
    "not pad with guesses.\n\n"
    "Output RAW JSON only — do not wrap the response in markdown code fences like "
    "```json, and do not include any prose before or after the JSON object."
)


LOCAL_SYSTEM_PROMPT = """You are a file analyzer. Given a file's content, output a JSON object describing what the file is and the details someone might use to find it later via keyword search.

The JSON MUST have exactly these keys (and only these keys):
- title (string, <=80 chars)
- summary (string, 3-7 sentences of natural prose)
- content_type (one of: "image", "pdf", "docx", "xlsx", "text", "code", "markdown", "other")
- keywords (list of 3-10 topical words)
- key_entities (list of named entities: people, organisations, places, products, branches — copied verbatim from the file)
- identifiers (list of exact tokens that uniquely distinguish this file: numeric IDs, dates in their ORIGINAL format, SKUs, version strings, exact prices with currency, URLs — copied verbatim)

EXAMPLE:
Input:
Filename: flight-receipt.pdf
Content type: pdf
Delta Airlines - Flight Receipt
Passenger: Jane Doe
Flight DL1492, Atlanta ATL -> Hartford BDL, 25 May 2022
Confirmation code: ABC123
Total charged: $247.50

Output:
{"title": "Delta flight DL1492 Atlanta to Hartford - Jane Doe", "summary": "Delta Airlines flight receipt for passenger Jane Doe. Flight DL1492 from Atlanta ATL to Hartford BDL on 25 May 2022. Confirmation code ABC123. Total charged: $247.50.", "content_type": "pdf", "keywords": ["flight", "receipt", "airline", "delta", "travel"], "key_entities": ["Delta Airlines", "Jane Doe", "Atlanta ATL", "Hartford BDL"], "identifiers": ["DL1492", "25 May 2022", "ABC123", "$247.50"]}

Now analyze the file below. Return ONLY the JSON object - no markdown fences, no code blocks, no commentary. Start with { and end with }."""


def build_agent() -> ChatAgent[FileSummary]:
    # No fallback — hard-fail on parse errors so the file is skipped cleanly
    # (matches cloud behavior). The next `ns --sync` will retry it.
    # Cloud providers use PydanticAI's NativeOutput which enforces the schema
    # natively; local Gemma 3n needs a few-shot example to stay in JSON mode.
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
    SUMMARIES_DIR.mkdir(exist_ok=True)
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
    fallback = get_fallback_agent()
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
        # Re-raise as SummarizeError so worker() prints a "skip:" line and
        # leaves the manifest untouched — next sync will retry.
        raise SummarizeError(
            f"model output could not be parsed into FileSummary for {path.name}"
        ) from e
    await asyncio.to_thread(write_summary_at, out_path, summary, source_rel)

    new_summary_rel = str(out_path.relative_to(REPO_ROOT))
    if old_summary_rel and old_summary_rel != new_summary_rel:
        await asyncio.to_thread(_delete_summary_file, old_summary_rel)
    return summary, new_summary_rel


def find_supported_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SUPPORTED_EXTS
    )


async def run_batch(
    agent: ChatAgent[FileSummary],
    root: Path,
    force: bool,
    concurrency: int,
    skip_fast_tier: bool = False,
) -> None:
    from tqdm import tqdm

    # Pre-load the local model before the tqdm bar starts so the 20-30s
    # Gemma load doesn't look like "stuck on first file."
    if active_provider().name == "local":
        from src.llm import get_model
        get_model()

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
