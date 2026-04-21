"""Turn an AltDocument into the summary-markdown shape Stage 2 expects.

For each `.alt` we emit:
    * 1 file-level summary    -> "<digest>_video.md"
    * N per-scene summaries   -> "<digest>_s<index>_<tc>.md"

All emitted markdowns set `Source:` to the `.alt` itself (not the underlying
video), because Stage 4 reads `Source:` into an LLM — and `.alt` is readable
text while `.mov` bytes are not.

The per-scene markdowns carry a manifest key like
    "<alt rel path>#scene:00:20"
so Stage 2's existing dedup-by-source-path does the right thing and every
scene gets its own Qdrant point.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.stage3.alt import AltDocument, AltScene


@dataclass
class EmittedSummary:
    manifest_key: str          # what Stage 2 keys on (source_path in ParsedSummary)
    summary_md: str            # full markdown body (Source: header + content)
    kind: str                  # "video" | "scene" — for filename suffix


def _fmt_list(items: list[str]) -> str:
    return ", ".join(items) if items else "—"


def _entities_for_file(alt: AltDocument) -> list[str]:
    """Pick named entities from the .alt — people/places/orgs live in context."""
    ents: list[str] = []
    for value in alt.context.values():
        if isinstance(value, str) and value.strip():
            ents.append(value.strip())
    if alt.source_filename:
        ents.append(alt.source_filename)
    return ents


def _identifiers_for_file(alt: AltDocument) -> list[str]:
    """Exact-match tokens: hash, path, dates, filename, duration."""
    ids: list[str] = []
    if alt.source_hash:
        ids.append(alt.source_hash)
    if alt.source_local_path:
        ids.append(alt.source_local_path)
    if alt.source_filename:
        ids.append(alt.source_filename)
    rec_date = alt.recorded.get("date")
    if rec_date:
        ids.append(str(rec_date))
    rec_time = alt.recorded.get("time_utc")
    if rec_time:
        ids.append(str(rec_time))
    duration = alt.technical.get("duration_human")
    if duration:
        ids.append(str(duration))
    return ids


def _file_level_summary_text(alt: AltDocument) -> str:
    """Prose that will be embedded — include enough discriminator tokens for BM25."""
    parts: list[str] = []
    if alt.summary_one_line:
        parts.append(alt.summary_one_line)
    if alt.summary_full:
        parts.append(alt.summary_full)
    # Flatten scene descriptions into the prose so file-level search can still
    # match timecode-specific language even when per-scene points miss.
    if alt.scenes:
        scene_lines = [
            f"At {s.timecode}: {s.description}." for s in alt.scenes
        ]
        parts.append(" ".join(scene_lines))
    return " ".join(p.strip() for p in parts if p.strip())


def _title_for_file(alt: AltDocument) -> str:
    if alt.summary_one_line:
        # First ~80 chars of the one-liner, stripped of trailing punctuation.
        t = alt.summary_one_line.strip().rstrip(".")
        return t[:80]
    return alt.source_filename or alt.alt_path.name


def render_file_level(alt: AltDocument, alt_source_rel: str) -> str:
    keywords = sorted(set(alt.themes + alt.search_tokens))
    return (
        f"Source: {alt_source_rel}\n\n"
        f"# {_title_for_file(alt)}\n\n"
        f"{_file_level_summary_text(alt)}\n\n"
        f"**Content type:** alt\n\n"
        f"**Keywords:** {_fmt_list(keywords)}\n\n"
        f"**Key entities:** {_fmt_list(_entities_for_file(alt))}\n\n"
        f"**Identifiers:** {_fmt_list(_identifiers_for_file(alt))}\n"
    )


def _scene_prose(alt: AltDocument, scene: AltScene) -> str:
    """Short prose the scene-level point gets embedded on."""
    bits = [f"At timecode {scene.timecode}: {scene.description}"]
    if scene.setting:
        bits.append(f"Setting: {scene.setting}")
    if scene.mood:
        bits.append(f"Mood: {scene.mood}")
    # Anchor back to the parent video so scene-only hits still know the context.
    if alt.summary_one_line:
        bits.append(f"Parent video: {alt.summary_one_line}")
    return " ".join(bits)


def render_scene(alt: AltDocument, scene: AltScene, alt_source_rel: str) -> str:
    ids = [scene.timecode]
    if alt.source_filename:
        ids.append(alt.source_filename)
    if alt.source_hash:
        ids.append(alt.source_hash)

    keywords = sorted(set(alt.themes + alt.search_tokens))
    entities = _entities_for_file(alt)
    source_with_fragment = f"{alt_source_rel}#scene:{scene.timecode}"

    return (
        f"Source: {source_with_fragment}\n\n"
        f"# Scene {scene.timecode} — {scene.description[:60]}\n\n"
        f"{_scene_prose(alt, scene)}\n\n"
        f"**Content type:** alt-scene\n\n"
        f"**Keywords:** {_fmt_list(keywords)}\n\n"
        f"**Key entities:** {_fmt_list(entities)}\n\n"
        f"**Identifiers:** {_fmt_list(ids)}\n"
    )


def _tc_slug(timecode: str) -> str:
    """'00:20' -> '00_20' so it's safe to embed in a filename."""
    return timecode.replace(":", "_").replace("/", "_")


def transcode(alt: AltDocument, alt_source_rel: str) -> list[EmittedSummary]:
    """Turn one AltDocument into a list of summary-markdown blobs.

    `alt_source_rel` is the repo-relative (or absolute, if outside repo)
    path-string that should appear on the `Source:` line AND be used as
    the manifest key for the file-level point.
    """
    out: list[EmittedSummary] = []

    out.append(
        EmittedSummary(
            manifest_key=alt_source_rel,
            summary_md=render_file_level(alt, alt_source_rel),
            kind="video",
        )
    )
    for scene in alt.scenes:
        out.append(
            EmittedSummary(
                manifest_key=f"{alt_source_rel}#scene:{scene.timecode}",
                summary_md=render_scene(alt, scene, alt_source_rel),
                kind=f"s_{_tc_slug(scene.timecode)}",
            )
        )
    return out
