"""Parse summary markdown files produced by summarize.py into structured objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedSummary:
    source_path: str
    title: str
    summary: str
    content_type: str
    keywords: list[str] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    summary_file: str = ""


def _extract_bold_field(text: str, label: str) -> str:
    pattern = rf"\*\*{re.escape(label)}:\*\*\s*(.+)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _split_comma_list(value: str) -> list[str]:
    if not value or value == "—":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_summary_file(path: Path) -> ParsedSummary:
    """Parse a single summary markdown file into a ParsedSummary."""
    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")

    source_path = ""
    if lines and lines[0].startswith("Source:"):
        source_path = lines[0].removeprefix("Source:").strip()

    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line.removeprefix("# ").strip()
            break

    summary_lines: list[str] = []
    in_summary = False
    for line in lines:
        if line.startswith("# "):
            in_summary = True
            continue
        if in_summary:
            if line.startswith("**"):
                break
            stripped = line.strip()
            if stripped:
                summary_lines.append(stripped)
    summary = " ".join(summary_lines)

    content_type = _extract_bold_field(text, "Content type")
    keywords = _split_comma_list(_extract_bold_field(text, "Keywords"))
    key_entities = _split_comma_list(_extract_bold_field(text, "Key entities"))
    identifiers = _split_comma_list(_extract_bold_field(text, "Identifiers"))

    return ParsedSummary(
        source_path=source_path,
        title=title,
        summary=summary,
        content_type=content_type,
        keywords=keywords,
        key_entities=key_entities,
        identifiers=identifiers,
        summary_file=str(path),
    )


def load_all_summaries(summaries_dir: Path) -> list[ParsedSummary]:
    """Load and parse all .md files from the summaries directory."""
    if not summaries_dir.is_dir():
        raise FileNotFoundError(f"summaries directory not found: {summaries_dir}")
    files = sorted(summaries_dir.glob("*.md"))
    return [parse_summary_file(f) for f in files]
