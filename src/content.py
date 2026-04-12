"""Shared file-content dispatch used by stage 1 (summarize.py) and stage 4 (answer.py).

Responsibilities:
- Know every supported file extension.
- Turn a single Path into a list of content blocks (strings + BinaryContent) suitable
  for handing to a PydanticAI Agent. Caller owns the framing (filename hints, question
  prefix, etc.); this module only produces the content itself.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import BinaryContent


IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif"}
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
             ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".swift", ".kt",
             ".sh", ".sql", ".json", ".yaml", ".yml", ".toml"}
TEXT_EXTS = {".txt"}
MD_EXTS = {".md", ".markdown"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
XLSX_EXTS = {".xlsx", ".xlsm"}

PDF_VISION_DPI = 150

SUPPORTED_EXTS = (
    set(IMAGE_EXTS)
    | PDF_EXTS
    | DOCX_EXTS
    | XLSX_EXTS
    | MD_EXTS
    | TEXT_EXTS
    | CODE_EXTS
)


class SummarizeError(RuntimeError):
    """Raised for per-file failures that should not abort a batch run."""


def extract_pdf_text(path: Path, max_chars: int) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError) as e:
        raise SummarizeError(f"could not open PDF {path}: {e}") from e

    if reader.is_encrypted:
        raise SummarizeError(f"PDF is password-protected: {path}")

    chunks: list[str] = []
    total = 0
    try:
        for page in reader.pages:
            t = page.extract_text() or ""
            chunks.append(t)
            total += len(t)
            if total >= max_chars:
                break
    except PdfReadError as e:
        raise SummarizeError(f"PDF parse error while reading pages: {path}: {e}") from e
    return "\n\n".join(chunks)


def render_pdf_pages_as_png(path: Path, max_pages: int) -> list[bytes]:
    import pymupdf

    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        raise SummarizeError(f"could not open PDF for rendering: {path}: {e}") from e

    images: list[bytes] = []
    try:
        if doc.needs_pass:
            raise SummarizeError(f"PDF is password-protected: {path}")
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=PDF_VISION_DPI)
            images.append(pix.tobytes("png"))
    finally:
        doc.close()
    return images


def extract_docx_text(path: Path) -> str:
    from docx import Document
    from docx.opc.exceptions import PackageNotFoundError

    try:
        doc = Document(str(path))
    except (PackageNotFoundError, OSError) as e:
        raise SummarizeError(f"not a valid .docx file: {path}: {e}") from e

    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append("\t".join(cells))
    return "\n".join(parts)


def extract_xlsx_text(path: Path) -> str:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = load_workbook(str(path), data_only=True, read_only=True)
    except (InvalidFileException, OSError) as e:
        raise SummarizeError(f"not a valid .xlsx file: {path}: {e}") from e

    parts: list[str] = []
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            parts.append(f"## Sheet: {sheet_name}")
            for row in ws.iter_rows(values_only=True):
                if not any(cell is not None and str(cell).strip() for cell in row):
                    continue
                parts.append(",".join("" if cell is None else str(cell) for cell in row))
            parts.append("")
    finally:
        wb.close()
    return "\n".join(parts)


def build_content_blocks(
    path: Path,
    *,
    max_chars: int,
    max_pdf_pages: int,
) -> list:
    """Return content blocks for a single file.

    The returned list contains `str` blocks (carrying textual content, with a
    'Content type: ...' header) and `BinaryContent` blocks (for images or for PDF
    pages rendered via the scanned-PDF vision fallback).

    Raises SummarizeError for unsupported extensions, encrypted PDFs, corrupt
    Office files, non-UTF-8 text files, or empty content.
    """
    ext = path.suffix.lower()

    if ext in IMAGE_EXTS:
        return [BinaryContent(data=path.read_bytes(), media_type=IMAGE_EXTS[ext])]

    if ext in PDF_EXTS:
        text = extract_pdf_text(path, max_chars).strip()
        if text:
            return [f"Content type: pdf\n\n---\n{text[:max_chars]}"]
        pages = render_pdf_pages_as_png(path, max_pdf_pages)
        if not pages:
            raise SummarizeError(f"PDF has no pages: {path}")
        blocks: list = [
            f"Content type: pdf (scanned / image-only — {len(pages)} page(s) as images)"
        ]
        for page_png in pages:
            blocks.append(BinaryContent(data=page_png, media_type="image/png"))
        return blocks

    if ext in DOCX_EXTS:
        text = extract_docx_text(path).strip()
        if not text:
            raise SummarizeError(f"docx appears empty: {path}")
        return [f"Content type: docx\n\n---\n{text[:max_chars]}"]

    if ext in XLSX_EXTS:
        text = extract_xlsx_text(path).strip()
        if not text:
            raise SummarizeError(f"xlsx appears empty: {path}")
        return [f"Content type: xlsx\n\n---\n{text[:max_chars]}"]

    if ext in MD_EXTS or ext in TEXT_EXTS or ext in CODE_EXTS:
        ctype = "markdown" if ext in MD_EXTS else ("code" if ext in CODE_EXTS else "text")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise SummarizeError(f"file is not valid UTF-8 text: {path}") from e
        return [f"Content type: {ctype}\n\n---\n{text[:max_chars]}"]

    raise SummarizeError(f"unsupported file type '{ext}' for {path}")
