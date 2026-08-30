"""Images and scanned PDFs read their index-time transcript instead of pixels."""

from pathlib import Path

from PIL import Image

from src import content


def _png(tmp_path: Path) -> Path:
    p = tmp_path / "receipt.png"
    Image.new("RGB", (40, 40), "white").save(p)
    return p


def test_image_without_transcript_is_pixels(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "t"))
    blocks = content.build_content_blocks(_png(tmp_path), max_chars=1000, max_pdf_pages=1)
    assert len(blocks) == 1 and not isinstance(blocks[0], str)


def test_image_with_transcript_is_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "t"))
    img = _png(tmp_path)
    out = content.transcript_path_for(img)
    out.parent.mkdir(parents=True)
    out.write_text("# Transcript (ocr)\n\nSource: x\n\n## Page 1\n\nTOTAL 42.50\n", encoding="utf-8")
    blocks = content.build_content_blocks(img, max_chars=1000, max_pdf_pages=1)
    assert len(blocks) == 1 and isinstance(blocks[0], str)
    assert "TOTAL 42.50" in blocks[0] and "index-time transcript" in blocks[0]


def test_stub_transcript_counts_as_none(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "t"))
    img = _png(tmp_path)
    out = content.transcript_path_for(img)
    out.parent.mkdir(parents=True)
    out.write_text("# Transcript (ocr)\n\nSource: x\nPages transcribed: 1 of 1\n", encoding="utf-8")
    assert content.transcript_for(img) is None
    blocks = content.build_content_blocks(img, max_chars=1000, max_pdf_pages=1)
    assert not isinstance(blocks[0], str)


def test_transcripts_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "elsewhere"))
    assert content.transcript_path_for(_png(tmp_path)).parent == tmp_path / "elsewhere"
