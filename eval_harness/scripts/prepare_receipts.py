"""Build the `receipts` eval dataset from SROIE (PLAN.md §6).

Source: HF dataset jsdnrs/ICDAR2019-SROIE (CC-BY-4.0 mirror of ICDAR-2019
SROIE), test split. Deterministic throughout — same inputs, same corpus, same
golden set, byte-for-byte.

  corpus   150 receipt JPEGs (sorted order, first 150 of the test split)
           -> OUTSIDE the repo (default ~/Documents/Magpie-eval-corpora/receipts)
  golden   eval_harness/datasets/receipts/golden.json   (committed)
  qrels    eval_harness/datasets/receipts/qrels.tsv     (committed)
  manifest eval_harness/datasets/receipts/manifest.json (committed; sha256s)
  pointer  eval_harness/datasets/receipts/corpus_root.local.json (untracked)

Question design (blind by construction — built from labeled entity fields,
never from OCR text, so questions cannot lexically copy the receipt):
  - extractive: total / date / address, disambiguated by company (+date when
    a company recurs); only unambiguous keys are used
  - not_found: companies present in the test split but NOT in the 150 —
    plausible in-domain vendors guaranteed absent from the corpus
  - aggregation / enumeration: counts and date-lists for companies with >=2
    receipts in the corpus (answers derived mechanically from the labels)

Run (one-time prep; eval runs themselves stay offline):
  uv run --with datasets --with pillow python eval_harness/scripts/prepare_receipts.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO / "eval_harness" / "datasets" / "receipts"
DEFAULT_CORPUS = Path.home() / "Documents" / "Magpie-eval-corpora" / "receipts"

N_CORPUS = 150          # decided 2026-08-28 (PLAN §9.5)
GENERATOR = "prepare_receipts.py (mechanical, SROIE labels)"
# Pinned dataset revision (review #41): resolved 2026-08-28. Without a pin,
# "deterministic" depends on whatever HEAD resolves on rerun day.
REVISION = "bffe40c26759f3376ec2b3ae9031dbba54cd587c"

# Tokens too generic to prove two company strings are the same vendor
# (review #42): legal suffixes and ubiquitous trade words.
_GENERIC_TOKENS = {
    "sdn", "bhd", "s/b", "sb", "the", "and", "enterprise", "trading",
    "store", "mart", "shop", "restoran", "restaurant", "cafe", "sales",
    "services", "service", "company", "co", "malaysia",
}


def _company_tokens(name: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", name.casefold())
    return {t for t in toks if len(t) >= 4 and t not in _GENERIC_TOKENS}


def address_facts(addr: str) -> list[str]:
    """Atomic, binary-checkable facts from an OCR address (review #39): the
    5-digit postcode and the trailing locality segment. Full OCR addresses
    are too noisy for exact matching and would misattribute grading noise
    to scaffolding."""
    facts: list[str] = []
    m = re.search(r"\b(\d{5})\b", addr or "")
    if m:
        facts.append(m.group(1))
    segments = [s.strip() for s in re.split(r"[,\n]", addr or "") if s.strip()]
    if segments:
        last = segments[-1]
        last = re.sub(r"\b\d{5}\b", "", last).strip(" .,-")
        if 3 <= len(last) <= 40:
            facts.append(last)
    return facts


def norm_company(raw: str) -> str:
    """Company name as it appears in questions: title-cased, collapsed
    whitespace, no trailing punctuation."""
    s = re.sub(r"\s+", " ", (raw or "").strip()).strip(".,")
    return s.title() if s.isupper() else s


def norm_total(raw: str) -> str:
    """Totals in SROIE are Malaysian ringgit amounts in assorted shapes
    ('9.00', 'RM9.00', '$9.00'). Keep the numeric core."""
    m = re.search(r"(\d[\d,]*\.?\d*)", raw or "")
    return m.group(1).replace(",", "") if m else (raw or "").strip()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_split():
    from datasets import Image, load_dataset

    ds = load_dataset("jsdnrs/ICDAR2019-SROIE", split="test", revision=REVISION)
    # decode=False -> original bytes written verbatim (review #40): no second
    # lossy JPEG pass altering the pixels a visual retriever reads.
    ds_raw = ds.cast_column("image", Image(decode=False))
    rows = []
    for i, row in enumerate(ds_raw):
        rows.append({"i": i, **{k: row[k] for k in row.keys()}})
    return rows


def verify(corpus_dir: Path) -> int:
    """Re-hash the on-disk corpus against the committed manifest (review #41:
    the sha256s exist to be load-bearing, not decorative)."""
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    bad = 0
    for entry in manifest["files"]:
        p = corpus_dir / entry["name"]
        if not p.exists():
            print(f"MISSING {entry['name']}")
            bad += 1
        elif sha256_file(p) != entry["sha256"]:
            print(f"HASH MISMATCH {entry['name']}")
            bad += 1
    print(f"verify: {len(manifest['files']) - bad}/{len(manifest['files'])} files OK")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS))
    ap.add_argument("--verify", action="store_true",
                    help="re-hash the corpus against the committed manifest and exit")
    args = ap.parse_args()
    if args.verify:
        raise SystemExit(verify(Path(args.corpus_dir).expanduser()))
    corpus_dir = Path(args.corpus_dir).expanduser()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    rows = load_split()
    print(f"test split: {len(rows)} receipts; columns: {sorted(rows[0].keys() - {'i'})}")

    # Deterministic identity per row: prefer an explicit filename column if
    # the mirror has one, else the split index (stable for a fixed dataset
    # revision, which the manifest records).
    def row_key(r: dict) -> str:
        for k in ("key", "filename", "file_name", "id", "image_id"):
            if isinstance(r.get(k), str) and r[k]:
                return r[k]
        return f"idx{r['i']:05d}"

    rows.sort(key=row_key)
    corpus_rows, held_out = rows[:N_CORPUS], rows[N_CORPUS:]

    # --- write corpus images -------------------------------------------------
    manifest_files = []
    for r in corpus_rows:
        name = f"receipt_{row_key(r)}"
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        if not name.lower().endswith((".jpg", ".jpeg", ".png")):
            name += ".jpg"
        dest = corpus_dir / name
        img = r.get("image")
        if img is None:
            raise SystemExit(f"row {row_key(r)} has no image column")
        if not dest.exists():
            # decode=False rows carry the ORIGINAL bytes — written verbatim
            # (review #40: no second lossy encode altering retrieval pixels)
            raw = img.get("bytes") if isinstance(img, dict) else None
            if raw:
                dest.write_bytes(raw)
            else:  # fallback for rows without raw bytes
                pil = img if not isinstance(img, dict) else None
                if pil is None:
                    raise SystemExit(f"row {row_key(r)}: no bytes and no PIL image")
                pil = pil.convert("RGB") if pil.mode not in ("RGB", "L") else pil
                pil.save(dest, quality=95)
        r["_file"] = name
        manifest_files.append(name)

    for r in corpus_rows:  # hash after all writes so reruns are idempotent
        r["_sha"] = sha256_file(corpus_dir / r["_file"])

    # --- entity views --------------------------------------------------------
    def entities(r: dict) -> dict:
        e = r.get("entities") or {k: r.get(k) for k in ("company", "date", "address", "total")}
        return {k: (e.get(k) or "").strip() if isinstance(e.get(k), str) else e.get(k)
                for k in ("company", "date", "address", "total")}

    by_company: dict[str, list[dict]] = {}
    for r in corpus_rows:
        c = norm_company(entities(r)["company"])
        if c:
            by_company.setdefault(c, []).append(r)

    unique_companies = {c: rs[0] for c, rs in by_company.items() if len(rs) == 1}
    multi_companies = {c: rs for c, rs in by_company.items() if 2 <= len(rs) <= 5}

    # Held-out vendors for not_found items (review #42): exact-string absence
    # is not enough — OCR'd company labels vary ("X" vs "X SDN BHD"), so a
    # vendor could be present under a variant spelling. Require zero overlap
    # of significant tokens with ANY corpus company.
    corpus_tokens: set[str] = set()
    for c in by_company:
        corpus_tokens |= _company_tokens(c)
    held_out_companies = []
    for r in held_out:
        c = norm_company(entities(r)["company"])
        if not c or c in held_out_companies:
            continue
        toks = _company_tokens(c)
        if toks and not (toks & corpus_tokens):
            held_out_companies.append(c)

    golden: list[dict] = []

    def add(qid, question, answer_type, golden_answer, key_facts, gold_sources,
            difficulty, variants=None):
        golden.append({
            "id": qid,
            "question": question,
            "question_variants": variants or [],
            "answer_type": answer_type,
            "golden_answer": golden_answer,
            "key_facts": key_facts,
            "gold_sources": gold_sources,
            "acceptable_sources": [],
            "requires": {"visual_tier": True, "multi_file": len(gold_sources) > 1},
            "difficulty": difficulty,
            "human_verified": False,
            "generator": GENERATOR,
        })

    # --- extractive: totals (20), dates (12), addresses (10) -----------------
    # Raised from 10/8/7 (review #38): H1 is stated on extractive questions,
    # and at n=25 its CI was ±14 points — too wide for the stated threshold.
    uniq = sorted(unique_companies.items())
    picked_total = [(c, r) for c, r in uniq if norm_total(entities(r)["total"])][:20]
    rest = [(c, r) for c, r in uniq if (c, r) not in picked_total]
    picked_date = [(c, r) for c, r in rest if entities(r)["date"]][:12]
    rest = [(c, r) for c, r in rest if (c, r) not in picked_date]
    picked_addr = [(c, r) for c, r in rest
                   if entities(r)["address"] and address_facts(entities(r)["address"])][:10]

    for n, (c, r) in enumerate(picked_total, 1):
        e = entities(r)
        total = norm_total(e["total"])
        add(f"rcpt-total-{n:02d}",
            f"What was the total amount on the receipt from {c}?",
            "extractive", f"The total on the {c} receipt was {total}.",
            [total], [r["_file"]], "easy",
            variants=[f"{c.lower()} receipt total"])

    for n, (c, r) in enumerate(picked_date, 1):
        e = entities(r)
        add(f"rcpt-date-{n:02d}",
            f"On what date was the receipt from {c} issued?",
            "extractive", f"The {c} receipt is dated {e['date']}.",
            [e["date"]], [r["_file"]], "easy",
            variants=[f"when did i buy from {c.lower()}"])

    for n, (c, r) in enumerate(picked_addr, 1):
        e = entities(r)
        # atomic facts (postcode + locality), never the raw OCR string —
        # review #39: long OCR addresses fail exact-match and key_fact_spans
        # for formatting reasons, misattributing grading noise to scaffolding
        add(f"rcpt-addr-{n:02d}",
            f"What address is printed on the receipt from {c}?",
            "extractive", f"The {c} receipt shows the address: {e['address']}.",
            address_facts(e["address"]), [r["_file"]], "medium")

    # --- abstention: 6 held-out companies ------------------------------------
    for n, c in enumerate(held_out_companies[:6], 1):
        add(f"rcpt-absent-{n:02d}",
            f"What was the total amount on the receipt from {c}?",
            "not_found",
            f"No receipt from {c} exists in the files.",
            [], [], "medium")
        golden[-1]["review_note"] = (
            "founder-review priority: vendor absence established by "
            "token-overlap filtering of OCR labels; verify it is truly "
            "not in the corpus under any variant spelling"
        )

    # --- aggregation / enumeration over recurring companies ------------------
    agg = sorted(multi_companies.items())[:5]
    for n, (c, rs) in enumerate(agg, 1):
        files = [r["_file"] for r in rs]
        if n <= 3:
            add(f"rcpt-count-{n:02d}",
                f"How many receipts from {c} are in the files?",
                "enumeration", f"There are {len(rs)} receipts from {c}.",
                [str(len(rs))], files, "hard")
        else:
            dates = sorted({entities(r)["date"] for r in rs if entities(r)["date"]})
            add(f"rcpt-listdates-{n:02d}",
                f"List the dates of every receipt from {c}.",
                "enumeration",
                f"The {c} receipts are dated: {', '.join(dates)}.",
                dates, files, "hard")

    # --- write artifacts -----------------------------------------------------
    (DATASET_DIR / "golden.json").write_text(
        json.dumps(golden, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with (DATASET_DIR / "qrels.tsv").open("w", encoding="utf-8") as f:
        f.write("query-id\tcorpus-id\trelevance\n")
        for q in golden:
            for src in q["gold_sources"]:
                f.write(f"{q['id']}\t{src}\t2\n")
            for src in q["acceptable_sources"]:
                f.write(f"{q['id']}\t{src}\t1\n")

    (DATASET_DIR / "manifest.json").write_text(json.dumps({
        "dataset": "receipts",
        "source": "jsdnrs/ICDAR2019-SROIE (test split; CC-BY-4.0)",
        "source_revision": REVISION,
        "n_files": len(manifest_files),
        "selection": f"first {N_CORPUS} of test split under deterministic sort",
        "files": [{"name": r["_file"], "sha256": r["_sha"]} for r in corpus_rows],
        "golden_items": len(golden),
        "composition": {
            "extractive": sum(1 for q in golden if q["answer_type"] == "extractive"),
            "not_found": sum(1 for q in golden if q["answer_type"] == "not_found"),
            "enumeration": sum(1 for q in golden if q["answer_type"] == "enumeration"),
        },
    }, indent=2) + "\n", encoding="utf-8")

    (DATASET_DIR / "corpus_root.local.json").write_text(
        json.dumps({"corpus_root": str(corpus_dir)}, indent=2) + "\n", encoding="utf-8")

    print(f"corpus: {len(manifest_files)} images -> {corpus_dir}")
    print(f"golden: {len(golden)} items "
          f"({json.loads((DATASET_DIR / 'manifest.json').read_text())['composition']})")
    print(f"committed artifacts in {DATASET_DIR}")


if __name__ == "__main__":
    main()
