"""Hybrid search: Kimi query rewriting + dense/sparse Qdrant retrieval."""

from __future__ import annotations

import csv
import os
import re
import sys
from dataclasses import dataclass

from pydantic import BaseModel, Field
from qdrant_client.models import (
    FieldCondition,
    Filter,
    FusionQuery,
    MatchValue,
    Prefetch,
    SparseVector,
)

from src.llm import ChatAgent, build_agent
from src.manifest import REPO_ROOT
from src.stage2.db import COLLECTION_NAME, get_qdrant_client
from src.stage2.embeddings import embed_dense_query, embed_sparse_query


# ---------------------------------------------------------------------------
# Kimi query rewriting
# ---------------------------------------------------------------------------

class SearchQuery(BaseModel):
    """Structured search query produced by Kimi from a raw user question."""

    query: str = Field(
        description="Clean, keyword-rich search string optimized for semantic embedding."
    )
    keywords: list[str] = Field(
        description="3-8 explicit keywords or entity names for exact-match boosting."
    )


# NOTE: Until Phase 2.5 step 5 lands, this prompt is duplicated in
# `server/magpie_server/prompts.py:REWRITE_PROMPT`. Edit there, not here.
# After step 5: deleted; desktop calls /llm/rewrite on cloud.
REWRITE_SYSTEM_PROMPT = (
    "You are a search-query optimizer. Given a user's natural-language question "
    "about their personal documents (invoices, receipts, notes, contracts, etc.), "
    "rewrite it into a SearchQuery: a dense `query` string that captures the full "
    "intent in keyword-rich language, and a `keywords` list of 5-12 terms — "
    "include the user's specific values verbatim (names, amounts, dates, course "
    "codes, document types) AND the likely synonyms, abbreviations, alternate "
    "vocabulary, and paraphrases the documents themselves may use for the same "
    "concept. Do not answer the question — only produce the search query. "
    "If prior conversation turns are provided, use them to resolve pronouns and "
    "references in the current question (e.g. 'what about its prerequisites?' → "
    "the subject from the previous turn). The rewrite should be self-contained: "
    "a search engine seeing only the rewritten query must have enough context. "
    "Output RAW JSON only — do not wrap the response in markdown code fences "
    "like ```json, and do not include any prose before or after the JSON object."
)


_REWRITE_FALLBACK = SearchQuery(query="", keywords=[])


_rewrite_agent: ChatAgent[SearchQuery] | None = None


def _build_rewrite_agent() -> ChatAgent[SearchQuery]:
    return build_agent(REWRITE_SYSTEM_PROMPT, SearchQuery, _REWRITE_FALLBACK)


def _build_rewrite_prompt(
    question: str,
    history: list[tuple[str, str]] | None,
) -> str:
    if not history:
        return question
    lines = ["Previous conversation turns:"]
    for i, (q, a) in enumerate(history, 1):
        lines.append(f"[Turn {i}] Q: {q}")
        lines.append(f"[Turn {i}] A: {a}")
    lines.append("")
    lines.append(f"Current question: {question}")
    return "\n".join(lines)


def rewrite_query(
    question: str,
    history: list[tuple[str, str]] | None = None,
) -> SearchQuery:
    """Send a raw user question to the LLM and get back a structured SearchQuery.

    If `history` is provided (list of (question, answer) tuples from prior turns),
    prepend it as context so the rewriter can resolve references like 'it',
    'that course', 'the same thing' to the actual subject.
    """
    global _rewrite_agent
    if _rewrite_agent is None:
        _rewrite_agent = _build_rewrite_agent()
    sq = _rewrite_agent.run_sync([_build_rewrite_prompt(question, history)])
    # Fallback tweak: if parse failed, empty `query` is unhelpful; substitute the raw question.
    if not sq.query:
        sq = SearchQuery(query=question, keywords=sq.keywords)
    return sq


async def rewrite_query_async(
    question: str,
    history: list[tuple[str, str]] | None = None,
) -> SearchQuery:
    """Async variant of rewrite_query — safe to call inside an existing event loop."""
    global _rewrite_agent
    if _rewrite_agent is None:
        _rewrite_agent = _build_rewrite_agent()
    sq = await _rewrite_agent.run([_build_rewrite_prompt(question, history)])
    if not sq.query:
        sq = SearchQuery(query=question, keywords=sq.keywords)
    return sq


