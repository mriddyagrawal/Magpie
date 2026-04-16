"""Pre-process courses_raw.json into per-department and per-GER CSV files.

Usage:
    uv run python3 -m src.split_courses "Test Content/courses_raw.json"

Output goes into the same parent directory:
    <parent>/courses_by_dept/ACC.csv, CSC.csv, ...
    <parent>/courses_by_ger/TA.csv, HB.csv, ...
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Columns in the output CSVs (coid deliberately excluded).
COLUMNS = ["code", "title", "ger", "prerequisites", "description", "credits"]

# Regex to pull 2-3 letter GER codes that appear before a '(' in the raw string.
_GER_CODE_RE = re.compile(r"\b([A-Z]{2,3})\b(?=\s*\()")
# Fallback: codes inside parentheses, e.g. "(IEJ)"
_GER_PAREN_RE = re.compile(r"\(([A-Z]{2,3})\)")


def _extract_ger_codes(raw: str) -> list[str]:
    """Return deduplicated list of normalised GER short codes."""
    codes = _GER_CODE_RE.findall(raw)
    if not codes:
        codes = _GER_PAREN_RE.findall(raw)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["code"]):
            writer.writerow({k: row[k] for k in COLUMNS})


def split(src: Path) -> None:
    data: list[dict] = json.loads(src.read_text(encoding="utf-8"))
    base = src.parent

    by_dept: dict[str, list[dict]] = defaultdict(list)
    by_ger: dict[str, list[dict]] = defaultdict(list)

    for course in data:
        dept = course["code"].split("-")[0]
        by_dept[dept].append(course)

        if course["ger"]:
            for code in _extract_ger_codes(course["ger"]):
                by_ger[code].append(course)

    dept_dir = base / "courses_by_dept"
    ger_dir = base / "courses_by_ger"

    for dept, rows in by_dept.items():
        _write_csv(dept_dir / f"{dept}.csv", rows)

    for ger, rows in by_ger.items():
        _write_csv(ger_dir / f"{ger}.csv", rows)

    print(f"Wrote {len(by_dept)} department CSVs to {dept_dir}")
    print(f"Wrote {len(by_ger)} GER CSVs to {ger_dir}")
    print(f"Total courses: {len(data)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python3 -m src.split_courses <courses_raw.json>")
        sys.exit(1)
    split(Path(sys.argv[1]))
