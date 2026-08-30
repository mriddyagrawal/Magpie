"""The walker writes a pixels-only file's transcript as it indexes it."""

from pathlib import Path

from PIL import Image

from src import content
from src.ingest import walker
from src import transcribe


def _png(tmp_path: Path) -> Path:
    p = tmp_path / "receipt.png"
    Image.new("RGB", (40, 40), "white").save(p)
    return p


def _fake_write(path, backend, max_pages=8):
    out = content.transcript_path_for(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"# Transcript ({backend})\n\n## Page 1\n\nTOTAL 42.50\n", encoding="utf-8")
    return out, {"pages": 1, "total_pages": 1, "chars": 11, "seconds": 0.2}


def test_photo_gets_a_transcript(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "t"))
    monkeypatch.setenv("MAGPIE_TRANSCRIBE_BACKEND", "ocr")
    monkeypatch.setattr(transcribe, "write_transcript", _fake_write)
    img = _png(tmp_path)
    note = walker.write_transcript_if_needed(img)
    assert note == "transcript: ocr 1/1 pages 11 chars 0.2s"
    assert content.transcript_for(img) is not None


def test_text_file_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "t"))
    monkeypatch.setenv("MAGPIE_TRANSCRIBE_BACKEND", "ocr")
    called = []
    monkeypatch.setattr(transcribe, "write_transcript", lambda *a, **k: called.append(a))
    doc = tmp_path / "notes.md"
    doc.write_text("plain text\n", encoding="utf-8")
    assert walker.write_transcript_if_needed(doc) is None
    assert called == []


def test_existing_transcript_is_kept_unless_force(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "t"))
    monkeypatch.setenv("MAGPIE_TRANSCRIBE_BACKEND", "ocr")
    img = _png(tmp_path)
    _fake_write(img, "vlm")
    called = []
    monkeypatch.setattr(transcribe, "write_transcript", lambda *a, **k: (called.append(a), _fake_write(*a))[1])
    assert walker.write_transcript_if_needed(img) is None
    assert called == []
    assert walker.write_transcript_if_needed(img, force=True) is not None
    assert len(called) == 1


def test_backend_off_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "t"))
    monkeypatch.setenv("MAGPIE_TRANSCRIBE_BACKEND", "off")
    img = _png(tmp_path)
    assert walker.write_transcript_if_needed(img) is None
    assert content.transcript_for(img) is None


def test_backend_failure_never_fails_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIPTS_DIR", str(tmp_path / "t"))
    monkeypatch.setenv("MAGPIE_TRANSCRIBE_BACKEND", "vlm")

    def boom(*a, **k):
        raise ConnectionError("llama-server is down")

    monkeypatch.setattr(transcribe, "write_transcript", boom)
    img = _png(tmp_path)
    note = walker.write_transcript_if_needed(img)
    assert note.startswith("transcript: vlm failed (ConnectionError")
    assert content.transcript_for(img) is None


def test_auto_backend_picks_ocr_or_vlm(monkeypatch):
    monkeypatch.setenv("MAGPIE_TRANSCRIBE_BACKEND", "auto")
    assert walker.transcribe_backend() in ("ocr", "vlm")
    monkeypatch.setenv("MAGPIE_TRANSCRIBE_BACKEND", "VLM")
    assert walker.transcribe_backend() == "vlm"