# ---------------------------------------------------------------------------
# Qdrant hybrid search
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """One retrieval hit. `tier` indicates which collection contributed:
    "summary", "fast", or "both" (after RRF merge across both tiers).

    `chunk_index` is the 0-based index of a within-file chunk: the row
    number for CSV row-tier hits (set during `csv_ingest.ingest_csv_rows`);
    None for hits where the whole file is a single Qdrant point. Generic
    name so future tier types (PDF section chunks, audio segments) can
    reuse the same answer-step neighbor-lookup logic — see Plans/Future
    Plans.md and the industry convention for RAG payload metadata.
    """

    summary: str
    path: str
    score: float
    tier: str = "summary"
    chunk_index: int | None = None


CSV_NEIGHBOR_WINDOW = 2
"""How many rows above and below a CSV row hit to splice into `summary`.

A CSV hit alone is a single row stripped of context — neighbors often carry
the column headers' meaning, the running total, or the next/prev event in a
log. ±2 rows is a 5-row window: enough context for the LLM to disambiguate
without ballooning the prompt or polluting the cross-encoder rerank score."""


def _format_csv_row(row: dict[str, str]) -> str:
    """Format a row the same way `csv_ingest.stream_csv_rows` does so the
    spliced neighbors look identical to what the embedder originally saw."""
    return " | ".join(f"{k}: {v}" for k, v in row.items() if v)


_csv_rows_cache: dict[str, list[dict[str, str]] | None] = {}


def _load_csv_rows(source_rel: str) -> list[dict[str, str]] | None:
    """Read all rows of a CSV (cached). Returns None if the file is missing
    or unreadable so callers can fall back to the bare row summary."""
    if source_rel in _csv_rows_cache:
        return _csv_rows_cache[source_rel]
    path = REPO_ROOT / source_rel
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        rows = None
    _csv_rows_cache[source_rel] = rows
    return rows


def _expand_csv_hit(source_rel: str, row_idx: int, focal_summary: str) -> str:
    """Replace a single-row hit with a ±CSV_NEIGHBOR_WINDOW snippet.

    Falls back to the focal row alone if the source CSV can't be read (file
    moved, deleted, or permissions changed since ingestion)."""
    rows = _load_csv_rows(source_rel)
    if rows is None:
        return focal_summary
    start = max(0, row_idx - CSV_NEIGHBOR_WINDOW)
    end = min(len(rows), row_idx + CSV_NEIGHBOR_WINDOW + 1)
    lines: list[str] = []
    for i in range(start, end):
        marker = " (match)" if i == row_idx else ""
        text = _format_csv_row(rows[i]) if i != row_idx else focal_summary
        lines.append(f"[row {i}{marker}] {text}")
    return "\n".join(lines)


_MATCH_MARKER = "   (this row matched the question)"


def _ordered_headers(rows: list[dict[str, str]]) -> list[str]:
    """Return column headers in the order they appear in the first row.
    `csv.DictReader` preserves order on Python 3.7+ — we just take row 0."""
    if not rows:
        return []
    return list(rows[0].keys())


def _csv_row_to_csv_line(
    row: dict[str, str], headers: list[str], *, matched: bool
) -> str:
    """Render one row as a properly-quoted CSV line, optionally with the
    match-marker parenthetical appended. Uses `csv.writer` so values
    containing commas / quotes / newlines round-trip correctly."""
    import io
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="")
    writer.writerow([row.get(h, "") for h in headers])
    line = buf.getvalue()
    return line + _MATCH_MARKER if matched else line


def _csv_header_line(headers: list[str]) -> str:
    """Render the CSV header line. Same quoting semantics as data rows
    so a header containing a comma (rare) is still parseable."""
    import io
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="")
    writer.writerow(headers)
    return buf.getvalue()


