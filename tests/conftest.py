"""Repo-wide test guards.

Tests must never touch the user's REAL app config. The walker's
`ensure_path_included` side effect persists every walk root into
`indexing_rules.json` under APP_DATA_DIR — which for a plain pytest run is
the developer's live `~/Library/Application Support/Magpie/`. Before this
fixture existed, every test run appended its tmp corpus dirs there
(observed: ~120 dead pytest-tmpdir entries accumulated on a dev machine).

`_user_rules_path()` is the single choke point for load/save/compose of the
user rules JSON (APP_DATA_DIR itself is bound at src.manifest import time,
so an env-var fixture would be import-order dependent — patching the
function is not). The isolated file lives in its OWN tmp dir, never inside
`tmp_path`: tests use `tmp_path` as a walk corpus, and a rules file planted
there becomes a phantom candidate in their assertions.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_user_indexing_rules(tmp_path_factory, monkeypatch):
    rules_dir = tmp_path_factory.mktemp("magpie-rules")
    from src.config import indexing_rules as ir_mod

    monkeypatch.setattr(
        ir_mod, "_user_rules_path",
        lambda: rules_dir / "indexing_rules.json",
    )
