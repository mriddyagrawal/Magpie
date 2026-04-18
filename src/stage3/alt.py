"""Parse `.alt` sidecar files into structured objects.

An `.alt` is a YAML document describing a too-large-to-read source (video,
archive, raw dataset) so the search pipeline can discover and answer
questions about it without ever loading the underlying bytes.

Schema (v1, see `Plans/Stage 3 - Videos.md`):

    ---
    alt_version: 1
    type: home_video           # or: movie, lecture, podcast, ...
    source:
      filename: "..."          # original bytes' filename
      local_path: "..."        # absolute path to original bytes
      file_hash_sha256: "..."  # optional
      file_size_bytes: 123     # optional
    technical: { ... }         # codec, fps, duration, etc. — free-form
    recorded: { date, time_utc }
    summary:
      one_line: "..."
      full: "..."              # prose paragraph(s)
    scenes:                    # optional list
      - timecode: "00:20"
        description: "..."
        setting: "..."         # optional
        mood: "..."            # optional
    context: { ... }           # free-form k:v
    themes: [ ... ]
    search_tokens: [ ... ]
    thumbnails: [ ... ]        # optional
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class AltParseError(ValueError):
    """Raised when an `.alt` file is malformed."""


@dataclass
class AltScene:
    timecode: str
    description: str
    setting: str = ""
    mood: str = ""


@dataclass
class AltDocument:
    alt_path: Path
    alt_version: int
    type: str
    source_filename: str
    source_local_path: str
    source_hash: str
    summary_one_line: str
    summary_full: str
    scenes: list[AltScene] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    search_tokens: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    technical: dict[str, Any] = field(default_factory=dict)
    recorded: dict[str, Any] = field(default_factory=dict)


def _require(data: dict[str, Any], path: str, key: str, *, where: str) -> Any:
    if key not in data:
        raise AltParseError(f"{where}: missing required field '{path}.{key}'")
    return data[key]


def _as_str_list(value: Any, *, where: str, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AltParseError(f"{where}: '{field_name}' must be a list, got {type(value).__name__}")
    return [str(item) for item in value]


def parse_alt_file(path: Path) -> AltDocument:
    """Read and parse an `.alt` YAML file into an AltDocument.

    Raises `AltParseError` for malformed or incomplete files.
    """
    where = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise AltParseError(f"{where}: not valid UTF-8: {e}") from e
    except OSError as e:
        raise AltParseError(f"{where}: cannot read: {e}") from e

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise AltParseError(f"{where}: YAML parse error: {e}") from e

    if not isinstance(data, dict):
        raise AltParseError(f"{where}: top-level must be a mapping, got {type(data).__name__}")

    alt_version = _require(data, "", "alt_version", where=where)
    if not isinstance(alt_version, int):
        raise AltParseError(f"{where}: alt_version must be an int, got {type(alt_version).__name__}")

    source = _require(data, "", "source", where=where)
    if not isinstance(source, dict):
        raise AltParseError(f"{where}: 'source' must be a mapping")

    summary = _require(data, "", "summary", where=where)
    if not isinstance(summary, dict):
        raise AltParseError(f"{where}: 'summary' must be a mapping")

    scenes_raw = data.get("scenes", []) or []
    if not isinstance(scenes_raw, list):
        raise AltParseError(f"{where}: 'scenes' must be a list")
    scenes: list[AltScene] = []
    for i, s in enumerate(scenes_raw):
        if not isinstance(s, dict):
            raise AltParseError(f"{where}: scenes[{i}] must be a mapping")
        timecode = str(_require(s, f"scenes[{i}]", "timecode", where=where))
        description = str(_require(s, f"scenes[{i}]", "description", where=where))
        scenes.append(
            AltScene(
                timecode=timecode,
                description=description,
                setting=str(s.get("setting", "") or ""),
                mood=str(s.get("mood", "") or ""),
            )
        )

    context_raw = data.get("context") or {}
    technical_raw = data.get("technical") or {}
    recorded_raw = data.get("recorded") or {}

    return AltDocument(
        alt_path=path,
        alt_version=alt_version,
        type=str(data.get("type", "unknown") or "unknown"),
        source_filename=str(source.get("filename", "") or ""),
        source_local_path=str(source.get("local_path", "") or ""),
        source_hash=str(source.get("file_hash_sha256", "") or ""),
        summary_one_line=str(summary.get("one_line", "") or ""),
        summary_full=str(summary.get("full", "") or "").strip(),
        scenes=scenes,
        themes=_as_str_list(data.get("themes"), where=where, field_name="themes"),
        search_tokens=_as_str_list(
            data.get("search_tokens"), where=where, field_name="search_tokens"
        ),
        context=context_raw if isinstance(context_raw, dict) else {},
        technical=technical_raw if isinstance(technical_raw, dict) else {},
        recorded=recorded_raw if isinstance(recorded_raw, dict) else {},
    )