def build_csv_row_window_block(
    source_rel: str,
    row_indexes: list[int],
    *,
    window: int = CSV_NEIGHBOR_WINDOW,
) -> str | None:
    """Build a multi-window CSV text block for the answer step (Plan #17 Part B).

    For each row index in `row_indexes`, expand to a ±`window` neighbor
    range. Overlapping or adjacent ranges merge into a single window so
    rows aren't duplicated in the prompt. Each window is a self-contained
    CSV snippet: header line at the top, comma-separated rows below.
    Matched rows get a trailing `(this row matched the question)` marker
    so the LLM can tell signal from context. Returns the block text or
    None if the CSV can't be read.

    Result for one CSV with 3 hits at rows [5, 6, 47] (window=2):

        coid,code,title,prerequisites
        67000,PHY-101,Introduction to Physics,
        67050,PHY-102,Physics II,PHY-101
        67053,PHY-113,General Physics III,PHY-111   (this row matched the question)
        67100,PHY-201,Mechanics,PHY-113   (this row matched the question)
        67200,PHY-301,Quantum,PHY-201
        67250,PHY-302,Relativity,PHY-201

        ---

        coid,code,title,prerequisites
        68045,ENG-244,Romantic Literature,ENG-101
        68099,ENG-254,Prison Literature,   (this row matched the question)
        68110,ENG-275,Postcolonial Voices,

    The first two hits' windows merged (3-7 ∪ 4-8 → 3-8); the third stayed
    separate. Headers repeat at the top of each window — for weak local
    models this is much easier to parse than relying on cross-block memory.

    Indexing-time row format (`csv_ingest.stream_csv_rows`) stays as
    `key: value | key: value | ...` because that's what the dense + BM25
    embedders need for column-aware semantic search. The two formats live
    on opposite sides of the wall: vector store indexing vs. answer-time
    prompt readability for weak LLMs.
    """

    rows = _load_csv_rows(source_rel)
    if rows is None or not row_indexes:
        return None
    headers = _ordered_headers(rows)
    if not headers:
        return None

    # Build per-hit windows, then merge overlapping/adjacent.
    sorted_idxs = sorted(set(row_indexes))
    raw_windows: list[tuple[int, int]] = []
    for ri in sorted_idxs:
        start = max(0, ri - window)
        end = min(len(rows), ri + window + 1)  # half-open [start, end)
        raw_windows.append((start, end))

    merged: list[tuple[int, int]] = []
    for start, end in raw_windows:
        if merged and start <= merged[-1][1]:
            # overlap or touch — extend the last window
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    match_set = set(sorted_idxs)
    header_line = _csv_header_line(headers)
    sections: list[str] = []
    for start, end in merged:
        lines: list[str] = [header_line]
        for i in range(start, end):
            lines.append(
                _csv_row_to_csv_line(rows[i], headers, matched=(i in match_set))
            )
        sections.append("\n".join(lines))

    return "\n\n---\n\n".join(sections)


def build_csv_sample_block(
    source_rel: str,
    *,
    max_rows: int = 5,
) -> str | None:
    """Build a CSV header + first-N-rows sample for the case-A answer path
    (Plan #17 Part B + 2026-05 file-level summary follow-up).

    Used when a CSV's file-level summary point is in top-k retrieval but
    none of its row points are. The user asked something the LLM summary
    matched semantically (e.g. "do we have a faculty directory?") rather
    than something a specific row matches verbatim. The sample gives the
    answer model a representative slice of the CSV's rows alongside the
    summary supplement, so it can answer "what is this file" + "what
    do its rows look like" together.

    Same raw-CSV format as `build_csv_row_window_block` (header line +
    comma-separated rows) for prompt-format consistency. No
    `(this row matched the question)` markers — none of these rows
    matched directly. Returns None if the CSV can't be read.
    """

    rows = _load_csv_rows(source_rel)
    if rows is None or not rows:
        return None
    headers = _ordered_headers(rows)
    if not headers:
        return None

    sample = rows[:max_rows]
    lines: list[str] = [_csv_header_line(headers)]
    for row in sample:
        lines.append(_csv_row_to_csv_line(row, headers, matched=False))
    return "\n".join(lines)


