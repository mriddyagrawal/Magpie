"""Unit tests for the manifest module (pure Python, no network)."""

from pathlib import Path

import pytest

from src.manifest import Entry, Manifest


@pytest.fixture
def tmp_manifest(tmp_path: Path) -> Manifest:
    return Manifest(path=tmp_path / "_manifest.json")


def test_new_manifest_is_empty(tmp_manifest: Manifest) -> None:
    assert tmp_manifest.entries == {}
    assert tmp_manifest.paths() == []


def test_mark_summarized_creates_entry(tmp_manifest: Manifest) -> None:
    tmp_manifest.mark_summarized("Test Content/a.pdf", size=100, summary_file="Test Summaries/a.md")
    e = tmp_manifest.get("Test Content/a.pdf")
    assert e is not None
    assert e.size == 100
    assert e.summary_file == "Test Summaries/a.md"
    assert e.ingested_at is None
    assert e.summarized_at  # iso timestamp string


def test_mark_ingested_sets_timestamp(tmp_manifest: Manifest) -> None:
    tmp_manifest.mark_summarized("a.pdf", 100, "a.md")
    tmp_manifest.mark_ingested("a.pdf")
    e = tmp_manifest.get("a.pdf")
    assert e is not None and e.ingested_at is not None


def test_mark_ingested_missing_raises(tmp_manifest: Manifest) -> None:
    with pytest.raises(KeyError):
        tmp_manifest.mark_ingested("nonexistent.pdf")


def test_needs_summarization_new_file(tmp_manifest: Manifest) -> None:
    assert tmp_manifest.needs_summarization("new.pdf", 100) is True


def test_needs_summarization_unchanged(tmp_manifest: Manifest) -> None:
    tmp_manifest.mark_summarized("a.pdf", 100, "a.md")
    assert tmp_manifest.needs_summarization("a.pdf", 100) is False


def test_needs_summarization_size_changed(tmp_manifest: Manifest) -> None:
    tmp_manifest.mark_summarized("a.pdf", 100, "a.md")
    assert tmp_manifest.needs_summarization("a.pdf", 101) is True


def test_needs_ingestion_lifecycle(tmp_manifest: Manifest) -> None:
    assert tmp_manifest.needs_ingestion("absent.pdf") is False  # not summarized
    tmp_manifest.mark_summarized("a.pdf", 100, "a.md")
    assert tmp_manifest.needs_ingestion("a.pdf") is True  # summarized, not ingested
    tmp_manifest.mark_ingested("a.pdf")
    assert tmp_manifest.needs_ingestion("a.pdf") is False


def test_resummarization_clears_ingested_at(tmp_manifest: Manifest) -> None:
    tmp_manifest.mark_summarized("a.pdf", 100, "old.md")
    tmp_manifest.mark_ingested("a.pdf")
    tmp_manifest.mark_summarized("a.pdf", 200, "new.md")  # content changed
    e = tmp_manifest.get("a.pdf")
    assert e is not None
    assert e.ingested_at is None
    assert e.summary_file == "new.md"


def test_drop_removes_entry(tmp_manifest: Manifest) -> None:
    tmp_manifest.mark_summarized("a.pdf", 100, "a.md")
    dropped = tmp_manifest.drop("a.pdf")
    assert isinstance(dropped, Entry)
    assert tmp_manifest.get("a.pdf") is None


def test_drop_missing_returns_none(tmp_manifest: Manifest) -> None:
    assert tmp_manifest.drop("absent.pdf") is None


def test_roundtrip_save_load(tmp_path: Path) -> None:
    path = tmp_path / "_manifest.json"
    m1 = Manifest(path=path)
    m1.mark_summarized("a.pdf", 100, "a.md")
    m1.mark_summarized("b.pdf", 200, "b.md")
    m1.mark_ingested("a.pdf")
    m1.save()

    m2 = Manifest(path=path)
    assert set(m2.paths()) == {"a.pdf", "b.pdf"}
    assert m2.get("a.pdf") is not None and m2.get("a.pdf").ingested_at is not None
    assert m2.get("b.pdf") is not None and m2.get("b.pdf").ingested_at is None


def test_save_is_sorted(tmp_path: Path) -> None:
    """Stable ordering of keys in the saved file — easier to diff."""
    path = tmp_path / "_manifest.json"
    m = Manifest(path=path)
    m.mark_summarized("z.pdf", 1, "z.md")
    m.mark_summarized("a.pdf", 1, "a.md")
    m.mark_summarized("m.pdf", 1, "m.md")
    m.save()

    import json
    raw = json.loads(path.read_text())
    assert list(raw.keys()) == ["a.pdf", "m.pdf", "z.pdf"]
