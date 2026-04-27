"""Tests for `--include-data` / `include_data=` — controlling whether the
walker considers `.json`, `.csv`, `.dat` files.

Default behavior: these are skipped.
With opt-in: they're added to the considered set and routed normally.
"""

from __future__ import annotations

from pathlib import Path

from src.ingest.walker import _DATA_EXTS_DEFAULT_OFF, find_candidates


def _touch(p: Path, contents: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents, encoding="utf-8")
    return p


def test_data_files_skipped_by_default(tmp_path: Path):
    """`.json`, `.csv`, `.dat` are silently dropped without `--include-data`."""
    _touch(tmp_path / "real.md", "real content")
    _touch(tmp_path / "real.py", "print('hi')")
    _touch(tmp_path / "settings.json", '{"k":"v"}')
    _touch(tmp_path / "data.csv", "a,b\n1,2\n")
    _touch(tmp_path / "blob.dat", "anything")

    files, _, _ = find_candidates(tmp_path)
    names = {f.name for f in files}
    assert names == {"real.md", "real.py"}


def test_data_files_indexed_with_include_data(tmp_path: Path):
    """`include_data=True` re-adds `.json`, `.csv`, `.dat` to the candidate set."""
    _touch(tmp_path / "real.md", "real")
    _touch(tmp_path / "settings.json", '{"k":"v"}')
    _touch(tmp_path / "data.csv", "a,b\n1,2\n")
    _touch(tmp_path / "blob.dat", "fixed-width text data")

    files, _, _ = find_candidates(tmp_path, include_data=True)
    names = {f.name for f in files}
    assert names == {"real.md", "settings.json", "data.csv", "blob.dat"}


def test_data_default_off_set_is_exactly_three(tmp_path: Path):
    """Sanity: the default-off set is `.json`, `.csv`, `.dat` and nothing else.
    If we add a new data extension later, this test reminds us to update docs
    and the `--include-data` flag's behavior intentionally."""
    assert _DATA_EXTS_DEFAULT_OFF == {".json", ".csv", ".dat"}


def test_yaml_toml_still_indexed_by_default(tmp_path: Path):
    """We deliberately did NOT lump `.yaml`, `.yml`, `.toml` with `.json`.
    These tend to be small config files (pyproject.toml, app configs) that
    users typically DO want searchable."""
    _touch(tmp_path / "config.yaml", "key: value")
    _touch(tmp_path / "settings.yml", "k: v")
    _touch(tmp_path / "pyproject.toml", '[project]\nname = "x"')

    files, _, _ = find_candidates(tmp_path)
    names = {f.name for f in files}
    assert names == {"config.yaml", "settings.yml", "pyproject.toml"}


def test_data_flag_does_not_disable_other_filters(tmp_path: Path):
    """`include_data=True` is permission to consider data files. It doesn't
    bypass `.gitignore`, hidden-path filters, or built-in defaults."""
    _touch(tmp_path / ".nasignore", "ignored.json\n")
    _touch(tmp_path / "ignored.json", "should still be ignored")
    _touch(tmp_path / "kept.json", "should be kept")
    _touch(tmp_path / "node_modules" / "nested.json", "node_modules cruft")

    files, _, _ = find_candidates(tmp_path, include_data=True)
    names = {f.name for f in files}
    assert names == {"kept.json"}