def _search_summary_tier(sq: SearchQuery, limit: int) -> list[SearchResult]:
    """Hybrid (dense + BM25) search of the summaries collection.

    Returns an empty list if the collection doesn't exist yet (e.g. fresh
    setup, or the user has only run --fast-only syncs).

    Asserts the configured embedding model's dim matches the collection's
    stored dim before issuing the query — if you swap the dense model
    (e.g. MiniLM-384 → E5-base-768) the index becomes incompatible, and
    silently sending a 768-d vector at a 384-d collection either errors
    cryptically or returns garbage. Fail loudly with re-index instructions.
    """
    from src.stage2.db import assert_dense_dim_match

    client = get_qdrant_client()
    if not client.collection_exists(COLLECTION_NAME):
        return []
    assert_dense_dim_match(client, COLLECTION_NAME)

    dense_text = sq.query + " " + " ".join(sq.keywords)
    dense_vec = embed_dense_query(dense_text)
    sparse_idx, sparse_val = embed_sparse_query(dense_text)

    # doc2query experiment points (hype:true) NEVER compete in the main
    # tier — measured 2026-08-26: letting them vote in the same RRF pool
    # cost recall@5 33→29 and eroded solo-gate margins (q20 6.63→0).
    # They are fetched by _search_hype_tier and blended with a reduced
    # weight in run_search (MAGPIE_HYPE_WEIGHT). No-op when no hype
    # points exist (production).
    no_hype = Filter(
        must_not=[FieldCondition(key="hype", match=MatchValue(value=True))]
    )
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=dense_vec, using="dense", limit=limit, filter=no_hype),
            Prefetch(
                query=SparseVector(indices=sparse_idx, values=sparse_val),
                using="sparse",
                limit=limit,
                filter=no_hype,
            ),
        ],
        query=FusionQuery(fusion="rrf"),
        limit=limit,
        # Payload is path + chunk index only since 2026-05; the display
        # summary is reconstructed from disk via `_summary_for_result`.
        with_payload=["source_path", "chunk_index"],
    )

    # Per-call caches: same CSV may produce multiple row hits, same
    # file-level path could appear once. Load each at most once.
    _csv_rows_cache.clear()
    _summary_md_cache.clear()

    out: list[SearchResult] = []
    for p in results.points:
        payload = p.payload or {}
        source_path = payload.get("source_path", "")
        chunk_index = payload.get("chunk_index")
        summary = _summary_for_result(source_path, chunk_index)
        out.append(
            SearchResult(
                summary=summary,
                path=source_path,
                score=p.score,
                tier="summary",
                chunk_index=chunk_index if chunk_index is None else int(chunk_index),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Display-summary reconstruction (since payload no longer carries text)
# ---------------------------------------------------------------------------

# Per-query cache for the parsed prose-summary of file-level hits. Keyed
# by source_path; reset at the top of each search call. Avoids rereading
# the same markdown when a file shows up in both dense and sparse tiers
# of the same RRF result set.
_summary_md_cache: dict[str, str] = {}


def _summary_for_result(source_path: str, chunk_index: int | None) -> str:
    """Reconstruct the search-snippet text for a Qdrant hit.

    Two paths:
      - chunk_index is set (CSV row hit) → re-read the CSV at chunk_index
        and expand to ±CSV_NEIGHBOR_WINDOW neighbors via `_expand_csv_hit`.
      - chunk_index is None (file-level hit) → load the file's summary
        markdown via the manifest, return its parsed `summary` prose.

    Returns an empty string if reconstruction fails (file moved, manifest
    out of sync, etc.) — better than raising; the UI just shows an empty
    snippet rather than crashing on a stale point.
    """

    if not source_path:
        return ""
    if chunk_index is not None:
        rows = _load_csv_rows(source_path)
        if rows is None or not (0 <= int(chunk_index) < len(rows)):
            return ""
        focal = _format_csv_row(rows[int(chunk_index)])
        return _expand_csv_hit(source_path, int(chunk_index), focal)
    return _load_summary_prose(source_path)


def _load_summary_prose(source_path: str) -> str:
    """Look up the summary markdown for a file-level hit and return its
    parsed prose summary. Cached per query.

    The lookup chain: source_path → manifest entry → summary_file → disk
    read → parse_summary_file → ParsedSummary.summary. Falls back to an
    empty string when any link breaks (manifest missing, file moved,
    parse error)."""
    if source_path in _summary_md_cache:
        return _summary_md_cache[source_path]
    text = ""
    try:
        from src.manifest import APP_DATA_DIR, Manifest
        from src.stage2.parser import parse_summary_file

        manifest = Manifest()
        entry = manifest.get(source_path)
        if entry is not None and entry.summary_file:
            md_path = APP_DATA_DIR / entry.summary_file
            if md_path.is_file():
                parsed = parse_summary_file(md_path)
                text = parsed.summary or parsed.title or ""
    except Exception:  # pylint: disable=broad-except
        text = ""
    _summary_md_cache[source_path] = text
    return text


def _search_fast_tier(query_text: str, limit: int) -> list[SearchResult]:
    """ColPali MaxSim search of the fast_tier collection, deduped to one
    result per file (best-matching page wins).

    Returns an empty list if the collection doesn't exist or the fast-tier
    model can't be loaded (e.g. in CI or on a machine without colpali-engine).
    """
    from src.stage2.fast_db import FAST_COLLECTION_NAME

    client = get_qdrant_client()
    if not client.collection_exists(FAST_COLLECTION_NAME):
        return []

    try:
        from src.stage1_fast.model import encode_queries
        from src.stage2.fast_db import search as fast_search
    except ImportError:
        return []

    try:
        q_tensor = encode_queries([query_text])
        q_vecs = q_tensor[0].float().cpu().tolist()
    except Exception:  # pylint: disable=broad-except
        # Model load failure (no GPU, missing weights, etc.) — fall through.
        return []

    hits = fast_search(q_vecs, limit=limit)

    # A single file can have multiple matching pages. Collapse to best page.
    best_by_path: dict[str, tuple[int, float]] = {}
    for path, page, score in hits:
        prev = best_by_path.get(path)
        if prev is None or score > prev[1]:
            best_by_path[path] = (page, score)

    return [
        SearchResult(
            summary=f"(visual match — page {page})",
            path=path,
            score=score,
            tier="fast",
        )
        for path, (page, score) in sorted(
            best_by_path.items(), key=lambda kv: kv[1][1], reverse=True
        )
    ]


RRF_K = 60  # standard RRF constant; higher = flatter fusion curve


def _rerank_enabled() -> bool:
    """Global kill-switch for the cross-encoder rerank stage.

    `MAGPIE_RERANK=0` disables reranking everywhere, regardless of what a
    caller passes for `rerank=` — results come back in RRF-fusion order.
    Anything else (unset, "1", garbage) leaves reranking caller-controlled,
    so the default behavior is exactly what it was before the switch.

    The solo gate (`gate_to_solo`) also checks this: its margin threshold is
    calibrated to cross-encoder score scale, so with reranking off the gate
    is structurally off too — see the comment there.
    """
    return os.environ.get("MAGPIE_RERANK", "1").strip() != "0"


def _hit_key(r: SearchResult) -> tuple[str, int | None]:
    """Dedup key for RRF fusion. Composite to handle within-file chunks.

    For non-chunked points (PDF/DOCX/IMAGE summary points, fast_tier page
    points) `chunk_index is None`, so the key collapses to `(path, None)`
    — the legacy file-level dedup behavior survives unchanged.

    For CSV row points (and future PDF/audio chunked points), each chunk
    of the same file is a distinct key. CRITICAL: without this, a query
    that matches multiple rows of the same CSV would silently lose all
    but the last row's `chunk_index` after RRF — see the 2026-05 audit;
    this was a real correctness bug.
    """
    return (r.path, r.chunk_index)


def _rrf_merge(
    summary_hits: list[SearchResult],
    fast_hits: list[SearchResult],
    top_k: int,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion of two result lists, keyed by
    `(source_path, chunk_index)`.

    Each key's RRF score is the sum over each list of `1 / (RRF_K + rank)`
    where rank is 1-indexed. Missing from a list contributes 0. The kept
    SearchResult prefers the summary-tier entry (it has a real summary)
    when a key appears in both lists.

    The composite key matters for CSV row points and future chunked
    types: a 5-row hit on `tax_2025.csv` produces 5 distinct keys
    `(tax_2025.csv, 0..4)` instead of one collapsed key `(tax_2025.csv,)`,
    so all matched rows reach the answer step.
    """
    scores: dict[tuple[str, int | None], float] = {}
    chosen: dict[tuple[str, int | None], SearchResult] = {}
    seen_in: dict[tuple[str, int | None], set[str]] = {}

    for rank, r in enumerate(summary_hits, start=1):
        if not r.path:
            continue
        key = _hit_key(r)
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
        chosen[key] = r  # summary-tier entries have human-readable summaries
        seen_in.setdefault(key, set()).add("summary")

    for rank, r in enumerate(fast_hits, start=1):
        if not r.path:
            continue
        key = _hit_key(r)
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
        chosen.setdefault(key, r)  # only fill if summary didn't already
        seen_in.setdefault(key, set()).add("fast")

    ordered = sorted(chosen.values(), key=lambda r: scores[_hit_key(r)], reverse=True)
    # Overwrite each result's score with its RRF score so callers see fused ranking.
    for r in ordered:
        key = _hit_key(r)
        r.score = scores[key]
        tiers = seen_in.get(key, set())
        r.tier = "both" if len(tiers) == 2 else next(iter(tiers), r.tier)
    return ordered[:top_k]


RERANK_OVERSAMPLE = 2
RERANK_MIN_CANDIDATES = 10
"""When reranking, how many RRF-fused candidates to feed the cross-encoder.

`fetch_k = max(RERANK_MIN_CANDIDATES, top_k * RERANK_OVERSAMPLE)`. The floor
matters for the common `top_k=5` case: 5×2=10 satisfies the floor exactly,
giving the cross-encoder real options to reorder without paying the cost of
50+ pairs. The user's framing was "always pull at least 10 files, rerank
down to top 5". Per-pair cost on the default ms-marco-MiniLM-L-6-v2 is
~50-100 ms on CPU, batched in one `predict()` call, so 10 pairs is
~200-400 ms total — well under the answer-step's multi-second LLM cost."""


def _search_hype_tier(sq: SearchQuery, limit: int) -> list[SearchResult]:
    """Hybrid search restricted to doc2query question points (hype:true).

    Experiment tier (2026-08-26): only queried when MAGPIE_HYPE_WEIGHT
    is set > 0. Empty list when the collection has no hype points.
    """
    client = get_qdrant_client()
    if not client.collection_exists(COLLECTION_NAME):
        return []
    dense_text = sq.query + " " + " ".join(sq.keywords)
    dense_vec = embed_dense_query(dense_text)
    sparse_idx, sparse_val = embed_sparse_query(dense_text)
    only_hype = Filter(
        must=[FieldCondition(key="hype", match=MatchValue(value=True))]
    )
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=dense_vec, using="dense", limit=limit, filter=only_hype),
            Prefetch(
                query=SparseVector(indices=sparse_idx, values=sparse_val),
                using="sparse",
                limit=limit,
                filter=only_hype,
            ),
        ],
        query=FusionQuery(fusion="rrf"),
        limit=limit,
        with_payload=["source_path"],
    )
    out: list[SearchResult] = []
    for p in results.points:
        payload = p.payload or {}
        source_path = payload.get("source_path", "")
        out.append(SearchResult(
            summary=_summary_for_result(source_path, None),
            path=source_path,
            score=p.score,
            tier="summary",
            chunk_index=None,
        ))
    return out


