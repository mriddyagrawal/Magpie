"""Ripgrep helper for T0 files — on-demand lookup when the index couldn't embed the whole file.

At answer time, `src/answer.py` checks each retrieved file's manifest entry.
If it's a T0 file (huge text/log/CSV we deliberately did not embed), we run
ripgrep against the user's question to surface the most likely relevant
lines, and prepend those hits to the content blocks handed to the LLM.

This complements semantic retrieval — retrieval finds the *file*, ripgrep
finds the *lines*. Works especially well for "how much did I pay on May 4"
style queries against a big transaction CSV.

`ripgrep` is assumed available on PATH; we fall back to a pure-Python line
scan if it isn't, so nothing breaks on systems without rg installed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.subproc import no_window_kwargs


RIPGREP_DEFAULT_MAX_HITS = 30
RIPGREP_BIN = shutil.which("rg")


@dataclass(frozen=True)
class RipgrepHit:
    line_number: int
    text: str


def _tokens_for_pattern(question: str) -> list[str]:
    """Pull simple word/number tokens out of a natural-language question.

    We want ripgrep to match on substantive tokens — dates, amounts, names —
    not noise words. Tokens are kept verbatim so exact-match searches (e.g.
    invoice number R2NDSL) still work.
    """
    # Word-boundary tokens: letters / digits / slashes / dashes / dots / dollar
    tokens = re.findall(r"[\w$/.-]+", question)
    # Stopword set is deliberately narrow — we must NOT drop modal verbs like
    # "may" / "can" because they collide with real nouns (the month May, a can
    # of soup). Only drop words that are unambiguously noise.
    stop = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "of", "in", "on", "at", "to", "for", "with", "by", "from",
        "that", "this", "these", "those", "and", "or", "not",
        "what", "when", "where", "why", "how", "who", "which",
        "do", "does", "did", "have", "has", "had",
        "it", "its",
    }
    return [t for t in tokens if t.lower() not in stop and len(t) >= 2]


def _build_pattern(question: str) -> str | None:
    """Build a ripgrep-friendly OR-pattern from the question's tokens."""
    tokens = _tokens_for_pattern(question)
    if not tokens:
        return None
    # Escape regex metacharacters so tokens are matched literally.
    escaped = [re.escape(t) for t in tokens]
    return "|".join(escaped)


def _rg_hits(path: Path, pattern: str, max_hits: int) -> list[RipgrepHit]:
    """Invoke the ripgrep binary; return parsed (line_number, text) hits."""
    try:
        out = subprocess.run(
            [
                RIPGREP_BIN, "--line-number", "--no-heading", "--color=never",
                "--max-count", str(max_hits),
                pattern, str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            # Windows: suppress the flashing console window on this probe.
            **no_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if out.returncode not in (0, 1):  # 1 == no matches
        return []

    hits: list[RipgrepHit] = []
    for line in out.stdout.splitlines()[:max_hits]:
        # format: "NNN:line content"
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        try:
            ln = int(parts[0])
        except ValueError:
            continue
        hits.append(RipgrepHit(line_number=ln, text=parts[1]))
    return hits


def _python_fallback_hits(path: Path, pattern: str, max_hits: int) -> list[RipgrepHit]:
    """Pure-Python line scan, used when the ripgrep binary isn't on PATH."""
    try:
        regex = re.compile(pattern)
    except re.error:
        return []
    hits: list[RipgrepHit] = []
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, start=1):
                if regex.search(line):
                    hits.append(RipgrepHit(line_number=i, text=line.rstrip("\n")))
                    if len(hits) >= max_hits:
                        break
    except OSError:
        return []
    return hits


def search_file(
    path: Path,
    question: str,
    *,
    max_hits: int = RIPGREP_DEFAULT_MAX_HITS,
) -> list[RipgrepHit]:
    """Return up to `max_hits` lines from `path` matching tokens in `question`.

    Empty list on any failure or when no tokens could be extracted.
    """
    pattern = _build_pattern(question)
    if pattern is None:
        return []
    if RIPGREP_BIN:
        hits = _rg_hits(path, pattern, max_hits)
        if hits:
            return hits
        # If ripgrep ran but returned nothing, skip the fallback — empty is truthful.
        return []
    return _python_fallback_hits(path, pattern, max_hits)


def format_hits_block(path: Path, hits: list[RipgrepHit]) -> str:
    """Render hits as a plain-text content block for the LLM prompt."""
    if not hits:
        return ""
    lines = [f"Ripgrep hits from {path.name} (line: content):"]
    for h in hits:
        lines.append(f"  {h.line_number}: {h.text.strip()}")
    return "\n".join(lines)
