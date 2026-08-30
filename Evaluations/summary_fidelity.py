"""Measure how much of each generated summary is actually in the file.

The answer-side groundedness guard checks an answer against the files it
read. This is the same check one stage earlier, and it is the stage that
matters more: a summary is written once and then read by every question
about that file, forever. A fabricated answer costs one question. A
fabricated summary costs all of them.

sem_4 is the case that forced this. `Receipt-2794-8324.pdf` is a $20.00
Cursor Pro invoice; its generated summary describes "a receipt for a flight
from Atlanta to Hartford, flight number DL1492, passenger Jane Doe". Five
eval questions inherited that fiction, and no answer-side lever recovered
them — the model that wrote the fiction is the model doing the reading.

Two signals, both deterministic, no model in the loop:

  numerals   figures in the summary that appear nowhere in the source
  entities   things the summary's own `Key entities:` / `Identifiers:`
             lists claim are in the document, but are not

The entity list is what catches a wholesale invention. That receipt's
summary lists `Atlanta, Hartford, DL1492, Jane Doe` as its key entities —
not one of which appears in the file. No number scrubber sees that, because
none of it is a number; but every item is a claim, and a claim is
checkable.

    uv run python Evaluations/summary_fidelity.py            # current data dir
    MAGPIE_DATA_DIR=... uv run python Evaluations/summary_fidelity.py --worst 15
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.content import build_content_blocks  # noqa: E402
from src.grounding import normalize, numerals  # noqa: E402

# Below this much extracted text the file is effectively unreadable and its
# summary cannot be checked against anything — scanned pages land here, and
# scrubbing/scoring them punishes a vision pass that read the image fine.
MIN_SOURCE_CHARS = 200

# The summarizer emits `Key entities:` and `Identifiers:` — an explicit list
# of things it CLAIMS are in the document. That claim is checkable, and it is
# a far cleaner signal than parsing entities out of the prose: prose
# extraction trips over the model's own title-case headings ("Weighted Die
# Roller Script") and reports 70% fabrication on a corpus that is mostly fine.
_CLAIM_FIELDS = ("**Key entities:**", "**Identifiers:**")

# Claim lists sometimes carry the em-dash placeholder for "none".
_EMPTY_CLAIM = {"—", "-", "none", "n/a", ""}


def _claims(md: str) -> list[str]:
    out: list[str] = []
    for ln in md.splitlines():
        for field in _CLAIM_FIELDS:
            if ln.startswith(field):
                for item in ln[len(field):].split(","):
                    item = item.strip()
                    if item.lower() in _EMPTY_CLAIM or item in out:
                        continue
                    out.append(item)
    return out


def _summary_prose(md: str) -> str:
    """The generated prose only — not the Source: path line, not the
    Identifiers list (which is machine-extracted and grounded by
    construction)."""
    lines = []
    for ln in md.splitlines():
        if ln.startswith("Source:") or ln.startswith("**Identifiers:**"):
            continue
        if ln.startswith("**Key entities:**") or ln.startswith("**Keywords:**"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def audit(data_dir: Path, worst: int) -> None:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))

    checked = skipped = 0
    tot_nums = bad_nums = tot_ents = bad_ents = 0
    offenders: list[tuple[float, str, list[str], list[str]]] = []

    for src, entry in manifest.items():
        sf = entry.get("summary_file")
        if not sf:
            continue
        md_path = data_dir / sf
        path = Path(src)
        if not md_path.is_file() or not path.is_file():
            continue
        try:
            blocks = build_content_blocks(path, max_chars=60_000, max_pdf_pages=20)
        except Exception:  # noqa: BLE001
            continue
        source = normalize("".join(b for b in blocks if isinstance(b, str)))
        if "scanned / image-only" in source or len(source.strip()) < MIN_SOURCE_CHARS:
            skipped += 1
            continue

        source = f"{path.name}\n{source}"
        despaced = re.sub(r"\s+", "", source)
        low = source.lower()

        md = md_path.read_text(encoding="utf-8", errors="replace")
        prose = _summary_prose(md)
        nums = [n for n in numerals(prose) if "[unreadable]" not in n]
        ents = _claims(md)

        miss_n = [n for n in nums if n not in source and n not in despaced]
        # De-spaced comparison for entities too: several PDFs here extract
        # with a space between every glyph ("R a h u l   R a n j a n"), which
        # made a correctly-named author look fabricated.
        low_despaced = re.sub(r"\s+", "", low)
        miss_e = [
            e for e in ents
            if e.lower() not in low and re.sub(r"\s+", "", e.lower()) not in low_despaced
        ]

        checked += 1
        tot_nums += len(nums); bad_nums += len(miss_n)
        tot_ents += len(ents); bad_ents += len(miss_e)

        total = len(nums) + len(ents)
        if total and (miss_n or miss_e):
            rate = (len(miss_n) + len(miss_e)) / total
            offenders.append((rate, path.name, miss_n, miss_e))

    print(f"data dir      : {data_dir}")
    print(f"summaries     : {checked} checked, {skipped} skipped (scanned / too thin)")
    if tot_nums:
        print(f"figures       : {bad_nums}/{tot_nums} absent from the source "
              f"({100*bad_nums/tot_nums:.1f}%)")
    if tot_ents:
        print(f"claimed entities: {bad_ents}/{tot_ents} absent from the source "
              f"({100*bad_ents/tot_ents:.1f}%)")
    dirty = len(offenders)
    if checked:
        print(f"summaries with at least one unsupported claim: "
              f"{dirty}/{checked} ({100*dirty/checked:.1f}%)")

    offenders.sort(reverse=True)
    if offenders:
        print(f"\nworst {min(worst, len(offenders))} by unsupported fraction:")
        for rate, name, miss_n, miss_e in offenders[:worst]:
            bits = ", ".join((miss_e + miss_n)[:6])
            print(f"  {100*rate:5.0f}%  {name[:48]:50s} {bits[:70]}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--worst", type=int, default=10)
    args = p.parse_args()
    from src.manifest import APP_DATA_DIR

    audit(APP_DATA_DIR, args.worst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
