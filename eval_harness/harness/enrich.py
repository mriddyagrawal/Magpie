"""Post-run enrichment + deterministic scoring (PLAN.md §4.4, §5).

Everything here is observation and arithmetic — no LLM. The judge pass
(Phase 3) later appends binary verdicts to what this module emits.

Inputs (from runs/<id>/raw/): retrieve.jsonl (full pre-gate rankings),
answers.jsonl (pipeline-mode results), worker_answer.log ([query] stage
traces between [eval] sentinels), and the backend's own LLM JSONL log
(assembled prompts — the observed source for in_prompt / key_fact_spans).

Outputs (committed, runs/<id>/): answers_enriched.json, metrics.json,
report.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import metrics


# --- normalization ----------------------------------------------------------

def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").casefold()).strip()


def _norm_fact(s: str) -> str:
    """Facts are short strings (totals, dates, addresses). Comparison strips
    currency tokens and collapses whitespace/case. Currency is stripped as a
    TOKEN, never a substring (review #51: replace('rm','') turned PHARMACY
    into PHACY, silently raising vendor-collision odds — false positives in
    exactly the abstention slices)."""
    s = _norm_text(s)
    s = s.replace(",", "")
    s = re.sub(r"\brm\b\s*", "", s)
    s = s.replace("$", "")
    return s.strip()


_DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y",
    "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
)
_DATE_TOKEN_RE = re.compile(
    r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2} [A-Za-z]{3,9} \d{4}|[A-Za-z]{3,9} \d{1,2},? \d{4})\b"
)


def _parse_date(s: str):
    from datetime import datetime

    s = s.strip().replace(",", "")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fact_in_text(fact: str, text: str) -> bool:
    f, t = _norm_fact(fact), _norm_fact(text)
    if not f:
        return False
    if f in t:
        return True
    # Date-aware comparison (review #52): SROIE labels are OCR-formatted
    # (DD/MM/YYYY etc.); a model rendering the same date differently
    # ('2/1/2019', '02-01-2019') must still count. Parse both sides.
    gold_date = _parse_date(fact)
    if gold_date is not None:
        for m in _DATE_TOKEN_RE.finditer(text or ""):
            if _parse_date(m.group(0)) == gold_date:
                return True
    return False


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tiff", ".bmp"}


def _is_image_path(p: str) -> bool:
    return Path(p).suffix.lower() in _IMAGE_EXTS


# Deterministic prose-abstain detector: the model can decline in prose while
# the structured not_found flag stays False (observed live in smoke-02 —
# itself a product finding: the frontend would render a normal answer card
# instead of the not-found state). Conservative patterns; the judge refines.
_ABSTAIN_RE = re.compile(
    r"(is not found|was not found|not in the provided|no receipt|"
    r"does not exist|could ?n[o']t find|couldn't locate|no such file|"
    r"not available in the provided|do not contain|does not contain any)",
    re.IGNORECASE,
)


def prose_abstain(answer: str) -> bool:
    return bool(_ABSTAIN_RE.search(answer or ""))


# --- llm-log mining ---------------------------------------------------------

_TRUNC_MARKER = "[...truncated "


def _string_leaves(obj) -> list[str]:
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_string_leaves(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_string_leaves(v))
    return out


def load_llm_requests(llm_log_path: Path) -> list[dict]:
    """Request records with their prompt text flattened to one string."""
    reqs = []
    if not llm_log_path or not llm_log_path.exists():
        return reqs
    for line in llm_log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if rec.get("phase") != "request":
            continue
        text = "\n".join(
            _string_leaves(rec.get("messages")) + _string_leaves(rec.get("system_prompt"))
        )
        reqs.append({"text": text, "truncated_in_log": _TRUNC_MARKER in text})
    return reqs


def find_answer_request(reqs: list[dict], question: str) -> dict | None:
    """The answer-stage request for this question — identified by the prompt
    sandwich's closing echo ('Now answer this question: …'), which the
    rewrite request doesn't contain. Falls back to any request containing
    the question text plus file-block markers."""
    needle = _norm_text(f"Now answer this question: {question}")
    for r in reqs:
        if needle in _norm_text(r["text"]):
            return r
    qn = _norm_text(question)
    candidates = [r for r in reqs if qn in _norm_text(r["text"]) and "file:" in r["text"].casefold()]
    return candidates[-1] if candidates else None


# --- per-question stage latencies from the worker log -----------------------

def parse_stage_latencies(worker_log: Path) -> dict[str, dict]:
    """[eval] qa_id=X begin … [query] rewrite (1.23s) … retrieval (0.45s) …
    → {qa_id: {rewrite: s, retrieval: s}}"""
    out: dict[str, dict] = {}
    if not worker_log.exists():
        return out
    current: str | None = None
    for line in worker_log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r"\[eval\] qa_id=(\S+) begin", line)
        if m:
            current = m.group(1)
            out[current] = {}
            continue
        if current is None:
            continue
        m = re.search(r"\[query\] rewrite \(([\d.]+)s\)", line)
        if m:
            out[current]["rewrite"] = float(m.group(1))
        m = re.search(r"\[query\] retrieval \(([\d.]+)s\)", line)
        if m:
            out[current]["retrieval"] = float(m.group(1))
        if re.search(r"\[eval\] qa_id=\S+ end", line):
            current = None
    return out


# --- verdicts (deterministic component only) --------------------------------

def deterministic_verdict(item: dict, row: dict) -> dict:
    """Binary, rule-based scoring. The judge pass may OVERRIDE `verdict` for
    prose nuance; facts/citations/abstention are ground truth already."""
    answer_text = row.get("answer") or ""
    flag_abstain = bool(row.get("not_found")) or not answer_text.strip()
    prose = prose_abstain(answer_text)
    abstained = flag_abstain or prose
    facts = item.get("key_facts") or []
    facts_hit = [fact_in_text(f, answer_text) for f in facts]

    if item["answer_type"] == "not_found":
        verdict = "correct_abstain" if abstained else "false_answer"
    elif abstained:
        verdict = "false_abstain"
    elif facts and all(facts_hit):
        verdict = "correct"
    elif facts and any(facts_hit):
        verdict = "partial"
    else:
        verdict = "wrong"
    return {
        "verdict": verdict,
        "facts_total": len(facts),
        "facts_matched": sum(facts_hit),
        "abstained": abstained,
        "abstain_source": ("flag" if flag_abstain else "prose" if prose else None),
        # flag/prose disagreement is a product signal, not just scoring detail
        "not_found_flag_missing": prose and not flag_abstain,
    }


# --- main entry -------------------------------------------------------------

def enrich_run(run_dir: Path, golden: list[dict], params: dict) -> dict:
    raw = run_dir / "raw"
    by_id = {q["id"]: q for q in golden}

    retrieve_rows = _load_jsonl(raw / "retrieve.jsonl")
    answer_rows = _load_jsonl(raw / "answers.jsonl")
    stage_lat = parse_stage_latencies(raw / "worker_answer.log")

    llm_log = None
    result_file = raw / "worker_answer_result.json"
    if result_file.exists():
        llm = json.loads(result_file.read_text()).get("llm_log")
        llm_log = Path(llm) if llm else None
    reqs = load_llm_requests(llm_log) if llm_log else []

    ranked_by_id = {r["qa_id"]: r for r in retrieve_rows}
    enriched: list[dict] = []

    for row in answer_rows:
        qa_id = row["qa_id"]
        item = by_id.get(qa_id)
        if item is None:
            continue
        qrels = {p: 2 for p in item.get("gold_sources", [])}
        qrels.update({p: 1 for p in item.get("acceptable_sources", [])})

        out = dict(row)
        out["answer_type"] = item["answer_type"]

        # retrieval metrics from the PRE-gate retrieve pass
        ret = ranked_by_id.get(qa_id)
        ranked_paths = [h["path"] for h in (ret or {}).get("ranked", [])]
        if qrels and ranked_paths:
            out["retrieval"] = metrics.retrieval_row(ranked_paths, qrels)
        out["ranked_pre_gate"] = len(ranked_paths)

        # solo gate: observed as pipeline list collapsing to 1 while the
        # pre-gate ranking had more (local provider only, by construction)
        post_gate = row.get("retrieved") or []
        out["solo_gated"] = (
            params.get("provider") == "local"
            and len(post_gate) == 1
            and len(ranked_paths) >= 2
        )
        if out["solo_gated"] and len(ranked_paths) >= 2 and ret:
            r0, r1 = ret["ranked"][0], ret["ranked"][1]
            out["solo_margin_observed"] = round(r0["score"] - r1["score"], 3)
            # self-validation (review #46): the gate inference is a heuristic
            # over two separate passes; require the margin the gate itself
            # keys on to corroborate, and flag when it doesn't.
            try:
                out["gate_inference_disagreement"] = (
                    out["solo_margin_observed"] < float(params.get("solo_margin", 2.0))
                )
            except (TypeError, ValueError):
                out["gate_inference_disagreement"] = None

        # observed prompt composition — from the backend's OWN markers, not
        # bare filename presence (review #44: the "--- File N: <path> ---"
        # header AND the omitted-files context note both name files whose
        # content was cut, so filename presence alone reads truncated and
        # dropped files as "full", emptying §5's budget-fault class).
        req = find_answer_request(reqs, row.get("question", "")) if reqs else None
        if req:
            ptext = req["text"]
            unknown = req["truncated_in_log"]
            # split into per-file blocks on the exact header answer.py emits
            # (answer.py:742: "--- File {i}: {display} ---")
            header_re = re.compile(r"--- File \d+: (.+?) ---")
            blocks: dict[str, str] = {}
            matches = list(header_re.finditer(ptext))
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(ptext)
                blocks[Path(m.group(1).strip()).name.casefold()] = ptext[m.start():end]
            # files named by the omitted-note (answer.py:141-142)
            omitted_note = re.search(
                r"\(Context note: \d+ lower-ranked source file\(s\) were omitted[^)]*\)",
                ptext,
            )
            omitted_text = omitted_note.group(0).casefold() if omitted_note else ""

            def classify(path: str) -> str:
                base = Path(path).name.casefold()
                block = blocks.get(base)
                if block is not None:
                    if "…(truncated to fit the local model's context window)" in block:
                        return "truncated"
                    return "full"
                if base in omitted_text:
                    return "dropped"
                return "unknown_log_truncated" if unknown else "absent"

            in_prompt = {Path(h["path"]).name: classify(h["path"]) for h in post_gate}
            # pre-gate files the solo gate excluded never reached the prompt
            if params.get("provider") == "local" and len(post_gate) == 1:
                post_names = {Path(h["path"]).name for h in post_gate}
                for h in (ret or {}).get("ranked", [])[: int(params.get("top_k", 5))]:
                    name = Path(h["path"]).name
                    if name not in post_names and name not in in_prompt:
                        in_prompt[name] = "solo_excluded"
            out["in_prompt"] = in_prompt
            # Fact-span observability only exists for TEXT blocks. When the
            # gold sources are images, the prompt carries pixels the log
            # can't expose — fact presence is undecidable, not false
            # (smoke-02: every span read false and H1's eligible set was
            # empty on a dataset where retrieval was perfect).
            gold_all_images = bool(item.get("gold_sources")) and all(
                _is_image_path(p) for p in item["gold_sources"]
            )
            spans = {}
            for i, f in enumerate(item.get("key_facts") or []):
                if fact_in_text(f, ptext):
                    spans[str(i)] = True
                elif gold_all_images:
                    spans[str(i)] = "unknown_image_block"
                else:
                    spans[str(i)] = "unknown_log_truncated" if unknown else False
            out["key_fact_spans"] = spans
            # H1 eligibility basis (PLAN H1): fact-level when observable;
            # file-level fallback for image gold sources.
            gold_in_prompt_full = bool(item.get("gold_sources")) and all(
                in_prompt.get(Path(p).name) == "full" for p in item["gold_sources"]
            )
            if spans and all(v is True for v in spans.values()):
                out["h1_eligible"], out["h1_basis"] = True, "fact_spans"
            elif gold_all_images and gold_in_prompt_full:
                out["h1_eligible"], out["h1_basis"] = True, "file_level_image"
            else:
                out["h1_eligible"], out["h1_basis"] = False, None
        else:
            out["in_prompt"] = {}
            out["key_fact_spans"] = {}
            out["h1_eligible"], out["h1_basis"] = False, None

        # citations + verdict
        cited = row.get("cited") or []
        if qrels:
            out["citations"] = metrics.citation_scores(cited, qrels)
        out.update(deterministic_verdict(item, row))

        # stage latencies
        lat = dict(row.get("latency_s") or {})
        lat.update(stage_lat.get(qa_id, {}))
        if "total" in lat:
            known = sum(v for k, v in lat.items() if k not in ("total",))
            lat["generation_approx"] = round(max(0.0, lat["total"] - known), 2)
        out["latency_s"] = lat

        enriched.append(out)

    summary = _summarize(enriched, params)
    # Review #58: phases and enrichment can run under different harness
    # versions (enrichment is re-runnable by design); both must be stamped
    # or the archive is uninterpretable.
    try:
        import subprocess as _sp
        summary["enriched_at_sha"] = _sp.run(
            ["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        summary["enriched_at_sha"] = "unknown"
    # Silver-golden gate (reviewer note on ad18e5a): headline numbers from an
    # unverified golden set are provisional and must say so everywhere.
    n_unverified = sum(1 for q in golden if not q.get("human_verified"))
    summary["golden_set"] = {
        "items": len(golden),
        "human_verified": len(golden) - n_unverified,
        "status": "GOLD" if n_unverified == 0 else "SILVER (provisional)",
    }
    envs = _load_json(run_dir / "run.json")
    _write_report(run_dir, summary, enriched, envs)
    _dump(run_dir / "answers_enriched.json", enriched)
    _dump(run_dir / "metrics.json", summary)
    return summary


def _summarize(enriched: list[dict], params: dict) -> dict:
    answerable = [e for e in enriched if e["answer_type"] != "not_found"]
    notfound = [e for e in enriched if e["answer_type"] == "not_found"]
    extractive = [e for e in enriched if e["answer_type"] == "extractive"]

    def rate(rows, pred) -> float | None:
        return round(sum(1 for r in rows if pred(r)) / len(rows), 3) if rows else None

    retrieval_agg = metrics.aggregate([e["retrieval"] for e in answerable if e.get("retrieval")])
    citation_agg = metrics.aggregate([e["citations"] for e in answerable if e.get("citations")])

    # H1 slice: eligibility observed per row (fact-level for text gold,
    # file-level for image gold — see enrich_run). Review #50: the two bases
    # measure DIFFERENT claims (fact was available vs right image was shown),
    # so a combined number is refused whenever both bases occur; per-basis
    # accuracies are always reported and must never be pooled or compared
    # across bases.
    h1_eligible = [e for e in extractive if e.get("h1_eligible")]
    basis_counts = {
        b: sum(1 for e in h1_eligible if e.get("h1_basis") == b)
        for b in ("fact_spans", "file_level_image")
    }
    mixed_basis = sum(1 for v in basis_counts.values() if v) > 1
    per_basis_acc = {
        b: rate([e for e in h1_eligible if e.get("h1_basis") == b],
                lambda e: e["verdict"] == "correct")
        for b, n in basis_counts.items() if n
    }
    h1 = {
        "n_extractive": len(extractive),
        "n_eligible": len(h1_eligible),
        "eligible_fraction": rate(extractive, lambda e: e in h1_eligible),
        "basis_counts": basis_counts,
        "accuracy_by_basis": per_basis_acc,
        "accuracy_on_eligible": (
            None if mixed_basis
            else rate(h1_eligible, lambda e: e["verdict"] == "correct")
        ),
        "mixed_basis": mixed_basis,
        "note": "per-arm number; never compare raw across arms OR across "
                "bases (PLAN H1). accuracy_on_eligible is None when bases "
                "are mixed - use accuracy_by_basis.",
    }

    product_findings = {
        "not_found_flag_missing": sum(1 for e in enriched if e.get("not_found_flag_missing")),
        "zero_citation_answers": sum(
            1 for e in answerable
            if not (e.get("cited")) and e["verdict"] in ("correct", "partial", "wrong")
        ),
    }

    lat_totals = sorted(
        e["latency_s"].get("total", 0.0) for e in enriched if e.get("latency_s")
    )

    def pct(p: float):
        if not lat_totals:
            return None
        return round(lat_totals[min(len(lat_totals) - 1, int(p * len(lat_totals)))], 1)

    return {
        "n_questions": len(enriched),
        "answer": {
            "correct": rate(answerable, lambda e: e["verdict"] == "correct"),
            "partial": rate(answerable, lambda e: e["verdict"] == "partial"),
            "wrong": rate(answerable, lambda e: e["verdict"] == "wrong"),
            "false_abstain": rate(answerable, lambda e: e["verdict"] == "false_abstain"),
            "by_type": {
                t: rate([e for e in answerable if e["answer_type"] == t],
                        lambda e: e["verdict"] == "correct")
                for t in sorted({e["answer_type"] for e in answerable})
            },
        },
        "abstention": {
            "n_not_found": len(notfound),
            "correct_abstain_rate": rate(notfound, lambda e: e["verdict"] == "correct_abstain"),
            "false_answer_rate": rate(notfound, lambda e: e["verdict"] == "false_answer"),
        },
        "retrieval": retrieval_agg,
        "citations": citation_agg,
        "solo_gate": {
            "fire_rate": rate(enriched, lambda e: e.get("solo_gated")),
        },
        "h1_slice": h1,
        "product_findings": product_findings,
        "latency": {"p50_total_s": pct(0.50), "p95_total_s": pct(0.95)},
        "errors": sum(1 for e in enriched if e.get("error")),
    }


def _write_report(run_dir: Path, s: dict, enriched: list[dict], run_record: dict) -> None:
    gs = s.get("golden_set", {})
    silver_banner = (
        []
        if gs.get("status") == "GOLD"
        else [
            "",
            f"> ⚠️ **{gs.get('status', 'SILVER')} golden set** — "
            f"{gs.get('human_verified', 0)}/{gs.get('items', '?')} items human-verified. "
            "Every number below is provisional until both founders complete the "
            "silver→gold review (PLAN §6). Do not act on H1 or publish these figures.",
        ]
    )
    lines = [
        f"# Eval report — {run_record.get('run_id', run_dir.name)}",
        *silver_banner,
        "",
        f"Config `{run_record.get('config_name')}` · dataset `{run_record.get('dataset')}` · "
        f"{s['n_questions']} questions · backend `{str(run_record.get('backend_git_sha'))[:12]}`",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Correct (answerable, deterministic) | {s['answer']['correct']} |",
        f"| Partial | {s['answer']['partial']} |",
        f"| Wrong | {s['answer']['wrong']} |",
        f"| False abstain | {s['answer']['false_abstain']} |",
        f"| Correct abstain (of {s['abstention']['n_not_found']} not_found) | {s['abstention']['correct_abstain_rate']} |",
        f"| False answer on not_found | {s['abstention']['false_answer_rate']} |",
        f"| hit@5 | {s['retrieval'].get('hit@5')} |",
        f"| recall@12 | {s['retrieval'].get('recall@12')} |",
        f"| MRR | {s['retrieval'].get('mrr')} |",
        f"| nDCG@5 | {s['retrieval'].get('ndcg@5')} |",
        f"| Citation precision / recall | {s['citations'].get('citation_precision')} / {s['citations'].get('citation_recall')} |",
        f"| Solo-gate fire rate | {s['solo_gate']['fire_rate']} |",
        f"| Latency p50 / p95 (s) | {s['latency']['p50_total_s']} / {s['latency']['p95_total_s']} |",
        "",
        "## H1 slice (per-arm; never compare raw across arms)",
        "",
        f"- extractive n={s['h1_slice']['n_extractive']}, eligible "
        f"n={s['h1_slice']['n_eligible']} ({s['h1_slice']['eligible_fraction']}) "
        f"— basis: {s['h1_slice']['basis_counts']}",
        f"- accuracy by basis: {s['h1_slice']['accuracy_by_basis']} "
        + ("(mixed bases — no combined number; bases measure different claims)"
           if s['h1_slice']['mixed_basis'] else
           f"| combined: {s['h1_slice']['accuracy_on_eligible']}"),
        "",
        "## Product findings (deterministic observations, not verdicts)",
        "",
        f"- answers that abstained in prose while the structured not_found flag "
        f"stayed False: {s['product_findings']['not_found_flag_missing']}",
        f"- non-abstain answers returned with ZERO cited sources: "
        f"{s['product_findings']['zero_citation_answers']}",
        "",
        "## Failures (deterministic verdicts)",
        "",
    ]
    for e in enriched:
        if e["verdict"] in ("correct", "correct_abstain"):
            continue
        r = e.get("retrieval") or {}
        lines.append(
            f"- **{e['qa_id']}** [{e['verdict']}] hit@5={r.get('hit@5')} "
            f"gate={e.get('solo_gated')} facts={e.get('facts_matched')}/{e.get('facts_total')} "
            f"err={e.get('error') or '-'}"
        )
    lines.append("")
    lines.append("_Deterministic scoring only; judge pass (Phase 3) refines prose verdicts._")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            pass
    return rows


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _dump(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
