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
    currency-ish punctuation and collapses whitespace/case."""
    s = _norm_text(s)
    return s.replace(",", "").replace("rm", "").replace("$", "").strip()


def fact_in_text(fact: str, text: str) -> bool:
    f, t = _norm_fact(fact), _norm_fact(text)
    return bool(f) and f in t


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
    abstained = bool(row.get("not_found")) or not answer_text.strip()
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

        # observed prompt composition
        req = find_answer_request(reqs, row.get("question", "")) if reqs else None
        if req:
            ptext = req["text"]
            unknown = req["truncated_in_log"]
            in_prompt = {}
            for h in post_gate:
                base = Path(h["path"]).name
                present = base.casefold() in ptext.casefold()
                in_prompt[base] = "full" if present else ("unknown_log_truncated" if unknown else "absent")
            out["in_prompt"] = in_prompt
            spans = {}
            for i, f in enumerate(item.get("key_facts") or []):
                if fact_in_text(f, ptext):
                    spans[str(i)] = True
                else:
                    spans[str(i)] = "unknown_log_truncated" if unknown else False
            out["key_fact_spans"] = spans
        else:
            out["in_prompt"] = {}
            out["key_fact_spans"] = {}

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

    # H1 slice: extractive rows whose key facts were OBSERVED in the prompt
    h1_eligible = [
        e for e in extractive
        if e.get("key_fact_spans") and all(v is True for v in e["key_fact_spans"].values())
    ]
    h1 = {
        "n_extractive": len(extractive),
        "n_eligible_fact_in_prompt": len(h1_eligible),
        "eligible_fraction": rate(extractive, lambda e: e in h1_eligible),
        "accuracy_on_eligible": rate(h1_eligible, lambda e: e["verdict"] == "correct"),
        "note": "per-arm number; never compare raw across arms (PLAN H1)",
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
        "latency": {"p50_total_s": pct(0.50), "p95_total_s": pct(0.95)},
        "errors": sum(1 for e in enriched if e.get("error")),
    }


def _write_report(run_dir: Path, s: dict, enriched: list[dict], run_record: dict) -> None:
    lines = [
        f"# Eval report — {run_record.get('run_id', run_dir.name)}",
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
        f"- extractive n={s['h1_slice']['n_extractive']}, key-facts-in-prompt eligible "
        f"n={s['h1_slice']['n_eligible_fact_in_prompt']} "
        f"({s['h1_slice']['eligible_fraction']})",
        f"- accuracy on eligible: {s['h1_slice']['accuracy_on_eligible']}",
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
