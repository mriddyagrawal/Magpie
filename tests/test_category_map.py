"""CATEGORY_MAP consistency tests.

Two invariants:
  1. Every existing router extension constant (TEXT_EXTS, CODE_EXTS, etc.)
     is a subset of its corresponding CATEGORY_MAP entry. If you add an
     extension to a router constant without also adding it here, the user
     can't disable that file type via the categories UI.
  2. No extension appears in two categories. Categories are user-facing
     toggles; ambiguity makes the toggle behavior unpredictable.

These tests are cheap and fast — they're our guard against the kind of
silent drift where a new extension lands in the router but never makes it
into the user-facing classification.
"""

from __future__ import annotations

from src.router import (
    CATEGORY_MAP,
    CODE_EXTS,
    CONFIG_EXTS,
    CSV_EXTS,
    DOCX_EXTS,
    HTML_EXTS,
    IMAGE_EXTS,
    IPYNB_EXTS,
    PDF_EXTS,
    PPTX_EXTS,
    TEXT_EXTS,
    XLSX_EXTS,
)


def test_router_text_exts_in_text_category() -> None:
    assert TEXT_EXTS.issubset(CATEGORY_MAP["text"])


def test_router_code_exts_in_code_category() -> None:
    assert CODE_EXTS.issubset(CATEGORY_MAP["code"])


def test_router_config_csv_in_data_category() -> None:
    assert CONFIG_EXTS.issubset(CATEGORY_MAP["data"])
    assert CSV_EXTS.issubset(CATEGORY_MAP["data"])


def test_router_document_exts_in_document_category() -> None:
    document_router_exts = (PDF_EXTS | DOCX_EXTS | XLSX_EXTS
                            | PPTX_EXTS | HTML_EXTS | IPYNB_EXTS)
    assert document_router_exts.issubset(CATEGORY_MAP["document"])


def test_router_image_exts_in_image_category() -> None:
    assert IMAGE_EXTS.issubset(CATEGORY_MAP["image"])


def test_no_extension_appears_in_two_categories() -> None:
    """An extension in two categories means toggling either one has
    unpredictable effect for the user. Surface as a hard test failure.
    """

    seen: dict[str, str] = {}
    duplicates = []
    for category, exts in CATEGORY_MAP.items():
        for ext in exts:
            if ext in seen:
                duplicates.append((ext, seen[ext], category))
            else:
                seen[ext] = category
    assert not duplicates, (
        f"extensions appear in multiple categories: {duplicates!r} "
        "— each extension must belong to exactly one category"
    )


def test_archive_category_present_even_though_router_has_no_handler() -> None:
    """`archive` is in CATEGORY_MAP for the user toggle even though there's
    no router handler today. Default-OFF in `categories_enabled` so users
    don't accidentally try to embed zip files. See plan §3 / Plan #12.
    """

    assert "archive" in CATEGORY_MAP
    assert ".zip" in CATEGORY_MAP["archive"]
