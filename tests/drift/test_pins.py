"""Pins are the single source of truth - the installers and the justfile
must agree with them, and check_pins must report every kind of mismatch."""

from __future__ import annotations

import re
from pathlib import Path

from src.drift import pins

REPO = Path(__file__).resolve().parents[2]


def test_installer_reads_its_version_from_pins() -> None:
    from src.tools.install_llama_server import DEFAULT_VERSION

    assert DEFAULT_VERSION == pins.LLAMA_SERVER_TAG == f"b{pins.LLAMA_SERVER_BUILD}"


def test_justfile_qdrant_version_matches_pins() -> None:
    text = (REPO / "justfile").read_text(encoding="utf-8")
    m = re.search(r'^QDRANT_VERSION\s*:=\s*"([^"]+)"', text, re.M)
    assert m, "justfile lost its QDRANT_VERSION variable"
    assert m.group(1) == pins.QDRANT_VERSION, (
        "justfile QDRANT_VERSION and src/drift/pins.QDRANT_VERSION diverged - "
        "bump both together"
    )


def test_check_pins_all_match() -> None:
    prov = {"llama_server": {"build": pins.LLAMA_SERVER_BUILD},
            "qdrant": {"version": pins.QDRANT_VERSION.lstrip("v")}}
    assert pins.check_pins(prov) == []


def test_check_pins_reports_llama_server_drift() -> None:
    out = pins.check_pins({"llama_server": {"build": pins.LLAMA_SERVER_BUILD + 100},
                           "qdrant": {"version": None}})
    assert [m["component"] for m in out] == ["llama-server"]
    assert out[0]["installed"] == f"b{pins.LLAMA_SERVER_BUILD + 100}"
    assert out[0]["pinned"] == pins.LLAMA_SERVER_TAG


def test_check_pins_unparseable_binary_is_a_mismatch() -> None:
    # an unparseable version is the case that silently defeated the old guard
    out = pins.check_pins({"llama_server": {"build": None, "raw": "weird build"}, "qdrant": {}})
    assert out and out[0]["installed"] == "weird build"


def test_check_pins_qdrant_accepts_with_or_without_v() -> None:
    bare = pins.QDRANT_VERSION.lstrip("v")
    assert pins.check_pins({"llama_server": {"build": pins.LLAMA_SERVER_BUILD},
                            "qdrant": {"version": bare}}) == []
    out = pins.check_pins({"llama_server": {"build": pins.LLAMA_SERVER_BUILD},
                           "qdrant": {"version": "9.9.9"}})
    assert [m["component"] for m in out] == ["qdrant"]


def test_unreachable_qdrant_is_not_a_mismatch() -> None:
    out = pins.check_pins({"llama_server": {"build": pins.LLAMA_SERVER_BUILD},
                           "qdrant": {"version": None, "reachable": False}})
    assert out == []
