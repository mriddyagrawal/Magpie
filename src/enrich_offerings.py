"""Enrich course CSVs with term-specific offering data parsed from a Workday
'Find Course Listings' HTML page save.

For each course code in the target CSVs, adds (or overwrites) a column named
after `--term` (e.g. `fall_2026`) with either:

    "not offered"

or a rich, human-readable string like:

    Section 01: Professor Marcelo Dias, MWF 8:30 AM - 9:20 AM, PYR-222 (Open 22/24) | Section 02: ...

Readable in CSV, dense with the exact tokens (instructor names, rooms, days,
times) that BM25 matches on, and preserved as natural prose for dense
embeddings. Idempotent — re-running overwrites the column; adding a new term
just adds a new column.

Usage:

    uv run python3 -m src.enrich_offerings \\
        --html "Test Content/Find Course Listings - Workday.html" \\
        --term fall-2026 \\
        --csvs "Test Content/courses_by_dept" "Test Content/courses_by_ger"
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

# Matches the first token of a section listing: "CSC 121-01 - Intro to ..." or
# "CHM 110-01L - Foundations of Chemistry" (L = lab sibling of section 01).
_SECTION_RE = re.compile(r"([A-Z]{2,4}) (\d{3})-(\d{2}[A-Z]?) - ([^\"<]{1,200})")

# Workday embeds each meeting pattern as data-automation-label="ROOM | DAYS | TIME - TIME".
_MEETING_RE = re.compile(
    r'data-automation-label="([^"|]+?\|[^"|]+?\|[^"|]+? - [^"|]+?)"'
)


@dataclass
class Section:
    number: str          # "01", "02", ...
    status: str          # "Open" | "Waitlist" | "Closed"
    instructor: str      # "Marcelo Dias" or "TBA"
    mode: str            # "In-Person" | "Online" | ...
    seats: str           # "22/24"
    meetings: list[str] = field(default_factory=list)
    # Each meeting is a tuple joined as " | " from Workday: "PYR-222 | MWF | 8:30 AM - 9:20 AM".


@dataclass
class CourseOfferings:
    sections: list[Section] = field(default_factory=list)


def _normalize_code(code: str) -> str:
    """Normalize course code to the CSV's `CSC-121` form (dashed, no spaces)."""
    return code.replace(" ", "-").strip()


def _strip_tags(s: str) -> str:
    """Replace tags with a separator, collapse whitespace."""
    s = re.sub(r"<[^>]+>", " | ", s)
    s = re.sub(r"\s+\|\s+", " | ", s)
    s = re.sub(r"(\|\s*){2,}", " | ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_STATUS_VALUES = {"Open", "Waitlist", "Closed"}
_MODE_VALUES = {"In-Person", "Online", "Hybrid", "Blended", "Remote"}
_SEATS_RE = re.compile(r"^\d+/\d+$")


def _parse_section_window(
    window: str, current_key: tuple[str, str, str]
) -> tuple[str, str, str, str]:
    """Extract (status, instructor, mode, seats) by pattern-matching rather
    than relying on positional order.

    Workday's DOM repeats the section title (CODE NUM-SEC - TITLE) several
    times — in `title=`, `aria-label=`, and as div text — before the actual
    per-section row data appears. We must not truncate at those repetitions;
    `current_key` (the current section's CODE, NUM, SEC) lets us skip them.

    Some rows have empty fields (e.g. no instructor for a TBA course). The
    tag-stripping regex collapses consecutive separators, which shifts
    positional parsing. Identifying status/mode/seats by shape and treating
    "the remaining non-section-title part before Section Details" as
    instructor avoids that shift.
    """
    text = _strip_tags(window)
    # Chop at the next section whose key differs from current_key.
    for nxt in _SECTION_RE.finditer(text):
        if (nxt.group(1), nxt.group(2), nxt.group(3)) != current_key:
            text = text[: nxt.start()]
            break
    # Only look at the portion before "Section Details" — that marker reliably
    # separates the status/instructor/mode/seats prefix from meeting patterns.
    sd_idx = text.find("Section Details")
    prefix = text[:sd_idx] if sd_idx != -1 else text

    parts = [p.strip() for p in prefix.split("|")]

    def _is_noise(p: str) -> bool:
        if not p:
            return True
        if p.startswith('"') or "aria-label" in p or "title=" in p:
            return True
        m = _SECTION_RE.search(p)
        if m and (m.group(1), m.group(2), m.group(3)) == current_key:
            return True
        return False

    # Pattern-match each known field. What's left (non-noise, non-identified)
    # is the instructor.
    status = "?"
    mode = "?"
    seats = "?"
    other: list[str] = []
    for p in parts:
        if _is_noise(p):
            continue
        if status == "?" and p in _STATUS_VALUES:
            status = p
        elif mode == "?" and p in _MODE_VALUES:
            mode = p
        elif seats == "?" and _SEATS_RE.match(p):
            seats = p
        else:
            other.append(p)

    instructor = other[0] if other else "TBA"
    return status, instructor, mode, seats


def parse_workday_html(path: Path) -> dict[str, CourseOfferings]:
    """Return a mapping from normalized course code → CourseOfferings."""
    html = path.read_text(encoding="utf-8", errors="replace")
    offerings: dict[str, CourseOfferings] = defaultdict(CourseOfferings)
    seen: set[tuple[str, str, str]] = set()

    for m in _SECTION_RE.finditer(html):
        code, num, sec, _title = m.groups()
        key = (code, num, sec)
        if key in seen:
            continue
        seen.add(key)

        # Grab a generous window after the match and extract fields.
        window = html[m.end() : m.end() + 5000]
        status, instructor, mode, seats = _parse_section_window(window, key)

        # Meeting patterns — dedupe while preserving order.
        meetings: list[str] = []
        seen_meetings: set[str] = set()
        for mm in _MEETING_RE.finditer(window):
            val = mm.group(1).strip()
            # Sanity: a real meeting has at least one time-of-day marker.
            if not re.search(r"\d{1,2}:\d{2}", val):
                continue
            if val not in seen_meetings:
                seen_meetings.add(val)
                meetings.append(val)

        course_key = _normalize_code(f"{code} {num}")  # "CSC-121"
        offerings[course_key].sections.append(
            Section(
                number=sec,
                status=status,
                instructor=instructor,
                mode=mode,
                seats=seats,
                meetings=meetings,
            )
        )

    return dict(offerings)


# ---------------------------------------------------------------------------
# Rich-string rendering
# ---------------------------------------------------------------------------

NOT_OFFERED = "not offered"


def _format_meeting(raw: str) -> str:
    """Convert 'PYR-222 | MWF | 8:30 AM - 9:20 AM' → 'MWF 8:30 AM - 9:20 AM, PYR-222'."""
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) >= 3:
        room, days, time_range = parts[0], parts[1], parts[2]
        return f"{days} {time_range}, {room}"
    return raw.strip()


