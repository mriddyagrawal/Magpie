"""Tests for src/ingest/tier2.py — extract-then-embed for PDF/DOCX/XLSX/CSV.

We use real pypdf/python-docx/openpyxl to exercise the extraction codepaths.
The invariant is the same as T1: extracted text reaches the embedded body
verbatim (caps honored) so BM25 can hit exact tokens. No LLM call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.content import SummarizeError
from src.ingest import tier2
from src.stage2.parser import parse_summary_file


@pytest.fixture
def isolate_summaries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    sdir = tmp_path / "summaries"
    sdir.mkdir()
    monkeypatch.setattr("src.ingest.common.SUMMARIES_DIR", sdir)
    monkeypatch.setattr(
        "src.ingest.tier2.summary_output_path",
        lambda path, tier: sdir / f"{path.stem}_{tier}.md",
    )
    return sdir


def _make_pdf(tmp_path: Path, text: str) -> Path:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    out = tmp_path / "doc.pdf"
    doc.save(str(out))
    doc.close()
    return out


def _make_docx(tmp_path: Path, paragraphs: list[str]) -> Path:
    from docx import Document
    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    out = tmp_path / "doc.docx"
    d.save(str(out))
    return out


def _make_xlsx(tmp_path: Path, rows: list[list[str]]) -> Path:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    out = tmp_path / "doc.xlsx"
    wb.save(str(out))
    return out


def test_tier2_pdf_extracts_text_verbatim(isolate_summaries: Path, tmp_path: Path):
    pdf = _make_pdf(tmp_path, "Breeze Airways flight $170.45")
    outcome = tier2.run(pdf, "doc.pdf")
    md_path = isolate_summaries / f"{pdf.stem}_t2.md"
    parsed = parse_summary_file(md_path)
    assert "Breeze Airways" in parsed.summary
    assert "$170.45" in parsed.summary
    assert parsed.content_type == "pdf"


def test_tier2_docx_extracts_paragraphs(isolate_summaries: Path, tmp_path: Path):
    d = _make_docx(tmp_path, ["First line.", "Second line about invoices."])
    outcome = tier2.run(d, "doc.docx")
    md_path = isolate_summaries / f"{d.stem}_t2.md"
    parsed = parse_summary_file(md_path)
    assert "First line" in parsed.summary
    assert "invoices" in parsed.summary
    assert parsed.content_type == "docx"


def test_tier2_xlsx_extracts_cells(isolate_summaries: Path, tmp_path: Path):
    x = _make_xlsx(tmp_path, [["name", "amount"], ["Alice", "100"], ["Bob", "200"]])
    outcome = tier2.run(x, "doc.xlsx")
    md_path = isolate_summaries / f"{x.stem}_t2.md"
    parsed = parse_summary_file(md_path)
    assert "Alice" in parsed.summary
    assert "Bob" in parsed.summary
    assert parsed.content_type == "xlsx"


def test_tier2_raises_on_empty_pdf(isolate_summaries: Path, tmp_path: Path):
    # Empty-page PDF — no extractable text
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()
    out = tmp_path / "empty.pdf"
    doc.save(str(out))
    doc.close()

    with pytest.raises(SummarizeError):
        tier2.run(out, "empty.pdf")


def test_tier2_rejects_unsupported_extension(isolate_summaries: Path, tmp_path: Path):
    bogus = tmp_path / "x.weird"
    bogus.write_text("hello", encoding="utf-8")
    with pytest.raises(SummarizeError):
        tier2.run(bogus, "x.weird")


def test_tier2_csv_embeds_raw_rows(isolate_summaries: Path, tmp_path: Path):
    csv = tmp_path / "sales.csv"
    csv.write_text("id,name,amount\n1,Alice,100\n2,Bob,200\n", encoding="utf-8")
    outcome = tier2.run(csv, "sales.csv")
    md_path = isolate_summaries / f"{csv.stem}_t2.md"
    parsed = parse_summary_file(md_path)
    assert "Alice" in parsed.summary
    assert "Bob" in parsed.summary
    assert parsed.content_type == "csv"