def _blend_hype(
    fused: list[SearchResult],
    hype_hits: list[SearchResult],
    weight: float,
    limit: int,
) -> list[SearchResult]:
    """Blend doc2query question hits into the fused pool as a NOMINATING
    tier: each file's best hype rank contributes `weight / (RRF_K + rank)`
    — added to the file's existing fused score, or introducing the file
    with just that bonus if the main tiers missed it entirely. With
    weight < 1 a hype hit can surface a candidate but cannot outvote a
    summary consensus. Best-rank-only per file so a file with many
    generated questions is not over-boosted."""
    best_rank: dict[str, int] = {}
    for rank, h in enumerate(hype_hits):
        if h.path not in best_rank:
            best_rank[h.path] = rank
    seen_paths: set[str] = set()
    out = list(fused)
    for r in out:
        if r.path in best_rank and r.path not in seen_paths:
            r.score += weight / (RRF_K + best_rank[r.path])
            seen_paths.add(r.path)
    for h in hype_hits:
        if h.path in seen_paths or h.path not in best_rank:
            continue
        seen_paths.add(h.path)
        h.score = weight / (RRF_K + best_rank[h.path])
        out.append(h)
    out.sort(key=lambda r: r.score, reverse=True)
    return out[:limit]


def run_search(
    sq: SearchQuery,
    top_k: int = 5,
    *,
    question: str | None = None,
    rerank: bool = False,
    skip_fast: bool = False,
    enumerate_lists: bool = True,
) -> list[SearchResult]:
    """Run hybrid search across both the summary and fast-tier collections.

    Each tier returns its top `top_k * 2` candidates; results are merged via
    Reciprocal Rank Fusion keyed on `source_path`. Either tier being empty
    (missing collection, disabled, etc.) is tolerated — the other tier's
    results pass through unchanged.

    Adaptive routing: if `question` is provided, the raw user text is
    classified (list/enumeration vs general) and the per-class top_k can
    override the caller's default. The caller's `top_k` still wins if it's
    larger — explicit user override (e.g. `.top-k 50` in the REPL) is
    respected. See `src.stage2.query_classify`.

    Optional cross-encoder rerank (`rerank=True`): pulls `top_k *
    RERANK_OVERSAMPLE` RRF-fused candidates, scores each `(question, doc)`
    pair with a small cross-encoder model, then returns the top-k by that
    score. Default off because cross-encoders occasionally regress factoid
    queries (rememex postmortem). Enable in the REPL with `.rerank on`.
    `MAGPIE_RERANK=0` is a global kill-switch that overrides any caller's
    `rerank=True` — see `_rerank_enabled`. See `src.stage2.rerank`.
    """
    from src.stage2.query_classify import QueryClass, classify_and_config

    if rerank and not _rerank_enabled():
        rerank = False

    if question is not None and enumerate_lists:
        klass, cfg = classify_and_config(question)
        # Adaptive routing only **widens** top_k, never narrows. We bump the
        # caller's value only when (a) the class is one with a real
        # widening preference and (b) the class wants more than the caller
        # asked for. Explicit small caller values (e.g. tests passing
        # top_k=3) and explicit large caller values (e.g. `.top-k 50` in the
        # REPL) are both respected — the classifier just helps the default
        # case where caller didn't customize.
        if klass is QueryClass.LIST_ALL and cfg.top_k > top_k:
            widened = cfg.top_k
            # The local backend still gets a narrower fan-out than cloud, but
            # the old cap of 8 was sized for Gemma 4 E4B at an 8K default
            # context: 30 paths × ~29 KB/file is ~870 KB and blew straight
            # past it. LFM2.5-VL-3B declares a 128K context and we open 16K
            # of it (see DEFAULT_N_CTX), so 8 was leaving real recall on the
            # table for enumeration queries.
            #
            # 12 rather than the full 30: the ceiling here is no longer the
            # context window but the model's ability to actually use it.
            # Liquid explicitly does not recommend LFM2.5-VL for
            # long-context, reasoning-heavy work, and a 3B model degrades on
            # wide multi-document synthesis well before it runs out of
            # tokens. Treat this as a starting point to benchmark, not a
            # derived constant — raise it with eval numbers, not vibes.
            from src.llm import active_provider
            if active_provider().name == "local":
                local_cap = int(os.environ.get("LOCAL_MAX_TOP_K", "12"))
                if widened > local_cap:
                    print(
                        f"  query_class={klass.value}  top_k {top_k}→{local_cap}  "
                        f"(local backend cap; cfg wanted {widened})"
                    )
                    top_k = local_cap
                else:
                    print(
                        f"  query_class={klass.value}  top_k {top_k}→{widened}  "
                        f"({cfg.notes})"
                    )
                    top_k = widened
            else:
                print(
                    f"  query_class={klass.value}  top_k {top_k}→{widened}  "
                    f"({cfg.notes})"
                )
                top_k = widened

        # Cross-encoder rerank regresses LIST_ALL queries — proper-noun /
        # receipt / enumeration lookups. The cross-encoder over-weights
        # rich semantic prose (e.g. project context docs) against terse
        # receipt-style summaries, pushing the actually-relevant files out
        # of the top-K. Auto-disable rerank for this class even when the
        # caller toggled it on. Empirically validated 2026-04-25:
        # "find me all my uber/lodging receipts" with rerank=on → 0 receipts
        # in top-20; same query with rerank=off → 11 receipts in top-20.
        # GENERAL queries (Hamiltonian, music 101, Romantic era) keep rerank.
        if rerank and klass is QueryClass.LIST_ALL:
            print(
                f"  query_class={klass.value}  rerank suppressed "
                f"(cross-encoder regresses list/enumeration queries)"
            )
            rerank = False

    # If reranking, fetch a wider RRF-fused candidate pool so the cross-encoder
    # has real options to reorder. Otherwise stick with the original top_k.
    fetch_k = max(RERANK_MIN_CANDIDATES, top_k * RERANK_OVERSAMPLE) if rerank else top_k

    summary_hits = _search_summary_tier(sq, fetch_k * 2)
    # Feed the raw dense-query text (same as summary tier) to ColPali; it
    # handles multi-token query encoding internally.
    # When `skip_fast=True`, bypass ColPali entirely — saves the ~30s first-
    # query model load and ~1s/query encode for sessions that only need text
    # retrieval. The REPL exposes this via `.fast on/off`.
    if skip_fast:
        fast_hits: list[SearchResult] = []
    else:
        query_text = (sq.query + " " + " ".join(sq.keywords)).strip()
        fast_hits = _search_fast_tier(query_text, fetch_k * 2)
    fused = _rrf_merge(summary_hits, fast_hits, fetch_k)

    # doc2query experiment (2026-08-26): question points blend in as a
    # nominating tier — but ONLY when the cross-encoder will re-judge the
    # pool (rerank on). Measured same day: with rerank suppressed
    # (list_all queries) any hype bonus reorders the FINAL ranking
    # unchecked and displaced key files (recall@5 33→31 at weight 0.4);
    # with rerank on, a nominated file still has to win the cross-encoder
    # on its own summary, so nomination is safe at full weight. Off
    # unless MAGPIE_HYPE_WEIGHT is set AND hype points exist.
    hype_weight = float(os.environ.get("MAGPIE_HYPE_WEIGHT", "0") or 0)
    if hype_weight > 0 and rerank:
        hype_hits = _search_hype_tier(sq, fetch_k * 2)
        if hype_hits:
            fused = _blend_hype(fused, hype_hits, hype_weight, fetch_k)

    if rerank and len(fused) > 1:
        from src.stage2.rerank import rerank as cross_encoder_rerank
        # Use the raw user question for reranking when available — it
        # carries the user's actual intent, where the LLM rewrite is
        # paraphrased. Fall back to the rewritten query for non-question
        # callers (programmatic use without `question=`).
        rerank_text = question if question is not None else sq.query
        return cross_encoder_rerank(rerank_text, fused, top_k)

    return fused[:top_k]


