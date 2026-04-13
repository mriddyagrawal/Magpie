"""Tests for the summary markdown parser.

Ground truth: Test Summaries/8c2bbf673a91ef8d.md
Source: Test Content/Flight GSP - Hartford Receipt.pdf
Title: Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley
Content type: pdf
"""

from pathlib import Path

from src.stage2.parser import load_all_summaries, parse_summary_file

SUMMARIES_DIR = Path(__file__).resolve().parents[2] / "Test Summaries"
FLIGHT_SUMMARY = SUMMARIES_DIR / "8c2bbf673a91ef8d.md"


def test_parse_source_path():
    """Source path must match the Source: line exactly."""
    result = parse_summary_file(FLIGHT_SUMMARY)
    assert result.source_path == "Test Content/Flight GSP - Hartford Receipt.pdf"


def test_parse_title():
    """Title must match the markdown H1 exactly."""
    result = parse_summary_file(FLIGHT_SUMMARY)
    assert result.title == "Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley"


def test_parse_summary_text():
    """Summary must contain key facts from the document."""
    result = parse_summary_file(FLIGHT_SUMMARY)
    assert "$170.45" in result.summary
    assert "March 24, 2026" in result.summary
    assert "R2NDSL" in result.summary


def test_parse_content_type():
    """Content type must match the bold field value."""
    result = parse_summary_file(FLIGHT_SUMMARY)
    assert result.content_type == "pdf"


def test_parse_keywords():
    """Keywords must be parsed as a list, not a raw string."""
    result = parse_summary_file(FLIGHT_SUMMARY)
    assert isinstance(result.keywords, list)
    assert "Breeze Airways" in result.keywords
    assert "Greenville-Spartanburg" in result.keywords


def test_parse_key_entities():
    """Key entities must include named people and orgs."""
    result = parse_summary_file(FLIGHT_SUMMARY)
    assert isinstance(result.key_entities, list)
    entities_str = ", ".join(result.key_entities)
    assert "Mridul Agrawal" in entities_str
    assert "Rahul Ranjan Sah" in entities_str


def test_parse_summary_file_path():
    """summary_file must point back to the source .md file."""
    result = parse_summary_file(FLIGHT_SUMMARY)
    assert result.summary_file == str(FLIGHT_SUMMARY)


def test_load_all_summaries_count():
    """Number of parsed summaries must match number of .md files on disk."""
    files = sorted(SUMMARIES_DIR.glob("*.md"))
    summaries = load_all_summaries(SUMMARIES_DIR)
    assert len(summaries) == len(files)


def test_load_all_no_empty_fields():
    """Every parsed summary must have source_path, title, and summary filled."""
    summaries = load_all_summaries(SUMMARIES_DIR)
    for s in summaries:
        assert s.source_path, f"empty source_path in {s.summary_file}"
        assert s.title, f"empty title in {s.summary_file}"
        assert s.summary, f"empty summary in {s.summary_file}"
