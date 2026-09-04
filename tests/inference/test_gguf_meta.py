"""GGUF header reader: the honest source for the model's context ceiling."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from src.inference import gguf_meta


def _s(text: str) -> bytes:
    b = text.encode()
    return struct.pack("<Q", len(b)) + b


def _kv_str(key: str, value: str) -> bytes:
    return _s(key) + struct.pack("<I", 8) + _s(value)


def _kv_u32(key: str, value: int) -> bytes:
    return _s(key) + struct.pack("<I", 4) + struct.pack("<I", value)


def _kv_arr_str(key: str, values: list[str]) -> bytes:
    body = struct.pack("<I", 8) + struct.pack("<Q", len(values)) + b"".join(_s(v) for v in values)
    return _s(key) + struct.pack("<I", 9) + body


def _kv_arr_f32(key: str, n: int) -> bytes:
    body = struct.pack("<I", 6) + struct.pack("<Q", n) + b"\x00" * (4 * n)
    return _s(key) + struct.pack("<I", 9) + body


def _gguf(tmp_path: Path, kvs: list[bytes], version: int = 3) -> Path:
    header = b"GGUF" + struct.pack("<I", version) + struct.pack("<Q", 0) + struct.pack("<Q", len(kvs))
    p = tmp_path / "m.gguf"
    p.write_bytes(header + b"".join(kvs) + b"tensor-data-would-follow")
    return p


def test_reads_identity_and_context_length(tmp_path: Path) -> None:
    p = _gguf(tmp_path, [
        _kv_str("general.architecture", "lfm2"),
        _kv_str("general.name", "LFM2.5-VL-3B"),
        _kv_arr_str("tokenizer.ggml.tokens", ["a", "b", "c"]),   # skipped, not kept
        _kv_arr_f32("tokenizer.ggml.scores", 3),
        _kv_u32("lfm2.context_length", 32768),
        _kv_u32("lfm2.embedding_length", 2048),
    ])
    meta = gguf_meta.read_metadata(p)
    assert meta["general.architecture"] == "lfm2"
    assert meta["lfm2.context_length"] == 32768
    assert "tokenizer.ggml.tokens" not in meta
    assert gguf_meta.declared_context_length(p) == 32768
    ident = gguf_meta.identity(p)
    assert ident == {"architecture": "lfm2", "name": "LFM2.5-VL-3B", "size_label": None,
                     "context_length": 32768, "gguf_version": 3}


def test_context_length_prefers_the_declared_architecture(tmp_path: Path) -> None:
    p = _gguf(tmp_path, [
        _kv_str("general.architecture", "lfm2"),
        _kv_u32("clip.context_length", 4096),
        _kv_u32("lfm2.context_length", 128000),
    ])
    assert gguf_meta.declared_context_length(p) == 128000


def test_not_a_gguf(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"not a model at all")
    with pytest.raises(gguf_meta.GGUFError):
        gguf_meta.read_metadata(p)
    assert gguf_meta.declared_context_length(p) is None
    assert "error" in gguf_meta.identity(p)


def test_missing_file_is_none(tmp_path: Path) -> None:
    assert gguf_meta.declared_context_length(tmp_path / "nope.gguf") is None


def test_truncated_header_is_an_error(tmp_path: Path) -> None:
    p = _gguf(tmp_path, [_kv_str("general.architecture", "lfm2")])
    p.write_bytes(p.read_bytes()[:20])
    with pytest.raises(gguf_meta.GGUFError):
        gguf_meta.read_metadata(p)


def test_context_lookup_is_memoized_and_stops_early(tmp_path: Path) -> None:
    """The answer budget asks for the ceiling on every query: the header must
    be walked once per (path, size, mtime) and the walk must stop before the
    tokenizer arrays even when optional identity keys are absent."""
    p = _gguf(tmp_path, [
        _kv_str("general.architecture", "lfm2"),
        _kv_u32("lfm2.context_length", 32768),       # no basename / size_label
        _kv_arr_str("tokenizer.ggml.tokens", [f"t{i}" for i in range(5000)]),
    ])
    gguf_meta._MEMO.clear()
    walks = gguf_meta._HEADER_WALKS
    assert gguf_meta.declared_context_length(p) == 32768
    assert gguf_meta.declared_context_length(p) == 32768
    assert gguf_meta._HEADER_WALKS == walks + 1                   # second call served from memo
    meta = gguf_meta.read_metadata(p, gguf_meta._CONTEXT_KEYS)
    assert "tokenizer.ggml.tokens" not in meta                     # early stop before the vocab
    p.write_bytes(p.read_bytes() + b"x")                            # size change invalidates
    assert gguf_meta.declared_context_length(p) == 32768
    assert gguf_meta._HEADER_WALKS == walks + 2