def format_offering(off: CourseOfferings) -> str:
    """Produce the rich string for a course's sections."""
    if not off.sections:
        return NOT_OFFERED
    pieces: list[str] = []
    for s in off.sections:
        meets = " + ".join(_format_meeting(m) for m in s.meetings) if s.meetings else "TBA"
        instructor = s.instructor if s.instructor and s.instructor.lower() != "tba" else "TBA"
        instructor_phrase = instructor if instructor == "TBA" else f"Professor {instructor}"
        pieces.append(
            f"Section {s.number}: {instructor_phrase}, {meets} ({s.status} {s.seats})"
        )
    return " | ".join(pieces)


# ---------------------------------------------------------------------------
# CSV enrichment
# ---------------------------------------------------------------------------

def _term_column_name(term: str) -> str:
    """fall-2026 / Fall 2026 / fall_2026 → fall_2026"""
    return re.sub(r"[\s\-]+", "_", term.strip().lower())


def enrich_csv(
    csv_path: Path,
    offerings: dict[str, CourseOfferings],
    column: str,
) -> tuple[int, int]:
    """Rewrite `csv_path` in place, adding/overwriting `column`.

    Returns (rows_offered, rows_not_offered).
    """
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        original_fields = list(reader.fieldnames or [])
        rows = list(reader)

    if column in original_fields:
        # Idempotent: keep the column in its existing position.
        fieldnames = original_fields
    else:
        fieldnames = original_fields + [column]

    offered = 0
    not_offered = 0
    for row in rows:
        code = row.get("code", "").strip()
        course_off = offerings.get(code)
        value = format_offering(course_off) if course_off else NOT_OFFERED
        row[column] = value
        if value == NOT_OFFERED:
            not_offered += 1
        else:
            offered += 1

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return offered, not_offered


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich course CSVs with Workday term-offering data.",
    )
    parser.add_argument(
        "--html",
        required=True,
        type=Path,
        help="Path to the Workday 'Find Course Listings' HTML page save.",
    )
    parser.add_argument(
        "--term",
        required=True,
        help="Term label. Becomes the new column name (e.g. 'fall-2026' → 'fall_2026').",
    )
    parser.add_argument(
        "--csvs",
        nargs="+",
        required=True,
        type=Path,
        help="One or more directories containing the course CSVs to enrich.",
    )
    args = parser.parse_args()

    if not args.html.is_file():
        sys.exit(f"error: no such HTML file: {args.html}")

    print(f"parsing {args.html.name} ...")
    offerings = parse_workday_html(args.html)
    total_sections = sum(len(o.sections) for o in offerings.values())
    print(f"  found {len(offerings)} courses with {total_sections} sections")

    column = _term_column_name(args.term)
    print(f"target column: {column}\n")

    total_offered = 0
    total_not_offered = 0
    total_rows = 0
    # Track which offered courses actually matched a row in any CSV, to spot
    # orphans in the HTML that don't exist in the catalog.
    matched_codes: set[str] = set()

    for csv_dir in args.csvs:
        if not csv_dir.is_dir():
            print(f"  skipping {csv_dir}: not a directory", file=sys.stderr)
            continue
        print(f"enriching CSVs under {csv_dir}/")
        for csv_path in sorted(csv_dir.glob("*.csv")):
            offered, not_offered = enrich_csv(csv_path, offerings, column)
            total_offered += offered
            total_not_offered += not_offered
            total_rows += offered + not_offered
            # Track matches by re-reading what we just wrote. Cheap here.
            with csv_path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get(column) and row[column] != NOT_OFFERED:
                        matched_codes.add(row.get("code", "").strip())
            print(f"  {csv_path.name}: {offered} offered, {not_offered} not offered")

    print()
    print(f"summary: {total_offered}/{total_rows} course rows marked offered "
          f"across {len(args.csvs)} directories")
    orphans = set(offerings.keys()) - matched_codes
    if orphans:
        print(f"  {len(orphans)} courses in Workday HTML but not in any target CSV "
              f"(skipped, not added):")
        for code in sorted(orphans)[:20]:
            print(f"    {code}")
        if len(orphans) > 20:
            print(f"    ... and {len(orphans) - 20} more")


if __name__ == "__main__":
    main()
