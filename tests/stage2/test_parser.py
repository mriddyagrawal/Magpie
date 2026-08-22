"""Tests for the summary markdown parser.

These tests used to rely on a specific committed fixture
(`Test Summaries/8c2bbf673a91ef8d.md`) as ground truth. That coupled test
outcomes to arbitrary repo state and broke every time summaries were
regenerated or pruned.

Now we synthesize a Breeze-Airways-shaped summary into `tmp_path` per test —
the same *shape* real Stage-1 output produces — so coverage is unchanged
but tests are hermetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.stage2.parser import load_all_summaries, parse_summary_file


FLIGHT_SUMMARY_BODY = (
    "Source: Test Content/Flight GSP - Hartford Receipt.pdf\n\n"
    "# Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley\n\n"
    "This receipt documents a $170.45 USD flight booking transaction on "
    "March 24, 2026 for passengers Mridul Agrawal and Rahul Ranjan Sah, "
    "confirmation code X7QK2M.\n\n"
    "**Content type:** pdf\n\n"
    "**Keywords:** Breeze Airways, Greenville-Spartanburg, Flight Receipt\n\n"
    "**Key entities:** Mridul Agrawal, Rahul Ranjan Sah\n\n"
    "**Identifiers:** X7QK2M, $170.45, March 24 2026\n"
)


@pytest.fixture
def flight_summary(tmp_path: Path) -> Path:
    p = tmp_path / "8c2bbf673a91ef8d.md"
    p.write_text(FLIGHT_SUMMARY_BODY, encoding="utf-8")
    return p


def test_parse_source_path(flight_summary: Path):
    """Source path must match the Source: line exactly."""
    result = parse_summary_file(flight_summary)
    assert result.source_path == "Test Content/Flight GSP - Hartford Receipt.pdf"


def test_parse_title(flight_summary: Path):
    """Title must match the markdown H1 exactly."""
    result = parse_summary_file(flight_summary)
    assert result.title == "Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley"


def test_parse_summary_text(flight_summary: Path):
    """Summary must contain key facts from the document."""
    result = parse_summary_file(flight_summary)
    assert "$170.45" in result.summary
    assert "March 24, 2026" in result.summary
    assert "X7QK2M" in result.summary


def test_parse_content_type(flight_summary: Path):
    """Content type must match the bold field value."""
    result = parse_summary_file(flight_summary)
    assert result.content_type == "pdf"


def test_parse_keywords(flight_summary: Path):
    """Keywords must be parsed as a list, not a raw string."""
    result = parse_summary_file(flight_summary)
    assert isinstance(result.keywords, list)
    assert "Breeze Airways" in result.keywords
    assert "Greenville-Spartanburg" in result.keywords


def test_parse_key_entities(flight_summary: Path):
    """Key entities must include named people and orgs."""
    result = parse_summary_file(flight_summary)
    assert isinstance(result.key_entities, list)
    entities_str = ", ".join(result.key_entities)
    assert "Mridul Agrawal" in entities_str
    assert "Rahul Ranjan Sah" in entities_str


def test_parse_summary_file_path(flight_summary: Path):
    """summary_file must point back to the source .md file."""
    result = parse_summary_file(flight_summary)
    assert result.summary_file == str(flight_summary)


def test_load_all_summaries_count(tmp_path: Path):
    """`load_all_summaries` must parse every .md file in the directory."""
    for i in range(3):
        (tmp_path / f"sample{i}.md").write_text(
            FLIGHT_SUMMARY_BODY, encoding="utf-8"
        )
    summaries = load_all_summaries(tmp_path)
    assert len(summaries) == 3


def test_load_all_no_empty_fields(tmp_path: Path):
    """Every parsed summary must have source_path, title, and summary filled."""
    (tmp_path / "x.md").write_text(FLIGHT_SUMMARY_BODY, encoding="utf-8")
    summaries = load_all_summaries(tmp_path)
    for s in summaries:
        assert s.source_path, f"empty source_path in {s.summary_file}"
        assert s.title, f"empty title in {s.summary_file}"
        assert s.summary, f"empty summary in {s.summary_file}"