# Comparison-shaped questions need MULTIPLE files by definition — solo-gating
# one away breaks them (observed 2026-08-24: the Rochester-vs-Swarthmore
# question got only the Rochester file and honestly answered half). Mirror of
# answer.py's SYNTHESIS MODE detector; keep the two in sync.
_COMPARATIVE_Q_RE = re.compile(
    r"\b(compare|versus|vs\.?|difference between|connects?|links?|"
    r"in common|both .{0,40}\b(essays?|files?|documents?|letters?)|"
    r"same (file|document|content)|are (these|those|they) .{0,20}same)\b",
    re.IGNORECASE,
)


def gate_to_solo(
    retrieved: list[SearchResult], question: str | None = None
) -> list[SearchResult]:
    """Adaptive context gating (2026-08-24): when the top hit's rerank score
    DOMINATES #2 by a margin, hand the answer stage that file ALONE.

    Why: the reading-isolation ladder showed the local 3B model answers
    near-perfectly from a single correct file and collapses to ~13% with 4
    distractors stacked around it. A replay of 121 saved retrieval traces
    showed the top hit is the right file only 45% of the time overall — but
    93% of the time when its margin over #2 is >= 2.0 (fires on ~24% of
    questions). So: confident retrieval -> solo file -> ladder conditions;
    uncertain retrieval -> unchanged multi-file behavior.

    Local provider only — cloud's 26B reads through distractor stacks fine
    (47% strict with the crowd) and loses enumeration coverage if starved.
    Tune/disable via LOCAL_SOLO_MARGIN (0 disables). Also structurally off
    when reranking is disabled (`MAGPIE_RERANK=0`) — see below.
    """
    if len(retrieved) < 2:
        return retrieved
    if question is not None and _COMPARATIVE_Q_RE.search(question):
        return retrieved
    # The margin below is a CROSS-ENCODER score margin. With the rerank
    # stage killed (MAGPIE_RERANK=0), `score` holds RRF-fusion values on a
    # ~1/RRF_K scale where the default 2.0 threshold can never fire — so
    # treat the gate as explicitly off rather than let it silently never
    # fire against the wrong scale.
    if not _rerank_enabled():
        return retrieved
    try:
        from src.llm import active_provider

        if active_provider().name != "local":
            return retrieved
    except Exception:  # noqa: BLE001 — gating must never sink a query
        return retrieved
    try:
        threshold = float(os.environ.get("LOCAL_SOLO_MARGIN", "2.0"))
    except ValueError:
        threshold = 2.0
    if threshold <= 0:
        return retrieved
    margin = float(retrieved[0].score) - float(retrieved[1].score)
    if margin >= threshold:
        print(
            f"  solo-gate: top hit dominates (margin {margin:.2f} >= "
            f"{threshold}) — sending 1 file instead of {len(retrieved)}",
            file=sys.stderr,
        )
        return retrieved[:1]
    return retrieved


def raw_query(question: str) -> SearchQuery:
    """Build a SearchQuery from the raw user question, skipping the Kimi rewrite.

    Useful when rewrite latency dominates and the raw question is already
    keyword-rich. Pair with the Future-Plans item on asymmetric search /
    HyDE when quality regresses on vague queries.
    """
    return SearchQuery(query=question, keywords=[])


def search_summaries(
    question: str,
    top_k: int = 5,
    *,
    rewrite: bool = True,
) -> list[SearchResult]:
    """Retrieve top-k summaries from Qdrant for a user question.

    If `rewrite` is True (default): Kimi expands the question into a dense
    keyword-rich query + explicit keyword list, then hybrid search.
    If False: the raw question goes directly to the embedders. Saves ~20s
    (one LLM round-trip) per call but may hurt recall on short / vague queries.

    Returns up to top_k results ranked by Reciprocal Rank Fusion of dense
    (semantic) and sparse (BM25) scores.

    Passes the raw `question` through to `run_search` so the adaptive
    classifier can widen top_k for enumeration-shaped queries.
    """
    sq = rewrite_query(question) if rewrite else raw_query(question)
    return run_search(sq, top_k, question=question)
