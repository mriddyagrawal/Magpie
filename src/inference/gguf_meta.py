"""Read a GGUF file's header metadata - no tensor data, no model load.

Why: llama-server clamps `-c` to the model's declared `<arch>.context_length`
(n_ctx_train). Magpie's answer budget (src/answer.py) is sized from the
profile's ctx_size, so the two must agree, and the only honest source for
the ceiling is the file that will be served - not a constant. The LFM2.5-VL
GGUF on Hugging Face declared 128,000 in August 2026 and 32,768 after the
2026-08-31 "Update GGUFs" commit; a hardcoded limit was wrong within a day
of being written. Reading the header also lets provenance record the
model's declared identity (architecture, name, context) so a metadata-only
upstream change shows up as a fingerprint diff.

GGUF layout (v2/v3): magic "GGUF", u32 version, u64 tensor count, u64 kv
count, then kv pairs of (string key, u32 type, value). Values are scalars,
strings (u64 length + bytes) or arrays (u32 element type, u64 count,
elements). Everything we need is in the first few hundred KB; we stop as
soon as the requested keys are found.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, Optional

_SCALAR = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
_STRING, _ARRAY = 8, 9
_MAX_ARRAY_ELEMENTS_KEPT = 0     # arrays (vocab etc.) are skipped, never materialised

DEFAULT_KEYS = ("general.architecture", "general.name", "general.basename",
                "general.size_label", "general.file_type")


class GGUFError(ValueError):
    """Not a GGUF file, or a header we cannot walk."""


def _read(f, fmt: str):
    size = struct.calcsize("<" + fmt)
    buf = f.read(size)
    if len(buf) != size:
        raise GGUFError("truncated header")
    return struct.unpack("<" + fmt, buf)[0]


def _read_string(f) -> str:
    n = _read(f, "Q")
    if n > 1 << 20:
        raise GGUFError(f"implausible string length {n}")
    return f.read(n).decode("utf-8", "replace")


def _skip_or_read_value(f, vtype: int, keep: bool) -> Any:
    if vtype in _SCALAR:
        return _read(f, _SCALAR[vtype])
    if vtype == _STRING:
        return _read_string(f)
    if vtype == _ARRAY:
        etype = _read(f, "I")
        n = _read(f, "Q")
        if etype in _SCALAR:
            f.seek(n * struct.calcsize("<" + _SCALAR[etype]), 1)
            return f"[{n} items]"
        for _ in range(n):            # string or nested arrays: walk them
            _skip_or_read_value(f, etype, keep=False)
        return f"[{n} items]"
    raise GGUFError(f"unknown value type {vtype}")


def read_metadata(path: Path | str, keys: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Return the requested header keys (default: identity keys plus every
    `*.context_length`). Raises GGUFError on a non-GGUF file."""
    wanted = set(keys or DEFAULT_KEYS)
    out: dict[str, Any] = {}
    with Path(path).open("rb") as f:
        if f.read(4) != b"GGUF":
            raise GGUFError("missing GGUF magic")
        version = _read(f, "I")
        if version < 2:
            raise GGUFError(f"unsupported GGUF version {version}")
        _read(f, "Q")                 # tensor count
        n_kv = _read(f, "Q")
        if n_kv > 100_000:
            raise GGUFError(f"implausible kv count {n_kv}")
        out["gguf_version"] = version
        for _ in range(n_kv):
            key = _read_string(f)
            vtype = _read(f, "I")
            want = key in wanted or key.endswith(".context_length")
            value = _skip_or_read_value(f, vtype, keep=want)
            if want:
                out[key] = value
            if wanted <= set(out) and any(k.endswith(".context_length") for k in out):
                break
    return out


def declared_context_length(path: Path | str) -> Optional[int]:
    """`<arch>.context_length` from the header - what llama-server clamps
    `-c` to - or None when the file is missing/unreadable."""
    try:
        meta = read_metadata(path)
    except (OSError, GGUFError):
        return None
    arch = meta.get("general.architecture")
    if isinstance(arch, str) and isinstance(meta.get(f"{arch}.context_length"), int):
        return int(meta[f"{arch}.context_length"])
    for k, v in meta.items():
        if k.endswith(".context_length") and isinstance(v, int):
            return int(v)
    return None


def identity(path: Path | str) -> dict[str, Any]:
    """Compact provenance record: architecture, name, declared context."""
    try:
        meta = read_metadata(path)
    except (OSError, GGUFError) as e:
        return {"error": str(e)[:120]}
    arch = meta.get("general.architecture")
    return {
        "architecture": arch,
        "name": meta.get("general.name"),
        "size_label": meta.get("general.size_label"),
        "context_length": declared_context_length(path),
        "gguf_version": meta.get("gguf_version"),
    }


if __name__ == "__main__":  # `python -m src.inference.gguf_meta <file.gguf>`
    import sys

    print(json.dumps(identity(sys.argv[1]), indent=2))
