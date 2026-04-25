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


# ---------------------------------------------------------------------------
# clean_stale — drop entries whose source files no longer exist
# ---------------------------------------------------------------------------

def test_clean_stale_drops_nonexistent_files(tmp_path: Path) -> None:
    """Manifest entries pointing to gone files should be dropped."""
    manifest_path = tmp_path / "_manifest.json"
    m = Manifest(path=manifest_path)

    # Real file on disk
    real = tmp_path / "real.txt"
    real.write_text("hello", encoding="utf-8")
    m.mark_summarized(str(real), size=5, summary_file=None)

    # Fake (path that doesn't exist)
    m.mark_summarized("/tmp/pytest-of-fake/never-existed/foo.txt", size=10, summary_file=None)

    stats = m.clean_stale()
    assert stats == {"dropped": 1, "summaries_removed": 0}
    assert str(real) in m.paths()
    assert "/tmp/pytest-of-fake/never-existed/foo.txt" not in m.paths()


def test_clean_stale_deletes_orphaned_summary_markdown(tmp_path: Path) -> None:
    """When a stale entry has a summary_file, the markdown is also removed."""
    manifest_path = tmp_path / "_manifest.json"
    summary_dir = tmp_path / "summaries"
    summary_dir.mkdir()
    summary_md = summary_dir / "abc123.md"
    summary_md.write_text("# old summary", encoding="utf-8")

    # Patch REPO_ROOT so the relative summary_file resolves under tmp_path.
    import src.manifest as manifest_mod
    original_root = manifest_mod.REPO_ROOT
    manifest_mod.REPO_ROOT = tmp_path
    try:
        m = Manifest(path=manifest_path)
        # Source file gone, summary file present
        m.mark_summarized(
            "/nonexistent/source.pdf",
            size=100,
            summary_file=str(summary_md.relative_to(tmp_path)),
        )
        stats = m.clean_stale()
    finally:
        manifest_mod.REPO_ROOT = original_root

    assert stats == {"dropped": 1, "summaries_removed": 1}
    assert not summary_md.exists()


def test_clean_stale_handles_repo_relative_paths(tmp_path: Path) -> None:
    """Manifest keys without a leading slash are treated as REPO_ROOT-relative."""
    manifest_path = tmp_path / "_manifest.json"
    real_subdir = tmp_path / "kept"
    real_subdir.mkdir()
    real_file = real_subdir / "doc.txt"
    real_file.write_text("here", encoding="utf-8")

    import src.manifest as manifest_mod
    original_root = manifest_mod.REPO_ROOT
    manifest_mod.REPO_ROOT = tmp_path
    try:
        m = Manifest(path=manifest_path)
        m.mark_summarized("kept/doc.txt", size=4, summary_file=None)       # exists under REPO_ROOT
        m.mark_summarized("vanished/doc.txt", size=4, summary_file=None)   # does NOT
        stats = m.clean_stale()
    finally:
        manifest_mod.REPO_ROOT = original_root

    assert stats == {"dropped": 1, "summaries_removed": 0}
    assert "kept/doc.txt" in m.paths()
    assert "vanished/doc.txt" not in m.paths()


def test_clean_stale_noop_when_all_files_present(tmp_path: Path) -> None:
    """No-op when every manifest entry's source still exists."""
    manifest_path = tmp_path / "_manifest.json"
    f1 = tmp_path / "a.txt"; f1.write_text("a", encoding="utf-8")
    f2 = tmp_path / "b.txt"; f2.write_text("b", encoding="utf-8")
    m = Manifest(path=manifest_path)
    m.mark_summarized(str(f1), 1, None)
    m.mark_summarized(str(f2), 1, None)

    stats = m.clean_stale()
    assert stats == {"dropped": 0, "summaries_removed": 0}
    assert len(m.paths()) == 2


# ---------------------------------------------------------------------------
# mark_summarized must NOT wipe fast-tier or router fields (regression test)
# ---------------------------------------------------------------------------

def test_mark_summarized_preserves_fast_tier_state(tmp_manifest: Manifest) -> None:
    """A prior T4 ingest's fast_indexed_at + fast_pages must survive re-summarization.

    The pre-2026-04-25 bug replaced the whole Entry on every mark_summarized,
    silently zeroing out fast_indexed_at. Vectors stayed in Qdrant but the
    manifest forgot — re-ingests then re-encoded unnecessarily.
    """
    # First: file gets T4-indexed
    tmp_manifest.mark_fast_indexed("textbook.pdf", size=5_000_000, pages=42)
    assert tmp_manifest.get("textbook.pdf").fast_indexed_at is not None
    assert tmp_manifest.get("textbook.pdf").fast_pages == 42

    # Then: same file goes through summarization (T2 / T3)
    tmp_manifest.mark_summarized("textbook.pdf", size=5_000_000, summary_file="summaries/x.md")

    e = tmp_manifest.get("textbook.pdf")
    # Fast-tier state PRESERVED
    assert e.fast_indexed_at is not None, "fast_indexed_at was wiped — regression"
    assert e.fast_pages == 42, "fast_pages was wiped — regression"
    # Summary state SET
    assert e.summary_file == "summaries/x.md"
    assert e.summarized_at != ""
    assert e.ingested_at is None  # cleared so stage 2 re-ingests


def test_mark_summarized_preserves_router_audit(tmp_manifest: Manifest) -> None:
    """Router audit fields (routes, scores, criticality) survive re-summarization."""
    tmp_manifest.mark_routed(
        "doc.pdf",
        size=1000,
        routes=["T3", "T4"],
        visual_score=7,
        sensitivity_score=4,
        t4_cost_mb=12.3,
        t4_cost_s=15.0,
        criticality="critical",
        criticality_source="auto",
        skip_reason=None,
    )
    tmp_manifest.mark_summarized("doc.pdf", size=1000, summary_file="x.md")
    e = tmp_manifest.get("doc.pdf")
    assert e.routes == ["T3", "T4"]
    assert e.visual_score == 7
    assert e.criticality == "critical"
    assert e.criticality_source == "auto"


def test_mark_summarized_creates_entry_if_absent(tmp_manifest: Manifest) -> None:
    """Calling mark_summarized on a never-seen path still creates the row."""
    tmp_manifest.mark_summarized("brand_new.md", size=42, summary_file="s/n.md")
    e = tmp_manifest.get("brand_new.md")
    assert e is not None
    assert e.size == 42
    assert e.summary_file == "s/n.md"
