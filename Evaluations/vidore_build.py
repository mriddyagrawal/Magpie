"""Turn a ViDoRe parquet into a Magpie corpus: page JPGs + eval JSON + criteria.

    python vidore_build.py <subset> <parquet> [<parquet> ...]
Writes /mnt/astavaknew/vidore/<subset>/{pages/*.jpg, gt_ocr/*.txt, eval_<subset>.json,
eval_<subset>_100.json, criteria.json}. Every row is a (query, page) pair; pages
repeat across rows, so the corpus is the set of distinct pages.
"""
import json, re, sys
from pathlib import Path
import pyarrow.parquet as pq

subset = sys.argv[1]
files = [a for a in sys.argv[2:] if not a.startswith("--")]
MAX_PAGES = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--max-pages=")), "100000"))
MAX_Q_PER_PAGE = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--max-q-per-page=")), "100000"))
q_per_page = {}
root = Path("/mnt/astavaknew/vidore") / subset
(root / "pages").mkdir(parents=True, exist_ok=True)
(root / "gt_ocr").mkdir(exist_ok=True)

questions, criteria = [], {"_note": f"ViDoRe {subset}: pre-registered strict criteria = the dataset's own answer, regex-escaped, thousands separators stripped; every element of a list answer must be present."}
seen_pages = set()
n = 0
for f in files:
    t = pq.read_table(f)
    cols = t.column_names
    for row in t.to_pylist():
        q = re.sub(r"\s*Keep it brief\.?\s*$", "", (row.get("query") or "").strip(), flags=re.I).strip()
        img = row.get("image") or {}
        data = img.get("bytes") if isinstance(img, dict) else None
        fname = row.get("image_filename") or f"page_{n:05d}.jpg"
        fname = re.sub(r"[^A-Za-z0-9._-]", "_", Path(fname).name)
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            fname += ".jpg"
        if fname not in seen_pages and len(seen_pages) >= MAX_PAGES:
            continue  # page cap reached: skip rows for pages not in the corpus
        if q_per_page.get(fname, 0) >= MAX_Q_PER_PAGE:
            continue
        q_per_page[fname] = q_per_page.get(fname, 0) + 1
        if data and fname not in seen_pages:
            (root / "pages" / fname).write_bytes(data)
            seen_pages.add(fname)
            ocr = row.get("ocr")
            if ocr:
                (root / "gt_ocr" / (fname + ".txt")).write_text(ocr if isinstance(ocr, str) else json.dumps(ocr), encoding="utf-8")
        if not q:
            continue
        ans = row.get("answer")
        if isinstance(ans, str) and ans.strip().startswith("["):
            import ast
            try: ans = json.loads(ans)
            except Exception:
                try: ans = ast.literal_eval(ans)
                except Exception: pass
        answers = [str(a).strip().rstrip(".").strip() for a in (ans if isinstance(ans, list) else [ans]) if a is not None and str(a).strip()]
        answers = [a for a in answers if a]
        # no answer (ViDoRe test splits withhold them): keep the query for the
        # retrieval-only score, write no criterion so the answer scorer skips it
        n += 1
        qid = f"q{n:03d}"
        questions.append({
            "id": qid, "question": q, "ground_truth": " | ".join(answers),
            "reasoning_type": ["single_doc", f"vidore_{subset}", str(row.get("answer_type") or "")],
            "key_files": [f"pages/{fname}"], "notes": f"ViDoRe {subset} row; source={row.get('source')}",
            "difficulty": "n/a",
        })
        if answers:
            pats = [re.escape(re.sub(r"(?<=\d),(?=\d)", "", a)) for a in answers]
            criteria[qid] = {"all": pats}

(root / f"eval_{subset}.json").write_text(json.dumps(questions, indent=1, ensure_ascii=False), encoding="utf-8")
(root / f"eval_{subset}_100.json").write_text(json.dumps(questions[:100], indent=1, ensure_ascii=False), encoding="utf-8")
(root / "criteria.json").write_text(json.dumps(criteria, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"{subset}: {len(seen_pages)} pages, {len(questions)} questions ({len(criteria)-1} with answers), gt_ocr={len(list((root/'gt_ocr').iterdir()))}; sample: {questions[0]['question'][:80]!r} -> {questions[0]['ground_truth'][:40]!r}")
